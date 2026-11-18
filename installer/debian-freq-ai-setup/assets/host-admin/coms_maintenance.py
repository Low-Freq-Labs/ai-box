"""Metadata-only inspection and original-identity proven-undelivered retry."""
import json
import grp
import os
from pathlib import Path
import pwd
import sqlite3
import sys
import time
import uuid
import stat
sys.path.append('/usr/local/lib')

COMS=Path('/var/lib/freq-agents/coms')
DISCORD_DB=Path('/var/lib/freq-discord/deliveries.sqlite')


def receipt(sender,ident):
    """Opened directories prevent agent-controlled symlink substitution at root."""
    from freq_coms_receipts import public
    base=Path('/var/lib/freq-discord/receipts') if sender=='freq-discord' else COMS/sender/'receipts'
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in base.parts[1:]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        file=os.open(str(uuid.UUID(ident))+'.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        with os.fdopen(file,'rb') as stream:
            meta=os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or meta.st_uid!=pwd.getpwnam(sender).pw_uid:
                raise ValueError('Unsafe receipt owner/type')
            raw=stream.read(2*1024*1024+8193)
            if len(raw)>2*1024*1024+8192:raise ValueError('Receipt exceeds bound')
            value=json.loads(raw)
        if value.get('sender')!=sender or value.get('sender_uid')!=pwd.getpwnam(sender).pw_uid or value.get('message_id')!=ident:
            raise ValueError('Receipt identity mismatch')
        return public(value)
    finally:os.close(fd)


def lookup(names,ident):
    from freq_coms_receipts import read,public
    ident=str(uuid.UUID(ident));matches=[]
    for sender in [*names,'freq-discord']:
        try:matches.append(receipt(sender,ident))
        except FileNotFoundError:continue
    if len(matches)!=1: raise ValueError('Unknown or ambiguous message ID')
    value=matches[0]
    if value['recipient']=='sonny' and value.get('filename'):
        remote=ledger('lookup',value['filename'])
        value['downstream_state']=remote.pop('state')
        value.update({k:v for k,v in remote.items() if k.startswith('discord_')})
    return value


def ledger(action,filename=None):
    import subprocess
    user=pwd.getpwnam('freq-discord')
    result=subprocess.run(['/usr/bin/python3','-I','-B',str(Path(__file__).with_name('coms_ledger.py')),action,*([filename] if filename else [])],
        user=user.pw_uid,group=user.pw_gid,extra_groups=[],env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},
        capture_output=True,text=True,timeout=5)
    if result.returncode:raise ValueError('Discord ledger inspection unavailable')
    if len(result.stdout)>8192:raise ValueError('Discord metadata exceeds bound')
    return json.loads(result.stdout)


def dispatch(b,r,actor,uid,operator,state):
    from maintenance import authorize,audit
    if r['area']=='coms-status':
        b.fields(r,'area message')
        value=lookup(b.agents(),r['message'])
        b.require(operator or actor in (value['sender'],value['recipient']),'Receipt is private to its participants')
        return value
    grant=authorize(b,state,actor,uid,'coms-maintenance','coms:shared',operator)
    action=r['action']
    if action=='health':
        b.fields(r,'area action')
        counts={};oldest=None
        from freq_coms_receipts import read
        for sender in b.agents():
            folder=COMS/sender/'receipts'
            if folder.is_symlink(): raise ValueError('Unsafe receipt directory')
            for index,path in enumerate(folder.glob('*.json')):
                if index>=10000: raise ValueError('Receipt health scan bound exceeded')
                try:
                    v=receipt(sender,path.stem);stage=v['state'];counts[stage]=counts.get(stage,0)+1
                    stamp=v['created_at'];oldest=stamp if oldest is None else min(oldest,stamp)
                except (OSError,ValueError,KeyError): counts['CORRUPT']=counts.get('CORRUPT',0)+1
        fs=os.statvfs(COMS)
        discord=ledger('health')
        return {'schema':1,'states':counts,'discord_ledger':discord,'oldest_receipt_age_seconds':time.time()-oldest if oldest else None,
                'free_bytes':fs.f_bavail*fs.f_frsize,'free_inodes':fs.f_favail,
                'history_deleted':False,'legacy_messages':'Messages created before receipt rollout have no synthetic delivery claim'}
    if action=='inspect':
        b.fields(r,'area action message')
        return lookup(b.agents(),r['message'])
    if action=='retry':
        b.fields(r,'area action message expected_revision approval')
        value=lookup(b.agents(),r['message'])
        b.require(value['revision']==r['expected_revision'],'Stale receipt revision')
        b.require(value.get('downstream_state') not in ('DELIVERY_UNCERTAIN','DISCORD_POSTED'),'Remote post is uncertain or already posted; retry refused')
        b.require(value['state'] in ('NOT_STORED','NOTIFICATION_PENDING','DURABLY_STORED'),'Original message is not proven retryable')
        b.require(isinstance(r['approval'],str) and r['approval']==grant['approval'] if not operator else bool(r['approval']), 'Retry requires the scoped approval reference')
        audit_receipt=audit(b,actor,'COMS_RETRY',{'message_id':value['message_id'],'approval':r['approval'],'scope':grant['scope'],'before_revision':value['revision']})
        user=b.pwd.getpwnam(value['sender'])
        result=b.run(['/usr/bin/python3','-I','/usr/local/lib/freq_coms_receipts.py','retry',value['message_id'],str(value['revision'])],
                     user=user.pw_uid,group=grp.getgrnam('freq-agents').gr_gid,timeout=30)
        audit(b,actor,'COMS_RETRY_RESULT',{'operation':audit_receipt,'state':'RETURNED'})
        return json.loads(result)
    if action=='reconcile':
        b.fields(r,'area action message')
        value=lookup(b.agents(),r['message'])
        value['reconciliation']='Confirmed by local Discord acknowledgment' if value.get('downstream_state')=='DISCORD_POSTED' else 'No definitive remote acknowledgment; uncertainty retained'
        value['resent']=False
        return value
    if action=='discord-status':
        b.fields(r,'area action filename')
        import re
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}_[0-9]+_[0-9]+_[a-z][a-z0-9_-]*\.json',r['filename']):raise ValueError('Exact generated outbox filename required')
        return ledger('lookup',r['filename'])
    raise ValueError('Unknown communications maintenance operation')
