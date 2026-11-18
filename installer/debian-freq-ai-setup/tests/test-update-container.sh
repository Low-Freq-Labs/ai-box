#!/bin/bash
set -euo pipefail
[[ -f /run/.containerenv ]] || { echo 'Disposable container required' >&2; exit 2; }
source=/work/debian-freq-ai-setup
install -m 0755 "$source/tests/policy-rc.d" /usr/sbin/policy-rc.d
bash "$source/assets/install-dev-apt" "$source/assets/packages"
install -d /opt/freq-agents/toolchain /opt/freq-agents/devtools /opt/freq-agents/npm-global /etc/freq-ai-setup
cp -a /seed-node/. /opt/freq-agents/toolchain/
cp -a /seed-dev/. /opt/freq-agents/devtools/
for command in node npm npx codex claude; do
    ln -s "/opt/freq-agents/toolchain/node-current/bin/$command" "/usr/local/bin/$command"
done
for binary in /opt/freq-agents/devtools/current/bin/*; do
    ln -s "$binary" "/usr/local/bin/${binary##*/}"
done
ln -s /usr/bin/fdfind /usr/local/bin/fd
ln -s /usr/bin/batcat /usr/local/bin/bat
install -d /usr/local/share/freq-ai-setup/devtools
cp -a "$source/assets/packages" /usr/local/share/freq-ai-setup/devtools/
chown -R root:root /usr/local/share/freq-ai-setup/devtools
find /usr/local/share/freq-ai-setup/devtools -type d -exec chmod 0755 {} +
find /usr/local/share/freq-ai-setup/devtools -type f -exec chmod 0644 {} +
install -m 0755 "$source/assets/devtools-install" "$source/assets/devtools-accept" /usr/local/share/freq-ai-setup/devtools/
useradd --create-home --shell /bin/bash fixture-master
# Fixture configuration only; never the host's operator account.
install -m 0644 "$source/tests/maintenance-site.conf" /etc/freq-ai-setup/site.conf
npm install -g --prefix /opt/freq-agents/npm-global prettier@3.5.3
python3 "$source/assets/update-managed-tools" --check --plan /tmp/update-plan.json
python3 "$source/assets/update-managed-tools" --apply --plan /tmp/update-plan.json
first=$(readlink /opt/freq-agents/devtools/current)
python3 "$source/assets/update-managed-tools" --apply --plan /tmp/update-plan.json
[[ $(readlink /opt/freq-agents/devtools/current) == "$first" ]]
echo 'PASS repeat update reuses the same developer release'
python3 "$source/tests/test_maintenance.py"
python3 "$source/tests/test_devtools.py"
echo 'MANAGED_UPDATE_CONTAINER_PASS'
