---
name: project-assign
description: "Join or leave a board project as the current Linux agent. Use this skill whenever an agent starts or resumes work on a project, assigns itself to a project, stops working on a project, becomes inactive on a project, or is told by BOARD-ALERT to set its project assignment inactive."
---

# Change project assignment

Run exactly one form:

```text
project-assign <project-id> active
project-assign <project-id> inactive
project-assign <project-id> paused
```

Follow these rules:

- Use `active` when starting or resuming work on the project.
- Direct task assignment and transfer already activate the recipient on that
  project; do not add a redundant `project-assign active` call afterward.
- Before using `inactive`, create a current prerequisite assessment with `project-assess <project-id> --template` and `--submit /absolute/assessment.json`; see the project-assess skill. Missing, stale, incomplete or expired assessments are refused. Then, run `project-status <project-id>` and confirm no
  actionable work remains. The command refuses to abandon owned active tasks.
- Pass no agent name. The effective Linux account is always the agent.
- Treat `ASSIGNMENT: <agent> -> active/<project-id>` or `inactive/<project-id>`
  with exit zero as assignment truth. An `already` result is also successful.
- If it fails, report the exact `ASSIGNMENT FAILED` message.
- Do not manually create or remove `active/<agent>/` directories.

## Explicit operator pause with retained active work

After an actual operator pause, save a current `project-assess` assessment with `exception: "operator_pause"`, a concrete reason and immutable shared proof. Then use `project-assign PROJECT paused`. It retains all active task bytes/IDs/owners, records a visible paused assignment and prevents automatic stall/empty-queue alerts and stop-hook continuations from overriding the pause. `project-list` labels it `(paused)`; task lifecycle remains active. `inactive` with retained active tasks also yields `paused`, never a false inactive result. Other exceptions cannot create this disposition.

Use immutable shared proof files. New pauses refuse rotating current session-state paths; preserve the operator instruction in fixed project evidence or a stable archive record. Evidence changes invalidate pause verification, and newly assigned task IDs are not covered automatically. An explicit paused marker persists beyond the short assessment expiry while its proof/ownership remains valid. `project-assign PROJECT active` clears the pause without changing task ownership; use only when operator direction authorizes resumption or the selected closure audit. No service or job is stopped by these commands.

Use `project-assess PROJECT --status` to distinguish assessment expiry from pause-proof validity without resuming work. To replace copied proof for an existing pause under still-current operator direction, submit the new assessment with `--refresh-pause`; ordinary submission leaves the marker unchanged. Refresh refuses newly owned task IDs and never recreates a pause cleared by `active`.
