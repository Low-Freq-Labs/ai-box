#!/usr/bin/env python3
import os
import pathlib
import pwd
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV_DRAIN = ROOT / "bin" / "dev-drain"
MESSAGE_1 = "2026-09-01_063254_262273409_1338817_finn.md"
MESSAGE_2 = "2026-09-01_064102_736251904_1349921_clancy.md"


class DevDrainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.agent = pwd.getpwuid(os.geteuid()).pw_name
        self.coms_root = self.root / "coms"
        self.agent_root = self.coms_root / self.agent
        self.inbox = self.agent_root / "inbox"
        self.read_dir = self.agent_root / "read"
        self.inbox.mkdir(parents=True)
        self.read_dir.mkdir()
        self.env = os.environ.copy()
        self.env["FREQ_COMS_TESTING"] = "1"
        self.env["FREQ_COMS_ROOT"] = str(self.coms_root)

    def tearDown(self):
        self.temp.cleanup()

    def run_dev_drain(self, *args):
        return subprocess.run(
            [str(DEV_DRAIN), *args],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def test_empty_read_directory(self):
        result = self.run_dev_drain()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Drained 0 read messages.\n")

    def test_deletes_only_read_messages_and_never_touches_inbox(self):
        (self.read_dir / MESSAGE_1).write_text("old read one")
        (self.read_dir / MESSAGE_2).write_text("old read two")
        (self.read_dir / "notes.md").write_text("not a generated message")
        unread = self.inbox / MESSAGE_1
        unread.write_text("still unread")

        result = self.run_dev_drain()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Drained 2 read messages.\n")
        self.assertFalse((self.read_dir / MESSAGE_1).exists())
        self.assertFalse((self.read_dir / MESSAGE_2).exists())
        self.assertEqual((self.read_dir / "notes.md").read_text(), "not a generated message")
        self.assertEqual(unread.read_text(), "still unread")

    def test_generated_symlink_fails_before_deleting_any_messages(self):
        regular = self.read_dir / MESSAGE_1
        regular.write_text("keep on failure")
        outside = self.root / "outside"
        outside.write_text("target")
        (self.read_dir / MESSAGE_2).symlink_to(outside)

        result = self.run_dev_drain()

        self.assertEqual(result.returncode, 1)
        self.assertIn("not a regular file", result.stderr)
        self.assertEqual(regular.read_text(), "keep on failure")
        self.assertEqual(outside.read_text(), "target")

    def test_arguments_are_rejected(self):
        result = self.run_dev_drain("--all")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "Usage: dev-drain\n")


if __name__ == "__main__":
    unittest.main()
