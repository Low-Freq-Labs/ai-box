---
name: dev-read
description: "Read one exact development-agent message file. Use this skill whenever a pane notification shows a dev-read command, an inbox listing provides an exact .md filename, or the agent is asked to open, read, show, or reread a specific communication message."
---

# Read an exact development message

Run exactly the command shown in the notification or inbox listing:

```bash
dev-read 2026-09-01_224625_655609127_3613773_finn.md
```

Follow these rules:

- Pass one exact generated `.md` basename; never pass a path or wildcard.
- Read the printed stdout as the complete message body.
- On first read, allow the command to move the file from `inbox/` to `read/`
  before printing it.
- Use the same exact command to reread a file already in `read/`.
- Do not replace this command with `cat`, `mv`, filesystem searches, or manual
  receipt handling.
- If it fails, report the exact `READ FAILED` message without guessing.
