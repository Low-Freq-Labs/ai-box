"""Write-ahead task transitions. Call only while holding the project lock.

The immutable journal contains full before/after images and notification intent.
PREPARED is the recovery decision: finish the complete new state, never repeat
the business operation. A missing terminal receipt is not permission to resend.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid

CONTEXT = {}
MAX_BYTES = 2 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError('Not a bounded regular board file')
        data = b''
        while chunk := os.read(fd, 65536):
            data += chunk
            if len(data) > MAX_BYTES:
                raise ValueError('Board file exceeds bound')
        return data
    finally:
        os.close(fd)


def sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fault(stage):
    # Explicit fixture injection, not a production environment override.
    from freq_board import testing
    if testing() and os.environ.get('FREQ_BOARD_FAULT') == stage:
        if os.environ.get('FREQ_BOARD_FAULT_KIND') == 'kill':
            os._exit(91)
        raise OSError(28, 'Injected ENOSPC at ' + stage)


def write_new(path, data, mode=0o660):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fchmod(stream.fileno(), mode)
        os.fsync(stream.fileno())


def atomic(path, data):
    temp = path.parent / ('.pending-' + uuid.uuid4().hex)
    try:
        write_new(temp, data)
        os.replace(temp, path)
        sync(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


def revision(project, path):
    return digest(str(path.relative_to(project)).encode() + b'\0' + regular(path))


def identity(project, title):
    from freq_task_identity import identity as stable_identity
    return stable_identity(project, title)


def checked_path(project, relative):
    from freq_board import STATUSES, AGENT_RE
    parts = Path(relative).parts
    if (not isinstance(relative, str) or Path(relative).is_absolute() or
        len(parts) not in (2, 3) or parts[0] not in STATUSES or
        any(p in ('.', '..') or p.startswith('.') for p in parts) or
        not parts[-1].endswith('.md') or
        (parts[0] == 'active') != (len(parts) == 3) or
        len(parts) == 3 and not AGENT_RE.fullmatch(parts[1])):
        raise ValueError('Invalid transaction task path')
    path = project
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlink in transaction task path')
    if not path.parent.is_dir():
        raise ValueError('Missing transaction destination directory')
    return path


def journal_root(project, create=False):
    root = project / '.transactions'
    if root.is_symlink():
        raise ValueError('Unsafe transaction directory')
    if create and not root.exists():
        root.mkdir(mode=0o2770)
        root.chmod(0o2770)
        sync(project)
    return root


def aborted_before_prepare(folder):
    if not (folder/'aborted.json').exists(): return False
    marker=json.loads(regular(folder/'aborted.json'))
    files={p.name:digest(regular(p)) for p in sorted(folder.iterdir()) if p.name!='aborted.json'}
    if 'prepared.json' in files or 'committed.json' in files:
        raise ValueError('Abort marker conflicts with prepared transaction')
    value={'operation_id':str(uuid.UUID(folder.name)),'project':folder.parent.parent.name,
           'files':files,'state':'NOT_PREPARED'}
    if 'notification.json' in files:value['notification']=json.loads(regular(folder/'notification.json'))
    expected=digest(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
    if marker.get('state')!='ABORTED_BEFORE_PREPARE' or marker.get('snapshot_sha256')!=expected:
        raise ValueError('Abort marker does not match preserved journal')
    return True


def record(project, operation):
    operation = str(uuid.UUID(operation))
    folder = journal_root(project) / operation
    if folder.is_symlink():
        raise ValueError('Unsafe transaction record')
    value = json.loads(regular(folder / 'prepared.json'))
    if value['operation_id'] != operation or value['schema'] != 1:
        raise ValueError('Transaction identity mismatch')
    for field in ('source', 'target'):
        checked_path(project, value[field])
    for name in ('before', 'after'):
        if digest(regular(folder / (name + '.bin'))) != value[name + '_sha256']:
            raise ValueError('Transaction image checksum mismatch')
    for image, path, field in (('before', 'source', 'old_revision'), ('after', 'target', 'new_revision')):
        if digest(value[path].encode() + b'\0' + regular(folder / (image + '.bin'))) != value[field]:
            raise ValueError('Transaction revision mismatch')
    if Path(value['source']).name != Path(value['target']).name:
        raise ValueError('Task rename is not a supported transition')
    return folder, value


def finish(project, folder, value):
    source = checked_path(project, value['source'])
    target = checked_path(project, value['target'])
    before, after = value['before_sha256'], value['after_sha256']
    if (folder / 'committed.json').exists():
        return value
    source_hash = digest(regular(source)) if source.exists() else None
    target_hash = digest(regular(target)) if target.exists() else None
    if source == target:
        if source_hash not in (before, after):
            raise ValueError('Pending repair conflicts with current task bytes')
    elif source_hash not in (before, None) or target_hash not in (None, after):
        raise ValueError('Pending transition conflicts with current task bytes')
    if source_hash is None and target_hash != after:
        raise ValueError('Both task locations missing; retained journal requires repair')
    if target_hash != after:
        staged = folder / ('.publish-' + uuid.uuid4().hex)
        # Live files must not share an inode with preserved journal images.
        write_new(staged, regular(folder / 'after.bin'))
        fault('before_publish')
        os.replace(staged, target)
        fault('after_publish')
    # Recovery may find a published name whose directory never reached disk.
    # Always persist it before removing the source, including on replay.
    sync(target.parent)
    fault('after_target_sync')
    if source != target and source.exists():
        if digest(regular(source)) != before:
            raise ValueError('Source changed during transition recovery')
        source.unlink()
        fault('after_source_unlink')
    if source != target:
        sync(source.parent)
    fault('before_receipt')
    atomic(folder / 'committed.json', json.dumps({
        'schema': 1, 'operation_id': value['operation_id'], 'state': 'COMMITTED',
        'revision': value['new_revision'], 'notification': 'PENDING' if value.get('notification') else 'NONE'
    }, sort_keys=True).encode())
    fault('after_receipt')
    return value


def recover(project):
    root = journal_root(project)
    if not root.exists():
        return
    for folder in sorted(root.iterdir()):
        if folder.name.startswith('.'):
            continue
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError('Invalid transaction journal entry')
        if not (folder / 'prepared.json').exists():
            # Pre-prepare crash: live state was never changed. Keep evidence.
            continue
        if (folder / 'committed.json').exists():
            continue
        _, value = record(project, folder.name)
        finish(project, folder, value)


def transition(project, location, status, content, owner=None, notification=None, audit=None):
    from freq_board import current_agent
    recover(project)
    source = location['path']
    target = project / status
    if status == 'active':
        target = target / owner
    target = checked_path(project, str((target / source.name).relative_to(project)))
    before = regular(source)
    old_revision = revision(project, source)
    if CONTEXT.get('expected_revision') and CONTEXT['expected_revision'] != old_revision:
        raise ValueError('Revision conflict; current revision=' + old_revision)
    if target != source and target.exists():
        raise ValueError('Destination already exists; ownership conflict')
    after = content.encode('utf-8')
    if len(after) > MAX_BYTES:
        raise ValueError('Task exceeds transaction bound')
    operation = CONTEXT.get('operation_id') or str(uuid.uuid4())
    root = journal_root(project, True)
    folder = root / operation
    folder.mkdir(mode=0o2770)
    folder.chmod(0o2770)
    sync(root)
    value = {
        'schema': 1, 'operation_id': operation,
        'actor': current_agent(), 'request_sha256': CONTEXT.get('request_sha256'),
        'task_id': identity(project, source.stem),
        'source': str(source.relative_to(project)), 'target': str(target.relative_to(project)),
        'before_sha256': digest(before), 'after_sha256': digest(after),
        'old_revision': old_revision,
        'new_revision': digest(str(target.relative_to(project)).encode() + b'\0' + after),
        'notification': notification, 'audit': audit,
    }
    fault('before_images')
    write_new(folder / 'before.bin', before)
    fault('after_before_image')
    write_new(folder / 'after.bin', after)
    fault('after_after_image')
    sync(folder)
    atomic(folder / 'prepared.json', json.dumps(value, sort_keys=True).encode())
    fault('after_prepare')
    finish(project, folder, value)
    print('OPERATION: ' + operation + ' REVISION: ' + value['new_revision'], file=sys.stderr)
    return {'path': target, 'status': status, 'owner': owner, 'operation_id': operation}


def arguments(args, command):
    """Optional trailing operation/revision flags without changing legacy argv."""
    from freq_board import current_agent, board_root, locked
    args = list(args)
    CONTEXT.clear()
    for flag, field in (('--operation-id', 'operation_id'), ('--expected-revision', 'expected_revision')):
        if flag in args:
            pos = args.index(flag)
            if pos + 1 >= len(args):
                raise ValueError(flag + ' requires a value')
            CONTEXT[field] = args[pos+1]
            del args[pos:pos+2]
    if 'operation_id' in CONTEXT:
        CONTEXT['operation_id'] = str(uuid.UUID(CONTEXT['operation_id']))
    CONTEXT['request_sha256'] = digest(json.dumps([current_agent(), command, args, CONTEXT.get('expected_revision')], ensure_ascii=False).encode())
    operation = CONTEXT.get('operation_id')
    if operation:
        for project in (board_root() / 'projects').iterdir():
            if project.is_symlink() or not project.is_dir() or project.name.startswith('.'):
                continue
            folder = journal_root(project) / operation
            if folder.exists():
                if not (folder / 'prepared.json').exists():
                    raise ValueError('Operation was interrupted before prepare; inspect original state and use a new ID')
                with locked(project):
                    _, value = record(project, operation)
                    if value['actor'] != current_agent() or value['request_sha256'] != CONTEXT['request_sha256']:
                        raise ValueError('Operation ID conflicts with another request')
                    finish(project, folder, value)
                    print('ALREADY COMMITTED: ' + operation + ' REVISION: ' + value['new_revision'])
                    return None
    return args


def notification_result(project, location, state):
    operation = location.get('operation_id')
    if operation:
        atomic(journal_root(project) / operation / 'notification.json',
               json.dumps({'state': state, 'operation_id': operation}).encode())
