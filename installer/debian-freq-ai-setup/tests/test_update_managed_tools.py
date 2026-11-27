"""Release matching keeps the exact wheel compatibility and checksum boundary."""
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'assets/update-managed-tools'
loader = importlib.machinery.SourceFileLoader('managed_update', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class WheelReleaseTests(unittest.TestCase):
    wanted = 'py_spy-0.4.4-py2.py3-none-manylinux_2_5_x86_64.manylinux1_x86_64.whl'
    published = 'py_spy-0.4.4-py2.py3-none-manylinux1_x86_64.manylinux_2_5_x86_64.whl'

    def asset(self, name=None, digest='sha256:' + 'a' * 64):
        return {'name': name or self.published, 'digest': digest,
                'browser_download_url': 'https://github.com/example/tool/releases/download/v0.4.4/tool.whl'}

    def test_equivalent_compressed_platform_tags_match(self):
        asset = self.asset()
        self.assertEqual(module.release_asset([asset], self.wanted, 'py-spy'), asset)

    def test_different_architecture_abi_python_or_version_is_refused(self):
        for name in [self.published.replace('x86_64', 'aarch64'),
                     self.published.replace('-none-', '-cp313-'),
                     self.published.replace('-py2.py3-', '-py3-'),
                     self.published.replace('0.4.4', '0.4.3')]:
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                module.release_asset([self.asset(name)], self.wanted, 'py-spy')

    def test_ambiguous_equivalent_assets_are_refused(self):
        with self.assertRaises(RuntimeError):
            module.release_asset([self.asset(), self.asset(self.wanted)], self.wanted, 'py-spy')

    def test_absent_or_malformed_checksum_is_refused(self):
        for digest in [None, '', 'sha256:xyz', 'sha512:' + 'a' * 64]:
            with self.subTest(digest=digest), self.assertRaises(RuntimeError):
                module.release_asset([self.asset(digest=digest)], self.wanted, 'py-spy')

    def test_nonwheel_names_remain_exact(self):
        asset = self.asset('tool-x86_64.tar.gz')
        self.assertEqual(module.release_asset([asset], 'tool-x86_64.tar.gz', 'tool'), asset)
        with self.assertRaises(RuntimeError):
            module.release_asset([asset], 'tool-aarch64.tar.gz', 'tool')


if __name__ == '__main__':
    unittest.main()
