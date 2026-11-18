# Own-user scheduling on ai-box

The installed agent launcher uses Landlock and excludes the cron spool, so
native `crontab` cannot access it. NoNewPrivs also prevents native setgid access
when enabled; that separate reproduction was not the established original cause.
`agent-crontab` uses the existing ai-box host broker and its authenticated Unix
socket peer UID instead. It manages only that UID's
registered, non-root agent account. There is no target-user option or field.
It does not relax sandbox policy or grant root access.

Inspect the current table:

```
agent-crontab show
```

The JSON contains `exists`, `content`, and `sha256`. Keep a private copy of the
old content before editing; cron files can contain private paths or credentials.
Merge any existing entries into your candidate file, then use the exact hash
returned by `show`:

```
agent-crontab install --expected-sha256 HASH /path/to/your/candidate.cron
agent-crontab show
```

`-` may replace the filename to read stdin. Native Debian crontab validates syntax
before installation. The file must contain at most8192 UTF-8 bytes, end with a
newline unless empty, and have no controls except tab/newline. Existing tables
outside those bounds are refused without modification. There is no shell editor
mode and no automatic merging. Cron runs jobs as the caller's ordinary user,
with normal cron environment and PAM behavior, not as root. Use absolute paths.

To remove your whole table, first inspect it and use its current hash:

```
agent-crontab remove --expected-sha256 HASH
```

Hash preconditions serialize broker clients under the existing broker lock.
Native crontab edits outside the broker do not take this lock: coordinate those
edits. An out-of-band edit can race the precondition; readback detects many such
races but does not provide atomic compare-and-swap against native writers.
On timeout, disconnect or failure, inspect the current table before deciding
whether to retry. A successful install proves table installation and readback,
not execution or application health. The owner must verify their own scheduled
job, environment, outputs and alert delivery. This interface does not authorize
new host access or operations beyond the owner's existing scope.

Deployment rollback restores the saved broker/doc before-images, removes the
new module and CLI, and restarts the socket-activated broker. It does not remove
user tables installed afterward. Users retain native crontab access outside the
sandbox; scheduler policy and cron daemon configuration are unchanged.
