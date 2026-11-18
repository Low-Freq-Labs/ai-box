#!/bin/bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { printf 'retire-freq-ops must run as root\n' >&2; exit 2; }
readonly source_root="$(cd -- "$(dirname -- "$0")" && pwd -P)"
readonly assets="$source_root/assets"
readonly old_root=/home/freq-ops
readonly new_root=/home/freq-agents
readonly backup_root=/var/backups/freq-ai-setup/freq-ops-retirement
readonly trust_helper=/usr/local/libexec/freq-ai-setup/agent-trust-current

fail() { printf 'retire-freq-ops: %s\n' "$*" >&2; exit 2; }

usage() {
    printf 'usage: retire-freq-ops --dry-run | --prepare BACKUP-ID | --apply BACKUP-ID\n' >&2
}

required_assets=(
    create-agent delete-agent freq-agent-sandbox.c
    shared-projects-README.md shared-staging-README.md ssh-agent-policy.conf
)
for asset in "${required_assets[@]}"; do
    [[ -f $assets/$asset && ! -L $assets/$asset ]] || fail "migration asset is missing: $asset"
done

mapfile -t agents < <(
    find /etc/freq-ai-setup/agents.d -mindepth 1 -maxdepth 1 -type f -name '*.conf' \
        -printf '%f\n' | sed 's/\.conf$//' | sort
)

validate_prestate() {
    getent passwd freq-ops >/dev/null || fail 'freq-ops account is already absent'
    getent group freq-ops >/dev/null || fail 'freq-ops group is already absent'
    getent group freq-agents >/dev/null || fail 'freq-agents group is missing'
    [[ -d $old_root && ! -L $old_root ]] || fail "old shared root is missing: $old_root"
    [[ ! -e $new_root && ! -L $new_root ]] || fail "new shared root is already occupied: $new_root"
    [[ $(stat -Lc '%U:%G:%a' "$old_root") == freq-ops:freq-ops:750 ]] || fail 'old shared root metadata is unexpected'
    [[ $(stat -Lc '%U:%G:%a' "$old_root/projects") == freq-ops:freq-ops:2770 ]] || fail 'old projects metadata is unexpected'
    [[ $(stat -Lc '%U:%G:%a' "$old_root/staging") == root:freq-ops:2750 ]] || fail 'old staging metadata is unexpected'
    [[ -x $trust_helper ]] || fail 'folder-trust helper is missing'
    for agent in "${agents[@]}"; do
        [[ $agent =~ ^[a-z][a-z0-9-]{0,31}$ ]] || fail "invalid registry agent: $agent"
        getent passwd "$agent" >/dev/null || fail "registered account is missing: $agent"
        id -nG "$agent" | tr ' ' '\n' | grep -Fxq freq-agents || fail "agent lacks freq-agents membership: $agent"
        [[ $(stat -Lc '%U:%G:%a' "$old_root/staging/$agent") == "$agent:freq-ops:2750" ]] \
            || fail "staging lane metadata is unexpected: $agent"
    done
    [[ -z $(ps -u freq-ops -o pid=) ]] || fail 'freq-ops owns a live process'
}

show_plan() {
    printf 'MOVE %s -> %s\n' "$old_root" "$new_root"
    printf 'OWNER %s root:freq-agents mode=0750\n' "$new_root"
    printf 'OWNER %s/projects root:freq-agents mode=2770 shared-write\n' "$new_root"
    printf 'OWNER %s/staging root:freq-agents mode=2750\n' "$new_root"
    for agent in "${agents[@]}"; do
        printf 'LANE %s/staging/%s %s:freq-agents mode=2750 peer-read-only\n' \
            "$new_root" "$agent" "$agent"
    done
    printf 'UPDATE create-agent delete-agent Landlock SSH trust README fleet-key-comment\n'
    printf 'REMOVE account=freq-ops group=freq-ops\n'
    printf 'RESTART active agent tmux sessions to clear the retired supplemental GID\n'
    printf 'PRESERVE shared-project-bytes=yes agent-home-bytes=yes\n'
}

prepare() {
    local backup_id=$1 destination="$backup_root/$1" archive
    [[ $backup_id =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || fail 'backup identity must match YYYYMMDDTHHMMSSZ'
    validate_prestate
    [[ ! -e $destination ]] || fail "backup identity already exists: $backup_id"
    install -d -o root -g root -m 0700 "$backup_root" "$destination" "$destination/new-assets"
    archive="$destination/old-state.tar"
    paths=(
        etc/passwd etc/group etc/shadow etc/gshadow etc/subuid etc/subgid
        etc/ssh/sshd_config.d/60-freq-ai-setup.conf
        etc/freq-ai-setup/agent-fleet-key.pub
        home/freq-ops
        home/sonny-aif/tools/create-agent home/sonny-aif/tools/delete-agent
        usr/local/src/freq-agent-sandbox.c usr/local/sbin/freq-agent-sandbox
    )
    for agent in "${agents[@]}"; do
        for path in \
            "home/$agent/.ssh/authorized_keys" \
            "home/$agent/.codex/config.toml" \
            "home/$agent/.claude.json"; do
            [[ -e /$path || -L /$path ]] && paths+=("$path")
        done
    done
    tar --acls --xattrs --numeric-owner --one-file-system -C / -cpf "$archive" "${paths[@]}"
    chmod 0600 "$archive"
    for asset in "${required_assets[@]}"; do
        install -o root -g root -m 0600 "$assets/$asset" "$destination/new-assets/$asset"
    done
    printf '%s\n' "${agents[@]}" >"$destination/agents"
    chmod 0600 "$destination/agents"
    : >"$destination/running-agents"
    for agent in "${agents[@]}"; do
        if runuser -u "$agent" -- tmux -S "/run/freq-agents/tmux/agent-$agent" list-sessions >/dev/null 2>&1; then
            printf '%s\n' "$agent" >>"$destination/running-agents"
        fi
    done
    chmod 0600 "$destination/running-agents"
    {
        printf 'backup_id=%s\n' "$backup_id"
        printf 'old_root=%s\nnew_root=%s\n' "$old_root" "$new_root"
        printf 'freq_ops_uid=%s\n' "$(id -u freq-ops)"
        printf 'freq_ops_gid=%s\n' "$(getent group freq-ops | cut -d: -f3)"
        printf 'freq_agents_gid=%s\n' "$(getent group freq-agents | cut -d: -f3)"
    } >"$destination/receipt"
    chmod 0600 "$destination/receipt"
    (
        cd "$destination"
        sha256sum old-state.tar agents running-agents receipt new-assets/* >SHA256SUMS
        chmod 0600 SHA256SUMS
    )
    printf 'RETIREMENT_BACKUP_READY id=%s path=%s agents=%s\n' "$backup_id" "$destination" "${agents[*]}"
    printf 'ROLLBACK restore old-state.tar with ACLs/xattrs and reinstall the archived passwd/group databases and sandbox bytes.\n'
}

rewrite_fleet_key_comment() {
    local path=$1 temporary
    [[ -f $path && ! -L $path ]] || fail "fleet key is missing: $path"
    temporary="$(mktemp "$(dirname -- "$path")/.fleet-key.XXXXXX")"
    sed -E 's/[[:space:]][^[:space:]]+$/ freq-agents@ai-box-fleet/' "$path" >"$temporary"
    chown --reference="$path" "$temporary"
    chmod --reference="$path" "$temporary"
    mv -Tf -- "$temporary" "$path"
}

apply_migration() {
    local backup_id=$1 destination="$backup_root/$1" binary_tmp agent peer test_file
    [[ -d $destination && ! -L $destination ]] || fail "retirement backup is missing: $backup_id"
    [[ ! -e $destination/STALE ]] || fail "retirement backup predates the current agent layout: $backup_id"
    [[ $(stat -Lc '%U:%G:%a' "$destination") == root:root:700 ]] || fail 'retirement backup metadata is unsafe'
    (cd "$destination" && sha256sum --check --status SHA256SUMS) || fail 'retirement backup verification failed'
    validate_prestate
    [[ $(cat "$destination/agents") == "$(printf '%s\n' "${agents[@]}")" ]] || fail 'agent registry changed after backup'
    current_running="$(
        for agent in "${agents[@]}"; do
            if runuser -u "$agent" -- tmux -S "/run/freq-agents/tmux/agent-$agent" list-sessions >/dev/null 2>&1; then
                printf '%s\n' "$agent"
            fi
        done
    )"
    [[ $current_running == "$(cat "$destination/running-agents")" ]] || fail 'running agent set changed after backup'
    bash -n "$destination/new-assets/create-agent"
    bash -n "$destination/new-assets/delete-agent"
    binary_tmp="$(mktemp)"
    trap 'rm -f -- "${binary_tmp:-}"' EXIT HUP INT TERM
    gcc -O2 -Wall -Wextra -Werror -o "$binary_tmp" "$destination/new-assets/freq-agent-sandbox.c"

    while IFS= read -r agent; do
        [[ -n $agent ]] || continue
        "/home/sonny-aif/agents/$agent/$agent-stop"
    done <"$destination/running-agents"

    mv -- "$old_root" "$new_root"
    chown root:freq-agents "$new_root" "$new_root/projects" "$new_root/staging"
    chgrp -R freq-agents "$new_root"
    chmod 0750 "$new_root"
    chmod 2770 "$new_root/projects"
    chmod 2750 "$new_root/staging"
    setfacl -m u::rwx,g::rwx,m::rwx,o::---,d:u::rwx,d:g::rwx,d:m::rwx,d:o::--- "$new_root/projects"
    setfacl -m u::rwx,g::r-x,m::r-x,o::---,d:u::rwx,d:g::r-x,d:m::r-x,d:o::--- "$new_root/staging"
    setfacl -m u:sonny-aif:r-x "$new_root"
    setfacl -m u:sonny-aif:rwx,d:u:sonny-aif:rwx "$new_root/projects"
    setfacl -m u:sonny-aif:r-x,d:u:sonny-aif:r-x "$new_root/staging"
    for agent in "${agents[@]}"; do
        chown "$agent:freq-agents" "$new_root/staging/$agent"
        chmod 2750 "$new_root/staging/$agent"
        setfacl -m u::rwx,u:sonny-aif:r-x,g::r-x,m::r-x,o::---,d:u::rwx,d:u:sonny-aif:r-x,d:g::r-x,d:m::r-x,d:o::--- \
            "$new_root/staging/$agent"
    done
    install -o root -g freq-agents -m 0640 "$destination/new-assets/shared-projects-README.md" \
        "$new_root/projects/README.md"
    install -o root -g freq-agents -m 0640 "$destination/new-assets/shared-staging-README.md" \
        "$new_root/staging/README.md"
    setfacl -m u:sonny-aif:r-- "$new_root/projects/README.md" "$new_root/staging/README.md"

    install -o sonny-aif -g sonny-aif -m 0755 "$destination/new-assets/create-agent" \
        /home/sonny-aif/tools/create-agent
    install -o sonny-aif -g sonny-aif -m 0755 "$destination/new-assets/delete-agent" \
        /home/sonny-aif/tools/delete-agent
    install -o root -g root -m 0644 "$destination/new-assets/freq-agent-sandbox.c" \
        /usr/local/src/freq-agent-sandbox.c
    install -o root -g root -m 4755 "$binary_tmp" /usr/local/sbin/freq-agent-sandbox
    install -o root -g root -m 0644 "$destination/new-assets/ssh-agent-policy.conf" \
        /etc/ssh/sshd_config.d/60-freq-ai-setup.conf

    rewrite_fleet_key_comment /etc/freq-ai-setup/agent-fleet-key.pub
    for agent in "${agents[@]}"; do
        rewrite_fleet_key_comment "/home/$agent/.ssh/authorized_keys"
        runuser -u "$agent" -- "$trust_helper" codex --remove "$old_root/projects"
        runuser -u "$agent" -- "$trust_helper" claude --remove "$old_root/projects"
        runuser -u "$agent" -- "$trust_helper" codex "$new_root/projects"
        runuser -u "$agent" -- "$trust_helper" claude "$new_root/projects"
        usermod -aG freq-agents "$agent"
    done
    mapfile -t old_members < <(getent group freq-ops | cut -d: -f4 | tr ',' '\n')
    for member in "${old_members[@]}"; do
        [[ -n $member ]] || continue
        gpasswd -d "$member" freq-ops >/dev/null
    done
    userdel freq-ops
    getent group freq-ops >/dev/null && groupdel freq-ops

    sshd -t
    systemctl reload ssh
    trap - EXIT HUP INT TERM
    rm -f -- "$binary_tmp"

    [[ ! -e $old_root && ! -L $old_root ]] || fail 'old shared root remains'
    ! getent passwd freq-ops >/dev/null || fail 'freq-ops account remains'
    ! getent group freq-ops >/dev/null || fail 'freq-ops group remains'
    [[ $(stat -Lc '%U:%G:%a' "$new_root") == root:freq-agents:750 ]] || fail 'new shared root verification failed'
    [[ $(stat -Lc '%U:%G:%a' "$new_root/projects") == root:freq-agents:2770 ]] || fail 'new projects verification failed'
    [[ $(stat -Lc '%U:%G:%a' "$new_root/staging") == root:freq-agents:2750 ]] || fail 'new staging verification failed'
    for agent in "${agents[@]}"; do
        id -nG "$agent" | tr ' ' '\n' | grep -Fxq freq-agents || fail "new membership missing: $agent"
        ! id -nG "$agent" | tr ' ' '\n' | grep -Fxq freq-ops || fail "retired membership remains: $agent"
        test_file="$new_root/projects/.retirement-$agent-$$"
        runuser -u "$agent" -- sh -c "printf ok >'$test_file'"
        rm -f -- "$test_file"
        test_file="$new_root/staging/$agent/.retirement-$$"
        runuser -u "$agent" -- sh -c "printf ok >'$test_file'"
        rm -f -- "$test_file"
        for peer in "${agents[@]}"; do
            [[ $peer != "$agent" ]] || continue
            if runuser -u "$agent" -- sh -c ": >'$new_root/staging/$peer/.forbidden'" 2>/dev/null; then
                rm -f -- "$new_root/staging/$peer/.forbidden"
                fail "$agent can write peer staging lane: $peer"
            fi
        done
        runuser -u "$agent" -- env SSH_ORIGINAL_COMMAND="test -r '$new_root/projects/README.md' && test ! -e '$old_root'" \
            /usr/local/sbin/freq-agent-sandbox || fail "new Landlock path failed: $agent"
    done
    ! id -nG sonny-aif | tr ' ' '\n' | grep -Fxq freq-agents || fail 'Sonny incorrectly joined agent security group'
    runuser -u sonny-aif -- test -w "$new_root/projects" || fail 'Sonny projects ACL missing'
    while IFS= read -r agent; do
        [[ -n $agent ]] || continue
        "/home/sonny-aif/agents/$agent/$agent-start"
    done <"$destination/running-agents"
    printf 'FREQ_OPS_RETIRED backup=%s shared_root=%s agents=%s\n' "$destination" "$new_root" "${agents[*]}"
}

case "${1:-}" in
    --dry-run)
        [[ $# -eq 1 ]] || { usage; exit 2; }
        validate_prestate
        show_plan
        ;;
    --prepare)
        [[ $# -eq 2 ]] || { usage; exit 2; }
        prepare "$2"
        ;;
    --apply)
        [[ $# -eq 2 ]] || { usage; exit 2; }
        apply_migration "$2"
        ;;
    *) usage; exit 2 ;;
esac
