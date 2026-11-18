# Update an existing agent

Operator-only command, installed in the configured operator's tools directory:

```sh
update-agent
update-agent rick
update-agent morty --show
```

The interactive command asks which agent if omitted, then asks about **color** and
**runtime**, one at a time. Enter keeps the current value. It shows the exact files
to update and asks for confirmation. It never stops or restarts an agent for you.
The agent must be fully stopped, including other SSH/shell/container processes,
before any change. Read-only `--show` and `--dry-run` work while it is running.

Colors: red, orange, yellow, green, blue, purple, pink, toxic-green, or #RRGGBB.
Color updates change only the registered color, shell identity color values and
tmux's agent-color option. Shared NEXUS branding and custom tmux settings remain.
The next agent start and new shells pick up the new color.

Runtime can switch between codex and claude. The tool updates registry/identity
and existing start/connect/stop launchers. It copies current instructions into
the selected runtime's AGENTS.md or CLAUDE.md and the operator's matching copy,
backing up any earlier destination version. Missing target skills are installed;
existing target skills are preserved. Role/team text is carried as-is.

Both runtimes' existing configs, authentication and conversation histories stay
in their own directories. History is retained, not converted between products.
The target runtime and its pre-provisioned config must exist and parse correctly.
If it has not been authenticated, connect after the next start and sign in.
Startup briefing delivery can report that the runtime needs onboarding first.

Groups, host grants, Linux account name/UID, homes, projects and credentials are
not changed. Use agent-groups and agent-admin for their respective settings.

For explicit commands, preview first and apply once the agent is stopped:

```sh
update-agent rick --color purple --dry-run
update-agent rick --color purple --yes
update-agent morty --color toxic-green --yes
update-agent rick --runtime claude --dry-run
update-agent rick --runtime claude --yes
```

`--yes` skips only the final confirmation; it cannot bypass the stopped check.
Backups and manifests, including original hashes and ownership, are kept under
`/var/backups/freq-agent-updates/`. Handled write failures restore changed files
when they still match this operation's output. Retain backups for operator recovery.
