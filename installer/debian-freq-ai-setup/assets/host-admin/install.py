#!/usr/bin/python3 -I
"""Focused install/upgrade. Preserve pre-state; never restart agents or mount a share."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
DEST = Path('/usr/local/libexec/freq-ai-setup/host-admin')
ROOT = Path('/etc/freq-ai-setup/host-admin')


def run(*args):
    subprocess.run(args, check=True, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})


def main():
    if os.geteuid():
        raise SystemExit('host-admin installation requires root')
    # Validate candidate SSH syntax before writing any installed file.
    run('/usr/sbin/sshd', '-t', '-f', str(HERE / 'sshd.conf'))
    site = Path('/etc/freq-ai-setup/site.conf')
    if site.is_symlink() or site.stat().st_uid or site.stat().st_mode & 0o022:
        raise SystemExit('unsafe site config')
    values = {k.removeprefix('export '): shlex.split(v)[0] for line in site.read_text().splitlines()
              if '=' in line for k, v in [line.split('=', 1)]}
    master = pwd.getpwnam(values['FREQ_MASTER_USER'])
    menu = Path(master.pw_dir) / 'tools'
    if menu.resolve() != menu or not menu.is_dir():
        raise SystemExit('unsafe operator tools directory')
    backup = Path('/var/backups/freq-host-admin') / str(time.time_ns())
    backup.mkdir(parents=True, mode=0o700)
    backup.parent.chmod(0o700)
    records = []

    def install(source, target, mode=0o755, owner=0, group=0):
        target = Path(target)
        if target.is_symlink() or target.parent.resolve() != target.parent:
            raise SystemExit(f'unsafe destination: {target}')
        existed = target.exists()
        if existed:
            data = target.read_bytes()
            saved = backup / str(len(records))
            shutil.copy2(target, saved)
            records.append({'path': str(target), 'backup': str(saved), 'sha256': hashlib.sha256(data).hexdigest(),
                            'mode': target.stat().st_mode & 0o7777, 'uid': target.stat().st_uid, 'gid': target.stat().st_gid})
        else:
            records.append({'path': str(target), 'backup': None})
        (backup / 'manifest.json').write_text(json.dumps(records, indent=2))
        temp = target.with_name('.' + target.name + '.install-' + str(os.getpid()))
        with temp.open('xb') as stream:
            stream.write(source.read_bytes().replace(b'\r\n', b'\n'))
        os.chown(temp, owner, group); temp.chmod(mode)
        os.replace(temp, target)

    for path, mode in ((DEST, 0o755), (ROOT, 0o755), (ROOT / 'private', 0o700)):
        if path.exists() and (path.is_symlink() or path.stat().st_uid or path.stat().st_mode & 0o022):
            raise SystemExit(f'unsafe managed directory: {path}')
        path.mkdir(parents=True, exist_ok=True, mode=mode)
        path.chmod(mode)
    for item in ('broker.py', 'client.py', 'network_file.py', 'packages.py', 'alert-shell',
                 'maintenance.py', 'board_api.py', 'board_worker.py', 'coms_maintenance.py', 'coms_ledger.py', 'own_crontab.py', 'storage_budget.py', 'storage_run.py', 'control_capacity.py', 'tooling.py'):
        install(HERE / item, DEST / item)
    for command in ('service-alerts', 'host-admin', 'board-admin', 'coms-admin', 'storage-budget'):
        install(HERE / 'client.py', Path('/usr/local/bin') / command)
    install(HERE / 'agent-crontab', Path('/usr/local/bin/agent-crontab'))
    install(HERE / 'agent-crontab.md', Path('/usr/local/share/freq-ai-setup/agent-crontab.md'), 0o644)
    install(HERE / 'storage-run', Path('/usr/local/bin/storage-run'))
    install(HERE / 'storage-run.md', Path('/usr/local/share/freq-ai-setup/storage-run.md'), 0o644)
    legacy = Path('/usr/local/bin/ai-box-admin')
    if legacy.exists() or legacy.is_symlink():
        if (legacy.is_symlink() or not legacy.is_file() or legacy.stat().st_uid
                or (legacy.read_bytes() != (HERE / 'client.py').read_bytes().replace(b'\r\n', b'\n')
                    and hashlib.sha256(legacy.read_bytes()).hexdigest()
                    != '5b6e320cb15ba3d73bd8ec35a386f35a0b7cb938ada07ba6f5e9eea00994e6bf')):
            raise SystemExit('unexpected legacy host command; preserve for operator review')
        saved = backup / 'legacy-host-command'
        data = legacy.read_bytes()
        records.append({'path': str(legacy), 'backup': str(saved),
                        'sha256': hashlib.sha256(data).hexdigest(),
                        'mode': legacy.stat().st_mode & 0o7777, 'uid': 0, 'gid': legacy.stat().st_gid})
        (backup / 'manifest.json').write_text(json.dumps(records, indent=2))
        legacy.rename(saved)
    install(HERE / 'client.py', menu / 'agent-admin', 0o700, master.pw_uid, master.pw_gid)
    install(HERE / 'README.md', Path('/usr/local/share/freq-ai-setup/host-admin.md'), 0o644)
    skill_root=Path('/opt/freq-agents/skills')
    for skill in ('board-admin','coms-admin','storage-budget','host-tooling'):
        (skill_root/skill/'agents').mkdir(parents=True,exist_ok=True)
        install(HERE/'skills'/skill/'SKILL.md',skill_root/skill/'SKILL.md',0o644)
        install(HERE/'skills'/skill/'agents/openai.yaml',skill_root/skill/'agents/openai.yaml',0o644)
    if (ROOT/'private/state.json').exists():
        grants=json.loads((ROOT/'private/state.json').read_text()).get('maintenance_grants',{})
        for agent,capabilities in grants.items():
            if not capabilities: continue
            account=pwd.getpwnam(agent)
            registry=Path('/etc/freq-ai-setup/agents.d')/(agent+'.conf')
            config=registry.read_text()
            runtime='codex' if "RUNTIME='codex'" in config else 'claude' if "RUNTIME='claude'" in config else None
            if not runtime:raise ValueError('Unknown maintenance agent runtime')
            home=Path(account.pw_dir)
            if home.resolve()!=home or home.stat().st_uid!=account.pw_uid:raise ValueError('Unsafe maintenance skill home')
            for skill in ('board-admin','coms-admin','storage-budget','host-tooling'):
                destination=home/('.'+runtime)/'skills'/skill
                for directory in (destination,destination/'agents'):
                    if directory.is_symlink():raise ValueError('Unsafe skill directory')
                    directory.mkdir(mode=0o700,parents=True,exist_ok=True);os.chown(directory,account.pw_uid,account.pw_gid)
                install(HERE/'skills'/skill/'SKILL.md',destination/'SKILL.md',0o644,account.pw_uid,account.pw_gid)
                install(HERE/'skills'/skill/'agents/openai.yaml',destination/'agents/openai.yaml',0o644,account.pw_uid,account.pw_gid)
    for unit in ('freq-host-admin.socket', 'freq-host-admin.service', 'freq-host-routes.service', 'freq-host-network-recovery.service', 'freq-host-packages.service', 'freq-control-capacity.service', 'freq-control-capacity.timer'):
        install(HERE / unit, Path('/etc/systemd/system') / unit, 0o644)
    if not (ROOT / 'private/state.json').exists():
        state = {'schema': 1, 'sources': {}, 'grants': {}, 'mounts': {}, 'routes': {}, 'pending': None}
        with (ROOT / 'private/state.json').open('x') as stream:
            json.dump(state, stream)
        (ROOT / 'private/state.json').chmod(0o600)
    try:
        account = pwd.getpwnam('freq-alerts')
        if account.pw_shell != str(DEST / 'alert-shell'):
            raise SystemExit('existing freq-alerts account has an unexpected shell; preserved for review')
        if account.pw_dir == '/nonexistent':
            run('/usr/sbin/usermod', '--home', '/var/empty/freq-alerts', 'freq-alerts')
    except KeyError:
        run('/usr/sbin/useradd', '--system', '--no-create-home', '--home-dir', '/var/empty/freq-alerts',
            '--shell', str(DEST / 'alert-shell'), '--password', '*', 'freq-alerts')
    run('/usr/bin/install', '-d', '-o', 'root', '-g', 'root', '-m', '0755', '/var/empty/freq-alerts')
    sys.path.insert(0, str(HERE))
    import broker
    broker.keys(broker.load())
    install(HERE / 'sshd.conf', Path('/etc/ssh/sshd_config.d/55-freq-service-alerts.conf'), 0o644)
    run('/usr/sbin/sshd', '-t')
    reserve = Path('/var/lib/freq-control-capacity')
    # Never recreate existing state or silently replace a symlink.
    action = 'status' if reserve.exists() or reserve.is_symlink() else 'initialize'
    run('/usr/bin/python3', '-I', str(DEST / 'control_capacity.py'), action)
    run('/usr/bin/systemctl', 'daemon-reload')
    run('/usr/bin/systemctl', 'enable', '--now', 'freq-control-capacity.timer')
    run('/usr/bin/systemctl', 'enable', '--now', 'freq-host-admin.socket')
    run('/usr/bin/systemctl', 'enable', 'freq-host-routes.service')
    run('/usr/bin/systemctl', 'enable', 'freq-host-network-recovery.service')
    run('/usr/bin/systemctl', 'try-restart', 'freq-host-admin.service')
    run('/usr/bin/systemctl', 'reload', 'ssh.service')
    print(f'Installed. Pre-state manifest: {backup}/manifest.json')
    print('No host capabilities granted automatically. Use agent-admin grant AGENT CAPABILITY.')


if __name__ == '__main__':
    main()
