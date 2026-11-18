<!-- FREQ_BOARD_WORKFLOW_BEGIN -->
## FREQ board workflow

Use the board skills for all task and assignment changes; never edit board files directly. Follow their command syntax and procedures.

- Create projects only at the operator's explicit request. Handle standalone requests without board registration. Reuse existing projects and tasks; register missing scope with full intent before starting. Size tasks for independently reviewable outcomes.
- Discover unknown projects with `project-list`; check `project-status` before choosing work. Activate your project assignment when starting or resuming, unless assignment or transfer already did so.
- `ready` means actionable, `active` means owned, `blocked` requires a concrete unmet dependency, and `done` means complete. Register known dependencies as blocked; missing review artifacts are not ready. Lack of an assignee is not a blocker.
- Assign or reopen work with `task-ready`; transfer only your own active work with `task-transfer`. Never reassign another agent's active task or shotgun multiple assignments. Handoffs must identify the shared artifact, revision, completed and remaining work, expected action, and acceptance criteria.
- Continue owned work until complete, transferred, genuinely blocked, or stopped by the operator. After completion or an empty queue, reassess project status and blockers, then take the next actionable task. Do not abandon active work on another project.
- Keep review gates open until acceptance. Substantial rework needs a linked correction task and a blocked review returned to its original reviewer afterward; minor fixes may remain in review. Findings-only work may finish without acceptance if explicitly labeled. Update resolved blockers promptly.
- Complete tasks only when every authored requirement is met. Moving unfinished requirements elsewhere does not complete a task; define separate correction or verification scopes before starting.
- Keep done tasks visible during work. Archive only on explicit wrap-up or board-cleanup requests, using `project-archive`; archived history is retained.
- Inspect BOARD-ALERTs at the next safe boundary. Arrival order does not set cross-project priority. Follow the board skills for alert handling.
<!-- FREQ_BOARD_WORKFLOW_END -->
