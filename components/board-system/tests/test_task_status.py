#!/usr/bin/env python3
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_REGISTER = ROOT / "bin" / "project-register"
PROJECT_ASSIGN = ROOT / "bin" / "project-assign"
TASK_REGISTER = ROOT / "bin" / "task-register"
TASK_STATUS = ROOT / "bin" / "task-status"


class TaskStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.board_root = pathlib.Path(self.temp.name) / "board"
        (self.board_root / "projects").mkdir(parents=True)
        self.env = os.environ.copy()
        self.env.update(
            FREQ_BOARD_TESTING="1",
            FREQ_BOARD_ROOT=str(self.board_root),
            FREQ_BOARD_AGENT="finn",
        )
        self.assert_ok(self.command(PROJECT_REGISTER, "PVE Freq", "Test"))
        self.assert_ok(
            self.command(TASK_REGISTER, "PVE-FREQ", "Backend API", "Build it.")
        )

    def tearDown(self):
        self.temp.cleanup()

    def command(self, executable, *arguments):
        return subprocess.run(
            [str(executable), *arguments],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reports_exact_task_state_without_mutation(self):
        before = list((self.board_root / "projects/PVE-FREQ/ready").iterdir())
        result = self.command(TASK_STATUS, "PVE-FREQ", "Backend API")
        self.assert_ok(result)
        self.assertIn("TASK: Backend API\nSTATUS: ready\n", result.stdout)
        self.assertIn("FILE:", result.stdout)
        self.assertEqual(
            list((self.board_root / "projects/PVE-FREQ/ready").iterdir()), before
        )

    def test_reports_active_owner_and_blocked_reason(self):
        project = self.board_root / "projects/PVE-FREQ"
        (project / "active/finn").mkdir()
        task = project / "ready/Backend API.md"
        task.rename(project / "active/finn/Backend API.md")
        active = self.command(TASK_STATUS, "PVE-FREQ", "Backend API")
        self.assert_ok(active)
        self.assertIn("STATUS: active\nOWNER: finn\n", active.stdout)

        task = project / "active/finn/Backend API.md"
        task.write_text(
            task.read_text()
            + '\n<!-- FREQ_BOARD_BLOCKED_BEGIN -->\n'
            + '<!-- FREQ_BOARD_BLOCKED_REASON_JSON: "Waiting for host" -->\n'
            + '## Blocked reason\n\nWaiting for host\n'
            + '<!-- FREQ_BOARD_BLOCKED_END -->\n'
        )
        task.rename(project / "blocked/Backend API.md")
        blocked = self.command(TASK_STATUS, "PVE-FREQ", "Backend API")
        self.assert_ok(blocked)
        self.assertIn("STATUS: blocked\nREASON: Waiting for host\n", blocked.stdout)

    def test_duplicate_or_missing_task_fails_closed(self):
        project = self.board_root / "projects/PVE-FREQ"
        shutil.copy2(
            project / "ready/Backend API.md", project / "done/Backend API.md"
        )
        duplicate = self.command(TASK_STATUS, "PVE-FREQ", "Backend API")
        self.assertEqual(duplicate.returncode, 1)
        self.assertIn("multiple board locations", duplicate.stderr)

        missing = self.command(TASK_STATUS, "PVE-FREQ", "Missing")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("task does not exist", missing.stderr)

    def test_latest_handoff_preview_is_read_only_and_bounded(self):
        import sys
        sys.path.insert(0, str(ROOT / 'lib'))
        from freq_board import append_task_note
        project = self.board_root / 'projects/PVE-FREQ'
        task = project / 'ready/Backend API.md'
        content = append_task_note(task.read_text(), 'Assignment note', 'finn', 'OLD NOTE')
        content = append_task_note(content, 'Transfer handoff', 'jarvis',
                                   'LATEST ACTION\n' + ('long detail ' * 300))
        task.write_text(content)
        for status in ('ready', 'archive'):
            if status == 'archive':
                task = task.rename(project / 'archive/Backend API.md')
            before = task.read_bytes()
            result = self.command(TASK_STATUS, 'PVE-FREQ', 'Backend API')
            self.assert_ok(result)
            self.assertIn('LATEST ACTION', result.stdout)
            self.assertIn('Recorded by: `jarvis`', result.stdout)
            self.assertNotIn('OLD NOTE', result.stdout)
            self.assertIn('Preview only', result.stdout)
            self.assertLess(len(result.stdout), 1800)
            self.assertEqual(task.read_bytes(), before)

    def test_note_free_task_has_no_invented_note(self):
        result = self.command(TASK_STATUS, 'PVE-FREQ', 'Backend API')
        self.assert_ok(result)
        self.assertNotIn('LATEST NOTE', result.stdout)

    def test_mutating_forms_and_extra_arguments_are_rejected(self):
        for arguments in (
            ("active",),
            ("assign", "jarvis"),
            ("blocked", "reason"),
            ("ready",),
            ("done",),
        ):
            with self.subTest(arguments=arguments):
                result = self.command(
                    TASK_STATUS, "PVE-FREQ", "Backend API", *arguments
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    result.stderr,
                    "Usage: task-status <project-id> <task-name>\n",
                )


if __name__ == "__main__":
    unittest.main()
