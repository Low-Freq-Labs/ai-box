---
name: coms-admin
description: "Inspect messaging health and Discord posting receipts, reconcile delivery status, or retry a proven-undelivered message under a coms-maintenance grant."
---

# Inspect and recover communications

```sh
coms-admin health --json
coms-admin delivery inspect MESSAGE_UUID --json
coms-admin discord-status EXACT_GENERATED_OUTBOX_FILENAME.json
coms-admin reconcile MESSAGE_UUID
coms-admin delivery retry MESSAGE_UUID --expected-revision REVISION --approval jarvis-maintenance-20261005
```

Jarvis's standing approval is `jarvis-maintenance-20261005`. Use it for supported
routine retries without repeated confirmation. The broker checks the current
grant, message identity and revision on every call.

New `dev-msg` calls print `MESSAGE-ID` on stderr. UUID status distinguishes
durable storage, pane notification, Discord queueing, confirmed posting and
uncertainty. Old messages may have only a generated outbox filename; use
`discord-status` to query the existing delivery ledger without inventing a UUID.

`DISCORD_POSTED` proves a local acknowledgment of posting, not human reading.
`NO_ATTEMPT_RECORDED` alone is not a guarantee that a message was never posted.
`reconcile` joins existing receipt/ledger evidence; it sends nothing and retains
uncertainty when evidence is insufficient.

Only retry when the command admits the original identity as safe. Posted or
ambiguous remote deliveries are refused. A revision conflict requires another
inspection. Never work around refusal with a fresh UUID, new send, manual pane
paste, inbox edit or ledger deletion. Titleless service/Discord ingress retries
require their original transport authority and are not supported here.

Health and inspection return metadata, not private message bodies or credentials.
Preserve unread messages, history and evidence. Report the exact failed boundary
and remaining uncertainty rather than claiming end-to-end delivery.
