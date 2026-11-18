# Optional remote test client

`remote-test` submits bounded offline test packets to a separately provisioned test server. The client is included; a test server, its host identity, owner accounts, and keys are not bundled. No connection is attempted during installation. The command fails closed until enrollment exists.

An operator provisions `/etc/freq-remote-tests/client.json` as a root-owned regular file, not writable by group/others, containing only `{"host":"test-server.example"}`. Pin the verified server key in `/etc/freq-remote-tests/known_hosts`. Provision a separate restricted server identity `freq-test-<agent>` and private key `/etc/freq-remote-tests/keys/<agent>/id_ed25519` for each authorized agent; never share identities. The server must enforce the matching fixed profiles, quotas, isolation, and authenticated owner protocol. Installing this client does not provision or authorize a server.

Commands: `remote-test submit RUN INPUT.tar.gz`, `status RUN`, `results RUN NEW_PRIVATE_DIRECTORY`, `cleanup RUN RECEIPT_SHA256`, and `list`. Inspect `remote-test --help` for optional profiles supported by the enrolled server. Use one stable run ID; inspect status after uncertainty instead of resubmitting a different ID. Acceptance is not successful test completion.

The archive has a `remote_entry.py` and regular input files; the isolated entry receives `--input /input --scratch /work`. Do not include credentials or production configuration. Source remains on the development host; remote inputs and scratch are disposable. Receipts live under `/home/freq-agents/projects/infrastructure-management/remote-tests/receipts/<agent>`; provision that shared project path with private per-owner receipt directories before use.

Keep the private result directory and verification receipt intact. Cleanup verifies the exact closed owned run and retains a remote tombstone. It does not authorize deleting project source or other owners' work. Missing enrollment, quota, or reconciliation failures require operator/infrastructure resolution, not bypasses.


Phase observations: `remote-test phase-observation-v1 RUN INPUT_SHA256 --profile offline-python-v1` makes one read-only request. A successful observation reports a historical phase, not current execution or confirmed closure. Unsupported responses, transport loss, wrong bindings and malformed data yield unknown; no automatic retry, cleanup or resubmission is authorized. The separately enrolled server must support this protocol.

The launcher requires `/usr/bin/python3 -I -S`. All application modules are embedded and digest-checked before execution; caller directories, sibling modules and Python site startup files are not imported. Readable sources and the loader template are maintained alongside `build_client.py`; run that builder after edits and `build_client.py --check` before packaging. The portable client validates owner names without embedding this site's agent roster; the remote server and per-owner SSH keys remain responsible for authorization.
