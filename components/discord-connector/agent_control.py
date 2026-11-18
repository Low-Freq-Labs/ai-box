#!/usr/bin/python3
"""Local operator lifecycle bridge: fixed actions, authenticated Unix peer."""
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import stat
import struct
import subprocess

NAME = re.compile(r'[a-z][a-z0-9-]{0,31}')
REGISTRY = Path('/etc/freq-ai-setup/agents.d')
ENV = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'}


def trusted(path):
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
        raise ValueError('Unsafe root configuration')
    return path.read_text()


def settings(path):
    result = {}
    for line in trusted(Path(path)).splitlines():
        match = re.fullmatch(r"(?:export )?([A-Z_]+)=(?:'([^']*)'|([a-zA-Z0-9_./ -]+))", line)
        if match:
            result[match[1]] = match[2] if match[2] is not None else match[3]
    return result


def run(argv, timeout=30):
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=ENV, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise ValueError('Lifecycle timed out; outcome uncertain. Check /agents before retrying.')
    return process.returncode, output.decode(errors='replace')[:3000]


def agents():
    names = []
    for path in sorted(REGISTRY.glob('*.conf')):
        if not NAME.fullmatch(path.stem):
            continue
        if settings(path).get('AGENT') != path.stem:
            raise ValueError('Agent registry mismatch')
        names.append(path.stem)
    return names


def status(agent, tmux_root):
    path = Path(tmux_root) / ('agent-' + agent)
    try:
        meta = path.lstat()
    except FileNotFoundError:
        return 'stopped'
    if not stat.S_ISSOCK(meta.st_mode) or meta.st_uid != pwd.getpwnam(agent).pw_uid:
        return 'unknown'
    code, _ = run(['/usr/bin/tmux', '-S', str(path), 'list-sessions'], 2)
    return 'running' if code == 0 else 'stopped'


def handle(request):
    if not isinstance(request, dict) or request.get('action') not in ('list', 'start', 'stop'):
        raise ValueError('Unsupported action')
    action = request['action']
    if set(request) != ({'action'} if action == 'list' else {'action', 'agent'}):
        raise ValueError('Unexpected request fields')
    names = agents()
    tmux_root = settings('/etc/freq-ai-setup/coms.conf')['FREQ_COMS_TMUX_DIR']
    if action == 'list':
        return {'ok': True, 'agents': {name: status(name, tmux_root) for name in names}}
    agent = request['agent']
    if not isinstance(agent, str) or agent not in names:
        raise ValueError('Unknown registered agent')
    current = status(agent, tmux_root)
    expected = 'stopped' if action == 'start' else 'running'
    if current != expected:
        raise ValueError(f'{agent} is {current}; refresh /agents.')
    site = settings('/etc/freq-ai-setup/site.conf')
    master = site['FREQ_MASTER_USER']
    master_uid = pwd.getpwnam(master).pw_uid
    root = Path(site['FREQ_MASTER_HOME']) / 'agents'
    script = root / agent / f'{agent}-{action}'
    for path in (root, root / agent, script):
        meta = path.lstat()
        if stat.S_ISLNK(meta.st_mode) or meta.st_uid != master_uid or meta.st_mode & 0o022:
            raise ValueError('Unsafe lifecycle path')
    if not script.is_file():
        raise ValueError('Lifecycle script unavailable')
    code, output = run(['/usr/sbin/runuser', '-u', master, '--', '/bin/bash', str(script)])
    after = status(agent, tmux_root)
    target = 'running' if action == 'start' else 'stopped'
    return {'ok': code == 0 and after == target, 'message': output or f'{agent}: {after}', 'state': after}


def main():
    expected_uid = pwd.getpwnam('freq-discord').pw_uid
    if int(os.environ.get('LISTEN_PID', '0')) != os.getpid() or os.environ.get('LISTEN_FDS') != '1':
        raise SystemExit('Use the systemd socket unit')
    server = socket.socket(fileno=3)
    while True:
        connection, _ = server.accept()
        with connection:
            connection.settimeout(5)
            _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != expected_uid:
                continue
            try:
                data = b''
                while not data.endswith(b'\n') and len(data) <= 1024:
                    chunk = connection.recv(1025 - len(data))
                    if not chunk:
                        break
                    data += chunk
                if len(data) > 1024 or not data.endswith(b'\n'):
                    raise ValueError('Invalid request size/framing')
                result = handle(json.loads(data))
            except (ValueError, OSError, KeyError) as error:
                result = {'ok': False, 'message': str(error)}
            try:
                connection.sendall(json.dumps(result).encode() + b'\n')
            except OSError:
                pass


if __name__ == '__main__':
    main()
