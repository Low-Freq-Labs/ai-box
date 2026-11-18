"""Revision-bound cooperative stop assessment. No task mutation or messaging."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from freq_board import board_root, current_agent, validate_project, testing, BoardError
from freq_board_inspect import inspect

MAX_BYTES = 4 * 1024 * 1024
MAX_AGE = 1800
KINDS = {'unavailable_access', 'operator_decision', 'external_condition', 'owned_elsewhere', 'outside_role'}
EXCEPTIONS = {'operator_pause', 'operator_cancel', 'infrastructure_failure', 'budget_exhausted'}

class GateError(Exception):
    pass

def need(condition, message):
    if not condition:
        raise GateError(message)

def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()

def read_regular(path):
    path = Path(path)
    need(path.is_absolute(), 'evidence/input path must be absolute')
    need(path.resolve() == path, 'symlink or noncanonical path refused')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, 'requires bounded regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(MAX_BYTES + 1)
        after = os.fstat(fd)
        need(len(data) <= MAX_BYTES and (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) == (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'file changed during read')
        final = path.lstat()
        need(not stat.S_ISLNK(final.st_mode) and (final.st_dev,final.st_ino) == (after.st_dev,after.st_ino), 'file replaced during read')
        return data
    finally:
        os.close(fd)

def evidence_hash(path):
    p = Path(path)
    if not testing():
        roots = [Path('/home/freq-agents/projects'), Path('/home/freq-agents/session-data'), Path('/var/lib/freq-agents/board/projects'), Path('/var/lib/freq-agents/coms') / current_agent() / 'read']
        need(any(p.is_relative_to(root) for root in roots), 'evidence must be shared project/state/board or caller read-message evidence')
    return hashlib.sha256(read_regular(p)).hexdigest()

@contextmanager
def project_lock(project, exclusive=False):
    fd = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        end = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise GateError('board lock unavailable; report infrastructure condition, do not claim assessment passed')
                time.sleep(.05)
        yield
    finally:
        os.close(fd)

def snapshot(project):
    report = inspect(project)
    need(report['complete'] and not report['errors'] and not report['pending_operations'], 'board incomplete or pending recovery; no stopping acceptance')
    rows = [{k:r.get(k) for k in ('task_id','title','status','owner','revision')} for r in report['tasks']]
    return {'project': project.name, 'revision': digest(rows), 'tasks': rows}

def state_path(project, agent):
    root = board_root().parent / 'stop-gate' if testing() else Path('/home/freq-agents/session-data')
    directory = root / agent if testing() else root / agent / 'stop-assessments'
    if testing():
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    need(directory.resolve() == directory and directory.is_dir(), 'assessment directory unavailable; infrastructure setup required')
    st = directory.stat()
    need(st.st_uid == os.geteuid() and not st.st_mode & 0o077, 'assessment directory must be caller-owned mode 0700')
    return directory / (project.name + '.json')

def text_field(value, label):
    need(isinstance(value,str) and 3 <= len(value.strip()) <= 4000, label + ' must be concrete nonempty text (3..4000 characters)')

def validate(project, agent, assessment, snap):
    need(isinstance(assessment, dict) and assessment.get('schema') == 1, 'assessment schema must be 1')
    need(assessment.get('agent') == agent and assessment.get('project') == project.name, 'assessment agent/project mismatch')
    need(assessment.get('revision') == snap['revision'], 'stale assessment: board revisions changed; regenerate template and reassess')
    text_field(assessment.get('summary'), 'summary')
    refs = assessment.get('evidence', {})
    need(isinstance(refs,dict), 'evidence must map absolute paths to SHA256')
    for path, expected in refs.items():
        need(isinstance(path,str) and isinstance(expected,str) and evidence_hash(path) == expected, 'evidence changed or hash mismatch: ' + str(path))
    exception = assessment.get('exception')
    if exception is not None:
        need(exception in EXCEPTIONS, 'invalid exception')
        need(refs, 'exception requires hashed evidence and explicit reason; not approval verification')
        text_field(assessment.get('exception_reason'), 'exception_reason')
        return
    own = [r for r in snap['tasks'] if r['status']=='active' and r['owner']==agent]
    need(not own, 'owned active work remains; continue, complete, transfer, or block truthfully')
    pending = {r['task_id']:r for r in snap['tasks'] if r['status'] in ('ready','blocked')}
    entries = assessment.get('dispositions')
    need(isinstance(entries,list), 'dispositions must cover every ready and blocked task')
    seen = set()
    for entry in entries:
        need(isinstance(entry,dict), 'invalid disposition')
        ids = entry.get('task_ids')
        need(isinstance(ids,list) and ids and all(isinstance(i,str) for i in ids), 'task_ids must be nonempty list')
        kind = entry.get('kind')
        need(kind in KINDS, 'missing prerequisite is work, not a stop reason; choose a concrete allowed disposition')
        for field in ('reason','next_step','owner'):
            text_field(entry.get(field),field)
        paths = entry.get('evidence')
        need(isinstance(paths,list) and paths and all(isinstance(p,str) and p in refs for p in paths), 'disposition requires pinned evidence')
        if kind == 'owned_elsewhere':
            target = entry.get('active_task_id')
            need(any(r['task_id']==target and r['status']=='active' and r['owner']==entry['owner'] and r['owner'] != agent for r in snap['tasks']), 'owned_elsewhere must reference a currently active other-owner task in this project')
        for task_id in ids:
            need(task_id in pending and task_id not in seen, 'unknown or duplicate assessed task')
            need(pending[task_id]['status'] != 'ready' or kind in ('outside_role','owned_elsewhere'), 'ready work must be claimed and resolved/blocked; cannot stop on an unowned ready prerequisite')
            seen.add(task_id)
    need(seen == set(pending), 'assessment omits ready or blocked tasks')

def check_locked(project, agent):
    path = state_path(project, agent)
    need(path.exists(), 'missing assessment; run project-assess ' + project.name + ' --template, assess prerequisites, then --submit FILE')
    record = json.loads(read_regular(path))
    need(isinstance(record,dict), 'invalid assessment receipt')
    age = time.time() - record.get('recorded_at', 0)
    need(0 <= age <= MAX_AGE, 'assessment expired; reassess current prerequisites')
    validate(project, agent, record['assessment'], snapshot(project))
    return record

def template(project, agent):
    snap = snapshot(project)
    return {'schema':1, 'project':project.name, 'agent':agent, 'revision':snap['revision'], 'summary':'', 'evidence':{}, 'exception':None, 'dispositions':[{'task_ids':[r['task_id']], 'kind':'', 'reason':'', 'next_step':'', 'owner':'', 'evidence':[]} for r in snap['tasks'] if r['status'] in ('ready','blocked')], 'observed_tasks':snap['tasks']}

def save(path, record):
    fd, temporary = tempfile.mkstemp(prefix='.assessment-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(encode(record)+b'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        fd = os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)

def status_locked(project, agent):
    # Bounded output; snapshot/check still validate the complete board and evidence.
    from freq_board_pause import load, marker_path
    snap = snapshot(project)
    counts = {state: sum(r['status'] == state for r in snap['tasks'])
              for state in ('ready', 'active', 'blocked', 'done', 'archive')}
    assessment = {'state': 'invalid', 'detail': ''}
    try:
        receipt = check_locked(project, agent)
        assessment = {'state': 'current', 'age_seconds': round(time.time() - receipt['recorded_at'], 3)}
    except (GateError, BoardError, OSError, ValueError, KeyError, TypeError) as exc:
        assessment['detail'] = str(exc)[:1000]
    paused = {'state': 'absent'}
    path = marker_path(project, agent)
    if path.exists() or path.is_symlink():
        try:
            record = load(project, agent)
            paused = ({'state': 'valid', 'retained_task_count': len(record['active_task_ids'])}
                      if record else {'state': 'ownership_changed', 'detail': 'New task ownership is not covered by the stored pause.'})
        except (GateError, BoardError, OSError, ValueError, KeyError, TypeError) as exc:
            paused = {'state': 'invalid', 'detail': str(exc)[:1000]}
    return {'schema': 1, 'project': project.name, 'agent': agent,
            'revision': snap['revision'], 'task_counts': counts,
            'owned_active_count': sum(r['status'] == 'active' and r['owner'] == agent for r in snap['tasks']),
            'assessment': assessment, 'pause': paused,
            'limit': 'Read-only diagnostics; pause validity does not renew authority, accept tasks, or resume work.'}

def cli():
    parser=argparse.ArgumentParser(description='Record a revision-bound prerequisite assessment. Human judgment remains required.')
    parser.add_argument('project')
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--template',action='store_true')
    actions.add_argument('--submit',type=Path)
    actions.add_argument('--check',action='store_true')
    actions.add_argument('--status',action='store_true',help='bounded read-only assessment freshness and pause-proof validity')
    parser.add_argument('--refresh-pause',action='store_true',help='with --submit only: explicitly refresh an existing pause using the new immutable proof; never recreate a resumed pause')
    args=parser.parse_args()
    if args.refresh_pause and not args.submit:
        parser.error('--refresh-pause requires --submit FILE')
    project=validate_project(args.project);agent=current_agent()
    with project_lock(project, exclusive=bool(args.submit)):
        if args.template:
            print(json.dumps(template(project,agent),indent=2));return
        if args.status:
            print(json.dumps(status_locked(project,agent),indent=2));return
        if args.submit:
            from freq_board_pause import prepare_locked, write_locked, marker_path
            assessment=json.loads(read_regular(args.submit))
            validate(project,agent,assessment,snapshot(project))
            paused_record = prepare_locked(project, agent, assessment, refresh=True) if args.refresh_pause else None
            save(state_path(project,agent),{'schema':1,'recorded_at':time.time(),'assessment':assessment})
            if paused_record is not None:
                try:
                    write_locked(project, agent, paused_record)
                except (OSError, ValueError) as exc:
                    raise GateError('assessment saved but pause refresh failed; inspect --status before recovery: ' + str(exc)) from exc
            print('ASSESSMENT RECORDED: '+agent+'/'+project.name)
            if paused_record is not None:
                print('PAUSE REFRESHED: existing scope retained; no work resumed')
            elif marker_path(project, agent).exists():
                print('PAUSE UNCHANGED: assessment submission does not refresh copied proof; inspect --status or explicitly use --refresh-pause')
            return
        check_locked(project,agent)
        print('ASSESSMENT CURRENT: '+agent+'/'+project.name)

def stop_hook(event):
    # No transcript inspection, prompt parsing, messaging, or persistent polling.
    need(isinstance(event,dict) and event.get('hook_event_name') == 'Stop', 'unsupported hook event')
    agent=current_agent();projects=board_root()/'projects';failures=[]
    need(projects.is_dir() and not projects.is_symlink(), 'board unavailable')
    for project in sorted(projects.iterdir()):
        if project.name.startswith('.'):continue
        assignment=project/'active'/agent
        if not assignment.exists() and not assignment.is_symlink():continue
        try:
            project=validate_project(project.name)
            need(assignment.is_dir() and not assignment.is_symlink(), 'invalid assignment')
            with project_lock(project):
                from freq_board_pause import load as paused
                if not paused(project,agent):check_locked(project,agent)
        except (GateError,BoardError,OSError,ValueError,KeyError,TypeError) as exc:
            failures.append(project.name+': '+str(exc))
    if not failures:return {}
    reason='Prerequisite stop assessment required. '+ '; '.join(failures)[:6000]+'. Inspect the full blocked queue, trace executable prerequisites, and claim work or make a concrete owner handoff. Record a current project-assess assessment or an evidenced operator/infrastructure exception. Do not ask for generic renewed permission.'
    if event.get('stop_hook_active') is True:
        return {'systemMessage':'Stop gate unresolved after one corrective continuation; no stopping acceptance. '+reason}
    return {'decision':'block','reason':reason}

def hook_cli():
    try:
        raw=sys.stdin.buffer.read(MAX_BYTES+1);need(len(raw)<=MAX_BYTES,'hook input too large')
        result=stop_hook(json.loads(raw))
    except (GateError,BoardError,OSError,ValueError,KeyError,TypeError) as exc:
        result={'systemMessage':'Stop gate infrastructure failure; assessment NOT accepted: '+str(exc)}
    print(json.dumps(result))
