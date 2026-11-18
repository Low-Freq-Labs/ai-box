"""Own-user scheduling authorization and preservation checks; no native cron writes."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('own_crontab', Path(__file__).with_name('own_crontab.py'))
cron = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cron)


class API:
    @staticmethod
    def require(value, reason):
        if not value:
            raise ValueError(reason)

    @staticmethod
    def fields(request, names):
        if set(request) != set(names.split()):
            raise ValueError('unexpected request fields')


class OwnCrontab(unittest.TestCase):
    def setUp(self):
        self.identity = patch.object(cron.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1001))
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.old = {'exists': False, 'content': '', 'sha256': hashlib.sha256(b'0\0').hexdigest()}

    def call(self, request, actor='example', uid=1001, names=('example',)):
        return cron.handle(API, request, actor, uid, names)

    def test_rejects_root_unregistered_and_identity_mismatch_before_native_call(self):
        with patch.object(cron, 'invoke') as native:
            for actor, uid, names in [('example', 0, ('example',)), ('other', 1001, ('example',)), ('example', 1002, ('example',))]:
                with self.subTest(uid=uid, actor=actor), self.assertRaises(ValueError):
                    self.call({'area': 'own-crontab', 'action': 'show'}, actor, uid, names)
            native.assert_not_called()

    def test_rejects_target_user_field(self):
        with patch.object(cron, 'invoke') as native, self.assertRaises(ValueError):
            self.call({'area': 'own-crontab', 'action': 'show', 'user': 'root'})
        native.assert_not_called()

    def test_stale_fingerprint_preserves_table(self):
        with patch.object(cron, 'snapshot', return_value=self.old), patch.object(cron, 'invoke') as native:
            with self.assertRaisesRegex(ValueError, 'stale'):
                self.call({'area': 'own-crontab', 'action': 'remove', 'expected_sha256': '1' * 64})
            native.assert_not_called()

    def test_native_syntax_refusal_never_installs(self):
        with patch.object(cron, 'snapshot', return_value=self.old), patch.object(cron, 'invoke', return_value=SimpleNamespace(returncode=1)) as native:
            with self.assertRaisesRegex(ValueError, 'syntax refused'):
                self.call({'area': 'own-crontab', 'action': 'install', 'expected_sha256': self.old['sha256'], 'content': 'bad syntax\n'})
            native.assert_called_once_with('example', ['-n', '-'], b'bad syntax\n')

    def test_install_requires_validation_and_exact_readback(self):
        content = '0 0 * * * /usr/bin/true\n'
        after = {'exists': True, 'content': content, 'sha256': '2' * 64}
        with patch.object(cron, 'snapshot', side_effect=[self.old, after]), patch.object(cron, 'invoke', return_value=SimpleNamespace(returncode=0)) as native:
            result = self.call({'area': 'own-crontab', 'action': 'install', 'expected_sha256': self.old['sha256'], 'content': content})
            self.assertEqual([call.args[1] for call in native.call_args_list], [['-n', '-'], ['-']])
            self.assertIn(after['sha256'], result)

    def test_oversize_and_control_bytes_never_reach_native(self):
        with patch.object(cron, 'invoke') as native:
            for content in ['x' * 8193 + '\n', 'value\x00\n', 'missing newline']:
                with self.subTest(size=len(content)), self.assertRaises(ValueError):
                    self.call({'area': 'own-crontab', 'action': 'install', 'expected_sha256': self.old['sha256'], 'content': content})
            native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
