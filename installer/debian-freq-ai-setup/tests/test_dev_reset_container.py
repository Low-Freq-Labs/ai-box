"""Exercise the actual developer-only level-set block in the disposable container."""
from pathlib import Path
import subprocess

assert Path('/run/.containerenv').is_file(), 'container required'
source = Path('/work/debian-freq-ai-setup/assets/level-set').read_text()
functions = source[source.index('safe_remove_tree() {'):source.index('if getent passwd freq-discord')]
block = source[source.index('for command in uv uvx'):source.index('safe_remove_tree "$opt_root/toolchain"')]
root = Path('/opt/freq-agents/devtools')
assert (root / 'current').is_symlink(), 'installed test release required'
unrelated = Path('/usr/local/bin/freq-test-unrelated')
assert not unrelated.exists()
unrelated.write_text('preserve\n')
subprocess.run(['bash', '-s'], input='set -euo pipefail\nopt_root=/opt/freq-agents\nfail() { echo "$*" >&2; exit 2; }\n' + functions + block,
               text=True, check=True)
assert not root.exists()
for name in ('uv', 'semgrep', 'playwright', 'lighthouse', 'fd', 'bat'):
    path = Path('/usr/local/bin') / name
    assert not path.exists() and not path.is_symlink(), name
assert unrelated.read_text() == 'preserve\n'
assert Path('/usr/local/share/freq-ai-setup/devtools/packages/binaries.json').is_file()
unrelated.unlink()
print('PASS actual developer level-set block: releases/links removed; sources/unrelated file preserved')
