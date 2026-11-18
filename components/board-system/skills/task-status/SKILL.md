---
name: task-status
description: "USE THIS whenever you need to INSPECT one exact board task and see its current status, owner, file, or blocked reason. This command is read-only and never changes task state or assignment."
---

# Inspect one task

Run exactly:

```text
task-status <project-id> <exact-task-name>
```

Follow these rules:

- Use the exact authored task name, not a generated number or approximation.
- Read `STATUS`, `OWNER`, and `REASON` as current board truth.
- `LATEST NOTE` previews the last recorded Status note, assignment or transfer handoff,
  including attribution. It is historical context, not necessarily the current
  owner or acceptance verdict. Long or multi-section notes may be truncated;
  use `FILE` for the complete note and history. Do not echo it through coms.
- An `archive` status is terminal historical truth. Read its exact returned
  file when needed, but never return it to the live board.
- You may read the exact task file returned by `FILE` when its description,
  history, assignment, handoff, or completion context is needed. Never mutate
  that file directly.
- This command is read-only. Use `task-ready`, `task-block`, `task-done`, or
  `task-transfer` when a state change is required.
- On `STATUS FAILED`, report the exact error. Do not search for, move, or edit
  board files manually.

Use `task-update` for current description/reason/status-note corrections without lifecycle changes; inspect its skill first. Historical notes and transaction before-images remain dated history.
