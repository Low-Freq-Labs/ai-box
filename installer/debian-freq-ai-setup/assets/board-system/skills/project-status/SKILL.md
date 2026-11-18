---
name: project-status
description: "Inspect one board project's task states, owners and blocked reasons, using the full tree, paginated JSON or bounded summary before choosing work."
---

# Inspect one project's task states

Use one exact project ID. All forms are read-only.

For the full current task tree:

```text
project-status <project-id>
```

This shows ready, active owners, blocked reasons and done tasks. It excludes
archived history; use `project-archive <project-id> show` when archived tasks
are needed. Names are alphabetical for display, not priority. Overview and
ordinary task descriptions are not printed.

For a bounded overview:

```text
project-status <project-id> --summary
```

Summary is JSON with queue totals, shown/omitted counts and at most 20 ready,
active or blocked task details, within 12,288 output bytes. Done tasks contribute
counts, not detail rows. Blocked reasons may be shortened to 160 characters,
with `reason_shortened` set. Check `partial` and omitted counts; an omitted task
is not absent from the board. Do not combine `--summary` with other flags.

For paginated records and diagnostics:

```text
project-status <project-id> --json --cursor 0 --limit 25
project-status <project-id> --include-errors --cursor 0 --limit 25
```

Both forms produce JSON. Cursor is a nonnegative offset; limit is 1–1000
(default 100). Follow `next_cursor` until null when a full census is needed;
`total_tasks` describes the entire observed record set, including archived rows.
Check `complete`, `errors` and `pending_operations`: legacy JSON exit zero alone
is not proof of a healthy, complete board. JSON-mode option help is available as
`project-status --json --help`.

Each invocation observes the board under one read lock. Separate pages do not
share a snapshot; concurrent transitions can shift offsets. A summary timestamp
is an observation time, not an ownership claim or a lease.

Before acting, inspect the exact authored task with `task-status` and use the
supported task commands for changes. Read the exact task file when its full
purpose or history is needed. On failure, report the exact diagnostic rather
than treating unreadable or corrupt records as an empty queue. Default tree and
summary failures are nonzero; summary does not emit healthy partial counts.
Do not replace board inspection with filesystem searches or manual board edits.

For explicitly linked blocked tasks, use `task-dependencies list <project-id>`
to inspect advisory reassessment hints. This view does not cover unlinked
blockers and never makes a task ready or claimed. Follow the task-dependencies
skill when recording links or review dispositions; ordinary lifecycle actions
continue to use their existing task skills.
