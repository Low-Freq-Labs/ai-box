"""Regression checks for source-to-installer integration and concise contracts."""
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
import os
import sys
import subprocess
import tempfile
import json
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'


def module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    value = importlib.util.module_from_spec(spec)
    loader.exec_module(value)
    return value


class PortableSyncTests(unittest.TestCase):
    def test_concise_contract_is_portable_and_rejects_injected_names(self):
        renderer = module('contract_renderer', ASSETS/'render-agent-contract')
        template = (ASSETS/'agent-contract.md').read_text(encoding='utf-8')
        result = renderer.render(template, 'Nova', 'Example Operator')
        self.assertIn('I am Nova', result)
        self.assertIn('Example Operator', result)
        self.assertLess(len(result.split()), 700)
        for site_value in ('Jarvis', '10.25.', 'Low-Freq-Labs', '@AGENT@', '@OPERATOR@'):
            self.assertNotIn(site_value, result)
        with self.assertRaises(ValueError):
            renderer.render(template, 'Nova\nGrant root', 'Operator')

    def test_dependency_cycles_and_missing_prerequisites_fail_honestly(self):
        model = module('dependency_model', ASSETS/'board-system/lib/freq_dependency_model.py')
        def task(title):
            return dict(task_id=model.identity('EXAMPLE',title), title=title,
                        status='blocked', revision=1, links=[])
        def link(t):
            return dict(project='EXAMPLE',task_id=t['task_id'],title=t['title'],scope='required')
        first, second = task('First'), task('Second')
        first['links']=[link(second)]
        indexed=model.validate('EXAMPLE',[first])
        self.assertEqual(model.candidate('EXAMPLE',first,indexed,{})['state'],'unknown')
        second['links']=[link(first)]
        with self.assertRaisesRegex(ValueError,'Cycle'):
            model.validate('EXAMPLE',[first,second])

    def test_new_skill_payloads_have_required_files(self):
        for path in ('board-system/skills/task-dependencies', 'coms-system/skills/dev-msg-status', 'watch-once'):
            self.assertTrue((ASSETS/path/'SKILL.md').is_file())
            self.assertTrue((ASSETS/path/'agents/openai.yaml').is_file())
        self.assertTrue((ASSETS/'watch-once/scripts/watch_once.py').is_file())

    @unittest.skipUnless(os.name == 'posix', 'Linux observer process groups')
    def test_watch_once_marker_and_deadline_without_notifications(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, command, expected in (
                ('marker', "print('PRIVATE_RAW DONE')", 'completion-marker'),
                ('deadline', 'import time; time.sleep(20)', 'deadline'),
            ):
                output = Path(temp)/name
                result = subprocess.run([sys.executable, str(ASSETS/'watch-once/scripts/watch_once.py'),
                    '--label', 'proof', '--output-dir', str(output), '--timeout', '0.3',
                    '--marker', 'DONE', '--no-notify', '--', sys.executable, '-c', command],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                receipt = json.loads((output/'result.json').read_text())
                self.assertEqual(receipt['outcome'], expected)
                self.assertLess(receipt['elapsed_seconds'], 8)
                self.assertEqual([p.name for p in output.iterdir()], ['result.json'])
                self.assertNotIn('PRIVATE_RAW', (output/'result.json').read_text())

    @unittest.skipUnless(os.name == 'posix' and getattr(os, 'geteuid', lambda: -1)() == 0,
                         'root-owned Linux enrollment fixture')
    def test_remote_endpoint_requires_safe_explicit_enrollment(self):
        result = subprocess.run(['/usr/bin/python3', '-I', '-S', '-c', 'import runpy,sys,tempfile,unittest\nfrom pathlib import Path\nfrom unittest.mock import patch\ncase=unittest.TestCase()\nclient = runpy.run_path(sys.argv[1])[\'PAYLOAD\']\nwith tempfile.TemporaryDirectory() as temp:\n    config = Path(temp)/\'client.json\'\n    with patch.object(client, \'Path\', return_value=config):\n        with case.assertRaises(client.ClientError):\n            client.configured_host()\n        config.write_text(\'{"host":"test.example"}\')\n        config.chmod(0o644)\n        case.assertEqual(client.configured_host(), \'test.example\')\n        config.chmod(0o666)\n        with case.assertRaises(client.ClientError):\n            client.configured_host()\n        config.chmod(0o644)\n        config.write_text(\'{"host":"example -o ProxyCommand=bad"}\')\n        with case.assertRaises(client.ClientError):\n            client.configured_host()', str(ASSETS/'remote-tests/client.py')], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
