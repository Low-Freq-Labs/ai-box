---
name: board-admin
description: "Inspect board integrity and reconcile interrupted board transactions using a granted board-maintenance scope. Use for NOT_PREPARED or PREPARED operations, not normal task assignment or acceptance."
---

# Inspect and reconcile the board

Use the installed `board-admin`; do not edit task files or journals manually.
The broker authenticates your Linux UID and checks the current revocable grant.
For Jarvis, the current standing approval reference is `jarvis-maintenance-20261005`.

```sh
board-admin validate PVE-FREQ --json --cursor 0 --limit 25
board-admin operation-status PVE-FREQ OPERATION_UUID --json
board-admin reconcile plan PVE-FREQ OPERATION_UUID
board-admin reconcile apply PLAN_UUID --expect-plan-sha256 PLAN_SHA256 --approval jarvis-maintenance-20261005
```

Follow `next_cursor` until null for a complete census. `complete`, `error_count`
and `pending_count` describe the whole project; each response contains a bounded
page. Keep valid work visible while reporting corrupt entries.

Review the plan's exact operation, revision and effect before applying. Within
the standing scope, proceed without asking Sonny again. A stale plan requires a
fresh inspection and plan, not a forced write.

- `CLOSE_UNPREPARED` records a terminal abort marker and preserves every journal
  image. It leaves the original task untouched and does not reuse the old ID.
- `FINISH_PREPARED` finishes the already-recorded transaction; it does not invent
  a new assignment, completion or acceptance.
- `COMMITTED` ownership with `UNCERTAIN` notification is not permission to rerun
  the task command. Inspect comms receipts when available. Board alerts without
  delivery evidence retain their uncertainty; do not blindly resend them.

The worker runs as your UID, not root. Root protects the plan and audit records.
This command does not offer arbitrary task-content rewriting. A malformed
reason that needs new owner wording requires a separately reviewed repair.
After reconciliation, check operation status and revalidate the project.
