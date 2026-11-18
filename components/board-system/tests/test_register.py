#!/usr/bin/env python3
import concurrent.futures
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT_REGISTER = ROOT / "bin" / "project-register"
TASK_REGISTER = ROOT / "bin" / "task-register"


class RegisterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.board_root = self.root / "board"
        self.projects_root = self.board_root / "projects"
        self.projects_root.mkdir(parents=True)
        self.projects_root.chmod(0o2770)
        self.env = os.environ.copy()
        self.env["FREQ_BOARD_TESTING"] = "1"
        self.env["FREQ_BOARD_ROOT"] = str(self.board_root)

    def tearDown(self):
        self.temp.cleanup()

    def run_project(self, *args, env=None):
        return subprocess.run(
            [str(PROJECT_REGISTER), *args],
            text=True,
            capture_output=True,
            env=env or self.env,
            check=False,
        )

    def run_task(self, *args):
        return subprocess.run(
            [str(TASK_REGISTER), *args],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def register_project(self):
        result = self.run_project(
            "PVE Freq", "Manage the existing PVE frequency platform."
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "REGISTERED PROJECT: PVE-FREQ\n")
        return self.projects_root / "PVE-FREQ"

    def test_project_registration_generates_id_and_clean_layout(self):
        project = self.register_project()
        self.assertEqual(
            result_paths(project),
            {
                "active",
                "archive",
                "blocked",
                "done",
                "overview.md",
                "ready",
            },
        )
        overview = (project / "overview.md").read_text(encoding="utf-8")
        self.assertEqual(overview, "Manage the existing PVE frequency platform.\n")
        self.assertEqual(
            stat.S_IMODE((project / "overview.md").stat().st_mode), 0o660
        )
        self.assertFalse((self.board_root / "overview.md").exists())
        for path in [project, *project.rglob("*")]:
            if path.is_dir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o2770, path)

    def test_each_project_owns_its_exact_overview(self):
        first = self.register_project()
        result = self.run_project("Control Plane", "Coordinate agent work.")
        self.assertEqual(result.returncode, 0, result.stderr)
        second = self.projects_root / "CONTROL-PLANE"
        self.assertEqual(
            (first / "overview.md").read_text(),
            "Manage the existing PVE frequency platform.\n",
        )
        self.assertEqual(
            (second / "overview.md").read_text(), "Coordinate agent work.\n"
        )
        self.assertFalse((self.board_root / "overview.md").exists())

    def test_project_registration_refuses_generated_id_collision_without_mutation(self):
        project = self.register_project()
        before_project = snapshot(project)
        result = self.run_project("pve--freq", "Replacement overview")
        self.assertEqual(result.returncode, 1)
        self.assertIn("project already exists: PVE-FREQ", result.stderr)
        self.assertEqual(snapshot(project), before_project)

    def test_project_registration_rejects_bad_inputs(self):
        cases = (
            (("", "Overview"), "project name is empty"),
            (("!!!", "Overview"), "cannot produce a project ID"),
            (("PVE Freq", ""), "brief overview is empty"),
            (("PVE Freq", "bad\noverview"), "must be one line"),
        )
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.run_project(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)

    def test_task_registration_uses_exact_authored_name_as_filename(self):
        project = self.register_project()
        title = 'VM create "OK" bug'
        description = "When creating a VM, clicking OK does not load or continue."

        result = self.run_task("PVE-FREQ", title, description)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"REGISTERED TASK: {title} -> PVE-FREQ/ready/{title}.md\n",
        )
        task = project / "ready" / f"{title}.md"
        contents = task.read_text(encoding="utf-8")
        self.assertIn(f"# {title}\n", contents)
        self.assertIn("- Project: `PVE-FREQ`\n", contents)
        self.assertIn(f"## Task\n\n{description}\n", contents)
        self.assertNotRegex(contents.lower(), r"(?:state|status|holder):")
        self.assertEqual(stat.S_IMODE(task.stat().st_mode), 0o660)
        self.assertNotIn("PVE-001", contents)

    def test_task_registration_can_start_directly_blocked_with_reason(self):
        project = self.register_project()
        title = "Final implementation review"
        reason = "Waiting for the implementation artifact"

        result = self.run_task("PVE-FREQ", title, "Review the final build.", reason)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"REGISTERED TASK: {title} -> PVE-FREQ/blocked/{title}.md\n",
        )
        task = project / "blocked" / f"{title}.md"
        contents = task.read_text()
        self.assertIn("## Blocked reason\n\n" + reason, contents)
        self.assertIn("**REGISTER BLOCKED**", contents)
        self.assertFalse((project / "ready" / f"{title}.md").exists())

    def test_task_name_must_be_unique_across_project_statuses(self):
        project = self.register_project()
        first = self.run_task("PVE-FREQ", "Frontend auth", "Build frontend auth.")
        self.assertEqual(first.returncode, 0, first.stderr)
        task = project / "ready" / "Frontend auth.md"
        task.rename(project / "done" / task.name)

        duplicate = self.run_task("PVE-FREQ", "Frontend auth", "Duplicate.")

        self.assertEqual(duplicate.returncode, 1)
        self.assertIn("task already exists in project: Frontend auth", duplicate.stderr)

    def test_concurrent_distinct_task_names_register_without_collision(self):
        project = self.register_project()

        def register(number):
            return self.run_task(
                "PVE-FREQ", f"Planned section {number}", f"Build section {number}."
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(register, range(1, 13)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        names = {path.name for path in (project / "ready").glob("*.md")}
        self.assertEqual(
            names, {f"Planned section {number}.md" for number in range(1, 13)}
        )

    def test_task_registration_rejects_unknown_project_and_bad_names(self):
        self.register_project()
        cases = (
            (("MISSING", "Title", "Body"), "project does not exist"),
            (("PVE-FREQ", "bad\ntitle", "Body"), "must be one line"),
            (("PVE-FREQ", "path/title", "Body"), "must not contain a slash"),
            (("PVE-FREQ", ".hidden", "Body"), "must not begin with a dot"),
            (("PVE-FREQ", "Title", ""), "full description is empty"),
            (("PVE-FREQ", "Title", "Body", "line one\nline two"), "one non-empty line"),
            (("PVE-FREQ", "Title", "Body", " "), "one non-empty line"),
        )
        for args, expected in cases:
            with self.subTest(args=args):
                result = self.run_task(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)

    @unittest.skipIf(__import__("pathlib").Path("/var/lib/freq-agents/board/projects").exists(),
                     "non-test fallback check requires a host without a live board")
    def test_runtime_override_requires_explicit_test_flag(self):
        env = self.env.copy()
        env.pop("FREQ_BOARD_TESTING")
        result = self.run_project("PVE Freq", "Brief overview", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "projects root is unavailable: /var/lib/freq-agents/board/projects",
            result.stderr,
        )
        self.assertFalse((self.projects_root / "PVE-FREQ").exists())


def result_paths(root):
    return {str(path.relative_to(root)) for path in root.rglob("*")}


def snapshot(root):
    return {
        str(path.relative_to(root)): (
            "dir" if path.is_dir() else path.read_bytes()
        )
        for path in root.rglob("*")
    }


if __name__ == "__main__":
    unittest.main()
