#!/usr/bin/env python3
import os
import pathlib
import pwd
import socket
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"


FAKE_TMUX = r'''#!/usr/bin/env python3
import os
import sys

args = sys.argv[1:]
command = args[args.index("-S") + 2]
if command == "list-panes":
    agent = os.environ["LIFECYCLE_AGENT"]
    print(f"%11|{agent}|agent|0|1")
elif command == "load-buffer":
    sys.stdin.read()
raise SystemExit(0)
'''


class LifecycleTests(unittest.TestCase):
    def test_send_list_read_list_drain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            agent = pwd.getpwuid(os.geteuid()).pw_name
            coms_root = root / "coms"
            inbox = coms_root / agent / "inbox"
            read_dir = coms_root / agent / "read"
            inbox.mkdir(parents=True)
            read_dir.mkdir()
            tmux_dir = root / "tmux"
            tmux_dir.mkdir()
            tmux_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            tmux_socket.bind(str(tmux_dir / f"agent-{agent}"))
            fake_tmux = root / "fake-tmux"
            fake_tmux.write_text(FAKE_TMUX)
            fake_tmux.chmod(0o755)
            env = os.environ.copy()
            env.update(
                FREQ_COMS_TESTING="1",
                FREQ_COMS_ROOT=str(coms_root),
                DEV_MSG_TMUX_DIR=str(tmux_dir),
                DEV_MSG_TMUX_BIN=str(fake_tmux),
                DEV_MSG_FLOCK_BIN="/usr/bin/flock",
                LIFECYCLE_AGENT=agent,
            )
            body = "Lifecycle body line one.\n\nLifecycle body line two."

            sent = subprocess.run(
                [str(BIN / "dev-msg"), agent, "LIFECYCLE ACCEPTANCE", body],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(sent.returncode, 0, sent.stderr)
            files = list(inbox.glob("*.md"))
            self.assertEqual(len(files), 1)
            filename = files[0].name

            listed = subprocess.run(
                [str(BIN / "dev-inbox")],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("1 unread message", listed.stdout)
            self.assertIn(filename, listed.stdout)

            read = subprocess.run(
                [str(BIN / "dev-read"), filename],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(read.returncode, 0, read.stderr)
            self.assertEqual(read.stdout, body)
            self.assertFalse((inbox / filename).exists())
            self.assertTrue((read_dir / filename).exists())

            relisted = subprocess.run(
                [str(BIN / "dev-inbox")],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(relisted.stdout, "0 unread messages.\n")

            drained = subprocess.run(
                [str(BIN / "dev-drain")],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(drained.returncode, 0, drained.stderr)
            self.assertEqual(drained.stdout, "Drained 1 read message.\n")
            self.assertFalse((read_dir / filename).exists())
            tmux_socket.close()


if __name__ == "__main__":
    unittest.main()
