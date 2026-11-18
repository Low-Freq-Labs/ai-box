"""Preserve task identity when an operator-approved project migration relocates it."""
import json
import os
from pathlib import Path
import re
import stat
import uuid

NAME = '.task-identities.json'
PROJECT = re.compile(r'^[A-Z0-9]+(?:-[A-Z0-9]+)*$')


def legacy(project, title):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'freq-board:' + project + ':' + title))


def read_registry(project):
    path = Path(project) / NAME
    if not path.exists() and not path.is_symlink():
        return {'schema': 1, 'project': Path(project).name, 'aliases': {}, 'departures': {}}
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
            raise ValueError('Invalid task identity registry')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
    finally:
        os.close(fd)
    value = json.loads(raw)
    if (set(value) != {'schema', 'project', 'aliases', 'departures'}
            or value['schema'] != 1 or value['project'] != Path(project).name
            or not isinstance(value['aliases'], dict) or not isinstance(value['departures'], dict)):
        raise ValueError('Invalid task identity registry schema')
    for collection in ('aliases', 'departures'):
        for title, row in value[collection].items():
            if (not isinstance(title, str) or not title or len(title) > 160
                    or not isinstance(row, dict) or not PROJECT.fullmatch(row['origin_project'])
                    or row['task_id'] != legacy(row['origin_project'], title)):
                raise ValueError('Invalid immutable task origin')
            uuid.UUID(row['migration_operation'])
            if not PROJECT.fullmatch(row['destination']):
                raise ValueError('Invalid task migration destination')
    return value


def identity(project, title):
    row = read_registry(project)['aliases'].get(title)
    return row['task_id'] if row else legacy(Path(project).name, title)


def assert_title_available(project, title):
    row = read_registry(project)['departures'].get(title)
    if row:
        raise ValueError('Task migrated to ' + row['destination'] + '; reuse its existing identity there')


def pending(project):
    path = Path(project) / '.project-migration-pending.json'
    if path.exists() or path.is_symlink():
        raise ValueError('Project migration pending; use task-project-migrate resume with its exact plan')
