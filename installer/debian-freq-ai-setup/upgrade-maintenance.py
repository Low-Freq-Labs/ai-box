#!/usr/bin/python3
"""Deploy maintenance/menu changes only. Does not update packages or remove agents."""
import hashlib
import fcntl
import os
from pathlib import Path
import pwd
import re
import shlex
import subprocess
import tempfile

if os.geteuid():
    raise SystemExit('root required')
assets = Path(__file__).resolve().parent / 'assets'
site = Path('/etc/freq-ai-setup/site.conf')
if site.is_symlink() or site.stat().st_uid or site.stat().st_mode & 0o022:
    raise SystemExit('unsafe site config')
values = {k.removeprefix('export '): shlex.split(v)[0] for line in site.read_text().splitlines() if '=' in line for k,v in [line.split('=',1)]}
master = pwd.getpwnam(values['FREQ_MASTER_USER'])
home = Path(values['FREQ_MASTER_HOME'])
if home.resolve() != home or home != Path(master.pw_dir):
    raise SystemExit('unexpected operator home')
known = {}
for line in Path('/etc/freq-ai-setup/source-manifest.sha256').read_text().splitlines():
    digest, path = line.split(maxsplit=1)
    known[Path(path).name] = digest
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
for name in ('create-agent', 'delete-agent', 'level-set', 'full-update', 'ai-packages-install', 'setup-coms', 'setup-board', 'setup-discord', 'agent-groups'):
    path = home / 'tools' / name
    if (path.exists() or path.is_symlink()) and (path.is_symlink() or not path.is_file() or sha(path) not in (known.get(name), sha(assets / name))):
        raise SystemExit(f'preserved modified/unrecognized tool: {path}')
internal = Path('/usr/local/libexec/freq-ai-setup')
if internal.resolve() != internal or internal.stat().st_uid or internal.stat().st_mode & 0o022:
    raise SystemExit('unsafe internal tool directory')
template = (assets / 'agent-lifecycle.template').read_text()
old_template = Path('/usr/local/share/freq-ai-setup/agent-lifecycle.template').read_text()
launchers = []
for registry in Path('/etc/freq-ai-setup/agents.d').glob('*.conf'):
    if registry.is_symlink() or not re.fullmatch('[a-z][a-z0-9-]{0,31}', registry.stem):
        raise SystemExit('unexpected registry')
    fields = {k: shlex.split(v)[0] for line in registry.read_text().splitlines() if '=' in line for k,v in [line.split('=',1)]}
    agent = registry.stem
    if fields.get('AGENT') != agent or fields.get('RUNTIME') not in ('codex', 'claude'):
        raise SystemExit('unexpected agent identity')
    for action in ('start', 'stop', 'connect'):
        path = home / 'agents' / agent / (agent + '-' + action)
        if path.is_symlink() or not path.is_file() or path.parent.resolve() != path.parent:
            raise SystemExit('unexpected launcher path')
        def render(text):
            return text.replace('__AGENT__', agent).replace('__PRETTY__', agent.capitalize()).replace('__RUNTIME__', fields['RUNTIME']).replace('__ACTION__', action)
        if path.read_text() not in (render(old_template), render(template)):
            raise SystemExit(f'preserved modified launcher: {path}')
        launchers.append((path, render(template)))
source = Path('/usr/local/src/freq-agent-sandbox.c')
if source.is_symlink() or sha(source) not in (known.get('freq-agent-sandbox.c'), sha(assets / 'freq-agent-sandbox.c')):
    raise SystemExit('preserved modified sandbox source')
subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0644', str(assets / 'freq-maintenance.conf'), '/etc/tmpfiles.d/freq-maintenance.conf'], check=True)
subprocess.run(['systemd-tmpfiles', '--create', '/etc/tmpfiles.d/freq-maintenance.conf'], check=True)
maintenance = open('/run/lock/freq-ai-maintenance.lock', 'rb')
fcntl.flock(maintenance, fcntl.LOCK_EX | fcntl.LOCK_NB)
binary = tempfile.NamedTemporaryFile(prefix='freq-maintenance-sandbox-', delete=False)
binary.close()
try:
    subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(assets / 'freq-agent-sandbox.c'), '-o', binary.name], check=True)
except BaseException:
    Path(binary.name).unlink(missing_ok=True)
    raise
subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0644', str(assets / 'discord-connector/freq_groups.py'), '/opt/freq-agents/discord-connector/freq_groups.py'], check=True)
subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0700', str(assets / 'manage-agent-groups'), str(internal / 'manage-agent-groups')], check=True)
subprocess.run(['install', '-o', master.pw_name, '-g', str(master.pw_gid), '-m', '0700', str(assets / 'agent-groups'), str(home / 'tools/agent-groups')], check=True)
for name in ('setup-coms', 'setup-board', 'setup-discord', 'ai-packages-install', 'delete-agent', 'retire-agent-data', 'update-managed-tools', 'refresh-tool-menu'):
    subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0755', str(assets / name), str(internal / name)], check=True)
subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0755', str(assets / 'configure-master-ssh-key'), str(internal / 'configure-master-ssh-key')], check=True)
for name in ('create-agent', 'delete-agent', 'level-set', 'full-update', 'update-discord', 'update-ssh-key'):
    subprocess.run(['install', '-o', master.pw_name, '-g', str(master.pw_gid), '-m', '0755', str(assets / name), str(home / 'tools' / name)], check=True)
for name in ('devtools-install', 'devtools-accept'):
    subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0755', str(assets / name), '/usr/local/share/freq-ai-setup/devtools/' + name], check=True)
subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0644', str(assets / 'freq-maintenance.conf'), '/etc/tmpfiles.d/freq-maintenance.conf'], check=True)
subprocess.run(['systemd-tmpfiles', '--create', '/etc/tmpfiles.d/freq-maintenance.conf'], check=True)
subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '4755', binary.name, '/usr/local/sbin/freq-agent-sandbox'], check=True)
Path(binary.name).unlink()
subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0644', str(assets / 'freq-agent-sandbox.c'), '/usr/local/src/freq-agent-sandbox.c'], check=True)
subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0644', str(assets / 'agent-lifecycle.template'), '/usr/local/share/freq-ai-setup/agent-lifecycle.template'], check=True)
for path, content in launchers:
    import tempfile
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.maintenance-')
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
        os.fchown(stream.fileno(), master.pw_uid, master.pw_gid)
        os.fchmod(stream.fileno(), 0o755)
    os.replace(name, path)
for name in ('apt-base.txt', 'apt-browser.txt'):
    subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0644', str(assets / 'packages' / name), '/usr/local/share/freq-ai-setup/devtools/packages/' + name], check=True)
cmd_list = home / 'cmd-list'
if cmd_list.is_file() and not cmd_list.is_symlink() and sha(cmd_list) == known.get('cmd-list'):
    subprocess.run(['install', '-o', master.pw_name, '-g', str(master.pw_gid), '-m', '0644', str(assets / 'cmd-list'), str(cmd_list)], check=True)
else:
    print('Preserved custom cmd-list.')
subprocess.run([str(internal / 'refresh-tool-menu')], check=True)
print('MAINTENANCE_TOOLS_INSTALLED packages=unchanged agents=unchanged projects=unchanged')
