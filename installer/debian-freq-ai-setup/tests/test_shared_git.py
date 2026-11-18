import importlib.machinery
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    return importlib.machinery.SourceFileLoader(name.replace("-", "_"),
        str(ROOT / "assets" / name)).load_module()
adapter = load("shared-git")
setup = load("configure-shared-git")
FAKE = dict(name="Fixture Host", email="fixture@example.invalid",
            login="fixture-account", token="ghp_FAKE_NOT_A_REAL_CREDENTIAL")


class SharedGitTests(unittest.TestCase):
    def test_project_trust_is_scoped_and_inherited_by_gh(self):
        original = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'test.keep',
                    'GIT_CONFIG_VALUE_0': 'preserved'}
        env = adapter.project_environment(original)
        self.assertEqual(env['GIT_CONFIG_VALUE_1'], '/home/freq-agents/projects/*')
        self.assertEqual(env['GIT_CONFIG_VALUE_0'], 'preserved')
        self.assertEqual(original['GIT_CONFIG_COUNT'], '1')
        _, gh_env = adapter.invocation('gh', ['repo', 'view'], FAKE, env)
        self.assertEqual(gh_env['GIT_CONFIG_COUNT'], '3')
        self.assertNotIn('*', [v for k,v in gh_env.items() if k.startswith('GIT_CONFIG_VALUE_')])

    def test_capability_summary_reports_limits(self):
        text = setup.capability_summary('repo, workflow')
        self.assertIn('repo: available', text)
        self.assertIn('workflow: available', text)
        self.assertIn('delete_repo: MISSING', text)

    def test_exact_credential_host(self):
        self.assertIn(FAKE["token"], adapter.credential(FAKE, "get",
                      "protocol=https\nhost=github.com\n"))
        for protocol, host in (("http", "github.com"), ("https", "github.com.evil"),
                               ("https", "evil"), ("https", "github.com:443")):
            self.assertEqual(adapter.credential(FAKE, "get",
                f"protocol={protocol}\nhost={host}\n"), "")
        self.assertEqual(adapter.credential(FAKE, "store", "protocol=https\nhost=github.com"), "")

    def test_secret_not_in_git_arguments(self):
        args, env = adapter.invocation("git", ["status"], FAKE, {"GIT_TRACE": "1"})
        self.assertNotIn(FAKE["token"], " ".join(args))
        self.assertNotIn("GIT_TRACE", env)
        self.assertEqual(env["GIT_AUTHOR_EMAIL"], FAKE["email"])

    def test_gh_uses_shared_token_without_argument_leak(self):
        args, env = adapter.invocation("gh", ["api", "user"], FAKE,
                                       {"GH_TOKEN": "old", "GH_DEBUG": "api"})
        self.assertEqual(env["GH_TOKEN"], FAKE["token"])
        self.assertNotIn(FAKE["token"], " ".join(args))
        self.assertNotIn("GH_DEBUG", env)

    def test_email_required_and_name_validation(self):
        for name, email, token in (("Host", "", "ghp_FAKE"), ("", "a@b", "ghp_FAKE"),
                                   ("Host\ninject", "a@b", "ghp_FAKE"),
                                   ("Host", "a@b", "not-a-token")):
            with self.assertRaises(ValueError):
                setup.validate_fields(name, email, token)
        setup.validate_fields("Other Host", "other@example.invalid", "ghp_FAKE")

    @unittest.skipUnless(os.getuid() == 0, "publication is installer-root only")
    def test_atomic_rotation_permissions_and_failure_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            setup.publish(path, FAKE, os.getgid())
            self.assertEqual((path / "config.json").stat().st_mode & 0o777, 0o640)
            before = (path / "config.json").read_bytes()
            with patch.object(setup.os, "replace", side_effect=OSError("failure")):
                with self.assertRaises(OSError):
                    setup.publish(path, dict(FAKE, name="Changed"), os.getgid())
            self.assertEqual((path / "config.json").read_bytes(), before)
            setup.publish(path, dict(FAKE, name="Changed"), os.getgid())
            self.assertEqual(adapter.load(path / "config.json")["name"], "Changed")
            self.assertFalse(list(path.glob(".candidate-*")))

    def test_real_git_commit_uses_identity_without_repository_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["/usr/bin/git", "init", "-q", tmp], check=True)
            args, env = adapter.invocation("git", ["-C", tmp, "commit", "--allow-empty",
                                                 "-qm", "test: identity"], FAKE, os.environ)
            subprocess.run(args, env=env, check=True)
            result = subprocess.check_output(["/usr/bin/git", "-C", tmp, "log", "-1",
                                               "--format=%an <%ae>"], text=True)
            self.assertEqual(result.strip(), "Fixture Host <fixture@example.invalid>")
            self.assertNotIn(FAKE["token"], (Path(tmp) / ".git/config").read_text())

    def test_failed_verification_does_not_leak_token(self):
        class Broken:
            def open(self, *args, **kwargs):
                raise OSError(FAKE["token"])
        with patch.object(setup.urllib.request, "build_opener", return_value=Broken()):
            with self.assertRaises(ValueError) as result:
                setup.verify(FAKE["token"])
        self.assertNotIn(FAKE["token"], str(result.exception))

    @unittest.skipUnless(os.getuid() == 0, "interactive setup publishes as root")
    def test_interactive_defaults_keep_values_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "config"
            with patch.object(setup, "ROOT", root), patch.object(setup.sys, "argv", ["setup"]), \
                 patch.object(setup.sys.stdin, "isatty", return_value=True), \
                 patch.object(setup.socket, "gethostname", return_value="test-host"), \
                 patch.object(setup, "verify", return_value=("fixture-account", "repo")), \
                 patch.object(setup.getpass, "getpass", return_value="ghp_FAKE"), \
                 patch("builtins.input", side_effect=["", "typed@example.invalid", "y"]), \
                 patch.object(setup.sys, "stdout", io.StringIO()):
                setup.main()
            saved = adapter.load(root / "config.json")
            self.assertEqual(saved["name"], "test-host")
            self.assertEqual(saved["email"], "typed@example.invalid")
            before = (root / "config.json").read_bytes()
            with patch.object(setup, "ROOT", root), patch.object(setup.sys, "argv", ["setup"]), \
                 patch.object(setup.sys.stdin, "isatty", return_value=True), \
                 patch.object(setup, "verify", return_value=("fixture-account", "repo")), \
                 patch.object(setup.getpass, "getpass", return_value=""), \
                 patch("builtins.input", side_effect=["Changed", "", "n"]), \
                 patch.object(setup.sys, "stdout", io.StringIO()):
                setup.main()
            self.assertEqual((root / "config.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
