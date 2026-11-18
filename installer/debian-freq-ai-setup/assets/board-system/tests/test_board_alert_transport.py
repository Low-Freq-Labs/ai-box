#!/usr/bin/env python3
import json
import os
import pathlib
import socket
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from freq_board_alert import BoardAlertError, capture_visible, send_alert


class BoardAlertTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.tmux_dir = self.root / "tmux"
        self.tmux_dir.mkdir()
        self.socket_path = self.tmux_dir / "agent-jarvis"
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.socket_path))
        self.log = self.root / "tmux.jsonl"
        self.fake_tmux = self.root / "fake-tmux"
        self.fake_tmux.write_text(
            """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
import time
stdin = sys.stdin.read() if "load-buffer" in args else None
with open(os.environ["FAKE_TMUX_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"args": args, "stdin": stdin, "at": time.monotonic()}) + "\\n")
if "list-panes" in args:
    print(os.environ.get("FAKE_TMUX_ROWS", "%7|jarvis|agent|0|1"))
elif "capture-pane" in args:
    print(os.environ.get("FAKE_TMUX_CAPTURE", "visible pane"))
elif "send-keys" in args and os.environ.get("FAKE_TMUX_FAIL_SEND") == "1":
    raise SystemExit(1)
""",
            encoding="utf-8",
        )
        self.fake_tmux.chmod(0o755)
        self.env = {
            "FREQ_BOARD_TESTING": "1",
            "FREQ_BOARD_ALERT_TMUX_DIR": str(self.tmux_dir),
            "FREQ_BOARD_ALERT_TMUX_BIN": str(self.fake_tmux),
            "FREQ_BOARD_ALERT_TEST_SINK": "",
            "FAKE_TMUX_LOG": str(self.log),
            "FAKE_TMUX_ROWS": "%7|jarvis|agent|0|1",
        }

    def tearDown(self):
        self.socket.close()
        self.temp.cleanup()

    def calls(self):
        return [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]

    def test_send_uses_exact_pane_paste_then_two_independent_enters(self):
        with mock.patch.dict(os.environ, self.env, clear=False):
            pane = send_alert("jarvis", "BOARD-ALERT: Test")

        self.assertEqual(pane, "%7")
        calls = self.calls()
        operations = [
            next(
                operation
                for operation in (
                    "list-panes",
                    "load-buffer",
                    "paste-buffer",
                    "send-keys",
                )
                if operation in call["args"]
            )
            for call in calls
        ]
        self.assertEqual(
            operations,
            ["list-panes", "load-buffer", "paste-buffer", "send-keys", "send-keys"],
        )
        self.assertEqual(calls[1]["stdin"], "BOARD-ALERT: Test")
        self.assertIn("%7", calls[2]["args"])
        self.assertGreaterEqual(calls[3]['at'] - calls[2]['at'], 0.45)
        self.assertGreaterEqual(calls[4]['at'] - calls[3]['at'], 0.45)

    def test_both_enter_calls_run_even_when_they_fail(self):
        env = dict(self.env)
        env["FAKE_TMUX_FAIL_SEND"] = "1"
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(BoardAlertError, "Enter strokes"):
                send_alert("jarvis", "BOARD-ALERT: Test")
        send_calls = [call for call in self.calls() if "send-keys" in call["args"]]
        self.assertEqual(len(send_calls), 2)

    def test_capture_uses_exact_visible_joined_pane_contract(self):
        env = dict(self.env)
        env["FAKE_TMUX_CAPTURE"] = "Working (1m 02s)"
        with mock.patch.dict(os.environ, env, clear=False):
            pane, capture = capture_visible("jarvis")
        self.assertEqual((pane, capture), ("%7", "Working (1m 02s)\n"))
        capture_call = self.calls()[-1]["args"]
        self.assertIn("capture-pane", capture_call)
        self.assertIn("-J", capture_call)

    def test_zero_and_multiple_marked_panes_fail_closed(self):
        cases = (
            ("%7|jarvis|agent|1|1", "no live marked"),
            (
                "%7|jarvis|agent|0|1\n%8|jarvis|agent|0|1",
                "multiple live marked",
            ),
        )
        for rows, expected in cases:
            with self.subTest(rows=rows):
                env = dict(self.env)
                env["FAKE_TMUX_ROWS"] = rows
                with mock.patch.dict(os.environ, env, clear=False):
                    with self.assertRaisesRegex(BoardAlertError, expected):
                        send_alert("jarvis", "BOARD-ALERT: Test")


if __name__ == "__main__":
    unittest.main()
