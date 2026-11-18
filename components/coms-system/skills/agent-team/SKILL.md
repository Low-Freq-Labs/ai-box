---
name: agent-team
description: "Discover the real communications team and show every agent's unread inbox count. Use this skill whenever asked who is on the team, which agents exist, who has messages waiting, who has an inbox, or when asked to contact, notify, poll, survey, or ask the opinion of everyone, the whole team, or all agents before choosing dev-msg recipients."
---

# Discover the agent team

Run exactly:

```text
agent-team
```

Treat the listed agent directories as the authoritative communications roster. The `(you)` marker identifies the current Linux agent. Inbox values are unread message-file counts; they do not claim an agent is online, working, available, or has processed anything.

For requests involving everyone or the whole team:

1. Run `agent-team`.
2. Exclude the row marked `(you)`.
3. Use `dev-msg` once for every remaining listed agent.
4. Report exactly which agents were contacted.

Do not infer recipients from Linux passwd entries, home directories, documentation, memory, or hard-coded names.
