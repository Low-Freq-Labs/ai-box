---
name: wrap-up
description: Save lightweight session checkpoints at meaningful work boundaries, or perform full closure checks and board archiving when the operator explicitly requests wrap-up.
---

# Checkpoint or wrap up a session

## Lightweight checkpoint

After a meaningful milestone or before going inactive with changed progress,
blockers, or next steps, refresh the same session-state record using steps 5–6
below. Carry forward all ongoing projects, not just the most recent task. Label
it **Checkpoint — not a completed wrap-up**; report unchecked Git/remote and
closure requirements as unverified. Skip unchanged snapshots and tiny edits.

Checkpointing does not authorize inbox polling, archiving tasks, draining messages,
committing/pushing, moving work, or stopping services. Save and read back the
record, then continue the normal workflow. No automatic operator message is needed.

## Full wrap-up

Run only on an operator wrap-up request, not after ordinary task completion.
Wrap-up permits a safe checkpoint; it does not make unfinished tasks complete.

1. Reach a safe stopping point. Run `dev-inbox` once, handle actionable
   messages, and record unanswered questions without polling. Make board state
   truthful: finish, transfer with a handoff, or block only for a real dependency.
   Work you will resume may remain active; explicitly record it. Stop only your
   disposable test processes; record any intentional remaining service.
2. Inventory this session's project paths and your home, including hidden files
   and untracked/ignored artifacts. Move project work to its existing
   `/home/freq-agents/projects/<project>/` directory. Preserve repository history
   and verify contents before removing the old copy. Never overwrite a conflicting
   destination, traverse another agent's home, or copy secrets into shared storage.
   Leave authentication, runtime settings, installed skills, caches, and disposable
   scratch in your home. If you cannot distinguish work from scratch, report it.
3. For each touched repository, inspect status, diff, untracked files, submodules,
   and worktrees. Stage only reviewed in-scope work: no blanket `git add .`,
   secrets, caches, or unrelated teammate edits. Run relevant checks. Make
   coherent commits with an imperative summary; record purpose and checks in the
   body when useful. Label unfinished work `checkpoint: ...` and state what is
   incomplete. Never invent Git identity, bypass hooks, amend others' commits,
   stash away leftovers, reset, force-push, or blindly pull.
4. Push to the authorized upstream and verify the remote branch contains the
   committed HEAD. If a project repository has no remote and shared GitHub is
   configured, creating a private repository in that dedicated account is allowed:
   - Verify the account with `gh api user --jq .login`; never read token files.
   - Use the existing project name; check whether that account/repository already
     exists. Reuse only a verified matching project, never an unrelated name collision.
   - For a new repository use `gh repo create <account>/<project> --private
     --source <shared-project-path> --remote origin` as one command, then push
     the intended branch with upstream tracking and verify remote HEAD.
   - Coordinate one creator per project. If creation reports a collision or partial
     failure, inspect remote/GitHub state before proceeding; never blindly retry.
   Never replace existing remotes, force-push, publish publicly, or delete a remote
   repository without explicit direction. Other accounts/organizations need named
   authorization. Report unavailable authentication, denied operations, ambiguous
   ownership or rejected pushes; do not claim backup. Recheck the working tree.
   Non-Git deliverables remain explicitly listed shared files unless project scope
   authorizes putting them in Git. A lightweight checkpoint alone does not authorize
   remote creation or pushing.
5. Draft one Markdown session-state record under your shared state directory:
   `/home/freq-agents/session-data/<your-linux-username>/`.
   Include the timestamp and three short sections:
   - **Resume here:** all ongoing projects/task IDs, shared paths, current progress,
     next actions, blockers, pending reviews/messages, and intentional processes.
   - **Session summary:** meaningful changes, decisions, and unresolved issues.
   - **Verification:** artifact paths, branches/commits, push evidence, actual
     checks/results, limitations, and unmet wrap-up requirements.
   Link evidence instead of copying transcripts; never include secrets. Make the
   record usable without your home. Use `task-status` for archived task evidence.
6. Save it with `wrap-up-state save <session-draft.md>`. The helper writes a
   UTC timestamped file inside `session-state/`, verifies it, then moves previous
   records into `session-state/archive/`. Read back the returned file.
   `STATE_SAVED` proves only that the record was saved, not that wrap-up passed.
7. Run `project-archive <project-id> all` for each board project worked on this
   session. Only done tasks move; do not archive unrelated projects. Verify exit
   status and use `project-status` to confirm remaining live work. If this fails,
   record the error in the session draft and save a fresh record again. Do not
   manipulate board files manually. Do not drain coms unless separately requested.
8. Recheck changes and run `dev-inbox` once at the final safe boundary, without
   waiting. If anything invalidates the handoff, update the records/checks before
   claiming success. Remove only your verified redundant drafts.

Report the saved path, shared-location check, Git/remote result, board archive
result, and any remaining work. Say **Safe to close** only when every requirement
passed. Otherwise say **Wrap-up incomplete** and name the exact unmet checks, even
if the record saved successfully. Never imply the next session's work is done.

On resume, treat the current session-state as a dated snapshot, not live truth;
verify it against current board/files and referenced evidence before
continuing. The state directories survive agent deletion and level-set; they are
shared team data, not private agent-home storage.
