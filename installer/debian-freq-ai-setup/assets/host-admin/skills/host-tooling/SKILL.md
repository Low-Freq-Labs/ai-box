---
name: host-tooling
description: "Verify installed board/comms tooling and deploy or roll back an operator-published reviewed release using a tooling-maintenance grant."
---

# Maintain reviewed tooling

```sh
host-admin tooling status
host-admin tooling verify
host-admin tooling plan RELEASE_NAME
host-admin tooling apply PLAN_UUID --expect-plan-sha256 PLAN_SHA256 --approval jarvis-maintenance-20261005
host-admin tooling job-status JOB_UUID
host-admin tooling rollback JOB_UUID --approval jarvis-maintenance-20261005
```

Use `status` to discover operator-published releases. The current standing grant
is limited to board/comms components, with approval `jarvis-maintenance-20261005`.
It permits supported routine application and rollback without another approval
prompt. It does not authorize authoring a new release manifest or pinning your
own code. Ask the operator to review and publish a missing version.

Review the dry-run per-file hashes, component, release review and plan digest.
Apply only that plan. The broker rejects installed drift, changed release pins,
revoked grants and targets outside the component allowlist. `job-status` is the
durable result; a disconnected call is not permission to create a new job.

Backups include exact prior bytes and metadata. Rollback requires the installed
version still match the job's after-image; it refuses to erase later work or
remove newly introduced files. `RECOVERY_REQUIRED` or an interrupted prepared
job requires operator inspection, not manual file replacement.

Verification covers installed fingerprints/metadata and code syntax. Reviewed
release evidence must cover behavior and compatible schemas; do not call syntax
checks full runtime acceptance. Coordinate a quiet command window for a real
version change. No arbitrary shell, package origin, broker self-update, service
restart, disk operation or agent-home access is granted by this capability.
