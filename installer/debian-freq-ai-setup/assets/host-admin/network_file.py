"""Reviewable interfaces-file editing without exposing root shell hooks."""
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import secrets
import shlex
import time
import stat

INTERFACES = Path('/etc/network/interfaces')
IFACE = re.compile(r'[A-Za-z][A-Za-z0-9_.:-]{0,14}')
DOMAIN = re.compile(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}')


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def interface(value):
    check(bool(IFACE.fullmatch(value)), 'invalid interface name')


def route_hook(words):
    check(words and words.pop(0) in ('ip', '/usr/sbin/ip', '/sbin/ip'), 'hooks may only run validated ip route commands')
    if words and words[0] in ('-4', '-6'):
        words.pop(0)
    check(len(words) >= 3 and words[:1] == ['route'] and words[1] in ('add', 'replace', 'del'), 'only ip route add/replace/del hooks are supported')
    target = words[2]
    if target != 'default':
        ipaddress.ip_network(target, strict=False)
    rest = words[3:]
    check(len(rest) % 2 == 0, 'route hook arguments must be explicit key/value pairs')
    seen = set()
    for key, value in zip(rest[::2], rest[1::2]):
        check(key not in seen, 'duplicate route hook option')
        seen.add(key)
        if key in ('via', 'src'):
            ipaddress.ip_address(value)
        elif key == 'dev':
            interface(value)
        elif key == 'metric':
            check(value.isdecimal() and 0 <= int(value) <= 65535, 'invalid route metric')
        else:
            raise ValueError('unsupported route hook option')


def validate(content):
    check(isinstance(content, str) and 0 < len(content.encode()) <= 32768, 'interfaces file must be 1–32768 bytes')
    check(all(c in '\n\t' or 32 <= ord(c) < 127 for c in content), 'interfaces file must be plain ASCII text')
    stanzas = {}
    current = None
    for number, original in enumerate(content.splitlines(), 1):
        line = original.split('#', 1)[0].strip()
        if not line:
            continue
        try:
            check(not any(c in line for c in ';|&`$\\<>"\'{}()'), 'shell syntax is not accepted in interfaces configuration')
            words = line.split()
            key, values = words[0], words[1:]
            if key in ('source', 'source-directory'):
                expected = '/etc/network/interfaces.d/*' if key == 'source' else '/etc/network/interfaces.d'
                check(values == [expected], 'includes are limited to the existing root-managed interfaces.d directory')
                current = None
            elif key in ('auto', 'allow-auto', 'allow-hotplug'):
                check(values, 'interface list is empty')
                for value in values:
                    interface(value)
                current = None
            elif key == 'iface':
                check(len(values) == 3 and values[1] in ('inet','inet6') and values[2] in ('static','dhcp','manual','loopback','auto'), 'unsupported iface declaration')
                interface(values[0])
                current = (values[0], values[1])
                check(current not in stanzas, 'duplicate interface/address-family stanza')
                stanzas[current] = [line]
            else:
                check(current is not None, 'setting must follow an iface declaration')
                check(values, 'setting has no value')
                if key == 'address':
                    check(len(values) == 1, 'address takes one value')
                    ipaddress.ip_interface(values[0])
                elif key in ('netmask','network','broadcast','gateway'):
                    check(len(values) == 1, key + ' takes one value')
                    if key == 'netmask' and values[0].isdecimal():
                        check(0 <= int(values[0]) <= 128, 'invalid prefix length')
                    else:
                        ipaddress.ip_address(values[0])
                elif key == 'dns-nameservers':
                    for value in values:
                        ipaddress.ip_address(value)
                elif key in ('dns-search','dns-domain'):
                    check(all(DOMAIN.fullmatch(value) for value in values), 'invalid DNS domain')
                elif key in ('mtu','metric','bridge_fd','bridge_maxwait','bridge_hello','bridge_maxage','vlan-id'):
                    check(len(values) == 1 and values[0].isdecimal() and 0 <= int(values[0]) <= 65535, 'invalid numeric setting')
                    if key == 'mtu':
                        check(int(values[0]) >= 576, 'MTU must be at least 576')
                elif key in ('bridge_ports','vlan-raw-device'):
                    for value in values:
                        interface(value)
                elif key == 'bridge_stp':
                    check(values in (['on'], ['off']), 'bridge_stp must be on or off')
                elif key == 'hwaddress':
                    check(len(values) == 2 and values[0] == 'ether' and re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', values[1]), 'invalid Ethernet address')
                elif key in ('pre-up','up','post-up','pre-down','down','post-down'):
                    route_hook(values.copy())
                else:
                    raise ValueError('unsupported setting: ' + key)
                stanzas[current].append(line)
        except ValueError as error:
            raise ValueError(f'line {number}: {error}') from None
    check(('lo','inet') in stanzas and stanzas[('lo','inet')] == ['iface lo inet loopback'], 'preserve the IPv4 loopback stanza unchanged')
    return stanzas


def snapshot(b):
    text = b.trusted(INTERFACES)
    return {'content': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()}


def prepare(b, state, actor, request):
    check(not state.get('pending'), 'another network change is pending')
    before = snapshot(b)
    check(request['sha256'] == before['sha256'], 'interfaces file changed since editing began; reopen it before applying')
    old = validate(before['content'])
    new = validate(request['content'])
    include = Path('/etc/network/interfaces.d')
    if include.exists():
        meta = include.lstat()
        check(stat.S_ISDIR(meta.st_mode) and meta.st_uid == 0 and not meta.st_mode & 0o022,
              'interfaces.d must remain root-owned and not writable by agents')
        for path in include.glob('*'):
            included = b.trusted(path)
            check(not re.search(r'^\s*source(?:-directory)?\s', included, re.M), 'nested network includes require operator review')
            validate('auto lo\niface lo inet loopback\n' + included)
    affected = sorted({key[0] for key in old.keys() | new.keys() if old.get(key) != new.get(key)})
    check('lo' not in affected, 'loopback changes remain operator-only')
    check(len(affected) <= 8, 'change at most eight interfaces per transaction')
    check(request['content'] != before['content'], 'no changes to apply')
    token = secrets.token_hex(12)
    backup = b.ROOT / 'private' / ('interfaces-' + token + '.before')
    b.atomic(backup, before['content'])
    state['pending'] = {'kind':'interfaces', 'token':token, 'actor':actor, 'deadline':time.time() + 120,
                        'before':str(backup), 'before_sha256':before['sha256'],
                        'after_sha256':hashlib.sha256(request['content'].encode()).hexdigest(),
                        'affected':affected, 'old_names':sorted({k[0] for k in old}),
                        'new_names':sorted({k[0] for k in new}), 'status':'prepared'}
    b.save(state)
    try:
        b.run(['/usr/bin/systemd-run','--quiet','--unit=freq-host-rollback-' + token,'--on-active=120s',
               '/usr/bin/python3','-I','/usr/local/libexec/freq-ai-setup/host-admin/broker.py','--rollback',token])
    except (OSError, ValueError):
        state['pending'] = None; b.save(state)
        raise
    b.atomic(INTERFACES, request['content'], 0o644)
    b.run(['/usr/bin/systemd-run','--quiet','--unit=freq-host-netapply-' + token,
           '--property=RuntimeMaxSec=80','--property=TimeoutStopSec=5',
           '/usr/bin/python3','-I','/usr/local/libexec/freq-ai-setup/host-admin/broker.py','--apply-interfaces',token])
    return f'Applying /etc/network/interfaces. Original saved as {backup}.\nCheck connectivity, then within 120 seconds run:\nhost-admin network confirm {token}\nIf disconnected or unconfirmed, the original configuration is restored automatically.'


def reconfigure(b, pending, restoring=False):
    old_file = str(INTERFACES) if restoring else pending['before']
    up_file = pending['before'] if restoring else str(INTERFACES)
    down_names = pending['new_names'] if restoring else pending['old_names']
    up_names = pending['old_names'] if restoring else pending['new_names']
    for iface in pending['affected']:
        if iface in down_names:
            b.run(['/usr/sbin/ifdown','--force','--interfaces',old_file,iface], timeout=20, check=False)
        if iface in up_names:
            b.run(['/usr/sbin/ifup','--force','--interfaces',up_file,iface], timeout=25)


def apply_worker(b, token):
    with b.locked():
        state = b.load(); pending = state.get('pending')
        check(pending and pending.get('kind') == 'interfaces' and pending['token'] == token, 'network edit is no longer pending')
    try:
        reconfigure(b, pending)
        status = 'applied'
    except (OSError, ValueError):
        status = 'failed'
    with b.locked():
        state = b.load()
        if state.get('pending') and state['pending']['token'] == token:
            state['pending']['status'] = status
            b.save(state)
    check(status == 'applied', 'network apply failed; rollback timer remains armed')


def restore(b, state, boot=False):
    pending = state['pending']
    errors = []
    if not boot:
        b.run(['/usr/bin/systemctl','stop','freq-host-netapply-' + pending['token'] + '.service'], check=False)
    original = b.trusted(Path(pending['before']))
    check(hashlib.sha256(original.encode()).hexdigest() == pending['before_sha256'], 'network backup hash mismatch')
    check(snapshot(b)['sha256'] in (pending['before_sha256'], pending['after_sha256']), 'interfaces file changed externally; preserved for operator review')
    if not boot:
        # Bring down edited stanzas before replacing the file they describe.
        for iface in pending['affected']:
            if iface in pending['new_names']:
                try:
                    b.run(['/usr/sbin/ifdown','--force','--interfaces',str(INTERFACES),iface], timeout=20, check=False)
                except (OSError, ValueError):
                    errors.append(iface)
    b.atomic(INTERFACES, original, 0o644)
    if not boot:
        for iface in pending['affected']:
            if iface in pending['old_names']:
                try:
                    b.run(['/usr/sbin/ifup','--force','--interfaces',str(INTERFACES),iface], timeout=25)
                except (OSError, ValueError):
                    errors.append(iface)
    if errors:
        state['pending']['status'] = 'rollback-needs-review'; b.save(state)
        raise ValueError('original interfaces file restored; interface recovery needs operator review: ' + ', '.join(sorted(set(errors))))
    state['pending'] = None; b.save(state)
    return 'original /etc/network/interfaces restored' + (' before networking startup' if boot else ' and reapplied')
