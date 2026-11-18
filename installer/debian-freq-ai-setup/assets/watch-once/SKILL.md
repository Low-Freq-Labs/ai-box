---
name: watch-once
description: Observe a long-running authorized job through a bounded read-only command stream, save a compact result, and notify my inbox once so I can continue other work. Use for temporary completion follow-up, not permanent service monitoring or waiting for communications replies.
---

# Watch Once

Use this pattern for jobs that can continue while I do other useful work.

Use `scripts/watch_once.py` with a read-only observer command, a fresh output directory, a deadline, and a literal completion marker. Attach to the specific run (for example, Docker logs with an exact `--since` start time); historical completion messages must not satisfy a new observation. If the command itself performs the work, choose another method: this helper terminates its observer process group on a match or deadline.

The helper records compact status only, discards raw output, sends exactly one `dev-msg` attempt to my own Linux-agent inbox, and exits. It reports completion-marker, stream-ended, command-failed, deadline, or observer-error distinctly. A marker is evidence to investigate, not proof the task passed. No retries, polling of inboxes, permanent service, or service-alert registration is involved. Use the dev-msg skill for communications semantics; queue acceptance is not proof I read the result.

Choose an explicit deadline. Use a recognizable nonsensitive label and marker; do not put secrets in command arguments. Use the project's existing shared tree for the fresh output directory. Never reuse an observation directory, and do not launch a duplicate observer for the same active run.

```bash
python3 scripts/watch_once.py --label 'Authorized finite job' \
  --output-dir /home/freq-agents/projects/PROJECT/evidence/watch-RUN-UTC \
  --timeout 7200 --marker 'RUN completed' --background -- \
  tail --follow=name /path/to/exact-authorized-run.log
```

Use the actual emitted marker, including spacing; the example is illustrative. Omit `--background` to observe in the foreground. `--no-notify` is for isolated tests. The background launcher prints its PID and evidence directory. Record those, the run identity, deadline and expected follow-up in the current checkpoint. Continue useful work rather than waiting for the notification. Mark board work according to its actual state; the observer does not finish or assign tasks.

On notification, read the exact dev-read message, inspect `result.json`, check the affected service/client as required, and report material outcomes to the operator. If the observer fails or times out, investigate before deciding whether another observation is justified. `notification.json` records the single delivery attempt separately from the job result.

This skill and helper are installed personal runtime resources. Durable source is maintained at the portable installer?s `assets/watch-once/`.
