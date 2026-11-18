#!/bin/bash
# Release-maintainer operation, run in a disposable Debian 13 environment.
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")" && pwd)
packages="$base/assets/packages"
work=$(mktemp -d /var/tmp/freq-locks.XXXXXX)
trap 'find "$work" -xdev -depth -delete' EXIT
python3 - "$base" "$work" <<'PY'
import importlib.machinery, json, sys
from pathlib import Path
base,work=map(Path,sys.argv[1:])
module=importlib.machinery.SourceFileLoader('devtools_install',str(base/'assets/devtools-install')).load_module()
tool=json.loads((base/'assets/packages/binaries.json').read_text())['tools'][0]
assert tool['name']=='uv'
module.fetch(tool,work/'uv.tar.gz')
module.extract_commands(tool,work/'uv.tar.gz',work)
PY
for tool in semgrep fonttools; do
    UV_CACHE_DIR="$work/cache" "$work/uv" pip compile --python /usr/bin/python3 \
        --only-binary :all: --generate-hashes --no-header \
        "$packages/python/$tool.in" --output-file "$packages/python/$tool.txt"
done
cd "$packages/webqa"
npm install --package-lock-only --ignore-scripts --no-fund --no-audit
printf 'Release locks resolved; review before distribution.\n'
