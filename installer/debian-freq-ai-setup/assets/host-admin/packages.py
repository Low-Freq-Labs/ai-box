#!/usr/bin/python3 -I
"""Fixed APT operations; authenticated broker submits one durable job at a time."""
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

JOBS = Path('/var/lib/freq-agents/package-jobs')
UNIT = 'freq-host-packages.service'
PACKAGE = re.compile(r'[a-z0-9][a-z0-9+.-]{0,127}')
JOB = re.compile(r'[0-9a-f]{24}')
ENV = {'PATH':'/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL':'C.UTF-8',
       'HOME':'/root', 'DEBIAN_FRONTEND':'noninteractive', 'NEEDRESTART_MODE':'l'}


def names(values):
    if (not isinstance(values, list) or not 1 <= len(values) <= 32
            or any(not isinstance(v, str) or not PACKAGE.fullmatch(v)
                   or v.endswith(('-', '+')) for v in values)):
        raise ValueError('use 1–32 exact Debian package names; no flags, paths, versions or install/remove suffixes')
    return list(dict.fromkeys(values))


def active(b):
    output = b.run(['/usr/bin/systemctl', 'show', UNIT, '-p', 'ActiveState', '-p', 'Job'])
    info = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
    return (info.get('ActiveState') in ('active', 'activating', 'deactivating', 'reloading')
            or (info.get('Job', '').strip() or '0').split()[0] != '0')


def read(b, path):
    return json.loads(b.trusted(path))


def current(b):
    path = JOBS / 'current.json'
    return read(b, path) if path.exists() else None


def write(b, job):
    b.atomic(JOBS / (job['id'] + '.json'), json.dumps(job) + '\n')
    b.atomic(JOBS / 'current.json', json.dumps(job) + '\n')


def handle(b, request, actor, uid):
    verb = request.get('verb')
    if verb == 'search':
        b.fields(request, 'area action verb query')
        query = names([request['query']])[0]
        return b.run(['/usr/bin/apt-cache', 'search', '--names-only', re.escape(query)], timeout=15)
    if verb == 'show':
        b.fields(request, 'area action verb package')
        package = names([request['package']])[0]
        output = b.run(['/usr/bin/apt-cache', 'show', package], timeout=15)
        # No repository URLs or arbitrary metadata in the response.
        return '\n'.join(line for line in output.splitlines()
                         if line.startswith(('Package:', 'Version:', 'Description:', 'Installed-Size:', 'Architecture:')))
    if verb == 'status':
        b.fields(request, 'area action verb job')
        token = request['job']
        b.require(isinstance(token, str) and (token == 'latest' or JOB.fullmatch(token)), 'invalid job ID')
        job = current(b) if token == 'latest' else read(b, JOBS / (token + '.json'))
        if not job:
            return 'No package jobs yet.'
        latest = current(b)
        if job['status'] in ('queued', 'running') and (not latest or latest['id'] != job['id'] or not active(b)):
            job = dict(job, status='interrupted', message='Worker stopped before recording completion. No automatic retry; operator should inspect APT/dpkg state.')
        return json.dumps(job, indent=2)
    b.require(verb in ('install', 'refresh'), 'unsupported package operation')
    b.fields(request, 'area action verb packages' if verb == 'install' else 'area action verb')
    packages = names(request['packages']) if verb == 'install' else []
    b.require(not active(b), 'A package job is already running; use host-admin packages status')
    if JOBS.exists():
        info = JOBS.lstat()
        b.require(JOBS.is_dir() and not JOBS.is_symlink() and info.st_uid == 0 and not info.st_mode & 0o077,
                  'unsafe package job directory')
    else:
        JOBS.mkdir(mode=0o700)
    job = dict(id=secrets.token_hex(12), actor=actor, uid=uid, operation=verb,
               packages=packages, status='queued', submitted=int(time.time()))
    # Keep a bounded receipt history. These are generated job metadata, not user files.
    history = sorted((p for p in JOBS.glob('*.json') if JOB.fullmatch(p.stem)), key=lambda p:p.stat().st_mtime)
    for path in history[:-19]:
        path.unlink()
    write(b, job)
    try:
        b.run(['/usr/bin/systemctl', 'start', '--no-block', UNIT])
    except (OSError, ValueError):
        write(b, dict(job, status='failed', message='Unable to start package worker'))
        raise
    return f"Package job {job['id']} queued.\nCheck: host-admin packages status {job['id']}"


def apt_command(job):
    base = ['/usr/bin/apt-get', '-q', '-o', 'DPkg::Lock::Timeout=60',
            '-o', 'APT::Get::AllowUnauthenticated=false',
            '-o', 'Acquire::AllowInsecureRepositories=false',
            '-o', 'Acquire::AllowDowngradeToInsecureRepositories=false',
            '-o', 'Acquire::Retries=0', '-o', 'Acquire::http::Timeout=30',
            '-o', 'Acquire::https::Timeout=30']
    if job['operation'] == 'refresh':
        return base + ['-o', 'APT::Update::Error-Mode=any', 'update']
    return base + ['-y', '--no-remove', '--no-upgrade', '--no-install-recommends',
                   '-o', 'Dpkg::Options::=--force-confold', 'install', *names(job['packages'])]


def apt_run(argv):
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, env=ENV)
    tail = b''
    while chunk := process.stdout.read(4096):
        tail = (tail + chunk)[-16384:]
    code = process.wait()
    output = tail.decode(errors='replace').lower()
    hints = []
    for text, hint in (
        ('permission denied', 'filesystem permission denied'),
        ('operation not permitted', 'required OS operation denied'),
        ('read-only file system', 'read-only filesystem'),
        ('could not get lock', 'APT/dpkg lock held by another process'),
        ('unable to locate package', 'package unavailable; refresh indexes'),
        ('failed to fetch', 'repository download failed'),
        ('unmet dependencies', 'unmet dependencies'),
        ('dpkg was interrupted', 'dpkg repair required'),
        ('not enough free space', 'insufficient disk space'),
        ('not signed', 'repository signature verification failed'),
    ):
        if text in output: hints.append(hint)
    return code, '; '.join(hints)


def worker():
    import broker as b
    b.require(os.geteuid() == 0, 'package worker requires root')
    with b.locked():
        job = current(b)
        b.require(job and job['status'] == 'queued', 'no queued package job')
        state = b.load()
        authorized = b.operator(job['uid']) or (
            job['actor'] in b.agents() and b.pwd.getpwuid(job['uid']).pw_name == job['actor']
            and state.get('grant_uids', {}).get(job['actor']) == job['uid']
            and 'packages' in state['grants'].get(job['actor'], []))
        if not authorized:
            write(b, dict(job, status='failed', message='Package grant revoked before job started'))
            return
        job.update(status='running', started=int(time.time()))
        write(b, job)
    try:
        with open('/run/lock/freq-ai-maintenance.lock', 'r') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if job['operation'] == 'install':
                for package in names(job['packages']):
                    available = b.run(['/usr/bin/apt-cache', 'pkgnames', package], timeout=15)
                    if package not in available.splitlines():
                        raise ValueError('package not found')
            code, hint = apt_run(apt_command(job))
        job.update(status='succeeded' if code == 0 else 'failed', exit_code=code,
                   message='Completed.' if code == 0 else 'APT failed' + (': ' + hint if hint else '') + '; operator should inspect APT/dpkg logs. No automatic retry.')
    except BlockingIOError:
        job.update(status='failed', message='Host maintenance is busy; retry after it finishes.')
    except ValueError as error:
        job.update(status='failed', message=str(error))
    except OSError:
        job.update(status='failed', message='Package worker failed; operator should inspect host state.')
    job['finished'] = int(time.time())
    with b.locked():
        write(b, job)


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('internal worker only')
    worker()
