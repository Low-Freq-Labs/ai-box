---
name: project-list
description: "List every registered board project and its currently assigned agents. Use this skill whenever asked which projects exist, what projects are on the board, who is assigned to which project, what project to continue, or when the project ID is unknown."
---

# List board projects

Run exactly:

```text
project-list
```

Follow these rules:

- Use the default form for normal discovery. Both forms below are read-only.
- Treat the displayed project IDs and assigned agents as current board truth.
- Understand that it does not show project overviews, tasks, runtime status, or
  agent availability.
- Use `project-status <project-id>` when one project's task tree is needed.
- If it fails, report the exact `LIST FAILED` message without guessing.
- Do not replace it with `find`, `ls`, filesystem searches, or hard-coded
  project names.


A `(paused)` suffix identifies an explicit operator pause with retained active task ownership; it does not make those tasks done or unowned.

If pause-proof validation prevents normal discovery, use:

```text
project-list --diagnostic
```

This labels invalid pause markers conspicuously and includes unaffected projects. Invalid proof still produces a nonzero exit and an explicit unhealthy diagnostic; do not treat that inventory as verified pause authority. Structural board/assignment errors still fail. Report the exact error and coordinate supported owner recovery; never bypass proof or edit another agent's marker.
