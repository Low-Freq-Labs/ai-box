---
name: task-ready
description: "USE THIS whenever a task should become READY or should be ASSIGNED from ready/blocked to an agent. Without an agent it reopens blocked work into ready; with an agent it places ready or resolved-blocked work directly in that agent's active queue."
---

# Ready or assign one task

Run exactly one form:

```text
task-ready <project-id> <exact-task-name>
task-ready <project-id> <exact-task-name> <agent> [assignment-note]
```

Choose the form precisely:

- No agent: move a blocked task to `ready` after its blocker is resolved.
- With an agent: assign a ready or resolved-blocked task directly to that
  agent's active queue. The recipient becomes active on the project
  automatically.

Follow these rules:

- Reopening blocked work requires the current Linux agent to be active on the
  project. The stored blocked reason is cleared and the resolution is recorded.
  If inactive, first run `project-assign <project-id> active`, then retry the
  reopen. Automatic recipient activation does not waive this caller precondition.
- This command cannot touch active or done work. Use `task-transfer` for an
  active task you own.
- Assigning to another agent requires a useful assignment note. The full note
  is stored durably in the task; the compact BOARD-ALERT points the recipient
  to the exact `task-status` command. A note is optional for self-assignment.
- For review handoffs, name who will reopen or assign dependent work after
  acceptance. That agent performs the transition; others inspect before acting.
- An assignment to another agent sends a BOARD-ALERT. `ALERT FAILED` means the
  task still moved successfully; report the alert failure without moving files.
- Treat `READY` or `ASSIGNED` with exit zero as board truth.
- On `READY FAILED`, report the exact error. Never edit board files manually.
  Check each command's exit code before dependent edits or assignments; do not
  semicolon-chain them. Awaiting a tool result alone does not check success.
  Inspect `task-status` and continue only after ownership and prerequisites
  are verified; do not blindly repeat the assignment. An
  `ALERT FAILED` after a successful move requires notification recovery, not
  repeating the ownership change.

For stale description/reason/note wording while a task must remain blocked, use the supported `task-update` metadata command and its skill. Do not falsely reopen an unresolved blocker only to edit its text.
