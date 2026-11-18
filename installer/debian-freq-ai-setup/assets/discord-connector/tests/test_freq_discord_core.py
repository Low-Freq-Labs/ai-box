#!/usr/bin/env python3
import json
import os
import pathlib
import pwd
import stat
import tempfile
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from freq_discord_core import (  # noqa: E402
    ConnectorConfig,
    ConnectorError,
    MAX_IMAGE_BYTES,
    color_for,
    compose_agent_body,
    discover_roster,
    load_outbox_record,
    parse_inbound,
    stage_images,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"png-data"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-data"
WEBP = b"RIFF\x08\x00\x00\x00WEBP" + b"webp-data"


class DiscordCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.coms = self.root / "coms"
        for agent in ("chris", "donny"):
            (self.coms / agent / "inbox").mkdir(parents=True)
            (self.coms / agent / "media").mkdir()
            media = self.coms / agent / "media"
            media.chmod(0o2770)
            subprocess.run(['setfacl', '-m', 'd:u::rwx,d:g::rwx,d:m::rwx,d:o::---', str(media)], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_roster_and_plain_name_message_parsing(self):
        roster = discover_roster(self.coms)
        self.assertEqual(roster, ("chris", "donny"))
        parsed = parse_inbound(
            "  Chris: compare these screenshots\nthen tell me what changed  ",
            roster,
            3,
        )
        self.assertEqual(parsed.recipient, "chris")
        self.assertEqual(
            parsed.text, "compare these screenshots\nthen tell me what changed"
        )

    def test_image_only_message_is_valid_but_empty_message_is_not(self):
        roster = discover_roster(self.coms)
        parsed = parse_inbound("donny", roster, 10)
        self.assertEqual(parsed.text, "")
        with self.assertRaisesRegex(ConnectorError, "at least one attachment"):
            parse_inbound("donny", roster, 0)

    def test_unknown_agent_and_more_than_ten_images_fail(self):
        roster = discover_roster(self.coms)
        with self.assertRaisesRegex(ConnectorError, "unknown agent"):
            parse_inbound("jarvis hello", roster, 0)
        with self.assertRaisesRegex(ConnectorError, "between 0 and 10"):
            parse_inbound("chris hello", roster, 11)

    def test_stages_ten_mixed_images_atomically_with_safe_names(self):
        images = [PNG, JPEG, WEBP, PNG, JPEG, WEBP, PNG, JPEG, WEBP, PNG]
        directory, paths = stage_images(self.coms, "chris", 1545551228484849735, images)

        self.assertEqual(directory.name, "1545551228484849735")
        self.assertEqual(len(paths), 10)
        self.assertEqual(
            [path.name for path in paths],
            [
                "01.png",
                "02.jpg",
                "03.webp",
                "04.png",
                "05.jpg",
                "06.webp",
                "07.png",
                "08.jpg",
                "09.webp",
                "10.png",
            ],
        )
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o2770)
        for path in paths:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o660)
        self.assertEqual(
            list((self.coms / "chris" / "media").glob(".incoming-*")), []
        )

    def test_bad_or_oversize_picture_leaves_no_partial_batch(self):
        media = self.coms / "chris" / "media"
        cases = ([PNG, b"not-an-image"], [PNG, b"\x89PNG\r\n\x1a\n" + b"x" * MAX_IMAGE_BYTES])
        for index, images in enumerate(cases, start=1):
            with self.subTest(index=index):
                with self.assertRaises(ConnectorError):
                    stage_images(self.coms, "chris", index, images)
                self.assertEqual(list(media.iterdir()), [])

    def test_restrictive_umask_inherits_shared_permissions(self):
        previous = os.umask(0o077)
        try:
            directory, paths = stage_images(self.coms, 'chris', 1234, [PNG])
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o2770)
        self.assertEqual(stat.S_IMODE(paths[0].stat().st_mode), 0o660)
        self.assertEqual(paths[0].stat().st_gid, (self.coms / 'chris/media').stat().st_gid)

    def test_missing_inheritance_fails_cleanly(self):
        media = self.coms / 'chris/media'
        media.chmod(0o770)
        with self.assertRaisesRegex(ConnectorError, 'not inherited'):
            stage_images(self.coms, 'chris', 1235, [PNG])
        self.assertEqual(list(media.iterdir()), [])

    def test_composes_exact_agent_body_with_all_picture_paths(self):
        paths = (
            pathlib.Path("/var/lib/freq-agents/coms/chris/media/123/01.png"),
            pathlib.Path("/var/lib/freq-agents/coms/chris/media/123/02.jpg"),
        )
        body = compose_agent_body("please compare these", paths)
        self.assertEqual(
            body,
            "please compare these\n\nPictures (2):\n"
            "- /var/lib/freq-agents/coms/chris/media/123/01.png\n"
            "- /var/lib/freq-agents/coms/chris/media/123/02.jpg",
        )

    def test_config_accepts_ids_and_agent_colors(self):
        path = self.root / "discord.json"
        path.write_text(
            json.dumps(
                {
                    "sonny_user_id": "12345678901234567",
                    "guild_id": "760990483718995978",
                    "channel_id": "1545551228484849735",
                    "agent_colors": {"chris": "#36C98F"},
                }
            )
        )
        config = ConnectorConfig.load(path)
        self.assertEqual(config.channel_id, 1545551228484849735)
        self.assertEqual(config.agent_colors["chris"], 0x36C98F)
        self.assertEqual(color_for("chris", config.agent_colors), 0x36C98F)
        self.assertEqual(color_for("donny", {}), color_for("donny", {}))

    def test_outbox_record_requires_schema_sender_owner_and_mode(self):
        sender = pwd.getpwuid(os.geteuid()).pw_name
        path = self.root / f"2026-09-04_120000_123456789_99_{sender}.json"
        path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "sender": sender,
                    "title": "REVIEW DONE",
                    "message": "Everything looks clean.",
                }
            )
        )
        path.chmod(0o660)
        record = load_outbox_record(path, (sender,))
        self.assertEqual(record.sender, sender)
        self.assertEqual(record.title, "REVIEW DONE")

        path.chmod(0o600)
        with self.assertRaisesRegex(ConnectorError, "mode is not 0660"):
            load_outbox_record(path, (sender,))


if __name__ == "__main__":
    unittest.main()
