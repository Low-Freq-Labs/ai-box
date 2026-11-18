---
name: dev-msg-status
description: "Inspect a message's durable receipt and delivery state by the MESSAGE-ID returned by dev-msg, without reading or deleting inbox messages."
---

# Inspect message delivery

```sh
dev-msg-status MESSAGE_UUID --json
```

Use the stable `MESSAGE-ID` printed by `dev-msg`. The broker permits participant
status access; a granted comms administrator uses `coms-admin` for maintenance.
Receipts contain metadata rather than message bodies. They do not mark messages
read, delete history, or retry delivery.

Distinguish `NOT_STORED`, `DURABLY_STORED`, `NOTIFICATION_PENDING`,
`NOTIFIED_TO_PANE`, `DISCORD_QUEUED`, `DISCORD_POSTED` and uncertain states.
Only a confirmed Discord acknowledgment supports a posted claim; it does not
prove human reading. Old messages without UUID receipts require the administrator's
legacy outbox-filename lookup. Never invent a receipt or retry an ambiguous send.
