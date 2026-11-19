---
name: project-archive
description: "USE THIS when the operator explicitly asks to WRAP UP, CLEAN the board, FLUSH completed work, ARCHIVE a project's done queue, archive one completed task, or SHOW previously archived tasks. It archives completed work, and explicitly retires cancelled or superseded open work while preserving unfinished truth and history."
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
  `done`. Ready, active, and blocked tasks require the explicit retirement form below; they must never be marked done merely to archive them.
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

## Retire cancelled or superseded work

Use only within an explicit operator cleanup/cancellation request, after inspecting
the exact task. Existing operator authorization applies; do not ask again.
Retirement preserves the task and transaction before-image in archive, labels it
RETIRED, and does not claim implementation completion or acceptance.

```sh
project-archive PROJECT 'Exact title' --retire /absolute/retirement.json --expected-revision CURRENT_SHA256
```

The JSON has schema 1, one-line reason (cancelled/superseded and why), note, and
1–32 evidence paths mapped to actual SHA256 hashes. It uses the task-update
evidence limits; no description rewrite. Pin the operator instruction and the
audit or replacement task record that explains the disposition.

One exact open task per call; no bulk retirement. The caller must be assigned
active to the project and may retire only ready/blocked work or their own active
work. Peer active work, stale revisions and changed evidence are refused.
On failure inspect the exact task and transaction before any retry. Verify the
returned archive status and retained retirement note. Normal all archives only
done work and never retires open work. Archived records may represent completed
or explicitly retired work; read the final disposition before claiming success.
