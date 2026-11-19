"""Offline defaults and nested launch quoting; no agent/model invocation."""
from pathlib import Path
import re
import shlex
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ModelDefaultsTests(unittest.TestCase):
    def test_creation_config(self):
        source = (ROOT / 'assets/create-agent').read_text(encoding='utf-8')
        config = source.split('cat >"$home/.codex/config.toml" <<\'EOF\'\n', 1)[1].split('\nEOF', 1)[0]
        parsed = tomllib.loads(config)
        self.assertEqual(parsed['model'], 'gpt-6.1-sol')
        self.assertEqual(parsed['model_reasoning_effort'], 'high')
        self.assertIs(parsed['check_for_update_on_startup'], False)
        self.assertIs(parsed['notice']['hide_rate_limit_model_nudge'], True)

    def test_two_shell_layers_preserve_toml_string(self):
        source = (ROOT / 'assets/agent-lifecycle.template').read_text(encoding='utf-8')
        command = re.search(r"runtime_command='([^']+)'", source)[1]
        outer = shlex.split("tmux new-session /bin/bash -lc 'exec " + command + "'")
        actual = shlex.split(outer[-1])
        self.assertEqual(actual[:5], ['exec', 'codex', '--no-daemon', '--model', 'gpt-6.1-sol'])
        overrides = [actual[i+1] for i, value in enumerate(actual) if value == '-c']
        parsed = tomllib.loads('\n'.join(overrides))
        self.assertEqual(parsed['model_reasoning_effort'], 'high')
        self.assertIs(parsed['check_for_update_on_startup'], False)
        self.assertIs(parsed['notice']['hide_rate_limit_model_nudge'], True)
        self.assertIn('if [[ $runtime == codex ]]; then', source)


if __name__ == '__main__':
    unittest.main()
