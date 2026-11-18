#!/usr/bin/env python3
import os
import pathlib
import pwd
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV_INBOX = ROOT / "bin" / "dev-inbox"


class DevInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.agent = pwd.getpwuid(os.geteuid()).pw_name
        self.coms_root = self.root / "coms"
        self.inbox = self.coms_root / self.agent / "inbox"
        self.inbox.mkdir(parents=True)
        self.env = os.environ.copy()
        self.env["FREQ_COMS_TESTING"] = "1"
        self.env["FREQ_COMS_ROOT"] = str(self.coms_root)

    def tearDown(self):
        self.temp.cleanup()

    def run_dev_inbox(self, *args):
        return subprocess.run(
            [str(DEV_INBOX), *args],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def test_empty_inbox(self):
        result = self.run_dev_inbox()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0 unread messages.\n")

    def test_lists_exact_messages_oldest_to_newest_without_mutation(self):
        newest = "2026-09-01_210000_000000003_300_clancy.md"
        oldest = "2026-09-01_190000_000000001_100_finn.md"
        middle = "2026-09-01_200000_000000002_200_jarvis.md"
        for filename in (newest, oldest, middle):
            (self.inbox / filename).write_text(filename)
        before = {
            path.name: (path.stat().st_ino, path.read_text())
            for path in self.inbox.iterdir()
        }

        result = self.run_dev_inbox()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "3 unread messages:\n\n" + "\n".join((oldest, middle, newest)) + "\n",
        )
        after = {
            path.name: (path.stat().st_ino, path.read_text())
            for path in self.inbox.iterdir()
        }
        self.assertEqual(after, before)

    def test_ignores_non_message_entries(self):
        (self.inbox / ".dev-msg.pending").write_text("temporary")
        (self.inbox / "notes.md").write_text("not a generated message")
        (self.inbox / "2026-09-01_190000_000000001_100_finn.md").symlink_to(
            self.inbox / "notes.md"
        )

        result = self.run_dev_inbox()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0 unread messages.\n")

    def test_arguments_are_rejected(self):
        result = self.run_dev_inbox("--triage")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "Usage: dev-inbox\n")


if __name__ == "__main__":
    unittest.main()
