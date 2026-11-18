"""Package input, grant, job, and command-boundary tests; no real APT calls."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import io
import unittest
from unittest.mock import patch
from contextlib import nullcontext

spec = importlib.util.spec_from_file_location('package_broker', Path(__file__).with_name('broker.py'))
b = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = b
spec.loader.exec_module(b)
import packages as p


class PackagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = {'grants':{'jarvis':['packages']}, 'grant_uids':{'jarvis':1001}}
        for target, attr, value in (
            (p, 'JOBS', Path(self.temp.name) / 'jobs'),
            (b, 'load', lambda:copy.deepcopy(self.state)),
            (b, 'operator', lambda uid:uid == 0),
            (b, 'agents', lambda:['jarvis', 'clancy']),
            (b.pwd, 'getpwuid', lambda uid:type('Account', (), {'pw_name':{0:'root',1001:'jarvis',1002:'clancy'}[uid]})()),
        ):
            change = patch.object(target, attr, value)
            change.start(); self.addCleanup(change.stop)
        self.run = patch.object(b, 'run', return_value='ActiveState=inactive\nJob=\n').start()
        self.addCleanup(patch.stopall)

    def request(self, verb='install', **extra):
        return {'area':'host', 'action':'packages', 'verb':verb, **extra}

    def test_grant_required_and_uid_bound(self):
        req = self.request(packages=['jq'])
        for uid in (1002,):
            with self.assertRaisesRegex(ValueError, 'not granted'):
                b.handle(uid, req)
        self.state['grant_uids']['jarvis'] = 99
        with self.assertRaisesRegex(ValueError, 'not granted'):
            b.handle(1001, req)
        self.assertFalse(p.JOBS.exists())

    def test_valid_job_queued_without_running_apt_in_broker(self):
        result = b.handle(1001, self.request(packages=['jq', 'tree', 'jq']))
        self.assertIn('queued', result)
        job = p.current(b)
        self.assertEqual(job['packages'], ['jq','tree'])
        self.assertEqual(job['uid'],1001)
        self.assertEqual(job['status'],'queued')
        self.assertEqual(self.run.call_args.args[0], ['/usr/bin/systemctl','start','--no-block',p.UNIT])

    def test_options_files_patterns_and_remove_suffixes_rejected(self):
        for value in ('-y','--allow-unauthenticated','./bad.deb','/tmp/x.deb','https://host/x',
                      'jq=1.0','jq/testing','jq-', 'jq+', 'jq;id', 'jq\nsh','*','jq:amd64'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                b.handle(1001,self.request(packages=[value]))
        for values in ([], ['jq']*33, 'jq', [1]):
            with self.assertRaises(ValueError): p.names(values)
        self.assertEqual(p.names(['libstdc++6','python3-venv']),['libstdc++6','python3-venv'])

    def test_unknown_fields_and_operations_rejected(self):
        for req in (self.request(packages=['jq'], command='id'), self.request('remove',packages=['jq']),
                    self.request('install',packages=['jq'],uid=0), self.request('refresh',source='custom')):
            with self.assertRaises(ValueError): b.handle(1001,req)

    def test_busy_refuses_second_job(self):
        self.run.return_value='ActiveState=activating\nJob=1\n'
        with self.assertRaisesRegex(ValueError,'already running'):
            b.handle(1001,self.request(packages=['jq']))

    def test_systemd_queued_start_is_busy_even_before_activation(self):
        self.run.return_value='ActiveState=inactive\nJob=123\n'
        with self.assertRaisesRegex(ValueError,'already running'):
            b.handle(1001,self.request(packages=['jq']))

    def test_status_path_validation_and_interrupted_state(self):
        with self.assertRaises(ValueError):
            b.handle(1001,self.request('status',job='../state'))
        b.handle(1001,self.request(packages=['jq']))
        status=json.loads(b.handle(1001,self.request('status',job='latest')))
        self.assertEqual(status['status'],'interrupted')

    def test_fixed_apt_arguments(self):
        args=p.apt_command({'operation':'install','packages':['jq']})
        self.assertIn('--no-remove',args)
        self.assertIn('--no-upgrade',args)
        self.assertIn('APT::Get::AllowUnauthenticated=false',args)
        self.assertEqual(args[-2:],['install','jq'])
        self.assertEqual(p.apt_command({'operation':'refresh'})[-1],'update')
        self.assertNotIn('upgrade',args)

    def test_revocation_blocks_subsequent_package_request(self):
        self.state['grants']['jarvis']=[]
        with self.assertRaisesRegex(ValueError,'not granted'):
            b.handle(1001,self.request('refresh'))
        self.run.assert_not_called()

    def test_revocation_before_worker_start_never_calls_apt(self):
        b.handle(1001,self.request(packages=['jq']))
        self.state['grants']['jarvis']=[]
        with patch.dict(sys.modules, broker=b), patch.object(b,'locked',side_effect=nullcontext), \
                patch.object(p.subprocess,'run') as apt:
            p.worker()
            apt.assert_not_called()
        self.assertEqual(p.current(b)['status'],'failed')

    def test_apt_failure_returns_fixed_hint_not_raw_output(self):
        process=type('Process',(),{'stdout':io.BytesIO(b'E: seteuid failed: Operation not permitted https://user:secret@repo/\n'),
                                  'wait':lambda self:100})()
        with patch.object(p.subprocess,'Popen',return_value=process):
            code,hint=p.apt_run(['/usr/bin/apt-get'])
        self.assertEqual(code,100)
        self.assertEqual(hint,'required OS operation denied')
        self.assertNotIn('secret',hint)


if __name__ == '__main__':
    unittest.main()
