---
name: task-dependencies
description: Inspect explicit task dependency reassessment hints or record dependency links and human review dispositions. Use for named task dependencies; ordinary task lifecycle changes still use the existing task skills.
---

# Review explicit task dependencies

Inspect advisory hints with:

```text
task-dependencies list PROJECT
```

`needs_reassessment` calls for human review of the named prerequisites and their
scope. It does not prove that they are complete or that every blocker is cleared.
`unknown` requires resolving missing or ambiguous evidence. `reviewed_unchanged`
means a committed disposition still matches the observed dependent revision and
prerequisite fingerprints; it does not mean ready, approved, or claimed.

An empty result covers explicitly linked blocked tasks only. It does not clear
unlinked blockers. A failed or incomplete scan provides no healthy empty result.
The read holds one project lock; its output is an observation, not a reservation.

Record links only for a concrete, understood dependency:

```text
task-dependencies set PROJECT --title TITLE --expected-revision SHA256 --links JSON [--kind mixed|task-dependency] [--operation-id UUID]
```

The JSON value is a list of objects with exactly `project`, `task_id`, `title`
and `scope` string fields. Obtain current exact identity and revision through
`task-status PROJECT TITLE --json`; inspect its errors and pending operations.
Use the same project and the exact prerequisite title/ID. Scope describes what
that evidence establishes, at most 160 characters. At most 32 links and 8,192
UTF-8 bytes of metadata are supported. `mixed` is the default kind; distinguish
remaining non-task blockers in the authored task reason. An empty list removes
explicit links, not the task's blocked status or reason. Setting links clears
any previous disposition.

Only the current owner can edit active task metadata. A currently assigned agent
can edit blocked task metadata; ready, done and archived tasks are refused.
The expected revision must still match. Self-links, duplicates, cycles and
cross-project links are refused. Never infer links from similar titles.

After reviewing the evidence and remaining blocker clauses, record a disposition:

```text
task-dependencies review PROJECT --title TITLE --expected-revision SHA256 --fingerprint SHA256 [--disposition still-blocked|superseded] [--operation-id UUID]
```

Use the exact current fingerprint from `list`. The task must remain linked and
blocked. Default disposition is `still-blocked`; `superseded` records your review
without changing links or lifecycle state. Both suppress an unchanged hint only
while its committed operation, dependent revision and prerequisite fingerprints
still match. Any lifecycle transition requires the existing task command and its
own authority and evidence.

Omitting the operation ID generates a UUID; a supplied UUID is normalized.
Empty or malformed supplied IDs are refused. Existing operation IDs are not
replayed automatically. A failed/disconnected write may have a pending or
committed transaction: inspect the task and supported board transaction evidence
before another write. Do not infer non-commit from missing output, edit board
files directly, or retry blindly.
