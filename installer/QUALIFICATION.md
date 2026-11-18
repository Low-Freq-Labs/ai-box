# Installer qualification — ai-box-sync-20261118

This revision extends the existing Debian13 amd64 installer rather than reinstalling the running AI-Box host.

The successful offline suites contain **407 test executions**:156 core/startup/group/installer checks,88 board checks,46 communications checks,80 host administration checks (including6 new own-user scheduler authorization/preservation checks),18 Discord transport/control checks, and19 attachment/core checks. These are execution counts; the core suite imports some communications test classes. Earlier stale expectations and test-environment failures were preserved, corrected, and rechecked; the final applicable checks passed. No production implementation was weakened to satisfy an old test.

Python/Bash syntax checks passed. Actual board/comms file installation, custom-contract preservation, managed Stop policy and caller-owned receipt-directory delivery passed inside isolated filesystem/process/network namespaces. The host-admin installer delivered exact program bytes and preserved existing state across two runs; service and account operations were stubbed. Fleet SSH defaults, explicit key selection, preservation and symlink refusal passed. The original deployment’s fleet key is absent from the source.

The host root was read-only in those namespaces; system directories were private. An existing dependency environment was bound read-only for offline Discord tests. No live agent was created, production service restarted, authenticated provider contacted or machine reinstalled.

**Not qualified here:** a complete clean-machine APT/toolchain install, reboot, live model/Discord authentication or delivery, external remote-test enrollment, or the two reset modules that require an actual disposable container. Use a clean target and its recovery backup. This report does not claim production acceptance or automatic Root grants.

The deterministic builder includes per-file source hashes, checked before the bootstrap executes. The release checksum file identifies the final single-file installer. Instructions are in [PORTABLE-INSTALL.md](PORTABLE-INSTALL.md).
