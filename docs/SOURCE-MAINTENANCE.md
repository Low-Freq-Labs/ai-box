# Keeping AI-Box source current

The AI-Box infrastructure owner maintains this public repository and its portable Debian installer when the deployed system changes. Source synchronization is part of completing a system change and of the owner's session wrap-up.

For an owned infrastructure change:

1. Review the actual deployed program and its maintained source, then preserve the accepted revision and rollback evidence.
2. Update both the `components/` copy and the corresponding `installer/debian-freq-ai-setup/assets/` copy when both exist. Keep matching skills, documentation and meaningful infrastructure tests current.
3. Classify differences explicitly: portable setup and fresh-install behavior may intentionally differ from a configured running host. Exclude live board tasks, messages, session records, credentials, private keys, private homes, site-specific grants and unrelated project applications. Synthetic fixture project/agent names in infrastructure tests are not live project state.
4. Run checks relevant to the changed behavior, check syntax and source hashes, and scan the public tree and Git history for secrets. Rebuild the self-contained installer deterministically and verify its embedded source hashes.
5. Commit and push the reviewed source to the intended repository. Verify the remote commit, publish a versioned installer release without replacing earlier evidence, and refresh the operator's installer distribution with a verified before-image and rollback path. Read back the actual distributed bytes.
6. Report exact revisions, checks and limits. Wrap-up is incomplete if a required public-source or installer update is outstanding.

Current launch defaults match the maintained installed template: `gpt-6.1-sol` with `high` reasoning effort. This is parity with the selected deployment default, not a recommendation to migrate models. See the [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) for the settings. Existing agents' model choices and live contracts are not overwritten by a source update.

The repository includes portable setup improvements that are intentionally different from old installed setup helpers: preservation of custom agent contracts, managed stopping checks and caller-owned assessment directories. Developer-tool package inputs reflect accepted managed releases rather than old bootstrap lockfiles. Personal notification destinations and operator-specific authority grants are never exported.

A clean-machine install, reboot and real provider/Discord authentication require their own qualification. Offline fixtures and an installer `--help` check do not establish those outcomes. Never rerun the full installer on a working host just to synchronize source.
