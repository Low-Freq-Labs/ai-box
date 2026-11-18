import importlib.machinery
import importlib.util
from pathlib import Path
import os
import stat
import subprocess
import tempfile
import unittest

loader = importlib.machinery.SourceFileLoader('ssh_setup', str(Path(__file__).resolve().parents[1] / 'assets/configure-master-ssh-key'))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class SSHKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.home / 'fixture')], check=True)
        self.key = (self.home / 'fixture.pub').read_text().strip()
        self.identity = self.key.split()[:2]

    def tearDown(self):
        self.temp.cleanup()

    def test_validation_rejects_private_multiline_and_malformed(self):
        key, identity, fingerprint = module.validate_key(self.key)
        self.assertEqual(identity, self.identity)
        self.assertIn('SHA256:', fingerprint)
        for value in ('-----BEGIN OPENSSH PRIVATE KEY-----', self.key + '\n' + self.key, 'ssh-ed25519 aaaa'):
            with self.assertRaises(ValueError):
                module.validate_key(value)

    def test_add_modes_and_idempotence(self):
        added, backup = module.add_key(self.home, self.key, self.identity)
        self.assertTrue(added)
        self.assertIsNone(backup)
        ssh = self.home / '.ssh'
        self.assertEqual(stat.S_IMODE(ssh.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((ssh / 'authorized_keys').stat().st_mode), 0o600)
        self.assertFalse(module.add_key(self.home, self.key + ' changed-comment', self.identity)[0])
        self.assertEqual((ssh / 'authorized_keys').read_text(), self.key + '\n')

    def test_preserves_existing_bytes_and_backup(self):
        ssh = self.home / '.ssh'
        ssh.mkdir()
        original = b'# existing comment without newline'
        (ssh / 'authorized_keys').write_bytes(original)
        added, backup = module.add_key(self.home, self.key, self.identity)
        self.assertTrue(added)
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertTrue((ssh / 'authorized_keys').read_bytes().startswith(original + b'\n'))

    def test_does_not_bypass_existing_key_options(self):
        content = 'from="192.0.2.1",no-port-forwarding ' + self.key + '\n'
        self.assertTrue(module.duplicate(content, self.identity))

    def test_symlink_and_hardlink_targets_rejected(self):
        ssh = self.home / '.ssh'
        ssh.mkdir()
        outside = self.home / 'untouched'
        outside.write_text('unchanged')
        target = ssh / 'authorized_keys'
        target.symlink_to(outside)
        with self.assertRaises(ValueError):
            module.add_key(self.home, self.key, self.identity)
        target.unlink()
        os.link(outside, target)
        with self.assertRaises(ValueError):
            module.add_key(self.home, self.key, self.identity)
        self.assertEqual(outside.read_text(), 'unchanged')


if __name__ == '__main__':
    unittest.main()
