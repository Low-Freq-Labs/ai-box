import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import freq_board as board
import freq_board_transaction as tx
from freq_board_inspect import inspect


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'board/projects/TEST'
        for status in board.STATUSES:
            (self.project / status).mkdir(parents=True)
        (self.project / 'active/finn').mkdir()
        (self.project / 'active/jarvis').mkdir()
        self.env = patch.dict(os.environ, {'FREQ_BOARD_TESTING':'1',
            'FREQ_BOARD_ROOT':str(self.root/'board'), 'FREQ_BOARD_AGENT':'finn',
            'FREQ_BOARD_ALERT_TEST_SINK':str(self.root/'alerts')})
        self.env.start(); tx.CONTEXT.clear()
        self.source = self.project / 'active/finn/Task.md'
        self.source.write_text('# Task\n\nOriginal content\n')

    def tearDown(self):
        self.env.stop(); tx.CONTEXT.clear(); self.temp.cleanup()

    def location(self):
        return board.task_location(self.project, self.source)

    def after(self):
        return board.append_history(board.set_blocked_reason(self.source.read_text(), 'Owner confirmed'),
                                    board.history_entry('finn','BLOCKED','Owner confirmed'))

    def test_enospc_at_each_boundary_recovers_complete_old_or_new(self):
        stages = ('before_images','after_before_image','after_after_image','after_prepare',
                  'before_publish','after_publish','after_target_sync','after_source_unlink',
                  'before_receipt','after_receipt')
        original = self.source.read_bytes()
        for number, stage in enumerate(stages):
            with self.subTest(stage=stage):
                task = self.project / 'active/finn' / (str(number)+'.md')
                task.write_bytes(original)
                new = board.set_blocked_reason(task.read_text(), 'Required reason')
                with patch.dict(os.environ, {'FREQ_BOARD_FAULT':stage}):
                    with self.assertRaises(OSError):
                        tx.transition(self.project,board.task_location(self.project,task),'blocked',new)
                tx.recover(self.project)
                dest = self.project/'blocked'/task.name
                self.assertEqual(int(task.exists())+int(dest.exists()),1)
                if dest.exists():
                    self.assertEqual(dest.read_text(),new)
                else:
                    self.assertEqual(task.read_bytes(),original)

    def test_process_death_after_publish_is_recovered(self):
        script = "import sys;sys.path.insert(0,sys.argv[1]);import freq_board as b;import freq_board_transaction as t;from pathlib import Path;p=Path(sys.argv[2]);s=p/'active/finn/Task.md';t.transition(p,b.task_location(p,s),'blocked',b.set_blocked_reason(s.read_text(),'Crash reason'))"
        env = dict(os.environ,FREQ_BOARD_FAULT='after_publish',FREQ_BOARD_FAULT_KIND='kill')
        process = subprocess.run([sys.executable,'-c',script,str(ROOT/'lib'),str(self.project)],env=env)
        self.assertEqual(process.returncode,91)
        self.assertFalse(inspect(self.project)['complete'])
        tx.recover(self.project)
        self.assertFalse(self.source.exists())
        self.assertEqual(board.blocked_reason(self.project/'blocked/Task.md'),'Crash reason')

    def test_preserved_images_do_not_share_live_inode(self):
        result=tx.transition(self.project,self.location(),'blocked',self.after())
        before=(self.project/'.transactions'/result['operation_id']/'after.bin').read_bytes()
        result['path'].write_text('Later editor change')
        self.assertEqual((self.project/'.transactions'/result['operation_id']/'after.bin').read_bytes(),before)

    def test_expected_revision_conflict_does_not_create_journal(self):
        tx.CONTEXT['expected_revision']='0'*64
        with self.assertRaisesRegex(ValueError,'Revision conflict'):
            tx.transition(self.project,self.location(),'blocked',self.after())
        self.assertFalse((self.project/'.transactions').exists())

    def test_idempotent_replay_and_conflicting_reuse(self):
        operation=str(uuid.uuid4())
        args=['--project','TEST','Task','Reason','--operation-id',operation]
        tx.arguments(args,'task-block')
        tx.transition(self.project,self.location(),'blocked',self.after())
        self.assertIsNone(tx.arguments(args,'task-block'))
        with self.assertRaisesRegex(ValueError,'conflicts'):
            tx.arguments(['--project','TEST','Task','Different','--operation-id',operation],'task-block')

    def test_status_keeps_good_and_corrupt_rows_without_mutation(self):
        broken=self.project/'blocked/Broken.md';broken.write_text('no reason')
        report=inspect(self.project)
        self.assertEqual(len(report['tasks']),2)
        self.assertEqual(len(report['errors']),1)
        self.assertEqual(broken.read_text(),'no reason')

    def test_symlink_target_refused(self):
        target=self.project/'blocked/Task.md'
        target.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError,'Symlink'):
            tx.transition(self.project,self.location(),'blocked',self.after())

    def test_directory_fsync_failure_before_prepare_preserves_old(self):
        before=self.source.read_bytes()
        with patch.object(tx,'sync',side_effect=OSError(28,'inode/space failure')):
            with self.assertRaises(OSError):
                tx.transition(self.project,self.location(),'blocked',self.after())
        self.assertEqual(self.source.read_bytes(),before)

    def test_concurrent_claim_has_one_winner(self):
        self.source.rename(self.project/'ready/Task.md')
        coms=self.root/'coms'
        for agent in ('finn','jarvis'):
            (coms/agent/'inbox').mkdir(parents=True);(coms/agent/'read').mkdir()
        workers=[]
        for agent in ('finn','jarvis'):
            env=dict(os.environ,FREQ_BOARD_AGENT=agent,FREQ_COMS_ROOT=str(coms))
            workers.append(subprocess.Popen([sys.executable,str(ROOT/'bin/task-ready'),'TEST','Task',agent],
                env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        results=[p.communicate() for p in workers]
        self.assertEqual(sorted(p.returncode for p in workers),[0,1],results)
        self.assertEqual(sum((self.project/'active'/a/'Task.md').exists() for a in ('finn','jarvis')),1)

    def test_notification_intent_survives_commit_without_send(self):
        result=tx.transition(self.project,self.location(),'active',self.source.read_text(),'jarvis',
                             notification={'recipient':'jarvis','payload':'fixture'})
        folder,value=tx.record(self.project,result['operation_id'])
        self.assertEqual(value['notification']['recipient'],'jarvis')
        self.assertEqual(json.loads((folder/'committed.json').read_text())['notification'],'PENDING')

    def test_transfer_recovery_keeps_new_assignment_directory(self):
        (self.project/'active/jarvis').rmdir()
        coms=self.root/'coms'
        for agent in ('finn','jarvis'):
            (coms/agent/'inbox').mkdir(parents=True);(coms/agent/'read').mkdir()
        env=dict(os.environ,FREQ_COMS_ROOT=str(coms),FREQ_BOARD_FAULT='after_prepare')
        result=subprocess.run([sys.executable,str(ROOT/'bin/task-transfer'),'--project','TEST','Task','jarvis','Fixture handoff'],env=env,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.project/'active/jarvis').is_dir(),result.stderr)
        tx.recover(self.project)
        self.assertFalse(self.source.exists())
        self.assertIn('Fixture handoff',(self.project/'active/jarvis/Task.md').read_text())

    def test_replay_syncs_published_target_before_unlink(self):
        with patch.dict(os.environ,{'FREQ_BOARD_FAULT':'after_publish'}):
            with self.assertRaises(OSError):tx.transition(self.project,self.location(),'blocked',self.after())
        events=[]
        original_sync=tx.sync
        def observed_sync(path):
            events.append((path,self.source.exists()))
            original_sync(path)
        with patch.object(tx,'sync',side_effect=observed_sync):tx.recover(self.project)
        self.assertIn((self.project/'blocked',True),events)
        self.assertIn((self.source.parent,False),events)


if __name__=='__main__': unittest.main()
