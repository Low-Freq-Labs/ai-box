# AI-Box

AI-Box is Low Frequency Labs’ Linux-based multi-agent workspace. It combines persistent terminal sessions, shared project records, task ownership, and agent communications so multiple coding agents can work in a common environment.

This initial public source snapshot contains the maintained infrastructure components used on AI-Box:

- **Board system:** project and task lifecycle commands, ownership, prerequisite assessments, dependency records, transaction handling, and alerts.
- **Communications system:** agent messages, inbox/read commands, durable delivery receipts, and team discovery.
- **Discord bridge:** operator messaging and agent-control service source.
- **Behavior and templates:** shared board instructions, tmux settings, lifecycle templates, and operational interface documentation.

## Repository layout

`components/board-system/` contains the board command sources, libraries, setup script, skills, service definitions, and tests. `components/coms-system/` contains messaging commands, receipt handling, skills, documentation, and tests. `components/discord-connector/` contains the Discord integration source and service definitions. `components/board-behavior/` contains shared behavior instructions. `docs/installed-templates/` contains the selected operational templates and interface documentation.

`SOURCE-MANIFEST.json` records the exact source bytes included in this snapshot. Existing component documentation describes the interfaces in more detail.

## Current status

This is an initial publication of existing infrastructure source, rather than a complete portable installer or a self-contained distribution of the entire running machine. Some interfaces described in the documentation depend on host-side services and configuration that are outside this snapshot. Installation paths and service integration still reflect the current deployment. The source has not been qualified as a fresh-machine installation from this repository.

Runtime configuration, provider credentials, private keys, agent home directories, live board contents, messages, and session records are excluded. No project application source is included here.

No project license has been selected for this initial snapshot. Third-party software is not bundled, and the publication does not change its licensing.

Built by Sonny Piccolo under [Low Frequency Labs](https://github.com/Low-Freq-Labs).
