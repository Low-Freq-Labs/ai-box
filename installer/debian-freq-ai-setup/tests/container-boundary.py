#!/usr/bin/python3
"""Root orchestration; probes themselves run through two real agent sandboxes.

Requires two already registered test principals. Never stops their tmux sessions,
deletes their accounts, or prunes unrelated images. Restarts container services.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import select
import shlex
import signal
import subprocess
import tempfile
import time
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('agent')
parser.add_argument('peer')
args = parser.parse_args()
assert os.getuid() == 0 and args.agent != args.peer
for name in (args.agent, args.peer):
    assert (Path('/etc/freq-ai-setup/agents.d') / (name + '.conf')).is_file()
    assert pwd.getpwnam(name).pw_dir == '/home/' + name

def command(name, argv):
    original = 'cd ' + shlex.quote('/home/' + name) + '; exec ' + shlex.join(argv)
    return ['runuser', '-u', name, '--', 'env', 'SSH_ORIGINAL_COMMAND=' + original,
            '/usr/local/sbin/freq-agent-sandbox']

def agent(name, argv, *, code=0, data=None):
    result = subprocess.run(command(name, argv), input=data, capture_output=True, text=True, timeout=120)
    if result.returncode != code:
        raise RuntimeError(f'{name}: expected {code}, got {result.returncode}: {result.stderr[-2000:]}')
    return result.stdout

def receipt(test, detail):
    print(json.dumps(dict(test=test, status='PASS', detail=detail)), flush=True)

wrap = ['/usr/local/bin/bwrap', '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev']
for name, other in ((args.agent, args.peer), (args.peer, args.agent)):
    info = json.loads(agent(name, ['/usr/local/bin/podman', 'info', '--format=json']))
    assert info['host']['security']['rootless'] is True
    assert '/home/' + name + '/' in info['store']['graphRoot']
    assert info['store']['runRoot'] == '/run/freq-container-state/' + name + '/containers'
    body = 'import socket; s=socket.socket(socket.AF_UNIX); s.connect(' + repr('/run/freq-containers/' + other + '/worker.sock') + ')'
    agent(name, ['/usr/bin/python3', '-c', body], code=1)
    agent(name, wrap + ['/usr/bin/python3', '-c', body], code=1)
receipt('per-agent isolation', 'Separate rootless stores; peer sockets denied in both shell and worker, both directions')

probe = 'import os; assert not os.path.exists("/run/systemd/private"); assert not os.path.exists("/run/dbus/system_bus_socket"); assert open("/proc/1/comm").read().strip()=="catatonit"'
agent(args.agent, wrap + ['/usr/bin/python3', '-c', probe])
receipt('host process/service boundary', 'Private PID 1; host systemd and DBus sockets absent')

for sample in ['spaces and "quotes"', '; touch /tmp/NOT-A-COMMAND', 'snowman \u2603 and $HOME']:
    output = agent(args.agent, wrap + ['/usr/bin/python3', '-c', 'import sys; print(sys.argv[1])', sample])
    assert output.strip() == sample
text = 'FREQ framed stdin\n' * 8000
assert agent(args.agent, wrap + ['/bin/cat'], data=text) == text
receipt('argv and stdin', 'Quotes, Unicode, shell metacharacters remain literal; >64 KiB stdin streamed intact')

for shell, reply, expected in [('echo TTY_READY; read answer; test "$answer" = FREQ || exit 9; exit 7', b'FREQ\n', 7),
                               ('echo TTY_READY; sleep 300', b'\x03', 130)]:
    master, slave = os.openpty()
    child = subprocess.Popen(command(args.agent, wrap + ['/bin/sh', '-c', shell]),
                             stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    try:
        output = b''
        deadline = time.monotonic() + 20
        while b'TTY_READY' not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.25)[0]:
                output += os.read(master, 4096)
        assert b'TTY_READY' in output, output
        os.write(master, reply)
        assert child.wait(timeout=10) == expected
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=10)
        os.close(master)
receipt('interactive transport', 'PTY input and nonzero exit preserved; Ctrl-C reached the foreground job and returned 130')

# The supplementary group must survive a rootless container, not merely a
# worker process or a bind directory owned by the invoking agent.
with tempfile.TemporaryDirectory(prefix='.freq-cross-agent-', dir='/home/freq-agents/projects') as shared:
    path = Path(shared)
    group = __import__('grp').getgrnam('freq-agents').gr_gid
    os.chown(path, 0, group); os.chmod(path, 0o2770)
    file = path / 'result'; file.write_text('before\n')
    os.chown(file, 0, group); os.chmod(file, 0o660)
    for name in (args.agent, args.peer):
        agent(name, ['/usr/bin/env', 'FREQ_CONTAINER_SHARED_PROBE=' + str(file),
                     '/usr/bin/python3', '/usr/local/libexec/freq-ai-setup/container-accept'])
        assert file.read_text() == 'FREQ\n'
receipt('shared group writes', 'Both agents built and ran containers writing a root-owned, group-writable project file')

# Disconnect with a foreground child that closed output: it must not occupy a
# worker slot until the one-hour deadline.
jobs = []
try:
    for _ in range(4):
        jobs.append(subprocess.Popen(command(args.agent, wrap + ['/bin/sh', '-c', 'exec >/dev/null 2>&1; sleep 60']),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     start_new_session=True))
    time.sleep(2)
    for job in jobs:
        os.killpg(job.pid, signal.SIGKILL); job.communicate(timeout=10)
    time.sleep(2)
    assert agent(args.agent, wrap + ['/bin/echo', 'RECOVERED']).strip() == 'RECOVERED'
finally:
    for job in jobs:
        if job.poll() is None:
            os.killpg(job.pid, signal.SIGKILL); job.communicate(timeout=10)
receipt('disconnect cleanup', 'Four closed-output foreground jobs disconnected; worker accepted the next job')

# No test process may survive service restart. Runtime state must be recreated
# rather than trusting an old pause PID from the previous private PID namespace.
unit = 'freq-container@' + args.agent + '.service'
image = 'localhost/freq-restart-' + uuid.uuid4().hex
container = 'freq-restart-' + uuid.uuid4().hex
with tempfile.TemporaryDirectory(prefix='.freq-restart-', dir='/home/' + args.agent) as directory:
    work = Path(directory)
    account = pwd.getpwnam(args.agent)
    os.chown(work, account.pw_uid, account.pw_gid)
    (work / 'probe.c').write_text('#include <stdio.h>\n#include <unistd.h>\nint main(int argc,char **argv){if(argc>1)sleep(300); puts("RESTART_PASS");return 0;}\n')
    (work / 'Containerfile').write_text('FROM scratch\nCOPY probe /probe\nENTRYPOINT ["/probe"]\n')
    agent(args.agent, ['cc', '-static', str(work / 'probe.c'), '-o', str(work / 'probe')])
    try:
        agent(args.agent, ['/usr/local/bin/podman', 'build', '-t', image, str(work)])
        agent(args.agent, ['/usr/local/bin/podman', 'run', '-d', '--network=none', '--name', container, image, 'sleep'])
        group_path = subprocess.check_output(['systemctl', 'show', '-p', 'ControlGroup', '--value', unit], text=True).strip()
        assert group_path.startswith('/system.slice/')
        subprocess.run(['systemctl', 'stop', unit], check=True)
        assert subprocess.check_output(['systemctl', 'show', '-p', 'Result', '--value', unit], text=True).strip() == 'success'
        cg = Path('/sys/fs/cgroup' + group_path)
        assert not cg.exists() or not (cg / 'cgroup.procs').read_text().strip()
        state = agent(args.agent, ['/usr/local/bin/podman', 'inspect', '--format', '{{.State.Running}}', container])
        assert state.strip() == 'false'
        assert agent(args.agent, ['/usr/local/bin/podman', 'run', '--rm', '--network=none', image]).strip() == 'RESTART_PASS'
    finally:
        agent(args.agent, ['/usr/local/bin/podman', 'rm', '-f', '--ignore', container])
        agent(args.agent, ['/usr/local/bin/podman', 'rmi', '--ignore', image])
receipt('service restart cleanup', 'Detached real container killed; old cgroup empty; stored container stopped and a fresh run succeeded after activation')
print('CONTAINER_BOUNDARY_PASS')
