import gzip
import importlib.machinery
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import json
from unittest.mock import patch

module = importlib.machinery.SourceFileLoader(
    'devtools_install', str(Path(__file__).resolve().parents[1] / 'assets/devtools-install')).load_module()


class DeveloperInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_preserves_unrelated_command(self):
        command = self.bin / 'uv'
        command.write_text('existing')
        with self.assertRaisesRegex(RuntimeError, 'existing command'):
            module.replace_link(command, self.root / 'replacement')
        self.assertEqual(command.read_text(), 'existing')

    def test_preserves_unrelated_symlink(self):
        command = self.bin / 'uv'
        command.symlink_to('/another/tool')
        with self.assertRaisesRegex(RuntimeError, 'unrelated command'):
            module.replace_link(command, self.root / 'replacement')
        self.assertEqual(str(command.readlink()), '/another/tool')

    def test_archive_cannot_write_external_paths(self):
        archive = self.root / 'archive.tar.gz'
        with tarfile.open(archive, 'w:gz') as out:
            for name in ('../../escape', 'release/bin/uv'):
                item = tarfile.TarInfo(name)
                item.size = 4
                out.addfile(item, io.BytesIO(b'test'))
        module.extract_commands({'format': 'tar.gz', 'commands': ['uv']}, archive, self.bin)
        self.assertEqual((self.bin / 'uv').read_bytes(), b'test')
        self.assertFalse((self.root / 'escape').exists())

    def test_archive_symlink_not_executable_source(self):
        archive = self.root / 'archive.tar.gz'
        with tarfile.open(archive, 'w:gz') as out:
            item = tarfile.TarInfo('uv')
            item.type = tarfile.SYMTYPE
            item.linkname = '/etc/passwd'
            out.addfile(item)
        with self.assertRaisesRegex(RuntimeError, 'one executable'):
            module.extract_commands({'format': 'tar.gz', 'commands': ['uv']}, archive, self.bin)

    def test_rejects_unsafe_manifest_url(self):
        with self.assertRaisesRegex(RuntimeError, 'unsafe binary'):
            module.fetch({'url': 'http://example.com/tool', 'sha256': '0' * 64}, self.root / 'download')

    def test_release_tampering_fails(self):
        command = self.bin / 'uv'
        command.write_text('original')
        (self.root / 'receipt.json').write_text(json.dumps({'bin/uv': module.digest(command)}))
        module.verify_release(self.root)
        command.write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
            module.verify_release(self.root)

    def test_operator_default_and_explicit_override(self):
        import subprocess
        source = (Path(__file__).resolve().parents[1] / 'bootstrap-freq-ai-setup').read_text()
        line = next(line for line in source.splitlines() if line.startswith('operator_name=${'))
        for master, explicit, expected in [('benny-boi', '', 'benny-boi'), ('alice', '', 'alice'), ('alice', 'Team Lead', 'Team Lead')]:
            command = 'master_user=$1; operator_name=$2; ' + line + '; printf "%s" "$operator_name"'
            result = subprocess.check_output(['bash', '-c', command, 'test', master, explicit], text=True)
            self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
