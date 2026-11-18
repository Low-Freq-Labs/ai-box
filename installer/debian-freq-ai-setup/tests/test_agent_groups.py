"""Group behavior tests; Linux-only storage checks are explicit on Windows."""
import asyncio
import copy
import json
import importlib.machinery
import importlib.util
import io
import contextlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'assets/discord-connector'))
if sys.platform == 'win32':
    # Import shims only; no Linux storage/permission behavior is simulated as real.
    sys.modules.setdefault('pwd', types.ModuleType('pwd'))
    sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
    sys.modules.setdefault('grp', types.ModuleType('grp'))

from freq_groups import change, validate, load_groups, save_groups
from freq_discord_core import ConnectorConfig, ConnectorError
from freq_discord_bot import FreqDiscordClient

loader = importlib.machinery.SourceFileLoader('manage_groups', str(ROOT / 'assets/manage-agent-groups'))
spec = importlib.util.spec_from_loader(loader.name, loader)
manager = importlib.util.module_from_spec(spec)
loader.exec_module(manager)


class OperatorTests(unittest.TestCase):
    def test_nonroot_cannot_show_or_mutate(self):
        with patch.object(manager.os, 'geteuid', return_value=1001, create=True), patch.object(manager, 'load_groups') as read:
            for args in (['show'], ['create', 'devs'], ['finn', 'devs'], ['--forget-agent', 'finn']):
                with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'only the operator'):
                    manager.main(args)
            read.assert_not_called()

    def test_lifecycle_collision_and_retirement(self):
        with patch.object(manager.os, 'geteuid', return_value=0, create=True), \
             patch.object(manager, 'load_groups', return_value={'devs': ['finn', 'jarvis'], 'reviewers': ['finn']}), \
             patch.object(manager, 'discord_gid', return_value=123), patch.object(manager, 'save_groups') as save:
            with self.assertRaisesRegex(ValueError, 'already belongs'):
                manager.main(['--check-agent-name', 'devs'])
            manager.main(['--check-agent-name', 'new-agent'])
            manager.main(['--forget-agent', 'finn'])
            save.assert_called_once_with({'devs': ['jarvis'], 'reviewers': []}, 123)

    def test_show_includes_empty_groups_and_unassigned_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'lock'
            lock.touch()
            registry = Path(directory) / 'finn.conf'
            registry.touch()
            output = io.StringIO()
            with patch.object(manager.os, 'geteuid', return_value=0, create=True), \
                 patch.object(manager, 'load_groups', return_value={'devs': []}), \
                 patch.object(manager.fcntl, 'flock', create=True), \
                 patch.object(manager.fcntl, 'LOCK_EX', 2, create=True), \
                 patch.object(manager.fcntl, 'LOCK_NB', 4, create=True), \
                 patch('builtins.open', return_value=lock.open('rb')), \
                 patch.object(Path, 'glob', return_value=[registry]), contextlib.redirect_stdout(output):
                manager.main(['show'])
            self.assertIn('devs: (empty)', output.getvalue())
            self.assertIn('Unassigned: finn', output.getvalue())


class MembershipTests(unittest.TestCase):
    def test_create_assign_multiple_remove(self):
        groups = {}
        for name in ('devs', 'reviewers'):
            change(groups, ['create', name], ['finn', 'jarvis'])
            change(groups, ['finn', name], ['finn', 'jarvis'])
        change(groups, ['jarvis', 'devs'], ['finn', 'jarvis'])
        change(groups, ['finn', 'remove', 'devs'], ['finn', 'jarvis'])
        self.assertEqual(groups, {'devs': ['jarvis'], 'reviewers': ['finn']})

    def test_duplicate_assignment_is_idempotent(self):
        groups = {'devs': ['finn']}
        change(groups, ['finn', 'devs'], ['finn'])
        self.assertEqual(groups, {'devs': ['finn']})

    def test_invalid_commands_do_not_mutate(self):
        for args in (['create', 'finn'], ['create', 'show'], ['create', '../bad'],
                     ['create', 'two words'], ['create', 'devs'], ['nobody', 'devs'],
                     ['finn', 'missing'], ['finn', 'remove', 'missing'], ['jarvis', 'remove', 'devs'],
                     ['finn', 'remove', 'devs', 'extra']):
            with self.subTest(args=args):
                groups = {'devs': ['finn']}
                with self.assertRaises(ValueError):
                    change(groups, args, ['finn'])
                self.assertEqual(groups, {'devs': ['finn']})

    def test_stale_member_can_be_removed(self):
        groups = {'devs': ['finn']}
        change(groups, ['finn', 'remove', 'devs'], [])
        self.assertEqual(groups, {'devs': []})

    def test_registry_rejects_bad_schema_duplicates_and_limits(self):
        for raw in ({}, {'schema': True, 'groups': {}}, {'schema': 2, 'groups': {}},
                    {'schema': 1, 'groups': {'devs': ['finn', 'finn']}},
                    {'schema': 1, 'groups': {'devs': ['../finn']}},
                    {'schema': 1, 'groups': {'devs': [f'agent{i}' for i in range(33)]}}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate(raw)

    @unittest.skipUnless(sys.platform == 'linux' and getattr(os, 'geteuid', lambda: -1)() == 0, 'requires Linux root fixture')
    def test_atomic_persistence_modes_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'groups.json'
            save_groups({'devs': ['finn']}, 0, path)
            self.assertEqual(load_groups(path), {'devs': ['finn']})
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            save_groups({'devs': []}, 0, path)
            self.assertEqual(load_groups(path), {'devs': []})
            path.chmod(0o666)
            with self.assertRaises(ValueError):
                load_groups(path)
            path.unlink()
            path.symlink_to(Path(directory) / 'missing')
            with self.assertRaises(OSError):
                load_groups(path)


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = FreqDiscordClient(ConnectorConfig(11, 22, 33, {}))
        self.client._deliver_agent = AsyncMock()
        self.groups = {'pve-freq': ['finn', 'jarvis', 'clancy']}
        self.roster = ('finn', 'jarvis', 'clancy')
        self.patches = [patch('freq_discord_bot.load_groups', side_effect=lambda _: copy.deepcopy(self.groups)),
                        patch('freq_discord_bot.discover_roster', side_effect=lambda _: self.roster)]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.client.close()

    def message(self, content='pve-freq review this', attachments=()):
        return types.SimpleNamespace(id=123, content=content, attachments=attachments,
                                     author=types.SimpleNamespace(id=11, bot=False),
                                     guild=types.SimpleNamespace(id=22), channel=types.SimpleNamespace(id=33),
                                     add_reaction=AsyncMock(), reply=AsyncMock())

    async def test_group_routes_once_to_every_member_with_context(self):
        await self.client._deliver_inbound(self.message())
        calls = self.client._deliver_agent.await_args_list
        self.assertEqual([c.args[0] for c in calls], list(self.roster))
        for call in calls:
            self.assertEqual(call.args[1], '[Operator group message: pve-freq; addressed to: finn, jarvis, clancy]\n\nreview this')

    async def test_individual_body_unchanged(self):
        await self.client._deliver_inbound(self.message('finn hello'))
        self.client._deliver_agent.assert_awaited_once_with('finn', 'hello')

    async def test_partial_failure_continues_without_retry(self):
        self.client._deliver_agent.side_effect = [None, ConnectorError('ENTER FAILED', 'uncertain'), None]
        message = self.message()
        await self.client.on_message(message)
        self.assertEqual(self.client._deliver_agent.await_count, 3)
        description = message.reply.call_args.kwargs['embed'].description
        self.assertIn('Delivered to session: finn, clancy', description)
        self.assertIn('Failed or uncertain: jarvis', description)
        self.assertNotIn('✅', [c.args[0] for c in message.add_reaction.call_args_list])

    async def test_missing_member_does_not_block_remaining_members(self):
        self.roster = ('finn', 'clancy')
        with self.assertRaisesRegex(ConnectorError, 'Failed or uncertain: jarvis'):
            await self.client._deliver_inbound(self.message())
        self.assertEqual([c.args[0] for c in self.client._deliver_agent.await_args_list], ['finn', 'clancy'])

    async def test_empty_group_and_collision_rejected(self):
        self.groups = {'pve-freq': []}
        with self.assertRaisesRegex(ConnectorError, 'no members'):
            await self.client._deliver_inbound(self.message())
        self.groups = {'finn': ['jarvis']}
        with self.assertRaisesRegex(ConnectorError, 'both an agent and a group'):
            await self.client._deliver_inbound(self.message('finn hello'))
        self.client._deliver_agent.assert_not_awaited()

    async def test_unknown_target(self):
        with self.assertRaises(ConnectorError):
            await self.client._deliver_inbound(self.message('missing hello'))
        self.client._deliver_agent.assert_not_awaited()

    async def test_unauthorized_user_channel_and_bot_are_ignored(self):
        for field, value in [('author', types.SimpleNamespace(id=44, bot=False)),
                             ('channel', types.SimpleNamespace(id=44)),
                             ('author', types.SimpleNamespace(id=11, bot=True))]:
            message = self.message()
            setattr(message, field, value)
            await self.client.on_message(message)
            message.reply.assert_not_awaited()
        self.client._deliver_agent.assert_not_awaited()

    async def test_membership_refresh_and_per_message_snapshot(self):
        async def mutate(*_):
            self.groups['pve-freq'] = ['finn']
        self.client._deliver_agent.side_effect = mutate
        await self.client._deliver_inbound(self.message())
        self.assertEqual(self.client._deliver_agent.await_count, 3)
        self.client._deliver_agent.reset_mock()
        await self.client._deliver_inbound(self.message())
        self.client._deliver_agent.assert_awaited_once()

    async def test_attachment_download_once_and_paths_per_recipient(self):
        attachment = types.SimpleNamespace(size=10, content_type='image/png', read=AsyncMock(return_value=b'\x89PNG\r\n\x1a\nimage'))
        def stage(root, recipient, message_id, data, filenames):
            self.assertEqual(data, [b'\x89PNG\r\n\x1a\nimage'])
            return Path('/media'), (Path('/media') / recipient / '01.png',)
        with patch('freq_discord_bot.stage_attachments', side_effect=stage) as staging:
            await self.client._deliver_inbound(self.message(attachments=[attachment]))
        attachment.read.assert_awaited_once()
        self.assertEqual(staging.call_count, 3)
        for call in self.client._deliver_agent.await_args_list:
            self.assertIn(str(Path('/media') / call.args[0] / '01.png'), call.args[1])

    async def test_attachment_failure_continues_to_other_members(self):
        attachment = types.SimpleNamespace(size=10, content_type='image/png', read=AsyncMock(return_value=b'\x89PNG\r\n\x1a\nimage'))
        with patch('freq_discord_bot.stage_attachments', side_effect=[ConnectorError('images', 'failed'), (Path('/media'), ()), (Path('/media'), ())]):
            with self.assertRaisesRegex(ConnectorError, 'Failed or uncertain: finn'):
                await self.client._deliver_inbound(self.message(attachments=[attachment]))
        self.assertEqual([c.args[0] for c in self.client._deliver_agent.await_args_list], ['jarvis', 'clancy'])


if __name__ == '__main__':
    unittest.main()
