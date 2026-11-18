---
name: dev-msg
description: "Send a communication message to another development agent or reply to Sonny through Discord. Use this skill whenever an agent needs to message, notify, update, ACK, report progress, report DONE or BLOCKED, request review, respond to SONNY-MSG, or otherwise communicate using dev-msg."
---

# Send a development message

Run exactly:

```text
dev-msg <recipient> <plain-title> <full-message>
```

Example:

```bash
dev-msg jarvis 'SOURCE REVIEW NEEDED' 'Please review the socket ACL behavior and report the exact result.'
dev-msg sonny 'SOURCE REVIEW COMPLETE' 'The review passed. Here is the full result.'
```

## Operator message layout

Format substantive operator messages with short paragraphs and blank lines
between distinct topics. Use brief, descriptive headings or bullets where helpful,
chosen for the actual content, not a fixed template. Keep commands and important
paths on separate lines. Preserve useful detail, but never pack several topics
into one paragraph. Simple replies can remain one or two sentences.

Before sending, split any paragraph that mixes distinct topics. Pass real newline
characters inside the single full-message argument, not literal `\\n` text.
Headings and section counts depend on the message; omit irrelevant sections.

Follow these rules:

- Supply the recipient's lowercase Linux agent name.
- Supply the title without square brackets; `dev-msg` adds exactly one pair.
- Keep the title nonempty, single-line, and at most 160 characters.
- Put all details in the full-message argument. For agent recipients, only the
  title and message-file pointer enter the pane.
- Use recipient `sonny` to reply through the one-bot Discord connector. That
  route writes the full reply to the connector outbox and performs no tmux
  injection.
- Let `dev-msg` perform the exact paste, first Enter, second Enter sequence; do not add manual tmux keys.
- Trust `SENT` with exit zero as confirmation that the message reached its
  immediate durable boundary: an agent inbox plus pane notification, or the
  Discord outbox for Sonny. It does not prove a human read, understood, or
  completed anything, and the Sonny route does not prove Discord posted it yet.
- On failure, report the exact named boundary from stderr.
- Do not automatically retry a failed call.
- Do not use `dev-reply`, `dev-send`, raw tmux commands, or direct inbox-file creation.

New sends print a stable `MESSAGE-ID` on stderr. Record it and use
`dev-msg-status MESSAGE_UUID --json` to inspect delivery after success or failure.
For a logical message that may be submitted again, use a stable idempotency key:

```sh
dev-msg --idempotency-key UNIQUE_LOGICAL_MESSAGE_KEY --body-file /path/to/message.txt jarvis 'SOURCE REVIEW NEEDED'
```

`--body-file -` reads UTF-8 from stdin. Repeating the same key and content returns
the existing receipt without resending; changed content with that key is refused.
`EXISTING` is not a new delivery acknowledgment. Keep title/key identity stable,
inspect the receipt, and route recovery to the granted comms administrator.
