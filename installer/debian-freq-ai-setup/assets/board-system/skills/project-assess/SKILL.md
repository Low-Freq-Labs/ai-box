---
name: project-assess
description: Record and check a current prerequisite assessment before voluntary project inactivity or completing an ongoing work turn.
---

Run `project-assess PROJECT --template` to obtain the current revision and complete ready/blocked task list. Trace each relevant task to its next executable prerequisite. Do available work before preparing a stopping assessment. Keep project task updates in the existing task commands.

Write the assessment JSON in shared project evidence. Retain schema, project, agent and revision from the template. Set a concrete summary. `dispositions` must cover every ready/blocked task ID exactly once; related IDs may be grouped in `task_ids`.

Each disposition requires `kind`, `reason`, `next_step`, `owner`, and `evidence` (absolute paths listed in the top-level `evidence` mapping of path to actual SHA256). Allowed kinds: `unavailable_access`, `operator_decision`, `external_condition`, `owned_elsewhere`, `outside_role`. Missing code/contracts/tests/reviews is actionable work, not a stopping kind. Ready work permits only an evidenced role boundary or another owner's active prerequisite. `owned_elsewhere` also requires `active_task_id` belonging to that named other owner in this same project. Cross-project handoffs require explicit role-boundary evidence; do not claim they are machine-verified active prerequisites.

Submit with `project-assess PROJECT --submit /absolute/assessment.json`, then use `project-assign PROJECT inactive`. `project-assess PROJECT --check` is read-only. Any project task revision change, referenced evidence hash change, or 30-minute expiry requires reassessment. Never auto-fill dispositions from existing blocked reasons.

If truly required, an assessment may set `exception` to `operator_pause`, `operator_cancel`, `infrastructure_failure`, or `budget_exhausted`, with concrete `exception_reason` and pinned evidence. Exceptions preserve active tasks; they do not authorize abandonment, infer operator approval, or mark unfinished work done. A broken assessment command is infrastructure failure, not a passed assessment.

The managed local Codex Stop hook gives at most one corrective continuation. Repeated failure, native interruption, process/budget failure, unassigned projects, unsupported clients or unloaded hooks are not proof of compliance. No polling or automated messages. See `/usr/local/share/freq-ai-setup/stop-gate.md` for the exact supported boundary and rollback.

Outside-role is not a blanket dismissal of frontend/backend dependencies: name the concrete next owner and handoff, then check independent work. Receipt storage is /home/freq-agents/session-data/<agent>/stop-assessments/ (caller-owned 0700); the initial /var/lib receipt location was rejected by the live session write boundary and superseded. Do not bypass a denied write. Shared tool setup must preserve project-assess, task-dependencies, task-update, their supporting libraries, the managed Stop configuration and per-agent assessment directories. The maintained setup-board source includes this overlay; older setup copies need the same overlay before reinstall. No setup rerun was required for the current repair.

For an explicit operator pause, publish immutable shared proof of the current instruction, submit an `operator_pause` assessment, then use `project-assign PROJECT paused`. Current rotating `session-state/` paths are refused as new pause proof; use a fixed project evidence file or a preserved archive record. Do not copy an old instruction to imply new authority. Pauses retain unfinished task ownership and can remain valid beyond the 30-minute assessment expiry.

Use `project-assess PROJECT --status` for bounded read-only diagnostics: it validates the full board/evidence and separately reports assessment freshness, pause-proof validity and retained ownership. An expired activity assessment does not by itself invalidate an operator pause or authorize resumption. Status exit zero means the diagnostic ran; inspect its fields for validity. `--check` still strictly checks the assessment.

Plain `--submit FILE` leaves any existing pause marker unchanged and says so. When the current operator pause still applies, use `project-assess PROJECT --submit FILE --refresh-pause` to explicitly refresh its copied proof under the project lock. This requires an existing caller-owned marker, current `operator_pause` assessment, immutable shared proof and no newly owned task IDs. A later `project-assign PROJECT active` removes the pause; refresh cannot recreate it. New pauses or expanded task scope require the explicit assignment procedure. Refresh never infers operator authority from text.

Assessment and marker writes are individually durable, not a crash-atomic pair. A reported marker-write failure can leave the new assessment with the old marker; inspect `--status` and actual evidence before supported recovery. Do not edit markers manually.
