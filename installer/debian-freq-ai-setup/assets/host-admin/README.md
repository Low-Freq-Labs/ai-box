# Service alerts and delegated ai-box management

## Maintenance controls (2026-10-05)

The new endpoints are `board-admin`, `coms-admin`, `dev-msg-status`,
`storage-budget`, and `host-admin tooling`. Their maintained skills live under
`/opt/freq-agents/skills/`; installation refreshes personal skills for agents
already recorded with maintenance grants. No agent named Jarvis is assumed.
Use each command's `--help` and the skill for its exact schema and limits.

New grants are separate from legacy `all` and are checked by UID on each request:

```sh
agent-admin grant-scoped AGENT board-maintenance --scope project:PROJECT --approval APPROVAL_REFERENCE
agent-admin grant-scoped AGENT coms-maintenance --scope coms:shared --approval APPROVAL_REFERENCE
agent-admin grant-scoped AGENT tooling-maintenance --scope component:board-coms --approval APPROVAL_REFERENCE
agent-admin show-scoped AGENT
agent-admin revoke-scoped AGENT board-maintenance
```

Replace uppercase placeholders with the intended registered agent, exact scope,
and actual operator approval reference. These examples grant nothing by themselves.
Only the authenticated operator can grant/revoke. The portable installer places
`agent-admin` in the configured operator's `~/tools`; do not assume a global
`/usr/local/sbin/agent-admin` exists.
Board workers run as the authenticated agent; root stores plans and audit only.
Routine recovery closes pre-prepare journals without deleting evidence or finishes
the exact prepared transition. It never replays uncertain notifications.

Comms inspection exposes metadata, including legacy Discord ledger lookup by
exact outbox filename. New sends have stable UUID receipts and optional idempotency
keys. Ambiguous remote posts are not retried. Reconciliation reports existing
acknowledgments and preserves unresolved uncertainty; it does not guess delivery.

Storage admission serializes shared reservations. Expiry does not release them;
owners release only after writers stop. Logical reservations are not a quota or
physically isolated capacity. `storage-run` provides opt-in case supervision;
existing scripts are not automatically managed. A separate root-owned reservoir
holds emergency capacity when sufficient headroom exists. Its timer can release
only that reserve; recovered space is not exclusive to control operations.
Inspect `physical_control_reserve` and read the installed `storage-run.md` for
receipt, controller-loss, and rollback limits. Shared project paths are exposed
read-only through a narrow bind inside the broker; private homes remain hidden.

Tooling accepts only operator-published, reviewed root-private releases for fixed
board/comms targets and compatible schema 1. Initial baseline releases provide
verified versions to inspect; they do not permit agents to publish arbitrary code.
Broker self-updates, credentials, private homes, disk surgery and service control
outside existing capabilities are excluded. Incomplete jobs retain before-images
and require inspection. Syntax/hash verification is not full behavioral acceptance.

All registered agents can use `service-alerts`. Only the operator can use
`agent-admin` to grant host-management capabilities. Requests go through an
authenticated Unix socket; there is no sudo shell, arbitrary command, arbitrary
file operation, or access to private agent directories in this API.

## Operator permissions

```sh
agent-admin show
agent-admin grant jarvis diagnostics smb network services
agent-admin grant jarvis packages
agent-admin revoke jarvis network
agent-admin revoke jarvis all
```

Grants take effect immediately and are checked on every request. No capabilities
are granted by installation. Existing operations finish when a grant is revoked;
revoking network access does not cancel its automatic rollback timer.

## Alert setup (available to every agent)

Generate a dedicated SSH key on the machine running the watchdog. Keep its private
key on that machine. Give the public key to the agent setting up the integration:

```sh
service-alerts add plex PLEX-WATCHDOG jarvis < plex-alert.pub
service-alerts show
service-alerts update plex PLEX-WATCHDOG clancy
service-alerts key plex < replacement-alert.pub
service-alerts disable plex
service-alerts enable plex
service-alerts remove plex
```

Each agent manages only sources it creates. The operator can manage all sources.
A key belongs to exactly one source and fixes the sender label and recipient.
Labels are uppercase, up to 48 characters; existing agent/operator message
identities are reserved. There are at most 32 sources per owner and 256 per host.
Source IDs are globally unique; use a descriptive name if another source exists.

From the watchdog host, after verifying ai-box's SSH host key:

```sh
printf '%s\n' 'Plex is offline' |
  ssh -T -o BatchMode=yes -i /path/to/plex-alert-key freq-alerts@ai-box
```

No remote command is required (`send` is also accepted). Interactive shell,
forwarding, password login and agent-file access are unavailable to this account.
The notification begins `PLEX-WATCHDOG:` and uses the same locked pane delivery
and `dev-read` body storage as `dev-msg`. It is not an agent or operator message.
The body is UTF-8 text up to 32768 bytes. Terminal control sequences are rejected.

For a locally generated alert belonging to the caller:

```sh
printf '%s\n' 'Renewal completed' | service-alerts send caddy
```

Delivery requires a running, marked agent pane. Failures return nonzero. There is
no offline queue or automatic retry: a paste/Enter failure can have delivered part
of the notification. Watchdogs should record failures rather than blindly retry
an uncertain delivery. High-frequency checks should normally alert on state
transitions or use their own repeat interval.

## Shared Debian packages

The separate `packages` grant permits system-wide APT installs from the host's
operator-configured repositories. Installed command-line tools are available to
all agents; project-local npm/pip environments remain project-managed.

```sh
agent-admin grant jarvis packages       # operator only
agent-admin revoke jarvis packages      # operator only

host-admin packages search imagemagick
host-admin packages show imagemagick
host-admin packages refresh
host-admin packages install imagemagick poppler-utils
host-admin packages status
host-admin packages status JOB_ID
```

`refresh` updates repository indexes, not installed packages. `install` accepts
up to 32 exact package names, installs necessary dependencies without recommended
extras, and refuses package removals. Already-installed requested packages are
not upgraded; APT may update dependencies needed for a new package. Use the
operator's `full-update` workflow for general maintenance and shared AI runtimes.
No local .deb files, URLs, version/release selectors, repository/key changes,
arbitrary APT options, purge, autoremove, or shell commands are accepted.

This is a trusted administrative capability: repository packages run their normal
root installation scripts and can add services. The worker cannot access agent
homes. Existing configuration files are retained on package conffile conflicts;
the tool does not grant an agent a root shell or access to peer homes.

Install/refresh return a job ID immediately. One job runs at a time, separately
from the alert broker, with the shared maintenance lock and APT's package locks.
Use `status` to check completion at a suitable boundary; a queued job is not a
successful install. Requests are not automatically retried after failure or an
interruption. Status distinguishes queued/running/succeeded/failed/interrupted.
An interrupted transaction may require operator repair of APT/dpkg state. The
worker has a 20-minute limit and retains the latest 20 job receipts. Detailed APT
output is not returned through the broker; normal APT/dpkg logs remain on the host.

No package grants are added automatically. Grants are checked on submission and
again when the worker starts. Revocation does not kill an installation already
in progress. Existing `all` grants are stored as explicit capabilities, so an
older grant does not silently gain `packages`; grant it explicitly.

## Global SMB mounts

After the operator grants `smb`:

```sh
host-admin smb add nexus //10.25.25.25/smb-share/Nexus
host-admin smb show
host-admin smb unmount nexus
host-admin smb mount nexus
host-admin smb remove nexus
```

Add prompts for SMB username, hidden password, and optional domain. Credentials
go directly to a root-only file through the local socket; never put a password
in argv, tickets, chat, source files or logs. Authentication remains subject to
the SMB server's permissions. The tool does not change the remote server.

Every mount is global at `/mnt/<name>` and readable/writable by `freq-agents`.
No alternate path, private mount, mount inside a home, or arbitrary mount option
is accepted. Names `c`, `wsl`, and `wslg` are reserved. Mounts use SMB 3.0 with
`noexec,nosuid,nodev`; credentials stay under `/etc/freq-ai-setup/host-admin/private`.
Mounts persist through reboot using systemd mount units. A failed initial mount
retains configuration for diagnosis and a later `mount` attempt. Existing paths
are never silently adopted. Removal unmounts the share and archives its unit and
credentials; it never deletes remote data.

The sandbox grants non-executable shared access beneath `/mnt`. Existing sessions
must be restarted once after this sandbox upgrade; there is no live relaxation
of an already-running Landlock sandbox. Agent homes remain private. Container
workers retain their separate existing filesystem policy; this change provides
global agent-shell access, not automatic volume injection into containers.

## Host diagnostics, network and services

```sh
host-admin status
host-admin network show
host-admin network interfaces
host-admin network edit
host-admin network route-add lab 10.50.0.0/24 10.25.255.1 ens18
host-admin network confirm TOKEN
host-admin network route-remove lab
host-admin services show
host-admin services status systemd-timesyncd.service
host-admin services restart systemd-timesyncd.service
```

`network edit` opens a private copy of `/etc/network/interfaces` in nano. Saving
submits the edited file to the broker, which checks it against the original hash,
validates it, preserves the original, updates the real file, and applies changed
interfaces. The same caller must confirm within 120 seconds after checking
connectivity. Otherwise a separate systemd timer restores and reapplies the
original. An early-boot recovery service restores unconfirmed edits before
networking starts after an unexpected reboot. No agent receives direct write
access to the root configuration file.

Supported settings include IPv4/IPv6 addresses, gateways, DHCP/static/manual
methods, MTU, metrics, DNS directives, bridge/VLAN settings and validated `ip route`
hooks. DNS directives use the host's existing ifupdown DNS integration. Arbitrary
shell hooks, includes outside `/etc/network/interfaces.d`, changes to loopback,
and unsupported directives are rejected with a line number. Existing custom
configuration using unsupported hooks requires operator review. Interface apply
and rollback can interrupt connectivity; a saved file alone is not proof that
the desired connectivity works. The confirmation step requires a successful apply.
Edits to other files, firewall rules and arbitrary root commands are not exposed.

The separate `route-add`/`route-remove` commands manage additional IPv4 routes,
also with the 120-second confirmation window. They never replace an existing
destination or remove a route they did not create. Confirmed routes are restored
at boot and use protocol 186 and metric 42700. Default routes can instead be
configured through the validated interfaces-file editor.

Service authority is limited to status/restart of `cron.service`,
`rsyslog.service`, and `systemd-timesyncd.service` when installed. It cannot edit
units, install root scripts, restart agent sessions, or change security services.
Diagnostics provide filesystem space, interface addresses and failed-unit names.

Broker audit entries record authenticated UID, operation and result, without
message bodies, credentials, public keys or full request dumps:
`journalctl -u freq-host-admin.service`. This service uses `ProtectHome=tmpfs`
with only shared projects bound read-only; private homes remain hidden;
alert delivery also drops to the recipient UID before accessing agent-writable
comms paths. SSH source authentication and local source ownership are enforced
by the broker, independently of client command names.
