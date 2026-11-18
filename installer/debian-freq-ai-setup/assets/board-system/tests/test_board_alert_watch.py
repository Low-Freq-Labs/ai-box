#!/usr/bin/env python3
import json
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
TASK_DONE = ROOT / "bin" / "task-done"
BOARD_ALERT_WATCH = ROOT / "bin" / "board-alert-watch"


class BoardAlertWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.board_root = self.root / "board"
        self.state_root = self.root / "alert-state"
        self.capture = self.root / "capture.txt"
        self.sink = self.root / "alerts.jsonl"
        self.coms_root = self.root / "coms"
        for agent in ("finn",):
            (self.coms_root / agent / "inbox").mkdir(parents=True)
            (self.coms_root / agent / "read").mkdir()
        (self.board_root / "projects").mkdir(parents=True)
        self.state_root.mkdir()
        self.capture.write_text("initial pane\n", encoding="utf-8")
        self.env = os.environ.copy()
        self.env.update(
            {
                "FREQ_BOARD_TESTING": "1",
                "FREQ_BOARD_ROOT": str(self.board_root),
                "FREQ_BOARD_AGENT": "finn",
                "FREQ_BOARD_ALERT_STATE_ROOT": str(self.state_root),
                "FREQ_BOARD_ALERT_TEST_CAPTURE_FILE": str(self.capture),
                "FREQ_BOARD_ALERT_TEST_SINK": str(self.sink),
                "FREQ_COMS_ROOT": str(self.coms_root),
            }
        )
        self.assert_ok(
            self.run_command(PROJECT_REGISTER, "PVE Freq", "Test project")
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, command, *arguments, now=None):
        env = self.env.copy()
        if now is not None:
            env["FREQ_BOARD_ALERT_NOW"] = str(now)
        return subprocess.run(
            [str(command), *arguments],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def alerts(self):
        if not self.sink.exists():
            return []
        return [
            json.loads(line)
            for line in self.sink.read_text(encoding="utf-8").splitlines()
        ]

    def assign(self):
        self.assert_ok(self.run_command(PROJECT_ASSIGN, "PVE-FREQ", "active"))

    def register_and_claim(self, task_name):
        self.assert_ok(
            self.run_command(TASK_REGISTER, "PVE-FREQ", task_name, "Do the work.")
        )
        self.assert_ok(
            self.run_command(TASK_READY, "PVE-FREQ", task_name, "finn")
        )

    def test_active_queue_alerts_once_after_five_unchanged_minutes(self):
        self.assign()
        self.register_and_claim("Backend API")
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=0))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=299))
        self.assertEqual(self.alerts(), [])

        alert = self.run_command(BOARD_ALERT_WATCH, now=300)
        self.assert_ok(alert)
        self.assertIn("active queue stalled", alert.stdout)
        self.assertEqual(len(self.alerts()), 1)
        self.assertIn("pane has not changed for 5 minutes", self.alerts()[0]["payload"])
        self.assertIn("PVE-FREQ:\n- Backend API", self.alerts()[0]["payload"])

        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=900))
        self.assertEqual(len(self.alerts()), 1)

    def test_pane_change_rearms_active_alert(self):
        self.assign()
        self.register_and_claim("Backend API")
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=0))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=300))
        self.capture.write_text("new pane output\n", encoding="utf-8")
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=301))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=600))
        self.assertEqual(len(self.alerts()), 1)
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=601))
        self.assertEqual(len(self.alerts()), 2)

    def test_task_set_change_resets_active_timer(self):
        self.assign()
        self.register_and_claim("First task")
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=0))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=299))
        self.register_and_claim("Second task")
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=300))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=599))
        self.assertEqual(self.alerts(), [])
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=600))
        self.assertEqual(len(self.alerts()), 1)
        self.assertIn("- First task\n- Second task", self.alerts()[0]["payload"])

    def test_one_active_alert_groups_tasks_from_multiple_projects(self):
        self.assign()
        self.register_and_claim("Backend API")
        self.assert_ok(
            self.run_command(PROJECT_REGISTER, "Control Plane", "Control work")
        )
        self.assert_ok(
            self.run_command(PROJECT_ASSIGN, "CONTROL-PLANE", "active")
        )
        self.assert_ok(
            self.run_command(
                TASK_REGISTER, "CONTROL-PLANE", "Watcher service", "Build it."
            )
        )
        self.assert_ok(
            self.run_command(
                TASK_READY, "CONTROL-PLANE", "Watcher service", "finn"
            )
        )
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=0))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=300))
        self.assertEqual(len(self.alerts()), 1)
        payload = self.alerts()[0]["payload"]
        self.assertIn("CONTROL-PLANE:\n- Watcher service", payload)
        self.assertIn("PVE-FREQ:\n- Backend API", payload)

    def test_empty_queue_alerts_once_after_ten_minutes_and_rearms(self):
        self.assign()
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=0))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=599))
        self.assertEqual(self.alerts(), [])

        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=600))
        self.assertEqual(len(self.alerts()), 1)
        payload = self.alerts()[0]["payload"]
        self.assertIn("active queue has been empty for 10 minutes", payload)
        self.assertIn("project-status PVE-FREQ", payload)
        self.assertIn("project-assign PVE-FREQ inactive", payload)
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=1800))
        self.assertEqual(len(self.alerts()), 1)

        self.register_and_claim("Temporary work")
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=1801))
        self.assert_ok(
            self.run_command(TASK_DONE, "Temporary work", "Watcher test completed.")
        )
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=1802))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=2402))
        self.assertEqual(len(self.alerts()), 2)

    def test_archived_tasks_do_not_count_as_active_work(self):
        self.assign()
        archive = self.board_root / "projects" / "PVE-FREQ" / "archive"
        (archive / "Historical task.md").write_text(
            "# Historical task\n\nAlready completed.\n", encoding="utf-8"
        )

        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=0))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=600))

        self.assertEqual(len(self.alerts()), 1)
        payload = self.alerts()[0]["payload"]
        self.assertIn("active queue has been empty for 10 minutes", payload)
        self.assertNotIn("Historical task", payload)

    def test_unassigned_agent_never_alerts(self):
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=0))
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=1000))
        self.assertEqual(self.alerts(), [])

    def test_delivery_failure_is_latched_without_retry_spam(self):
        self.assign()
        self.env["FREQ_BOARD_ALERT_TEST_FAIL"] = "1"
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=0))
        failed = self.run_command(BOARD_ALERT_WATCH, now=600)
        self.assertEqual(failed.returncode, 0)
        self.assertIn("EMPTY ALERT FAILED", failed.stderr)
        self.assert_ok(self.run_command(BOARD_ALERT_WATCH, now=1200))
        self.assertEqual(self.alerts(), [])

    def test_usage_is_exact(self):
        result = self.run_command(BOARD_ALERT_WATCH, "unexpected", now=0)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Usage: board-alert-watch", result.stderr)


if __name__ == "__main__":
    unittest.main()
