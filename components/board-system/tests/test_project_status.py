#!/usr/bin/env python3
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_REGISTER = ROOT / "bin" / "project-register"
PROJECT_ASSIGN = ROOT / "bin" / "project-assign"
PROJECT_STATUS = ROOT / "bin" / "project-status"
TASK_REGISTER = ROOT / "bin" / "task-register"
TASK_READY = ROOT / "bin" / "task-ready"
TASK_BLOCK = ROOT / "bin" / "task-block"
TASK_DONE = ROOT / "bin" / "task-done"


class ProjectStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.board_root = pathlib.Path(self.temp.name) / "board"
        (self.board_root / "projects").mkdir(parents=True)
        self.env = os.environ.copy()
        self.env["FREQ_BOARD_TESTING"] = "1"
        self.env["FREQ_BOARD_ROOT"] = str(self.board_root)
        self.env["FREQ_BOARD_AGENT"] = "finn"
        self.coms_root = pathlib.Path(self.temp.name) / "coms"
        for agent in ("finn", "clancy"):
            (self.coms_root / agent / "inbox").mkdir(parents=True)
            (self.coms_root / agent / "read").mkdir()
        self.env["FREQ_COMS_ROOT"] = str(self.coms_root)
        self.env["FREQ_BOARD_ALERT_TEST_SINK"] = str(
            pathlib.Path(self.temp.name) / "alerts.jsonl"
        )
        self.assert_ok(
            self.run_command(
                PROJECT_REGISTER,
                "PVE Freq",
                "Manage the PVE frequency platform.",
            )
        )
        self.project = self.board_root / "projects" / "PVE-FREQ"

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, command, *arguments, agent=None):
        env = self.env.copy()
        if agent:
            env["FREQ_BOARD_AGENT"] = agent
        return subprocess.run(
            [str(command), *arguments],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def register_task(self, title):
        self.assert_ok(
            self.run_command(TASK_REGISTER, "PVE-FREQ", title, f"Do {title}.")
        )

    def test_empty_project_is_exact_four_status_tree(self):
        result = self.run_command(PROJECT_STATUS, "PVE-FREQ")
        self.assert_ok(result)
        self.assertEqual(
            result.stdout,
            "PROJECT: PVE-FREQ\n"
            "├── ready/\n"
            "│   └── (empty)\n"
            "├── active/\n"
            "│   └── (empty)\n"
            "├── blocked/\n"
            "│   └── (empty)\n"
            "└── done/\n"
            "    └── (empty)\n",
        )

    def test_populated_tree_shows_task_names_owners_and_blocked_reasons(self):
        for agent in ("finn", "clancy"):
            self.assert_ok(
                self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "active", agent=agent)
            )
        for title in ("Backend API", "Frontend form", "Storage review", "Discovery"):
            self.register_task(title)
        self.assert_ok(
            self.run_command(TASK_READY, "PVE-FREQ", "Backend API", "finn")
        )
        self.assert_ok(
            self.run_command(
                TASK_READY,
                "PVE-FREQ",
                "Storage review",
                "clancy",
                agent="clancy",
            )
        )
        self.assert_ok(
            self.run_command(
                TASK_BLOCK,
                "Storage review",
                'Recheck "OK" after storage changes',
                agent="clancy",
            )
        )
        self.assert_ok(
            self.run_command(TASK_READY, "PVE-FREQ", "Discovery", "finn")
        )
        self.assert_ok(
            self.run_command(TASK_DONE, "Discovery", "Discovery findings recorded.")
        )

        result = self.run_command(PROJECT_STATUS, "PVE-FREQ")

        self.assert_ok(result)
        self.assertEqual(
            result.stdout,
            "PROJECT: PVE-FREQ\n"
            "├── ready/\n"
            "│   └── Frontend form\n"
            "├── active/\n"
            "│   ├── clancy/\n"
            "│   │   └── (empty)\n"
            "│   └── finn/\n"
            "│       └── Backend API\n"
            "├── blocked/\n"
            "│   └── Storage review\n"
            '│       Reason: Recheck "OK" after storage changes\n'
            "└── done/\n"
            "    └── Discovery\n",
        )

    def test_task_names_are_alphabetical_for_display_only(self):
        for title in ("Zulu task", "alpha task", "Middle task"):
            self.register_task(title)
        result = self.run_command(PROJECT_STATUS, "PVE-FREQ")
        self.assert_ok(result)
        self.assertLess(result.stdout.index("alpha task"), result.stdout.index("Middle task"))
        self.assertLess(result.stdout.index("Middle task"), result.stdout.index("Zulu task"))

    def test_corrupt_ready_contents_fail_closed_without_overview(self):
        self.register_task("Opaque ready task")
        (self.project / "overview.md").unlink()
        (self.project / "ready" / "Opaque ready task.md").write_bytes(b"\xff\xfe")
        result = self.run_command(PROJECT_STATUS, "PVE-FREQ")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STATUS FAILED", result.stderr)
        self.assertIn("CORRUPT:", result.stdout)
        self.assertIn("ERROR: ready/Opaque ready task.md:", result.stdout)

    def test_blocked_reason_is_required_and_fail_closed(self):
        self.register_task("Broken blocker")
        task = self.project / "ready" / "Broken blocker.md"
        task.rename(self.project / "blocked" / task.name)
        result = self.run_command(PROJECT_STATUS, "PVE-FREQ")
        self.assertEqual(result.returncode, 1)
        self.assertIn("blocked task has no reason: Broken blocker", result.stderr)

    def test_usage_and_unknown_project_fail_closed(self):
        usage = self.run_command(PROJECT_STATUS)
        self.assertEqual(usage.returncode, 1)
        self.assertIn("Usage: project-status <project-id>", usage.stderr)
        missing = self.run_command(PROJECT_STATUS, "MISSING")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("project does not exist: MISSING", missing.stderr)


if __name__ == "__main__":
    unittest.main()
