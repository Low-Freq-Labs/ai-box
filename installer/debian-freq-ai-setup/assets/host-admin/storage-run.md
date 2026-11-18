# Participating local run supervision

`storage-run run --project PROJECT_DIRECTORY --run UNIQUE_RUN_ID --output EXISTING_SHARED_OUTPUT --plan PLAN.json --bytes PEAK_BYTES --inodes PEAK_INODES --deadline SECONDS`

The plan is {"cases":[{"id":"case-id","argv":["/absolute/program","argument"],"timeout":60}]}.1..1000 unique case IDs, each at most64characters; total plan1MiB. Deadline1..86400seconds, each case1..3600seconds. All commands run as the invoking UID, in the declared output directory; stdout/stderr go to null. Commands must publish their own intended case outputs there. The wrapper is opt-in: existing scripts do not silently become managed. It is not a sandbox or an output quota. Include the256KiB preallocated receipt and all staging/output in the peak estimate.

`storage-run status /absolute/output/storage-run-RUN_ID.receipt` decodes the latest complete checksum-verified slot. The two slots protect generation, length and JSON payload. Named inode/link/parent identity is checked at checkpoint publication and before release. Ordinary case cleanup must preserve this receipt. This is a cooperative same-UID boundary: another same-UID process can tamper with its files. Detected unlink/replacement/truncation refuses success/release; it cannot create a trustworthy receipt after the user destroys both copies.

Reservation admission and renewals occur before and after every case. A refused renewal stops the next case and preserves completed/failed/unrun IDs. Timeout or leftover descendants closes only the supervisor's own subreaper children using PID descriptors; no peer UID scan/kill occurs. Failure stops further cases. The wrapper never treats lease expiry as death. SIGKILL/controller loss can leave children running and the last record RUNNING; reservation remains charged. Root infrastructure administration must verify exact PID/start/descendant closure before any recovery/release. The controller-loss test exercises this honest incomplete state, not automatic recovery.

# Physical emergency capacity

Root owns /var/lib/freq-control-capacity (0700), a fully allocated64MiB byte reservoir and4096 precreated inode files. freq-control-capacity.timer runs a bounded check every30seconds. Below128MiB or2048freeinodes it releases only these reserve files; it never deletes output or kills workloads. It rearms only above20GiB plus reserve and16384freeinodes plus reserve. Portable installations record transitions in the systemd journal. Production-specific alert recipients and grants are not copied; enroll alert routing separately if needed. An already empty reservoir does not repeatedly send release events.

`storage-budget inspect --filesystem / --json` reports physical_control_reserve alongside existing conservative logical accounting. The reservoir is recovery headroom for control writes, not exclusive after release or a guarantee against an uncontrolled writer consuming that headroom. It is not root's filesystem-reserved blocks. Actual byte/inode exhaustion tests run on disposable ext4 with zero reserved blocks; live root is never filled.

# Deployment and rollback

The host-admin installer installs these components and preserves replaced files in its timestamped /var/backups/freq-host-admin directory with a hash manifest. It initializes the root-owned reservoir only when absent, validates existing state, and enables freq-control-capacity.timer. No maintenance or alert grants are added. Initialization may leave the reservoir unarmed when headroom is below the rearm threshold; inspect status rather than assuming capacity.

Rollback: disable/stop only freq-control-capacity.timer and its service; restore the exact host-admin before-images recorded by the installer, then daemon-reload and restart only freq-host-admin.service in a coordinated maintenance window. Preserve reservoir data, receipts, reservations, and unrelated services. Removing reserve storage requires a separate reviewed cleanup. This installer does not migrate production jobs, credentials, or evidence.
