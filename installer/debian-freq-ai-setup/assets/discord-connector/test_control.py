import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock
import agent_control as control
from connector import Connector


class ControlTests(unittest.TestCase):
    def test_rejects_arbitrary_actions_fields_and_agents(self):
        for request in ({'action': 'exec'}, {'action': 'list', 'command': 'id'}):
            with self.assertRaises(ValueError):
                control.handle(request)
        with patch.object(control, 'agents', return_value=['test']), patch.object(control, 'settings', return_value={'FREQ_COMS_TMUX_DIR': '/tmp'}):
            with self.assertRaises(ValueError):
                control.handle({'action': 'start', 'agent': 'test;id'})

    def test_stale_selection_refuses_before_launch(self):
        with patch.object(control, 'agents', return_value=['test']), patch.object(control, 'settings', return_value={'FREQ_COMS_TMUX_DIR': '/tmp'}), patch.object(control, 'status', return_value='running'), patch.object(control, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'refresh'):
                control.handle({'action': 'start', 'agent': 'test'})
            run.assert_not_called()

    def test_listing_has_actual_status(self):
        with patch.object(control, 'agents', return_value=['one', 'two']), patch.object(control, 'settings', return_value={'FREQ_COMS_TMUX_DIR': '/tmp'}), patch.object(control, 'status', side_effect=['running', 'stopped']):
            self.assertEqual(control.handle({'action': 'list'})['agents'], {'one': 'running', 'two': 'stopped'})


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = Connector(dict(user_id=1, guild_id=2, channel_id=3, coms_root=self.temp.name, outbox=self.temp.name), 'test', Path(self.temp.name))
        self.event = SimpleNamespace(user=SimpleNamespace(id=1, bot=False), guild_id=2, channel_id=3,
                                     response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                                     followup=SimpleNamespace(send=AsyncMock()))

    async def asyncTearDown(self):
        await self.client.close()
        self.client.db.close()
        self.temp.cleanup()

    async def test_autocomplete_filters_running_and_stopped(self):
        self.client.control = AsyncMock(return_value={'ok': True, 'agents': {'chris': 'running', 'donny': 'stopped', 'broken': 'unknown'}})
        self.assertEqual([c.value for c in await self.client.choices(self.event, '', 'stopped')], ['donny'])
        self.assertEqual([c.value for c in await self.client.choices(self.event, '', 'running')], ['chris'])
        self.assertEqual(await self.client.choices(self.event, 'no-match', 'running'), [])
        self.event.user.id = 99
        self.assertEqual(await self.client.choices(self.event, '', 'running'), [])

    async def test_commands_are_exact_and_operator_restricted(self):
        _, commands = self.client.define_commands()
        self.assertEqual([command.name for command in commands], ['agents', 'start', 'stop'])
        self.client.control = AsyncMock(return_value={'ok': True, 'message': 'Started donny.'})
        for change in ('user', 'guild_id', 'channel_id'):
            previous = getattr(self.event, change)
            setattr(self.event, change, SimpleNamespace(id=99, bot=False) if change == 'user' else 99)
            await self.client.management(self.event, 'start', 'donny')
            setattr(self.event, change, previous)
        self.client.control.assert_not_awaited()
        await self.client.management(self.event, 'start', 'donny')
        self.client.control.assert_awaited_once_with('start', 'donny')

    async def test_agents_response_is_private(self):
        self.client.control = AsyncMock(return_value={'ok': True, 'agents': {'one': 'running', 'two': 'stopped'}})
        await self.client.management(self.event, 'list')
        response = self.event.followup.send.call_args.kwargs
        self.assertTrue(response['ephemeral'])
        self.assertIn('running', response['embed'].description)
        self.assertIn('stopped', response['embed'].description)
        self.assertIn('✅ **one** — running', response['embed'].description)
        self.assertIn('🚫 **two** — stopped', response['embed'].description)
