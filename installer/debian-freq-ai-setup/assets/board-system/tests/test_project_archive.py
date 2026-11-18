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
PROJECT_STATUS = ROOT / "bin" / "project-status"
PROJECT_ARCHIVE = ROOT / "bin" / "project-archive"
TASK_REGISTER = ROOT / "bin" / "task-register"
TASK_READY = ROOT / "bin" / "task-ready"
TASK_DONE = ROOT / "bin" / "task-done"
TASK_STATUS = ROOT / "bin" / "task-status"


class ProjectArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.board_root = self.root / "board"
        (self.board_root / "projects").mkdir(parents=True)
        self.coms_root = self.root / "coms"
        (self.coms_root / "finn" / "inbox").mkdir(parents=True)
        (self.coms_root / "finn" / "read").mkdir()
        self.env = os.environ.copy()
        self.env.update(
            FREQ_BOARD_TESTING="1",
            FREQ_BOARD_ROOT=str(self.board_root),
            FREQ_BOARD_AGENT="finn",
            FREQ_COMS_ROOT=str(self.coms_root),
            FREQ_BOARD_ALERT_TEST_SINK=str(self.root / "alerts.jsonl"),
        )
        self.assert_ok(
            self.command(PROJECT_REGISTER, "PVE Freq", "Archive acceptance.")
        )
        self.assert_ok(self.command(PROJECT_ASSIGN, "PVE-FREQ", "active"))
        self.project = self.board_root / "projects" / "PVE-FREQ"

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

    def complete(self, task_name):
        self.assert_ok(
            self.command(
                TASK_REGISTER,
                "PVE-FREQ",
                task_name,
                f"Complete {task_name}.",
            )
        )
        self.assert_ok(
            self.command(TASK_READY, "PVE-FREQ", task_name, "finn")
        )
        note = (
            f"Artifact: {task_name}.txt\n"
            "Verification: acceptance passed\n"
            "Outcome: complete\n"
            "Known limitations: none"
        )
        self.assert_ok(self.command(TASK_DONE, task_name, note))
        return note

    def test_archives_one_exact_done_task_and_preserves_evidence(self):
        note = self.complete("Backend API")
        self.complete("Frontend form")

        result = self.command(PROJECT_ARCHIVE, "PVE-FREQ", "Backend API")

        self.assert_ok(result)
        self.assertEqual(
            result.stdout,
            "ARCHIVED: Backend API -> PVE-FREQ/archive/Backend API.md\n",
        )
        archived = self.project / "archive" / "Backend API.md"
        self.assertTrue(archived.is_file())
        self.assertFalse((self.project / "done" / "Backend API.md").exists())
        content = archived.read_text(encoding="utf-8")
        self.assertIn(note, content)
        self.assertIn("**ARCHIVE**", content)

        status = self.command(TASK_STATUS, "PVE-FREQ", "Backend API")
        self.assert_ok(status)
        self.assertIn("STATUS: archive\n", status.stdout)
        self.assertIn(f"FILE: {archived}\n", status.stdout)

        project_status = self.command(PROJECT_STATUS, "PVE-FREQ")
        self.assert_ok(project_status)
        self.assertNotIn("Backend API", project_status.stdout)
        self.assertIn("Frontend form", project_status.stdout)
        self.assertNotIn("archive/", project_status.stdout)

    def test_all_flushes_done_queue_and_is_idempotent(self):
        for task_name in ("Zulu task", "alpha task", "Middle task"):
            self.complete(task_name)

        result = self.command(PROJECT_ARCHIVE, "PVE-FREQ", "all")

        self.assert_ok(result)
        self.assertEqual(
            result.stdout,
            "ARCHIVED: PVE-FREQ done -> archive (3 tasks)\n",
        )
        self.assertEqual(list((self.project / "done").iterdir()), [])
        self.assertEqual(
            {path.name for path in (self.project / "archive").iterdir()},
            {"Zulu task.md", "alpha task.md", "Middle task.md"},
        )

        repeated = self.command(PROJECT_ARCHIVE, "PVE-FREQ", "all")
        self.assert_ok(repeated)
        self.assertEqual(
            repeated.stdout,
            "ARCHIVED: PVE-FREQ nothing moved: done queue already empty; 3 tasks retained in archive\n",
        )

    def test_concurrent_archive_reports_one_move_and_one_noop(self):
        for name in ('One', 'Two'):
            self.complete(name)
        callers = [subprocess.Popen([str(PROJECT_ARCHIVE), 'PVE-FREQ', 'all'],
                                    env=dict(self.env, FREQ_BOARD_AGENT=agent),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                   for agent in ('finn', 'jarvis')]
        results = [process.communicate(timeout=10) for process in callers]
        for process, (_, stderr) in zip(callers, results):
            self.assertEqual(process.returncode, 0, stderr)
        self.assertCountEqual([stdout for stdout, _ in results], [
            'ARCHIVED: PVE-FREQ done -> archive (2 tasks)\n',
            'ARCHIVED: PVE-FREQ nothing moved: done queue already empty; 2 tasks retained in archive\n'])
        self.assertEqual(list((self.project / 'done').iterdir()), [])
        for path in (self.project / 'archive').iterdir():
            self.assertEqual(path.read_text().count('**ARCHIVE**'), 1)

    def test_empty_project_noop_changes_nothing(self):
        before = snapshot(self.project)
        result = self.command(PROJECT_ARCHIVE, 'PVE-FREQ', 'all')
        self.assert_ok(result)
        self.assertIn('nothing moved: done queue already empty; 0 tasks retained', result.stdout)
        self.assertEqual(snapshot(self.project), before)

    def test_show_lists_archive_names_alphabetically_without_dumping_contents(self):
        for task_name in ("Zulu task", "alpha task", "Middle task"):
            self.complete(task_name)
        self.assert_ok(self.command(PROJECT_ARCHIVE, "PVE-FREQ", "all"))

        before = snapshot(self.project)
        result = self.command(PROJECT_ARCHIVE, "PVE-FREQ", "show")

        self.assert_ok(result)
        self.assertEqual(
            result.stdout,
            "ARCHIVE: PVE-FREQ\n"
            "├── alpha task\n"
            "├── Middle task\n"
            "└── Zulu task\n",
        )
        self.assertNotIn("Completion note", result.stdout)
        self.assertEqual(snapshot(self.project), before)

    def test_show_empty_archive_is_explicit(self):
        result = self.command(PROJECT_ARCHIVE, "PVE-FREQ", "show")
        self.assert_ok(result)
        self.assertEqual(
            result.stdout,
            "ARCHIVE: PVE-FREQ\n"
            "└── (empty)\n",
        )

    def test_only_done_tasks_can_be_archived(self):
        self.assert_ok(
            self.command(
                TASK_REGISTER,
                "PVE-FREQ",
                "Ready task",
                "Not complete.",
            )
        )
        result = self.command(PROJECT_ARCHIVE, "PVE-FREQ", "Ready task")
        self.assertEqual(result.returncode, 1)
        self.assertIn("task must be done to archive: Ready task", result.stderr)
        self.assertTrue((self.project / "ready" / "Ready task.md").is_file())

        self.complete("Done task")
        self.assert_ok(self.command(PROJECT_ARCHIVE, "PVE-FREQ", "Done task"))
        repeated = self.command(PROJECT_ARCHIVE, "PVE-FREQ", "Done task")
        self.assertEqual(repeated.returncode, 1)
        self.assertIn("task is already archived: Done task", repeated.stderr)

    def test_all_preflights_duplicate_or_invalid_paths_before_mutation(self):
        self.complete("First done")
        self.complete("Duplicate done")
        shutil.copy2(
            self.project / "done" / "Duplicate done.md",
            self.project / "archive" / "Duplicate done.md",
        )
        before = snapshot(self.project)

        result = self.command(PROJECT_ARCHIVE, "PVE-FREQ", "all")

        self.assertEqual(result.returncode, 1)
        self.assertIn("task exists in multiple board locations", result.stderr)
        self.assertEqual(snapshot(self.project), before)

    def test_usage_unknown_project_and_extra_arguments_fail_closed(self):
        for arguments in (
            (),
            ("PVE-FREQ",),
            ("PVE-FREQ", "all", "extra"),
        ):
            with self.subTest(arguments=arguments):
                result = self.command(PROJECT_ARCHIVE, *arguments)
                self.assertEqual(result.returncode, 1)
                self.assertIn(
                    "project-archive <project-id> <all|task-name|show>",
                    result.stderr,
                )
        missing = self.command(PROJECT_ARCHIVE, "MISSING", "show")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("project does not exist: MISSING", missing.stderr)


def snapshot(root):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_file():
            result[relative] = path.read_bytes()
        elif path.is_symlink():
            result[relative] = ("symlink", os.readlink(path))
        else:
            result[relative] = "directory"
    return result


if __name__ == "__main__":
    unittest.main()
