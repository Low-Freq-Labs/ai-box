#!/usr/bin/env python3
import os
import json
import pathlib
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_REGISTER = ROOT / "bin" / "project-register"
PROJECT_ASSIGN = ROOT / "bin" / "project-assign"
TASK_REGISTER = ROOT / "bin" / "task-register"
TASK_READY = ROOT / "bin" / "task-ready"


class ProjectAssignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.board_root = pathlib.Path(self.temp.name) / "board"
        (self.board_root / "projects").mkdir(parents=True)
        self.env = os.environ.copy()
        self.env["FREQ_BOARD_TESTING"] = "1"
        self.env["FREQ_BOARD_ROOT"] = str(self.board_root)
        self.env["FREQ_BOARD_AGENT"] = "finn"
        self.coms_root = pathlib.Path(self.temp.name) / "coms"
        for agent in ("finn", "jarvis", "clancy"):
            (self.coms_root / agent / "inbox").mkdir(parents=True)
            (self.coms_root / agent / "read").mkdir()
        self.env["FREQ_COMS_ROOT"] = str(self.coms_root)
        self.assert_ok(self.run_command(PROJECT_REGISTER, "PVE Freq", "Test"))
        self.project = self.board_root / "projects" / "PVE-FREQ"

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, command, *arguments, agent=None, env=None):
        command_env = (env or self.env).copy()
        if agent:
            command_env["FREQ_BOARD_AGENT"] = agent
        return subprocess.run(
            [str(command), *arguments],
            text=True,
            capture_output=True,
            env=command_env,
            check=False,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_active_assignment_is_exact_agent_queue_and_is_idempotent(self):
        first = self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "active")
        self.assert_ok(first)
        self.assertEqual(first.stdout, "ASSIGNMENT: finn -> active/PVE-FREQ\n")
        assignment = self.project / "active" / "finn"
        self.assertTrue(assignment.is_dir())
        self.assertEqual(stat.S_IMODE(assignment.stat().st_mode), 0o2770)

        second = self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "active")
        self.assert_ok(second)
        self.assertIn("(already assigned)", second.stdout)

    def test_multiple_agents_can_be_assigned_to_one_project(self):
        for agent in ("finn", "clancy", "jarvis"):
            self.assert_ok(
                self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "active", agent=agent)
            )
        self.assertEqual(
            {path.name for path in (self.project / "active").iterdir()},
            {"finn", "clancy", "jarvis"},
        )

    def test_inactive_removes_only_an_empty_agent_queue(self):
        self.assert_ok(self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "active"))
        # Current inactivity requires an actual assessment, even for an empty queue.
        template = self.run_command(ROOT / "bin" / "project-assess", "PVE-FREQ", "--template")
        self.assert_ok(template)
        assessment = json.loads(template.stdout)
        assessment["summary"] = "Empty fixture project inspected; no remaining tasks or prerequisites."
        path = pathlib.Path(self.temp.name) / "assessment.json"
        path.write_text(json.dumps(assessment))
        self.assert_ok(self.run_command(ROOT / "bin" / "project-assess", "PVE-FREQ", "--submit", str(path)))
        inactive = self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "inactive")
        self.assert_ok(inactive)
        self.assertEqual(inactive.stdout, "ASSIGNMENT: finn -> inactive/PVE-FREQ\n")
        self.assertFalse((self.project / "active" / "finn").exists())

        repeated = self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "inactive")
        self.assert_ok(repeated)
        self.assertIn("(already inactive)", repeated.stdout)

    def test_inactive_refuses_to_abandon_owned_tasks(self):
        self.assert_ok(self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "active"))
        self.assert_ok(
            self.run_command(TASK_REGISTER, "PVE-FREQ", "Backend work", "Build it.")
        )
        self.assert_ok(
            self.run_command(TASK_READY, "PVE-FREQ", "Backend work", "finn")
        )

        result = self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "inactive")

        self.assertEqual(result.returncode, 1)
        self.assertIn("missing assessment", result.stderr)
        rejected = self.run_command(ROOT / "bin" / "project-assess", "PVE-FREQ", "--template")
        self.assert_ok(rejected)
        assessment = json.loads(rejected.stdout)
        assessment["summary"] = "Owned work is deliberately retained in this refusal fixture."
        path = pathlib.Path(self.temp.name) / "owned-assessment.json"
        path.write_text(json.dumps(assessment))
        submitted = self.run_command(ROOT / "bin" / "project-assess", "PVE-FREQ", "--submit", str(path))
        self.assertNotEqual(submitted.returncode, 0)
        self.assertIn("owned active work remains", submitted.stderr)
        self.assertTrue((self.project / "active" / "finn" / "Backend work.md").is_file())

    def test_task_assignment_auto_activates_recipient(self):
        self.assert_ok(
            self.run_command(TASK_REGISTER, "PVE-FREQ", "Backend work", "Build it.")
        )
        assignment = self.run_command(
            TASK_READY,
            "PVE-FREQ",
            "Backend work",
            "clancy",
            agent="clancy",
        )
        self.assert_ok(assignment)
        self.assertTrue((self.project / "active" / "clancy").is_dir())
        self.assertTrue(
            (self.project / "active" / "clancy" / "Backend work.md").is_file()
        )

        self.assert_ok(
            self.run_command(TASK_REGISTER, "PVE-FREQ", "Infra work", "Build it.")
        )
        assignment = self.run_command(
            TASK_READY,
            "PVE-FREQ",
            "Infra work",
            "jarvis",
            "Review and complete the infrastructure work.",
        )
        self.assert_ok(assignment)
        self.assertTrue((self.project / "active" / "jarvis").is_dir())
        self.assertTrue(
            (self.project / "active" / "jarvis" / "Infra work.md").is_file()
        )

    @unittest.skipIf(__import__("pathlib").Path("/var/lib/freq-agents/board/projects").exists(),
                     "non-test fallback check requires a host without a live board")
    def test_usage_and_project_validation_fail_closed(self):
        usage = self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "deactive")
        self.assertEqual(usage.returncode, 1)
        self.assertIn("project-assign <project-id> inactive", usage.stderr)

        missing = self.run_command(PROJECT_ASSIGN, "MISSING", "active")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("project does not exist: MISSING", missing.stderr)

        env = self.env.copy()
        env.pop("FREQ_BOARD_TESTING")
        no_override = self.run_command(
            PROJECT_ASSIGN, "PVE-FREQ", "active", env=env
        )
        self.assertEqual(no_override.returncode, 1)
        self.assertIn("project-assign: ASSIGNMENT FAILED:", no_override.stderr)
        self.assertFalse((self.project / "active" / "finn").exists())


if __name__ == "__main__":
    unittest.main()
