import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'assets/setup-discord'
loader = importlib.machinery.SourceFileLoader('discord_setup', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
setup = importlib.util.module_from_spec(spec)
loader.exec_module(setup)


class UpdateDiscordTests(unittest.TestCase):
    def exercise(self, answers, token='', prepare_only=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config'
            config.mkdir()
            (root / 'discord-venv/bin').mkdir(parents=True)
            (root / 'discord-venv/bin/python').touch()
            old = {'user_id': 111111111111111, 'guild_id': 222222222222222,
                   'channel_id': 333333333333333}
            (config / 'config.json').write_text(json.dumps(old))
            (config / 'bot-token').write_text('fixture-old-token-not-a-real-credential')
            coms = root / 'coms.conf'
            coms.write_text("FREQ_COMS_ROOT='/custom/coms'\nFREQ_COMS_BIN_DIR='/custom/bin'\n")
            writes = []
            output = io.StringIO()
            with patch.object(setup, 'ROOT', root), patch.object(setup, 'CONFIG', config), \
                 patch.object(setup, 'COMS_CONFIG', coms), \
                 patch.object(setup.os, 'geteuid', return_value=0), \
                 patch.object(setup.grp, 'getgrnam') as group, \
                 patch.object(setup.sys, 'argv', ['setup-discord', '--prepare-only' if prepare_only else '--configure-only']), \
                 patch.object(setup, 'prepare', return_value={}) as prepare, \
                 patch.object(setup, 'run') as run, \
                 patch.object(setup, 'atomic', side_effect=lambda *args: writes.append(args)), \
                 patch('builtins.input', side_effect=answers), \
                 patch.object(setup.getpass, 'getpass', return_value=token), \
                 contextlib.redirect_stdout(output):
                group.return_value.gr_gid = 123
                setup.main()
                if prepare_only:
                    prepare.assert_called_once()
                else:
                    prepare.assert_not_called()
                return writes, run.call_args_list, output.getvalue()

    def test_cancel_has_no_writes_or_service_changes(self):
        writes, calls, _ = self.exercise(['', '', '', 'n'])
        self.assertEqual(writes, [])
        self.assertEqual(calls, [])

    def test_enter_preserves_ids_token_and_custom_paths(self):
        writes, calls, output = self.exercise(['', '', '', 'y'])
        self.assertEqual(len(writes), 1)
        config = json.loads(writes[0][1])
        self.assertEqual(config['user_id'], 111111111111111)
        self.assertEqual(config['coms_root'], '/custom/coms')
        self.assertEqual(config['dev_msg'], '/custom/bin/dev-msg')
        self.assertEqual(writes[0][2:], (0o640, 123))
        self.assertIn(('systemctl', 'restart', 'freq-discord.service'), [c.args for c in calls])
        self.assertNotIn('fixture-old-token', output)

    def test_replace_ids_and_hidden_token(self):
        token = 'fixture-new-token-not-a-real-credential'
        writes, calls, output = self.exercise(['444444444444444', '555555555555555', '666666666666666', 'y'], token)
        self.assertEqual(json.loads(writes[0][1])['channel_id'], 666666666666666)
        self.assertEqual(writes[1][1:], (token + '\n', 0o600))
        self.assertNotIn(token, output)
        self.assertFalse(any(token in str(c) for c in calls))

    def test_invalid_token_never_applies(self):
        with self.assertRaisesRegex(RuntimeError, 'Token format invalid'):
            self.exercise(['', '', ''], 'short')

    def test_prepare_only_retains_install_path_without_prompts(self):
        writes, calls, _ = self.exercise([], prepare_only=True)
        self.assertEqual(writes, [])
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
