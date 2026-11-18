#!/usr/bin/env python3
import json
import os
import pathlib
import shlex
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_REGISTER = ROOT / "bin" / "project-register"
PROJECT_ASSIGN = ROOT / "bin" / "project-assign"
TASK_REGISTER = ROOT / "bin" / "task-register"
TASK_READY = ROOT / "bin" / "task-ready"


class TaskReadyTests(unittest.TestCase):
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
        self.assert_ok(self.command(PROJECT_REGISTER, "PVE Freq", "Test"))
        self.assert_ok(self.command(PROJECT_ASSIGN, "PVE-FREQ", "active"))

    def tearDown(self):
        self.temp.cleanup()

    def command(self, executable, *arguments, agent=None, **changes):
        env = self.env.copy()
        env.update(changes)
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

    def register(self, task_name):
        self.assert_ok(
            self.command(TASK_REGISTER, "PVE-FREQ", task_name, f"Do {task_name}.")
        )

    def force_blocked(self, task_name, reason="Waiting for host"):
        self.register(task_name)
        project = self.board_root / "projects/PVE-FREQ"
        task = project / "ready" / f"{task_name}.md"
        task.write_text(
            task.read_text()
            + '\n<!-- FREQ_BOARD_BLOCKED_BEGIN -->\n'
            + f'<!-- FREQ_BOARD_BLOCKED_REASON_JSON: {json.dumps(reason)} -->\n'
            + f'## Blocked reason\n\n{reason}\n'
            + '<!-- FREQ_BOARD_BLOCKED_END -->\n'
        )
        task.rename(project / "blocked" / task.name)

    def test_without_agent_moves_blocked_task_to_ready(self):
        self.force_blocked("Storage gate")
        result = self.command(TASK_READY, "PVE-FREQ", "Storage gate")
        self.assert_ok(result)
        self.assertEqual(result.stdout, "READY: Storage gate -> ready\n")
        task = self.board_root / "projects/PVE-FREQ/ready/Storage gate.md"
        self.assertTrue(task.is_file())
        self.assertNotIn("FREQ_BOARD_BLOCKED", task.read_text())
        self.assertIn("**READY** — blocker resolved", task.read_text())

    def test_with_agent_assigns_ready_and_auto_activates_recipient(self):
        self.register("Infrastructure review")
        result = self.command(
            TASK_READY,
            "PVE-FREQ",
            "Infrastructure review",
            "jarvis",
            "Review the storage boundary before acceptance.",
        )
        self.assert_ok(result)
        self.assertEqual(
            result.stdout,
            "ASSIGNED: Infrastructure review -> active/jarvis\n",
        )
        assignment = self.board_root / "projects/PVE-FREQ/active/jarvis"
        self.assertTrue(assignment.is_dir())
        self.assertEqual(stat.S_IMODE(assignment.stat().st_mode), 0o2770)
        self.assertTrue((assignment / "Infrastructure review.md").is_file())
        alert = json.loads(self.alert_sink.read_text())
        self.assertEqual(alert["recipient"], "jarvis")
        self.assertEqual(
            alert["payload"],
            "BOARD-ALERT: finn assigned you a task in PVE-FREQ:\n"
            "- Infrastructure review\n"
            "  → task-status PVE-FREQ 'Infrastructure review'",
        )
        contents = (assignment / "Infrastructure review.md").read_text()
        self.assertIn("## Assignment note", contents)
        self.assertIn("Review the storage boundary before acceptance.", contents)

    def test_with_agent_assigns_blocked_task_and_clears_reason(self):
        self.force_blocked("Resolved gate")
        result = self.command(
            TASK_READY,
            "PVE-FREQ",
            "Resolved gate",
            "jarvis",
            "The host dependency is resolved; verify the final path.",
        )
        self.assert_ok(result)
        task = self.board_root / "projects/PVE-FREQ/active/jarvis/Resolved gate.md"
        self.assertTrue(task.is_file())
        self.assertNotIn("FREQ_BOARD_BLOCKED", task.read_text())
        self.assertIn("blocker resolved", task.read_text())

    def test_unassigned_agent_cannot_reopen_blocked_but_can_assign_ready(self):
        self.force_blocked("Blocked review")
        blocked = self.command(
            TASK_READY,
            "PVE-FREQ",
            "Blocked review",
            "jarvis",
            "Review after the blocker cleared.",
            agent="clancy",
        )
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("agent is not assigned active", blocked.stderr)
        self.assertFalse(
            (self.board_root / "projects/PVE-FREQ/active/jarvis").exists()
        )

        self.register("Ready review")
        ready = self.command(
            TASK_READY,
            "PVE-FREQ",
            "Ready review",
            "jarvis",
            "Check the ready artifact.",
            agent="clancy",
        )
        self.assert_ok(ready)

    def test_active_and_done_tasks_cannot_be_readied_or_assigned(self):
        self.register("Already active")
        self.assert_ok(
            self.command(TASK_READY, "PVE-FREQ", "Already active", "finn")
        )
        for arguments in ((), ("jarvis",)):
            result = self.command(
                TASK_READY, "PVE-FREQ", "Already active", *arguments
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("task is active", result.stderr)

    def test_unknown_recipient_and_alert_failure_are_truthful(self):
        self.register("Unknown recipient")
        unknown = self.command(
            TASK_READY,
            "PVE-FREQ",
            "Unknown recipient",
            "ken",
            "Review this task.",
        )
        self.assertEqual(unknown.returncode, 1)
        self.assertIn("not a communications team agent", unknown.stderr)
        self.assertTrue(
            (self.board_root / "projects/PVE-FREQ/ready/Unknown recipient.md").is_file()
        )

        self.register("Alert failure")
        failed_alert = self.command(
            TASK_READY,
            "PVE-FREQ",
            "Alert failure",
            "jarvis",
            "Review despite notification failure.",
            FREQ_BOARD_ALERT_TEST_FAIL="1",
        )
        self.assertEqual(failed_alert.returncode, 0, failed_alert.stderr)
        self.assertIn("ALERT FAILED", failed_alert.stderr)
        self.assertTrue(
            (self.board_root / "projects/PVE-FREQ/active/jarvis/Alert failure.md").is_file()
        )

    def test_conflict_identifies_owner_and_safe_inspection_without_mutation(self):
        name = "Review owner's draft"
        self.register(name)
        self.assert_ok(self.command(TASK_READY, "PVE-FREQ", name, "finn"))
        task = self.board_root / "projects/PVE-FREQ/active/finn" / (name + ".md")
        before = task.read_bytes()
        for recipient in ("finn", "jarvis"):
            result = self.command(TASK_READY, "PVE-FREQ", name, recipient,
                                  "Do not replace the original handoff.")
            self.assertEqual(result.returncode, 1)
            self.assertIn("Current owner: finn.", result.stderr)
            inspection = result.stderr.split("Inspect: ", 1)[1].strip()
            self.assertEqual(shlex.split(inspection), ["task-status", "PVE-FREQ", name])
            self.assertEqual(task.read_bytes(), before)
            self.assertFalse(self.alert_sink.exists())

    def test_concurrent_assignments_have_one_winner_and_truthful_conflict(self):
        self.register("Concurrent review")
        processes = [subprocess.Popen(
            [str(TASK_READY), "PVE-FREQ", "Concurrent review", recipient,
             "Review the shared artifact."], env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        ) for recipient in ("jarvis", "clancy")]
        results = [(p, p.communicate(timeout=15)) for p in processes]
        self.assertEqual(sorted(p.returncode for p, _ in results), [0, 1])
        project = self.board_root / "projects/PVE-FREQ"
        files = list((project / "active").glob("*/Concurrent review.md"))
        self.assertEqual(len(files), 1)
        owner = files[0].parent.name
        loser_error = next(output[1] for p, output in results if p.returncode)
        self.assertIn(f"Current owner: {owner}.", loser_error)
        alerts = self.alert_sink.read_text().splitlines()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(json.loads(alerts[0])["recipient"], owner)

    def test_cross_agent_assignment_requires_nonempty_note_before_mutation(self):
        self.register("Needs context")
        for arguments in (("jarvis",), ("jarvis", " ")):
            with self.subTest(arguments=arguments):
                result = self.command(
                    TASK_READY, "PVE-FREQ", "Needs context", *arguments
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("cross-agent assignment note is required", result.stderr)
                self.assertTrue(
                    (
                        self.board_root
                        / "projects/PVE-FREQ/ready/Needs context.md"
                    ).is_file()
                )
                self.assertFalse(
                    (self.board_root / "projects/PVE-FREQ/active/jarvis").exists()
                )

    def test_usage_is_exact(self):
        result = self.command(TASK_READY)
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "task-ready <project-id> <task-name> [agent [assignment-note]]",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
