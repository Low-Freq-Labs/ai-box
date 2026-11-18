"""Linux isolated proof: durable receipts, real child closure, reserve boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import storage_run as runner
import control_capacity as capacity


class ReceiptTests(unittest.TestCase):
    def test_corrupt_latest_slot_falls_back_and_unlink_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'receipt'; j=runner.Journal(path,create=True)
            try:
                j.write({'version':1}); j.write({'version':2})
                os.pwrite(j.fd,b'broken',0)
                self.assertEqual(j.read(),{'version':1})
                path.unlink()
                with self.assertRaises((RuntimeError,FileNotFoundError)):j.write({'version':3})
            finally:j.close()

    def test_symlink_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'receipt';p.symlink_to(Path(d)/'target')
            with self.assertRaises(OSError):runner.Journal(p,create=True)


class ReserveTests(unittest.TestCase):
    def test_arm_release_and_preserve_unrelated_data(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'reserve';capacity.initialize(base)
            other=Path(d)/'work';other.write_text('keep')
            r=capacity.maintain(base,4096,3,0,0,0,0)
            self.assertEqual(r['action'],'armed');self.assertTrue(r['after']['armed'])
            r=capacity.maintain(base,4096,3,2**63,2**63,2**63,2**63)
            self.assertEqual(r['action'],'released');self.assertEqual(r['after']['allocated_bytes'],0)
            self.assertEqual(other.read_text(),'keep')
            self.assertEqual(capacity.maintain(base,4096,3,2**63,2**63,2**63,2**63)['action'],'unchanged')

    def test_unexpected_inode_aborts_without_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'reserve';capacity.initialize(base)
            alien=base/'inodes'/'unexpected';alien.write_text('keep')
            with self.assertRaises(RuntimeError):capacity.maintain(base,4096,3,2**63,2**63,2**63,2**63)
            self.assertEqual(alien.read_text(),'keep')


class SupervisorTests(unittest.TestCase):
    def scenario(self,argv,refuse=False):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);output=root/'output';output.mkdir()
            stub=root/'budget';calls=root/'calls'
            stub.write_text('#!/usr/bin/python3\nimport sys,json,os\n'
                f'p={str(output)!r};calls={str(calls)!r}\n'
                'with open(calls,"a") as f:f.write(sys.argv[1]+"\\n")\n'
                + ('if sys.argv[1]=="renew":sys.exit(3)\n' if refuse else '')+
                's=os.stat(p);print(json.dumps({"id":"fixture","revision":1,"device":s.st_dev,"inode":s.st_ino,"state":"ACTIVE"}))\n')
            stub.chmod(0o755)
            plan=root/'plan.json';plan.write_text(json.dumps({'cases':[
                {'id':'first','argv':argv,'timeout':1},
                {'id':'second','argv':['/usr/bin/touch','second-ran'],'timeout':1}]}))
            args=dict(plan=str(plan),output=str(output),project='fixture',run='proof',bytes=1048576,inodes=10,deadline=10)
            code=f'import sys;sys.path.insert(0,{str(Path(__file__).parent)!r});import storage_run as r;from types import SimpleNamespace;r.BUDGET={str(stub)!r};sys.exit(r.run(SimpleNamespace(**{args!r})))'
            result=subprocess.run(['/usr/bin/python3','-I','-c',code],capture_output=True,text=True,timeout=25)
            j=runner.Journal(output/'storage-run-proof.receipt')
            try:receipt=j.read()
            finally:j.close()
            return result.returncode,receipt,(output/'second-ran').exists(),calls.read_text().splitlines()

    def test_success_records_both_cases_and_releases(self):
        code,r,second,calls=self.scenario(['/usr/bin/true'])
        self.assertEqual(code,0);self.assertEqual(r['completed'],['first','second'])
        self.assertTrue(second and r['writers_closed'] and r['reservation_released'])
        self.assertEqual(calls.count('release'),1)

    def test_failure_does_not_start_next_case(self):
        code,r,second,calls=self.scenario(['/usr/bin/false'])
        self.assertEqual(code,3);self.assertEqual(r['state'],'CASE_FAILED');self.assertFalse(second)

    def test_renewal_refusal_stops_before_any_case(self):
        code,r,second,calls=self.scenario(['/usr/bin/true'],True)
        self.assertEqual(r['state'],'SAFE_BOUNDARY_STOP');self.assertEqual(r['unrun'],['first','second'])
        self.assertFalse(second)

    def test_timeout_closes_actual_descendants(self):
        code,r,second,calls=self.scenario(['/bin/sh','-c','sleep 30 & wait'])
        self.assertEqual(code,3);self.assertFalse(second);self.assertTrue(r['writers_closed'])


if __name__=='__main__':unittest.main()
