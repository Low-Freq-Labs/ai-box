---
name: dev-drain
description: "Permanently clear the current agent's already-read messages only when the operator explicitly requests draining communications or deleting read-message history. A general session wrap-up or inbox check does not authorize deletion."
---

# Drain read messages on explicit request

Only after an explicit drain/history-deletion request and preserving important
state in the handoff, run exactly:

```bash
dev-drain
```

Follow these rules:

- A general "wrap up" request is not a drain request.
- Pass no arguments.
- Understand that the command permanently deletes generated messages from the
  current agent's `read/` directory.
- Trust that it never deletes unread messages from `inbox/`.
- Report the exact drained count.
- If it fails, report the exact `DRAIN FAILED` message. Do not manually delete
  files or retry destructively.
