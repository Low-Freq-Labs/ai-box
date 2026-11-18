---
name: task-done
description: "USE THIS whenever an ACTIVE task YOU OWN is genuinely COMPLETE and should move into the terminal done queue. This is the only command for completing owned board work."
---

# Complete an owned task

Run exactly:

```text
task-done <exact-task-name> <completion-note>
```

Follow these rules:

- The exact task name must identify one active task owned by the current Linux
  agent across the board. Ambiguous names fail closed.
- Use this only when the task is genuinely complete. `done` is terminal.
- Supply a useful completion note that records the accepted artifact or path,
  verification performed, important outcome, and any known limitations that
  matter. The note is stored durably in the task.
- Treat `DONE` with exit zero as board truth, then review the project for the
  next task.
- You cannot complete another agent's task, ready work, or blocked work.
- On `DONE FAILED`, report the exact error. Never move or edit task files by
  hand.

When the same title exists in different projects, select the project explicitly:

```sh
task-done --project <project-id> <exact-task-name> <completion-note>
```

The selected task must still be active and owned by you. Without the selector, ambiguous titles are rejected without changing either task.
