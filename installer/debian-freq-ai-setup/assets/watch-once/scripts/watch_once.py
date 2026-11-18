"""Bounded one-shot stream observation. Raw command output is never persisted."""
import argparse
import datetime
import pwd
import json
import os
import pathlib
import selectors
import signal
import subprocess
import sys
import time


def save(path, data):
    with path.open('x') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


def observe(args):
    outcome = 'observer-error'
    returncode = None
    process = None
    selector = selectors.DefaultSelector()
    started = time.monotonic()
    try:
        process = subprocess.Popen(args.command, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        selector.register(process.stdout, selectors.EVENT_READ)
        pending = b''
        marker = args.marker.encode()
        outcome = 'deadline'
        while time.monotonic() - started < args.timeout:
            remaining = args.timeout - (time.monotonic() - started)
            if not selector.select(min(10, max(0, remaining))):
                continue
            chunk = process.stdout.read1(65536)
            if not chunk:
                returncode = process.wait(timeout=2)
                outcome = 'stream-ended' if returncode == 0 else 'command-failed'
                break
            pending += chunk
            if marker in pending:
                outcome = 'completion-marker'
                break
            pending = pending[-max(1, len(marker) - 1):]
    except Exception:
        outcome = 'observer-error'
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        selector.close()
    result = {'label': args.label, 'outcome': outcome, 'command_exit': returncode,
              'checked_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'elapsed_seconds': round(time.monotonic() - started, 3),
              'acceptance': 'Requires review; a completion marker does not prove success.'}
    save(args.output_dir / 'result.json', result)
    if not args.no_notify:
        message = (f"Watch Once: {args.label}: {outcome}.\n\n"
                   f"Evidence: {args.output_dir / 'result.json'}\n"
                   "Inspect the result and verify the affected system before claiming completion.")
        try:
            delivery = subprocess.run(['dev-msg', pwd.getpwuid(os.geteuid()).pw_name, 'Watch Once result', message],
                                      capture_output=True, timeout=30)
            status = 'queued' if delivery.returncode == 0 else 'failed'
        except Exception:
            status = 'failed-or-unknown'
        save(args.output_dir / 'notification.json', {'status': status, 'attempts': 1})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--output-dir', type=pathlib.Path, required=True)
    parser.add_argument('--timeout', type=float, required=True)
    parser.add_argument('--marker', required=True)
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--no-notify', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ['--']:
        args.command = args.command[1:]
    if not args.command or not args.marker or len(args.marker) > 4096 or not 0 < args.timeout <= 86400:
        parser.error('command, nonempty marker (up to4096 chars), and timeout0–86400 seconds required')
    args.output_dir = args.output_dir.resolve()
    if not args.worker:
        args.output_dir.mkdir(mode=0o700)
        if args.background:
            # Strip only our parsed option, never similarly named observer arguments.
            options = ['--label', args.label, '--output-dir', str(args.output_dir),
                       '--timeout', str(args.timeout), '--marker', args.marker, '--worker']
            if args.no_notify:
                options.append('--no-notify')
            with (args.output_dir / 'worker.log').open('xb') as log:
                child = subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve())]
                                         + options + ['--'] + args.command,
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                         start_new_session=True)
            save(args.output_dir / 'launch.json', {'pid': child.pid, 'label': args.label,
                 'timeout_seconds': args.timeout, 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})
            print(json.dumps({'pid': child.pid, 'output_dir': str(args.output_dir)}))
            return
    observe(args)


if __name__ == '__main__':
    main()
