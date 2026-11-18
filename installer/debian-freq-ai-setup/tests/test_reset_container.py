"""Actual agent-only reset against disposable Linux accounts and fixture data."""
import hashlib
import os
from pathlib import Path
import pwd
import shutil
import subprocess

assert Path('/run/.containerenv').is_file(), 'disposable container required'
SOURCE = Path('/work/debian-freq-ai-setup/assets')
prior_archives = set(Path('/home/freq-agents/staging/archive').glob('*/*/mockup.md'))
def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)
def directory(path, user='root', group='root', mode='0755'):
    run('install', '-d', '-o', user, '-g', group, '-m', mode, str(path))
def file(path, text):
    Path(path).write_text(text)
    Path(path).chmod(0o644)
if subprocess.run(['getent', 'group', 'freq-agents'], stdout=subprocess.DEVNULL).returncode:
    run('groupadd', 'freq-agents')
root = Path('/etc/freq-ai-setup')
directory(root / 'agents.d'); directory(root / 'identities')
directory('/run/freq-agents/tmux', group='freq-agents', mode='2770')
directory('/run/freq-agents/board-alert')
directory('/home/freq-agents/staging', group='freq-agents', mode='2750')
run('setfacl', '-m', 'u:fixture-master:rx', '/home/freq-agents/staging')
directory('/home/freq-agents/projects', group='freq-agents', mode='2770')
directory('/var/lib/freq-agents/coms', group='freq-agents', mode='0750')
directory('/usr/local/libexec/freq-ai-setup')
directory('/opt/freq-agents/board-system')
shutil.copytree(SOURCE / 'board-system/lib', '/opt/freq-agents/board-system/lib', dirs_exist_ok=True)
for helper in ('delete-agent', 'retire-agent-data'):
    run('install', '-m', '0755', str(SOURCE / helper), '/usr/local/libexec/freq-ai-setup/' + helper)
file('/run/lock/freq-ai-maintenance.lock', '')
file(root / 'coms.conf', "FREQ_COMS_TMUX_DIR='/run/freq-agents/tmux'\nFREQ_COMS_ROOT='/var/lib/freq-agents/coms'\n")
file(root / 'board.conf', "FREQ_BOARD_ROOT='/var/lib/freq-agents/board'\n")
project = Path('/var/lib/freq-agents/board/projects/FIXTURE')
if project.exists():
    assert project.resolve() == project and not project.is_symlink()
    shutil.rmtree(project)  # reset only this disposable test's previous fixture
for state in ('active', 'ready', 'blocked', 'done'):
    directory(project / state, group='freq-agents', mode='2770')
file(project / 'blocked/Waiting.md', '# Waiting\nDependency remains missing.\n')
file(project / 'done/Finished.md', '# Finished\nVerified result.\n')
file('/home/freq-agents/projects/durable.txt', 'DURABLE PROJECT DATA\n')
protected = [project / 'blocked/Waiting.md', project / 'done/Finished.md', Path('/home/freq-agents/projects/durable.txt')]
before = {p: p.read_bytes() for p in protected}
for name, runtime in [('fixture-one', 'codex'), ('fixture-two', 'claude')]:
    if subprocess.run(['getent', 'passwd', name], stdout=subprocess.DEVNULL).returncode:
        run('useradd', '--create-home', '--user-group', '--groups', 'freq-agents', '--shell', '/bin/bash', name)
    Path('/home', name).chmod(0o700)
    directory('/home/fixture-master/agents/' + name, 'fixture-master', 'fixture-master')
    owner = pwd.getpwnam('fixture-master')
    for action in ('start', 'connect', 'stop'):
        path = Path('/home/fixture-master/agents') / name / (name + '-' + action)
        text = (SOURCE / 'agent-lifecycle.template').read_text().replace('__AGENT__', name).replace('__PRETTY__', name.capitalize()).replace('__RUNTIME__', runtime).replace('__ACTION__', action)
        path.write_text(text)
        os.chown(path, owner.pw_uid, owner.pw_gid)
        path.chmod(0o755)
    directory('/home/freq-agents/staging/' + name, name, 'freq-agents', '2750')
    file('/home/freq-agents/staging/' + name + '/mockup.md', name + ' STAGING\n')
    directory('/var/lib/freq-agents/coms/' + name, name, 'freq-agents', '2750')
    for box in ('inbox', 'read'):
        directory('/var/lib/freq-agents/coms/' + name + '/' + box, name, 'freq-agents', '2770')
    file(root / 'agents.d' / (name + '.conf'), f"AGENT='{name}'\nRUNTIME='{runtime}'\nCOLOR='green'\n")
    file(root / 'identities' / (name + '.conf'), f"FREQ_USER='{name}'\n")
    directory(project / 'active' / name, group='freq-agents', mode='2770')
    file(project / 'active' / name / (name + '.md'), '# Exact title\nKeep full task intent.\n')
run('bash', str(SOURCE / 'level-set'), '--dry-run')
assert pwd.getpwnam('fixture-one')
run('bash', str(SOURCE / 'level-set'), input='LEVEL-SET\n', text=True)
for name in ('fixture-one', 'fixture-two'):
    assert subprocess.run(['getent', 'passwd', name], stdout=subprocess.DEVNULL).returncode == 2
    for path in (Path('/home') / name, Path('/var/lib/freq-agents/coms') / name, Path('/home/fixture-master/agents') / name):
        assert not path.exists(), path
    archives = list(set(Path('/home/freq-agents/staging/archive').glob('*/' + name + '/mockup.md')) - prior_archives)
    assert len(archives) == 1 and archives[0].read_text() == name + ' STAGING\n'
    run('runuser', '-u', 'fixture-master', '--', 'cat', str(archives[0]), stdout=subprocess.DEVNULL)
    assert 'AGENT REMOVED' in (project / 'ready' / (name + '.md')).read_text()
for path, data in before.items():
    assert path.read_bytes() == data, path
assert Path('/opt/freq-agents/devtools/current').is_dir()
run('bash', str(SOURCE / 'level-set'))
print('AGENT_ONLY_RESET_CONTAINER_PASS accounts_removed=2 projects_board_tools=preserved staging=archived')
