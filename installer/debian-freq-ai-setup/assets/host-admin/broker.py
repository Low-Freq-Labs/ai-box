#!/usr/bin/python3 -I
"""Closed host operations, authenticated by SO_PEERCRED; never a root shell API."""
import base64
import fcntl
import grp
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path('/etc/freq-ai-setup/host-admin')
STATE = ROOT / 'private/state.json'
REGISTRY = Path('/etc/freq-ai-setup/agents.d')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}
NAME = re.compile(r'[a-z][a-z0-9-]{0,31}')
LABEL = re.compile(r'[A-Z][A-Z0-9._-]{0,47}')
CAPS = {'diagnostics', 'smb', 'network', 'services', 'packages'}
SERVICES = ('cron.service', 'rsyslog.service', 'systemd-timesyncd.service')
LIMIT = 65536


def require(condition, message):
    if not condition:
        raise ValueError(message)


def trusted(path):
    meta = path.lstat()
    require(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and not meta.st_mode & 0o022,
            'unsafe managed configuration')
    return path.read_text()


def atomic(path, data, mode=0o600):
    # All parents are root-owned; no caller-supplied paths reach this function.
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load():
    return json.loads(trusted(STATE))


def save(state):
    atomic(STATE, json.dumps(state, sort_keys=True, indent=2) + '\n')


def run(argv, *, data=None, timeout=30, check=True, group=None, user=None, pass_fds=()):
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, env=ENV, start_new_session=True,
                               group=group, user=user, extra_groups=[] if user is not None else None,
                               pass_fds=pass_fds)
    try:
        output, _ = process.communicate(None if data is None else data.encode(), timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise ValueError('operation timed out; inspect status before retrying') from None
    if check and process.returncode:
        # Do not echo subprocess arguments/output: mount failures can contain credentials.
        raise ValueError(f'{Path(argv[0]).name} failed (exit {process.returncode}); inspect host status')
    return output.decode(errors='replace')[:12000]


def agents():
    result = []
    for path in REGISTRY.glob('*.conf'):
        if NAME.fullmatch(path.stem):
            trusted(path)
            result.append(path.stem)
    return sorted(result)


def operator(uid):
    if uid == 0:
        return True
    for line in trusted(Path('/etc/freq-ai-setup/site.conf')).splitlines():
        if line.startswith(('FREQ_MASTER_USER=', 'export FREQ_MASTER_USER=')):
            return pwd.getpwnam(shlex.split(line.split('=', 1)[1])[0]).pw_uid == uid
    return False


def fields(request, required):
    require(set(request) == set(required.split()), 'unexpected or missing request fields')


def name(value):
    require(isinstance(value, str) and NAME.fullmatch(value), 'invalid name (lowercase letters, digits, hyphens; max 32)')
    return value


def public_key(value):
    require(isinstance(value, str) and len(value) <= 8192 and '\n' not in value and '\r' not in value,
            'supply one SSH public key, without options')
    parts = value.split()
    require(len(parts) >= 2 and parts[0] in ('ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256'), 'unsupported public key')
    try:
        blob = base64.b64decode(parts[1], validate=True)
        length = struct.unpack('!I', blob[:4])[0]
        require(blob[4:4 + length].decode() == parts[0] and len(blob) > length + 8, 'public key type mismatch')
    except (ValueError, UnicodeError, struct.error):
        raise ValueError('invalid public key encoding') from None
    normalized = ' '.join(parts[:2])
    # OpenSSH validates the entire key structure, not just its encoded type.
    run(['/usr/bin/ssh-keygen', '-l', '-f', '/dev/stdin'], data=normalized + '\n')
    return normalized


def label(value, names):
    require(isinstance(value, str) and LABEL.fullmatch(value), 'label must be uppercase letters, digits, dot, hyphen or underscore; max 48')
    require(value not in {'SONNY', 'SONNY-MSG', 'STARTUP-MSG', 'BOARD-ALERT'} | {a.upper() + '-MSG' for a in names},
            'label is reserved for an existing message identity')
    return value


def keys(state):
    lines = [f'restrict,command="freq-alert-ingress {source["token"]}" {source["key"]}\n'
             for source in state['sources'].values() if source['enabled']]
    atomic(ROOT / 'authorized_keys', ''.join(lines), 0o644)


def alert(state, actor, is_operator, request, names, uid):
    action = request.get('action')
    if action == 'show':
        fields(request, 'area action')
        return json.dumps({k: {f: v[f] for f in ('owner', 'label', 'recipient', 'enabled')}
                           for k, v in state['sources'].items() if is_operator or v['owner'] == actor and v['owner_uid'] == uid}, indent=2)
    source_name = name(request.get('source'))
    source = state['sources'].get(source_name)
    if action == 'add':
        fields(request, 'area action source label recipient key')
        require(source is None, 'source already exists')
        require(sum(v['owner'] == actor for v in state['sources'].values()) < 32, 'source limit reached (32 per owner)')
        require(len(state['sources']) < 256, 'host source limit reached')
        source = {'owner': actor, 'owner_uid': uid, 'token': secrets.token_hex(16), 'enabled': True}
    else:
        require(source is not None and (is_operator or source['owner'] == actor and source['owner_uid'] == uid), 'source unavailable or owned by another agent')
    if action in ('add', 'update'):
        if action == 'update':
            fields(request, 'area action source label recipient')
        source['label'] = label(request['label'], names)
        require(request['recipient'] in names, 'recipient must be a registered agent')
        source['recipient'] = request['recipient']
        source['recipient_uid'] = pwd.getpwnam(request['recipient']).pw_uid
    if action in ('add', 'key'):
        if action == 'key':
            fields(request, 'area action source key')
        key = public_key(request['key'])
        require(all(k == source_name or v['key'] != key for k, v in state['sources'].items()), 'key is already assigned to another source')
        source['key'] = key
        source['token'] = secrets.token_hex(16)  # Invalidate any already-authenticated old connection.
    elif action in ('disable', 'enable', 'remove'):
        fields(request, 'area action source')
        source['enabled'] = action == 'enable'
    elif action == 'send':
        fields(request, 'area action source body')
        return deliver(source_name, source, request['body'], names)
    else:
        require(action == 'update', 'unsupported alert action')
    if action == 'remove':
        del state['sources'][source_name]
    else:
        state['sources'][source_name] = source
    save(state)
    keys(state)
    return f'{source_name}: {action} complete'


def deliver(source_name, source, body, names):
    require(source['enabled'], 'source disabled')
    owner_uid = pwd.getpwnam(source['owner']).pw_uid
    require(source['recipient'] in names and owner_uid == source['owner_uid'] and
            (source['owner'] in names or operator(owner_uid)) and
            pwd.getpwnam(source['recipient']).pw_uid == source['recipient_uid'],
            'source owner or recipient is unavailable or was recreated')
    require(isinstance(body, str) and body.strip() and len(body.encode()) <= 32768, 'body must contain 1–32768 bytes of text')
    require(all(c in '\n\t' or ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in body), 'body contains terminal control characters')
    # Hand authenticated metadata over a root-owned 0600 inherited descriptor.
    # Drop to the recipient before touching its writable inbox/socket/lock paths.
    # A malicious agent cannot use a symlink in those paths to gain root writes.
    account = pwd.getpwnam(source['recipient'])
    fd = os.memfd_create('freq-service-authority', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w+b') as authority:
        authority.write(json.dumps({'source': source_name, 'label': source['label'], 'recipient': source['recipient']}).encode())
        authority.flush(); authority.seek(0)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
        return run(['/usr/local/bin/dev-msg', '--service', str(authority.fileno())], data=body,
                   timeout=15, user=account.pw_uid, group=grp.getgrnam('freq-agents').gr_gid,
                   pass_fds=(authority.fileno(),)).strip()


def mount_name(value):
    value = name(value)
    require(value not in ('c', 'wsl', 'wslg'), 'reserved mount name')
    return value


def share(value):
    require(isinstance(value, str) and re.fullmatch(r'//[A-Za-z0-9][A-Za-z0-9.-]{0,252}/[A-Za-z0-9_.$-]+(?:/[A-Za-z0-9_.$-]+)*', value),
            'share must be //server/share[/folder], without options or whitespace')
    require(all(p not in ('.', '..') for p in value[2:].split('/')), 'relative share components are forbidden')
    return value


def mount_unit(mount):
    return 'mnt-' + mount.replace('-', '\\x2d') + '.mount'


def mount_path(mount):
    root = Path('/mnt')
    meta = root.lstat()
    require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == 0 and not meta.st_mode & 0o022, 'unsafe /mnt directory')
    path = root / mount
    if path.exists() or path.is_symlink():
        meta = path.lstat()
        require(stat.S_ISDIR(meta.st_mode) and not stat.S_ISLNK(meta.st_mode) and meta.st_uid == 0,
                'mount path must be a root-owned directory, never a symlink')
    return path


def smb(state, request):
    verb = request['verb']
    if verb == 'show':
        fields(request, 'area action verb')
        return json.dumps(state['mounts'], indent=2) + '\n' + run(['/usr/bin/findmnt', '-t', 'cifs', '-o', 'TARGET,SOURCE,OPTIONS'], check=False)
    mount = mount_name(request.get('name'))
    unit = mount_unit(mount)
    path = mount_path(mount)
    unit_path = Path('/etc/systemd/system') / unit
    if verb == 'add':
        fields(request, 'area action verb name share username password domain')
        unc = share(request['share'])
        require(mount not in state['mounts'] and not unit_path.exists() and not unit_path.is_symlink(), 'mount already managed or unit exists')
        require(not path.exists(), 'mount path already exists; operator must review it before adoption')
        require(len(state['mounts']) < 32, 'shared mount limit reached')
        for key in ('username', 'password', 'domain'):
            value = request[key]
            require(isinstance(value, str) and len(value) <= 1024 and not any(c in value for c in '\r\n\0'), 'invalid credential field')
        require(request['username'] and request['password'], 'SMB username and password are required')
        credential = ROOT / 'private' / ('smb-' + mount)
        require(not credential.exists(), 'credential already exists; operator review required')
        atomic(credential, ''.join(f'{k}={request[k]}\n' for k in ('username', 'password', 'domain') if request[k]))
        path.mkdir(mode=0o755)
        options = f'credentials={credential},vers=3.0,uid=0,gid={grp.getgrnam("freq-agents").gr_gid},forceuid,forcegid,file_mode=0660,dir_mode=0770,nounix,nosuid,nodev,noexec,_netdev'
        atomic(unit_path, f'[Unit]\nDescription=FREQ shared SMB {mount}\nWants=network-online.target\nAfter=network-online.target\n\n[Mount]\nWhat={unc}\nWhere={path}\nType=cifs\nOptions={options}\nTimeoutSec=25\n\n[Install]\nWantedBy=remote-fs.target\n', 0o644)
        state['mounts'][mount] = {'share': unc, 'path': str(path), 'unit': unit}
        save(state)
        run(['/usr/bin/systemctl', 'daemon-reload'])
        run(['/usr/bin/systemctl', 'enable', unit])
        run(['/usr/bin/systemctl', 'start', unit])
        return f'{unc} mounted globally at {path}; shared by all agents'
    fields(request, 'area action verb name')
    require(mount in state['mounts'], 'only mounts created by host-admin can be managed')
    require(verb in ('mount', 'unmount', 'remove'), 'unsupported SMB action')
    if verb == 'mount':
        run(['/usr/bin/systemctl', 'start', unit])
    else:
        run(['/usr/bin/systemctl', 'stop', unit])
        if verb == 'remove':
            run(['/usr/bin/systemctl', 'disable', unit])
            # Preserve configuration and credentials; never remove remote share contents.
            archive = ROOT / 'private' / ('removed-' + mount + '-' + secrets.token_hex(8))
            archive.mkdir(mode=0o700)
            # /etc/systemd and the private store may be on different filesystems.
            archived_unit = archive / unit
            atomic(archived_unit, trusted(unit_path), stat.S_IMODE(unit_path.stat().st_mode))
            require(archived_unit.read_bytes() == unit_path.read_bytes(), 'mount unit archive verification failed')
            unit_path.unlink()
            os.rename(ROOT / 'private' / ('smb-' + mount), archive / 'credentials')
            path.rmdir()  # Empty local mountpoint only; fails closed if unexpected content exists.
            del state['mounts'][mount]
            save(state)
            run(['/usr/bin/systemctl', 'daemon-reload'])
    return f'{mount}: {verb} complete'


def route_values(request):
    name(request['name'])
    try:
        destination = ipaddress.IPv4Network(request['destination'], strict=True)
        gateway = ipaddress.IPv4Address(request['gateway'])
    except (ValueError, TypeError):
        raise ValueError('use an IPv4 network/prefix and IPv4 gateway') from None
    require(destination.prefixlen > 0 and not destination.is_multicast and not destination.is_loopback,
            'default, loopback and multicast routes require operator management')
    require(not gateway.is_unspecified and not gateway.is_multicast and not gateway.is_loopback, 'invalid gateway')
    require(isinstance(request['interface'], str) and re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,14}', request['interface']), 'invalid interface')
    return {k: request[k] for k in ('destination', 'gateway', 'interface')}


def route_command(verb, entry):
    return ['/usr/sbin/ip', '-4', 'route', verb, entry['destination'], 'via', entry['gateway'],
            'dev', entry['interface'], 'proto', '186', 'metric', '42700']


def rollback(state, token):
    pending = state.get('pending')
    if not pending or pending['token'] != token:
        return 'no matching pending change'
    if pending.get('kind') == 'interfaces':
        import network_file
        return network_file.restore(sys.modules[__name__], state)
    entry = pending['entry']
    rows = json.loads(run(['/usr/sbin/ip', '-j', '-4', 'route', 'show', 'exact', entry['destination']]))
    matching = [r for r in rows if r.get('gateway') == entry['gateway'] and r.get('dev') == entry['interface']
                and r.get('metric') == 42700 and str(r.get('protocol')) == '186']
    if pending['verb'] == 'route-add':
        if matching:
            run(route_command('del', entry))
    elif not matching:
        require(not rows, 'rollback destination changed outside this tool; operator review required')
        run(route_command('add', entry))
    state['pending'] = None
    save(state)
    return 'network change rolled back'


def network(state, request, actor):
    verb = request['verb']
    if verb in ('get-interfaces', 'apply-interfaces'):
        import network_file
        if verb == 'get-interfaces':
            fields(request, 'area action verb')
            return json.dumps(network_file.snapshot(sys.modules[__name__]))
        fields(request, 'area action verb sha256 content')
        return network_file.prepare(sys.modules[__name__], state, actor, request)
    if verb == 'show':
        fields(request, 'area action verb')
        return run(['/usr/sbin/ip', '-brief', 'address']) + run(['/usr/sbin/ip', '-4', 'route']) + json.dumps({'managed': state['routes'], 'pending': state.get('pending')}, indent=2)
    if verb == 'confirm':
        fields(request, 'area action verb token')
        pending = state.get('pending')
        require(pending and pending['token'] == request['token'] and pending['actor'] == actor,
                'no pending change owned by this caller with that token')
        require(time.time() < pending['deadline'], 'confirmation expired; automatic rollback is due')
        if pending.get('kind') == 'interfaces':
            require(pending.get('status') == 'applied', 'interfaces apply has not succeeded; rollback remains armed')
        elif pending['verb'] == 'route-add':
            state['routes'][pending['name']] = pending['entry']
        else:
            del state['routes'][pending['name']]
        state['pending'] = None
        save(state)
        run(['/usr/bin/systemctl', 'stop', 'freq-host-rollback-' + request['token'] + '.timer'])
        return ('interfaces change' if pending.get('kind') == 'interfaces' else 'route change') + ' confirmed and persisted'
    require(not state.get('pending'), 'another network change is pending confirmation')
    require(verb in ('route-add', 'route-remove'), 'unsupported network action')
    if verb == 'route-add':
        fields(request, 'area action verb name destination gateway interface')
        entry = route_values(request)
        require(request['name'] not in state['routes'] and len(state['routes']) < 32, 'route name exists or route limit reached')
        existing = json.loads(run(['/usr/sbin/ip', '-j', '-4', 'route', 'show', 'exact', entry['destination']]))
        require(not existing, 'destination already has a host route; existing routes are not replaced')
    else:
        fields(request, 'area action verb name')
        require(name(request['name']) in state['routes'], 'only tool-managed routes can be removed')
        entry = state['routes'][request['name']]
    token = secrets.token_hex(12)
    state['pending'] = {'token': token, 'actor': actor, 'verb': verb, 'name': request['name'],
                        'entry': entry, 'deadline': time.time() + 120}
    save(state)
    try:
        run(['/usr/bin/systemd-run', '--quiet', '--unit=freq-host-rollback-' + token, '--on-active=120s',
             '/usr/bin/python3', '-I', '/usr/local/libexec/freq-ai-setup/host-admin/broker.py', '--rollback', token])
    except (OSError, ValueError):
        state['pending'] = None; save(state)
        raise
    # Keep pending state on an uncertain ip failure: the armed timer reconciles it.
    run(route_command('add' if verb == 'route-add' else 'del', entry))
    return f'Applied temporarily. Check connectivity, then within 120 seconds run:\nhost-admin network confirm {token}\nWithout confirmation the route change is rolled back.'


def handle(uid, request):
    require(isinstance(request, dict), 'request must be an object')
    actor = pwd.getpwuid(uid).pw_name
    names = agents()
    is_operator = operator(uid)
    state = load()
    area = request.get('area')
    if area == 'ingress':
        fields(request, 'area token body')
        require(actor == 'freq-alerts', 'ingress requires the alert SSH account')
        matches = [(k, v) for k, v in state['sources'].items() if v['token'] == request['token']]
        require(len(matches) == 1, 'alert source is unavailable')
        return deliver(*matches[0], request['body'], names)
    require(is_operator or actor in names, 'only the operator or a registered agent may use this endpoint')
    if area == 'own-crontab':
        import own_crontab
        return own_crontab.handle(sys.modules[__name__], request, actor, uid, names)
    if area == 'alerts':
        return alert(state, actor, is_operator, request, names, uid)
    if area == 'admin':
        require(is_operator, 'only the operator can grant or revoke host capabilities')
        action = request.get('action')
        if action in ('grant-scoped','revoke-scoped','show-scoped','approve-plan'):
            import maintenance
            return maintenance.grant(sys.modules[__name__],state,request,actor,names)
        if action == 'show':
            fields(request, 'area action')
            return json.dumps(state['grants'], indent=2)
        fields(request, 'area action agent capabilities')
        require(action in ('grant', 'revoke') and request['agent'] in names, 'unknown action or agent')
        caps = request['capabilities']
        require(isinstance(caps, list) and caps and all(isinstance(c, str) and c in CAPS | {'all'} for c in caps), 'unknown capability')
        wanted = CAPS if 'all' in caps else set(caps)
        agent_uid = pwd.getpwnam(request['agent']).pw_uid
        current = set(state['grants'].get(request['agent'], [])) if state.get('grant_uids', {}).get(request['agent']) == agent_uid else set()
        state['grants'][request['agent']] = sorted(current | wanted if action == 'grant' else current - wanted)
        state.setdefault('grant_uids', {})[request['agent']] = agent_uid
        save(state)
        return f'{request["agent"]}: ' + (', '.join(state['grants'][request['agent']]) or 'no host-management capabilities')
    if area in ('board-maintenance','storage-budget','coms-maintenance','coms-status'):
        import maintenance
        return maintenance.dispatch(sys.modules[__name__],state,request,actor,uid,is_operator)
    require(area == 'host', 'unsupported request area')
    action = request.get('action')
    if action == 'tooling':
        import tooling
        return json.dumps(tooling.dispatch(sys.modules[__name__],state,request,actor,uid,is_operator),indent=2)
    capability = 'diagnostics' if action == 'status' else action
    require(capability in CAPS and (is_operator or capability in state['grants'].get(actor, []) and
            state.get('grant_uids', {}).get(actor) == uid), 'operator has not granted this host capability')
    if action == 'status':
        fields(request, 'area action')
        return run(['/usr/bin/df', '-h', '/', '/mnt']) + run(['/usr/sbin/ip', '-brief', 'address']) + run(['/usr/bin/systemctl', '--failed', '--no-pager', '--no-legend'])
    if action == 'smb':
        return smb(state, request)
    if action == 'network':
        return network(state, request, actor)
    if action == 'packages':
        import packages
        return packages.handle(sys.modules[__name__], request, actor, uid)
    if request.get('verb') == 'show':
        fields(request, 'area action verb')
        return '\n'.join(SERVICES)
    fields(request, 'area action verb unit')
    require(request['unit'] in SERVICES and request['verb'] in ('status', 'restart'), 'service or operation is not approved')
    if request['verb'] == 'restart':
        run(['/usr/bin/systemctl', 'restart', request['unit']])
    return run(['/usr/bin/systemctl', 'show', request['unit'], '-p', 'ActiveState,SubState,Result'], check=False)


def locked():
    stream = open('/run/lock/freq-host-admin.lock', 'a')
    fcntl.flock(stream, fcntl.LOCK_EX)
    return stream


def main():
    require(os.geteuid() == 0, 'broker requires root')
    if len(sys.argv) > 1:
        if len(sys.argv) == 3 and sys.argv[1] == '--apply-interfaces':
            import network_file
            network_file.apply_worker(sys.modules[__name__], sys.argv[2])
            return
        with locked():
            state = load()
            if len(sys.argv) == 3 and sys.argv[1] == '--rollback':
                print(rollback(state, sys.argv[2])); return
            if sys.argv[1:] == ['--recover-config']:
                if state.get('pending') and state['pending'].get('kind') == 'interfaces':
                    import network_file
                    print(network_file.restore(sys.modules[__name__], state, boot=True))
                return
            require(sys.argv[1:] == ['--restore-routes'], 'unsupported internal action')
            # Pending changes are intentionally never restored across reboot.
            require(not state.get('pending') or state['pending'].get('kind') != 'interfaces', 'unconfirmed interfaces edit needs boot recovery first')
            state['pending'] = None; save(state)
            for entry in state['routes'].values():
                run(route_command('add', entry))
            return
    require(os.environ.get('LISTEN_PID') == str(os.getpid()) and os.environ.get('LISTEN_FDS') == '1', 'start through the systemd socket')
    server = socket.socket(fileno=3)
    while True:
        client, _ = server.accept()
        uid = -1
        operation = 'invalid'
        with client:
            client.settimeout(5)
            try:
                _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                data = bytearray()
                while part := client.recv(4096):
                    data.extend(part)
                    require(len(data) <= LIMIT, 'request too large')
                request = json.loads(data)
                if isinstance(request, dict):
                    operation = str(request.get('area', '')) + ':' + str(request.get('action', 'submit'))
                    operation = re.sub(r'[^a-z:-]', '?', operation)[:64]
                with locked():
                    result = handle(uid, request)
                response = {'ok': True, 'message': result}
            except (OSError, ValueError, KeyError, TypeError) as error:
                if isinstance(error, OSError):
                    print(json.dumps({'error_type':type(error).__name__, 'errno':error.errno,
                                      'location':[(f.name, f.lineno) for f in traceback.extract_tb(error.__traceback__)]}), flush=True)
                response = {'ok': False, 'message': str(error)[:500]}
            print(json.dumps({'uid': uid, 'operation': operation, 'ok': response['ok']}), flush=True)
            try:
                client.sendall(json.dumps(response).encode())
            except OSError:
                pass  # Never retry an operation because the caller disconnected.


if __name__ == '__main__':
    main()
