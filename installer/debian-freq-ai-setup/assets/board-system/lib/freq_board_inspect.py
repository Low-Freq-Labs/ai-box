"""Read-only diagnostics: retain valid rows and explicitly report damaged entries."""
import json
import os
from pathlib import Path
import stat
from freq_board import STATUSES, AGENT_RE, blocked_reason
from freq_board_transaction import identity, revision, journal_root, regular, aborted_before_prepare


def inspect(project):
    rows, errors = [], []
    def traversal_error(error):
        path = Path(error.filename) if error.filename else project
        try:
            relative = str(path.relative_to(project))
        except ValueError:
            relative = '.'
        errors.append({'path': relative, 'error': 'Directory traversal failed: ' + str(error)})
    for status in STATUSES:
        root = project / status
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=traversal_error):
            for name in list(dirs):
                path = Path(directory) / name
                if path.is_symlink() or status != 'active' or Path(directory) != root or not AGENT_RE.fullmatch(name):
                    errors.append({'path': str(path.relative_to(project)), 'error': 'Invalid directory or symlink'})
                    dirs.remove(name)
            for name in files:
                if name.startswith('.'):
                    continue
                path = Path(directory) / name
                row = {'title': path.stem, 'path': str(path.relative_to(project)),
                       'status': status, 'owner': Path(directory).name if status == 'active' else None,
                       'task_id': identity(project, path.stem), 'errors': []}
                try:
                    mode = path.lstat().st_mode
                    if not name.endswith('.md') or not stat.S_ISREG(mode) or status == 'active' and Path(directory) == root:
                        raise ValueError('Invalid task path')
                    row['revision'] = revision(project, path)
                    regular(path).decode('utf-8')
                    if status == 'blocked':
                        row['reason'] = blocked_reason(path)
                except Exception as exc:
                    row['errors'].append(str(exc))
                rows.append(row)
    counts = {}
    for row in rows:
        counts[row['title']] = counts.get(row['title'], 0) + 1
    for row in rows:
        if counts[row['title']] > 1:
            row['errors'].append('Task exists in multiple board locations')
        errors.extend({'path': row['path'], 'error': error} for error in row['errors'])
    pending = []
    migration_marker = project / '.project-migration-pending.json'
    if migration_marker.exists() or migration_marker.is_symlink():
        try:
            migration = json.loads(regular(migration_marker))
            pending.append({'operation_id': migration['operation_id'], 'state': 'PROJECT_MIGRATION_PENDING',
                            'recovery': 'task-project-migrate resume with exact plan'})
        except (OSError, ValueError, KeyError) as error:
            errors.append({'path': migration_marker.name, 'error': str(error)})
    root = journal_root(project)
    if root.exists():
        for folder in sorted(root.iterdir()):
            if folder.is_symlink() or not folder.is_dir():
                errors.append({'path': str(folder.relative_to(project)), 'error': 'Invalid journal entry'})
            elif not (folder / 'committed.json').exists():
                try:
                    if aborted_before_prepare(folder): continue
                except (OSError,ValueError) as exc:
                    errors.append({'path':str(folder.relative_to(project)),'error':str(exc)})
                pending.append({'operation_id': folder.name,
                                'state': 'PREPARED' if (folder / 'prepared.json').exists() else 'NOT_PREPARED'})
    return {'schema': 1, 'project': project.name, 'complete': not errors and not pending,
            'tasks': sorted(rows, key=lambda r: (r['title'].casefold(), r['path'])),
            'errors': errors, 'pending_operations': pending}
