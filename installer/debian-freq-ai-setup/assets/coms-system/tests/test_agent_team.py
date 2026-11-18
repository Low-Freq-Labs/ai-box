#!/usr/bin/env python3
import os
import pathlib
import pwd
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_TEAM = ROOT / "bin" / "agent-team"


class AgentTeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.coms_root = self.root / "coms"
        self.coms_root.mkdir()
        self.current_agent = pwd.getpwuid(os.geteuid()).pw_name
        self.env = os.environ.copy()
        self.env["FREQ_COMS_TESTING"] = "1"
        self.env["FREQ_COMS_ROOT"] = str(self.coms_root)

    def tearDown(self):
        self.temp.cleanup()

    def add_agent(self, name):
        agent = self.coms_root / name
        (agent / "inbox").mkdir(parents=True)
        (agent / "read").mkdir()
        return agent

    def add_message(self, agent, sequence, sender="gil"):
        filename = (
            f"2026-09-02_0{sequence}0000_{sequence:09d}_{sequence}_{sender}.md"
        )
        (agent / "inbox" / filename).write_text(f"message {sequence}")
        return filename

    def run_agent_team(self, *arguments, env=None):
        return subprocess.run(
            [str(AGENT_TEAM), *arguments],
            text=True,
            capture_output=True,
            env=env or self.env,
            check=False,
        )

    def test_lists_agents_inbox_counts_and_marks_current_user(self):
        current = self.add_agent(self.current_agent)
        self.add_agent("gil")
        self.add_message(current, 1)
        self.add_message(current, 2)
        before = snapshot(self.coms_root)

        result = self.run_agent_team()

        self.assertEqual(result.returncode, 0, result.stderr)
        names = sorted((self.current_agent, "gil"))
        width = max(5, *(len(name) for name in names))
        rows = [f"{'AGENT':<{width}}    INBOX"]
        counts = {self.current_agent: 2, "gil": 0}
        for name in names:
            marker = "  (you)" if name == self.current_agent else ""
            rows.append(f"{name:<{width}}    {counts[name]}{marker}")
        expected = "\n".join(rows) + "\n\n2 agents · 2 unread messages\n"
        self.assertEqual(result.stdout, expected)
        self.assertEqual(snapshot(self.coms_root), before)

    def test_counts_only_exact_regular_message_files(self):
        agent = self.add_agent("gil")
        self.add_message(agent, 1)
        (agent / "inbox" / "notes.md").write_text("not a message")
        valid_shape = agent / "inbox" / "2026-09-02_020000_000000002_2_gil.md"
        valid_shape.symlink_to(agent / "inbox" / "notes.md")

        result = self.run_agent_team()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "AGENT    INBOX\n"
            "gil      1\n\n"
            "1 agent · 1 unread message\n",
        )

    def test_empty_team_is_reported_cleanly(self):
        result = self.run_agent_team()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout, "AGENT    INBOX\n\n0 agents · 0 unread messages\n"
        )

    def test_incomplete_agent_directory_fails_instead_of_hiding_agent(self):
        (self.coms_root / "gil" / "inbox").mkdir(parents=True)

        result = self.run_agent_team()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "agent-team: TEAM FAILED: agent read directory is unavailable: gil\n",
        )

    def test_arguments_are_rejected(self):
        result = self.run_agent_team("--all")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "Usage: agent-team\n")

    def test_runtime_override_requires_explicit_test_flag(self):
        self.add_agent("gil")
        env = self.env.copy()
        env.pop("FREQ_COMS_TESTING")

        result = self.run_agent_team(env=env)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "communications root is unavailable: /var/lib/freq-agents/coms",
            result.stderr,
        )


def snapshot(root):
    return {
        str(path.relative_to(root)): (
            "dir"
            if path.is_dir() and not path.is_symlink()
            else ("symlink", os.readlink(path))
            if path.is_symlink()
            else path.read_bytes()
        )
        for path in root.rglob("*")
    }


if __name__ == "__main__":
    unittest.main()
