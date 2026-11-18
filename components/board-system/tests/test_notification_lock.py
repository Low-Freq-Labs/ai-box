"""Recipient transport waits must not block unrelated board assessments or writes.
Uses only supported isolated board/comms test fixtures and fake tmux.
"""
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import tempfile
import uuid

import unittest

ROOT = Path(__file__).resolve().parents[1]

def invoke(argv, env, timeout=12):
    result = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout)
    return {'argv': list(map(str, argv)), 'exit': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}

class NotificationLockTests(unittest.TestCase):
    def test_assignment_and_transfer_leave_project_available(self):
        with tempfile.TemporaryDirectory(prefix='freq-board-notification-') as temporary:
            output = Path(temporary)
            results = []
            for command in ('task-ready', 'task-transfer'):
                case = output / command
                case.mkdir(mode=0o700)
                board = case / 'board'
                project = board / 'projects' / 'BOARD-TEST'
                for name in ('ready', 'active/jarvis', 'blocked', 'done', 'archive'):
                    (project / name).mkdir(parents=True)
                for agent in ('jarvis', 'finn'):
                    for name in ('inbox', 'read'):
                        (case / 'coms' / agent / name).mkdir(parents=True)
                tmux_tmp = tempfile.TemporaryDirectory(prefix='jarvis-board-lock-')
                self.addCleanup(tmux_tmp.cleanup)
                tmux = Path(tmux_tmp.name)
                fake_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.addCleanup(fake_socket.close)
                fake_socket.bind(str(tmux / 'agent-finn'))
                log = case / 'fake-tmux.jsonl'
                fake = case / 'fake-tmux'
                fake.write_text("#!/usr/bin/python3\nimport json, os, sys, time\nargs = sys.argv[1:]\ndata = sys.stdin.read() if 'load-buffer' in args else None\nwith open(os.environ['FAKE_TMUX_LOG'], 'a') as stream:\n    stream.write(json.dumps(dict(args=args, stdin=data, at=time.monotonic()))+'\\n')\nif 'list-panes' in args:\n    print('%1|finn|agent|0|1')\n")
                fake.chmod(0o700)
                env = dict(os.environ, FREQ_BOARD_TESTING='1', FREQ_BOARD_ROOT=str(board),
                           FREQ_BOARD_AGENT='jarvis', FREQ_COMS_ROOT=str(case / 'coms'),
                           FREQ_BOARD_ALERT_TMUX_DIR=str(tmux), FREQ_BOARD_ALERT_TMUX_BIN=str(fake),
                           FREQ_BOARD_ALERT_TEST_SINK='', FAKE_TMUX_LOG=str(log),
                           PYTHONPATH=str(ROOT / 'lib'))
                assert board != Path('/var/lib/freq-agents/board') and board.is_relative_to(output)
                title = 'Original notification wait fixture'
                registration = invoke([str(ROOT / 'bin' / 'task-register'), 'BOARD-TEST', title,
                                       'Supported isolated infrastructure regression fixture'], env)
                assert registration['exit'] == 0, registration
                if command == 'task-transfer':
                    setup = invoke([str(ROOT / 'bin' / 'task-ready'), 'BOARD-TEST', title, 'jarvis'], env)
                    assert setup['exit'] == 0, setup
                original_template = invoke([str(ROOT / 'bin' / 'project-assess'), 'BOARD-TEST', '--template'], env)
                assert original_template['exit'] == 0, original_template
                operation = str(uuid.uuid4())
                selected = ROOT / 'bin'
                if command == 'task-ready':
                    argv = [str(selected / command), '--operation-id', operation,
                            'BOARD-TEST', title, 'finn', 'Isolated fixture only; no live communication']
                else:
                    argv = [str(selected / command), '--operation-id', operation, '--project',
                            'BOARD-TEST', title, 'finn', 'Isolated fixture handoff only']
                lock = os.open(tmux / '.dev-msg-finn.lock', os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC, 0o600)
                fcntl.flock(lock, fcntl.LOCK_EX)
                process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                body = None
                try:
                    committed = project / '.transactions' / operation / 'committed.json'
                    uncertain = project / '.transactions' / operation / 'notification.json'
                    end = time.monotonic() + 5
                    while not committed.exists() or not uncertain.exists():
                        assert process.poll() is None, 'fixture command ended before notification boundary'
                        assert time.monotonic() < end, 'commit was not observed'
                        time.sleep(.01)
                    assert json.loads(uncertain.read_text())['state'] == 'UNCERTAIN'
                    started = time.monotonic()
                    template = invoke([str(ROOT / 'bin' / 'project-assess'), 'BOARD-TEST', '--template'], env)
                    elapsed = time.monotonic() - started
                    assert process.poll() is None, 'recipient lock did not actually block notification'
                    checks = {'template_while_delivery_blocked': template, 'elapsed_seconds': elapsed}
                    assert template['exit'] == 0 and elapsed < 2, template
                    stale = json.loads(original_template['stdout'])
                    stale['summary'] = 'Old fixture snapshot must refuse after the committed ownership change.'
                    stale_path = case / 'stale.json'
                    stale_path.write_text(json.dumps(stale))
                    rejection = invoke([str(ROOT / 'bin' / 'project-assess'), 'BOARD-TEST', '--submit', str(stale_path)], env)
                    assert rejection['exit'] == 1 and 'stale assessment' in rejection['stderr'], rejection
                    checks['stale_submission_rejected'] = rejection
                    fresh = json.loads(template['stdout'])
                    fresh['summary'] = 'Only fixture active work is owned by finn; no ready or blocked work remains.'
                    fresh_path = case / 'fresh.json'
                    fresh_path.write_text(json.dumps(fresh))
                    submit = invoke([str(ROOT / 'bin' / 'project-assess'), 'BOARD-TEST', '--submit', str(fresh_path)], env)
                    assert submit['exit'] == 0, submit
                    current = invoke([str(ROOT / 'bin' / 'project-assess'), 'BOARD-TEST', '--check'], env)
                    assert current['exit'] == 0, current
                    unrelated = invoke([str(ROOT / 'bin' / 'task-register'), 'BOARD-TEST', 'Unrelated concurrent fixture',
                                        'Prove normal board writes are independent of blocked recipient delivery'], env)
                    assert unrelated['exit'] == 0, unrelated
                    revised = invoke([str(ROOT / 'bin' / 'project-assess'), 'BOARD-TEST', '--check'], env)
                    assert revised['exit'] == 1 and 'stale assessment' in revised['stderr'], revised
                    checks.update(fresh_submission=submit, current_check=current,
                                  independent_board_write=unrelated, subsequent_revision_rejected=revised)
                except BaseException as error:
                    body = error
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    os.close(lock)
                    stdout, stderr = process.communicate(timeout=8)
                    fake_socket.close()
                    (tmux / "agent-finn").unlink()
                    (tmux / ".dev-msg-finn.lock").unlink()
                    tmux.rmdir()
                    (case / 'COMMAND.stdout').write_text(stdout)
                    (case / 'COMMAND.stderr').write_text(stderr)
                if body is not None:
                    raise body
                assert process.returncode == 0, stderr
                assert json.loads(uncertain.read_text())['state'] == 'NOTIFIED'
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                assert len([call for call in calls if 'paste-buffer' in call['args']]) == 1
                assert len([call for call in calls if 'send-keys' in call['args']]) == 2
                assert len([call for call in calls if 'load-buffer' in call['args']]) == 1
                row = dict(command=command, stage='regression', result='PASS',
                           notification_wait_was_real=True, committed_before_wait=True,
                           uncertainty_retained_before_wait=True, final_notification='NOTIFIED',
                           one_paste_two_enters=True, child_process_reaped=True, checks=checks)
                results.append(row)
                (output / 'PROGRESS-R1.json').write_text(json.dumps(results, indent=2) + '\n')
            record = dict(schema=1, uid=os.getuid(), cases=results, live_board_or_peer_effects=False)
            (output / 'RESULT-R1.json').write_text(json.dumps(record, indent=2) + '\n')

if __name__ == '__main__':
    unittest.main()
