import importlib.machinery
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'assets/board-system/lib'))
def load(name):
    return importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(SOURCE / 'assets' / name)).load_module()
update = load('full-update')
managed = load('update-managed-tools')
retire = load('retire-agent-data')
import freq_board as board


class MaintenanceTests(unittest.TestCase):
    def test_ai_acceptance_uses_internal_installer(self):
        acceptance = (SOURCE / 'accept-ai-packages.sh').read_text()
        self.assertIn('readonly internal_installer=/usr/local/libexec/freq-ai-setup/ai-packages-install', acceptance)
        self.assertNotIn('stat -c \'%U:%G:%a\' "$master_home/tools/ai-packages-install"', acceptance)
        self.assertIn('retired public installer entrypoint remains', acceptance)
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='freq-maintenance-fixture-')
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def test_stable_compatible_updates_only(self):
        self.assertEqual(managed.compatible('24.19.0', ['25.0.0', '24.19.1', '24.18.0', '24.20.0-rc.1']), '24.19.1')
    def test_zero_major_minor_is_reviewed(self):
        self.assertEqual(managed.compatible('0.24.2', ['0.25.0', '0.24.3']), '0.24.3')
    def test_no_downgrade(self):
        self.assertEqual(managed.compatible('1.5.5', ['1.4.0']), '1.5.5')
    def test_reboot_marker(self):
        (self.root / 'reboot-required').touch()
        self.assertIn('REBOOT REQUIRED', update.reboot_status(self.root, self.root, '6.12.1-amd64'))
    def test_current_kernel(self):
        (self.root / 'vmlinuz-6.12.1-amd64').touch()
        self.assertIn('No reboot requirement detected', update.reboot_status(self.root, self.root, '6.12.1-amd64'))
    def test_new_kernel(self):
        for n in ('6.12.1-amd64', '6.12.2-amd64'):
            (self.root / ('vmlinuz-' + n)).touch()
        self.assertIn('REBOOT REQUIRED', update.reboot_status(self.root, self.root, '6.12.1-amd64'))
    def test_unknown_kernel_is_not_false_clean(self):
        self.assertIn('UNKNOWN', update.reboot_status(self.root, self.root, '6.12.1-amd64'))
    def test_wsl_kernel_not_guest_managed(self):
        self.assertIn('Windows host', update.reboot_status(self.root, self.root, '6.18-microsoft-standard-WSL2'))
    def test_needrestart_abi_update_requires_reboot(self):
        import subprocess
        result = subprocess.CompletedProcess([], 0, 'NEEDRESTART-KSTA: 2\n', '')
        with patch.object(update.shutil, 'which', return_value='/usr/sbin/needrestart'), patch.object(update.subprocess, 'run', return_value=result):
            self.assertIn('REBOOT REQUIRED', update.reboot_status(Path('/boot'), self.root, '6.12.1-amd64'))
    def test_needrestart_unknown_is_not_clean(self):
        import subprocess
        result = subprocess.CompletedProcess([], 0, 'NEEDRESTART-KSTA: 0\n', '')
        with patch.object(update.shutil, 'which', return_value='/usr/sbin/needrestart'), patch.object(update.subprocess, 'run', return_value=result):
            self.assertIn('UNKNOWN', update.reboot_status(Path('/boot'), self.root, '6.12.1-amd64'))
    def project(self):
        project = self.root / 'board/projects/TEST'
        for state in board.STATUSES:
            (project / state).mkdir(parents=True)
        (project / 'active/jake').mkdir()
        return project
    def test_board_preserves_history_done_and_blockers(self):
        project = self.project()
        (project / 'active/jake/Build.md').write_text('# Build\nOriginal intent\n')
        blocked = board.set_blocked_reason('# Waiting\n', 'Operator decision is missing')
        (project / 'blocked/Waiting.md').write_text(blocked)
        (project / 'done/Finished.md').write_text('# Finished\nEvidence\n')
        retire.retire_board(self.root / 'board', 'jake', check=True)
        self.assertTrue((project / 'active/jake/Build.md').exists())
        retire.retire_board(self.root / 'board', 'jake')
        self.assertFalse((project / 'active/jake').exists())
        ready = (project / 'ready/Build.md').read_text()
        self.assertIn('Original intent', ready)
        self.assertIn('AGENT REMOVED', ready)
        self.assertEqual((project / 'blocked/Waiting.md').read_text(), blocked)
        self.assertEqual((project / 'done/Finished.md').read_text(), '# Finished\nEvidence\n')
    def test_stale_blocker_in_active_task_is_preserved(self):
        project = self.project()
        (project / 'active/jake/Build.md').write_text(board.set_blocked_reason('# Build\n', 'Missing input'))
        retire.retire_board(self.root / 'board', 'jake')
        self.assertIn('Missing input', (project / 'blocked/Build.md').read_text())
    def test_board_collision_refuses(self):
        project = self.project()
        for path in ('active/jake/Build.md', 'ready/Build.md'):
            (project / path).write_text('keep')
        with self.assertRaises(Exception):
            retire.retire_board(self.root / 'board', 'jake')
        self.assertEqual((project / 'active/jake/Build.md').read_text(), 'keep')
    def test_board_symlink_status_refuses(self):
        project = self.project()
        (project / 'ready').rmdir()
        (project / 'ready').symlink_to(self.root)
        with self.assertRaisesRegex(RuntimeError, 'unsafe board status'):
            retire.retire_board(self.root / 'board', 'jake')
    def test_archive_does_not_mutate_linked_durable_work(self):
        if os.geteuid():
            self.skipTest('root-owned archive metadata requires root fixture runner')
        lane = self.root / 'jake'
        lane.mkdir()
        durable = self.root / 'durable.txt'
        durable.write_text('keep my work')
        durable.chmod(0o664)
        os.link(durable, lane / 'hardlink.txt')
        (lane / 'reference').symlink_to(durable)
        archive = self.root / '20260905T000000Z'
        retire.archive_lane(lane, archive, os.getgid())
        self.assertEqual(durable.read_text(), 'keep my work')
        self.assertEqual(stat.S_IMODE(durable.stat().st_mode), 0o664)
        self.assertNotEqual(durable.stat().st_ino, (archive / 'jake/hardlink.txt').stat().st_ino)
        self.assertEqual(os.readlink(archive / 'jake/reference'), str(durable))
        self.assertEqual(list(lane.iterdir()), [])
        with self.assertRaises(FileExistsError):
            retire.archive_lane(lane, archive, os.getgid())
    def test_archive_rejects_special_files(self):
        os.mkfifo(self.root / 'fifo')
        with self.assertRaisesRegex(RuntimeError, 'special file'):
            retire.inventory(self.root)
    def test_level_set_has_no_machine_reset_targets(self):
        source = (SOURCE / 'assets/level-set').read_text()
        for forbidden in ('npm-global', 'safe_remove_tree', 'discord-venv', 'board_root', '--yes'):
            self.assertNotIn(forbidden, source)
        self.assertIn('Type LEVEL-SET', source)

if __name__ == '__main__':
    unittest.main(verbosity=2)
