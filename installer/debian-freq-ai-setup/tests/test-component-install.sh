#!/bin/bash
# Run only inside the read-only-host/private-/etc,/opt,/home,/run,/var/lib proof namespace.
set -euo pipefail
assets=$(cd "$(dirname "$0")/../assets" && pwd)
[[ ${FREQ_ISOLATED_PROOF:-} == 1 ]] || { echo 'isolated proof required' >&2; exit 2; }
mkdir -p /opt/freq-agents /etc/freq-ai-setup/agents.d /etc/systemd/system /usr/local/libexec/freq-ai-setup /usr/local/share/freq-ai-setup /root/tools
mkdir -p /usr/local/bin /usr/local/lib
cp -a "$assets/board-system" "$assets/coms-system" "$assets/board-behavior" /opt/freq-agents/
install -m 0755 "$assets/configure-stop-guard" /usr/local/libexec/freq-ai-setup/configure-stop-guard
install -m 0755 "$assets/render-agent-contract" /usr/local/libexec/freq-ai-setup/render-agent-contract
install -m 0644 "$assets/agent-contract.md" /usr/local/share/freq-ai-setup/agent-contract.md
cat >/etc/freq-ai-setup/site.conf <<'EOF'
FREQ_MASTER_USER='root'
FREQ_MASTER_GROUP='root'
FREQ_MASTER_HOME='/root'
FREQ_OPERATOR_NAME='Proof Operator'
EOF
chmod 0644 /etc/freq-ai-setup/site.conf
# No service manager exists in this namespace; unit bytes are checked separately.
printf '#!/bin/sh\nexit 0\n' >/usr/local/bin/systemctl
chmod 0755 /usr/local/bin/systemctl
bash "$assets/setup-coms" --defaults --yes
bash "$assets/setup-board" --defaults --yes
for command in task-dependencies dev-msg-status project-status task-status project-assess task-update agent-skills board-stop-hook; do
    test -x "/usr/local/bin/$command"
done
for library in freq_board_dependencies.py freq_dependency_model.py freq_board_transaction.py freq_board_inspect.py freq_coms_receipts.py freq_stop_gate.py freq_board_update.py freq_board_pause.py freq_task_identity.py freq_project_migration.py; do
    test -s "/usr/local/lib/$library"
done
for skill in task-dependencies dev-msg-status project-assess task-update agent-skills; do
    test -s "/opt/freq-agents/skills/$skill/SKILL.md"
    test -s "/opt/freq-agents/skills/$skill/agents/openai.yaml"
done
grep -Fx 'RuntimeDirectoryPreserve=yes' /etc/systemd/system/freq-board-alert@.service
grep -Fx 'ExecStart=/usr/local/libexec/freq-board-alert-watch' /etc/systemd/system/freq-board-alert@.service
/usr/local/libexec/freq-ai-setup/render-agent-contract --agent Nova --operator 'Proof Operator' >/tmp/contract.md
grep -F 'I am Nova' /tmp/contract.md
printf 'proof:x:2001:2001:Proof:/home/proof:/bin/bash\n' >>/etc/passwd
printf 'proof:x:2001:\n' >>/etc/group
mkdir -p /home/proof/.codex /root/agents/proof
chmod 0700 /home/proof
printf 'KEEP CUSTOM ROLE AND AUTHORITY\n' >/home/proof/.codex/AGENTS.md
printf 'KEEP OPERATOR COPY\n' >/root/agents/proof/AGENTS.md
printf 'model="fixture"\n' >/home/proof/.codex/config.toml
chmod 0600 /home/proof/.codex/config.toml
chown -R 2001:2001 /home/proof
printf "AGENT='proof'\nRUNTIME='codex'\n" >/etc/freq-ai-setup/agents.d/proof.conf
chmod 0644 /etc/freq-ai-setup/agents.d/proof.conf
bash "$assets/setup-board" --defaults --yes
grep -Fx 'KEEP CUSTOM ROLE AND AUTHORITY' /home/proof/.codex/AGENTS.md
grep -Fx 'KEEP OPERATOR COPY' /root/agents/proof/AGENTS.md
test "$(stat -c '%u:%a' /home/freq-agents/session-data/proof/stop-assessments)" = '2001:700'
test -x /usr/local/libexec/freq-ai-setup/codex-hooks/board-stop-hook
python3 - <<'POLICY'
import tomllib
from pathlib import Path
p=tomllib.loads(Path('/etc/codex/requirements.toml').read_text())
assert p['features']['hooks'] is True
assert len(p['hooks']['Stop']) == 1
assert p['hooks']['Stop'][0]['hooks'][0]['command'].endswith('/codex-hooks/board-stop-hook')
POLICY
printf 'COMPONENT_INSTALL_PASS systemd_execution=stubbed agent_creation=not_exercised custom_contract_preservation=verified\n'
