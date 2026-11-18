#!/usr/bin/env python3
import json
import os
import pathlib
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV_MSG = ROOT / "bin" / "dev-msg"


FAKE_TMUX = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
command = args[args.index("-S") + 2]
import time
entry = {"args": args, "command": command, "stdin": "", "at": time.monotonic()}
if command == "load-buffer":
    entry["stdin"] = sys.stdin.read()
log_path = pathlib.Path(os.environ["FAKE_TMUX_LOG"])
call_number = len(log_path.read_text().splitlines()) + 1 if log_path.exists() else 1
with log_path.open("a") as stream:
    stream.write(json.dumps(entry) + "\n")
if command == "list-panes":
    print(os.environ.get("FAKE_TMUX_PANES", ""), end="")
failure = os.environ.get("FAKE_TMUX_FAIL", "")
failure_at = int(os.environ.get("FAKE_TMUX_FAIL_AT", "0"))
raise SystemExit(1 if command == failure or call_number == failure_at else 0)
'''


class DevMsgTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.tmux_dir = self.root / "tmux"
        self.tmux_dir.mkdir()
        self.coms_root = self.root / "coms"
        self.jarvis_inbox = self.coms_root / "jarvis" / "inbox"
        self.jarvis_inbox.mkdir(parents=True)
        self.discord_root = self.root / "discord"
        self.discord_outbox = self.discord_root / "outbox"
        self.discord_outbox.mkdir(parents=True)
        self.socket_path = self.tmux_dir / "agent-jarvis"
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.socket_path))
        self.fake_tmux = self.root / "fake-tmux"
        self.fake_tmux.write_text(FAKE_TMUX)
        self.fake_tmux.chmod(0o755)
        self.log = self.root / "tmux.log"
        self.sender = pwd.getpwuid(os.geteuid()).pw_name
        self.env = os.environ.copy()
        self.env.update(
            FREQ_COMS_TESTING="1",
            DEV_MSG_TMUX_DIR=str(self.tmux_dir),
            FREQ_COMS_ROOT=str(self.coms_root),
            FREQ_DISCORD_ROOT=str(self.discord_root),
            DEV_MSG_TMUX_BIN=str(self.fake_tmux),
            DEV_MSG_FLOCK_BIN="/usr/bin/flock",
            FAKE_TMUX_LOG=str(self.log),
            FAKE_TMUX_PANES=(
                "%4|other|agent|0|1\n"
                "%7|jarvis|agent|0|1\n"
                "%8|jarvis|agent|1|1\n"
            ),
        )

    def tearDown(self):
        self.socket.close()
        self.temp.cleanup()

    def run_dev_msg(self, *args, **env_changes):
        env = self.env.copy()
        env.update(env_changes)
        return subprocess.run(
            [str(DEV_MSG), *args],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_pastes_exact_payload_then_sends_two_enters_separately(self):
        title = "SECOND LOOK NEEDED"
        full_message = "I need a second look at xyz.\n\nHere are all the details."
        result = self.run_dev_msg("jarvis", title, full_message)

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(
            [call["command"] for call in calls],
            [
                "list-panes",
                "load-buffer",
                "paste-buffer",
                "send-keys",
                "send-keys",
            ],
        )
        notification = calls[1]["stdin"]
        self.assertGreaterEqual(calls[3]['at'] - calls[2]['at'], 0.45)
        self.assertGreaterEqual(calls[4]['at'] - calls[3]['at'], 0.45)
        lines = notification.splitlines()
        self.assertEqual(lines[0], f"{self.sender.upper()}-MSG: [{title}]")
        self.assertRegex(
            lines[1],
            r"^  — sent at (?:[1-9]|1[0-2]):[0-5][0-9] [AP]M C[DS]T$",
        )
        self.assertEqual(
            lines[2],
            f"  — from {self.sender} · team coms (not sonny.aif)",
        )
        filename = lines[3].removeprefix("  → dev-read ")
        self.assertRegex(
            filename,
            rf"^\d{{4}}-\d{{2}}-\d{{2}}_\d{{6}}_\d{{9}}_\d+_{re.escape(self.sender)}\.md$",
        )
        message_path = self.jarvis_inbox / filename
        self.assertEqual(message_path.read_text(), full_message)
        self.assertEqual(stat.S_IMODE(message_path.stat().st_mode), 0o660)
        self.assertEqual(
            [path.name for path in self.jarvis_inbox.iterdir()],
            [filename],
        )
        self.assertNotIn(full_message, notification)
        self.assertLessEqual(len(notification.encode()), 512)
        self.assertIn("%7", calls[2]["args"])
        self.assertIn("-p", calls[2]["args"])
        self.assertIn("-r", calls[2]["args"])
        self.assertIn("%7", calls[3]["args"])
        self.assertEqual(calls[3]["args"][-1], "Enter")
        self.assertIn("%7", calls[4]["args"])
        self.assertEqual(calls[4]["args"][-1], "Enter")
        self.assertIsNot(calls[3], calls[4])
        self.assertNotIn("Enter", calls[2]["args"])

    def test_simultaneous_messages_and_board_alert_do_not_interleave(self):
        board_lib = ROOT.parent / "board-system" / "lib"
        if not board_lib.is_dir():
            self.skipTest("combined installer source required")
        env = dict(self.env, FREQ_BOARD_TESTING="1",
                   FREQ_BOARD_ALERT_TMUX_DIR=str(self.tmux_dir),
                   FREQ_BOARD_ALERT_TMUX_BIN=str(self.fake_tmux),
                   PYTHONPATH=str(board_lib))
        commands = [[str(DEV_MSG), "jarvis", title, title] for title in ("FIRST", "SECOND")]
        commands.append([sys.executable, "-c",
                         "from freq_board_alert import send_alert; send_alert('jarvis', 'BOARD-ALERT: concurrent fixture')"])
        processes = [subprocess.Popen(command, env=env, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for command in commands]
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        calls = [c for c in self.calls() if c['command'] != 'list-panes']
        self.assertEqual([c['command'] for c in calls],
                         ['load-buffer', 'paste-buffer', 'send-keys', 'send-keys'] * 3)
        for offset in (0, 4, 8):
            self.assertGreaterEqual(calls[offset+2]['at'] - calls[offset+1]['at'], .45)
            self.assertGreaterEqual(calls[offset+3]['at'] - calls[offset+2]['at'], .45)
        self.assertEqual(len(list(self.jarvis_inbox.glob('*.md'))), 2)
        self.assertEqual({p.read_text() for p in self.jarvis_inbox.glob('*.md')}, {'FIRST', 'SECOND'})

    def test_discord_ingress_is_titleless_sonny_message(self):
        full_message = "hey what's going on with XYZ?"
        result = self.run_dev_msg(
            "jarvis",
            full_message,
            FREQ_COMS_TEST_SENDER="freq-discord",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(
            [call["command"] for call in calls],
            ["list-panes", "load-buffer", "paste-buffer", "send-keys", "send-keys"],
        )
        lines = calls[1]["stdin"].splitlines()
        self.assertEqual(lines[0], "SONNY-MSG:")
        self.assertRegex(
            lines[1],
            r"^  — sent at (?:[1-9]|1[0-2]):[0-5][0-9] [AP]M C[DS]T$",
        )
        self.assertEqual(lines[2], "  — from Sonny · Discord")
        filename = lines[3].removeprefix("  → dev-read ")
        self.assertRegex(
            filename,
            r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{9}_\d+_sonny\.md$",
        )
        self.assertEqual((self.jarvis_inbox / filename).read_text(), full_message)
        self.assertNotIn(full_message, calls[1]["stdin"])
        self.assertNotIn("[", lines[0])

    def test_titleless_mode_is_reserved_for_discord_service_account(self):
        result = self.run_dev_msg("jarvis", "No title.")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "Usage: dev-msg <recipient> <message-title> <full-message>\n",
        )
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(self.jarvis_inbox.iterdir()), [])

    def test_discord_sender_override_is_ignored_without_testing_gate(self):
        env = self.env.copy()
        env.pop("FREQ_COMS_TESTING")
        env["FREQ_COMS_TEST_SENDER"] = "freq-discord"
        result = subprocess.run(
            [str(DEV_MSG), "jarvis", "No title."],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "Usage: dev-msg <recipient> <message-title> <full-message>\n",
        )
        self.assertEqual(self.calls(), [])

    def test_agent_reply_to_sonny_routes_to_discord_outbox_without_tmux(self):
        title = "XYZ UPDATE"
        full_message = "Here is what is happening with XYZ."
        result = self.run_dev_msg("sonny", title, full_message)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"SENT: {self.sender} -> sonny (discord)\n",
        )
        self.assertEqual(self.calls(), [])
        files = list(self.discord_outbox.iterdir())
        self.assertEqual(len(files), 1)
        self.assertRegex(
            files[0].name,
            rf"^\d{{4}}-\d{{2}}-\d{{2}}_\d{{6}}_\d{{9}}_\d+_{re.escape(self.sender)}\.json$",
        )
        self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o660)
        self.assertEqual(
            json.loads(files[0].read_text()),
            {
                "schema": 1,
                "sender": self.sender,
                "title": title,
                "message": full_message,
            },
        )

    def test_agent_reply_to_sonny_fails_at_named_outbox_boundary(self):
        self.discord_outbox.rmdir()

        result = self.run_dev_msg("sonny", "UPDATE", "Full reply.")

        self.assertEqual(result.returncode, 1)
        self.assertIn("DISCORD FAILED", result.stderr)
        self.assertIn("outbox is unavailable", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_zero_matching_panes_fails_without_injection(self):
        result = self.run_dev_msg(
            "jarvis",
            "HELLO",
            "full message",
            FAKE_TMUX_PANES="%4|jarvis|agent|1|1\n",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("TARGET FAILED", result.stderr)
        self.assertIn("no live marked delivery pane", result.stderr)
        self.assertEqual([call["command"] for call in self.calls()], ["list-panes"])

    def test_multiple_matching_panes_fail_without_injection(self):
        result = self.run_dev_msg(
            "jarvis",
            "HELLO",
            "full message",
            FAKE_TMUX_PANES=(
                "%7|jarvis|agent|0|1\n"
                "%9|jarvis|agent|0|1\n"
            ),
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("TARGET FAILED", result.stderr)
        self.assertIn("multiple live marked delivery panes", result.stderr)
        self.assertEqual([call["command"] for call in self.calls()], ["list-panes"])

    def test_load_failure_is_named_and_stops_before_paste(self):
        result = self.run_dev_msg(
            "jarvis",
            "HELLO",
            "full message",
            FAKE_TMUX_FAIL="load-buffer",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("LOAD FAILED", result.stderr)
        commands = [call["command"] for call in self.calls()]
        self.assertNotIn("paste-buffer", commands)
        self.assertNotIn("send-keys", commands)

    def test_paste_failure_never_sends_enter(self):
        result = self.run_dev_msg(
            "jarvis",
            "HELLO",
            "full message",
            FAKE_TMUX_FAIL="paste-buffer",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("PASTE FAILED", result.stderr)
        commands = [call["command"] for call in self.calls()]
        self.assertNotIn("send-keys", commands)

    def test_first_enter_failure_still_attempts_second_enter(self):
        result = self.run_dev_msg(
            "jarvis",
            "HELLO",
            "full message",
            FAKE_TMUX_FAIL_AT="4",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("ENTER FAILED", result.stderr)
        self.assertEqual(self.calls()[-1]["command"], "send-keys")
        self.assertEqual(
            [call["command"] for call in self.calls()].count("send-keys"), 2
        )

    def test_second_enter_failure_uses_same_generic_boundary(self):
        result = self.run_dev_msg(
            "jarvis",
            "HELLO",
            "full message",
            FAKE_TMUX_FAIL_AT="5",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("ENTER FAILED", result.stderr)
        self.assertEqual(
            [call["command"] for call in self.calls()].count("send-keys"), 2
        )

    def test_both_enter_failures_still_attempt_both_calls(self):
        result = self.run_dev_msg(
            "jarvis",
            "HELLO",
            "full message",
            FAKE_TMUX_FAIL="send-keys",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("ENTER FAILED", result.stderr)
        self.assertEqual(
            [call["command"] for call in self.calls()].count("send-keys"), 2
        )

    def test_missing_socket_fails_before_tmux(self):
        self.socket.close()
        self.socket_path.unlink()

        result = self.run_dev_msg("jarvis", "HELLO", "full message")

        self.assertEqual(result.returncode, 1)
        self.assertIn("TARGET FAILED", result.stderr)
        self.assertIn("recipient socket is unavailable", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_missing_inbox_fails_before_tmux(self):
        self.jarvis_inbox.rmdir()

        result = self.run_dev_msg("jarvis", "HELLO", "full message")

        self.assertEqual(result.returncode, 1)
        self.assertIn("STORE FAILED", result.stderr)
        self.assertIn("recipient inbox is unavailable", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_title_must_be_plain_single_line_without_outer_brackets(self):
        result = self.run_dev_msg("jarvis", "[HELLO]", "full message")

        self.assertEqual(result.returncode, 1)
        self.assertIn("dev-msg adds them", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(self.jarvis_inbox.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
