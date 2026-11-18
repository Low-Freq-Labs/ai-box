#!/bin/bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { printf 'accept-ai-packages must run as root\n' >&2; exit 2; }
readonly site_config=/etc/freq-ai-setup/site.conf
[[ -f $site_config && ! -L $site_config \
   && $(stat -Lc '%U:%G:%a' "$site_config" 2>/dev/null) == root:root:644 ]] || {
    printf 'safe FREQ-AI-SETUP site config is unavailable\n' >&2; exit 2;
}
source "$site_config"
readonly master_user=${FREQ_MASTER_USER:?missing FREQ_MASTER_USER}
readonly master_group=${FREQ_MASTER_GROUP:?missing FREQ_MASTER_GROUP}
readonly master_home=${FREQ_MASTER_HOME:?missing FREQ_MASTER_HOME}
readonly node_root="$(readlink -f /opt/freq-agents/toolchain/node-current)"
readonly codex_package="$node_root/lib/node_modules/@openai/codex"
readonly claude_package="$node_root/lib/node_modules/@anthropic-ai/claude-code"

fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS %s\n' "$*"; }

[[ $node_root =~ ^/opt/freq-agents/toolchain/node-v24\.[0-9]+\.[0-9]+-linux-x64$ ]] || fail 'shared Node generation'
[[ $(node --version) == v24.* ]] && dpkg --compare-versions "$(node --version | cut -c2-)" ge 24.19.0 || fail 'Node version'
[[ $(npm --version) == 11.* ]] && dpkg --compare-versions "$(npm --version)" ge 11.17.0 || fail 'npm version'
[[ $(npm config get prefix) == /opt/freq-agents/npm-global ]] || fail 'shared npm prefix'
[[ $(stat -c '%U:%G:%a' "$node_root") == root:root:755 ]] || fail 'Node generation ownership'
[[ $(stat -c '%U:%G:%a' /opt/freq-agents/npm-global) == root:root:755 ]] || fail 'shared npm ownership'
[[ $(stat -c '%U:%G:%a' /usr/local/bin/codex) == root:root:755 ]] || fail 'Codex wrapper ownership'
[[ $(stat -c '%U:%G:%a' /usr/local/bin/claude) == root:root:755 ]] || fail 'Claude wrapper ownership'
[[ $(basename -- "$(readlink -f "$node_root/bin/claude")") == claude.exe ]] || fail 'Claude native binary link'
command -v bwrap >/dev/null || fail 'bubblewrap PATH'
dpkg-query -W -f='${Status}' bubblewrap | grep -Fqx 'install ok installed' || fail 'bubblewrap package state'
pass 'root-owned shared Node, npm, Codex, Claude, and bubblewrap'

for command in node npm npx codex claude; do
    runuser -u "$master_user" -- env FREQ_NO_BANNER=1 bash -lc \
        "source /etc/profile.d/20-freq-ai-setup.sh; source /etc/profile.d/30-freq-ai-setup-shared-tools.sh; command -v $command >/dev/null" \
        || fail "master PATH: $command"
done
[[ $(runuser -u "$master_user" -- npm config get prefix) == /opt/freq-agents/npm-global ]] \
    || fail 'master shared npm prefix'
[[ ! -e $master_home/.npm-global ]] || fail 'competing master npm prefix'
[[ ! -e $master_home/.local/bin/codex ]] || fail 'competing master Codex install'
[[ ! -e $master_home/.local/bin/claude ]] || fail 'competing master Claude install'
pass 'master sees one shared toolchain with no competing install'

runuser -u "$master_user" -- bwrap --ro-bind / / --proc /proc --dev /dev /usr/bin/true \
    || fail 'unprivileged bubblewrap execution'
pass 'bubblewrap works unprivileged'

codex_before="$(stat -c '%Y:%s' "$codex_package")"
codex_first="$(runuser -u "$master_user" -- /usr/local/bin/codex update)"
codex_second="$(runuser -u "$master_user" -- /usr/local/bin/codex update)"
codex_after="$(stat -c '%Y:%s' "$codex_package")"
[[ $codex_before == "$codex_after" ]] || fail 'current Codex was reinstalled'
printf '%s\n' "$codex_first" | grep -Eq '^Current version: [0-9]' || fail 'Codex current-version output'
printf '%s\n' "$codex_first" | grep -Eq '^Codex is up to date \([^)]+\)$' || fail 'Codex up-to-date output'
[[ $codex_first == "$codex_second" ]] || fail 'Codex repeated update output'
pass 'Codex update is native-looking and idempotent'

claude_before="$(stat -c '%Y:%s' "$claude_package")"
claude_first="$(runuser -u "$master_user" -- /usr/local/bin/claude update)"
claude_second="$(runuser -u "$master_user" -- /usr/local/bin/claude update)"
claude_after="$(stat -c '%Y:%s' "$claude_package")"
[[ $claude_before == "$claude_after" ]] || fail 'current Claude was reinstalled'
printf '%s\n' "$claude_first" | grep -Eq '^Current version: [0-9]' || fail 'Claude current-version output'
printf '%s\n' "$claude_first" | grep -Eq '^Claude Code is up to date \([^)]+\)$' || fail 'Claude up-to-date output'
[[ $claude_first == "$claude_second" ]] || fail 'Claude repeated update output'
pass 'Claude update is native-looking and idempotent'

grep -Fq -- '--dangerously-bypass-approvals-and-sandbox' /usr/local/bin/codex \
    || fail 'Codex YOLO launcher policy'
grep -Fq -- '--dangerously-skip-permissions' /usr/local/bin/claude \
    || fail 'Claude bypass launcher policy'
grep -Fq 'agent-trust-current' /usr/local/bin/codex || fail 'Codex folder trust policy'
grep -Fq 'agent-trust-current' /usr/local/bin/claude || fail 'Claude folder trust policy'
pass 'runtime permission and folder-trust launch policy'

readonly internal_installer=/usr/local/libexec/freq-ai-setup/ai-packages-install
[[ -f $internal_installer && ! -L $internal_installer && -x $internal_installer \
   && $(stat -c '%U:%G:%a' "$internal_installer") == root:root:755 ]] \
    || fail 'internal installer metadata'
[[ ! -e $master_home/tools/ai-packages-install && ! -L $master_home/tools/ai-packages-install ]] \
    || fail 'retired public installer entrypoint remains'
[[ $(stat -c '%U:%G:%a' "$master_home/cmd-list") == "$master_user:$master_group:644" ]] \
    || fail 'cmd-list metadata'
pass 'internal installer, pruned public menu, and cmd-list'

printf '%s\n' "$codex_first"
printf '%s\n' "$claude_first"
printf 'AI_PACKAGES_ACCEPTANCE_PASS node=%s npm=%s codex=%s claude=%s\n' \
    "$(node --version)" "$(npm --version)" "$(codex --version)" "$(claude --version)"
