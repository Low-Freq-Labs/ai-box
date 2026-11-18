#!/usr/bin/env python3
import json
import os
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
TASK_TRANSFER = ROOT / "bin" / "task-transfer"


class TaskTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.board_root = self.root / "board"
        (self.board_root / "projects").mkdir(parents=True)
        self.coms_root = self.root / "coms"
        for agent in ("finn", "jarvis", "clancy"):
            (self.coms_root / agent / "inbox").mkdir(parents=True)
            (self.coms_root / agent / "read").mkdir()
        self.alert_sink = self.root / "alerts.jsonl"
        self.env = os.environ.copy()
        self.env.update(
            FREQ_BOARD_TESTING="1",
            FREQ_BOARD_ROOT=str(self.board_root),
            FREQ_BOARD_AGENT="finn",
            FREQ_COMS_ROOT=str(self.coms_root),
            FREQ_BOARD_ALERT_TEST_SINK=str(self.alert_sink),
        )
        self.assert_ok(self.command(PROJECT_REGISTER, "PVE Freq", "Test project"))
        self.assert_ok(self.command(PROJECT_ASSIGN, "PVE-FREQ", "active"))
        self.register_and_claim("Infrastructure review")

    def tearDown(self):
        self.temp.cleanup()

    def command(self, executable, *arguments, agent=None, **environment):
        env = self.env.copy()
        env.update(environment)
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

    def register_and_claim(self, task_name, project="PVE-FREQ"):
        self.assert_ok(
            self.command(TASK_REGISTER, project, task_name, f"Do {task_name}.")
        )
        self.assert_ok(self.command(TASK_READY, project, task_name, "finn"))

    def test_transfer_auto_activates_recipient_stores_note_and_alerts(self):
        note = "Check the host boundary.\n\nThe exact reproduction is in section two."
        result = self.command(
            TASK_TRANSFER, "Infrastructure review", "jarvis", note
        )

        self.assert_ok(result)
        assignment = self.board_root / "projects/PVE-FREQ/active/jarvis"
        self.assertTrue(assignment.is_dir())
        self.assertEqual(stat.S_IMODE(assignment.stat().st_mode), 0o2770)
        task = assignment / "Infrastructure review.md"
        self.assertTrue(task.is_file())
        alerts = [json.loads(line) for line in self.alert_sink.read_text().splitlines()]
        self.assertEqual(len(alerts), 1)
        payload = alerts[0]["payload"]
        self.assertEqual(alerts[0]["recipient"], "jarvis")
        self.assertIn("BOARD-ALERT: finn transferred you a task in PVE-FREQ:", payload)
        self.assertIn("- Infrastructure review", payload)
        read_line = payload.splitlines()[-1]
        filename = read_line.removeprefix("  → dev-read ")
        self.assertRegex(
            filename,
            r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{9}_\d+_finn\.md$",
        )
        self.assertEqual(
            (self.coms_root / "jarvis/inbox" / filename).read_text(), note
        )
        self.assertIn(f"handoff `{filename}`", task.read_text())
        self.assertIn("## Transfer handoff", task.read_text())
        self.assertIn(note, task.read_text())
        self.assertIn(f"dev-read {filename}", result.stdout)

        (self.coms_root / "jarvis/inbox" / filename).unlink()
        self.assertIn(note, task.read_text())

    def test_other_agent_cannot_transfer_owned_task_or_activate_recipient(self):
        result = self.command(
            TASK_TRANSFER,
            "Infrastructure review",
            "jarvis",
            "I do not own this.",
            agent="clancy",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("no active task owned by clancy", result.stderr)
        project = self.board_root / "projects/PVE-FREQ"
        self.assertTrue((project / "active/finn/Infrastructure review.md").is_file())
        self.assertFalse((project / "active/jarvis").exists())
        self.assertEqual(list((self.coms_root / "jarvis/inbox").iterdir()), [])

    def test_unknown_recipient_fails_without_board_change(self):
        result = self.command(
            TASK_TRANSFER, "Infrastructure review", "ken", "Please review."
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("not a communications team agent", result.stderr)
        project = self.board_root / "projects/PVE-FREQ"
        self.assertTrue((project / "active/finn/Infrastructure review.md").is_file())
        self.assertFalse((project / "active/ken").exists())

    def test_owned_task_name_must_be_unique_across_projects(self):
        self.assert_ok(self.command(PROJECT_REGISTER, "Other Project", "Other"))
        self.assert_ok(self.command(PROJECT_ASSIGN, "OTHER-PROJECT", "active"))
        self.register_and_claim("Infrastructure review", "OTHER-PROJECT")

        result = self.command(
            TASK_TRANSFER, "Infrastructure review", "jarvis", "Please review."
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("ambiguous across projects", result.stderr)
        self.assertIn("OTHER-PROJECT, PVE-FREQ", result.stderr)
        self.assertEqual(list((self.coms_root / "jarvis/inbox").iterdir()), [])

    def test_alert_failure_keeps_transfer_and_handoff_note(self):
        result = self.command(
            TASK_TRANSFER,
            "Infrastructure review",
            "jarvis",
            "Durable handoff.",
            FREQ_BOARD_ALERT_TEST_FAIL="1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ALERT FAILED", result.stderr)
        self.assertTrue(
            (
                self.board_root
                / "projects/PVE-FREQ/active/jarvis/Infrastructure review.md"
            ).is_file()
        )
        notes = list((self.coms_root / "jarvis/inbox").iterdir())
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].read_text(), "Durable handoff.")

    def test_empty_note_self_transfer_and_usage_fail_closed(self):
        empty = self.command(TASK_TRANSFER, "Infrastructure review", "jarvis", " ")
        self.assertEqual(empty.returncode, 1)
        self.assertIn("handoff note must contain non-whitespace text", empty.stderr)

        same = self.command(
            TASK_TRANSFER, "Infrastructure review", "finn", "No handoff."
        )
        self.assertEqual(same.returncode, 1)
        self.assertIn("already owned by finn", same.stderr)

        usage = self.command(TASK_TRANSFER)
        self.assertEqual(usage.returncode, 1)
        self.assertIn(
            "task-transfer <task-name> <agent> <handoff-note>", usage.stderr
        )


if __name__ == "__main__":
    unittest.main()
