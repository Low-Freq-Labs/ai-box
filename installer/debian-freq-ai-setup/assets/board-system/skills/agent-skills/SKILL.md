---
name: agent-skills
description: Check or refresh the current agent's managed board/comms skill copies when installed instructions drift from the shared maintained versions.
---

Run as the owning agent, choosing its runtime:

```sh
agent-skills check --runtime codex
agent-skills sync --runtime codex
```

Use `--runtime claude` for Claude. Default scope is managed skills already present locally. To include missing managed skills or narrow the repair, add `--skills project-assign project-assess project-list dev-msg dev-msg-status agent-skills`.

`check` is read-only and reports changed file hashes. `sync` copies published root-owned SKILL.md and optional agents/openai.yaml into this caller's runtime only, preserving exact prior bytes and modes in private `~/.local/state/freq-agent-skills/` backups with a manifest. It refuses root, unsafe paths, symlinks, hard-linked files and unexpected ownership. Legacy group-write modes are accepted only inside a validated private caller tree; published source remains strict. It never changes custom skills, runtime configuration, credentials, agent instructions, tasks or assignments.

Inspect `changed_files`, `applied` and the backup path; run `check` again after sync. Sync is not an all-files transaction: after a failure inspect the manifest and actual files before retrying. For rollback restore only the caller's matching before-images and recorded modes; retain the manifest. Do not write peer homes. Read refreshed skills before using their procedures; an already loaded session may retain older skill text until reread or its next context.
