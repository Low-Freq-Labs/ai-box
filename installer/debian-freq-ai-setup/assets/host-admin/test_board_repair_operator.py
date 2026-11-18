import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'board-system/lib'))
import board_repair_operator as repair
import board_maintenance
import freq_board as board
import freq_board_transaction as tx
import broker

class OperatorRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.project=self.root/'projects/TEST'
        for status in board.STATUSES:(self.project/status).mkdir(parents=True)
        self.task=self.project/'blocked/Review.md'
        self.task.write_text('# Review\n\n- Assigned to: `finn`\n\nPreserved evidence\n');self.task.chmod(0o660)
        self.before=self.task.read_bytes()
        intent={'project':'TEST','task':'Review','responsibility':'finn','intended_state':'blocked',
                'reason':'Owner confirmed','source_message':'owner.md','provenance':'Current wording'}
        with patch.object(broker,'ROOT',self.root/'admin'),patch.dict(os.environ,{'FREQ_BOARD_TESTING':'1','FREQ_BOARD_ROOT':str(self.root)}):
            self.plan=board_maintenance.dispatch(broker,{'area':'board-maintenance','action':'plan','project':'TEST','task':'Review',
                'expected_revision':tx.revision(self.project,self.task),'intent':intent,'incident':'fixture'},'root',True)
        self.patches=[patch.object(repair,'BOARD',self.root/'projects'),patch.object(repair,'PRIVATE',self.root/'backups')]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def execute(self,apply=True):return repair.execute(self.plan,self.plan['sha256'],'fixture-approval',apply)

    def test_dry_run_then_apply_preserves_bytes_metadata_and_idempotency(self):
        meta=self.task.stat();self.assertEqual(self.execute(False)['state'],'DRY_RUN')
        self.assertFalse((self.root/'backups').exists());self.assertEqual(self.task.read_bytes(),self.before)
        result=self.execute();self.assertEqual(result['state'],'COMMITTED')
        self.assertEqual(Path(result['backup']).read_bytes(),self.before)
        after=self.task.stat();self.assertEqual((meta.st_uid,meta.st_gid,meta.st_mode),(after.st_uid,after.st_gid,after.st_mode))
        self.assertEqual(board.blocked_reason(self.task),'Owner confirmed')
        self.assertTrue(self.execute()['replayed'])

    def test_stale_revision_and_bad_digest_do_not_write_task(self):
        with self.assertRaisesRegex(ValueError,'digest'):
            repair.execute(self.plan,'0'*64,'fixture',True)
        self.task.write_text('Changed')
        with self.assertRaisesRegex(ValueError,'Stale'):self.execute()
        self.assertEqual(self.task.read_text(),'Changed')

    def test_parent_symlink_does_not_modify_outside_target(self):
        original=self.project/'blocked';moved=self.root/'elsewhere'
        original.rename(moved);original.symlink_to(moved)
        with self.assertRaises(OSError):self.execute()
        self.assertEqual((moved/'Review.md').read_bytes(),self.before)

    def test_shared_transaction_journal_is_never_replayed(self):
        journal=self.project/'.transactions/evil';journal.mkdir(parents=True)
        (journal/'prepared.json').write_text('{malicious')
        self.execute()
        self.assertEqual((journal/'prepared.json').read_text(),'{malicious')

    def test_enospc_before_prepared_preserves_original(self):
        original=repair.publish_at
        def fail(fd,name,*args,**kwargs):
            if name=='prepared.json':raise OSError(28,'fixture ENOSPC')
            return original(fd,name,*args,**kwargs)
        with patch.object(repair,'publish_at',side_effect=fail),self.assertRaises(OSError):self.execute()
        self.assertEqual(self.task.read_bytes(),self.before)
        self.assertEqual(self.execute()['state'],'COMMITTED')

    def test_commit_receipt_failure_replays_without_duplicate_history(self):
        original=repair.publish_at
        def fail(fd,name,*args,**kwargs):
            if name=='committed.json':raise OSError(28,'fixture ENOSPC')
            return original(fd,name,*args,**kwargs)
        with patch.object(repair,'publish_at',side_effect=fail),self.assertRaises(OSError):self.execute()
        self.assertTrue(self.execute()['replayed'])
        self.assertEqual(self.task.read_text().count('**REASON REPAIR**'),1)

    def test_task_hardlink_is_rejected(self):
        os.link(self.task,self.root/'duplicate')
        with self.assertRaisesRegex(ValueError,'regular'):self.execute()
        self.assertEqual(self.task.read_bytes(),self.before)

    def test_access_acl_and_user_attributes_survive_publication(self):
        import subprocess
        subprocess.run(['setfacl','-m','u:65534:r--',str(self.task)],check=True)
        os.setxattr(self.task,'user.fixture',b'preserve')
        before={k:os.getxattr(self.task,k) for k in os.listxattr(self.task)}
        self.execute()
        self.assertEqual({k:os.getxattr(self.task,k) for k in os.listxattr(self.task)},before)

    def test_rollback_restores_original_and_refuses_later_work(self):
        self.execute()
        dry=repair.rollback(self.plan,self.plan['sha256'],'rollback-approval',False)
        self.assertEqual(dry['state'],'DRY_RUN')
        self.task.write_text('Later work')
        with self.assertRaisesRegex(ValueError,'changed'):repair.rollback(self.plan,self.plan['sha256'],'rollback-approval',True)
        self.task.write_text(self.plan['plan']['after'])
        result=repair.rollback(self.plan,self.plan['sha256'],'rollback-approval',True)
        self.assertEqual(result['state'],'ROLLED_BACK');self.assertEqual(self.task.read_bytes(),self.before)
        self.assertTrue(repair.rollback(self.plan,self.plan['sha256'],'rollback-approval',True)['replayed'])

if __name__=='__main__':unittest.main()
