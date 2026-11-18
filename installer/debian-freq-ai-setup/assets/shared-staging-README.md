# Agent staging

Each agent owns one lane below this directory. The owner may create and change
files in that lane. The master user and peer agents may read the lane, but peers cannot
write, rename, replace, chmod, or link its contents.

Staging is for reviewable handoffs and temporary collaboration artifacts. Put
long-lived project work in `/home/freq-agents/projects`.
