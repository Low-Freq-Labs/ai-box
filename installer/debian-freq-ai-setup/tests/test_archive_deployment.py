"""Archive deployment checks; fixtures never use the live board."""
import grp
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ArchiveDeployment(unittest.TestCase):
    def test_command_and_skill_deployment_lists(self):
        for relative, count in (
            ("assets/setup-board", 2), ("assets/create-agent", 1),
            ("install-base.sh", 3), ("accept-base.sh", 2),
        ):
            self.assertGreaterEqual(
                (ROOT / relative).read_text().count("project-archive"), count)
        for runtime in ("AGENTS", "CLAUDE"):
            contract = (ROOT / "assets/board-behavior" /
                        f"{runtime}.board.md").read_text()
            self.assertIn("Archive only on explicit wrap-up", contract)
            self.assertIn("archived history is retained.", contract)

    @unittest.skipUnless(os.geteuid() == 0, "migration runs as installer root")
    def test_legacy_migration_idempotence_and_symlink_rejection(self):
        source = (ROOT / "assets/setup-board").read_text()
        marker = 'python3 - "$board_root/projects" "$agent_group" <<\'PY\'\n'
        code = source.split(marker, 1)[1].split("\nPY\n", 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "TEST"
            for state in ("ready", "active", "blocked", "done"):
                (project / state).mkdir(parents=True)
            task = project / "done/keep.md"
            task.write_text("completion evidence\n")
            command = [sys.executable, "-", tmp, grp.getgrgid(os.getgid()).gr_name]
            for _ in range(2):
                result = subprocess.run(command, input=code, text=True,
                                        capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(task.read_text(), "completion evidence\n")
                self.assertEqual(list((project / "archive").iterdir()), [])
            (project / "archive").rmdir()
            (project / "archive").symlink_to(project / "done", target_is_directory=True)
            result = subprocess.run(command, input=code, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(task.read_text(), "completion evidence\n")


if __name__ == "__main__":
    unittest.main()
