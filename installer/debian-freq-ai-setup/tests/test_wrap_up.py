import importlib.machinery
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
state = importlib.machinery.SourceFileLoader(
    "wrap_state", str(SOURCE / "assets/wrap-up-state")).load_module()


class WrapUpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "session-data"
        self.root.mkdir()
        self.resume = Path(self.temp.name) / "resume.md"
        self.journal = Path(self.temp.name) / "journal.md"
        self.resume.write_text("# Resume\nProject TEST; next: verify.\n")
        self.journal.write_text("# Journal\nBuilt fixture; not yet accepted.\n")
        self.drafts = [self.resume]

    def test_single_record_rotation_and_readback(self):
        first = state.save(self.root, "fixture", self.drafts)
        old = [p.read_bytes() for p in first]
        self.resume.write_text("# Resume\nNext session state.\n")
        second = state.save(self.root, "fixture", self.drafts)
        for index, path in enumerate(first):
            self.assertFalse(path.exists())
            self.assertEqual((path.parent / "archive" / path.name).read_bytes(), old[index])
            self.assertEqual(list(path.parent.glob("*.md")), [second[index]])
        self.assertEqual(second[0].read_bytes(), self.resume.read_bytes())

    def test_init_preserves_existing_state(self):
        first = state.save(self.root, "fixture", self.drafts)
        state.save(self.root, "fixture")
        self.assertTrue(all(p.exists() for p in first))

    def test_bad_draft_preserves_old_record(self):
        first = state.save(self.root, "fixture", self.drafts)
        self.resume.write_text("")
        with self.assertRaises(ValueError):
            state.save(self.root, "fixture", self.drafts)
        self.assertTrue(all(p.exists() for p in first))

    def test_archive_collision_never_overwrites(self):
        first = state.save(self.root, "fixture", self.drafts)
        collision = first[0].parent / "archive" / first[0].name
        collision.write_text("historical evidence")
        with self.assertRaisesRegex(ValueError, "collision"):
            state.save(self.root, "fixture", self.drafts)
        self.assertEqual(collision.read_text(), "historical evidence")
        self.assertTrue(all(p.exists() for p in first))

    def test_symlink_state_directory_rejected(self):
        state.save(self.root, "fixture")
        lane = self.root / "fixture"
        (lane / "session-state/archive").rmdir()
        (lane / "session-state").rmdir()
        (lane / "session-state").symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaises(OSError):
            state.save(self.root, "fixture", self.drafts)

    def test_write_failure_retains_old_record(self):
        first = state.save(self.root, "fixture", self.drafts)
        with patch.object(state.os, "fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                state.save(self.root, "fixture", self.drafts)
        self.assertTrue(all(p.exists() for p in first))
        self.assertFalse(list(self.root.rglob(".pending-*")))

    def test_agent_lanes_do_not_mix(self):
        first = state.save(self.root, "one", self.drafts)
        state.save(self.root, "two", self.drafts)
        self.assertTrue(all(p.exists() for p in first))

    def test_helper_does_not_claim_session_success(self):
        helper = (SOURCE / "assets/wrap-up-state").read_text()
        self.assertNotIn("Safe to close", helper)

    def test_obsolete_two_draft_call_is_rejected(self):
        with self.assertRaises(ValueError):
            state.save(self.root, "fixture", [self.resume, self.journal])


if __name__ == "__main__":
    unittest.main()
