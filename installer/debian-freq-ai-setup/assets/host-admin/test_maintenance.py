import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent/'board-system/lib'))
import broker as b
import maintenance
import storage_budget as storage
import freq_board as board
import freq_board_transaction as tx
import board_maintenance


class ScopedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'private').mkdir()
        self.p=patch.object(b,'ROOT',self.root);self.p.start()

    def tearDown(self):self.p.stop();self.temp.cleanup()

    def test_legacy_all_cannot_authorize_new_capabilities(self):
        state={'grants':{'jarvis':list(b.CAPS)},'grant_uids':{'jarvis':1001}}
        with self.assertRaisesRegex(ValueError,'not granted'):
            maintenance.authorize(b,state,'jarvis',1001,'board-maintenance','project:PVE-FREQ',False)

    def test_expiry_uid_and_scope_are_enforced(self):
        state={'maintenance_grants':{'jarvis':{'board-maintenance':{'uid':1001,'scope':'project:PVE-FREQ','until':None}}}}
        maintenance.authorize(b,state,'jarvis',1001,'board-maintenance','project:PVE-FREQ',False)
        for uid,scope in ((1002,'project:PVE-FREQ'),(1001,'project:OTHER')):
            with self.assertRaises(ValueError):maintenance.authorize(b,state,'jarvis',uid,'board-maintenance',scope,False)
        state['maintenance_grants']['jarvis']['board-maintenance']['until']=1
        with self.assertRaises(ValueError):maintenance.authorize(b,state,'jarvis',1001,'board-maintenance','project:PVE-FREQ',False)

    def test_reason_repair_plan_is_bound_and_preserves_original(self):
        project=self.root/'board/projects/TEST'
        for status in board.STATUSES:(project/status).mkdir(parents=True)
        task=project/'blocked/Review.md'
        task.write_text('# Review\n\n- Assigned to: `finn`\n\nOriginal evidence\n')
        before=task.read_bytes()
        intent={'project':'TEST','task':'Review','responsibility':'finn','reason':'Owner confirmed blocker',
                'source_message':'owner-message.md','provenance':'Current owner confirmation','intended_state':'blocked'}
        r={'area':'board-maintenance','action':'plan','project':'TEST','task':'Review',
           'expected_revision':tx.revision(project,task),'intent':intent,'incident':'fixture'}
        with patch.dict(os.environ,{'FREQ_BOARD_TESTING':'1','FREQ_BOARD_ROOT':str(self.root/'board'),'FREQ_BOARD_AGENT':'root'}):
            plan=board_maintenance.dispatch(b,r,'root',True)
            self.assertEqual(task.read_bytes(),before)
            apply={'area':'board-maintenance','action':'apply','plan':plan['plan_id'],'expected_plan_sha256':'0'*64,'approval':'fixture'}
            with self.assertRaises(ValueError):board_maintenance.dispatch(b,apply,'root',True)
            apply['expected_plan_sha256']=plan['sha256']
            with patch.object(b,'load',return_value={}),self.assertRaises(ValueError):
                board_maintenance.dispatch(b,apply,'jarvis',False)
            result=board_maintenance.dispatch(b,apply,'root',True)
            self.assertEqual(board.blocked_reason(task),intent['reason'])
            self.assertEqual(Path(result['backup']).read_bytes(),before)
            self.assertEqual(result['responsibility'],'finn')
            self.assertTrue(board_maintenance.dispatch(b,apply,'root',True)['replayed'])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.base=self.root/'projects';self.output=self.base/'TEST/run';self.output.mkdir(parents=True)
        self.patch=patch.object(storage,'BASE',self.base);self.patch.start()
        self.budget=storage.Budget(self.root/'budget.db')
        self.cap={'effective_free':100*storage.GIB,'effective_inodes':1000000}
        self.capacity=patch.object(self.budget,'capacity',return_value=self.cap);self.capacity.start()

    def tearDown(self):self.capacity.stop();self.budget.close();self.patch.stop();self.temp.cleanup()

    def request(self):return {'area':'storage-budget','action':'reserve','project':'TEST','run':'run','output':str(self.output),
                            'estimated_output_bytes':storage.GIB,'estimated_inodes':1000,'policy':storage.POLICY,'idempotency_key':'key'}

    def test_idempotency_ownership_revision_and_no_expiry_release(self):
        r=self.request();row=self.budget.handle(r,'finn',1001)
        self.assertEqual(self.budget.handle(r,'finn',1001)['id'],row['id'])
        operation={'action':'release','reservation':row['id'],'expected_revision':1}
        with self.assertRaises(PermissionError):self.budget.handle(operation,'jarvis',1002)
        with self.assertRaises(ValueError):self.budget.handle(dict(operation,expected_revision=2),'finn',1001)
        with self.assertRaisesRegex(ValueError,'Expiry is not liveness'):
            self.budget.handle(dict(operation,action='recover-stale'),'finn',1001)
        self.assertEqual(self.budget.handle(operation,'finn',1001)['state'],'RELEASED')

    def test_capacity_floor_is_strict_and_inode_aware(self):
        for cap in ({'effective_free':12*storage.GIB,'effective_inodes':10000},
                    {'effective_free':100*storage.GIB,'effective_inodes':2000}):
            self.cap.update(cap)
            with self.assertRaisesRegex(ValueError,'Insufficient'):self.budget.handle(self.request(),'finn',1001)
        self.assertEqual(self.budget.db.execute('SELECT count(*) FROM reservations').fetchone()[0],0)

    def test_overlap_and_symlink_substitution_refused(self):
        self.budget.handle(self.request(),'finn',1001)
        child=self.output/'child';child.mkdir()
        with self.assertRaisesRegex(ValueError,'overlaps'):
            self.budget.handle(dict(self.request(),output=str(child),idempotency_key='two'),'jarvis',1002)
        alias=self.base/'TEST/alias';alias.symlink_to(self.output)
        with self.assertRaises(OSError):storage.open_output(str(alias))

    def test_consumption_underestimate_retains_commitment(self):
        r=self.request();r['estimated_output_bytes']=100
        row=self.budget.handle(r,'finn',1001)
        (self.output/'result').write_bytes(b'x'*4096)
        result=self.budget.handle({'action':'renew','reservation':row['id'],'expected_revision':1},'finn',1001)
        self.assertEqual(result['state'],'SAFE_BOUNDARY_STOP_REQUIRED')
        self.assertTrue(result['commitment_retained'])

    def test_concurrent_reservations_have_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        self.capacity.stop()
        other=self.base/'TEST/other';other.mkdir()
        fake=type('FS',(),{'f_bavail':14*storage.GIB,'f_frsize':1,'f_favail':1000000})()
        def reserve(number):
            budget=storage.Budget(self.root/'budget.db')
            try:
                request=dict(self.request(),output=str(self.output if number==0 else other),idempotency_key=str(number))
                try:budget.handle(request,'finn',1001);return 'RESERVED'
                except ValueError:return 'REFUSED'
            finally:budget.close()
        with patch.object(storage.os,'fstatvfs',return_value=fake),ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,(0,1)))
        self.assertEqual(sorted(results),['REFUSED','RESERVED'])


if __name__=='__main__':unittest.main()
