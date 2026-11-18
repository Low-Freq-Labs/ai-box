---
name: storage-budget
description: "Inspect shared filesystem headroom and reserve output capacity before a substantial shared-project run; renew, increase estimates or release the caller's reservation."
---

# Reserve shared output capacity

```sh
storage-budget inspect --filesystem / --json
storage-budget list
storage-budget reserve --project PROJECT_DIRECTORY --run RUN_ID --output /home/freq-agents/projects/PROJECT_DIRECTORY/EXISTING_OUTPUT_DIRECTORY --estimated-output-bytes BYTES --estimated-inodes INODES --policy shared-output-v1 --idempotency-key UNIQUE_RUN_KEY
storage-budget renew RESERVATION_UUID --expected-revision REVISION
storage-budget update RESERVATION_UUID --expected-revision REVISION --estimated-output-bytes INCREASED_ESTIMATE
storage-budget release RESERVATION_UUID --expected-revision REVISION
```

Output must already exist beneath the named shared project. Estimate the entire
peak output, not just the next file. Atomic admission requires effective free
strictly greater than twice the estimate plus 10 GiB and sufficient inodes.
Other reservations remain fully charged until release. Warnings begin below
20 GiB physical availability. Use the returned ID and revision for later calls.

Recheck/renew at the workload's bounded checkpoints before further substantial
output. `SAFE_BOUNDARY_STOP_REQUIRED` exits 3: close the run at its safe boundary,
preserve completed/partial/unrun results, and retain the reservation until all
writers stop. Increase an underestimated peak before continuing. A refused
renewal is not a successful lease extension.

Release only after your run and its writers have stopped. You cannot release a
peer's reservation. Expiry does not prove a process is dead; `recover-stale`
refuses without reviewed lifecycle proof. Do not delete ledger rows to force
admission.

Reservations govern participating workloads; they are not an OS quota.
`physical_control_reserve` reports the root-managed emergency reservoir and
whether its device matches the inspected filesystem. Armed means64MiB is
physically allocated and4096inodes are held. Once released, the recovered space
is not exclusive; it does not make uncontrolled writers safe or grant runtime
release. Existing scripts are not automatically supervised.

For an authorized finite ordered case run, use the installed supervisor:

```sh
storage-run run --project PROJECT_DIRECTORY --run UNIQUE_RUN_ID --output EXISTING_OUTPUT_DIRECTORY --plan PLAN.json --bytes PEAK_BYTES --inodes PEAK_INODES --deadline SECONDS
storage-run status /absolute/output/storage-run-UNIQUE_RUN_ID.receipt
```

Plan format: `{"cases":[{"id":"case-id","argv":["/absolute/program","argument"],"timeout":60}]}`.
Commands run as the caller in the output directory with stdout/stderr discarded.
Include the256KiB preallocated receipt and all output/staging in the estimate.
The supervisor renews before/after cases and preserves completed/failed/unrun
accounting. Preserve the receipt during case cleanup; detected loss/replacement
refuses success and release. This is a cooperative same-UID boundary, not a sandbox.
Controller death may leave children alive: RUNNING plus a charged reservation
requires exact process-identity/closure verification, never expiry-based release.
Read the installed `/usr/local/share/freq-ai-setup/storage-run.md` for limits,
physical reserve behavior, diagnostics and rollback boundaries.
