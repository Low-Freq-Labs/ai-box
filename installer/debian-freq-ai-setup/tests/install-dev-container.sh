#!/bin/bash
# Isolated package test only. Never run on the VM host.
set -euo pipefail
[[ -f /run/.containerenv ]] || { echo 'container required' >&2; exit 2; }
source=/work/debian-freq-ai-setup
install -m 0755 "$source/tests/policy-rc.d" /usr/sbin/policy-rc.d
for command in node npm npx corepack; do
    [[ ! -e /opt/test-node/bin/$command ]] || ln -sfn "/opt/test-node/bin/$command" "/usr/local/bin/$command"
done
bash "$source/assets/install-dev-apt" "$source/assets/packages"
install -d /usr/local/share/freq-ai-setup/devtools
cp -a "$source/assets/packages" /usr/local/share/freq-ai-setup/devtools/
for helper in devtools-install devtools-accept install-dev-apt; do
    install -m 0755 "$source/assets/$helper" "/usr/local/share/freq-ai-setup/devtools/$helper"
done
/usr/local/share/freq-ai-setup/devtools/devtools-install
getent passwd baseline-master >/dev/null || useradd --create-home --shell /bin/bash baseline-master
runuser -u baseline-master -- /usr/local/share/freq-ai-setup/devtools/devtools-accept
first=$(readlink /opt/freq-agents/devtools/current)
/usr/local/share/freq-ai-setup/devtools/devtools-install
test "$(readlink /opt/freq-agents/devtools/current)" = "$first"
echo 'PASS idempotent developer release'
