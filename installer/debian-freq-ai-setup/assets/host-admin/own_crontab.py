"""Native crontab for the authenticated registered caller, never a target user."""
import hashlib
import json
import pwd
import re
import subprocess

MAX_BYTES = 8192
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}


def invoke(actor, args, data=None):
    try:
        return subprocess.run(['/usr/bin/crontab', '-u', actor, *args],
                              input=data, capture_output=True, timeout=5, env=ENV)
    except subprocess.TimeoutExpired:
        raise ValueError('crontab timed out; inspect current table before retrying') from None


def snapshot(actor):
    result = invoke(actor, ['-l'])
    absent = result.returncode == 1 and result.stderr == f'no crontab for {actor}\n'.encode()
    if result.returncode and not absent:
        raise ValueError('cannot read own crontab; inspect scheduler access')
    raw = b'' if absent else result.stdout
    if len(raw) > MAX_BYTES:
        raise ValueError('existing crontab exceeds supported 8192-byte limit; retained unchanged')
    if any(byte < 32 and byte not in (9, 10) for byte in raw):
        raise ValueError('existing crontab has unsupported control bytes; retained unchanged')
    return {'exists': not absent, 'content': raw.decode('utf-8'),
            'sha256': hashlib.sha256((b'0\0' if absent else b'1\0') + raw).hexdigest()}


def handle(api, request, actor, uid, names):
    api.require(actor in names and uid > 0 and pwd.getpwnam(actor).pw_uid == uid,
                'own crontab requires a registered non-root agent')
    action = request.get('action')
    api.require(action in ('show', 'install', 'remove'), 'unsupported crontab action')
    api.fields(request, 'area action' if action == 'show' else
               'area action expected_sha256 content' if action == 'install' else
               'area action expected_sha256')
    if action != 'show':
        expected = request['expected_sha256']
        api.require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected),
                    'expected_sha256 must be the current show fingerprint')
    if action == 'install':
        content = request['content']
        api.require(isinstance(content, str), 'crontab content must be UTF-8 text')
        raw = content.encode('utf-8')
        api.require(len(raw) <= MAX_BYTES and all(byte >= 32 or byte in (9, 10) for byte in raw),
                    'crontab must be at most 8192 bytes, with no controls except tab/newline')
        api.require(not raw or raw.endswith(b'\n'), 'crontab must end with a newline')
    current = snapshot(actor)
    if action == 'show':
        return json.dumps(current)
    api.require(current['sha256'] == expected, 'stale crontab fingerprint; show and merge before changing')
    if action == 'install':
        # Native parser checks all syntax before the atomic installation.
        checked = invoke(actor, ['-n', '-'], raw)
        api.require(checked.returncode == 0, 'crontab syntax refused; existing table retained')
        result = invoke(actor, ['-'], raw)
        api.require(result.returncode == 0, 'crontab install failed; show before retrying')
    elif current['exists']:
        result = invoke(actor, ['-r'])
        api.require(result.returncode == 0, 'crontab removal failed; show before retrying')
    after = snapshot(actor)
    api.require((action == 'install' and after['exists'] and after['content'] == content) or
                (action == 'remove' and not after['exists']),
                'crontab changed concurrently; inspect current table without replay')
    return json.dumps({'action': action, 'exists': after['exists'], 'sha256': after['sha256']})
