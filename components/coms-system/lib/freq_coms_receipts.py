#!/usr/bin/env python3
"""Private sender receipts; complete envelopes retained independently of delivery."""
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
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

LIMIT=1024*1024


def root():
    if os.environ.get('FREQ_COMS_TESTING')=='1':
        value=Path(os.environ['FREQ_COMS_ROOT'])
        if value==Path('/var/lib/freq-agents/coms'): raise ValueError('Fixture receipt root must be isolated')
        return value
    return Path('/var/lib/freq-agents/coms')


def actor():
    value=pwd.getpwuid(os.geteuid()).pw_name
    if os.environ.get('FREQ_COMS_TESTING')=='1': value=os.environ.get('FREQ_COMS_TEST_SENDER',value)
    return value


def directory(create=False):
    sender=actor()
    base=root()/sender
    if sender=='freq-discord' and os.environ.get('FREQ_COMS_TESTING')!='1': base=Path('/var/lib/freq-discord')
    if create and os.environ.get('FREQ_COMS_TESTING')=='1': base.mkdir(parents=True,exist_ok=True)
    if base.is_symlink() or not base.is_dir(): raise ValueError('Sender receipt parent unavailable')
    path=base/'receipts'
    if create:
        path.mkdir(mode=0o700,exist_ok=True)
        sync(base)
    if path.is_symlink(): raise ValueError('Unsafe receipt directory')
    if path.exists():
        meta=path.stat()
        # Shared comms parents are setgid: mkdir(0700) inherits 02000 on Linux.
        # Setgid controls group inheritance, not access; both modes stay private.
        if meta.st_uid!=os.geteuid() or stat.S_IMODE(meta.st_mode) not in (0o700,0o2700): raise ValueError('Receipt directory must be private to sender')
    return path


def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def read(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        meta=os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_size>LIMIT*2+8192: raise ValueError('Invalid receipt file')
        return json.load(stream)


def write(path,value):
    temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path);sync(path.parent)
    finally:
        if temp.exists(): temp.unlink()


def public(value):
    fields=('schema','message_id','sender','sender_uid','recipient','body_bytes','body_sha256',
            'envelope_sha256','revision','created_at','updated_at','state','boundary','filename')
    return {k:value[k] for k in fields if k in value}


def begin(recipient,title,key,body):
    if not re.fullmatch('[a-z][a-z0-9_-]{0,63}',recipient): raise ValueError('Invalid recipient')
    if len(body.encode())>LIMIT or not body.strip(): raise ValueError('Message body is empty or oversized')
    if key and not re.fullmatch('[a-zA-Z0-9._:-]{1,128}',key): raise ValueError('Invalid idempotency key')
    ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'freq-coms:'+actor()+':'+key)) if key else str(uuid.uuid4())
    print('MESSAGE-ID: '+ident,file=sys.stderr)
    envelope_hash=hashlib.sha256(json.dumps([actor(),recipient,title,body],ensure_ascii=False).encode()).hexdigest()
    folder=directory(True)
    lock=os.open(folder/'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=folder/(ident+'.json')
        if path.exists():
            value=read(path)
            if value['envelope_sha256']!=envelope_hash: raise ValueError('Idempotency key conflicts with existing message')
            return ident,False,value
        records=list(folder.glob('*.json'))
        if len(records)>=10000 or sum(p.lstat().st_size for p in records)>128*1024*1024:
            raise ValueError('Receipt retention budget reached; archive through reviewed maintenance before new messages')
        value={'schema':1,'message_id':ident,'sender':actor(),'sender_uid':os.geteuid(),
               'recipient':recipient,'title':title,'body':body,'body_bytes':len(body.encode()),
               'body_sha256':hashlib.sha256(body.encode()).hexdigest(),'envelope_sha256':envelope_hash,
               'idempotency_key':key,'revision':1,'created_at':time.time(),'updated_at':time.time(),
               'state':'NOT_STORED','boundary':'ENVELOPE_DURABLE','filename':None}
        write(path,value)
        return ident,True,value
    finally: os.close(lock)


def update(ident,state,boundary,filename=None):
    path=directory()/(str(uuid.UUID(ident))+'.json')
    lock=os.open(directory()/'.lock',os.O_RDWR|os.O_NOFOLLOW)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX)
        value=read(path)
        value.update(state=state,boundary=boundary,revision=value['revision']+1,updated_at=time.time())
        if filename: value['filename']=filename
        write(path,value)
        return value
    finally: os.close(lock)


def publish(ident,temp,target,discord=False):
    value=read(directory()/(str(uuid.UUID(ident))+'.json'))
    temp,target=Path(temp),Path(target)
    if temp.parent!=target.parent or target.parent.is_symlink(): raise ValueError('Invalid publication directory')
    expected=(Path(os.environ.get('FREQ_DISCORD_ROOT','/var/lib/freq-agents/discord'))/'outbox'
              if discord else root()/value['recipient']/'inbox')
    if os.environ.get('FREQ_COMS_TESTING')!='1' and discord: expected=Path('/var/lib/freq-agents/discord/outbox')
    if target.parent!=expected or target.name.startswith('.') or target.suffix not in ('.md','.json'): raise ValueError('Publication target outside message scope')
    fd=os.open(temp,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        meta=os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_size>LIMIT*2: raise ValueError('Invalid staged message')
        data=stream.read(LIMIT*2+1)
        content=json.loads(data)['message'].encode() if discord else data
        if len(content)!=value['body_bytes'] or hashlib.sha256(content).hexdigest()!=value['body_sha256']:
            raise ValueError('Staged body length/checksum mismatch')
        os.fsync(stream.fileno())
    update(ident,'STORING','BEFORE_PUBLICATION',target.name)
    os.link(temp,target,follow_symlinks=False)
    sync(target.parent)
    update(ident,'DISCORD_QUEUED' if discord else 'DURABLY_STORED','PUBLICATION_DURABLE',target.name)


def retry(ident,expected_revision):
    """Original identity only. Never retry a possibly pasted or posted message."""
    path=directory()/(str(uuid.UUID(ident))+'.json')
    lock=os.open(directory()/'.lock',os.O_RDWR|os.O_NOFOLLOW)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX)
        value=read(path)
        if value['revision']!=expected_revision: raise ValueError('Stale message revision')
        if not value.get('title'): raise ValueError('Titleless service/Discord ingress retry requires its original transport authority')
        if value['state'] not in ('NOT_STORED','NOTIFICATION_PENDING','DURABLY_STORED'):
            raise ValueError('Delivery is not proven retryable; reconcile uncertainty first')
        if value['sender']!=actor() or value['sender_uid']!=os.geteuid(): raise ValueError('Sender identity mismatch')
        def save(state,boundary):
            value.update(state=state,boundary=boundary,revision=value['revision']+1,updated_at=time.time())
            write(path,value)
        discord=value['recipient']=='sonny'
        destination=Path('/var/lib/freq-agents/discord/outbox') if discord else root()/value['recipient']/'inbox'
        if not value['filename']:
            stamp=datetime.fromtimestamp(value['created_at'],ZoneInfo('America/Chicago')).strftime('%Y-%m-%d_%H%M%S')
            value['filename']=stamp+'_000000000_'+str(uuid.UUID(ident).int)+'_'+actor()+('.json' if discord else '.md')
        target=destination/value['filename']
        candidates=[target] if discord else [target,root()/value['recipient']/'read'/value['filename']]
        found=[p for p in candidates if p.exists()]
        if len(found)>1: raise ValueError('Multiple envelope locations; reconcile first')
        raw=(json.dumps({'schema':1,'sender':actor(),'title':value['title'],'message':value['body']},ensure_ascii=False).encode()
             if discord else value['body'].encode())
        if found:
            fd=os.open(found[0],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ValueError('Invalid envelope path')
                existing=stream.read(LIMIT*2+1)
            body=json.loads(existing)['message'].encode() if discord else existing
            if hashlib.sha256(body).hexdigest()!=value['body_sha256']: raise ValueError('Envelope changed; refuse retry')
        else:
            save('STORAGE_UNCERTAIN','RETRY_PUBLICATION_INTENT')
            temp=destination/('.receipt-'+ident+'-'+uuid.uuid4().hex)
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o660)
            try:
                with os.fdopen(fd,'wb') as stream:
                    os.fchmod(stream.fileno(),0o660);stream.write(raw);stream.flush();os.fsync(stream.fileno())
                os.link(temp,target,follow_symlinks=False);sync(destination)
            finally:
                if temp.exists(): temp.unlink()
        if discord:
            save('DISCORD_QUEUED','ORIGINAL_IDENTITY_QUEUED')
            return public(value)
        save('NOTIFICATION_PENDING','ORIGINAL_ENVELOPE_DURABLE')
        socket=Path('/run/freq-agents/tmux')/('agent-'+value['recipient'])
        if not socket.is_socket(): return public(value)
        delivery_lock=os.open(socket.parent/('.dev-msg-'+value['recipient']+'.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o660)
        try:
            fcntl.flock(delivery_lock,fcntl.LOCK_EX)
            def tmux(*args,body=None):
                return subprocess.run(['/usr/bin/tmux','-S',str(socket),*args],input=body,text=True,capture_output=True,check=True,timeout=10)
            rows=tmux('list-panes','-a','-F','#{pane_id}|#{session_name}|#{window_name}|#{pane_dead}|#{@freq_delivery_pane}').stdout.splitlines()
            panes=[parts[0] for row in rows if len(parts:=row.split('|'))==5 and parts[1:]==[value['recipient'],'agent','0','1'] and re.fullmatch('%[0-9]+',parts[0])]
            if len(panes)!=1: return public(value)
            buffer='receipt-'+uuid.UUID(ident).hex
            payload=f"{actor().upper()}-MSG: [{value['title']}]\n  → dev-read {value['filename']}"
            tmux('load-buffer','-b',buffer,'-',body=payload)
            save('DELIVERY_UNCERTAIN','BEFORE_RETRY_PASTE')
            try:
                tmux('paste-buffer','-p','-r','-b',buffer,'-d','-t',panes[0])
                time.sleep(.5);tmux('send-keys','-t',panes[0],'Enter')
                time.sleep(.5);tmux('send-keys','-t',panes[0],'Enter')
            finally:
                subprocess.run(['/usr/bin/tmux','-S',str(socket),'delete-buffer','-b',buffer],capture_output=True,timeout=10)
            save('NOTIFIED_TO_PANE','RETRY_ENTERS_CONFIRMED')
            return public(value)
        finally: os.close(delivery_lock)
    finally: os.close(lock)


def main():
    action=sys.argv[1]
    if action=='begin':
        body=sys.stdin.buffer.read(LIMIT+1).decode('utf-8')
        ident,new,value=begin(sys.argv[2],sys.argv[3],sys.argv[4],body)
        print(ident+'|'+('NEW' if new else 'EXISTING')+'|'+value['state'])
    elif action=='state': update(*sys.argv[2:])
    elif action=='failure':
        ident=sys.argv[2]
        value=read(directory()/(str(uuid.UUID(ident))+'.json'))
        state=value['state']
        if state=='STORING': state='STORAGE_UNCERTAIN'
        elif state=='DURABLY_STORED': state='NOTIFICATION_PENDING'
        update(ident,state,sys.argv[3])
    elif action=='publish': publish(*sys.argv[2:5],discord=sys.argv[5]=='discord')
    elif action=='status': print(json.dumps(public(read(directory()/(str(uuid.UUID(sys.argv[2]))+'.json'))),indent=2))
    elif action=='retry': print(json.dumps(retry(sys.argv[2],int(sys.argv[3])),indent=2))
    else: raise ValueError('Unknown receipt operation')


if __name__=='__main__':
    try: main()
    except Exception as error:
        print('Receipt boundary failed: '+type(error).__name__,file=sys.stderr);sys.exit(1)
