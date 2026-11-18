"""In-place, revision-bound task metadata corrections; no lifecycle changes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import freq_board as board
import freq_board_transaction as tx
from freq_stop_gate import evidence_hash, read_regular

HEX = re.compile(r'^[0-9a-f]{64}$')

def pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('Duplicate changes key')
        value[key] = item
    return value

def changes_file(path):
    raw = read_regular(Path(path))
    if len(raw) > 65536:
        raise ValueError('Changes exceed 64KiB')
    value = json.loads(raw, object_pairs_hook=pairs)
    allowed = {'schema', 'description', 'reason', 'note', 'evidence'}
    if (not isinstance(value, dict) or set(value)-allowed or
        value.get('schema') != 1 or type(value.get('schema')) is not int):
        raise ValueError('Unknown changes schema/fields')
    board.validate_note(value.get('note'), 'status note')
    if not any(k in value for k in ('description', 'reason')):
        raise ValueError('A description or reason correction is required')
    if 'description' in value:
        board.validate_note(value['description'], 'description')
    if 'reason' in value:
        board.validate_reason(value['reason'])
    for key in ('description', 'reason', 'note'):
        if key in value and '<!-- FREQ_' in value[key]:
            raise ValueError('Board control markers are not task prose')
    refs = value.get('evidence')
    if not isinstance(refs, dict) or not 1 <= len(refs) <= 32:
        raise ValueError('Changes require 1..32 pinned evidence paths')
    for path, digest in refs.items():
        if not isinstance(digest, str) or not HEX.fullmatch(digest) or evidence_hash(path) != digest:
            raise ValueError('Correction evidence changed or invalid')
    return value, hashlib.sha256(raw).hexdigest()

def description(content, text):
    match = re.search(r'^## Task\n\n', content, re.M)
    if not match or len(list(re.finditer(r'^## Task\n\n', content, re.M))) != 1:
        raise ValueError('Ambiguous task description section')
    tail = content[match.end():]
    boundary = re.search(r'^(?:<!-- FREQ_|## (?:Assignment note|Transfer handoff|Status note)\b)', tail, re.M)
    end = match.end() + (boundary.start() if boundary else len(tail))
    return content[:match.end()] + text.rstrip() + '\n\n' + content[end:]

def run(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('project'); parser.add_argument('title')
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--changes', required=True)
    parser.add_argument('--operation-id')
    args = parser.parse_args(argv)
    if not HEX.fullmatch(args.expected_revision):
        raise ValueError('Expected revision must be SHA256')
    change, bundle_sha = changes_file(args.changes)
    operation = [args.project, args.title, bundle_sha, '--expected-revision', args.expected_revision]
    if args.operation_id:
        operation += ['--operation-id', args.operation_id]
    if tx.arguments(operation, 'task-update') is None:
        return
    project = board.validate_project(args.project); actor = board.current_agent()
    with board.locked(project):
        location = board.locate(project, args.title)
        if location['status'] == 'active':
            board.require_owner(location, actor)
            if 'reason' in change:
                raise ValueError('An active task cannot acquire a blocked reason through metadata update')
        elif location['status'] == 'blocked':
            board.require_assignment(project, actor)
        else:
            raise ValueError('Only blocked or your owned active task metadata can be corrected')
        if tx.revision(project, location['path']) != args.expected_revision:
            raise ValueError('Revision conflict; inspect task-status again')
        original = board.read_text(location['path'])
        reason = change.get('reason', board.blocked_reason(location['path'])) if location['status'] == 'blocked' else None
        content = board.set_blocked_reason(original)
        if 'description' in change:
            content = description(content, change['description'])
        fields = ', '.join(k for k in ('description', 'reason') if k in change)
        content = board.append_history(content, board.history_entry(actor, 'METADATA UPDATE', fields + '; lifecycle/owner unchanged'))
        content = board.append_task_note(content, 'Status note', actor, change['note'],
            [('Changes SHA256', bundle_sha), ('Prior revision', args.expected_revision)])
        content = board.set_blocked_reason(content, reason)
        after = tx.transition(project, location, location['status'], content, owner=location['owner'],
            audit={'kind':'metadata-correction', 'fields':fields, 'changes_sha256':bundle_sha, 'evidence':change['evidence']})
        print('UPDATED: ' + args.project + '/' + args.title + ' (status=' + after['status'] + '; owner unchanged)')
