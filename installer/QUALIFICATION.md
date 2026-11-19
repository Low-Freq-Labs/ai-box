# Installer qualification — ai-box-sync-20261118-r2

This maintenance revision synchronizes the installed board retirement repair, matching instructions and regression coverage into both maintained source copies and the portable installer. Codex creation and nested launch defaults now match the maintained installed template: gpt-6.1-sol/high. No running agent configuration or service was changed.

The current selected checks passed: **92 board tests, 2 offline launch-default checks and 5 portable-integration checks**. Board tests include retirement history/transaction preservation and stale revision, changed evidence, inactive caller and peer-ownership refusals. Actual component file installation and custom-contract preservation passed inside isolated filesystem/process/network namespaces, with host root read-only. Service operations remained stubbed. An initial portable dependency fixture failed because it lacked its board-library import path; the fixture now selects its own source library and temporary test board root. All five portable checks then passed; production code was not changed to bypass a test.

Python and Bash syntax checks passed (203 Python files and 44 shell files), and six JSON inputs parsed successfully. Public-tree and all-ref Git-history scans found no secrets with the default scanner rules, no ignore file entries and inline allow comments disabled. Final source-manifest and deterministic bundle checks are recorded with the release checksum. Installer `--help` and distributed-byte readback are ordinary-user checks.

The prior ai-box-sync-20261118 baseline had 407 successful test executions across the broader core/comms/admin/Discord suites. That historical qualification is preserved in the prior source revision and release; those unchanged suites were not all rerun for this maintenance update.

**Not qualified:** a complete fresh-machine APT/toolchain installation, reboot, live model/Discord authentication or delivery, external remote-test enrollment, or disposable-container reset modules. Local fixtures and source hashes do not establish those outcomes. The live machine was not reinstalled, and no agents were restarted.

See [PORTABLE-INSTALL.md](PORTABLE-INSTALL.md) and [source maintenance](../docs/SOURCE-MAINTENANCE.md).
