"""Explicit operator-pause disposition retaining active task ownership."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import tempfile
import time
from freq_board import testing
from freq_board_transaction import identity

def regular(path):
    from freq_stop_gate import read_regular, GateError
    try:
        return read_regular(path)
    except GateError as error:
        raise ValueError(str(error)) from error

def own_ids(project, agent):
    directory = project/'active'/agent
    if not directory.exists():
        return set()
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Invalid paused assignment')
    result = set()
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix != '.md':
            raise ValueError('Invalid retained active task')
        result.add(identity(project, path.stem))
    return result

def marker_path(project, agent):
    # Agent identity is already checked by the caller and is a single component.
    if not agent or '/' in agent or agent in ('.', '..'):
        raise ValueError('Invalid paused agent identity')
    directory = project/'.pauses'
    if directory.is_symlink():
        raise ValueError('Unsafe pause directory')
    return directory/(agent+'.json')

def read_marker(project, agent):
    path = marker_path(project, agent)
    if not path.exists() and not path.is_symlink():
        return None
    data = regular(path)
    owner = os.geteuid() if testing() else pwd.getpwnam(agent).pw_uid
    if path.stat().st_uid != owner:
        raise ValueError('Pause marker owner mismatch')
    record = json.loads(data)
    if not isinstance(record, dict):
        raise ValueError('Invalid operator-pause marker: expected a JSON object')
    if (record.get('schema') != 1 or record.get('project') != project.name or
        record.get('agent') != agent or record.get('exception') != 'operator_pause'):
        raise ValueError('Invalid operator-pause marker')
    if not record.get('reason') or not isinstance(record.get('active_task_ids'), list):
        raise ValueError('Incomplete operator-pause marker')
    refs = record.get('shared_evidence')
    if not isinstance(refs, dict) or not refs:
        raise ValueError('Pause requires shared pinned evidence')
    return record

def load(project, agent):
    record = read_marker(project, agent)
    if record is None:
        return None
    refs = record['shared_evidence']
    roots = (Path('/home/freq-agents/projects'), Path('/home/freq-agents/session-data'))
    for name, expected in refs.items():
        p = Path(name)
        if not testing() and not any(p.is_relative_to(root) for root in roots):
            raise ValueError('Pause evidence must be shared project/session evidence')
        if hashlib.sha256(regular(p)).hexdigest() != expected:
            raise ValueError('Paused operator evidence changed; reassess explicitly')
    if not own_ids(project, agent) <= set(record['active_task_ids']):
        return None  # New ownership is not silently covered by an older pause.
    return record

def prepare_locked(project, agent, assessment, refresh=False):
    if refresh:
        previous = read_marker(project, agent)
        if previous is None:
            raise ValueError('No existing pause to refresh; explicit resume must not be reversed by refresh')
        if not own_ids(project, agent) <= set(previous['active_task_ids']):
            raise ValueError('Pause ownership changed; assess the new scope and use project-assign PROJECT paused explicitly')
    if assessment.get('exception') != 'operator_pause':
        raise ValueError('Paused disposition requires a current explicit operator_pause assessment')
    roots = (Path('/home/freq-agents/projects'), Path('/home/freq-agents/session-data'))
    shared = {p:h for p,h in assessment['evidence'].items()
              if testing() or any(Path(p).is_relative_to(root) for root in roots)}
    if not shared:
        raise ValueError('Publish operator pause evidence in shared project/session records first')
    for name in shared:
        parts = Path(name).parts
        if 'session-state' in parts and 'archive' not in parts[parts.index('session-state')+1:]:
            raise ValueError('Pause evidence uses rotating session-state: ' + name + '; publish immutable shared proof and resubmit')
    record = {'schema':1, 'agent':agent, 'project':project.name, 'exception':'operator_pause',
        'reason':assessment['exception_reason'], 'recorded_at':time.time(),
        'assessment_revision':assessment['revision'],
        'assessment_sha256':hashlib.sha256(json.dumps(assessment,sort_keys=True).encode()).hexdigest(),
        'active_task_ids':sorted(own_ids(project,agent)), 'shared_evidence':shared,
        'scope':'Retains active ownership; no task completion, blocker resolution or work resumption.'}
    return record

def write_locked(project, agent, record):
    path = marker_path(project, agent);path.parent.mkdir(mode=0o2770,exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError('Unsafe pause directory')
    fd, name = tempfile.mkstemp(prefix='.pause-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(record,stream,sort_keys=True);stream.write('\n');stream.flush();os.fchmod(stream.fileno(),0o640);os.fsync(stream.fileno())
        os.replace(name,path)
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        if os.path.exists(name):os.unlink(name)
    return record

def create_locked(project, agent):
    from freq_stop_gate import check_locked
    record = prepare_locked(project, agent, check_locked(project, agent)['assessment'])
    return write_locked(project, agent, record)

def clear_locked(project, agent):
    path = marker_path(project,agent)
    if path.is_symlink():
        raise ValueError('Unsafe pause marker')
    if path.exists():
        path.unlink()
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(d)
        finally:os.close(d)
