import hashlib
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import test_project_archive as archive_tests
PROJECT_ARCHIVE=archive_tests.PROJECT_ARCHIVE
TASK_REGISTER=archive_tests.TASK_REGISTER
TASK_READY=archive_tests.TASK_READY

class RetirementTests(unittest.TestCase):
    setUp=archive_tests.ProjectArchiveTests.setUp
    tearDown=archive_tests.ProjectArchiveTests.tearDown
    command=archive_tests.ProjectArchiveTests.command
    assert_ok=archive_tests.ProjectArchiveTests.assert_ok
    def blocked(self, title="Abandoned scope"):
        self.assert_ok(self.command(TASK_REGISTER, "PVE-FREQ", title, "Unfinished implementation.", "Scope withdrawn"))
        source = self.project / "blocked" / (title + ".md")
        before = source.read_bytes()
        revision = hashlib.sha256(str(source.relative_to(self.project)).encode() + b"\0" + before).hexdigest()
        evidence = self.root / "operator.txt"
        evidence.write_text("Operator requests retirement of abandoned scope.")
        changes = self.root / "retirement.json"
        changes.write_text(json.dumps({"schema":1,"reason":"Cancelled by operator","note":"Preserve unfinished work as history.","evidence":{str(evidence):hashlib.sha256(evidence.read_bytes()).hexdigest()}}))
        return source, before, revision, changes

    def retire(self, title, revision, changes, **kw):
        return self.command(PROJECT_ARCHIVE, "PVE-FREQ", title, "--retire", str(changes), "--expected-revision", revision, **kw)

    def test_retirement_preserves_unfinished_truth_and_transaction(self):
        source,before,revision,changes=self.blocked()
        self.assert_ok(self.retire("Abandoned scope",revision,changes))
        archived=self.project/"archive"/source.name
        self.assertFalse(source.exists())
        text=archived.read_text()
        self.assertIn("Unfinished implementation.",text)
        self.assertIn("**RETIRED**",text)
        self.assertIn("not implementation completion or acceptance",text)
        self.assertNotIn("**DONE**",text)
        self.assertEqual(list((self.project/"done").iterdir()),[])
        journals=list((self.project/".transactions").iterdir())
        self.assertEqual(len(journals),1)
        self.assertEqual((journals[0]/"before.bin").read_bytes(),before)
        self.assertEqual(json.loads((journals[0]/"prepared.json").read_text())["audit"]["kind"],"retirement")
        self.assertTrue((journals[0]/"committed.json").exists())

    def test_stale_revision_refused_without_mutation(self):
        source,before,revision,changes=self.blocked()
        result=self.retire("Abandoned scope","0"*64,changes)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(source.read_bytes(),before)
        self.assertFalse((self.project/"archive"/source.name).exists())

    def test_changed_evidence_refused(self):
        source,before,revision,changes=self.blocked()
        (self.root/"operator.txt").write_text("Changed")
        self.assertNotEqual(self.retire("Abandoned scope",revision,changes).returncode,0)
        self.assertEqual(source.read_bytes(),before)

    def test_peer_active_and_inactive_caller_refused(self):
        source,before,revision,changes=self.blocked()
        self.assertNotEqual(self.retire("Abandoned scope",revision,changes,agent="jarvis").returncode,0)
        self.assertEqual(source.read_bytes(),before)
        self.assert_ok(self.command(TASK_READY,"PVE-FREQ","Abandoned scope","finn"))
        self.assert_ok(self.command(Path(__file__).resolve().parents[1]/"bin/project-assign","PVE-FREQ","active",agent="jarvis"))
        active=self.project/"active/finn"/source.name
        revision=hashlib.sha256(str(active.relative_to(self.project)).encode()+b"\0"+active.read_bytes()).hexdigest()
        self.assertNotEqual(self.retire("Abandoned scope",revision,changes,agent="jarvis").returncode,0)
        self.assertTrue(active.exists())

if __name__=="__main__":unittest.main()
