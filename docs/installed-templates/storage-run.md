# Participating local run supervision

`storage-run run --project PROJECT_SLUG --run UNIQUE_RUN_ID --output EXISTING_SHARED_OUTPUT --plan PLAN.json --bytes PEAK_BYTES --inodes PEAK_INODES --deadline SECONDS`

`PROJECT_SLUG` is the single shared-project directory name, for example
`infrastructure-management`, rather than an absolute path or board ID. `--output`
is the absolute existing output directory under
`/home/freq-agents/projects/PROJECT_SLUG/`; its first project component must match
`--project` exactly. The slug accepts 1–100 ASCII letters, digits, dots, underscores
or hyphens, with no slash.

The plan is {"cases":[{"id":"case-id","argv":["/absolute/program","argument"],"timeout":60}]}.1..1000 unique case IDs, each at most64characters; total plan1MiB. Deadline1..86400seconds, each case1..3600seconds. All commands run as the invoking UID, in the declared output directory; stdout/stderr go to null. Commands must publish their own intended case outputs there. The wrapper is opt-in: existing scripts do not silently become managed. It is not a sandbox or an output quota. Include the256KiB preallocated receipt and all staging/output in the peak estimate.

`storage-run status /absolute/output/storage-run-RUN_ID.receipt` decodes the latest complete checksum-verified slot. The two slots protect generation, length and JSON payload. Named inode/link/parent identity is checked at checkpoint publication and before release. Ordinary case cleanup must preserve this receipt. This is a cooperative same-UID boundary: another same-UID process can tamper with its files. Detected unlink/replacement/truncation refuses success/release; it cannot create a trustworthy receipt after the user destroys both copies.

Reservation admission and renewals occur before and after every case. A refused renewal stops the next case and preserves completed/failed/unrun IDs. Timeout or leftover descendants closes only the supervisor's own subreaper children using PID descriptors; no peer UID scan/kill occurs. Failure stops further cases. The wrapper never treats lease expiry as death. SIGKILL/controller loss can leave children running and the last record RUNNING; reservation remains charged. Root infrastructure administration must verify exact PID/start/descendant closure before any recovery/release. The controller-loss test exercises this honest incomplete state, not automatic recovery.

# Physical emergency capacity

Root owns /var/lib/freq-control-capacity (0700), a fully allocated64MiB byte reservoir and4096 precreated inode files. freq-control-capacity.timer runs a bounded check every30seconds. Below128MiB or2048freeinodes it releases only these reserve files; it never deletes output or kills workloads. It rearms only above20GiB plus reserve and16384freeinodes plus reserve. Changes notify Jarvis via registered service-alerts source control-capacity-jarvis. Delivery timeout stays uncertain with no automatic retry. An already empty reservoir does not repeatedly send release events.

`storage-budget inspect --filesystem / --json` reports physical_control_reserve alongside existing conservative logical accounting. The reservoir is recovery headroom for control writes, not exclusive after release or a guarantee against an uncontrolled writer consuming that headroom. It is not root's filesystem-reserved blocks. Actual byte/inode exhaustion tests run on disposable ext4 with zero reserved blocks; live root is never filled.

# Deployment and rollback

Deployment pins are SOURCE-PINS.json; before-images and new-path inventory retained under /var/backups/freq-capacity-20261009. Source: storage_run.py8ff76c94; final pins in manifest. Install root-owned code and service/timer; preserve original storage_budget.py before diagnostic extension. Broker restart loads only diagnostic extension; coordinate bounded socket service restart and verify actual Jarvis storage-budget/board/coms commands. No grant expansion.

Rollback: stop/disable only freq-control-capacity.timer; stop its oneshot service; restore the exact backed-up storage_budget.py and restart only freq-host-admin.service; remove only hash-matching newly installed storage-run wrapper/module and guard service/timer/module. daemon-reload. Preserve reservoir data/receipts and allocation until an explicit separate cleanup step; no recursive deletion implied. Existing reservations remain unchanged. Disable the new service-alerts source if rolling back notifications. Do not remove or alter existing alerts, source archives, jobs, grants or project artifacts.
