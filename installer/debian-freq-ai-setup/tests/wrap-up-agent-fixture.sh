#!/bin/bash
# Execute only as disposable wrap-check or wrap-check-two inside the agent sandbox.
set -euo pipefail
agent=$(id -un)
[[ $agent == wrap-check || $agent == wrap-check-two ]] || exit 2
root="/home/freq-agents/session-data/$agent"
repo="$root/qualification"
[[ ! -e $repo ]] || { echo 'fixture already exists'; exit 2; }
mkdir "$repo"
git init -q "$repo"
git -C "$repo" config user.name 'Wrap Up Fixture'
git -C "$repo" config user.email 'fixture@example.invalid'
printf '# Test artifact\n' > "$repo/artifact.md"
git -C "$repo" add -- artifact.md
git -C "$repo" commit -qm 'test: preserve wrap-up fixture'
git init -q --bare "$root/qualification-remote.git"
git -C "$repo" remote add origin "$root/qualification-remote.git"
git -C "$repo" push -qu origin HEAD
head=$(git -C "$repo" rev-parse HEAD)
remote=$(git -C "$repo" ls-remote origin "$(git -C "$repo" symbolic-ref HEAD)" | cut -f1)
[[ $head == "$remote" && -z $(git -C "$repo" status --porcelain) ]]
printf '# Session state\n## Resume here\nNext: operator test.\n## Session summary\nFixture committed.\n## Verification\nLocal remote verified: %s\n' "$head" > "$root/session-draft.md"
wrap-up-state save "$root/session-draft.md"
wrap-up-state save "$root/session-draft.md"
[[ $(find "$root/session-state" -maxdepth 1 -name '*.md' | wc -l) == 1 ]]
[[ $(find "$root/session-state/archive" -name '*.md' | wc -l) == 1 ]]
test -r "$HOME/.$([[ $agent == wrap-check ]] && echo codex || echo claude)/skills/wrap-up/SKILL.md"
# Missing payload must fail without rotating the valid current pair.
if wrap-up-state save "$root/absent.md"; then exit 1; fi
[[ $(find "$root/session-state/archive" -name '*.md' | wc -l) == 1 ]]
rm -- "$root/session-draft.md"
echo 'WRAP_AGENT_PASS shared-state=readable rotation=verified git=local-fixture failure=honest'
