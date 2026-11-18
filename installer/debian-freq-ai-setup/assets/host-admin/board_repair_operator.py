#!/usr/bin/python3 -I
"""Operator-only, pinned, single-file reason repair. No shared journal replay.

All mutable board traversal and publication use opened directory handles.
Private intent, before-image and receipt stay outside collaborative storage.
This is the narrow operator executor, not the future delegated maintenance API.
"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

BOARD=Path('/var/lib/freq-agents/board/projects')
PRIVATE=Path('/var/backups/freq-board-repair')
MAX_BYTES=2*1024*1024

def sha(data):return hashlib.sha256(data).hexdigest()

def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()

def directory(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise ValueError('Absolute canonical directory required')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for name in path.parts[1:]:
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        return fd
    except BaseException:os.close(fd);raise

def read_at(fd,name):
    opened=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    try:
        meta=os.fstat(opened)
        if not stat.S_ISREG(meta.st_mode) or meta.st_size>MAX_BYTES or meta.st_nlink!=1:
            raise ValueError('Expected bounded, unlinked regular task or receipt')
        data=b''
        while part:=os.read(opened,65536):
            data+=part
            if len(data)>MAX_BYTES:raise ValueError('File exceeded bound')
        return data,meta
    finally:os.close(opened)

def publish_at(fd,name,data,mode=0o600,owner=None,attributes=None):
    temporary='.repair-'+uuid.uuid4().hex
    opened=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode,dir_fd=fd)
    try:
        with os.fdopen(opened,'wb') as stream:
            stream.write(data);stream.flush()
            if owner:os.fchown(stream.fileno(),*owner)
            if attributes is not None:
                for key in os.listxattr(stream.fileno()):
                    if key not in attributes:os.removexattr(stream.fileno(),key)
                for key,value in attributes.items():os.setxattr(stream.fileno(),key,value)
            os.fchmod(stream.fileno(),mode);os.fsync(stream.fileno())
            if attributes is None and os.listxattr(stream.fileno()):raise ValueError('Unexpected inherited ACL/xattrs in private journal')
        os.replace(temporary,name,src_dir_fd=fd,dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:os.unlink(temporary,dir_fd=fd)
        except FileNotFoundError:pass

@contextmanager
def locked_task(core):
    if not re.fullmatch('[A-Z0-9]+(?:-[A-Z0-9]+)*',core['project']):raise ValueError('Invalid project')
    title=core['task']
    if not title or '/' in title or title.startswith('.') or '\n' in title or len(title)>160:
        raise ValueError('Invalid task')
    if core['path']!='blocked/'+title+'.md':raise ValueError('Only in-place blocked reason repair supported')
    root=directory(BOARD)
    project=blocked=None
    try:
        project=os.open(core['project'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        fcntl.flock(project,fcntl.LOCK_EX)
        blocked=os.open('blocked',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=project)
        yield blocked,title+'.md'
    finally:
        if blocked is not None:os.close(blocked)
        if project is not None:os.close(project)
        os.close(root)

def execute(plan,expected,approval,apply=False):
    if type(approval)is not str or not re.fullmatch('[A-Za-z0-9._:/-]{1,160}',approval):raise ValueError('Approval reference required')
    core=plan['plan'];operation=str(uuid.UUID(plan['plan_id']))
    if sha(canonical(core))!=expected or expected!=plan['sha256']:raise ValueError('Plan digest mismatch')
    if str(uuid.uuid5(uuid.NAMESPACE_URL,'freq-board-plan:'+expected))!=operation:raise ValueError('Plan identity mismatch')
    after=core['after'].encode()
    if len(after)>MAX_BYTES or sha(after)!=core['after_sha256']:raise ValueError('After-image mismatch')
    # Recompute the exact permitted edit rather than trusting arbitrary pinned
    # replacement content: only a reason insertion and one repair history row.
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'board-system/lib'))
    sys.path.append('/usr/local/lib')
    import freq_board as board
    with locked_task(core) as (fd,name):
        before,meta=read_at(fd,name)
        opened=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            current=os.fstat(opened)
            if (current.st_dev,current.st_ino)!=(meta.st_dev,meta.st_ino):raise ValueError('Changed task identity')
            attributes={key:os.getxattr(opened,key) for key in os.listxattr(opened)}
            if any(key!='system.posix_acl_access' and not key.startswith('user.') for key in attributes):
                raise ValueError('Security/trusted attributes require a separate plan')
            if sum(len(v) for v in attributes.values())>65536:raise ValueError('Extended metadata exceeds bound')
        finally:os.close(opened)
        if not apply:
            if sha(before)!=core['before_sha256'] or sha(core['path'].encode()+b'\0'+before)!=core['before_revision']:
                raise ValueError('Stale revision')
        else:
            # Only operator-owned ancestors are permitted for the private journal.
            parent=directory(PRIVATE.parent)
            try:
                parent_meta=os.fstat(parent)
                if parent_meta.st_uid!=os.geteuid() or parent_meta.st_mode&0o022:raise ValueError('Unsafe backup parent')
                try:os.mkdir(PRIVATE.name,0o700,dir_fd=parent);os.fsync(parent)
                except FileExistsError:pass
            finally:os.close(parent)
            private=directory(PRIVATE)
            try:
                m=os.fstat(private)
                if m.st_uid!=os.geteuid() or m.st_mode&0o077:raise ValueError('Unsafe private journal')
                try:os.mkdir(operation,0o700,dir_fd=private);os.fsync(private)
                except FileExistsError:pass
                journal=os.open(operation,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=private)
            finally:os.close(private)
            try:
                m=os.fstat(journal)
                if m.st_uid!=os.geteuid() or m.st_mode&0o077:raise ValueError('Unsafe operation directory')
                try:prepared=json.loads(read_at(journal,'prepared.json')[0])
                except FileNotFoundError:prepared=None
                if prepared:
                    if prepared['plan_sha256']!=expected or prepared['approval']!=approval:
                        raise ValueError('Operation already bound to another intent')
                    original=read_at(journal,'before.bin')[0]
                    if sha(original)!=core['before_sha256']:raise ValueError('Backup checksum mismatch')
                    if sha(before)==core['after_sha256']:
                        os.fsync(fd)
                        result={**prepared,'state':'COMMITTED','replayed':True,'after_sha256':sha(before)}
                        publish_at(journal,'committed.json',canonical(result))
                        return result
                if sha(before)!=core['before_sha256'] or sha(core['path'].encode()+b'\0'+before)!=core['before_revision']:
                    raise ValueError('Stale revision; no task write')
                result=validate_edit(board,core,before,meta,expected,approval,operation)
                result['metadata']['attributes']={k:base64.b64encode(v).decode() for k,v in attributes.items()}
                if not prepared:
                    publish_at(journal,'before.bin',before)
                    publish_at(journal,'after.bin',after)
                    publish_at(journal,'prepared.json',canonical(result))
                publish_at(fd,name,after,stat.S_IMODE(meta.st_mode),(meta.st_uid,meta.st_gid),attributes)
                check,after_meta=read_at(fd,name)
                if sha(check)!=core['after_sha256']:raise ValueError('Post-publication conflict; preserve journal')
                result={**result,'state':'COMMITTED','after_sha256':sha(check)}
                publish_at(journal,'committed.json',canonical(result))
                return result
            finally:os.close(journal)
        result=validate_edit(board,core,before,meta,expected,approval,operation)
        return {**result,'state':'DRY_RUN','diff':core['diff']}

def validate_edit(board,core,before,meta,expected,approval,operation):
    content=before.decode('utf-8');intent=core['intent']
    if 'FREQ_BOARD_BLOCKED_BEGIN' in content:raise ValueError('Existing reason cannot be overwritten')
    owners=re.findall(r'^- (?:Assigned to|Transferred to): `([a-z][a-z0-9_-]*)`$',content,re.M)
    if not owners or owners[-1]!=intent['responsibility'] or intent['intended_state']!='blocked':
        raise ValueError('Responsibility or intent mismatch')
    if (intent['project'],intent['task'])!=(core['project'],core['task']):raise ValueError('Intent target mismatch')
    board.validate_reason(intent['reason'])
    after=board.set_blocked_reason(content,intent['reason'])
    after=board.append_history(after,'- **REASON REPAIR** — owner-confirmed current wording; incident `'+core['incident']+'`; responsibility `'+owners[-1]+'`; no completion, acceptance or reassignment.')
    if after!=core['after']:raise ValueError('Plan contains changes beyond supported repair')
    return {'schema':1,'operation_id':operation,'plan_sha256':expected,'approval':approval,'actor_uid':os.geteuid(),
            'scope':'reason-repair','project':core['project'],'target':core['path'],'responsibility':owners[-1],
            'before_sha256':sha(before),'state':'PREPARED','backup':str(PRIVATE/operation/'before.bin'),
            'metadata':{'uid':meta.st_uid,'gid':meta.st_gid,'mode':stat.S_IMODE(meta.st_mode)}}

def rollback(plan,expected,approval,apply=False):
    if sha(canonical(plan['plan']))!=expected or expected!=plan['sha256']:raise ValueError('Plan digest mismatch')
    if not re.fullmatch('[A-Za-z0-9._:/-]{1,160}',approval):raise ValueError('Approval reference required')
    core=plan['plan'];operation=str(uuid.UUID(plan['plan_id']))
    private=directory(PRIVATE/operation)
    try:
        m=os.fstat(private)
        if m.st_uid!=os.geteuid() or m.st_mode&0o077:raise ValueError('Unsafe private journal')
        prepared=json.loads(read_at(private,'prepared.json')[0])
        original=read_at(private,'before.bin')[0]
        if prepared['plan_sha256']!=expected or sha(original)!=core['before_sha256']:raise ValueError('Backup identity mismatch')
        with locked_task(core) as (fd,name):
            current,_=read_at(fd,name)
            try:previous=json.loads(read_at(private,'rollback-prepared.json')[0])
            except FileNotFoundError:previous=None
            if sha(current)==core['before_sha256'] and previous and previous['approval']==approval:
                if apply:
                    os.fsync(fd);publish_at(private,'rollback-committed.json',canonical({**previous,'state':'ROLLED_BACK'}))
                return {**previous,'state':'ROLLED_BACK' if apply else 'DRY_RUN','replayed':True}
            if sha(current)!=core['after_sha256']:raise ValueError('Task changed since repair; rollback refused')
            result={'operation_id':operation,'plan_sha256':expected,'approval':approval,'state':'DRY_RUN',
                    'actor_uid':os.geteuid(),'target':core['path'],'restored_sha256':sha(original)}
            if apply:
                if previous and previous['approval']!=approval:raise ValueError('Rollback already bound to another approval')
                publish_at(private,'rollback-prepared.json',canonical({**result,'state':'ROLLBACK_PREPARED'}))
                metadata=prepared['metadata'];attributes={k:base64.b64decode(v,validate=True) for k,v in metadata['attributes'].items()}
                publish_at(fd,name,original,metadata['mode'],(metadata['uid'],metadata['gid']),attributes)
                result['state']='ROLLED_BACK';publish_at(private,'rollback-committed.json',canonical(result))
            return result
    finally:os.close(private)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan');parser.add_argument('--sha256',required=True)
    parser.add_argument('--approval',required=True);parser.add_argument('--apply',action='store_true')
    parser.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0:raise ValueError('Operator root required; no delegation implied')
    path=Path(args.plan);parent=directory(path.absolute().parent)
    try:
        raw,meta=read_at(parent,path.name)
        if meta.st_uid or meta.st_mode&0o022:raise ValueError('Plan must be root-owned and not writable by others')
    finally:os.close(parent)
    action=rollback if args.rollback else execute
    print(json.dumps(action(json.loads(raw),args.sha256,args.approval,args.apply),indent=2))

if __name__=='__main__':main()
