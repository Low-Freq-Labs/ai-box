#!/bin/bash
set -euo pipefail

failures=0
pass() { printf 'PASS %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*" >&2; failures=$((failures + 1)); }
expect() { local label=$1; shift; if "$@"; then pass "$label"; else fail "$label"; fi; }
expect_fail() { local label=$1; shift; if "$@"; then fail "$label"; else pass "$label"; fi; }
[[ $EUID -eq 0 ]] || { printf 'accept-base must run as root\n' >&2; exit 2; }

readonly coms_config=/etc/freq-ai-setup/coms.conf
readonly board_config=/etc/freq-ai-setup/board.conf
readonly site_config=/etc/freq-ai-setup/site.conf
[[ -f $site_config && ! -L $site_config \
   && $(stat -Lc '%U:%G:%a' "$site_config" 2>/dev/null) == root:root:644 ]] || {
    printf 'safe FREQ-AI-SETUP site config is unavailable\n' >&2; exit 2;
}
source "$site_config"
readonly master_user=${FREQ_MASTER_USER:?missing FREQ_MASTER_USER}
readonly master_group=${FREQ_MASTER_GROUP:?missing FREQ_MASTER_GROUP}
readonly master_home=${FREQ_MASTER_HOME:?missing FREQ_MASTER_HOME}
readonly site_host=${FREQ_HOST:?missing FREQ_HOST}
readonly master_tools="$master_home/tools"
if [[ -r $coms_config ]]; then
    source "$coms_config"
fi
readonly tmux_dir=${FREQ_COMS_TMUX_DIR:-/run/freq-agents/tmux}
readonly coms_root=${FREQ_COMS_ROOT:-/var/lib/freq-agents/coms}
readonly coms_bin=${FREQ_COMS_BIN_DIR:-/usr/local/bin}
if [[ -r $board_config ]]; then
    source "$board_config"
fi
readonly board_root=${FREQ_BOARD_ROOT:-/var/lib/freq-agents/board}
readonly board_bin=${FREQ_BOARD_BIN_DIR:-/usr/local/bin}

expect_fail 'retired freq-ops account absent' getent passwd freq-ops
expect_fail 'retired freq-ops group absent' getent group freq-ops
expect 'freq-agents group exists' getent group freq-agents
expect 'no agents created' bash -c "! find /etc/freq-ai-setup/agents.d -mindepth 1 -maxdepth 1 -type f -name '*.conf' -print -quit | grep -q ."
expect_fail 'master excluded from agent security group' bash -c "id -nG '$master_user' | tr ' ' '\n' | grep -qx freq-agents"
expect 'master shared projects ACL' runuser -u "$master_user" -- test -w /home/freq-agents/projects
expect 'master staging read ACL' runuser -u "$master_user" -- test -r /home/freq-agents/staging/README.md
expect 'master private home' test "$(stat -c '%U:%G:%a' "$master_home")" = "$master_user:$master_group:700"
expect 'shared projects metadata' test "$(stat -c '%U:%G:%a' /home/freq-agents/projects)" = 'root:freq-agents:2770'
expect 'shared session data metadata' test "$(stat -c '%U:%G:%a' /home/freq-agents/session-data)" = 'root:freq-agents:2770'
expect 'master session data access' runuser -u "$master_user" -- test -w /home/freq-agents/session-data
expect 'shared projects default ACL' bash -c "getfacl -cp /home/freq-agents/projects | grep -qx 'default:group::rwx'"
expect 'wrap-up state helper metadata' test "$(stat -c '%U:%G:%a' /usr/local/bin/wrap-up-state)" = root:root:755
expect 'wrap-up skill installed' test -r /opt/freq-agents/skills/wrap-up/SKILL.md
expect 'wrap-up skill metadata installed' test -r /opt/freq-agents/skills/wrap-up/agents/openai.yaml
expect 'wrap-up helper syntax' python3 -c "import ast; ast.parse(open('/usr/local/bin/wrap-up-state').read())"
expect 'staging root metadata' test "$(stat -c '%U:%G:%a' /home/freq-agents/staging)" = 'root:freq-agents:2750'
for tool in create-agent delete-agent level-set full-update update-shared-git update-discord update-ssh-key; do
    expect "$tool executable" test \
        "$(stat -c '%U:%G:%a' "$master_tools/$tool")" = "$master_user:$master_group:755"
done
expect 'operator-only agent updater' test "$(stat -c '%U:%G:%a' "$master_tools/update-agent")" = "$master_user:$master_group:700"
expect 'operator-only groups command' test "$(stat -c '%U:%G:%a' "$master_tools/agent-groups")" = "$master_user:$master_group:700"
expect 'root-only groups helper' test "$(stat -c '%U:%G:%a' /usr/local/libexec/freq-ai-setup/manage-agent-groups)" = root:root:700
for tool in shared-git configure-shared-git; do
    expect "$tool internal helper" test "$(stat -c '%U:%G:%a' "/usr/local/libexec/freq-ai-setup/$tool")" = root:root:755
done
for tool in git gh; do
    expect "$tool shared adapter" test "$(stat -c '%U:%G:%a' "/usr/local/bin/$tool")" = root:root:755
done
for tool in setup-coms setup-board ai-packages-install setup-discord retire-agent-data update-managed-tools container-worker container-client container-accept setup-container-tools; do
    expect "$tool internal helper" test "$(stat -c '%U:%G:%a' "/usr/local/libexec/freq-ai-setup/$tool")" = root:root:755
done
expect 'master command list' test "$(stat -c '%U:%G:%a' "$master_home/cmd-list")" = "$master_user:$master_group:644"
expect 'coms config metadata' test "$(stat -c '%U:%G:%a' "$coms_config")" = 'root:root:644'
expect 'board config metadata' test "$(stat -c '%U:%G:%a' "$board_config")" = 'root:root:644'
expect 'agent launchers directory' test "$(stat -c '%U:%G:%a' "$master_home/agents")" = "$master_user:$master_group:755"
expect 'agent lifecycle commands stay inside agent directories' bash -c \
    "grep -Fq '\$agent_tools/\${agent}-\${action}' '$master_tools/create-agent' && ! grep -Fq 'ln -s' '$master_tools/create-agent'"
expect 'agent lifecycle template' test "$(stat -c '%U:%G:%a' /usr/local/share/freq-ai-setup/agent-lifecycle.template)" = 'root:root:644'
expect 'startup notification helper' test "$(stat -c '%U:%G:%a' /usr/local/libexec/freq-ai-setup/agent-startup-notify)" = root:root:755
expect 'startup message' test "$(stat -c '%U:%G:%a' /usr/local/share/freq-ai-setup/agent-startup-message.md)" = root:root:644
expect 'startup helper syntax' python3 -c "import ast; ast.parse(open('/usr/local/libexec/freq-ai-setup/agent-startup-notify').read())"
expect 'shared tmux socket directory' test "$(stat -c '%U:%G:%a' "$tmux_dir")" = 'root:freq-agents:2770'
expect 'shared socket path contract' grep -Fq '/run/freq-agents/tmux' /usr/local/share/freq-ai-setup/agent-lifecycle.template
expect 'designated delivery pane contract' grep -Fq '@freq_delivery_pane' /usr/local/share/freq-ai-setup/agent-lifecycle.template
expect 'tmux internal write ACL contract' bash -c \
    "grep -Fq 'server-access -a' /usr/local/share/freq-ai-setup/agent-lifecycle.template && grep -Fq 'server-access -w' /usr/local/share/freq-ai-setup/agent-lifecycle.template && grep -Fq 'server-access -l' /usr/local/share/freq-ai-setup/agent-lifecycle.template"
expect 'locked shared inbox hierarchy' bash -c \
    "for path in /var/lib/freq-agents '$coms_root'; do [[ \$(stat -c '%U:%G:%a' \"\$path\") == root:freq-agents:750 ]] || exit 1; done"
expect 'locked shared board root' test \
    "$(stat -c '%U:%G:%a' "$board_root")" = 'root:freq-agents:750'
expect 'shared board projects root' test \
    "$(stat -c '%U:%G:%a' "$board_root/projects")" = 'root:freq-agents:2770'
expect 'per-agent inbox and read contract' bash -c \
    "grep -Fq '\$agent_coms/inbox' '$master_tools/create-agent' && grep -Fq '\$agent_coms/read' '$master_tools/create-agent'"
for skill in dev-msg dev-msg-status dev-inbox dev-read dev-drain agent-team; do
    expect "coms skill source $skill" test \
        "$(stat -c '%U:%G:%a' "/opt/freq-agents/skills/$skill/SKILL.md")" = 'root:root:644'
    expect "coms skill metadata $skill" test \
        "$(stat -c '%U:%G:%a' "/opt/freq-agents/skills/$skill/agents/openai.yaml")" = 'root:root:644'
done
expect 'agent identity document contract' bash -c \
    "grep -Fq 'Refer to yourself in first person' '$master_tools/create-agent' && grep -Fq 'Allow one recovery inbox check' '$master_tools/create-agent' && grep -Fq 'task ownership changes must use board tools' '$master_tools/create-agent' && grep -Fq 'confirms storage and notification submission' '$master_tools/create-agent'"
expect 'durable project location contract' bash -c \
    "grep -Fq 'not durable project work' '$master_tools/create-agent' && grep -Fq '/home/freq-agents/projects/<project-id-lowercased>/' '$master_tools/create-agent' && grep -Fq 'move accepted work into the project tree' '$master_tools/create-agent'"
expect 'single runtime-specific contract' bash -c \
    "grep -Fq 'contract_path=\"\$home/.codex/AGENTS.md\"' '$master_tools/create-agent' && grep -Fq 'contract_path=\"\$home/.claude/CLAUDE.md\"' '$master_tools/create-agent' && ! grep -Fq 'identity=/home/%s/{AGENTS.md,CLAUDE.md}' '$master_tools/create-agent'"
expect 'board owns task assignment' bash -c \
    "grep -Fq '\`ready\` means actionable' /opt/freq-agents/board-behavior/AGENTS.board.md && grep -Fq 'Register known dependencies as blocked; missing review artifacts are not ready.' /opt/freq-agents/board-behavior/CLAUDE.board.md && grep -Fq 'every authored requirement is met' /opt/freq-agents/board-behavior/AGENTS.board.md"
expect 'setup-coms refreshes existing agent skills' bash -c \
    "grep -Fq 'runtime_root=\"\$home/.\$runtime/skills\"' /usr/local/libexec/freq-ai-setup/setup-coms && grep -Fq '\$runtime_root/\$skill/SKILL.md' /usr/local/libexec/freq-ai-setup/setup-coms"
expect 'Codex skill install contract' grep -Fq 'runtime_root="$home/.codex/skills"' "$master_tools/create-agent"
expect 'Claude skill install contract' grep -Fq 'runtime_root="$home/.claude/skills"' "$master_tools/create-agent"
expect 'Codex dynamic status line contract' grep -Fq \
    'status_line = ["model-with-reasoning", "context-used", "weekly-limit"]' \
    "$master_tools/create-agent"
expect 'Codex rate-limit nudge disabled' bash -c \
    "grep -Fq '[notice]' '$master_tools/create-agent' && grep -Fq 'hide_rate_limit_model_nudge = true' '$master_tools/create-agent'"
expect 'Claude dynamic status line template' test \
    "$(stat -c '%U:%G:%a' /usr/local/share/freq-ai-setup/claude-statusline)" = 'root:root:755'
expect 'Claude five-hour status line contract' bash -c \
    "grep -Fq 'rate_limits.five_hour.used_percentage' /usr/local/share/freq-ai-setup/claude-statusline && ! grep -Fq 'seven_day' /usr/local/share/freq-ai-setup/claude-statusline"
for command in dev-msg dev-msg-status dev-read dev-inbox dev-drain agent-team; do
    expect "coms command $command" test \
        "$(stat -c '%U:%G:%a' "$coms_bin/$command")" = 'root:root:755'
    expect "coms command syntax $command" bash -n "$coms_bin/$command"
done
for command in \
    project-archive project-assign project-list project-register \
    project-status task-block task-done task-ready \
    task-register task-status task-transfer task-dependencies project-assess task-update agent-skills; do
    expect "board command $command" test \
        "$(stat -c '%U:%G:%a' "$board_bin/$command")" = 'root:root:755'
done
expect 'blocked-at-registration contract' grep -Fq \
    'task-register <project-id> <exact-title> <full-description> [blocked-reason]' \
    /opt/freq-agents/skills/task-register/SKILL.md
expect 'durable assignment-note contract' grep -Fq \
    'task-ready <project-id> <exact-task-name> <agent> [assignment-note]' \
    /opt/freq-agents/skills/task-ready/SKILL.md
expect 'durable handoff contract' grep -Fq \
    'stored both in the recipient' \
    /opt/freq-agents/skills/task-transfer/SKILL.md
expect 'completion-note contract' grep -Fq \
    'task-done <exact-task-name> <completion-note>' \
    /opt/freq-agents/skills/task-done/SKILL.md
expect 'board worker is not an agent command' test ! -e "$board_bin/board-alert-watch"
expect 'internal board alert worker' test \
    "$(stat -c '%U:%G:%a' /usr/local/libexec/freq-board-alert-watch)" = 'root:root:755'
for skill in \
    project-archive project-assign project-list project-register \
    project-status task-block task-done task-ready \
    task-register task-status task-transfer task-dependencies project-assess task-update agent-skills; do
    expect "board skill source $skill" test \
        "$(stat -c '%U:%G:%a' "/opt/freq-agents/skills/$skill/SKILL.md")" = 'root:root:644'
done
expect 'board task library' test \
    "$(stat -c '%U:%G:%a' /usr/local/lib/freq_board.py)" = 'root:root:644'
expect 'board alert library' test \
    "$(stat -c '%U:%G:%a' /usr/local/lib/freq_board_alert.py)" = 'root:root:644'
expect 'board alert service' test \
    "$(stat -c '%U:%G:%a' /etc/systemd/system/freq-board-alert@.service)" = 'root:root:644'
expect 'board alert service uses internal worker' grep -Fqx \
    'ExecStart=/usr/local/libexec/freq-board-alert-watch' \
    /etc/systemd/system/freq-board-alert@.service
expect 'board alert service preserves timing state' grep -Fqx \
    'RuntimeDirectoryPreserve=yes' \
    /etc/systemd/system/freq-board-alert@.service
expect 'board alert timer' test \
    "$(stat -c '%U:%G:%a' /etc/systemd/system/freq-board-alert@.timer)" = 'root:root:644'
expect 'master board read ACL' bash -c \
    "getfacl -cp '$board_root/projects' | grep -Fxq 'user:$master_user:r-x'"
expect 'master board default read ACL' bash -c \
    "getfacl -cp '$board_root/projects' | grep -Fxq 'default:user:$master_user:r-x'"
expect 'master project-list access' runuser -u "$master_user" -- "$board_bin/project-list"
expect 'sandbox setuid root' test "$(stat -c '%U:%G:%a' /usr/local/sbin/freq-agent-sandbox)" = 'root:root:4755'
expect 'sandbox board collaboration path' grep -Fq \
    '"/var/lib/freq-agents/coms", "/var/lib/freq-agents/board",' \
    /usr/local/src/freq-agent-sandbox.c
expect_fail 'sandbox denies non-agent master' runuser -u "$master_user" -- /usr/local/sbin/freq-agent-sandbox
expect 'create-agent has no network gate' bash -c \
    "! grep -Eq 'network.boundary|network_gate' '$master_tools/create-agent'"
expect 'create-agent dry-run' runuser -u "$master_user" -- "$master_tools/create-agent" --dry-run sample-agent codex blue
expect 'create-agent Claude dry-run' bash -c \
    "runuser -u '$master_user' -- '$master_tools/create-agent' --dry-run sample-claude claude orange | grep -Fq '/home/sample-claude/.claude/skills/'"
expect 'create-agent board dry-run' bash -c \
    "runuser -u '$master_user' -- '$master_tools/create-agent' --dry-run sample-agent codex blue | grep -Fq 'timer=freq-board-alert@sample-agent.timer'"
expect 'create-agent Claude five-hour dry-run' bash -c \
    "runuser -u '$master_user' -- '$master_tools/create-agent' --dry-run sample-claude claude orange | grep -Fq 'five-hour-limit'"
expect 'dry-run created no account' bash -c '! getent passwd sample-agent >/dev/null'
expect 'Claude dry-run created no account' bash -c '! getent passwd sample-claude >/dev/null'
expect 'MOTD empty' test ! -s /etc/motd
expect 'Mosh dynamic MOTD cache empty' test ! -s /run/motd.dynamic
expect 'uname MOTD disabled' test ! -x /etc/update-motd.d/10-uname
expect 'PAM MOTD disabled' bash -c "! grep -Eq '^[[:space:]]*session[[:space:]].*pam_motd\\.so' /etc/pam.d/sshd"
expect 'console PAM MOTD disabled' bash -c "! grep -Eq '^[[:space:]]*session[[:space:]].*pam_motd\\.so' /etc/pam.d/login"
expect 'sshd config valid' sshd -t
expect 'SSH active' systemctl is-active --quiet ssh
expect 'Mosh server installed' command -v mosh-server
expect 'Mosh configuration metadata' test \
    "$(stat -c '%U:%G:%a' /etc/freq-ai-setup/mosh.conf)" = 'root:root:644'
expect 'Mosh UDP range contract' grep -Fqx \
    'FREQ_MOSH_UDP_RANGE=60000:61000' /etc/freq-ai-setup/mosh.conf
expect 'prompt width and host' runuser -u "$master_user" -- env \
    FREQ_NO_BANNER=1 EXPECTED_MASTER="$master_user" EXPECTED_HOST="$site_host" \
    bash --noprofile --norc -ic \
    'source /etc/profile.d/20-freq-ai-setup.sh; test "$FREQ_WIDTH" = 59; test "$FREQ_HOST" = "$EXPECTED_HOST"; [[ $PS1 == *"$EXPECTED_MASTER"*"$EXPECTED_HOST"* ]]'
expect 'tmux config valid' runuser -u "$master_user" -- tmux -L freq-ai-setup-accept -f "$master_home/.tmux.conf" start-server
runuser -u "$master_user" -- tmux -L freq-ai-setup-accept kill-server 2>/dev/null || true
expect 'zero failed units' bash -c 'test "$(systemctl --failed --no-legend | wc -l)" -eq 0'
expect 'shared developer functional acceptance' runuser -u "$master_user" -- \
    /usr/local/share/freq-ai-setup/devtools/devtools-accept
expect 'container service template' systemd-analyze verify /etc/systemd/system/freq-container@.service /etc/systemd/system/freq-container@.socket
expect 'container worker private PID requirement' grep -Fq 'PrivatePIDs=yes' /etc/systemd/system/freq-container@.service
expect 'container worker has no host admin capability' grep -Fxq 'CapabilityBoundingSet=CAP_SETUID CAP_SETGID' /etc/systemd/system/freq-container@.service
expect 'private mapping helper directory' test "$(stat -c '%U:%G:%a' /usr/local/libexec/freq-ai-setup/container-uidmap)" = root:root:700
for helper in newuidmap newgidmap; do
    path=/usr/local/libexec/freq-ai-setup/container-uidmap/$helper
    expect "$helper matches Debian bytes" cmp -s "/usr/bin/$helper" "$path"
    expect "$helper is not setuid" test "$(stat -c '%U:%G:%a' "$path")" = root:root:755
done
expect 'UID mapping capability only' test "$(getcap /usr/local/libexec/freq-ai-setup/container-uidmap/newuidmap)" = '/usr/local/libexec/freq-ai-setup/container-uidmap/newuidmap cap_setuid=ep'
expect 'GID mapping capability only' test "$(getcap /usr/local/libexec/freq-ai-setup/container-uidmap/newgidmap)" = '/usr/local/libexec/freq-ai-setup/container-uidmap/newgidmap cap_setgid=ep'
expect 'agent creation tests actual container execution' grep -Fq '/usr/local/libexec/freq-ai-setup/container-accept' "$master_tools/create-agent"
for tool in podman buildah bwrap; do
    expect "container client $tool" test "$(readlink -f "/usr/local/bin/$tool")" = /usr/local/libexec/freq-ai-setup/container-client
done

for command in agent-crontab board-stop-hook; do
    expect "$command root-managed" test "$(stat -c '%U:%G:%a' "/usr/local/bin/$command")" = root:root:755
done
expect 'own scheduler help' /usr/local/bin/agent-crontab --help
expect 'native cron available' test -x /usr/bin/crontab
expect 'own scheduler module installed' test -r /usr/local/libexec/freq-ai-setup/host-admin/own_crontab.py
expect 'prerequisite documentation installed' test -r /usr/local/share/freq-ai-setup/stop-gate.md
for library in freq_stop_gate.py freq_board_update.py freq_board_pause.py freq_task_identity.py freq_project_migration.py; do
    expect "$library root-managed" test "$(stat -c '%U:%G:%a' "/usr/local/lib/$library")" = root:root:644
done
expect 'managed prerequisite hook policy' python3 -I -c '
from pathlib import Path
import tomllib
p=tomllib.loads(Path("/etc/codex/requirements.toml").read_text())
commands=[h.get("command") for group in p.get("hooks",{}).get("Stop",[]) for h in group.get("hooks",[])]
assert any(c in commands for c in ["/usr/local/bin/board-stop-hook", "/usr/local/libexec/freq-ai-setup/codex-hooks/board-stop-hook"])
'

if (( failures )); then printf 'FREQ_AI_SETUP_BASE_ACCEPTANCE_FAIL failures=%s\n' "$failures" >&2; exit 1; fi
printf 'FREQ_AI_SETUP_BASE_ACCEPTANCE_PASS agents_created=0\n'
