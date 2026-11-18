#!/usr/bin/env python3
import asyncio
import json
import os
import pathlib
import sys
import tempfile
import subprocess
import types
import unittest


try:
    import discord
except ModuleNotFoundError as error:
    raise unittest.SkipTest("discord.py is not installed in this test interpreter") from error


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from freq_discord_bot import FreqDiscordClient  # noqa: E402
from freq_discord_core import ConnectorConfig  # noqa: E402


PNG = b"\x89PNG\r\n\x1a\nclipboard-picture"


class FakeAttachment:
    def __init__(self, data):
        self.data = data
        self.size = len(data)
        self.content_type = "image/png"

    async def read(self, use_cached=True):
        return self.data


class FakeMessage:
    def __init__(self, content, attachments, user_id, guild_id, channel_id, message_id):
        self.content = content
        self.attachments = attachments
        self.id = message_id
        self.author = types.SimpleNamespace(id=user_id, bot=False)
        self.guild = types.SimpleNamespace(id=guild_id)
        self.channel = types.SimpleNamespace(id=channel_id)
        self.reactions = []
        self.replies = []

    async def add_reaction(self, reaction):
        self.reactions.append(reaction)

    async def reply(self, **kwargs):
        self.replies.append(kwargs)


class FakeChannel:
    def __init__(self):
        self.posts = []

    async def send(self, **kwargs):
        self.posts.append(kwargs)


class DiscordBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_gif_markdown_text_and_pdf_mixed_batch(self):
        files = [('animation.gif', b'GIF89a' + b'fixture', 'image/gif'),
                 ('../../notes.md', b'# Task\nRead this', 'text/markdown'),
                 ('report.txt', b'plain text', 'application/octet-stream'),
                 ('report.pdf', b'%PDF-1.7\nfixture', 'application/pdf')]
        attachments = []
        for filename, data, mime in files:
            item = FakeAttachment(data)
            item.filename, item.content_type = filename, mime
            attachments.append(item)
        message = FakeMessage('chris inspect these', attachments,
                             self.config.sonny_user_id, self.config.guild_id,
                             self.config.channel_id, 1545551228484849738)
        await self.client.on_message(message)
        self.assertEqual(message.replies, [])
        self.assertTrue(self.log.exists())
        folder = self.coms/'chris/media/1545551228484849738'
        expected_names = ['01.gif', '02-notes.md', '03-report.txt', '04-report.pdf']
        for expected_name, (name, data, mime) in zip(expected_names, files):
            self.assertEqual((folder/expected_name).read_bytes(), data)
        self.assertFalse((self.root/'notes.md').exists())
        self.assertIn('Attachments (4)', json.loads(self.log.read_text())[1])

    async def test_bad_text_batch_never_delivers_or_publishes(self):
        item = FakeAttachment(b'MZ\x00binary')
        item.filename, item.content_type = 'fake.txt', 'text/plain'
        message = FakeMessage('chris inspect', [FakeAttachment(PNG), item],
                             self.config.sonny_user_id, self.config.guild_id,
                             self.config.channel_id, 1545551228484849739)
        await self.client.on_message(message)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.coms/'chris/media/1545551228484849739').exists())
        self.assertTrue(message.replies)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.coms = self.root / "coms"
        self.outbox = self.root / "outbox"
        self.outbox.mkdir()
        for agent in ("chris", "donny"):
            (self.coms / agent / "inbox").mkdir(parents=True)
            (self.coms / agent / "media").mkdir()
            media = self.coms / agent / 'media'
            media.chmod(0o2770)
            subprocess.run(['setfacl', '-m', 'd:u::rwx,d:g::rwx,d:m::rwx,d:o::---', str(media)], check=True)
        self.log = self.root / "dev-msg.json"
        self.dev_msg = self.root / "dev-msg"
        self.dev_msg.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            f"pathlib.Path({str(self.log)!r}).write_text(json.dumps(sys.argv[1:]))\n"
        )
        self.dev_msg.chmod(0o755)
        self.config = ConnectorConfig(
            sonny_user_id=12345678901234567,
            guild_id=760990483718995978,
            channel_id=1545551228484849735,
            agent_colors={"chris": 0x36C98F},
            coms_root=self.coms,
            outbox=self.outbox,
            dev_msg=self.dev_msg,
            groups_path=self.root / 'groups.json',
        )
        self.client = FreqDiscordClient(self.config)

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_plain_name_and_pasted_picture_land_in_one_dev_msg(self):
        message = FakeMessage(
            "chris compare this",
            [FakeAttachment(PNG)],
            self.config.sonny_user_id,
            self.config.guild_id,
            self.config.channel_id,
            1545551228484849735,
        )

        await self.client.on_message(message)

        self.assertEqual(message.reactions, ["✅"])
        self.assertEqual(message.replies, [])
        arguments = json.loads(self.log.read_text())
        self.assertEqual(arguments[0], "chris")
        self.assertIn("compare this", arguments[1])
        picture = self.coms / "chris/media/1545551228484849735/01.png"
        self.assertIn(str(picture), arguments[1])
        self.assertEqual(picture.read_bytes(), PNG)

    async def test_bad_recipient_gets_failure_reaction_and_red_card(self):
        message = FakeMessage(
            "nobody hello",
            [],
            self.config.sonny_user_id,
            self.config.guild_id,
            self.config.channel_id,
            1545551228484849736,
        )

        await self.client.on_message(message)

        self.assertEqual(message.reactions, ["🚫"])
        self.assertEqual(len(message.replies), 1)
        embed = message.replies[0]["embed"]
        self.assertEqual(embed.title, "DELIVERY FAILED")
        self.assertIn("unknown agent", embed.description)
        self.assertFalse(self.log.exists())

    async def test_agent_reply_uses_sender_color_and_disables_mentions(self):
        channel = FakeChannel()

        await self.client._post_agent_reply(
            channel,
            "chris",
            "DONE",
            "@everyone finished cleanly",
        )

        self.assertEqual(len(channel.posts), 1)
        post = channel.posts[0]
        self.assertEqual(post["embed"].title, "CHRIS-MSG: [DONE]")
        self.assertEqual(post["embed"].description, "@everyone finished cleanly")
        self.assertEqual(post["embed"].colour.value, 0x36C98F)
        self.assertFalse(post["allowed_mentions"].everyone)


if __name__ == "__main__":
    unittest.main()
