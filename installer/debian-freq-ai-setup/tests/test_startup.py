"""Offline tests; no real model calls, accounts, or Discord messages."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
import tempfile
import io
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('startup', str(ROOT / 'assets/agent-startup-notify'))
spec = importlib.util.spec_from_loader(loader.name, loader)
startup = importlib.util.module_from_spec(spec)
loader.exec_module(startup)
sys.path.insert(0, str(ROOT / 'assets/coms-system/tests'))
from test_dev_msg import DevMsgTests


class StartupComsTests(DevMsgTests):
    def setUp(self):
        super().setUp()
        self.fake_tmux.write_text(self.fake_tmux.read_text().replace('import sys', 'import sys\nimport time').replace('entry = {', 'entry = {"at": time.monotonic(), '))
        self.source = self.root / 'instructions.md'
        self.source.write_text((ROOT / 'assets/agent-startup-message.md').read_text())
        self.source.chmod(0o644)
        (self.root / 'bin').mkdir(exist_ok=True)
        (self.root / 'lib').mkdir(exist_ok=True)
        (self.root / 'lib/freq_coms_receipts.py').write_bytes((ROOT / 'assets/coms-system/lib/freq_coms_receipts.py').read_bytes())
        self.command = self.root / 'bin/dev-msg'
        self.command.write_text((ROOT / 'assets/coms-system/bin/dev-msg').read_text().replace(
            '/usr/local/share/freq-ai-setup/agent-startup-message.md', str(self.source)))
        self.command.chmod(0o755)

    def invoke(self, sender='jarvis'):
        return subprocess.run([str(self.command), '--startup', 'jarvis'], text=True,
                              capture_output=True, env=dict(self.env, FREQ_COMS_TEST_SENDER=sender))

    @unittest.skipUnless(os.geteuid() == 0, 'root-owned fixture')
    def test_startup_delivery(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        messages = list(self.jarvis_inbox.glob('*.md'))
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].read_text(), self.source.read_text().rstrip('\n'))
        payload = next(c['stdin'] for c in self.calls() if c['command'] == 'load-buffer')
        self.assertTrue(payload.startswith('STARTUP-MSG: [Session startup]'))
        self.assertIn('dev-read ' + messages[0].name + '\n  → Verify the handoff', payload)
        self.assertLessEqual(len(payload.encode()), 512)
        self.assertEqual([c['command'] for c in self.calls()][-2:], ['send-keys', 'send-keys'])
        paste, first, second = self.calls()[-3:]
        self.assertGreaterEqual(first['at'] - paste['at'], 0.45)
        self.assertGreaterEqual(second['at'] - first['at'], 0.45)

    def test_startup_cannot_target_peer(self):
        self.assertNotEqual(self.invoke(sender='other').returncode, 0)
        self.assertFalse(self.calls())

    def test_startup_rejects_unsafe_source(self):
        self.source.chmod(0o666)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse(list(self.jarvis_inbox.glob('*.md')))


class StartupNotifierTests(unittest.TestCase):
    def test_no_state_skips_without_touching_tmux_or_coms(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(startup, 'STATE_ROOT', Path(temp)), \
             patch.object(sys, 'argv', ['helper', 'codex', 'jim', '/socket', '/dev-msg']), \
             patch.object(startup.subprocess, 'run') as run:
            self.assertEqual(startup.main(), 0)
            current = Path(temp) / 'jim/session-state'
            (current / 'archive').mkdir(parents=True)
            (current / 'archive/session-state-20260907T190000.000000Z.md').write_text('old')
            self.assertEqual(startup.main(), 0)
            run.assert_not_called()
            saved = current / 'session-state-20260907T200000.000000Z.md'
            saved.write_text('Resume here: verified task and next action.')
            self.assertTrue(startup.has_session_state('jim'))
            saved.write_text('   ')
            with self.assertRaises(ValueError):
                startup.has_session_state('jim')
            saved.unlink()
            saved.symlink_to(current / 'archive/session-state-20260907T190000.000000Z.md')
            with self.assertRaises(OSError):
                startup.has_session_state('jim')

    @unittest.skipUnless(os.geteuid() == 0, 'root-owned fixture')
    def test_real_tmux_delivery_and_dev_read(self):
        for runtime, marker in [('codex', '›'), ('claude', '❯')]:
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory(prefix='freq-startup-pane-') as temp:
                root = Path(temp)
                inbox = root / 'coms/root/inbox'
                inbox.mkdir(parents=True)
                (root / 'coms/root/read').mkdir()
                instructions = root / 'instructions.md'
                instructions.write_text((ROOT / 'assets/agent-startup-message.md').read_text())
                instructions.chmod(0o644)
                (root / 'bin').mkdir()
                (root / 'lib').mkdir()
                (root / 'lib/freq_coms_receipts.py').write_bytes((ROOT / 'assets/coms-system/lib/freq_coms_receipts.py').read_bytes())
                command = root / 'bin/dev-msg'
                command.write_text((ROOT / 'assets/coms-system/bin/dev-msg').read_text().replace(
                    '/usr/local/share/freq-ai-setup/agent-startup-message.md', str(instructions)))
                command.chmod(0o755)
                socket = str(root / 'agent-root')
                tmux = ['tmux', '-f', '/dev/null', '-S', socket]
                env = dict(os.environ, FREQ_COMS_TESTING='1', FREQ_COMS_ROOT=str(root / 'coms'),
                           DEV_MSG_TMUX_DIR=temp)
                try:
                    subprocess.run(tmux + ['new-session', '-d', '-s', 'root', '-n', 'agent',
                                          f"printf '{marker}\u00a0Try sign in troubleshooting'; exec cat"], check=True)
                    subprocess.run(tmux + ['set-option', '-p', '-t', 'root:agent.0', '@freq_delivery_pane', '1'], check=True)
                    state = root / 'session-data/root/session-state'
                    state.mkdir(parents=True)
                    (state / 'session-state-20260907T200000.000000Z.md').write_text('Fixture handoff')
                    helper = root / 'notifier'
                    helper.write_text((ROOT / 'assets/agent-startup-notify').read_text().replace(
                        '/home/freq-agents/session-data', str(root / 'session-data')))
                    result = subprocess.run([sys.executable, str(helper),
                                             runtime, 'root', socket, str(command)], env=env, capture_output=True, text=True, timeout=50)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn('SENT:', result.stdout)
                    files = list(inbox.glob('*.md'))
                    self.assertEqual(len(files), 1)
                    screen = subprocess.check_output(tmux + ['capture-pane', '-p', '-t', 'root:agent.0'], text=True)
                    self.assertIn('STARTUP-MSG:', screen)
                    read = subprocess.run([str(ROOT / 'assets/coms-system/bin/dev-read'), files[0].name],
                                          env=env, capture_output=True, text=True)
                    self.assertEqual(read.returncode, 0, read.stderr)
                    self.assertEqual(read.stdout, instructions.read_text().rstrip('\n'))
                    self.assertFalse(list(inbox.glob('*.md')))
                finally:
                    subprocess.run(tmux + ['kill-server'], capture_output=True)

    def test_readiness(self):
        for runtime, marker in [('codex', '›'), ('claude', '❯')]:
            self.assertTrue(startup.ready(runtime, 'ready\n' + marker + ' '))
            for text in ('Sign in', 'Do you trust this folder?', 'Loading...'):
                self.assertFalse(startup.ready(runtime, text + ('\n' + marker if text != 'Loading...' else '')))

    def test_update_dialog_is_not_chat_input(self):
        for screen in (
            'Update available! 0.153.4 -> 0.154.0\n› 1. Update now\n  2. Skip\nPress enter to continue',
            '› 1. Install\n  2. Cancel',
            'model:     loading   /model to change\n› Ask Codex to do anything',
        ):
            self.assertFalse(startup.ready('codex', screen))

    def test_prompt_whitespace_and_arbitrary_suggestions(self):
        for runtime, marker in [('codex', '›'), ('claude', '❯')]:
            for space in (' ', '\u00a0', '\u202f', '\u2003', '\t'):
                for suggestion in ('Try "how does <filepath> work?"',
                                   'Explain sign in and trust this folder', 'Anything else'):
                    with self.subTest(runtime=runtime, space=repr(space), suggestion=suggestion):
                        prompt = marker + space + suggestion
                        self.assertTrue(startup.ready(runtime, 'Welcome\n' + prompt))
                        self.assertFalse(startup.ready(runtime, 'Do you trust this folder?\n' + prompt))
                        self.assertFalse(startup.ready(runtime, 'Sign in required\n' + prompt))
            self.assertFalse(startup.ready(runtime, marker + 'not-a-prompt'))
            self.assertFalse(startup.ready(runtime, marker + '\n' + '\n'.join(['Loading'] * 12)))

    def test_delivery_once_including_failure(self):
        for code in (0, 1):
            with patch.object(sys, 'argv', ['helper', 'codex', 'jim', '/socket', '/dev-msg']), \
                 patch.object(startup, 'has_session_state', return_value=True), \
                 patch.object(startup.subprocess, 'run', side_effect=[
                     subprocess.CompletedProcess([], 0, '› '),
                     subprocess.CompletedProcess([], code)]) as run:
                self.assertEqual(startup.main(), code)
                self.assertEqual(run.call_count, 2)
                self.assertEqual(run.call_args.args[0], ['/dev-msg', '--startup', 'jim'])

    def test_start_receipt_quiet_but_failure_diagnostics_preserved(self):
        for code in (0, 1):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(sys, 'argv', ['helper', 'codex', 'jim', '/socket', '/dev-msg']), \
                 patch.object(startup, 'has_session_state', return_value=True), \
                 patch.object(startup.subprocess, 'run', side_effect=[
                     subprocess.CompletedProcess([], 0, '\u203a '),
                     subprocess.CompletedProcess([], code, 'SENT: fixture\n', 'diagnostic\n')]) as run, \
                 redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(startup.main(), code)
                self.assertEqual(run.call_count, 2)
                self.assertTrue(run.call_args.kwargs['capture_output'])
            self.assertEqual(out.getvalue(), '')
            self.assertIn('diagnostic', err.getvalue())
            self.assertEqual('SENT: fixture' in err.getvalue(), bool(code))

    def test_dead_pane(self):
        with patch.object(sys, 'argv', ['helper', 'claude', 'jim', '/socket', '/dev-msg']), \
             patch.object(startup, 'has_session_state', return_value=True), \
             patch.object(startup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '')) as run:
            self.assertEqual(startup.main(), 1)
            self.assertEqual(run.call_count, 1)

    def test_lifecycle_scope(self):
        source = (ROOT / 'assets/agent-lifecycle.template').read_text()
        start, rest = source.split('    connect)', 1)
        self.assertNotIn('agent-startup-notify', rest)
        delivery = start.index('if ! "${as_agent[@]}" /usr/local/libexec/freq-ai-setup/agent-startup-notify')
        self.assertLess(start.index('already running.'), start.index('new-session'))
        self.assertLess(start.index('server-access -l'), delivery)
        self.assertNotIn('agent-runtime-start', source)


if __name__ == '__main__':
    unittest.main()
