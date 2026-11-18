---
name: project-register
description: "Register a board project only when the operator explicitly requests creating a project or treating work as a project. Ordinary questions, inspections, reviews, and standalone changes do not authorize project creation."
---

# Register a board project

Require explicit operator intent to create a project. Do not turn an ordinary
request into one just to use the board. Check `project-list` first and reuse a
matching project instead of creating a duplicate.

Run exactly:

```text
project-register <project-name> <brief-overview>
```

Example:

```bash
project-register 'PVE Freq' 'Manage the PVE frequency platform.'
```

Follow these rules:

- Pass the human project name and one-line brief overview as two arguments.
- Preserve the authored name; let the command generate the uppercase,
  hyphenated project ID.
- Treat `REGISTERED PROJECT: <project-id>` with exit zero as creation truth and
  report that generated ID.
- The command creates live `ready`, `active`, `blocked`, and `done` queues plus
  the project's durable `archive` directory.
- If it fails, report the exact `REGISTER FAILED` message. Do not silently
  rename the project or retry with a different description.
- Do not manually create, rename, or repair board directories or `overview.md`.
