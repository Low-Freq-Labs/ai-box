import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import freq_coms_receipts as receipts


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'FREQ_COMS_TESTING':'1','FREQ_COMS_ROOT':str(self.root/'coms')})
        self.env.start()
        (self.root/'coms/jarvis/inbox').mkdir(parents=True)
        (self.root/'coms/jarvis/read').mkdir()

    def tearDown(self):self.env.stop();self.temp.cleanup()

    def test_setgid_parent_creates_private_receipts_and_replays(self):
        base=receipts.root()/receipts.actor()
        base.mkdir(parents=True,exist_ok=True);base.chmod(0o2750)
        ident,new,_=receipts.begin('jarvis','Title','setgid','Body')
        self.assertTrue(new)
        self.assertEqual(receipts.directory().stat().st_mode & 0o7777,0o2700)
        self.assertEqual(receipts.begin('jarvis','Title','setgid','Body')[:2],(ident,False))
        self.assertEqual((receipts.directory()/(ident+'.json')).stat().st_mode & 0o7777,0o600)

    def test_existing_private_modes_and_unsafe_permissions(self):
        folder=receipts.directory(True)
        for mode in (0o700,0o2700):
            folder.chmod(mode);self.assertEqual(receipts.directory(),folder)
        for mode in (0o750,0o770,0o707,0o2750,0o2770,0o2707,0o1700,0o4700):
            folder.chmod(mode)
            with self.subTest(mode=oct(mode)),self.assertRaisesRegex(ValueError,'private to sender'):
                receipts.directory()

    def test_private_mode_still_requires_sender_ownership(self):
        receipts.directory(True).chmod(0o2700)
        sender=receipts.actor();wrong_uid=os.geteuid()+1
        with patch.object(receipts.os,'geteuid',return_value=wrong_uid),patch.object(receipts,'actor',return_value=sender):
            with self.assertRaisesRegex(ValueError,'private to sender'):receipts.directory()

    def test_same_key_one_envelope_and_conflict_refused(self):
        ident,new,value=receipts.begin('jarvis','Title','same','Full body')
        self.assertTrue(new)
        self.assertEqual(receipts.begin('jarvis','Title','same','Full body')[:2],(ident,False))
        with self.assertRaisesRegex(ValueError,'conflicts'): receipts.begin('jarvis','Title','same','Different')
        self.assertEqual(len(list(receipts.directory().glob('*.json'))),1)

    def test_publication_verifies_body_and_records_identity(self):
        ident,_,value=receipts.begin('jarvis','Title','pub','Body')
        parent=self.root/'coms/jarvis/inbox';temp=parent/'.tmp';target=parent/'message.md'
        temp.write_text('Wrong')
        with self.assertRaisesRegex(ValueError,'checksum'): receipts.publish(ident,temp,target)
        self.assertFalse(target.exists())
        temp.write_text('Body');receipts.publish(ident,temp,target)
        status=receipts.read(receipts.directory()/(ident+'.json'))
        self.assertEqual(status['state'],'DURABLY_STORED')
        self.assertEqual(target.read_text(),'Body')

    def test_enospc_before_publication_never_claims_stored(self):
        ident,_,_=receipts.begin('jarvis','Title','space','Body')
        parent=self.root/'coms/jarvis/inbox';temp=parent/'.tmp';temp.write_text('Body')
        with patch.object(receipts.os,'fsync',side_effect=OSError(28,'ENOSPC')):
            with self.assertRaises(OSError): receipts.publish(ident,temp,parent/'body.md')
        self.assertFalse((parent/'body.md').exists())
        self.assertEqual(receipts.read(receipts.directory()/(ident+'.json'))['state'],'NOT_STORED')

    def test_uncertain_delivery_never_retried(self):
        ident,_,_=receipts.begin('jarvis','Title','uncertain','Body')
        value=receipts.update(ident,'DELIVERY_UNCERTAIN','BEFORE_PASTE')
        with self.assertRaisesRegex(ValueError,'not proven retryable'): receipts.retry(ident,value['revision'])

    def test_public_status_does_not_leak_unknown_fields(self):
        value={'message_id':'id','body':'private','title':'private','tokens':'private','state':'NOT_STORED'}
        self.assertEqual(receipts.public(value),{'message_id':'id','state':'NOT_STORED'})

    def test_concurrent_key_has_one_new_submission(self):
        cmd=[sys.executable,str(ROOT/'lib/freq_coms_receipts.py'),'begin','jarvis','Title','concurrent']
        processes=[subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
        outputs=[p.communicate(b'body')[0].decode() for p in processes]
        self.assertEqual(sum('|NEW|' in out for out in outputs),1,outputs)
        self.assertEqual(sum('|EXISTING|' in out for out in outputs),1,outputs)


if __name__=='__main__':unittest.main()
