# One-bot Discord connector

One Discord bot connects Sonny to every agent in the communications roster.
There is no bot, webhook, channel, or Discord identity per agent.

## Sonny to an agent

In the dedicated agent channel, send a normal Discord message whose first word
is the agent name:

```text
jarvis hey, compare these screenshots
```

The name is case-insensitive and may end in `:` or `,`. Everything after it is
the full message. Paste zero to ten pictures into that same Discord message and
send once. A picture-only message is valid when it still begins with the agent
name. There is no slash command, title field, modal, or required bot mention.

Only messages matching all three configured IDs are processed:

- Sonny's Discord user ID
- guild ID
- channel ID

All other messages are ignored, including bot-authored messages. Because the
bot reads unmentioned messages in one dedicated guild channel, enable the
Message Content intent in the Discord Developer Portal.

The current roster is discovered from valid direct directories under
`/var/lib/freq-agents/coms/`. `sonny` and `freq-discord` are never roster
agents. An unknown first word receives a precise error card and no host effect.

Accepted attachments include PNG, JPEG, WebP and GIF (original animation kept),
UTF-8 Markdown/text/logs, CSV/TSV, JSON/JSONL, YAML/TOML/INI/config, XML/HTML/SVG,
common source-code files, diffs/patches, SRT/VTT captions, PDF and ZIP.
Limits: ten files, 10 MiB per file, 50 MiB combined. ZIPs are stored without
extraction; code/documents are not executed or rendered by the connector.
Text must be UTF-8; binary data renamed to a text extension is rejected.
Discord MIME labels are not authoritative; supported content is checked locally.
Pasted links/GIF-picker embeds are not downloaded automatically: upload the GIF
as a file to send its bytes. Audio/video clips and Office formats are not yet
supported; a ZIP can carry a complete project with original names and structure.

The connector
downloads and validates the complete batch before publishing any of it. It
ignores supplied filenames and writes safe generated names under:

```text
/var/lib/freq-agents/coms/<recipient>/media/<discord-message-id>/
```

The body delivered to the agent contains Sonny's text followed by every exact
local picture path. The connector then executes without a shell:

```text
/usr/local/bin/dev-msg <recipient> <complete-body>
```

That private two-argument form is available only to Linux account
`freq-discord`. It writes one `*_sonny.md` inbox message and injects only:

```text
SONNY-MSG:
  — sent at 6:42 PM CDT
  — from Sonny · Discord
  → dev-read <exact-message-file>.md
```

Successful delivery adds `✅` to Sonny's Discord message. Failure adds `🚫`
and replies with one red embed naming the exact failed stage. The connector
does not automatically retry an inbound message.

## Agent replies

Agents use their existing command:

```text
dev-msg sonny <message-title> <full-message>
```

It atomically creates one mode-0660 JSON record in:

```text
/var/lib/freq-agents/discord/outbox/
```

The exact schema is:

```json
{"schema":1,"sender":"chris","title":"UPDATE","message":"Full reply."}
```

The connector accepts only exact regular `.json` files with mode `0660`,
schema `1`, nonempty string fields, and a current roster sender matching both
the filename suffix and Linux file owner. Outbox values are never executed or
interpolated.

Each valid reply is posted as a Discord embed:

```text
CHRIS-MSG: [UPDATE]

Full reply.
```

The embed's color is the sender's configured agent color. Unconfigured agents
receive a stable deterministic color. Discord mention expansion is disabled.
Replies longer than one embed description are attached as Markdown. The
outbox record is deleted only after Discord confirms the post; failures remain
visible for recovery. Only one connector process may own the outbox.

## Discord application permissions

Bot permissions in the dedicated channel:

- View Channel
- Send Messages
- Read Message History
- Add Reactions
- Attach Files
- Embed Links

Enable the privileged Message Content intent on the application's Bot page.
No slash command needs to be registered.

## FREQ-AI-SETUP installation

First run the base installer with the complete agent roster. It installs the
connector source, unit, pinned dependency requirement, per-agent media
directories, and the existing communications/board system. It deliberately
does not start the bot without credentials:

```text
sudo ./install-freq-ai-setup finn jarvis clancy
```

Create a configuration from `discord.example.json`. Keep Discord IDs as quoted
decimal strings and set optional `agent_colors` values to `#RRGGBB`. Put the
bot token alone in a separate root-readable file, then run:

```text
sudo /usr/local/sbin/freq-discord-setup /path/discord.json /path/discord-token
```

The setup command:

- creates or validates the unprivileged `freq-discord` service account;
- adds it to `freq-agents`;
- grants it tmux server write access on every current agent socket;
- copies the config as `0640` and token as root-only `0600`;
- creates a private virtual environment and installs `discord.py==2.7.1`;
- enables and starts `freq-discord-connector.service`; and
- fails visibly if the service does not become active.

The bot token is loaded through a systemd credential and is never placed in
the unit or command line. The service runs as `freq-discord`, uses one runtime
singleton lock, and has no access to agent home directories.

## Source verification

Run:

```text
python3 -m unittest discover -s discord-connector/tests -v
python3 -m unittest discover -s coms-system/tests -v
python3 -m unittest discover -s board-system/tests -v
python3 -m unittest discover -s tests -v
```

Network delivery can only be accepted on FREQ-AI-SETUP after the real token,
Discord IDs, channel permissions, Message Content intent, agent sockets, and
tmux ACLs exist.
