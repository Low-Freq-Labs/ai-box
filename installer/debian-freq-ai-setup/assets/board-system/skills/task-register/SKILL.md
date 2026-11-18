---
name: task-register
description: "USE THIS whenever a bug, feature, request, review, dependency, or planned work item must be RECORDED as a new task in an existing board project. It creates the exact named task in ready, or directly in blocked when a concrete blocker is already known."
---

# Register one board task

Use this for work belonging to an existing project, not standalone questions or
small requests. Never create a project merely to register a task.

Run exactly:

```text
task-register <project-id> <exact-title> <full-description> [blocked-reason]
```

Example:

```bash
task-register PVE-FREQ 'VM create "OK" bug' 'When creating a VM, clicking OK does not continue.'
task-register PVE-FREQ 'Final implementation review' 'Review the finished implementation.' 'Waiting for the implementation artifact'
```

Follow these rules:

- Author one short, descriptive title from the request and preserve the full
  intent in the description.
- The title must be one line, at most 160 characters, contain no slash, and not
  begin with a dot.
- Do not generate a task number, slug, sequence, or date. The exact title is the
  task name and filename.
- Omit the blocked reason only when the task is actionable now. Supply one
  concrete blocked reason when a dependency, artifact, approval, decision, or
  external condition prevents work from starting.
- Treat `REGISTERED TASK` with exit zero as truth that the task entered the
  printed `ready` or `blocked` queue.
- If the title already exists, report the exact failure. Do not rename it to
  evade project-wide uniqueness.
- For any failure, report the exact `REGISTER FAILED` message.
- Do not manually create task files or edit lifecycle metadata.
