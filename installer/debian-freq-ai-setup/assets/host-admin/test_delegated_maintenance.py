import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'board-system/lib'))
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'coms-system/lib'))
import board_worker as worker
import freq_board as board
import freq_board_transaction as tx
from freq_board_inspect import inspect
import broker as b
import board_api
import coms_maintenance as coms
import tooling

class BoardRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.project=self.root/'projects/TEST'
        for s in board.STATUSES:(self.project/s).mkdir(parents=True)
        (self.project/'active/jarvis').mkdir();self.task=self.project/'active/jarvis/Task.md';self.task.write_text('# Task\n')
        self.env=patch.dict(os.environ,FREQ_BOARD_TESTING='1',FREQ_BOARD_ROOT=str(self.root),FREQ_BOARD_AGENT='jarvis');self.env.start();tx.CONTEXT.clear()
    def tearDown(self):self.env.stop();tx.CONTEXT.clear();self.temp.cleanup()
    def interrupt(self,stage):
        with patch.dict(os.environ,FREQ_BOARD_FAULT=stage),self.assertRaises(OSError):
            tx.transition(self.project,board.task_location(self.project,self.task),'blocked',board.set_blocked_reason(self.task.read_text(),'Fixture'))
        return next((self.project/'.transactions').iterdir()).name
    def test_unprepared_closure_preserves_bytes_and_clears_pending(self):
        op=self.interrupt('after_before_image');original=self.task.read_bytes()
        plan=worker.handle({'action':'plan','project':'TEST','operation':op})
        self.assertEqual(plan['action'],'CLOSE_UNPREPARED')
        result=worker.handle({'action':'apply','project':'TEST','operation':op,'plan':plan,'approval':'fixture'})
        self.assertEqual(result['state'],'ABORTED_BEFORE_PREPARE');self.assertEqual(self.task.read_bytes(),original)
        self.assertTrue((self.project/'.transactions'/op/'before.bin').exists())
        self.assertEqual(inspect(self.project)['pending_operations'],[])
        self.assertTrue(worker.handle({'action':'apply','project':'TEST','operation':op,'plan':plan,'approval':'fixture'})['replayed'])
    def test_stale_plan_and_tampered_closure_fail(self):
        op=self.interrupt('after_before_image');plan=worker.handle({'action':'plan','project':'TEST','operation':op})
        image=self.project/'.transactions'/op/'before.bin';image.write_text('drift')
        with self.assertRaisesRegex(ValueError,'Stale'):worker.handle({'action':'apply','project':'TEST','operation':op,'plan':plan,'approval':'fixture'})
        self.assertFalse((image.parent/'aborted.json').exists())
    def test_prepared_recovery_commits_without_notifications(self):
        op=self.interrupt('after_prepare');plan=worker.handle({'action':'plan','project':'TEST','operation':op})
        result=worker.handle({'action':'apply','project':'TEST','operation':op,'plan':plan,'approval':'fixture'})
        self.assertEqual(result['state'],'COMMITTED');self.assertFalse(self.task.exists())
        self.assertEqual(board.blocked_reason(self.project/'blocked/Task.md'),'Fixture')
    def test_notification_uncertainty_is_not_a_recovery_replay(self):
        op=self.interrupt('after_prepare');tx.recover(self.project)
        tx.atomic(self.project/'.transactions'/op/'notification.json',b'{"state":"UNCERTAIN"}')
        with self.assertRaisesRegex(ValueError,'notification'):worker.handle({'action':'plan','project':'TEST','operation':op})
    def test_validation_paginates_without_reason_bodies(self):
        for n in range(60):(self.project/'ready'/f'T{n}.md').write_text('# Task')
        r=worker.handle({'action':'validate','project':'TEST','cursor':0,'limit':10})
        self.assertEqual(r['total'],61);self.assertEqual(r['next_cursor'],10);self.assertEqual(len(r['tasks']),10)
    def test_api_denies_ungranted_before_worker(self):
        with patch.object(board_api,'worker') as call,self.assertRaises(ValueError):
            board_api.dispatch(b,{}, {'action':'validate','project':'TEST'},'jarvis',1001,False)
        call.assert_not_called()

class ComsBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.sender=b.pwd.getpwuid(os.geteuid()).pw_name;self.ident=str(uuid.uuid4())
        self.folder=self.root/self.sender/'receipts';self.folder.mkdir(parents=True)
        self.value={'message_id':self.ident,'sender':self.sender,'sender_uid':os.geteuid(),'recipient':'jarvis','state':'NOT_STORED','revision':1,'body':'secret fixture body'}
        (self.folder/(self.ident+'.json')).write_text(json.dumps(self.value))
        self.p=patch.object(coms,'COMS',self.root);self.p.start()
    def tearDown(self):self.p.stop();self.temp.cleanup()
    def test_metadata_omits_body(self):self.assertNotIn('body',coms.receipt(self.sender,self.ident))
    def test_intermediate_symlink_is_refused(self):
        self.folder.rename(self.root/'moved');self.folder.symlink_to(self.root/'moved')
        with self.assertRaises(OSError):coms.receipt(self.sender,self.ident)
    def test_hardlinked_receipt_is_refused(self):
        os.link(self.folder/(self.ident+'.json'),self.root/'link')
        with self.assertRaisesRegex(ValueError,'Unsafe'):coms.receipt(self.sender,self.ident)
    def test_unrelated_actor_cannot_inspect_private_receipt(self):
        with patch.object(coms,'lookup',return_value=self.value),patch.object(b,'agents',return_value=[self.sender]),self.assertRaisesRegex(ValueError,'private'):
            coms.dispatch(b,{'area':'coms-status','message':self.ident},'clancy',1002,False,{})
    def test_uncertain_post_refuses_retry(self):
        value={**self.value,'downstream_state':'DELIVERY_UNCERTAIN'}
        state={'maintenance_grants':{'jarvis':{'coms-maintenance':{'uid':1001,'scope':'coms:shared','approval':'fixture','until':None}}}}
        with patch.object(coms,'lookup',return_value=value),patch.object(b,'agents',return_value=[]),self.assertRaisesRegex(ValueError,'uncertain'):
            coms.dispatch(b,{'area':'coms-maintenance','action':'retry','message':self.ident,'expected_revision':1,'approval':'fixture'},'jarvis',1001,False,state)

class ToolingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'private/tooling').mkdir(parents=True)
        self.code=self.root/'tool.py';self.code.write_text('VALUE=1\n');self.code.chmod(0o644)
        self.patches=[patch.object(b,'ROOT',self.root),patch.object(tooling,'TARGETS',{'board':{str(self.code)}})]
        for p in self.patches:p.start()
        self.before=tooling.image(self.code);after={**self.before,'body':base64.b64encode(b'VALUE=2\n').decode(),'sha256':tooling.sha(b'VALUE=2\n')}
        self.release={'schema':1,'compatible_schema':1,'component':'board','approved_for':['jarvis'],'review':'fixture','files':{str(self.code):after}}
        (self.root/'private/tooling/release-fixture.json').write_text(json.dumps(self.release))
        self.state={'maintenance_grants':{'jarvis':{'tooling-maintenance':{'uid':1001,'scope':'component:board-coms','approval':'fixture','until':None}}}}
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def call(self,verb,**kw):return tooling.dispatch(b,self.state,{'area':'host','action':'tooling','verb':verb,**kw},'jarvis',1001,False)
    def test_reviewed_deploy_and_revision_checked_rollback(self):
        plan=self.call('plan',release='fixture');job=self.call('apply',plan=plan['plan'],expected_plan_sha256=plan['sha256'],approval='fixture')
        self.assertEqual(job['state'],'COMMITTED');self.assertEqual(self.code.read_text(),'VALUE=2\n')
        self.assertEqual(self.call('rollback',job=job['job'],approval='fixture')['state'],'ROLLED_BACK')
        self.assertEqual(tooling.image(self.code),self.before)
    def test_stale_digest_and_revocation_refuse(self):
        plan=self.call('plan',release='fixture')
        with self.assertRaises(ValueError):self.call('apply',plan=plan['plan'],expected_plan_sha256='0'*64,approval='fixture')
        self.state['maintenance_grants']={}
        with self.assertRaises(ValueError):self.call('apply',plan=plan['plan'],expected_plan_sha256=plan['sha256'],approval='fixture')
        self.assertEqual(tooling.image(self.code),self.before)
    def test_arbitrary_broker_target_refused(self):
        self.release['files']={'/usr/local/libexec/freq-ai-setup/host-admin/broker.py':self.before}
        (self.root/'private/tooling/release-fixture.json').write_text(json.dumps(self.release))
        with self.assertRaisesRegex(ValueError,'target set'):self.call('plan',release='fixture')
    def test_verify_compares_installed_code_with_reviewed_release(self):
        self.assertFalse(self.call('verify')['components']['board']['verified'])
        plan=self.call('plan',release='fixture');self.call('apply',plan=plan['plan'],expected_plan_sha256=plan['sha256'],approval='fixture')
        self.assertTrue(self.call('verify')['components']['board']['verified'])
    def test_failed_verification_restores_before_image(self):
        plan=self.call('plan',release='fixture')
        with patch.object(tooling,'check_code',side_effect=ValueError('post verify failure')),self.assertRaises(ValueError):
            self.call('apply',plan=plan['plan'],expected_plan_sha256=plan['sha256'],approval='fixture')
        self.assertEqual(tooling.image(self.code),self.before)

if __name__=='__main__':unittest.main()
