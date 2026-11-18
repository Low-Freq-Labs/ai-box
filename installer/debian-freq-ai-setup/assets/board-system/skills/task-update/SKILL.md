---
name: task-update
description: Correct a task's current description, blocked reason and status note in place, preserving its lifecycle, owner, identity and transaction history. Use for stale guidance, not assignment or completion.
---

Inspect the exact task with `task-status PROJECT TITLE --json`. Check errors and pending operations. Prepare a canonical absolute JSON file:

```json
{"schema":1,"description":"Current scope and next prerequisite.","reason":"One current blocked reason.","note":"What was corrected, evidence, and remaining limits.","evidence":{"/absolute/shared/evidence.json":"ACTUAL_SHA256"}}
```

`description` and `reason` are optional individually; supply at least one. `note` and 1–32 actual SHA256-pinned evidence paths are required. Each evidence file must be canonical and regular, at most 4MiB; use bounded primary records and link larger inventories from those records. The changes JSON is at most 64KiB. Prose fields are bounded to 8,000 characters; reason is one line, at most 500. No board control markers. Use designated shared evidence or caller read-message evidence; credentials/private homes are not evidence inputs.

```sh
task-update PROJECT 'Exact task title' --expected-revision CURRENT_SHA256 --changes /absolute/changes.json
```

Only your owned active task or a blocked task in a project where you are assigned can be corrected. An active task cannot receive a blocked reason this way. Ready/done/archive tasks are refused. This operation does not resolve a blocker, claim work, reopen a task, grant authority or mark acceptance. An original task request is retained in the transaction before-image; preserve its intent while making current scope explicit. Corrections get an attributed Status note, history entry, immutable before/after images, operation ID and revision.

On `UPDATE FAILED`, stop dependent changes, inspect `task-status` and transaction state. Do not edit board files, blindly retry or reopen an unresolved task to change wording. An optional `--operation-id UUID` binds an exact request; a changed request is refused. On success verify status, owner and new revision with `task-status`.
