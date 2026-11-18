"""Serialized capacity admission for explicitly participating shared-project runs.

Reservations are not a filesystem quota. Unregistered writers remain visible in
statvfs headroom and can force safe-boundary refusal. No automatic kill/delete.
"""
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid

GIB=1024**3
POLICY='shared-output-v1'
CONTROL_BYTES=64*1024**2
CONTROL_INODES=4096
FLOOR_BYTES=10*GIB
WARNING_BYTES=20*GIB
BASE=Path('/home/freq-agents/projects')


def open_output(value):
    path=Path(value)
    if not path.is_absolute() or '..' in path.parts or path==BASE or not path.is_relative_to(BASE):
        raise ValueError('Output must be an existing directory below shared projects')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=next_fd
        return fd
    except BaseException:
        os.close(fd);raise


def footprint(fd,limit=200000):
    """Allocated blocks/inodes, deduplicated by device+inode; no link traversal."""
    seen=set();used=0;device=os.fstat(fd).st_dev
    def walk(directory):
        nonlocal used
        for name in os.listdir(directory):
            meta=os.stat(name,dir_fd=directory,follow_symlinks=False)
            if meta.st_dev!=device:
                raise ValueError('Output crosses filesystem boundary; retain reservation')
            key=(meta.st_dev,meta.st_ino)
            if key in seen: continue
            seen.add(key)
            if len(seen)>limit: raise ValueError('Output accounting bound exceeded; retain reservation')
            used+=meta.st_blocks*512
            if stat.S_ISDIR(meta.st_mode):
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                try: walk(child)
                finally: os.close(child)
    walk(fd)
    return used,len(seen)


class Budget:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=10,isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('''CREATE TABLE IF NOT EXISTS reservations(
            id TEXT PRIMARY KEY,owner TEXT NOT NULL,uid INTEGER NOT NULL,project TEXT NOT NULL,
            run TEXT NOT NULL,path TEXT NOT NULL,device INTEGER NOT NULL,inode INTEGER NOT NULL,
            estimate INTEGER NOT NULL,inodes INTEGER NOT NULL,baseline INTEGER NOT NULL,
            baseline_inodes INTEGER NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL,
            expires REAL NOT NULL,key TEXT NOT NULL,request TEXT NOT NULL,UNIQUE(uid,key))''')
        self.db.execute('CREATE TABLE IF NOT EXISTS events(id TEXT,actor TEXT,action TEXT,revision INTEGER,time REAL,details TEXT)')
        self.db.row_factory=sqlite3.Row

    def close(self): self.db.close()

    def event(self,row,actor,action,details):
        self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(row['id'],actor,action,row['revision'],time.time(),json.dumps(details)))

    def capacity(self,fd,exclude=None):
        v=os.fstatvfs(fd);device=os.fstat(fd).st_dev
        committed=0;inode_commit=0;uncertain=[]
        for raw in self.db.execute("SELECT * FROM reservations WHERE state='ACTIVE' AND device=?",(device,)):
            row=dict(raw)
            if row['id']==exclude: continue
            # Keep full commitments until explicit release. Paths are writable:
            # moved-in files or hardlinks cannot prove this run consumed new
            # filesystem capacity. Crediting them can admit overlapping claims.
            committed+=2*row['estimate']
            inode_commit+=2*row['inodes']
            if row['expires']<time.time(): uncertain.append(row['id'])
        available=v.f_bavail*v.f_frsize
        try:
            from control_capacity import snapshot
            physical_control=snapshot()
            physical_control['applies_to_inspected_filesystem']=physical_control['filesystem_device']==device
        except Exception as exc:
            physical_control={'armed':False,'diagnostic_error':type(exc).__name__}
        return {'policy':POLICY,'filesystem_device':device,'physical_available':available,
                'available_inodes':v.f_favail,'other_commitments':committed,'other_inode_commitments':inode_commit,
                'control_reserve_bytes':CONTROL_BYTES,'control_reserve_inodes':CONTROL_INODES,
                'effective_free':available-committed-CONTROL_BYTES,
                'effective_inodes':v.f_favail-inode_commit-CONTROL_INODES,
                'warning':available<WARNING_BYTES,'uncertain_or_expired':sorted(set(uncertain)),
                'enforcement':'Admission and participant checkpoints; not an OS quota',
                'accounting':'Conservative full commitments retained until release; no credit for apparent output growth',
                'protected_capacity':'Host-root physical emergency reserve; check applies_to_inspected_filesystem; not a quota or exclusive capacity after release',
                'physical_control_reserve':physical_control}

    def handle(self,request,actor,uid,operator=False):
        action=request['action']
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result=self._handle(request,actor,uid,operator)
            self.db.commit();return result
        except BaseException:
            self.db.rollback();raise

    def _handle(self,r,actor,uid,operator):
        action=r['action']
        if action=='list':
            rows=self.db.execute('SELECT id,owner,project,run,path,state,revision,estimate,inodes,expires FROM reservations ORDER BY expires DESC LIMIT 100').fetchall()
            return {'reservations':[dict(row) for row in rows],'limit':100,'expiry_is_release':False}
        if action=='inspect':
            fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY) if r['filesystem']=='/' else open_output(r['filesystem'])
            try: return self.capacity(fd)
            finally: os.close(fd)
        if action=='reserve':
            if r['policy']!=POLICY: raise ValueError('Unknown policy version')
            for key in ('project','run','idempotency_key'):
                if not isinstance(r[key],str) or not re.fullmatch('[a-zA-Z0-9._-]{1,100}',r[key]): raise ValueError('Invalid reservation identity')
            estimate=r['estimated_output_bytes'];inodes=r['estimated_inodes']
            if type(estimate)is not int or not 0<estimate<2**50 or type(inodes)is not int or not 0<inodes<100000000:
                raise ValueError('Positive bounded byte and inode estimates required')
            encoded=json.dumps(r,sort_keys=True)
            old=self.db.execute('SELECT * FROM reservations WHERE uid=? AND key=?',(uid,r['idempotency_key'])).fetchone()
            if old:
                if old['request']!=encoded: raise ValueError('Idempotency key content conflict')
                return dict(old)
            fd=open_output(r['output'])
            try:
                meta=os.fstat(fd)
                parts=Path(r['output']).relative_to(BASE).parts
                if parts[0]!=r['project']: raise ValueError('Output project mismatch')
                # Overlapping live output trees would double-credit consumed blocks.
                for row in self.db.execute("SELECT path FROM reservations WHERE state='ACTIVE'"):
                    prior=Path(row['path']);candidate=Path(r['output'])
                    if candidate==prior or candidate.is_relative_to(prior) or prior.is_relative_to(candidate):
                        raise ValueError('Output overlaps an outstanding reservation')
                cap=self.capacity(fd)
                if cap['effective_free']<=2*estimate+FLOOR_BYTES or cap['effective_inodes']<=2*inodes:
                    raise ValueError('Insufficient shared capacity; no reservation admitted')
                allocated,count=footprint(fd)
                row=dict(id=str(uuid.uuid4()),owner=actor,uid=uid,project=r['project'],run=r['run'],path=r['output'],
                    device=meta.st_dev,inode=meta.st_ino,estimate=estimate,inodes=inodes,baseline=allocated,
                    baseline_inodes=count,state='ACTIVE',revision=1,expires=time.time()+3600,
                    key=r['idempotency_key'],request=encoded)
                self.db.execute('INSERT INTO reservations VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
                self.event(row,actor,'RESERVED',{'policy':POLICY})
                return {k:v for k,v in row.items() if k!='request'}
            finally: os.close(fd)
        ident=str(uuid.UUID(r['reservation']))
        raw=self.db.execute('SELECT * FROM reservations WHERE id=?',(ident,)).fetchone()
        if not raw: raise ValueError('Unknown reservation')
        row=dict(raw)
        if row['uid']!=uid and not operator: raise PermissionError('Reservation belongs to another actor')
        if row['revision']!=r['expected_revision']: raise ValueError('Stale reservation revision')
        if row['state']!='ACTIVE': raise ValueError('Reservation already terminal')
        if action=='recover-stale':
            # No recorded supervisor identity exists in v1. Never infer death from TTL.
            raise ValueError('Expiry is not liveness proof; retain commitment until owner release or reviewed supervisor reconciliation')
        if action=='release':
            row.update(state='RELEASED',revision=row['revision']+1)
            self.db.execute('UPDATE reservations SET state=?,revision=? WHERE id=?',(row['state'],row['revision'],ident))
            self.event(row,actor,'RELEASED',{'owner_attests_finished':True})
            return {k:v for k,v in row.items() if k!='request'}
        if action not in ('renew','update'): raise ValueError('Unknown reservation action')
        fd=open_output(row['path'])
        try:
            meta=os.fstat(fd)
            if (meta.st_dev,meta.st_ino)!=(row['device'],row['inode']): raise ValueError('Output identity changed; retain reservation')
            if action=='update':
                if type(r['estimated_output_bytes'])is not int or r['estimated_output_bytes']<row['estimate']:
                    raise ValueError('Estimate updates may only increase the committed peak')
                row['estimate']=r['estimated_output_bytes']
                if 'estimated_inodes' in r:
                    value=r['estimated_inodes']
                    if type(value)is not int or not row['inodes']<=value<100000000:
                        raise ValueError('Inode estimate updates may only increase the committed peak within bounds')
                    row['inodes']=value
            allocated,inodes=footprint(fd);consumed=max(0,allocated-row['baseline'])
            cap=self.capacity(fd,exclude=ident)
            permitted=(cap['effective_free']>max(0,2*row['estimate']-consumed)+FLOOR_BYTES and
                cap['effective_inodes']>max(0,2*row['inodes']-max(0,inodes-row['baseline_inodes'])) and consumed<=row['estimate'])
            if not permitted:
                self.event(row,actor,'SAFE_BOUNDARY_STOP_REQUIRED',{'consumed':consumed})
                return {'id':ident,'revision':row['revision'],'state':'SAFE_BOUNDARY_STOP_REQUIRED','commitment_retained':True}
            row.update(revision=row['revision']+1,expires=time.time()+3600)
            self.db.execute('UPDATE reservations SET estimate=?,inodes=?,revision=?,expires=? WHERE id=?',
                            (row['estimate'],row['inodes'],row['revision'],row['expires'],ident))
            self.event(row,actor,action.upper(),{'consumed':consumed})
            return {k:v for k,v in row.items() if k!='request'}
        finally: os.close(fd)


def dispatch(b,r,actor,uid,operator):
    fields={'list':'area action','inspect':'area action filesystem','reserve':'area action project run output estimated_output_bytes estimated_inodes policy idempotency_key',
            'renew':'area action reservation expected_revision','update':'area action reservation expected_revision estimated_output_bytes',
            'release':'area action reservation expected_revision','recover-stale':'area action reservation expected_revision plan approval'}
    if r['action'] not in fields: raise ValueError('Unknown storage budget operation')
    required=fields[r['action']]
    if r['action']=='update' and 'estimated_inodes' in r: required+=' estimated_inodes'
    b.fields(r,required)
    root=b.ROOT/'private/storage-budget';root.mkdir(mode=0o700,exist_ok=True)
    path=root/'reservations.sqlite3'
    if path.is_symlink(): raise ValueError('Unsafe reservation database')
    db=Budget(path)
    try: return db.handle(r,actor,uid,operator)
    finally: db.close()
