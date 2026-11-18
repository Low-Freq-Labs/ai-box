"""Offline protocol and import-boundary checks; never contact a test server."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

CLIENT = Path(__file__).resolve().parents[1] / 'assets/remote-tests/client.py'


@unittest.skipUnless(os.name == 'posix', 'Linux isolated Python launcher')
class RemotePhaseTests(unittest.TestCase):
    def run_code(self, code):
        setup = "import runpy,sys,json; loaded=runpy.run_path(sys.argv[1]); client=loaded['PAYLOAD']; phase=sys.modules['phase_client_fixture']; reader=sys.modules['phase_reader_fixture']; "
        result = subprocess.run(['/usr/bin/python3', '-I', '-S', '-c', setup + '\n' + code, str(CLIENT)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_observation_is_historical_and_bound_to_request(self):
        self.run_code('''
request=dict(owner='nova',run_id='proof',input_sha256='a'*64,profile='offline-python-v1',nonce='12345678-1234-1234-1234-123456789abc')
response=dict(schema=1,operation='phase-observation-v1',**request,classification='historical_phase_observation',current_phase='unknown',closure_proven=False,retry_allowed=False,last_observed_phase='closing',observed_at=123,epoch='b'*32,producer_invocation='c'*32,producer_boot='d'*32)
wire=json.dumps(response).encode()
result=phase.parse(wire,request)
assert result['classification']=='historical_phase_observation'
assert result['closure_proven'] is False and result['retry_allowed'] is False
for key,value in [('owner','other'),('nonce','bad'),('input_sha256','e'*64),('closure_proven',True),('retry_allowed',True),('current_phase','running'),('unexpected',True)]:
    bad=dict(response);bad[key]=value
    assert phase.parse(json.dumps(bad).encode(),request)==reader.UNKNOWN
for raw in (b'{', b'x'*4097, b'{"schema":1,"schema":1}'):
    assert phase.parse(raw,request)==reader.UNKNOWN
calls=[]
def exchange(owner,args):
    calls.append((owner,args));return 0,wire,b'',False
assert phase.request_phase(exchange,request)==result
assert len(calls)==1 and calls[0][1][0]=='phase-observation-v1'
for code,uncertain in ((1,False),(0,True)):
    calls.clear()
    def failure(owner,args):
        calls.append(args);return code,wire,b'',uncertain
    assert phase.request_phase(failure,request)==reader.UNKNOWN
    assert len(calls)==1
''')

    def test_phase_ssh_uses_enrolled_host_and_rejects_injection(self):
        self.run_code('''
client.configured_host=lambda:'test.example'
args=['phase-observation-v1','proof','a'*64,'offline-python-v1','12345678-1234-1234-1234-123456789abc']
argv=client.ssh_argv('nova',args)
assert argv[-6:]==['test.example',*args]
assert 'HostName=test.example' in argv and 'StrictHostKeyChecking=yes' in argv
for owner,command in [('nova;id',args),('nova',args[:-1]+['bad']),('nova',args[:1]+['proof;id']+args[2:])]:
    try: client.ssh_argv(owner,command)
    except (ValueError,client.ClientError): pass
    else: raise AssertionError('Unsafe command accepted')
''')

    def test_loader_rejects_nonisolated_start_and_tampered_payload(self):
        result = subprocess.run(['/usr/bin/python3', str(CLIENT), '--help'], capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Isolated Python', result.stderr)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'client.py'
            target.write_text(CLIENT.read_text().replace('Fixture prototype:', 'Modified prototype:', 1))
            result = subprocess.run(['/usr/bin/python3', '-I', '-S', str(target), '--help'], capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Embedded source digest mismatch', result.stderr)

    def test_caller_and_sibling_modules_cannot_replace_embedded_modules(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'client.py'
            target.write_bytes(CLIENT.read_bytes())
            for name in ('phase_client_fixture', 'phase_reader_fixture', 'phase_event_fixture', 'visibility_model', 'sitecustomize'):
                (Path(temp)/(name+'.py')).write_text("raise RuntimeError('UNTRUSTED_MODULE_LOADED')")
            env=dict(os.environ, PYTHONPATH=temp)
            result = subprocess.run(['/usr/bin/python3','-I','-S',str(target),'phase-observation-v1','--help'], cwd=temp, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('phase-observation-v1', result.stdout)
            self.assertNotIn('UNTRUSTED_MODULE_LOADED', result.stderr)

    def test_embedded_payload_matches_reviewable_source(self):
        result = subprocess.run(['/usr/bin/python3',str(CLIENT.parent/'build_client.py'),'--check'], capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
