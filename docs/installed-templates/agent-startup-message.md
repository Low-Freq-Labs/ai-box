Operator startup request: orient and recommend; do not begin project work yet.

1. Read your latest session-state-<timestamp>.md in
   /home/freq-agents/session-data/<your-agent-name>/session-state/ (not archive).
   If none exists or it is unreadable, say so; do not invent a handoff.
2. Treat it as a dated snapshot, not live truth. Check its important claims against current shared files, Git status, and board
   state using read-only checks. Distinguish verified facts, changes, blockers,
   and anything unverified. Do not repair, claim, transfer, or resume tasks yet.
3. Send the operator a concise, natural Discord reply using the dev-msg skill's
   formatting guidance, not a fixed report template. Mention meaningful changes,
   blockers or verification limits. When work remains, recommend the most valuable
   next action, briefly explain why, and mention other worthwhile items. Ask whether
   to proceed or if the operator has something more important in mind.
   When nothing remains, simply say you're caught up and ask what they'd like next.
   Use short paragraphs or relevant sections only when useful; omit empty sections,
   routine checklists and invented priorities. Do not claim checks you did not run.

If Discord is unavailable or delivery fails, show the briefing and failure in
your terminal; do not claim delivery or blindly resend. End your turn awaiting
the operator's direction. Do not poll, sleep, or start the recommended work.
This startup pause takes precedence over automatic board-work continuation;
resume the normal workflow once the operator gives direction.
