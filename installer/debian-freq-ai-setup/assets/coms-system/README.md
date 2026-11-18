# Minimal agent communications

The communications system has five agent-facing commands.

```text
dev-msg <recipient> <message-title> <full-message>
```

The sender is always the effective Linux account returned by `/usr/bin/id
-un`. It cannot be supplied or overridden by the caller.

Agents use the same command to reply to Sonny through the Discord connector:

```text
dev-msg sonny <message-title> <full-message>
```

That reserved recipient writes one atomic JSON record to
`/var/lib/freq-agents/discord/outbox/` and performs no tmux operation. `SENT`
means the reply is safely in the connector outbox; it does not claim Discord
has posted it yet.

For recipient `jarvis`, delivery uses this fixed FREQ-AI-SETUP contract:

```text
socket:  /run/freq-agents/tmux/agent-jarvis
session: jarvis
window:  agent
pane:    exactly one live pane with @freq_delivery_pane=1
```

The socket is owned by the recipient with group `freq-agents` and mode `0660`.
On tmux 3.5a, filesystem permission is necessary but not sufficient: tmux also
enforces a per-server user ACL. `agent-start` must grant every peer agent write
access on each server, for example on Jarvis's server:

```text
tmux -S /run/freq-agents/tmux/agent-jarvis server-access -a finn
tmux -S /run/freq-agents/tmux/agent-jarvis server-access -w finn
tmux -S /run/freq-agents/tmux/agent-jarvis server-access -a clancy
tmux -S /run/freq-agents/tmux/agent-jarvis server-access -w clancy
```

`server-access -l` must show all trusted agent users with `(W)`. Without this,
cross-user clients receive `access not allowed` even when the socket is `0660`.

The complete full message is written verbatim to one `.md` file under:

```text
/var/lib/freq-agents/coms/<recipient>/inbox/
```

The plain title must be one line and at most 160 characters. `dev-msg` adds the
outer brackets. Only this notification is injected:

```text
SENDER-MSG: [MESSAGE TITLE]
  — sent at 8:45 PM CDT
  — from sender · team coms (not sonny.aif)
  → dev-read <exact-message-file>.md
```

The timestamp uses `America/Chicago` and automatically renders CST or CDT. The
notification is capped at 512 bytes; the full message never enters the pane.

The single Discord bot runs as the dedicated Linux account `freq-discord` and
uses a private two-argument ingress form:

```text
dev-msg <recipient> <full-message>
```

Only that effective Linux account may use the form. It creates a message file
whose sender is `sonny` and injects exactly:

```text
SONNY-MSG:
  — sent at 8:45 PM CDT
  — from Sonny · Discord
  → dev-read <exact-message-file>.md
```

There is no generated title, bracket pair, preview, or full message in the
pane. Other Linux accounts receive the normal three-argument usage error if
they attempt the private form.

The command loads that exact payload into a uniquely named tmux buffer, pastes
it into the exact pane with tmux's bracketed, literal-newline paste flags, and
then invokes two separate `send-keys ... Enter` operations. This prevents the
four notification lines from behaving like four Enter presses. Neither Enter
is stored in the buffer, batched with the paste, or batched with the other.

Zero or multiple matching panes fail closed. A paste failure sends neither
Enter. After a successful paste, both Enter calls are always attempted even if
one fails. Deliveries to one recipient are serialized to prevent two callers
from interleaving their paste and Enter operations.

There are only two outcomes. If storing the message and all five tmux operations succeed, the command prints
`SENT` and exits zero. Otherwise it exits nonzero and stderr identifies the
exact failed operation as `STORE FAILED`, `TARGET FAILED`, `LOAD FAILED`,
`PASTE FAILED`, or `ENTER FAILED`. It does not distinguish which Enter failed,
create delivery-state files,
inspect the pane after Enter, retry, or infer additional state.

Run the source tests with:

```text
python3 -m unittest discover -s tests -v
```

## Reading

```text
dev-read <exact-message-file>.md
```

The reader is always `/usr/bin/id -un`; no agent argument or identity override
exists. On first read, the exact regular `.md` file is moved before printing:

```text
/var/lib/freq-agents/coms/<reader>/inbox/<file>.md
→ /var/lib/freq-agents/coms/<reader>/read/<file>.md
```

The moved file is then printed verbatim. If the exact file is already in
`read/`, it is printed again without another state change. If it exists in both
locations, is not a regular file, or does not exist, `dev-read` fails rather
than guessing.

## Inbox

```text
dev-inbox
```

The agent is always `/usr/bin/id -un`. The command lists the exact regular
message filenames in that agent's `inbox/` oldest-to-newest and prints the
unread count. It takes no arguments and changes nothing. It does not inspect
`read/`, classify urgency, group messages, select a preferred message, or mark
anything read.

## Wrap-up drain

```text
dev-drain
```

The agent is always `/usr/bin/id -un`. The command permanently unlinks only
that agent's exact generated regular `.md` files from `read/` and reports the
count. It never touches `inbox/`, uses no recursive deletion, and has no timer
or automatic trigger. Agents run it explicitly during wrap-up after current
messages have been read and their important state has been handed off.

## Team discovery

```text
agent-team
```

The command lists each valid direct agent directory under the communications
root and counts that agent's exact unread inbox message files. It marks the
current Linux agent with `(you)`. It reads no message contents, changes
nothing, and makes no claim about runtime, usage, availability, or processing.

## Fixed production contract

Production paths and executables are fixed in the commands; there is no runtime
configuration interface. Isolated source tests may override paths and the tmux
binary only when `FREQ_COMS_TESTING=1`. Without that explicit test flag, all
override environment variables are ignored.

## Agent skills

Each command has one separate, obvious-use skill package:

```text
skills/dev-msg/      Send a message to another agent
skills/dev-inbox/    List the current agent's unread messages
skills/dev-read/     Read one exact message file
skills/dev-drain/    Clear read messages during explicit wrap-up
skills/agent-team/   Discover team agents and unread inbox counts
```

Each package contains a concise `SKILL.md` and matching `agents/openai.yaml`.

## Discord bridge boundary

The Discord-facing implementation contract is documented in
`../discord-connector/README.md`. It uses one bot for the whole roster. The bot
is not an agent and neither `freq-discord` nor Sonny appears in `agent-team`.
