"""Unprivileged remote-test client; endpoint enrollment is operator-managed."""
import argparse
import base64
import ctypes
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid

UPLOAD_MAX = 268435456
RESULT_MAX = 12 * 1024 * 1024
DECODED_MAX = 8 * 1024 * 1024
CONTROL_MAX = 65536
NAMES = {'stdout.log', 'TESTS.json', 'EXECUTION.json'}
STATES = {'uploading', 'accepted', 'preparing', 'running', 'closed', 'cleaned', 'reconciliation-required'}
LEDGER = Path('/home/freq-agents/projects/infrastructure-management/remote-tests/receipts')
PROFILES = {'offline-python-v1': ('submit', 2),
            'offline-browser-finite-v1': ('submit-browser-finite', 1),
            'offline-browser-stream-v1': ('submit-browser-stream', 1)}
SUBMIT_ACTIONS = frozenset(v[0] for v in PROFILES.values())
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}


class ClientError(Exception):
    pass


def require(ok, message='invalid response'):
    if not ok:
        raise ClientError(message)


def run_id(value):
    require(type(value) is str and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', value), 'invalid run ID')
    return value


def digest_id(value):
    require(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value), 'invalid digest')
    return value


def owner_name(value):
    require(type(value) is str and re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', value), 'invalid local identity')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode(raw, limit):
    require(type(raw) is bytes and 0 < len(raw) <= limit, 'response size refused')
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, 'duplicate JSON key')
            out[k] = v
        return out
    def constant(_):
        raise ClientError('nonfinite JSON')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
        count = 0
        def inspect(v, depth=0):
            nonlocal count
            count += 1
            require(depth <= 16 and count <= 10000, 'JSON structure refused')
            if type(v) is float:
                raise ClientError('floating JSON value refused')
            if type(v) is dict:
                for key, item in v.items():
                    key.encode('utf-8'); inspect(item, depth + 1)
            elif type(v) is list:
                for item in v: inspect(item, depth + 1)
            elif type(v) is str:
                v.encode('utf-8')
        inspect(value)
        return value
    except ClientError:
        raise
    except Exception:
        raise ClientError('malformed JSON') from None


def identity(obj, owner, run=None):
    require(type(obj) is dict and type(obj.get('schema')) is int and obj['schema'] == 1)
    require(obj.get('owner') == owner, 'response owner mismatch')
    if run is not None:
        require(obj.get('run_id') == run, 'response run mismatch')


def profile_identity(obj, expected=None):
    # Legacy Python state objects omitted both fields; never infer browser.
    name = obj.get('profile', 'offline-python-v1')
    require(type(name) is str and name in PROFILES, 'unknown profile')
    version = obj.get('profile_version')
    if name != 'offline-python-v1' or 'profile_version' in obj:
        require(type(version) is int and version == PROFILES[name][1], 'profile version mismatch')
    if expected is not None:
        require(name == expected, 'profile mismatch')
    return name


def state_response(raw, owner, run=None, digest=None, profile=None):
    obj = decode(raw, CONTROL_MAX)
    identity(obj, owner, run)
    profile_identity(obj, profile)
    run_id(obj.get('run_id'))
    require(type(obj.get('state')) is str and obj['state'] in STATES)
    for key, value in obj.items():
        if key.endswith('_at'): require(type(value) is int and value >= 0)
    digest_id(obj.get('input_sha256'))
    if digest is not None:
        require(obj['input_sha256'] == digest, 'input digest mismatch')
    return obj


def verify_results(raw, owner, run):
    obj = decode(raw, RESULT_MAX)
    require(type(obj) is dict and set(obj) == {'schema', 'receipt', 'receipt_sha256', 'artifacts'})
    require(type(obj['schema']) is int and obj['schema'] == 1)
    receipt = obj['receipt']; identity(receipt, owner, run)
    require(receipt.get('state') == 'closed' and 'profile' in receipt)
    profile_identity(receipt)
    digest_id(receipt.get('input_sha256'))
    require('exit' in receipt, 'missing exit observation')
    if 'execution_created' in receipt:
        require(type(receipt['execution_created']) is bool)
    reason = receipt.get('stop_reason')
    require(reason is None or type(reason) is str)
    failed_context = (reason in ('upload-failure', 'controller-failure', 'output-limit', 'controller-deadline', 'runtime-timeout')
                      or receipt.get('execution_created') is False)
    exit_value = receipt['exit']
    require(type(exit_value) is int or (exit_value is None and failed_context),
            'unexplained or malformed exit observation')
    require(receipt.get('execution_created') is not False or exit_value is None,
            'exit observation contradicts unexecuted receipt')
    require(type(receipt.get('closure_verified')) is bool)
    require(type(receipt.get('filesystem_closed')) is bool)
    digest_id(obj['receipt_sha256'])
    require(len(canonical(receipt)) <= CONTROL_MAX, 'receipt budget exceeded')
    require(sha(canonical(receipt)) == obj['receipt_sha256'], 'receipt hash mismatch')
    for key, value in receipt.items():
        if key.endswith('_at'): require(type(value) is int and value >= 0)
    expected = receipt.get('artifacts'); artifacts = obj['artifacts']
    require(type(expected) is list and type(artifacts) is list and 0 <= len(expected) == len(artifacts) <= len(NAMES))
    require(bool(expected) or (failed_context and exit_value != 0), 'empty successful or unexplained evidence')
    descriptors = {}
    for item in expected:
        require(type(item) is dict and set(item) == {'name', 'sha256', 'size'})
        name = item['name']; require(type(name) is str and name in NAMES and name not in descriptors)
        digest_id(item['sha256'])
        require(type(item['size']) is int and 0 <= item['size'] <= DECODED_MAX)
        descriptors[name] = item
    files = {}; total = 0
    for item in artifacts:
        require(type(item) is dict and set(item) == {'name', 'sha256', 'size', 'data_base64'})
        name = item['name']; require(type(name) is str and name in descriptors and name not in files)
        require(type(item['size']) is int and {k: item[k] for k in ('name', 'sha256', 'size')} == descriptors[name])
        require(type(item['data_base64']) is str and len(item['data_base64']) <= 4 * ((DECODED_MAX + 2) // 3))
        try:
            data = base64.b64decode(item['data_base64'], validate=True)
        except Exception:
            raise ClientError('invalid artifact encoding') from None
        total += len(data); require(total <= DECODED_MAX, 'artifact budget exceeded')
        require(len(data) == item['size'] and sha(data) == item['sha256'], 'artifact hash mismatch')
        files[name] = data
    return receipt, obj['receipt_sha256'], files


def configured_host():
    path = Path('/etc/freq-remote-tests/client.json')
    require(path.exists(), 'remote-test is not enrolled; configure the dedicated test endpoint first')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            'unsafe remote-test configuration')
    require(path.parent.resolve() == path.parent, 'unsafe remote-test configuration directory')
    require(info.st_size <= 4096, 'remote-test configuration too large')
    obj = decode(path.read_bytes(), 4096)
    require(set(obj) == {'host'}, 'unexpected remote-test configuration fields')
    host = obj['host']
    require(type(host) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host),
            'invalid remote-test host')
    return host


def ssh_argv(owner, args):
    owner_name(owner)
    if args[:1] == ['phase-observation-v1']:
        require(len(args) == 5, 'invalid phase command')
        run_id(args[1]); digest_id(args[2])
        require(args[3] in PROFILES, 'invalid phase profile')
        require(str(uuid.UUID(args[4])) == args[4], 'invalid phase nonce')
        return ssh_argv(owner, ['status', args[1]])[:-2] + args
    if args[:1]==['visibility-v1']:
        if args==['visibility-v1','capabilities']:
            binding_run='capability-probe'
        else:
            require(len(args)==6 and args[1] in ('observe','submit'),'invalid visibility command')
            run_id(args[2]);digest_id(args[3]);require(args[4] in PROFILES,'unknown visibility profile')
            require(str(uuid.UUID(args[5]))==args[5],'invalid visibility nonce')
            binding_run=args[2]
        return ssh_argv(owner,['status',binding_run])[:-2]+args
    require(args and args[0] in SUBMIT_ACTIONS | {'status', 'results', 'cleanup', 'list'}, 'invalid command')
    require(len(args) in ((1, 2) if args[0] == 'list' else (3 if args[0] in SUBMIT_ACTIONS else {'status': 2, 'results': 2, 'cleanup': 3}[args[0]],)))
    if len(args) > 1: run_id(args[1])
    if len(args) > 2: digest_id(args[2])
    host = configured_host()
    options = ['BatchMode=yes', 'IdentitiesOnly=yes', 'IdentityAgent=none', 'StrictHostKeyChecking=yes',
               'UserKnownHostsFile=/etc/freq-remote-tests/known_hosts', 'GlobalKnownHostsFile=/dev/null',
               'UpdateHostKeys=no', 'VerifyHostKeyDNS=no', 'CanonicalizeHostname=no',
               'HostName=' + host, 'ProxyCommand=none', 'ProxyJump=none', 'PermitLocalCommand=no',
               'ControlMaster=no', 'ControlPath=none', 'ControlPersist=no', 'ForwardAgent=no',
               'ForwardX11=no', 'ClearAllForwardings=yes', 'RequestTTY=no',
               'PreferredAuthentications=publickey', 'PasswordAuthentication=no',
               'KbdInteractiveAuthentication=no', 'GSSAPIAuthentication=no', 'HostbasedAuthentication=no',
               'ConnectionAttempts=1', 'ConnectTimeout=10']
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', *[v for o in options for v in ('-o', o)],
            '-p', '22', '-l', 'freq-test-' + owner, '-i', '/etc/freq-remote-tests/keys/' + owner + '/id_ed25519',
            '--', host, *args]


class SSHTransport:
    def exchange(self, owner, args, source=None):
        limit = RESULT_MAX if args[0] == 'results' else CONTROL_MAX
        deadline = time.monotonic() + (180 if args[0] in SUBMIT_ACTIONS | {'results'} or args[:2]==['visibility-v1','submit'] else 60)
        p = subprocess.Popen(ssh_argv(owner, args), shell=False, env=ENV, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        sel = selectors.DefaultSelector(); out = bytearray(); err = bytearray(); pending = b''; broken = False; streamed = 0
        try:
            for stream in (p.stdout, p.stderr, p.stdin): os.set_blocking(stream.fileno(), False)
            sel.register(p.stdout, selectors.EVENT_READ, out); sel.register(p.stderr, selectors.EVENT_READ, err)
            if source is None: p.stdin.close()
            else: sel.register(p.stdin, selectors.EVENT_WRITE, None)
            while sel.get_map() or p.poll() is None:
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'transport timeout; outcome uncertain')
                for key, _ in sel.select(min(.2, remaining)):
                    if key.fileobj is p.stdin:
                        if not pending:
                            pending = source.read(65536)
                            streamed += len(pending)
                            require(streamed <= UPLOAD_MAX, 'upload budget exceeded')
                        if not pending:
                            sel.unregister(p.stdin); p.stdin.close(); continue
                        try:
                            size = os.write(p.stdin.fileno(), pending); pending = pending[size:]
                        except BrokenPipeError:
                            broken = True; sel.unregister(p.stdin); p.stdin.close()
                    else:
                        data = os.read(key.fd, 65536)
                        if not data: sel.unregister(key.fileobj); continue
                        target = key.data; target.extend(data)
                        require(len(target) <= (limit if target is out else CONTROL_MAX), 'transport output budget exceeded')
            return p.returncode, bytes(out), bytes(err), broken
        finally:
            sel.close()
            # Retire the owned group even if its leader already exited while
            # a descendant retained a pipe. Never leave an overflow helper alive.
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: p.wait(timeout=2)
            except subprocess.TimeoutExpired: pass
            for stream in (p.stdin, p.stdout, p.stderr): stream.close()


def directory(path):
    path = os.fspath(path)
    require(os.path.isabs(path) and '..' not in Path(path).parts, 'absolute no-parent path required')
    require(path != '/', 'root is not an evidence directory')
    fd = os.open('/', os.O_PATH | os.O_DIRECTORY)
    try:
        parts = Path(path).parts[1:]
        for index, part in enumerate(parts):
            mode = os.O_RDONLY if index == len(parts) - 1 else os.O_PATH
            nxt = os.open(part, mode | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nxt
        return fd
    except Exception:
        os.close(fd); raise


def ident(fd):
    s = os.fstat(fd); return [s.st_dev, s.st_ino]


def file_ident(fd):
    s = os.fstat(fd); return [s.st_dev, s.st_ino, s.st_ctime_ns, s.st_size]


def regular(parent, name, limit, expected=None):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        s = os.fstat(fd)
        require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= limit, 'unsafe evidence file')
        before = file_ident(fd)
        require(s.st_uid == os.getuid() and not (stat.S_IMODE(s.st_mode) & 0o077), 'evidence ownership unavailable')
        if expected is not None: require(before == expected, 'evidence file substituted')
        with os.fdopen(os.dup(fd), 'rb') as f: data = f.read(limit + 1)
        require(len(data) <= limit and len(data) == s.st_size, 'evidence changed')
        require(file_ident(fd) == before, 'evidence changed during read')
        return data, before
    finally: os.close(fd)


def write_new(parent, name, data):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        with os.fdopen(os.dup(fd), 'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
        return file_ident(fd)
    except Exception:
        os.unlink(name, dir_fd=parent)
        raise
    finally: os.close(fd)


def rename_new(parent, old, new):
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, 'renameat2', None)
    require(fn is not None, 'no-replace publication unavailable')
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(parent, os.fsencode(old), parent, os.fsencode(new), 1) != 0:
        raise OSError(ctypes.get_errno(), 'no-replace publication refused')


class Client:
    def __init__(self, owner, *, transport=None, ledger=None):
        self.owner = owner_name(owner); self.transport = transport or SSHTransport()
        self.ledger = Path(ledger) if ledger is not None else LEDGER / owner

    def _ledger(self):
        fd = directory(self.ledger); s = os.fstat(fd)
        if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) not in (0o700, 0o2700):
            os.close(fd); raise ClientError('ledger ownership unavailable')
        return fd

    def _exchange(self, args, source=None):
        code, out, err, broken = self.transport.exchange(self.owner, args, source)
        require(len(out) <= (RESULT_MAX if args[0] == 'results' else CONTROL_MAX) and len(err) <= CONTROL_MAX)
        require(code == 0, 'remote request refused; reconcile outcome explicitly')
        return out, broken

    def status(self, run):
        run_id(run); raw, _ = self._exchange(['status', run])
        return state_response(raw, self.owner, run)

    def list(self, cursor=None):
        if cursor is not None: run_id(cursor)
        raw, _ = self._exchange(['list'] + ([cursor] if cursor is not None else []))
        obj = decode(raw, CONTROL_MAX); identity(obj, self.owner)
        require(type(obj.get('runs')) is list and len(obj['runs']) <= 100 and 'next_cursor' in obj)
        previous = cursor or ''
        for item in obj['runs']:
            state_response(canonical(item), self.owner)
            require(item['run_id'] > previous, 'unordered page')
            previous = item['run_id']
        if obj['next_cursor'] is not None:
            run_id(obj['next_cursor']); require(bool(obj['runs']) and obj['next_cursor'] == previous)
        return obj

    def submit(self, run, archive, profile='offline-python-v1'):
        require(type(profile) is str and profile in PROFILES, 'unknown profile')
        action = PROFILES[profile][0]
        run_id(run); archive = Path(os.path.abspath(archive)); parent = directory(archive.parent)
        fd = None
        try:
            fd = os.open(archive.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= UPLOAD_MAX, 'archive size/type refused')
            fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            with os.fdopen(os.dup(fd), 'rb') as f:
                h = hashlib.sha256(); total = 0
                while chunk := f.read(65536):
                    total += len(chunk); require(total <= UPLOAD_MAX, 'archive grew'); h.update(chunk)
                require(total == before.st_size and fingerprint(os.fstat(fd)) == fingerprint(before), 'archive changed')
                digest = h.hexdigest(); f.seek(0)
                code, out, err, broken = self.transport.exchange(self.owner, [action, run, digest], f)
                require(fingerprint(os.fstat(fd)) == fingerprint(before), 'archive changed; submission uncertain')
            require(len(out) <= CONTROL_MAX and len(err) <= CONTROL_MAX, 'transport output budget exceeded')
            if broken:
                result = self.status(run)
                profile_identity(result, profile)
                require(result['input_sha256'] == digest, 'input digest mismatch')
                return result
            require(code == 0, 'submission refused or uncertain; use status')
            return state_response(out, self.owner, run, digest, profile)
        finally:
            if fd is not None: os.close(fd)
            os.close(parent)

    def results(self, run, destination):
        run_id(run); destination = Path(os.path.abspath(destination))
        parent = directory(destination.parent); ledger = None; staged = None; stagefd = None; names = []
        try:
            try: os.stat(destination.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise ClientError('destination already exists')
            ledger = self._ledger()
            raw, _ = self._exchange(['results', run]); receipt, digest, files = verify_results(raw, self.owner, run)
            # Cross-check even Python receipts to reject browser-to-Python drift.
            observed = self.status(run)
            profile_identity(observed, profile_identity(receipt))
            require(observed['input_sha256'] == receipt['input_sha256'], 'result input drift')
            require(observed['state'] == 'closed', 'result state drift')
            ledgername = run + '--' + digest + '.json'
            try: os.stat(ledgername, dir_fd=ledger, follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise ClientError('receipt already retained; preserve existing verification')
            staged = '.remote-test-' + uuid.uuid4().hex
            os.mkdir(staged, 0o700, dir_fd=parent); stagefd = os.open(staged, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            files['receipt.json'] = canonical(receipt)
            fingerprints = {}
            for name, data in files.items():
                fingerprints[name] = write_new(stagefd, name, data); names.append(name)
            verification = dict(schema=1, owner=self.owner, run_id=run, receipt_sha256=digest,
                                destination=str(destination), parent=ident(parent), directory=ident(stagefd), files=fingerprints)
            fingerprints['verification.json'] = write_new(stagefd, 'verification.json', canonical(verification)); names.append('verification.json')
            os.fsync(stagefd); rename_new(parent, staged, destination.name); staged = None; os.fsync(parent)
            # Reopen by path and compare pinned identities before acknowledging
            # retention; an ancestor swap cannot redirect the published bytes.
            checkparent = directory(destination.parent)
            try: require(ident(checkparent) == ident(parent), 'destination parent moved')
            finally: os.close(checkparent)
            write_new(ledger, ledgername, canonical(verification)); os.fsync(ledger)
            checkledger = directory(self.ledger)
            try: require(ident(checkledger) == ident(ledger), 'ledger directory moved')
            finally: os.close(checkledger)
            eligible = receipt['closure_verified'] is True and receipt['filesystem_closed'] is True
            return dict(state='verified', run_id=run, receipt_sha256=digest, destination=str(destination),
                        cleanup_ack=digest if eligible else None)
        finally:
            if staged is not None and stagefd is not None:
                for name in names:
                    try: os.unlink(name, dir_fd=stagefd)
                    except FileNotFoundError: pass
                os.rmdir(staged, dir_fd=parent)
            if stagefd is not None: os.close(stagefd)
            if ledger is not None: os.close(ledger)
            os.close(parent)

    def cleanup(self, run, digest):
        run_id(run); digest_id(digest); ledger = self._ledger(); parent = root = None
        try:
            data, _ = regular(ledger, run + '--' + digest + '.json', CONTROL_MAX)
            meta = decode(data, CONTROL_MAX); identity(meta, self.owner, run)
            require(meta.get('receipt_sha256') == digest)
            destination = Path(meta['destination']); parent = directory(destination.parent)
            require(ident(parent) == meta['parent'], 'destination parent substituted')
            root = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            require(ident(root) == meta['directory'], 'destination substituted')
            info = os.fstat(root)
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) in (0o700, 0o2700), 'evidence directory ownership unavailable')
            sidecar, _ = regular(root, 'verification.json', CONTROL_MAX, meta['files']['verification.json'])
            expected = dict(meta, files={k: v for k, v in meta['files'].items() if k != 'verification.json'})
            require(decode(sidecar, CONTROL_MAX) == expected, 'verification sidecar changed')
            raw, _ = regular(root, 'receipt.json', CONTROL_MAX, meta['files']['receipt.json'])
            receipt = decode(raw, CONTROL_MAX); identity(receipt, self.owner, run)
            require(sha(canonical(receipt)) == digest)
            require(receipt.get('state') == 'closed' and receipt.get('closure_verified') is True
                    and receipt.get('filesystem_closed') is True, 'remote closure unverified')
            for item in receipt['artifacts']:
                require(item['name'] in NAMES)
                contents, _ = regular(root, item['name'], DECODED_MAX, meta['files'][item['name']])
                require(len(contents) == item['size'] and sha(contents) == item['sha256'], 'retained artifact changed')
            raw, _ = self._exchange(['cleanup', run, digest]); result = state_response(raw, self.owner, run, receipt['input_sha256'], profile_identity(receipt))
            require(result['state'] == 'cleaned' and result.get('receipt_sha256') == digest and 'cleaned_at' in result)
            return result
        finally:
            if root is not None: os.close(root)
            if parent is not None: os.close(parent)
            os.close(ledger)


def main():
    parser = argparse.ArgumentParser(prog='remote-test'); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('submit'); p.add_argument('run'); p.add_argument('archive'); p.add_argument('--profile', choices=tuple(PROFILES), default='offline-python-v1')
    p = sub.add_parser('status'); p.add_argument('run')
    p = sub.add_parser('results'); p.add_argument('run'); p.add_argument('destination')
    p = sub.add_parser('cleanup'); p.add_argument('run'); p.add_argument('digest')
    p = sub.add_parser('list'); p.add_argument('--cursor'); args = parser.parse_args()
    try:
        require(os.getuid() == os.geteuid() and os.getuid() != 0, 'unprivileged UID required')
        owner = owner_name(pwd.getpwuid(os.getuid()).pw_name); client = Client(owner)
        result = getattr(client, args.command)(*[getattr(args, k) for k in {
            'submit': ('run', 'archive', 'profile'), 'status': ('run',), 'results': ('run', 'destination'),
            'cleanup': ('run', 'digest'), 'list': ('cursor',)}[args.command]])
        # Only locally validated fields/receipt data; no remote stderr strings.
        print(canonical(result).decode('ascii')); return 0
    except Exception:
        print('{"error":"remote_test_refused_or_uncertain"}', file=sys.stderr); return 1


def visibility_submit_file(client,run,archive,profile='offline-python-v1'):
    require(profile in PROFILES,'unknown profile')
    run_id(run)
    archive=Path(os.path.abspath(archive))
    parent=directory(archive.parent)
    fd=None
    try:
        fd=os.open(archive.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        before=os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=UPLOAD_MAX,'archive size/type refused')
        fingerprint=lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        with os.fdopen(os.dup(fd),'rb') as source:
            h=hashlib.sha256();total=0
            while True:
                chunk=source.read(65536)
                if not chunk:break
                total+=len(chunk);require(total<=UPLOAD_MAX,'archive grew');h.update(chunk)
            require(total==before.st_size and fingerprint(os.fstat(fd))==fingerprint(before),'archive changed before request')
            source.seek(0)
            result=visibility_request(client.transport,client.owner,run,h.hexdigest(),profile,str(uuid.uuid4()),action='submit',source=source)
            source.seek(0);final_hash=hashlib.sha256();final_total=0
            while True:
                chunk=source.read(65536)
                if not chunk:break
                final_total+=len(chunk)
                if final_total>UPLOAD_MAX:return {'classification':'uncertain','retry_allowed':False}
                final_hash.update(chunk)
            if final_total!=before.st_size or final_hash.hexdigest()!=h.hexdigest() or fingerprint(os.fstat(fd))!=fingerprint(before):
                return {'classification':'uncertain','retry_allowed':False}
            return result
    finally:
        if fd is not None:os.close(fd)
        os.close(parent)

def visibility_main():
    parser=argparse.ArgumentParser(prog='remote-test-visibility')
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('submit');p.add_argument('run');p.add_argument('archive');p.add_argument('--profile',choices=tuple(PROFILES),default='offline-python-v1')
    p=sub.add_parser('observe');p.add_argument('run');p.add_argument('input_sha256');p.add_argument('--profile',choices=tuple(PROFILES),default='offline-python-v1')
    args=parser.parse_args()
    try:
        require(os.getuid()==os.geteuid() and os.getuid()!=0,'unprivileged UID required')
        owner=owner_name(pwd.getpwuid(os.getuid()).pw_name);client=Client(owner)
        if args.action=='submit':
            result=visibility_submit_file(client,args.run,args.archive,args.profile)
        else:
            result=visibility_request(client.transport,owner,args.run,args.input_sha256,args.profile,str(uuid.uuid4()))
        print(canonical(result).decode('ascii'))
        classification=result['classification']
        return 3 if classification=='definite_refusal' else 0 if classification in ('state_observation','absent_at_observation') else 4
    except Exception:
        print('{"classification":"uncertain","retry_allowed":false}',file=sys.stderr)
        return 4


def visibility_request(transport,owner,run,input_sha256,profile,nonce,action='observe',source=None):
    from visibility_model import classify,decode_wire
    uncertain={'classification':'uncertain','retry_allowed':False}
    require(action in ('observe','submit'),'invalid visibility action')
    args=['visibility-v1',action,run,input_sha256,profile,nonce]
    ssh_argv(owner,args) # Validate exact command/bindings before any request.
    try:
        code,out,err,broken=transport.exchange(owner,['visibility-v1','capabilities'])
        if code or broken or len(out)>4096:return {'classification':'unsupported_or_uncertain','retry_allowed':False}
        capability=decode_wire(out)
        if type(capability)is not dict or any(type(capability.get(k))is not int for k in ('schema','visibility_version','max_response_bytes')) or capability!={'schema':1,'visibility_version':1,'commands':['observe','submit'],'max_response_bytes':4096}:
            return {'classification':'unsupported_or_uncertain','retry_allowed':False}
    except Exception:
        return {'classification':'unsupported_or_uncertain','retry_allowed':False}
    binding=dict(nonce=nonce,owner=owner,run_id=run,input_sha256=input_sha256,profile=profile)
    try:
        code,out,err,broken=transport.exchange(owner,args,source)
        result=classify(out,binding,authenticated=True,exit_code=code)
        if broken and result['classification']!='definite_refusal':return uncertain
        return result
    except Exception:
        return uncertain

def phase_main():
    import phase_client_fixture as phase_client
    import phase_reader_fixture as phase_reader
    parser = argparse.ArgumentParser(prog='remote-test phase-observation-v1')
    parser.add_argument('run'); parser.add_argument('input_sha256')
    parser.add_argument('--profile', choices=tuple(PROFILES), default='offline-python-v1')
    args = parser.parse_args()
    try:
        require(os.getuid() == os.geteuid() and os.getuid() != 0, 'unprivileged UID required')
        owner = owner_name(pwd.getpwuid(os.getuid()).pw_name)
        request = dict(owner=owner, run_id=args.run, input_sha256=args.input_sha256,
                       profile=args.profile, nonce=str(uuid.uuid4()))
        phase_reader.binding(request)
        result = phase_client.request_phase(SSHTransport().exchange, request)
    except Exception:
        result = dict(phase_reader.UNKNOWN)
    print(canonical(result).decode('ascii'))
    return 0 if result['classification'] == 'historical_phase_observation' else 4

def dispatch():
    if sys.argv[1:2] == ['phase-observation-v1']:
        del sys.argv[1]
        return phase_main()
    if sys.argv[1:2] == ['visibility-v1']:
        del sys.argv[1]
        return visibility_main()
    return main()
