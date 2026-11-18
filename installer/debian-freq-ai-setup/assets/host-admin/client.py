#!/usr/bin/python3 -I
"""Structured local requests; the broker authenticates the actual socket peer."""
import argparse
import getpass
import json
import os
from pathlib import Path
import socket
import sys
import subprocess
import tempfile

SOCKET = '/run/freq-host-admin.sock'
LIMIT = 65536


def request(value, display=True):
    data = json.dumps(value).encode()
    if len(data) > LIMIT:
        raise ValueError('request is too large')
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(60)
        sock.connect(SOCKET)
        sock.sendall(data)
        sock.shutdown(socket.SHUT_WR)
        chunks = bytearray()
        while part := sock.recv(4096):
            chunks.extend(part)
            if len(chunks) > LIMIT:
                raise ValueError('response is too large')
    result = json.loads(chunks)
    if not result['ok']:
        raise ValueError(result['message'])
    if display:
        print(result['message'])
    return result['message']


def body():
    value = sys.stdin.buffer.read(32769)
    if len(value) > 32768:
        raise ValueError('alert exceeds 32768 bytes')
    return value.decode('utf-8')


def main():
    name = Path(sys.argv[0]).name
    parser = argparse.ArgumentParser(prog=name)
    sub = parser.add_subparsers(dest='action', required=True)
    if name == 'board-admin':
        p=sub.add_parser('validate');p.add_argument('project');p.add_argument('--json',action='store_true')
        p.add_argument('--cursor',type=int,default=0);p.add_argument('--limit',type=int,default=25)
        p=sub.add_parser('operation-status');p.add_argument('project');p.add_argument('operation');p.add_argument('--json',action='store_true')
        p=sub.add_parser('reconcile');s=p.add_subparsers(dest='verb',required=True)
        p=s.add_parser('plan');p.add_argument('project');p.add_argument('operation')
        p=s.add_parser('apply');p.add_argument('plan');p.add_argument('--expect-plan-sha256',dest='expected_plan_sha256',required=True)
        p.add_argument('--approval',required=True)
        args=vars(parser.parse_args());args.pop('json',None)
        if args['action']=='reconcile':args['action']=args.pop('verb')
        args['area']='board-maintenance'
    elif name == 'coms-admin':
        p=sub.add_parser('health');p.add_argument('--json',action='store_true')
        p=sub.add_parser('delivery');s=p.add_subparsers(dest='verb',required=True)
        p=s.add_parser('inspect');p.add_argument('message');p.add_argument('--json',action='store_true')
        p=s.add_parser('retry');p.add_argument('message');p.add_argument('--expected-revision',required=True,type=int);p.add_argument('--approval',required=True)
        p=sub.add_parser('reconcile');p.add_argument('message')
        p=sub.add_parser('discord-status');p.add_argument('filename')
        args=vars(parser.parse_args());args.pop('json',None)
        if args['action']=='delivery':args['action']=args.pop('verb')
        args['area']='coms-maintenance'
    elif name == 'storage-budget':
        sub.add_parser('list')
        p=sub.add_parser('inspect');p.add_argument('--filesystem',required=True);p.add_argument('--json',action='store_true')
        p=sub.add_parser('reserve')
        for option in ('project','run','output','policy','idempotency-key'): p.add_argument('--'+option,required=True)
        p.add_argument('--estimated-output-bytes',required=True,type=int)
        p.add_argument('--estimated-inodes',required=True,type=int)
        for verb in ('renew','update','release','recover-stale'):
            p=sub.add_parser(verb);p.add_argument('reservation');p.add_argument('--expected-revision',required=True,type=int)
            if verb=='update':
                p.add_argument('--estimated-output-bytes',required=True,type=int)
                p.add_argument('--estimated-inodes',type=int)
            if verb=='recover-stale': p.add_argument('--plan',required=True);p.add_argument('--approval',required=True)
        args=vars(parser.parse_args());args.pop('json',None);args['area']='storage-budget'
        if args['action']=='update' and args.get('estimated_inodes') is None: args.pop('estimated_inodes',None)
    elif name == 'service-alerts':
        sub.add_parser('show')
        p = sub.add_parser('add', help='register a source; read its SSH public key from stdin')
        p.add_argument('source'); p.add_argument('label'); p.add_argument('recipient')
        for verb in ('disable', 'enable', 'remove'):
            sub.add_parser(verb).add_argument('source')
        p = sub.add_parser('update')
        p.add_argument('source'); p.add_argument('label'); p.add_argument('recipient')
        sub.add_parser('key', help='replace a source public key from stdin').add_argument('source')
        sub.add_parser('send', help='send body from stdin as a source you own').add_argument('source')
        args = vars(parser.parse_args())
        if args['action'] in ('add', 'key'):
            args['key'] = sys.stdin.read(8193).strip()
        if args['action'] == 'send':
            args['body'] = body()
        args['area'] = 'alerts'
    elif name == 'agent-admin':
        sub.add_parser('show')
        for verb in ('grant', 'revoke'):
            p = sub.add_parser(verb)
            p.add_argument('agent'); p.add_argument('capabilities', nargs='+', choices=['diagnostics', 'smb', 'network', 'services', 'packages', 'all'])
        for verb in ('grant-scoped','revoke-scoped'):
            p=sub.add_parser(verb);p.add_argument('agent')
            p.add_argument('capability',choices=['board-maintenance','coms-maintenance','tooling-maintenance','runtime-maintenance','storage-maintenance'])
            if verb=='grant-scoped':
                p.add_argument('--scope',required=True);p.add_argument('--approval',required=True);p.add_argument('--until')
        p=sub.add_parser('show-scoped');p.add_argument('agent')
        p=sub.add_parser('approve-plan');p.add_argument('agent');p.add_argument('--plan-sha256',required=True);p.add_argument('--approval',required=True)
        args = vars(parser.parse_args()); args['area'] = 'admin'
    else:
        sub.add_parser('status')
        p=sub.add_parser('tooling');s=p.add_subparsers(dest='verb',required=True)
        s.add_parser('status');s.add_parser('verify')
        p=s.add_parser('plan');p.add_argument('release')
        p=s.add_parser('apply');p.add_argument('plan');p.add_argument('--expect-plan-sha256',dest='expected_plan_sha256',required=True);p.add_argument('--approval',required=True)
        p=s.add_parser('job-status');p.add_argument('job')
        p=s.add_parser('rollback');p.add_argument('job');p.add_argument('--approval',required=True)
        p = sub.add_parser('packages'); s = p.add_subparsers(dest='verb', required=True)
        s.add_parser('search').add_argument('query')
        s.add_parser('show').add_argument('package')
        s.add_parser('install').add_argument('packages', nargs='+')
        s.add_parser('refresh', help='refresh APT repository indexes; does not upgrade packages')
        s.add_parser('status').add_argument('job', nargs='?', default='latest')
        p = sub.add_parser('smb'); s = p.add_subparsers(dest='verb', required=True)
        s.add_parser('show')
        p = s.add_parser('add'); p.add_argument('name'); p.add_argument('share')
        for verb in ('mount', 'unmount', 'remove'):
            s.add_parser(verb).add_argument('name')
        p = sub.add_parser('network'); s = p.add_subparsers(dest='verb', required=True)
        s.add_parser('show')
        s.add_parser('edit', help='edit /etc/network/interfaces in nano, then apply with automatic rollback')
        s.add_parser('interfaces', help='show /etc/network/interfaces')
        p = s.add_parser('route-add'); p.add_argument('name'); p.add_argument('destination'); p.add_argument('gateway'); p.add_argument('interface')
        p = s.add_parser('confirm'); p.add_argument('token')
        p = s.add_parser('route-remove'); p.add_argument('name')
        p = sub.add_parser('services'); s = p.add_subparsers(dest='verb', required=True)
        s.add_parser('show')
        for verb in ('status', 'restart'):
            s.add_parser(verb).add_argument('unit', choices=['cron.service', 'rsyslog.service', 'systemd-timesyncd.service'])
        args = vars(parser.parse_args()); args['area'] = 'host'
        if args['action'] == 'network' and args['verb'] in ('edit', 'interfaces'):
            original = json.loads(request({'area':'host','action':'network','verb':'get-interfaces'}, display=False))
            if args['verb'] == 'interfaces':
                print(original['content'], end='')
                return
            with tempfile.TemporaryDirectory(prefix='.ai-box-network-', dir=Path.home()) as folder:
                target = Path(folder) / 'interfaces'
                target.write_text(original['content'])
                target.chmod(0o600)
                subprocess.run(['/usr/bin/nano','--',str(target)], check=True)
                edited = target.read_text()
            if edited == original['content']:
                print('No changes.'); return
            request({'area':'host','action':'network','verb':'apply-interfaces',
                     'sha256':original['sha256'],'content':edited})
            return
        if args['action'] == 'smb' and args['verb'] == 'add':
            args['username'] = input('SMB username: ')
            args['password'] = getpass.getpass('SMB password (hidden): ')
            args['domain'] = input('SMB domain (Enter for none): ')
    result=request(args)
    if args.get('area')=='storage-budget' and json.loads(result).get('state')=='SAFE_BOUNDARY_STOP_REQUIRED':
        raise SystemExit(3)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print(f'{Path(sys.argv[0]).name}: {error}', file=sys.stderr)
        sys.exit(2)
