import asyncio
import hashlib
import json
import os
from pathlib import Path
import pwd
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from connector import Connector, authorized, read_record, roster


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.coms = self.root / 'coms'
        self.coms.mkdir()
        self.sender = pwd.getpwuid(os.getuid()).pw_name
        (self.coms / self.sender / 'inbox').mkdir(parents=True)
        self.config = dict(user_id=123, guild_id=456, channel_id=789,
                           coms_root=str(self.coms), outbox=str(self.root))
        self.path = self.root / f'2026-09-05_123456_123456789_123_{self.sender}.json'
        self.record = dict(schema=1, sender=self.sender, title='UPDATE', message='hello @everyone')
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.record))
        self.path.chmod(0o660)

    def tearDown(self):
        self.tmp.cleanup()

    def test_authorization(self):
        event = SimpleNamespace(user=SimpleNamespace(id=123, bot=False), guild_id=456, channel_id=789)
        self.assertTrue(authorized(self.config, event))
        for field in ('guild_id', 'channel_id'):
            previous = getattr(event, field)
            setattr(event, field, 0)
            self.assertFalse(authorized(self.config, event))
            setattr(event, field, previous)
        event.user.id = 0
        self.assertFalse(authorized(self.config, event))
        event.user.id, event.user.bot = 123, True
        self.assertFalse(authorized(self.config, event))

    def test_roster_excludes_bot_and_symlink(self):
        for name in ('sonny', 'freq-discord'):
            (self.coms / name / 'inbox').mkdir(parents=True)
        (self.coms / 'alias').symlink_to(self.coms / self.sender)
        self.assertEqual(roster(self.coms), [self.sender])

    def test_valid_record(self):
        record, meta, digest = read_record(self.path, [self.sender])
        self.assertEqual(record, self.record)
        self.assertEqual(digest, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_reject_bad_fields_and_schema(self):
        for key, value in [('schema', True), ('schema', 2), ('message', ''), ('sender', 'impostor')]:
            original = self.record[key]
            self.record[key] = value
            self.write()
            with self.assertRaises(ValueError):
                read_record(self.path, [self.sender])
            self.record[key] = original
        self.record['extra'] = 'unexpected'
        self.write()
        with self.assertRaises(ValueError):
            read_record(self.path, [self.sender])

    def test_reject_owner_mismatch(self):
        with patch('connector.pwd.getpwuid', return_value=SimpleNamespace(pw_name='impostor')):
            with self.assertRaises(ValueError):
                read_record(self.path, [self.sender])

    def test_reject_symlink_and_permissions(self):
        self.path.chmod(0o666)
        with self.assertRaises(ValueError):
            read_record(self.path, [self.sender])
        other = self.root / 'original'
        self.path.rename(other)
        self.path.symlink_to(other)
        with self.assertRaises(OSError):
            read_record(self.path, [self.sender])

    async def test_confirmation_preserves_envelope_and_prevents_repost(self):
        client = Connector(self.config, 'test-only', self.root)
        async def post(record):
            self.assertTrue(self.path.exists())
            return '123456789'
        client.post_record = AsyncMock(side_effect=post)
        await client.deliver(self.path)
        self.assertTrue(self.path.exists())
        self.assertEqual(client.db.execute('SELECT remote_id FROM delivery_receipts WHERE name=?', (self.path.name,)).fetchone(), ('123456789',))
        await client.deliver(self.path)
        client.post_record.assert_awaited_once()
        await client.close()
        client.db.close()

    async def test_failure_held_across_restart_without_retry(self):
        client = Connector(self.config, 'test-only', self.root)
        client.post_record = AsyncMock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            await client.deliver(self.path)
        self.assertTrue(self.path.exists())
        await client.close()
        client.db.close()
        other = Connector(self.config, 'test-only', self.root)
        other.post_record = AsyncMock()
        await other.deliver(self.path)
        other.post_record.assert_not_awaited()
        self.assertTrue(self.path.exists())
        await other.close()
        other.db.close()

    async def test_changed_record_not_deleted(self):
        client = Connector(self.config, 'test-only', self.root)
        async def post(record):
            self.path.unlink()
            self.record['message'] = 'replacement'
            self.write()
        client.post_record = AsyncMock(side_effect=post)
        with self.assertRaises(ValueError):
            await client.deliver(self.path)
        self.assertTrue(self.path.exists())
        await client.close()
        client.db.close()

    async def test_post_disables_mentions_and_attaches_large_reply(self):
        client = Connector(self.config, 'test-only', self.root)
        response = MagicMock()
        response.status = 200
        response.json = AsyncMock(return_value={'id': '123'})
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        session = MagicMock()
        session.post.return_value = context
        session.__aenter__ = AsyncMock(return_value=session)
        with patch('connector.aiohttp.ClientSession', return_value=session):
            await client.post_record(self.record)
            payload = session.post.call_args.kwargs['json']
            self.assertEqual(payload['allowed_mentions']['parse'], [])
            self.assertIn('@everyone', payload['embeds'][0]['description'])
            self.record['message'] = 'large reply ' * 1000
            await client.post_record(self.record)
            self.assertIn('data', session.post.call_args.kwargs)
            response.status = 403
            with self.assertRaises(RuntimeError):
                await client.post_record(self.record)
            self.assertEqual(session.post.call_count, 3)
        await client.close()
        client.db.close()

    async def test_plain_message_authorization_and_deduplication(self):
        client = Connector(self.config, 'test-only', self.root)
        self.assertTrue(client.intents.message_content)
        event = SimpleNamespace(author=SimpleNamespace(id=0, bot=False),
                                guild=SimpleNamespace(id=456), channel=SimpleNamespace(id=789),
                                id=111, add_reaction=AsyncMock())
        client._deliver_inbound = AsyncMock()
        await client.on_message(event)
        client._deliver_inbound.assert_not_awaited()
        event.author.id = 123
        await client.on_message(event)
        await client.on_message(event)
        client._deliver_inbound.assert_awaited_once()
        event.add_reaction.assert_awaited_once_with('✅')
        await client.close()
        client.db.close()

    async def test_identity_color_is_loaded_on_every_reply(self):
        client = Connector(self.config, 'test-only', self.root)
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value={'id': '123'})
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        session = MagicMock()
        session.post.return_value = context
        session.__aenter__ = AsyncMock(return_value=session)
        with patch('connector.aiohttp.ClientSession', return_value=session), patch(
                'connector.Path.read_text', return_value="export FREQ_USER_TRUECOLOR='251;146;60'") as identity:
            await client.post_record(self.record)
            self.assertEqual(session.post.call_args.kwargs['json']['embeds'][0]['color'], 0xFB923C)
            identity.return_value = "export FREQ_USER_TRUECOLOR='96;165;250'"
            await client.post_record(self.record)
            self.assertEqual(session.post.call_args.kwargs['json']['embeds'][0]['color'], 0x60A5FA)
        await client.close()
        client.db.close()


if __name__ == '__main__':
    unittest.main()
