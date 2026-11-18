# Explicit Jarvis root administration

This opt-in component implements Sonny's 2026-10-06 root grant for Jarvis on
ai-box. It is deliberately separate from ordinary agent creation and scoped
host-admin grants. Do not add it to default new-agent installation.

On an explicitly authorized host, run as root:

```sh
python3 install.py --grant-jarvis-root --approval OWNER_APPROVAL_REFERENCE
```

The installer creates an on-host key, a localhost-only root authorized-key
entry, a pinned host key, `/usr/local/bin/vm-root`, personal/shared `vm-admin`
skills and a Jarvis-specific persistent instruction. Existing targets cause
refusal rather than key rotation or silent replacement. SSH must already
permit root public-key login on port 22. No SSH policy, sudo policy, agent
sandbox, other account or service restart is changed.

Exact before-images and a receipt are retained under a timestamped
`/var/backups/freq-jarvis-root-*` directory. Its `private/` contains credentials
and private instructions: keep it root-private on the VM, never copy into the
Windows workspace. Only the sanitized receipt may be exported.

The client is not a restricted command broker: successful authentication grants
unrestricted root. The UID check prevents accidental peer invocation, while
private-key permissions enforce access. It has no command allowlist or
independent review gate. SSH/session logs are not tamper-proof against root.

Revoke by removing only the authorized-key line with the receipt's fingerprint
after inspecting current authorized_keys; preserve unrelated keys. An existing
root session is not terminated by key revocation. Coordinate closure of such
sessions and review any additional access Jarvis may legitimately have created.
Do not blindly restore an older authorized_keys file over later changes.
