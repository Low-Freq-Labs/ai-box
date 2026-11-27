# Portable Debian 13 FREQ-AI-SETUP

Copy the self-contained `freq-ai-setup` file to a fresh Debian 13 amd64 host
running systemd, then run it as root:

```bash
sudo bash freq-ai-setup
```

Installation needs at least 8 GiB free on `/` and outbound access to the configured
Debian repositories plus HTTPS to Node.js, npm, GitHub releases, PyPI, and
Playwright's browser download endpoints. AI runtime downloads are also included.

The installer includes `service-alerts` for service-origin SSH notifications and
operator-only `agent-admin` grants for bounded host management. Granted agents use
`host-admin` for global SMB mounts under `/mnt/<name>`, diagnostics, approved
service restarts, and validated nano editing of `/etc/network/interfaces` with
automatic rollback. No host capabilities are granted automatically. The installed
guide is `/usr/local/share/freq-ai-setup/host-admin.md`.

Scoped maintenance also provides `board-admin`, `coms-admin`, `storage-budget`,
and `host-admin tooling`. `storage-run` supervises opt-in finite case plans and
records durable receipts; it is not a sandbox or disk quota. A root-owned timer
maintains emergency filesystem capacity and reports transitions to the system
journal. See `/usr/local/share/freq-ai-setup/storage-run.md` for limits and
recovery rules. No personal alert routing or production grants are copied.

The adjacent distribution `README.txt` identifies the release, SHA256, tested
behavior and remaining qualification limits. This is a fresh-machine installer;
do not run it over production just to synchronize individual components. The public source and build instructions are in the AI-Box repository.

The interactive installer asks for:

- the master Linux username;
- whether to create that account when it is absent;
- the operator display name used in agent contracts (defaults to the master username);
- the terminal/tmux host label; and
- an optional pasted master SSH public key or public-key file path;
- an optional updated `coms-system` source folder; and
- whether to configure your existing Discord bot.

Discord setup asks for your user ID, server ID, channel ID, and a hidden bot
token. You can configure it later with `setup-discord`, or change existing IDs
and the hidden token with `update-discord` (Enter keeps existing values; confirm
to apply and briefly restart the connector, without stopping agents). One bot serves all
agents through ordinary messages: `agent-name your message` (pictures optional).
Enable Message Content Intent for the bot. Agents reply with `dev-msg sonny ...`;
reply embeds use the agent color selected in `create-agent`.
Agent colors: red, orange, yellow, green, blue, purple, pink, or any `#RRGGBB`
hex color. Hex colors use exact RGB in the terminal, tmux, and Discord, with
a nearest xterm-256 fallback when truecolor is unavailable.
`/agents` lists running/stopped agents; `/start` suggests stopped agents and
`/stop` suggests running agents. Only the configured operator in the configured
server/channel may use these commands. They call the existing lifecycle scripts
through a restricted local endpoint; the Discord bot is not given sudo access.
The service runs as `freq-discord`, separate from agent accounts. Tokens are
root-owned credentials and are not bundled in the portable installer.

Failed or uncertain outbound posts remain in the outbox and are not retried
automatically. `OUTBOX_HELD` in `journalctl -u freq-discord` identifies the file.
Check the channel before manually recovering a held reply to avoid duplicates.
`level-set` leaves the Discord connector and its configuration intact.

Press Enter through the prompts for the recommended standard layout. Advanced
mode exposes the safe coms, board, and tmux paths. Durable projects always use
`/home/freq-agents/projects`.

It then installs the Debian development baseline, shared Node/npm/Codex/Claude
toolchain, prompt and tmux identity, agent isolation, lifecycle tools,
communications system, board system, shared projects/staging layout, and
acceptance tests. It creates no agents automatically.

Mosh server support is included. The installer opens UDP 60000-61000 when UFW
or firewalld is active. It reports custom nftables and upstream firewall work
instead of rewriting those policies blindly.

For unattended provisioning, provide the identity explicitly:

```bash
sudo bash freq-ai-setup \
  --master-user operator \
  --operator-name Operator \
  --host-label AI-BOX \
  --create-master \
  --yes
```

An unattended newly created account remains password-locked unless an SSH
public key is supplied. New installations never inherit the original deployment’s fleet SSH key. An explicitly supplied operator public key becomes the new fleet public key; without it, new agent SSH authorized-key files start empty. Existing safe fleet keys are preserved during a rerun. Do not put passwords on the command line. Interactive
creation offers to run `passwd` without recording the password.

Installed identity is stored in root-owned `/etc/freq-ai-setup/site.conf`.
The exact source hashes are recorded in
`/etc/freq-ai-setup/source-manifest.sha256`, and the non-secret install summary
is stored in `/etc/freq-ai-setup/install-receipt`.

## Developer tools

One canonical package directory drives initial setup and baseline repair:
`/usr/local/share/freq-ai-setup/devtools/packages`.
`apt-base.txt` contains OS tools; `apt-browser.txt` contains the native libraries
for the bundled Playwright release. No Docker daemon or database server is added.

Standalone tools use upstream release checksums. Release selection accepts an
upstream wheel whose compressed compatibility tags are reordered, while requiring
the same distribution/version, Python tags, ABI tags and platform tags. Missing
checksums, ambiguous matching assets and incompatible tags still stop the plan.
Semgrep and fonttools each have
their own hashed Python environment. Browser QA has one npm lockfile and its
matching Chromium, Firefox, and WebKit builds. Managed releases live in
`/opt/freq-agents/devtools`; commands in `/usr/local/bin` are shared by all users.
Users cannot mutate those root-owned releases. Only the current and immediately
previous managed release are retained.

Run `full-update` for shared maintenance, or `full-update --check` to inspect tool
candidates without applying them. Stop agents before applying updates. The command
previews Debian package/kernel changes and managed tool versions, asks for approval,
and verifies the result. It never reboots automatically; its final output explicitly
reports a required reboot, no detected requirement, or an inconclusive check.

Node stays within its supported LTS major; npm and developer tools stay within
their compatible major (minor for 0.x tools). Incompatible releases are held for
review. Codex and Claude use their official latest channels. Shared Python and
browser QA dependencies are re-resolved, audited, hash-locked, and functionally
tested as an unprivileged user before the candidate developer release is selected.
No project dependencies, local venvs, repositories, container images, credentials,
coms/board/Discord application code, skills, or policies are updated by this command.
APT package removals, automatic autoremove, and Debian-release migrations are excluded.
APT and npm updates are not one atomic transaction: a later failure may leave earlier
phases updated, and is reported as incomplete rather than rolled back silently.

Semgrep dependency compatibility is qualified for one exact scanner version.
The current local policy covers 1.186.0 with MCP 1.30.0 and the matching
OpenTelemetry 1.45.2/0.66b2 packages. Vendor scanner code stays unchanged.
The full resolved graph still passes the security scan, and every dependency
outside those six explicit packaging exceptions must satisfy its declared range.
Offline checks exercise the real MCP server and telemetry with a fixture issuer;
they do not establish live issuer or hosted-service acceptance. A future scanner
version does not inherit this policy without new qualification.

Projects still create their own `.venv` or `package.json` under
`/home/freq-agents/projects/<project>/`. Never install project dependencies into
the shared tool environments. Shared QA libraries are available at
`/opt/freq-agents/devtools/current/webqa/node_modules`; projects needing a different
version should declare their own dependencies. The global `playwright` and
`lighthouse` commands select the shared matching browsers without changing
project-level browser cache settings.

The operator's `~/tools` contains `create-agent`, `delete-agent`, `full-update`,
`level-set`, `update-shared-git`, `update-discord`, `update-ssh-key`, and `agent-groups`.

`agent-groups` is operator-only; agents retain their existing `agent-team` roster
command. Create a Discord delivery group with `agent-groups create pve-freq`,
assign with `agent-groups finn pve-freq`, inspect with `agent-groups show`, and
remove membership with `agent-groups finn remove pve-freq`. Agents can belong to
multiple groups. Use lowercase names with hyphens, such as `pve-freq-devs`; names
cannot collide with agents or command words. Up to 100 groups and 32 members per
group are supported. Membership survives reboot; deleting an agent removes its
memberships, while empty groups remain. Agent recreation does not restore old
memberships.

In the configured Discord channel, send `pve-freq your message` to all current
members, or `finn your message` to one agent. Each group recipient sees the group
name and addressed members, and receives its own accessible picture paths.
Membership is read once per message. Delivery continues to other members after
a failure and reports the delivered and failed/uncertain members. A successful
delivery means input was sent to the session, not that the agent read or acted on
it. Stopped agents are not automatically started, and uncertain deliveries are
not automatically retried. Group messages do not assign duplicate board tasks;
agents coordinate through existing task ownership. Replies keep agent identities
and colors. No Discord configuration or bot restart is needed for membership edits.
`update-ssh-key` accepts a pasted public key for the configured master, preserves
existing keys, and asks for confirmation. Test from a second terminal with the
matching private key before closing your current session.
`setup-discord` is shown
only until Discord is configured. Setup and
repair helpers remain in `/usr/local/libexec/freq-ai-setup/`, outside the daily menu.

`level-set` is an agent-only wipe, not a machine reset. After exact confirmation,
it stops agents, removes their accounts/homes/coms/launchers, and archives staging
under `/home/freq-agents/staging/archive/<timestamp>/<agent>/`. Archives are verified
copies and never overwrite an earlier archive. Projects, board history, installed
tools, and Discord configuration survive. Owned active tasks return to ready with
an agent-removal history entry; existing blockers remain blocked. `delete-agent`
uses the same archival and board-retirement behavior for one selected agent.

Agents use ordinary `podman`, `buildah`, and `bwrap` commands through a private,
rootless execution service. The operator keeps the native commands. Run agent
container commands from the agent's home, shared projects, or its staging lane;
those are the paths shared with the service. Host-private homes, credentials,
service sockets, and processes are not exposed. Host-PID and privileged-container
modes are unsupported; installing tools never grants agent sudo or host root.

Each service has four concurrent foreground jobs, a one-hour job deadline,
64 MiB stdin/output limits per job, and an 8 GiB/4-CPU/2048-task service limit.
Interactive terminals are supported. Detached containers remain until explicitly
stopped or the agent is stopped; stopping an agent kills its entire container
service. Images and volumes live in its private home and survive service stops,
but are removed by agent deletion or `level-set`. Durable output belongs in a
bind-mounted shared project, not a container's writable layer.
The command bridge forwards stdin like SSH; use `</dev/null` in input-reading
shell loops when the container command should not consume that input.

`create-agent` verifies developer tools and offline container builds/runs through
the actual agent boundary before reporting success. Packet capture, cross-process
debugging, privileged mounts, credentials, and external services remain subject
to their own permissions and are not implied by tool installation.

Agents refresh session-state at meaningful checkpoints as well as full wrap-up.
After an agent has a valid saved current session-state, each new start
sends `STARTUP-MSG` through coms after the runtime input
prompt is ready. The message points to `dev-read` and visibly requests a Discord
natural, concise briefing (no mandatory headings or empty sections). Its full instructions live in the installed
`agent-startup-message.md`, not in another long agent-contract section. Connect
and already-running starts do not resend it. The agent verifies its latest
session-state and current project/board state, recommends priorities, then asks
the operator before proceeding. Without a current saved record, startup skips
the briefing successfully: no notification, inbox file, or readiness wait.
Empty init directories and archived records do not enable startup briefings.

First-run login/trust screens are not message inputs. If readiness is not detected
within 12 seconds, start leaves the runtime running and reports `STARTUP_NOT_SENT`.
Connect to finish onboarding, then stop/start when safe. Delivery is never blindly
retried after a possible partial send. Readiness adapters currently recognize the
Codex and Claude input prompts; a changed runtime UI may require an adapter update.


## Current board and scheduling integration

The bundle includes `project-assess`, `task-update`, `agent-skills`, board migration and pause support, and the matching libraries and skills. New and existing agents receive their own mode0700 prerequisite-assessment receipt directory. Rerunning board setup preserves custom role and authority contracts.

The existing prerequisite guard is installed as a root-managed Codex Stop hook. The installer preserves unrelated requirements and existing guard policy; it refuses an explicitly disabled hook feature or incompatible managed directory rather than replacing an administrator’s policy. Existing sessions need their owner to reload the managed configuration. This is a cooperative stopping check, not task completion or an authorization mechanism. See the [official Codex hook documentation](https://learn.chatgpt.com/docs/hooks).

`agent-crontab` uses the existing broker and authenticated peer UID to manage only that registered non-root caller’s own table. It requires a current fingerprint for writes and native syntax validation. It grants no target-user or Root operation. Installation does not create scheduled jobs. The standard `cron` package supplies the native scheduler. See `/usr/local/share/freq-ai-setup/agent-crontab.md`.

The portable capacity reserve reports through the journal. Personal alert routes, live grants, enrolled remote endpoints, credentials and unrestricted Root authorization are not copied from the source machine. Optional vm-admin enrollment remains a separate explicit operator action.

## Build the self-contained installer

From a checkout, without Root:

```bash
python3 installer/build-installer.py /absolute/path/outside-the-source/freq-ai-setup
```

The builder refuses to overwrite an existing output and emits a sibling `.sha256` file. The embedded source manifest is checked before the bootstrap runs. `bash freq-ai-setup --help` works without Root; actual installation still requires Root on Debian13 amd64 with systemd. Use a clean target, preserve its recovery backup, and check the release qualification report before installation.
