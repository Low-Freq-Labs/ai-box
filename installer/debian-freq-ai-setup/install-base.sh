#!/bin/bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { printf 'install-base must run as root\n' >&2; exit 2; }
readonly source_root="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
readonly assets="$source_root/debian-freq-ai-setup/assets"
readonly coms_assets=${FREQ_COMS_SOURCE:-$source_root/debian-freq-ai-setup/assets/coms-system}
readonly existing_assets="$source_root/debian-freq-ai-setup/assets"
readonly master=${FREQ_MASTER_USER:?set FREQ_MASTER_USER through bootstrap-freq-ai-setup}
readonly requested_master_home=${FREQ_MASTER_HOME:-/home/$master}
readonly operator_name=${FREQ_OPERATOR_NAME:-Operator}
readonly site_host=${FREQ_HOST:-$(hostname -s)}
readonly create_master=${FREQ_CREATE_MASTER:-0}
readonly advanced_paths=${FREQ_ADVANCED_PATHS:-0}
readonly mosh_firewall=${FREQ_MOSH_FIREWALL:-auto}
readonly tmux_dir_default="$(realpath -m -- "${FREQ_COMS_TMUX_DEFAULT:-/run/freq-agents/tmux}")"
readonly coms_root_default="$(realpath -m -- "${FREQ_COMS_ROOT_DEFAULT:-/var/lib/freq-agents/coms}")"
readonly board_root_default="$(realpath -m -- "${FREQ_BOARD_ROOT_DEFAULT:-/var/lib/freq-agents/board}")"
master_public_key=${FREQ_MASTER_PUBLIC_KEY:-}
readonly stamp="${FREQ_BACKUP_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
readonly backup="/var/backups/freq-ai-setup/$stamp"

[[ $stamp =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || { printf 'invalid backup identity\n' >&2; exit 2; }
[[ $master =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { printf 'invalid master username\n' >&2; exit 2; }
[[ $requested_master_home == /* && $requested_master_home != / \
   && $requested_master_home != *$'\n'* && $requested_master_home != *$'\r'* ]] || {
    printf 'invalid master home path\n' >&2; exit 2;
}
[[ $operator_name =~ ^[A-Za-z][A-Za-z0-9._\ -]{0,63}$ ]] || { printf 'invalid operator display name\n' >&2; exit 2; }
[[ $site_host =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]] || { printf 'invalid terminal host label\n' >&2; exit 2; }
[[ $create_master == 0 || $create_master == 1 ]] || { printf 'invalid FREQ_CREATE_MASTER value\n' >&2; exit 2; }
[[ $advanced_paths == 0 || $advanced_paths == 1 ]] || { printf 'invalid FREQ_ADVANCED_PATHS value\n' >&2; exit 2; }
case $mosh_firewall in auto|skip|required) ;; *) printf 'invalid FREQ_MOSH_FIREWALL value\n' >&2; exit 2 ;; esac
[[ $tmux_dir_default == /run/freq-agents/tmux \
   || $tmux_dir_default == /run/freq-agents/tmux/* ]] || {
    printf 'invalid shared tmux path\n' >&2; exit 2;
}
[[ $coms_root_default == /var/lib/freq-agents/coms \
   || $coms_root_default == /var/lib/freq-agents/coms/* ]] || {
    printf 'invalid communications root\n' >&2; exit 2;
}
[[ $board_root_default == /var/lib/freq-agents/board \
   || $board_root_default == /var/lib/freq-agents/board/* ]] || {
    printf 'invalid board root\n' >&2; exit 2;
}
if [[ -n $master_public_key ]]; then
    master_public_key=$(realpath -e -- "$master_public_key")
    [[ -f $master_public_key && ! -L $master_public_key ]] || {
        printf 'master public key must be a regular file\n' >&2; exit 2;
    }
fi
readonly master_public_key

[[ -f $source_root/freq-ai-setup \
    && -f $source_root/PORTABLE-INSTALL.md \
    && -f $assets/agent-contract.md && -f $assets/render-agent-contract \
    && -f $assets/watch-once/SKILL.md && -f $assets/watch-once/agents/openai.yaml \
    && -f $assets/watch-once/scripts/watch_once.py \
    && -f $assets/remote-test && -f $assets/remote-tests/client.py \
    && -f $assets/remote-tests/visibility_model.py && -f $assets/remote-tests/README.md \
    && -f $coms_assets/lib/freq_coms_receipts.py && -f $coms_assets/bin/dev-msg-status \
    && -f $assets/board-system/bin/project-assess && -f $assets/board-system/bin/task-update \
    && -f $assets/board-system/bin/board-stop-hook && -f $assets/configure-stop-guard \
    && -f $assets/host-admin/own_crontab.py && -f $assets/host-admin/agent-crontab \
    && -f $assets/board-system/bin/task-dependencies \
    && -f $assets/board-system/lib/freq_board_dependencies.py \
    && -f $assets/board-system/lib/freq_dependency_model.py \
    && -f $assets/board-system/lib/freq_board_transaction.py \
    && -f $assets/board-system/lib/freq_board_inspect.py \
    && -f $source_root/debian-freq-ai-setup/bootstrap-freq-ai-setup \
    && -f $assets/create-agent && -f $assets/update-agent && -f $assets/update-agent.md && -f $assets/delete-agent && -f $assets/level-set \
    && -f $assets/ai-packages-install && -f $assets/full-update \
    && -f $assets/update-shared-git && -f $assets/update-discord && -f $assets/configure-shared-git \
    && -f $assets/update-ssh-key && -f $assets/configure-master-ssh-key \
    && -f $assets/agent-groups && -f $assets/manage-agent-groups && -f $assets/discord-connector/freq_groups.py \
    && -f $assets/shared-git \
    && -f $assets/wrap-up-state && -f $assets/wrap-up/SKILL.md \
    && -f $assets/agent-startup-notify && -f $assets/agent-startup-message.md \
    && -f $assets/wrap-up/agents/openai.yaml \
    && -f $assets/update-managed-tools && -f $assets/retire-agent-data \
    && -f $assets/container-worker && -f $assets/container-client \
    && -f $assets/container-accept && -f $assets/setup-container-tools \
    && -f $assets/container-tools.conf && -f $assets/freq-container@.service \
    && -f $assets/freq-container@.socket \
    && -f $assets/refresh-tool-menu && -f $assets/freq-maintenance.conf \
    && -f $assets/devtools-install && -f $assets/devtools-accept \
    && -f $assets/install-dev-apt && -f $assets/packages/apt-base.txt \
    && -f $assets/packages/apt-browser.txt && -f $assets/packages/binaries.json \
    && -f $assets/packages/python/semgrep.txt && -f $assets/packages/python/fonttools.txt \
    && -f $assets/packages/webqa/package-lock.json \
    && -f $assets/cmd-list && -f $existing_assets/nexus-prompt.sh \
    && -f $existing_assets/agent-trust-current \
    && -f $assets/ssh-agent-policy.conf \
    && -f $assets/setup-coms && -f $assets/setup-board \
    && -f $assets/setup-discord \
    && -f $assets/host-admin/install.py && -f $assets/host-admin/broker.py \
    && -f $assets/host-admin/client.py && -f $assets/host-admin/network_file.py \
    && -f $assets/discord-connector/connector.py \
    && -f $assets/discord-connector/freq_discord_core.py \
    && -f $assets/discord-connector/freq_discord_bot.py \
    && -f $assets/discord-connector/freq-discord.service \
    && -f $assets/claude-statusline \
    && -f $coms_assets/bin/dev-msg \
    && -f $coms_assets/bin/dev-read \
    && -f $coms_assets/bin/dev-inbox \
    && -f $coms_assets/bin/dev-drain \
    && -f $coms_assets/bin/agent-team \
    && -f $coms_assets/skills/dev-msg/SKILL.md \
    && -f $coms_assets/skills/dev-inbox/SKILL.md \
    && -f $coms_assets/skills/dev-read/SKILL.md \
    && -f $coms_assets/skills/dev-drain/SKILL.md \
    && -f $coms_assets/skills/agent-team/SKILL.md \
    && -f $assets/board-system/bin/board-alert-watch \
    && -f $assets/board-system/bin/project-assign \
    && -f $assets/board-system/bin/project-list \
    && -f $assets/board-system/bin/project-register \
    && -f $assets/board-system/bin/project-archive \
    && -f $assets/board-system/bin/project-status \
    && -f $assets/board-system/bin/task-block \
    && -f $assets/board-system/bin/task-done \
    && -f $assets/board-system/bin/task-ready \
    && -f $assets/board-system/bin/task-register \
    && -f $assets/board-system/bin/task-status \
    && -f $assets/board-system/bin/task-transfer \
    && -f $assets/board-system/lib/freq_board.py \
    && -f $assets/board-system/lib/freq_board_alert.py \
    && -f $assets/board-behavior/AGENTS.board.md \
    && -f $assets/board-behavior/CLAUDE.board.md ]] || {
    printf 'install source is incomplete\n' >&2; exit 2;
}
backup_target() {
    [[ ${FREQ_SKIP_BACKUP:-0} == 1 ]] && return 0
    local target=$1 name
    [[ -e $target || -L $target ]] || return 0
    name="${target#/}"
    install -d -o root -g root -m 0700 "$backup/$(dirname -- "$name")"
    cp -a -- "$target" "$backup/$name"
}
if [[ ${FREQ_SKIP_BACKUP:-0} != 1 ]]; then
    install -d -o root -g root -m 0700 "$backup"
fi
for target in \
    /etc/passwd /etc/group /etc/shadow /etc/gshadow \
    /etc/pam.d/sshd /etc/pam.d/login /etc/motd /run/motd.dynamic /etc/update-motd.d/10-uname \
    /etc/ssh/sshd_config /etc/ssh/sshd_config.d/60-freq-ai-setup.conf \
    /etc/profile.d/20-freq-ai-setup.sh /etc/sudoers.d/90-freq-ai-setup-owner \
    /etc/freq-ai-setup/site.conf /etc/freq-ai-setup/source-manifest.sha256 \
    /etc/freq-ai-setup/install-receipt /etc/freq-ai-setup/mosh.conf \
    "$requested_master_home/.bashrc" "$requested_master_home/.bash_profile" \
    "$requested_master_home/.tmux.conf" "$requested_master_home/tools/create-agent" \
    "$requested_master_home/tools/update-agent" \
    /usr/local/share/freq-ai-setup/update-agent.md \
    "$requested_master_home/tools/delete-agent" \
    "$requested_master_home/tools/agent-groups" \
    "$requested_master_home/tools/level-set" \
    "$requested_master_home/tools/setup-coms" \
    "$requested_master_home/tools/setup-board" \
    "$requested_master_home/tools/ai-packages-install" "$requested_master_home/cmd-list" \
    /usr/local/share/freq-ai-setup/claude-statusline \
    "$requested_master_home/.ssh/authorized_keys"; do
    backup_target "$target"
done

export DEBIAN_FRONTEND=noninteractive
source /etc/os-release
[[ ${ID:-} == debian && ${VERSION_ID:-} == 13 ]] || {
    printf 'portable FREQ-AI-SETUP requires Debian 13\n' >&2; exit 2;
}
[[ $(dpkg --print-architecture) == amd64 ]] || {
    printf 'portable FREQ-AI-SETUP currently requires Debian amd64\n' >&2; exit 2;
}
[[ $(cat /proc/1/comm) == systemd ]] || {
    printf 'portable FREQ-AI-SETUP requires systemd as PID 1\n' >&2; exit 2;
}
/bin/bash "$assets/install-dev-apt" "$assets/packages"

locale-gen en_US.UTF-8
command -v mosh-server >/dev/null || {
    printf 'mosh-server was not installed successfully\n' >&2; exit 2;
}
mosh_firewall_state=skipped
if [[ $mosh_firewall != skip ]]; then
    if command -v ufw >/dev/null 2>&1 \
       && ufw status 2>/dev/null | grep -Fqx 'Status: active'; then
        ufw allow 60000:61000/udp >/dev/null
        mosh_firewall_state=ufw-configured
    elif command -v firewall-cmd >/dev/null 2>&1 \
         && systemctl is-active --quiet firewalld; then
        firewall-cmd --permanent --add-port=60000-61000/udp >/dev/null
        firewall-cmd --reload >/dev/null
        mosh_firewall_state=firewalld-configured
    elif systemctl is-active --quiet nftables 2>/dev/null; then
        if [[ $mosh_firewall == required ]]; then
            printf 'active nftables policy requires an operator-defined UDP 60000:61000 rule\n' >&2
            exit 2
        fi
        mosh_firewall_state=nftables-manual-review
    else
        mosh_firewall_state=no-active-guest-firewall
    fi
fi
readonly mosh_firewall_state
if ! getent passwd "$master" >/dev/null; then
    (( create_master == 1 )) || {
        printf 'master user is missing: %s\n' "$master" >&2; exit 2;
    }
    useradd --user-group --create-home --home-dir "$requested_master_home" \
        --shell /bin/bash "$master"
fi
master_record=$(getent passwd "$master")
master_home=$(cut -d: -f6 <<<"$master_record")
master_shell=$(cut -d: -f7 <<<"$master_record")
[[ $master_home == "$requested_master_home" ]] || {
    printf 'master home mismatch: expected %s, found %s\n' \
        "$requested_master_home" "$master_home" >&2
    exit 2
}
[[ $master_shell == /bin/bash ]] || {
    printf 'master account must use /bin/bash: %s\n' "$master" >&2; exit 2;
}
master_group=$(id -gn "$master")
[[ -d $master_home && ! -L $master_home \
   && $(stat -Lc '%U:%G' "$master_home") == "$master:$master_group" ]] || {
    printf 'master home is unavailable or unsafe: %s\n' "$master_home" >&2; exit 2;
}
chmod 0700 "$master_home"
readonly master_home master_group master_shell master_record
getent group freq-agents >/dev/null || groupadd freq-agents

install -d -o root -g freq-agents -m 0750 /home/freq-agents
install -d -o root -g freq-agents -m 2770 /home/freq-agents/projects
python3 - <<'PY'
import os
from pathlib import Path
old = Path("/home/freq-agents/projects/_agent-state")
new = Path("/home/freq-agents/session-data")
if old.exists() or old.is_symlink():
    if old.is_symlink() or not old.is_dir() or new.exists() or new.is_symlink():
        raise SystemExit("Session-data migration needs review: refusing symlinks or merging existing destinations.")
    before = old.stat()
    os.rename(old, new)
    after = new.lstat()
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise SystemExit("Session-data source changed during migration; inspect before continuing.")
PY
install -d -o root -g freq-agents -m 2770 /home/freq-agents/session-data
setfacl -m u::rwx,g::rwx,m::rwx,o::---,d:u::rwx,d:g::rwx,d:m::rwx,d:o::--- /home/freq-agents/session-data
setfacl -m u:"$master":rwx,d:u:"$master":rwx /home/freq-agents/session-data
install -d -o root -g freq-agents -m 2750 /home/freq-agents/staging
setfacl -m u::rwx,g::rwx,m::rwx,o::---,d:u::rwx,d:g::rwx,d:m::rwx,d:o::--- /home/freq-agents/projects
setfacl -m u::rwx,g::r-x,m::r-x,o::---,d:u::rwx,d:g::r-x,d:m::r-x,d:o::--- /home/freq-agents/staging
setfacl -m u:"$master":r-x /home/freq-agents
setfacl -m u:"$master":rwx,d:u:"$master":rwx /home/freq-agents/projects
setfacl -m u:"$master":r-x,d:u:"$master":r-x /home/freq-agents/staging
install -o root -g freq-agents -m 0640 "$assets/shared-projects-README.md" /home/freq-agents/projects/README.md
install -o root -g freq-agents -m 0640 "$assets/shared-staging-README.md" /home/freq-agents/staging/README.md
setfacl -m u:"$master":r-- /home/freq-agents/projects/README.md /home/freq-agents/staging/README.md

install -d -o root -g root -m 0755 /etc/freq-ai-setup/identities /etc/freq-ai-setup/agents.d
install -d -o root -g root -m 0755 /usr/local/share/freq-ai-setup /usr/local/libexec/freq-ai-setup
install -d -o root -g freq-agents -m 0750 \
    /var/lib/freq-agents /var/lib/freq-agents/coms
{
    printf 'export FREQ_MASTER_USER=%q\n' "$master"
    printf 'export FREQ_MASTER_GROUP=%q\n' "$master_group"
    printf 'export FREQ_MASTER_HOME=%q\n' "$master_home"
    printf 'export FREQ_OPERATOR_NAME=%q\n' "$operator_name"
    printf 'export FREQ_HOST=%q\n' "$site_host"
} >/etc/freq-ai-setup/site.conf
chmod 0644 /etc/freq-ai-setup/site.conf
{
    printf 'FREQ_MOSH_UDP_RANGE=%q\n' '60000:61000'
    printf 'FREQ_MOSH_GUEST_FIREWALL_STATE=%q\n' "$mosh_firewall_state"
} >/etc/freq-ai-setup/mosh.conf
chmod 0644 /etc/freq-ai-setup/mosh.conf
printf "export FREQ_USER_TRUECOLOR='168;85;247'\nexport FREQ_USER_256='141'\n" \
    >"/etc/freq-ai-setup/identities/$master.conf"
chmod 0644 "/etc/freq-ai-setup/identities/$master.conf"
install -o root -g root -m 0644 "$existing_assets/nexus-prompt.sh" /usr/local/share/freq-ai-setup/nexus-prompt.sh
install -o root -g root -m 0644 "$assets/freq-ai-setup-profile.sh" /etc/profile.d/20-freq-ai-setup.sh
install -o root -g root -m 0644 "$assets/tmux.conf.template" /usr/local/share/freq-ai-setup/tmux.conf.template
install -o root -g root -m 0644 "$assets/agent-contract.md" /usr/local/share/freq-ai-setup/agent-contract.md
install -o root -g root -m 0755 "$assets/render-agent-contract" /usr/local/libexec/freq-ai-setup/render-agent-contract
sed -e 's/__NAME__/NEXUS/g' -e 's/__COLOUR__/#A855F7/g' \
    -e "s/__HOST__/$site_host/g" \
    "$assets/tmux.conf.template" >"$master_home/.tmux.conf"
chown "$master:$master_group" "$master_home/.tmux.conf"
chmod 0644 "$master_home/.tmux.conf"
install -o root -g root -m 0755 "$existing_assets/agent-trust-current" /usr/local/libexec/freq-ai-setup/agent-trust-current
# Public releases must not grant access to the original deployment's fleet key.
fleet_key=/etc/freq-ai-setup/agent-fleet-key.pub
if [[ -e $fleet_key || -L $fleet_key ]]; then
    [[ -f $fleet_key && ! -L $fleet_key && $(stat -Lc '%U:%G:%a' "$fleet_key") == root:root:644 ]] || {
        printf 'unsafe existing fleet public key; preserved
' >&2; exit 2;
    }
else
    if [[ -n $master_public_key ]]; then
        install -o root -g root -m 0644 "$master_public_key" "$fleet_key"
    else
        install -o root -g root -m 0644 /dev/null "$fleet_key"
    fi
fi
install -d -o "$master" -g "$master_group" -m 0755 "$master_home/tools" "$master_home/agents"
install -o "$master" -g "$master_group" -m 0755 "$assets/create-agent" "$master_home/tools/create-agent"
install -o "$master" -g "$master_group" -m 0700 "$assets/update-agent" "$master_home/tools/update-agent"
install -o root -g root -m 0644 "$assets/update-agent.md" /usr/local/share/freq-ai-setup/update-agent.md
install -o "$master" -g "$master_group" -m 0755 "$assets/delete-agent" "$master_home/tools/delete-agent"
install -o "$master" -g "$master_group" -m 0755 "$assets/level-set" "$master_home/tools/level-set"
install -o "$master" -g "$master_group" -m 0755 "$assets/full-update" "$master_home/tools/full-update"
install -o "$master" -g "$master_group" -m 0755 "$assets/update-shared-git" "$master_home/tools/update-shared-git"
install -o "$master" -g "$master_group" -m 0755 "$assets/update-discord" "$master_home/tools/update-discord"
install -o "$master" -g "$master_group" -m 0755 "$assets/update-ssh-key" "$master_home/tools/update-ssh-key"
install -o "$master" -g "$master_group" -m 0700 "$assets/agent-groups" "$master_home/tools/agent-groups"
install -d -o root -g root -m 0755 /usr/local/libexec/freq-ai-setup
install -o root -g root -m 0755 "$assets/configure-master-ssh-key" /usr/local/libexec/freq-ai-setup/configure-master-ssh-key
install -o root -g root -m 0700 "$assets/manage-agent-groups" /usr/local/libexec/freq-ai-setup/manage-agent-groups
python3 -I "$assets/host-admin/install.py"
for tool in setup-coms setup-board setup-discord ai-packages-install delete-agent retire-agent-data update-managed-tools refresh-tool-menu configure-stop-guard; do
    install -o root -g root -m 0755 "$assets/$tool" "/usr/local/libexec/freq-ai-setup/$tool"
done
install -o root -g root -m 0644 "$assets/stop-gate.md" /usr/local/share/freq-ai-setup/stop-gate.md
for helper in shared-git configure-shared-git; do
    install -o root -g root -m 0755 "$assets/$helper" "/usr/local/libexec/freq-ai-setup/$helper"
done
for program in git gh; do
    target="/usr/local/bin/$program"
    if [[ -e $target || -L $target ]]; then
        [[ -f $target && ! -L $target ]] \
            && grep -Fq 'Shared GitHub adapter; credentials are never written into repository config.' "$target" \
            || { printf 'Refusing to replace unrelated command: %s\n' "$target" >&2; exit 1; }
    fi
    install -o root -g root -m 0755 "$assets/shared-git" "$target"
done
install -o root -g root -m 0644 "$assets/freq-maintenance.conf" /etc/tmpfiles.d/freq-maintenance.conf
systemd-tmpfiles --create /etc/tmpfiles.d/freq-maintenance.conf
install -d -o root -g root -m 0755 /opt/freq-agents/discord-connector
for discord_file in connector.py freq-discord.service freq_discord_core.py freq_discord_bot.py freq_groups.py requirements.txt agent_control.py freq-agent-control.socket freq-agent-control.service; do
    install -o root -g root -m 0644 "$assets/discord-connector/$discord_file" "/opt/freq-agents/discord-connector/$discord_file"
done
install -d -o root -g root -m 0755 /usr/local/share/freq-ai-setup/devtools/packages
cp -a "$assets/packages/." /usr/local/share/freq-ai-setup/devtools/packages/
chown -R root:root /usr/local/share/freq-ai-setup/devtools
find /usr/local/share/freq-ai-setup/devtools -type d -exec chmod 0755 {} +
find /usr/local/share/freq-ai-setup/devtools -type f -exec chmod 0644 {} +
for helper in devtools-install install-dev-apt devtools-accept check-python-dependencies check-semgrep-compatibility; do
    install -o root -g root -m 0755 "$assets/$helper" "/usr/local/share/freq-ai-setup/devtools/$helper"
done
install -o root -g root -m 0644 "$assets/semgrep-compat-policy.json" /usr/local/share/freq-ai-setup/devtools/semgrep-compat-policy.json
install -o "$master" -g "$master_group" -m 0644 "$assets/cmd-list" "$master_home/cmd-list"
install -o root -g root -m 0644 "$assets/agent-lifecycle.template" /usr/local/share/freq-ai-setup/agent-lifecycle.template
install -o root -g root -m 0755 "$assets/agent-startup-notify" /usr/local/libexec/freq-ai-setup/agent-startup-notify
install -o root -g root -m 0644 "$assets/agent-startup-message.md" /usr/local/share/freq-ai-setup/agent-startup-message.md
install -o root -g root -m 0755 "$assets/claude-statusline" \
    /usr/local/share/freq-ai-setup/claude-statusline
install -d -o root -g root -m 0755 /opt/freq-agents/skills/wrap-up/agents
install -o root -g root -m 0644 "$assets/wrap-up/SKILL.md" \
    /opt/freq-agents/skills/wrap-up/SKILL.md
install -o root -g root -m 0644 "$assets/wrap-up/agents/openai.yaml" \
    /opt/freq-agents/skills/wrap-up/agents/openai.yaml
install -o root -g root -m 0755 "$assets/wrap-up-state" /usr/local/bin/wrap-up-state
install -d -o root -g root -m 0755 /opt/freq-agents/skills/watch-once/agents /opt/freq-agents/skills/watch-once/scripts
install -o root -g root -m 0644 "$assets/watch-once/SKILL.md" /opt/freq-agents/skills/watch-once/SKILL.md
install -o root -g root -m 0644 "$assets/watch-once/agents/openai.yaml" /opt/freq-agents/skills/watch-once/agents/openai.yaml
install -o root -g root -m 0644 "$assets/watch-once/scripts/watch_once.py" /opt/freq-agents/skills/watch-once/scripts/watch_once.py
install -d -o root -g root -m 0755 /usr/local/lib/freq-remote-tests-client
install -o root -g root -m 0644 "$assets/remote-tests/client.py" "$assets/remote-tests/visibility_model.py" /usr/local/lib/freq-remote-tests-client/
install -o root -g root -m 0755 "$assets/remote-test" /usr/local/bin/remote-test
install -o root -g root -m 0644 "$assets/remote-tests/README.md" /usr/local/share/freq-ai-setup/remote-tests.md
FREQ_DEV_APT_READY=1 /usr/local/libexec/freq-ai-setup/ai-packages-install
install -d -o root -g root -m 0755 \
    /opt/freq-agents \
    /opt/freq-agents/coms-system \
    /opt/freq-agents/coms-system/bin \
    /opt/freq-agents/coms-system/tests \
    /opt/freq-agents/coms-system/skills
install -d -o root -g root -m 0755 /opt/freq-agents/coms-system/lib
install -o root -g root -m 0644 "$coms_assets/lib/freq_coms_receipts.py" /opt/freq-agents/coms-system/lib/freq_coms_receipts.py
install -o root -g root -m 0644 "$coms_assets/README.md" \
    /opt/freq-agents/coms-system/README.md
for command in dev-msg dev-msg-status dev-read dev-inbox dev-drain agent-team; do
    install -o root -g root -m 0755 "$coms_assets/bin/$command" \
        "/opt/freq-agents/coms-system/bin/$command"
done
for test_file in "$coms_assets"/tests/test_*.py; do
    install -o root -g root -m 0644 "$test_file" \
        "/opt/freq-agents/coms-system/tests/${test_file##*/}"
done
for skill in dev-msg dev-msg-status dev-inbox dev-read dev-drain agent-team; do
    install -d -o root -g root -m 0755 \
        "/opt/freq-agents/coms-system/skills/$skill/agents"
    install -o root -g root -m 0644 \
        "$coms_assets/skills/$skill/SKILL.md" \
        "/opt/freq-agents/coms-system/skills/$skill/SKILL.md"
    install -o root -g root -m 0644 \
        "$coms_assets/skills/$skill/agents/openai.yaml" \
        "/opt/freq-agents/coms-system/skills/$skill/agents/openai.yaml"
done
FREQ_COMS_TMUX_DEFAULT=$tmux_dir_default \
FREQ_COMS_ROOT_DEFAULT=$coms_root_default \
    /usr/local/libexec/freq-ai-setup/setup-coms --defaults --yes

install -d -o root -g root -m 0755 \
    /opt/freq-agents/board-system/bin \
    /opt/freq-agents/board-system/lib \
    /opt/freq-agents/board-system/skills \
    /opt/freq-agents/board-system/systemd \
    /opt/freq-agents/board-system/tests \
    /opt/freq-agents/board-behavior
for command in \
    board-alert-watch project-archive project-assign project-list project-register \
    project-status task-dependencies task-block task-done task-ready task-register task-status \
    task-transfer project-assess task-update agent-skills board-stop-hook task-project-migrate; do
    install -o root -g root -m 0755 "$assets/board-system/bin/$command" \
        "/opt/freq-agents/board-system/bin/$command"
done
for library in freq_board.py freq_board_alert.py freq_board_transaction.py freq_board_inspect.py freq_board_dependencies.py freq_dependency_model.py freq_stop_gate.py freq_board_update.py freq_board_pause.py freq_task_identity.py freq_project_migration.py; do
    install -o root -g root -m 0644 \
        "$assets/board-system/lib/$library" \
        "/opt/freq-agents/board-system/lib/$library"
done
for unit in freq-board-alert@.service freq-board-alert@.timer; do
    install -o root -g root -m 0644 "$assets/board-system/systemd/$unit" \
        "/opt/freq-agents/board-system/systemd/$unit"
done
for test_file in "$assets"/board-system/tests/test_*.py; do
    install -o root -g root -m 0644 "$test_file" \
        "/opt/freq-agents/board-system/tests/${test_file##*/}"
done
for skill in \
    project-archive project-assign project-list project-register project-status \
    task-dependencies task-block task-done task-ready task-register task-status task-transfer project-assess task-update agent-skills; do
    install -d -o root -g root -m 0755 \
        "/opt/freq-agents/board-system/skills/$skill/agents"
    install -o root -g root -m 0644 \
        "$assets/board-system/skills/$skill/SKILL.md" \
        "/opt/freq-agents/board-system/skills/$skill/SKILL.md"
    install -o root -g root -m 0644 \
        "$assets/board-system/skills/$skill/agents/openai.yaml" \
        "/opt/freq-agents/board-system/skills/$skill/agents/openai.yaml"
done
install -o root -g root -m 0644 "$assets/board-behavior/AGENTS.board.md" \
    /opt/freq-agents/board-behavior/AGENTS.board.md
install -o root -g root -m 0644 "$assets/board-behavior/CLAUDE.board.md" \
    /opt/freq-agents/board-behavior/CLAUDE.board.md
FREQ_BOARD_ROOT_DEFAULT=$board_root_default \
    /usr/local/libexec/freq-ai-setup/setup-board --defaults --yes
install -o root -g root -m 0644 "$assets/freq-agent-tmux.conf" /etc/tmpfiles.d/freq-agent-tmux.conf
systemd-tmpfiles --create /etc/tmpfiles.d/freq-agent-tmux.conf

for helper in container-worker container-client container-accept setup-container-tools; do
    install -o root -g root -m 0755 "$assets/$helper" "/usr/local/libexec/freq-ai-setup/$helper"
done
install -o root -g root -m 0644 "$assets/container-tools.conf" /usr/local/share/freq-ai-setup/container-tools.conf
install -o root -g root -m 0644 "$assets/freq-container@.service" "$assets/freq-container@.socket" /etc/systemd/system/
/usr/local/libexec/freq-ai-setup/setup-container-tools --refresh

install -o root -g root -m 0644 "$assets/freq-agent-sandbox.c" /usr/local/src/freq-agent-sandbox.c
binary_tmp="$(mktemp)"
trap 'rm -f -- "$binary_tmp"' EXIT HUP INT TERM
gcc -O2 -Wall -Wextra -Werror -o "$binary_tmp" /usr/local/src/freq-agent-sandbox.c
install -o root -g root -m 4755 "$binary_tmp" /usr/local/sbin/freq-agent-sandbox

install -o root -g root -m 0644 "$assets/ssh-agent-policy.conf" \
    /etc/ssh/sshd_config.d/60-freq-ai-setup.conf
sed -Ei '/^[[:space:]]*session[[:space:]].*pam_motd\.so/s/^/# FREQ_AI_SETUP_MOTD_DISABLED /' /etc/pam.d/sshd /etc/pam.d/login
install -o root -g root -m 0644 /dev/null /etc/motd
# Mosh reads the dynamic cache directly, even with SSH/PAM MOTD disabled.
install -o root -g root -m 0644 /dev/null /run/motd.dynamic
[[ ! -e /etc/update-motd.d/10-uname ]] || chmod 0644 /etc/update-motd.d/10-uname

install -d -o "$master" -g "$master_group" -m 0700 "$master_home/.ssh"
if [[ -n $master_public_key ]] \
   && ! grep -Fqx -f "$master_public_key" "$master_home/.ssh/authorized_keys" 2>/dev/null; then
    [[ ! -s $master_home/.ssh/authorized_keys ]] || printf '\n' >>"$master_home/.ssh/authorized_keys"
    printf '%s\n' "$(cat "$master_public_key")" >>"$master_home/.ssh/authorized_keys"
fi
if [[ -e $master_home/.ssh/authorized_keys ]]; then
    chown "$master:$master_group" "$master_home/.ssh/authorized_keys"
    chmod 0600 "$master_home/.ssh/authorized_keys"
fi
printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "$master" \
    >/etc/sudoers.d/90-freq-ai-setup-owner
chmod 0440 /etc/sudoers.d/90-freq-ai-setup-owner
visudo -cf /etc/sudoers.d/90-freq-ai-setup-owner

for file in "$master_home/.bashrc" "$master_home/.bash_profile"; do
    touch "$file"
    chown "$master:$master_group" "$file"
    chmod 0644 "$file"
done
if ! grep -Fq '/etc/profile.d/20-freq-ai-setup.sh' "$master_home/.bashrc"; then
    printf '\n# NEXUS FREQ-AI-SETUP shell identity\n[[ -r /etc/profile.d/20-freq-ai-setup.sh ]] && source /etc/profile.d/20-freq-ai-setup.sh\n' >>"$master_home/.bashrc"
fi
if ! grep -Fq 'source ~/.bashrc' "$master_home/.bash_profile"; then
    printf '[[ -r ~/.bashrc ]] && source ~/.bashrc\n' >>"$master_home/.bash_profile"
fi

sshd -t
/usr/local/libexec/freq-ai-setup/refresh-tool-menu
systemctl reload ssh
manifest_tmp=$(mktemp)
(
    cd -- "$source_root"
    {
        find debian-freq-ai-setup/assets -type f -print0
        printf '%s\0' \
            freq-ai-setup \
            PORTABLE-INSTALL.md \
            debian-freq-ai-setup/bootstrap-freq-ai-setup \
            debian-freq-ai-setup/install-base.sh \
            debian-freq-ai-setup/accept-base.sh \
            debian-freq-ai-setup/accept-ai-packages.sh \
            debian-freq-ai-setup/assets/nexus-prompt.sh \
            debian-freq-ai-setup/assets/agent-trust-current
    } | LC_ALL=C sort -z | xargs -0 sha256sum
) >"$manifest_tmp"
install -o root -g root -m 0644 "$manifest_tmp" \
    /etc/freq-ai-setup/source-manifest.sha256
rm -f -- "$manifest_tmp"
{
    printf 'installed_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'master_user=%s\n' "$master"
    printf 'master_home=%s\n' "$master_home"
    printf 'host_label=%s\n' "$site_host"
    printf 'mosh_udp_range=60000:61000\n'
    printf 'mosh_guest_firewall_state=%s\n' "$mosh_firewall_state"
    printf 'source_manifest_sha256=%s\n' \
        "$(sha256sum /etc/freq-ai-setup/source-manifest.sha256 | cut -d' ' -f1)"
} >/etc/freq-ai-setup/install-receipt
chmod 0644 /etc/freq-ai-setup/install-receipt
printf 'MOSH_READY server=installed guest_firewall=%s udp=60000:61000 external_firewall=verify\n' \
    "$mosh_firewall_state"
if [[ ${FREQ_SKIP_BACKUP:-0} == 1 ]]; then
    printf 'FREQ_AI_SETUP_BASE_INSTALLED backup=skipped agents_created=0\n'
else
    printf 'FREQ_AI_SETUP_BASE_INSTALLED backup=%s agents_created=0\n' "$backup"
fi
