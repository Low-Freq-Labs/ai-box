import importlib.machinery
import importlib.util
from pathlib import Path
import tomllib
import unittest

path = Path(__file__).resolve().parents[1] / 'assets/configure-stop-guard'
loader = importlib.machinery.SourceFileLoader('guard_install', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
guard = importlib.util.module_from_spec(spec)
loader.exec_module(guard)


class ManagedPolicy(unittest.TestCase):
    def test_empty_policy_and_idempotence(self):
        result = guard.merge('')
        self.assertTrue(tomllib.loads(result)['features']['hooks'])
        self.assertEqual(guard.merge(result), result)

    def test_preserves_unrelated_policy_and_existing_hook(self):
        source = '''allowed_approval_policies = ["never"]
[features]
other_feature = false
[hooks]
[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = "/example/existing-hook"
'''
        result = tomllib.loads(guard.merge(source))
        self.assertEqual(result['allowed_approval_policies'], ['never'])
        self.assertFalse(result['features']['other_feature'])
        self.assertEqual(result['hooks']['SessionStart'], tomllib.loads(source)['hooks']['SessionStart'])
        self.assertEqual(result['hooks']['Stop'], [{'hooks': [guard.HOOK]}])

    def test_refuses_explicit_disable_and_foreign_directory(self):
        for source in ('[features]\nhooks = false\n', '[hooks]\nmanaged_dir = "/other"\n'):
            with self.assertRaises(ValueError):
                guard.merge(source)

    def test_preserves_existing_deployed_guard(self):
        source = '''[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/usr/local/bin/board-stop-hook"
'''
        self.assertEqual(guard.merge(source), source)

    def test_invalid_or_inline_policy_is_not_silently_replaced(self):
        for source in ('not toml', 'features = { other = true }\n'):
            with self.assertRaises(ValueError):
                guard.merge(source)


if __name__ == '__main__':
    unittest.main()
