#!/usr/bin/env python3
import os
import pathlib
import pwd
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV_READ = ROOT / "bin" / "dev-read"
MESSAGE = "2026-09-01_063254_262273409_1338817_finn.md"


class DevReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.reader = pwd.getpwuid(os.geteuid()).pw_name
        self.coms_root = self.root / "coms"
        self.agent_root = self.coms_root / self.reader
        self.inbox = self.agent_root / "inbox"
        self.read_dir = self.agent_root / "read"
        self.inbox.mkdir(parents=True)
        self.read_dir.mkdir()
        self.env = os.environ.copy()
        self.env["FREQ_COMS_TESTING"] = "1"
        self.env["FREQ_COMS_ROOT"] = str(self.coms_root)

    def tearDown(self):
        self.temp.cleanup()

    def run_dev_read(self, filename=MESSAGE):
        return subprocess.run(
            [str(DEV_READ), filename],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def test_first_read_moves_then_prints_exact_body(self):
        body = "Complete message line one.\n\nComplete message line two."
        unread = self.inbox / MESSAGE
        unread.write_text(body)

        result = self.run_dev_read()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, body)
        self.assertFalse(unread.exists())
        self.assertEqual((self.read_dir / MESSAGE).read_text(), body)

    def test_already_read_message_can_be_printed_again(self):
        body = "Previously read body."
        (self.read_dir / MESSAGE).write_text(body)

        result = self.run_dev_read()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, body)
        self.assertFalse((self.inbox / MESSAGE).exists())

    def test_message_in_both_locations_fails_without_overwrite(self):
        (self.inbox / MESSAGE).write_text("unread copy")
        (self.read_dir / MESSAGE).write_text("read copy")

        result = self.run_dev_read()

        self.assertEqual(result.returncode, 1)
        self.assertIn("exists in both", result.stderr)
        self.assertEqual((self.inbox / MESSAGE).read_text(), "unread copy")
        self.assertEqual((self.read_dir / MESSAGE).read_text(), "read copy")

    def test_missing_message_fails(self):
        result = self.run_dev_read()

        self.assertEqual(result.returncode, 1)
        self.assertIn("message not found", result.stderr)

    def test_path_traversal_is_rejected(self):
        result = self.run_dev_read(f"../{MESSAGE}")

        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid exact message filename", result.stderr)


if __name__ == "__main__":
    unittest.main()
