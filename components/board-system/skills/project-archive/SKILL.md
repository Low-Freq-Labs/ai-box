---
name: project-archive
description: "USE THIS when the operator explicitly asks to WRAP UP, CLEAN the board, FLUSH completed work, ARCHIVE a project's done queue, archive one completed task, or SHOW previously archived tasks. It moves only terminal done tasks into durable project history so project-status stays focused on current work."
---

# Archive completed project tasks

Run one exact form:

```text
project-archive <project-id> all
project-archive <project-id> <exact-task-name>
project-archive <project-id> show
```

Follow these rules:

- Use `all` only during an explicit wrap-up or board-cleanup request. Do not
  archive tasks automatically after `task-done`; completed work should remain
  visible during the working session.
- Use an exact task name to archive one task only when it is already in
  `done`. Ready, active, and blocked tasks cannot be archived.
- Use `show` to list archived task names without dumping their contents. Use
  `task-status <project-id> <exact-task-name>` to obtain the exact archived
  file when its full evidence is needed.
- The count reports tasks moved by this call, not the total archive. An empty
  `all` reports "nothing moved" and the retained archive count, a successful no-op.
  A peer may have archived first; the output does not identify who. Use `show`
  and `task-status` for history, and `project-status` to verify remaining work.
- Archived tasks remain terminal and cannot return to the live board.
- On `ARCHIVE FAILED`, report the exact error. Never move, delete, or edit
  board files manually.
