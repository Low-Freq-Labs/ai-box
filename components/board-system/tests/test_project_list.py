#!/usr/bin/env python3
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_REGISTER = ROOT / "bin" / "project-register"
PROJECT_ASSIGN = ROOT / "bin" / "project-assign"
PROJECT_LIST = ROOT / "bin" / "project-list"


class ProjectListTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.board_root = pathlib.Path(self.temp.name) / "board"
        (self.board_root / "projects").mkdir(parents=True)
        self.env = os.environ.copy()
        self.env["FREQ_BOARD_TESTING"] = "1"
        self.env["FREQ_BOARD_ROOT"] = str(self.board_root)
        self.env["FREQ_BOARD_AGENT"] = "finn"

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

    def register(self, name):
        result = self.run_command(PROJECT_REGISTER, name, f"Overview for {name}")
        self.assert_ok(result)

    def assign(self, project_id, agent):
        result = self.run_command(
            PROJECT_ASSIGN, project_id, "active", agent=agent
        )
        self.assert_ok(result)

    def test_lists_project_ids_and_assigned_agents_only(self):
        self.register("PVE Freq")
        self.register("Agent Tools")
        self.assign("PVE-FREQ", "jarvis")
        self.assign("PVE-FREQ", "finn")

        result = self.run_command(PROJECT_LIST)

        self.assert_ok(result)
        self.assertEqual(
            result.stdout,
            "PROJECT       ASSIGNED AGENTS\n"
            "AGENT-TOOLS   (none)\n"
            "PVE-FREQ      finn, jarvis\n"
            "\n2 projects\n",
        )
        self.assertNotIn("Overview", result.stdout)

    def test_empty_board_is_explicit(self):
        result = self.run_command(PROJECT_LIST)
        self.assert_ok(result)
        self.assertEqual(
            result.stdout,
            "PROJECT   ASSIGNED AGENTS\n\n0 projects\n",
        )

    def test_rejects_arguments_and_malformed_project_or_assignment(self):
        usage = self.run_command(PROJECT_LIST, "PVE-FREQ")
        self.assertEqual(usage.returncode, 1)
        self.assertIn("Usage: project-list", usage.stderr)

        self.register("PVE Freq")
        malformed = self.board_root / "projects" / "PVE-FREQ" / "active" / "BAD"
        malformed.mkdir()
        result = self.run_command(PROJECT_LIST)
        self.assertEqual(result.returncode, 1)
        self.assertIn("agent assignment name is invalid", result.stderr)

    @unittest.skipIf(__import__("pathlib").Path("/var/lib/freq-agents/board/projects").exists(),
                     "non-test fallback check requires a host without a live board")
    def test_override_requires_testing_gate(self):
        self.register("PVE Freq")
        env = self.env.copy()
        env.pop("FREQ_BOARD_TESTING")
        result = subprocess.run(
            [str(PROJECT_LIST)],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("project-list: LIST FAILED:", result.stderr)
        self.assertNotIn("PVE-FREQ", result.stdout)


if __name__ == "__main__":
    unittest.main()
