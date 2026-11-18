# FREQ-AI-SETUP integration

`freq_discord_core.py` and `freq_discord_bot.py` provide the SMB release's
ordinary-message, picture, reaction, and embed interface. `connector.py` runs
that interface under the existing `freq-discord.service`, preserving configured
paths, credentials, singleton locking, strict outbox validation, and the durable
attempted/posted journal. Uncertain outgoing posts are held, not blindly retried.

Reply colors are read from the identity files created by `create-agent`, on
each post. No separate Discord color configuration is needed.

Messaging uses `agent-name message`, with optional pictures. `/agents`, `/start`,
and `/stop` are operator-only lifecycle controls, not messaging commands.
Autocomplete filters by current state; execution rechecks state. Registration
preserves unrelated Discord commands and retires only the old FREQ `/msg`.

The unprivileged connector calls a local Unix socket owned by root:freq-discord.
The root worker checks the peer UID, allows only list/start/stop for registered
agents, and executes the master's existing lifecycle scripts as the master.
It accepts no shell commands, arbitrary paths, or additional arguments. The
worker's lifecycle must not terminate agent tmux servers started through it.

`setup-discord` prepares both services; `create-agent` and `setup-coms` create
media directories. `level-set` removes generated services and state. The
standalone `freq-ai-setup` contains these sources. Do not run the upstream
standalone installer alongside this integration: it uses another service name
and different configuration paths.
