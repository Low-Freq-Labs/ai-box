"""Operator-owned named delivery groups. No agent command or permissions."""
import json
import os
from pathlib import Path
import re
import stat
import tempfile

GROUPS = Path('/etc/freq-ai-setup/agent-groups.json')
NAME = re.compile(r'[a-z][a-z0-9-]{0,31}')
RESERVED = {'create', 'show', 'remove', 'root', 'sonny', 'freq-discord', 'freq-agents'}
LIMIT = 65536


def valid_name(name):
    return isinstance(name, str) and NAME.fullmatch(name) is not None and name not in RESERVED


def validate(raw):
    if not isinstance(raw, dict) or set(raw) != {'schema', 'groups'} or type(raw['schema']) is not int or raw['schema'] != 1:
        raise ValueError('invalid group registry schema')
    groups = raw['groups']
    if not isinstance(groups, dict) or len(groups) > 100:
        raise ValueError('expected at most 100 groups')
    for name, members in groups.items():
        if not valid_name(name) or not isinstance(members, list) or len(members) > 32:
            raise ValueError('invalid group name or more than 32 members')
        if any(not isinstance(member, str) or not NAME.fullmatch(member) for member in members) or len(set(members)) != len(members):
            raise ValueError('invalid or duplicate group member')
    return groups


def load_groups(path=GROUPS):
    # Parent is the installed, root-owned site directory; no environment override.
    if path.parent.resolve() != path.parent:
        raise ValueError('symlink in group registry path')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o027 or meta.st_nlink != 1:
            raise ValueError('unsafe group registry metadata')
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('group registry too large')
    return validate(json.loads(data))


def save_groups(groups, gid, path=GROUPS):
    raw = {'schema': 1, 'groups': groups}
    validate(raw)
    data = json.dumps(raw, sort_keys=True, indent=2) + '\n'
    if len(data.encode()) > LIMIT:
        raise ValueError('group registry too large')
    parent = path.parent.stat()
    if path.parent.resolve() != path.parent or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError('unsafe group registry directory')
    load_groups(path)  # Reject unsafe existing files before atomic replacement.
    fd, temporary = tempfile.mkstemp(prefix='.agent-groups-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
            stream.flush()
            os.fchown(stream.fileno(), 0, gid)
            os.fchmod(stream.fileno(), 0o640)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def change(groups, args, agents):
    """Validate first, then change a caller-owned snapshot."""
    if len(args) == 2 and args[0] == 'create':
        name = args[1]
        if not valid_name(name) or name in agents or name in groups:
            raise ValueError('group name is invalid, reserved, or already in use')
        if len(groups) >= 100:
            raise ValueError('maximum 100 groups')
        groups[name] = []
        return f'Created group {name}.'
    if len(args) == 2 or (len(args) == 3 and args[1] == 'remove'):
        agent, name = args[0], args[-1]
        if name not in groups:
            raise ValueError(f'unknown group: {name}')
        if len(args) == 3:
            if agent not in groups[name]:
                raise ValueError(f'{agent} is not assigned to {name}')
            groups[name].remove(agent)
            return f'Removed {agent} from {name}.'
        if agent not in agents or not NAME.fullmatch(agent):
            raise ValueError(f'unknown agent: {agent}')
        if agent in groups[name]:
            return f'{agent} is already assigned to {name}.'
        if len(groups[name]) >= 32:
            raise ValueError('maximum 32 members per group')
        groups[name] = sorted([*groups[name], agent])
        return f'Assigned {agent} to {name}.'
    raise ValueError('Usage: agent-groups create NAME | show | AGENT GROUP | AGENT remove GROUP')
