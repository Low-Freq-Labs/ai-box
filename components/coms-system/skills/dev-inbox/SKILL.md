---
name: dev-inbox
description: "List the current agent's unread development messages. Use this skill whenever an agent needs to check its inbox, see unread messages, find messages that arrived while it was away or out of usage, or determine which exact message filenames are waiting to be read."
---

# List unread development messages

Run exactly:

```bash
dev-inbox
```

The command derives the agent from the Linux account and lists unread message
filenames oldest-to-newest.

Follow these rules:

- Pass no arguments.
- Treat the displayed unread count and filenames as the inbox truth.
- Use `dev-read <exact-filename>.md` to open a listed message.
- Do not manually inspect, move, classify, group, or mutate inbox files.
- Do not infer that listing a message marks it read; `dev-inbox` changes nothing.
- Pane notifications normally make polling unnecessary. One recovery check is
  allowed after reconnecting, returning from an interruption, or when a missed
  notification is reasonably suspected. Do not repeatedly poll for replies.
- Explicit session wrap-up permits one inbox check at the start and one at the
  final safe boundary. These finite snapshots are not polling; do not wait for replies.
