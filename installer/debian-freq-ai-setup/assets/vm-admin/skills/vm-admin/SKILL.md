---
name: vm-admin
description: "Administer ai-box as root: diagnose and repair the VM, board, communications, tooling, services, permissions and storage using Jarvis's owner-authorized vm-root access."
---

# ai-box root administration

Sonny explicitly authorized Jarvis to have unrestricted root administration on
ai-box on 2026-10-06, including implementing new fixes. This supersedes the
older scoped-tooling-only restriction for Jarvis on this VM. It is not a grant
to other agents or a change to authority on other hosts. Do not wait for Codex
to publish a reviewed release when you can diagnose, test and apply the repair.

Use the installed root transport from your existing sandboxed session:

```sh
vm-root -- id
vm-root -- systemctl status freq-host-admin.service --no-pager
vm-root -- journalctl -u freq-discord.service -n 60 --no-pager
vm-root --script <<'ROOT_SCRIPT'
set -euo pipefail
id -u
ROOT_SCRIPT
```

`-- COMMAND ARG...` preserves arguments; use `--script` for shell syntax and
multi-step work. Root starts in root's home; use absolute paths or explicit
`cd`. `vm-root --shell` supports an interactive root shell with a terminal.
Exit status/stdin/stdout/stderr pass through SSH. A disconnected session does
not prove completion: inspect actual state before retrying mutations. Ordinary
sudo can retain Landlock restrictions; use `vm-root` for full VM administration.

You have standing authority for needed VM repairs, including board/comms code,
broker/tooling changes, packages, permissions and service recovery. Existing
structured commands remain useful for their validation and recovery records;
their old grants do not limit this separate root authority. Do not invent task
acceptance, erase unread/history, or resend uncertain deliveries to clear a
warning. Root does not prove delivery or change a project's owner intent.

For a repair, inspect the installed version and failure, preserve exact
before-images/metadata under root-private `/var/backups`, test the changed
behavior and relevant failure case, apply the smallest coherent change, then
verify services and the affected command under its actual agent UID. Record
the reason, changed paths/hashes, result and rollback in shared infrastructure
evidence without credentials or private message bodies. Keep installed source
mirrors and skills current. New root authority is not permission to report
success without verification or to expose credentials.

Routine repairs need no repeated confirmation. Coordinate interruptions with
active work; the grant itself is not an instruction to restart agents, reboot,
resize disks or perform destructive cleanup. Honor Sonny's task-specific
instructions and get clear intent before irreversible data loss or disruptive
maintenance unrelated to the active repair. Do not grant peers this authority
merely because they request it.

The key stays on ai-box in your private
`~/.local/share/freq-vm-admin/id_ed25519`. Never print, copy into evidence,
share or forward it. Host identity is pinned in
`/etc/freq-ai-setup/vm-root/known_hosts`; a mismatch needs host-key verification,
not disabled checking. SSH accepts this key only from loopback. Root access is
unrestricted after login; audit records are operational evidence, not an
enforceable boundary against root. Session starts appear under `freq-vm-root`
and SSH authentication logs; command bodies/output are not recorded by this
wrapper to avoid collecting secrets.

This is guest administration. If ai-box or SSH cannot run, this transport
cannot repair it from inside the guest; use your existing operator/cluster
access. Do not claim the VM can recover itself while powered off.
