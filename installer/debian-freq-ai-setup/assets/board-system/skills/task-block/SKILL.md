---
name: task-block
description: "USE THIS whenever an ACTIVE task YOU OWN cannot continue and must be BLOCKED with one concrete current reason. This is the only command for moving your owned work into the blocked queue."
---

# Block an owned task

Run exactly:

```text
task-block <exact-task-name> <one-line-reason>
```

Follow these rules:

- The exact task name must identify one active task owned by the current Linux
  agent across the board. Ambiguous names fail closed.
- Give one concrete, current, single-line reason. Do not write a vague status.
- Treat `BLOCKED` with exit zero as board truth.
- You cannot block another agent's task, ready work, or completed work.
- On `BLOCK FAILED`, report the exact error. Never move or edit task files by
  hand.

When the same title exists in different projects, select the project explicitly:

```sh
task-block --project <project-id> <exact-task-name> <one-line-reason>
```

The selected task must still be active and owned by you. Without the selector, ambiguous titles are rejected without changing either task.

For stale description/reason/note wording while a task must remain blocked, use the supported `task-update` metadata command and its skill. Do not falsely reopen an unresolved blocker only to edit its text.
