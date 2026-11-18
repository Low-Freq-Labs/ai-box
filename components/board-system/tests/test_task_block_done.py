#!/usr/bin/env python3
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_REGISTER = ROOT / "bin" / "project-register"
PROJECT_ASSIGN = ROOT / "bin" / "project-assign"
TASK_REGISTER = ROOT / "bin" / "task-register"
TASK_READY = ROOT / "bin" / "task-ready"
TASK_BLOCK = ROOT / "bin" / "task-block"
TASK_DONE = ROOT / "bin" / "task-done"


class TaskBlockDoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.board_root = self.root / "board"
        (self.board_root / "projects").mkdir(parents=True)
        self.coms_root = self.root / "coms"
        for agent in ("finn", "jarvis"):
            (self.coms_root / agent / "inbox").mkdir(parents=True)
            (self.coms_root / agent / "read").mkdir()
        self.env = os.environ.copy()
        self.env.update(
            FREQ_BOARD_TESTING="1",
            FREQ_BOARD_ROOT=str(self.board_root),
            FREQ_BOARD_AGENT="finn",
            FREQ_COMS_ROOT=str(self.coms_root),
            FREQ_BOARD_ALERT_TEST_SINK=str(self.root / "alerts.jsonl"),
        )
        self.assert_ok(self.command(PROJECT_REGISTER, "PVE Freq", "Test"))
        self.assert_ok(self.command(PROJECT_ASSIGN, "PVE-FREQ", "active"))

    def tearDown(self):
        self.temp.cleanup()

    def command(self, executable, *arguments, agent=None):
        env = self.env.copy()
        if agent:
            env["FREQ_BOARD_AGENT"] = agent
        return subprocess.run(
            [str(executable), *arguments],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def active_task(self, task_name):
        self.assert_ok(
            self.command(TASK_REGISTER, "PVE-FREQ", task_name, f"Do {task_name}.")
        )
        self.assert_ok(self.command(TASK_READY, "PVE-FREQ", task_name, "finn"))

    def test_block_moves_uniquely_owned_task_and_records_reason(self):
        self.active_task("Backend API")
        result = self.command(TASK_BLOCK, "Backend API", "Waiting for host API")
        self.assert_ok(result)
        self.assertEqual(result.stdout, "BLOCKED: Backend API -> blocked (PVE-FREQ)\n")
        task = self.board_root / "projects/PVE-FREQ/blocked/Backend API.md"
        self.assertIn("## Blocked reason\n\nWaiting for host API", task.read_text())

    def test_done_moves_uniquely_owned_task_terminal(self):
        self.active_task("Finished work")
        note = (
            "Artifact: build/output.json\n"
            "Verification: 18 tests passed\n"
            "Outcome: export clean\n"
            "Known limitations: none"
        )
        result = self.command(TASK_DONE, "Finished work", note)
        self.assert_ok(result)
        self.assertEqual(result.stdout, "DONE: Finished work -> done (PVE-FREQ)\n")
        task = self.board_root / "projects/PVE-FREQ/done/Finished work.md"
        self.assertTrue(task.is_file())
        contents = task.read_text()
        self.assertIn("## Completion note", contents)
        self.assertIn(note, contents)

    def test_nonowner_cannot_block_or_complete(self):
        self.active_task("Owned work")
        for executable, arguments in (
            (TASK_BLOCK, ("Owned work", "Not mine")),
            (TASK_DONE, ("Owned work", "Not my completion.")),
        ):
            result = self.command(executable, *arguments, agent="jarvis")
            self.assertEqual(result.returncode, 1)
            self.assertIn("no active task owned by jarvis", result.stderr)
        self.assertTrue(
            (self.board_root / "projects/PVE-FREQ/active/finn/Owned work.md").is_file()
        )

    def test_owned_title_must_be_unique_and_reason_is_one_line(self):
        self.active_task("Repeated work")
        self.assert_ok(self.command(PROJECT_REGISTER, "Other", "Other"))
        self.assert_ok(self.command(PROJECT_ASSIGN, "OTHER", "active"))
        self.assert_ok(
            self.command(TASK_REGISTER, "OTHER", "Repeated work", "Again.")
        )
        self.assert_ok(self.command(TASK_READY, "OTHER", "Repeated work", "finn"))
        ambiguous = self.command(TASK_DONE, "Repeated work", "Completed twice.")
        self.assertEqual(ambiguous.returncode, 1)
        self.assertIn("ambiguous across projects", ambiguous.stderr)

        bad_reason = self.command(TASK_BLOCK, "Repeated work", "line one\nline two")
        self.assertEqual(bad_reason.returncode, 1)
        self.assertIn("one non-empty line", bad_reason.stderr)

    def test_usage_is_exact(self):
        blocked = self.command(TASK_BLOCK)
        done = self.command(TASK_DONE)
        missing_note = self.command(TASK_DONE, "Missing note")
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("task-block <task-name> <reason>", blocked.stderr)
        self.assertEqual(done.returncode, 1)
        self.assertIn("task-done <task-name> <completion-note>", done.stderr)
        self.assertEqual(missing_note.returncode, 1)
        self.assertIn("task-done <task-name> <completion-note>", missing_note.stderr)


if __name__ == "__main__":
    unittest.main()
