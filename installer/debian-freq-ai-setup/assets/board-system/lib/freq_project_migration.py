"""Granted, journaled cross-project task relocation; never recreates task IDs."""
import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import time
import uuid

import freq_board as board
import freq_board_transaction as tx
from freq_board_inspect import inspect
import freq_board_dependencies as dependencies
import freq_task_identity as identities

HEX = re.compile(r'^[a-f0-9]{64}$')
TOKEN = re.compile(r'^[a-zA-Z0-9_-]{1,100}$')
MAX_TOTAL = 8 * 1024 * 1024
MARKER = '.project-migration-pending.json'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def need(value, message):
    if not value:
        raise ValueError(message)


def fixture_mode():
    if not board.testing():
        return False
    need(not board.board_root().resolve().is_relative_to(board.DEFAULT_BOARD_ROOT.resolve()), 'Test root cannot be within the live board')
    return True


def failpoint(name):
    if fixture_mode() and os.environ.get('FREQ_MIGRATION_FAULT') == name:
        os._exit(91)


def read_json(path):
    return json.loads(tx.regular(path))


def atomic(path, raw, mode=0o660):
    temporary = path.with_name('.migration-' + uuid.uuid4().hex)
    tx.write_new(temporary, raw, mode)
    os.replace(temporary, path)
    tx.sync(path.parent)


def grant_path(token):
    need(TOKEN.fullmatch(token), 'Invalid grant name')
    root = board.board_root() / '.migration-grants' if fixture_mode() else Path('/etc/freq-ai-setup/board-project-migrations')
    return root / (token + '.json')


def load_grant(token, allow_expired=False):
    path = grant_path(token)
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and not path.is_symlink(), 'Grant must be a regular file')
    if not fixture_mode():
        need(info.st_uid == 0 and not info.st_mode & 0o022, 'Grant must be root-owned and not group/world writable')
    raw = tx.regular(path)
    grant = json.loads(raw)
    need(grant['schema'] == 1 and grant['grant_id'] == token, 'Grant identity mismatch')
    need(os.geteuid() == grant['actor_uid'], 'This Linux UID does not hold the migration grant')
    need(allow_expired or time.time() < grant['expires'], 'Migration grant expired')
    board.validate_project_id(grant['source'])
    board.validate_project_id(grant['destination'])
    need(grant['source'] != grant['destination'], 'Migration requires two projects')
    ids = grant['task_ids']
    need(isinstance(ids, list) and 0 < len(ids) <= 1000 and len(set(ids)) == len(ids), 'Exact bounded unique task set required')
    for task_id in ids:
        need(str(uuid.UUID(task_id)) == task_id, 'Invalid granted task ID')
    need(sha(tx.regular(Path(grant['operator_proof']))) == grant['operator_proof_sha256'], 'Operator proof changed')
    return grant, sha(raw)


@contextmanager
def locks(source, destination):
    with ExitStack() as stack:
        for project in sorted((source, destination)):
            descriptor = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield


def projects(grant):
    source, destination = board.validate_project(grant['source']), board.validate_project(grant['destination'])
    if fixture_mode():
        expected = board.board_root().resolve() / 'projects'
        need(all(p.resolve().is_relative_to(expected) for p in (source, destination)), 'Fixture projects cannot point outside the test root')
    return source, destination


def snapshot(project):
    report = inspect(project)
    need(report['complete'], 'Incomplete project: inspect transactions/migrations before proceeding')
    return report['tasks']


def verify_links(source, rows, selected):
    """No dependency is silently severed or rewritten by this first mover."""
    for row in rows:
        metadata, _ = dependencies.parse(tx.regular(source / row['path']).decode())
        links = metadata['links'] if metadata else []
        need(not (row['task_id'] in selected and links),
             'Selected task has explicit dependency metadata; publish a reviewed dependency migration first')
        for link in links:
            need(link['task_id'] not in selected, 'An unmoved task explicitly depends on a selected task')


def index_bytes(project):
    path = project / identities.NAME
    return tx.regular(path) if path.exists() else None


def digest_unselected(rows, selected):
    return sha(canonical(sorted((r['task_id'], r['path'], r['revision']) for r in rows if r['task_id'] not in selected)))


def output_path(path):
    path = Path(path)
    need(path.is_absolute() and path.parent.resolve() == path.parent and not path.exists(), 'New canonical plan path required')
    if not fixture_mode():
        allowed = Path('/home/freq-agents/projects')
        need(path.is_relative_to(allowed), 'Plan belongs in shared project evidence')
    return path


def make_plan(token, output):
    grant, grant_sha = load_grant(token)
    source, destination = projects(grant)
    with locks(source, destination):
        for project in (source, destination):
            identities.pending(project)
            tx.recover(project)
        before = snapshot(source)
        target = snapshot(destination)
        selected = set(grant['task_ids'])
        chosen = [r for r in before if r['task_id'] in selected]
        need(len(chosen) == len(selected), 'Granted task set is absent or ambiguous')
        occupied = {r['title'] for r in target}
        for row in chosen:
            need(row['title'] not in occupied, 'Destination title collision: ' + row['title'])
            identities.assert_title_available(destination, row['title'])
        verify_links(source, before, selected)
        size = sum(len(tx.regular(source / row['path'])) for row in chosen)
        need(size <= MAX_TOTAL, 'Task image output bound exceeded')
        items = []
        for row in chosen:
            items.append({k: row[k] for k in ('task_id', 'title', 'path', 'status', 'owner', 'revision')})
            items[-1]['sha256'] = sha(tx.regular(source / row['path']))
        plan = {'schema': 1, 'operation_id': str(uuid.uuid4()), 'grant': token, 'grant_sha256': grant_sha,
                'source': source.name, 'destination': destination.name, 'actor_uid': os.geteuid(),
                'created': time.time(), 'items': items, 'total_task_bytes': size,
                'source_index_sha256': sha(index_bytes(source) or b''),
                'destination_index_sha256': sha(index_bytes(destination) or b''),
                'task_bytes_status_owner_history_preserved': True}
        raw = canonical(plan)
        path = output_path(output)
        tx.write_new(path, raw)
        tx.sync(path.parent)
    return {'status': 'PLANNED', 'plan': str(path), 'plan_sha256': sha(raw), 'tasks': len(items), 'operation_id': plan['operation_id']}


def checked_plan(path, expected_sha):
    need(HEX.fullmatch(expected_sha), 'Exact plan SHA256 required')
    raw = tx.regular(Path(path))
    need(sha(raw) == expected_sha, 'Plan SHA256 mismatch')
    plan = json.loads(raw)
    need(plan['schema'] == 1 and str(uuid.UUID(plan['operation_id'])) == plan['operation_id'], 'Invalid plan operation')
    grant, grant_sha = load_grant(plan['grant'], allow_expired=True)
    need(plan['actor_uid'] == os.geteuid() and plan['source'] == grant['source'] and plan['destination'] == grant['destination']
         and plan['grant_sha256'] == grant_sha, 'Plan exceeds exact actor/project grant')
    need(set(grant['task_ids']) == {r['task_id'] for r in plan['items']} and len(plan['items']) == len(grant['task_ids']), 'Plan task set differs from grant')
    return plan, grant, raw


def operation_folder(plan):
    root = board.board_root() / '.project-migrations'
    need(not root.is_symlink(), 'Unsafe migration journal root')
    if not root.exists():
        root.mkdir(mode=0o2770)
        root.chmod(0o2770)
        tx.sync(root.parent)
    return root / plan['operation_id']


def prepare(plan, grant, raw, folder, source, destination):
    need(time.time() < grant['expires'], 'Migration grant expired before prepare')
    for project in (source, destination):
        identities.pending(project)
        tx.recover(project)
    before = snapshot(source)
    target = snapshot(destination)
    current = {r['task_id']: r for r in before}
    selected = set(grant['task_ids'])
    verify_links(source, before, selected)
    need(sha(index_bytes(source) or b'') == plan['source_index_sha256'] and sha(index_bytes(destination) or b'') == plan['destination_index_sha256'], 'Identity index changed; make a fresh plan')
    occupied = {r['title'] for r in target}
    for item in plan['items']:
        row = current.get(item['task_id'])
        need(row and all(row[k] == item[k] for k in ('title', 'path', 'status', 'owner', 'revision')), 'Task state/revision changed; make a fresh plan')
        need(item['title'] not in occupied and sha(tx.regular(source / row['path'])) == item['sha256'], 'Collision or task byte change')
    folder.mkdir(mode=0o2770)
    folder.chmod(0o2770)
    tx.sync(folder.parent)
    images = folder / 'images'
    images.mkdir(mode=0o2770)
    images.chmod(0o2770)
    tx.write_new(folder / 'plan.json', raw)
    source_index = identities.read_registry(source)
    destination_index = identities.read_registry(destination)
    for item in plan['items']:
        tx.write_new(images / (item['task_id'] + '.bin'), tx.regular(source / item['path']))
        prior = source_index['aliases'].get(item['title'])
        origin = prior['origin_project'] if prior else source.name
        record = {'task_id': item['task_id'], 'origin_project': origin, 'destination': destination.name, 'migration_operation': plan['operation_id']}
        source_index['departures'][item['title']] = record
        destination_index['aliases'][item['title']] = record
    for name, project, value in (('source', source, source_index), ('destination', destination, destination_index)):
        tx.write_new(folder / (name + '-index.before'), index_bytes(project) or b'')
        tx.write_new(folder / (name + '-index.after'), canonical(value))
    tx.write_new(folder / 'unselected.json', canonical({'source': digest_unselected(before, selected), 'destination': digest_unselected(target, set())}))
    tx.sync(images)
    tx.sync(folder)
    failpoint('before_markers')
    marker = canonical({'schema': 1, 'operation_id': plan['operation_id'], 'source': source.name, 'destination': destination.name, 'plan_sha256': sha(raw)})
    # Both project markers are durable BEFORE PREPARED. No task/index effect
    # precedes the commit decision; an incomplete preparation safely aborts.
    atomic(source / MARKER, marker)
    failpoint('after_first_marker')
    atomic(destination / MARKER, marker)
    atomic(folder / 'prepared.json', canonical({'plan_sha256': sha(raw), 'state': 'PREPARED'}))
    failpoint('after_prepare')


def clear_markers(plan, source, destination):
    for project in (source, destination):
        path = project / MARKER
        if path.exists():
            need(read_json(path)['operation_id'] == plan['operation_id'], 'Another migration owns the project marker')
            path.unlink()
            tx.sync(project)


def finish(plan, folder, source, destination):
    for name, project in (('source', source), ('destination', destination)):
        before = tx.regular(folder / (name + '-index.before'))
        after = tx.regular(folder / (name + '-index.after'))
        need((index_bytes(project) or b'') in (before, after), 'Identity registry conflict; preserve prepared operation')
        atomic(project / identities.NAME, after)
    failpoint('after_indices')
    for index, item in enumerate(plan['items']):
        path = Path(item['path'])
        need(not path.is_absolute() and len(path.parts) in (2, 3) and path.parts[0] in board.STATUSES
             and path.name == item['title'] + '.md' and not any(p in ('.', '..') for p in path.parts), 'Invalid prepared task path')
        source_path = source / path
        target_path = destination / path
        if item['status'] == 'active':
            need(path.parts[1] == item['owner'], 'Owner path differs')
            board.ensure_assignment(destination, item['owner'])
        need(not source_path.is_symlink() and not target_path.is_symlink(), 'Symlink in prepared task path')
        raw = tx.regular(folder / 'images' / (item['task_id'] + '.bin'))
        need(sha(raw) == item['sha256'], 'Immutable task snapshot changed')
        if source_path.exists():
            need(sha(tx.regular(source_path)) == item['sha256'], 'Source changed after prepare; preserve conflict')
        if target_path.exists():
            need(sha(tx.regular(target_path)) == item['sha256'], 'Target changed after prepare; preserve conflict')
        else:
            atomic(target_path, raw)
        failpoint('after_target_' + str(index))
        if source_path.exists():
            source_path.unlink()
            tx.sync(source_path.parent)
        failpoint('after_move_' + str(index))
        need(identities.identity(destination, item['title']) == item['task_id'], 'Task identity not preserved')
    # Pending markers deliberately keep generic inspection incomplete, but
    # rows still allow checking exact unaffected paths/revisions under locks.
    source_rows = inspect(source)['tasks']
    target_rows = inspect(destination)['tasks']
    selected = {r['task_id'] for r in plan['items']}
    unaffected = read_json(folder / 'unselected.json')
    need(digest_unselected(source_rows, selected) == unaffected['source'] and digest_unselected(target_rows, selected) == unaffected['destination'], 'Unselected task changed during migration')
    need(not any(r['task_id'] in selected for r in source_rows), 'Source task still present')
    current = {r['task_id']: r for r in target_rows}
    for item in plan['items']:
        row = current.get(item['task_id'])
        need(row and all(row[k] == item[k] for k in ('title', 'path', 'status', 'owner', 'revision')), 'Moved task metadata/revision changed')
    receipt = {'schema': 1, 'state': 'COMMITTED', 'operation_id': plan['operation_id'], 'source': source.name,
               'destination': destination.name, 'tasks': len(plan['items']), 'committed': time.time(),
               'task_ids_bytes_revisions_status_owners_history_preserved': True, 'unselected_tasks_unchanged': True,
               'historical_transactions_retained_in_source': True}
    atomic(folder / 'committed.json', canonical(receipt))
    failpoint('after_commit')
    clear_markers(plan, source, destination)
    return receipt


def apply(path, expected_sha, resume=False):
    plan, grant, raw = checked_plan(path, expected_sha)
    source, destination = projects(grant)
    with locks(source, destination):
        folder = operation_folder(plan)
        if folder.exists():
            need(sha(tx.regular(folder / 'plan.json')) == expected_sha, 'Existing migration belongs to another plan')
            if (folder / 'committed.json').exists():
                clear_markers(plan, source, destination)
                return {'status': 'EXISTING_COMMITTED', 'receipt': read_json(folder / 'committed.json')}
            need(resume, 'Existing interrupted migration; use explicit resume, never replay apply')
            if not (folder / 'prepared.json').exists():
                clear_markers(plan, source, destination)
                atomic(folder / 'aborted.json', canonical({'state': 'ABORTED_BEFORE_PREPARE', 'operation_id': plan['operation_id']}))
                return {'status': 'ABORTED_BEFORE_PREPARE', 'operation_id': plan['operation_id']}
            need(read_json(folder / 'prepared.json')['plan_sha256'] == expected_sha, 'Prepared decision mismatch')
        else:
            need(not resume, 'No migration to resume')
            prepare(plan, grant, raw, folder, source, destination)
        return {'status': 'COMMITTED', 'receipt': finish(plan, folder, source, destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan'); p.add_argument('--grant', required=True); p.add_argument('--output', required=True)
    for name in ('apply', 'resume'):
        p = sub.add_parser(name); p.add_argument('--plan', required=True); p.add_argument('--expected-plan-sha256', required=True)
    args = parser.parse_args()
    try:
        result = make_plan(args.grant, args.output) if args.command == 'plan' else apply(args.plan, args.expected_plan_sha256, args.command == 'resume')
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, KeyError, board.BoardError) as error:
        print('MIGRATION FAILED: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
