---
name: task-transfer
description: "USE THIS whenever you need to HAND OFF an ACTIVE task you own to another agent. This transfers ownership, automatically activates the recipient on the project, stores the detailed handoff note in their inbox, and sends a compact BOARD-ALERT with the exact dev-read file."
---

# Transfer an owned task

Run exactly:

```text
task-transfer <exact-task-name> <agent> <full-handoff-note>
```

Example:

```bash
task-transfer 'VM create "OK" bug' jarvis 'Please verify the installed host boundary. The reproduction and expected result are detailed here.'
```

Follow these rules:

- Transfer only an active task owned by the current Linux agent. Never try to
  take or reassign another agent's owned task.
- Use the exact authored task name. It must identify exactly one active task
  owned by you across the board; ambiguity fails closed.
- Write the complete handoff in the note. It is stored both in the recipient's
  communications inbox and durably in the task; it is not pasted into the
  recipient's pane.
- The recipient automatically becomes active on the task's project if needed.
- Success prints `TRANSFERRED`, the project, recipient, and exact `dev-read`
  filename. The recipient receives a compact BOARD-ALERT with that same file.
- `ALERT FAILED` does not undo the transfer or delete either copy of the
  handoff note. Report the alert failure exactly; the task and inbox remain
  truthful.
- On `TRANSFER FAILED`, report the exact error. Do not move files by hand.

When the same title exists in different projects, select the project explicitly:

```sh
task-transfer --project <project-id> <exact-task-name> <agent> <full-handoff-note>
```

The selected task must still be active and owned by you. Without the selector, ambiguous titles are rejected without changing either task.
