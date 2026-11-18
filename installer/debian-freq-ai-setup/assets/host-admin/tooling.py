"""Deploy operator-published reviewed board/comms releases; broker excluded."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import uuid

BOARD_BIN=('task-block','task-ready','task-done','task-transfer','task-status','project-status')
BOARD_LIB=('freq_board.py','freq_board_alert.py','freq_board_transaction.py','freq_board_inspect.py')
TARGETS={'board':{prefix+kind+name for prefix in ('/usr/local/','/opt/freq-agents/board-system/') for kind,names in (('bin/',BOARD_BIN),('lib/',BOARD_LIB)) for name in names},
         'coms':{prefix+part for prefix in ('/usr/local/','/opt/freq-agents/coms-system/') for part in ('bin/dev-msg','bin/dev-msg-status','lib/freq_coms_receipts.py')}}
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def sha(v):return hashlib.sha256(v).hexdigest()
def image(path):
    path=Path(path)
    if path.parent.resolve()!=path.parent or path.is_symlink():raise ValueError('Unsafe tooling path')
    parent=path.parent.stat()
    if parent.st_uid or parent.st_mode&0o022:raise ValueError('Tooling parent is not operator controlled')
    if not path.exists():return None
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        m=os.fstat(fd)
        if not stat.S_ISREG(m.st_mode) or m.st_uid or m.st_mode&0o022 or m.st_nlink!=1:raise ValueError('Unsafe code metadata')
        with os.fdopen(os.dup(fd),'rb') as f:raw=f.read(262145)
        if len(raw)>262144:raise ValueError('Tool exceeds size bound')
        return {'body':base64.b64encode(raw).decode(),'sha256':sha(raw),'uid':m.st_uid,'gid':m.st_gid,'mode':stat.S_IMODE(m.st_mode),
                'xattrs':{k:base64.b64encode(os.getxattr(fd,k)).decode() for k in os.listxattr(fd)}}
    finally:os.close(fd)
def revision(images):return sha(canonical(images))
def check_code(target,raw):
    if target.endswith('/dev-msg'):
        if subprocess.run(['/bin/bash','-n'],input=raw,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5).returncode:raise ValueError('Shell syntax validation failed')
    else:compile(raw,target,'exec')
def replace(target,value):
    path=Path(target)
    image(path) # Validate root-controlled parent and current inode before replacement.
    temporary=path.with_name('.tooling-'+uuid.uuid4().hex)
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(base64.b64decode(value['body'],validate=True));stream.flush()
            os.fchown(stream.fileno(),value['uid'],value['gid'])
            for k in os.listxattr(stream.fileno()):
                if k not in value['xattrs']:os.removexattr(stream.fileno(),k)
            for k,v in value['xattrs'].items():os.setxattr(stream.fileno(),k,base64.b64decode(v,validate=True))
            os.fchmod(stream.fileno(),value['mode']);os.fsync(stream.fileno())
        os.replace(temporary,path)
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        if temporary.exists():temporary.unlink()

def dispatch(b,state,r,actor,uid,operator):
    from maintenance import authorize,audit
    grant=authorize(b,state,actor,uid,'tooling-maintenance','component:board-coms',operator)
    root=b.ROOT/'private/tooling';root.mkdir(mode=0o700,exist_ok=True)
    action=r['verb']
    if action in ('status','verify'):
        b.fields(r,'area action verb')
        releases=[];published=[]
        for p in sorted(root.glob('release-*.json'))[:100]:
            v=json.loads(b.trusted(p));published.append((p.stem[8:],v));releases.append({'release':p.stem[8:],'component':v['component'],'review':v['review'],'sha256':sha(canonical(v))})
        components={}
        for name,paths in TARGETS.items():
            current={p:image(p) for p in sorted(paths)};rev=revision(current)
            matches=[label for label,v in published if v['component']==name and revision(v['files'])==rev]
            components[name]={'revision':rev,'files':len(paths),'matches_reviewed_releases':matches,'verified':bool(matches)}
        return {'schema':1,'scope':grant['scope'],'releases':releases,'components':components,
                'broker_updates':'Operator-only separate review; never delegated by this scope'}
    if action=='plan':
        b.fields(r,'area action verb release')
        import re
        if not re.fullmatch('[a-zA-Z0-9._-]{1,80}',r['release']):raise ValueError('Invalid release identity')
        release=json.loads(b.trusted(root/('release-'+r['release']+'.json')))
        component=release['component']
        b.require(component in TARGETS and set(release['files'])==TARGETS[component],'Release target set is not allowed; broker changes forbidden')
        b.require(release.get('schema')==1 and release.get('compatible_schema')==1 and release.get('review') and actor in release.get('approved_for',[]),'Release is not operator reviewed for this actor/schema')
        before={p:image(p) for p in sorted(TARGETS[component])}
        for target,value in release['files'].items():
            raw=base64.b64decode(value['body'],validate=True)
            b.require(sha(raw)==value['sha256'] and value['uid']==0 and not value['mode']&0o022,'Invalid reviewed image')
            check_code(target,raw)
        core={'component':component,'release':r['release'],'release_sha256':sha(canonical(release)),'before':before,'before_revision':revision(before),'actor':actor,'uid':uid}
        digest=sha(canonical(core));ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'tooling-plan:'+digest))
        b.atomic(root/('plan-'+ident+'.json'),json.dumps(core))
        return {'plan':ident,'sha256':digest,'component':component,'review':release['review'],
                'diff':[{'path':p,'before':(before[p] or {}).get('sha256'),'after':release['files'][p]['sha256']} for p in sorted(before)]}
    if action=='job-status':
        b.fields(r,'area action verb job');ident=str(uuid.UUID(r['job']))
        v=json.loads(b.trusted(root/('job-'+ident+'.json')))
        return {k:v[k] for k in ('job','state','actor','component','approval','before_revision','after_revision') if k in v}
    if action not in ('apply','rollback'):raise ValueError('Unsupported tooling operation')
    b.fields(r,'area action verb plan expected_plan_sha256 approval' if action=='apply' else 'area action verb job approval')
    b.require(operator or r['approval']==grant['approval'],'Scoped approval reference required')
    ident=str(uuid.UUID(r['plan'] if action=='apply' else r['job']));jobpath=root/('job-'+ident+'.json')
    if action=='apply':
        core=json.loads(b.trusted(root/('plan-'+ident+'.json')))
        b.require(sha(canonical(core))==r['expected_plan_sha256'] and core['actor']==actor and core['uid']==uid,'Stale or foreign plan')
        release=json.loads(b.trusted(root/('release-'+core['release']+'.json')))
        b.require(sha(canonical(release))==core['release_sha256'],'Reviewed release changed')
        component=core['component'];before=core['before'];after=release['files']
        if jobpath.exists():
            old=json.loads(b.trusted(jobpath));return {k:old[k] for k in ('job','state','component')}
        b.require(revision({p:image(p) for p in sorted(before)})==core['before_revision'],'Installed code drift; replan')
        job={'job':ident,'actor':actor,'component':component,'approval':r['approval'],'before':before,'after':after,
             'before_revision':revision(before),'after_revision':revision(after),'state':'PREPARED'}
    else:
        job=json.loads(b.trusted(jobpath));component=job['component'];before=job['after'];after=job['before']
        b.require(job['state']=='COMMITTED','Only a committed job can be rolled back')
        b.require(all(v is not None for v in after.values()),'Rollback would remove new files; operator review required')
        b.require(revision({p:image(p) for p in sorted(before)})==job['after_revision'],'Code changed after job; rollback refused')
        job['state']='ROLLBACK_PREPARED'
    b.require(set(before)==set(after)==TARGETS[component],'Invalid job target scope')
    audit(b,actor,'TOOLING_'+action.upper(),{'scope':grant['scope'],'approval':r['approval'],'job':ident,'state':'ADMITTED'})
    b.atomic(jobpath,json.dumps(job))
    changed=[]
    try:
        for path in sorted(after,key=lambda p:('/bin/' in p,p)):
            b.require(image(path)==before[path],'Code drift during apply')
            changed.append(path);replace(path,after[path])
        b.require(all(image(p)==after[p] for p in after),'Post-install hash or metadata verification failed')
        for p in after:check_code(p,base64.b64decode(after[p]['body']))
        job['state']='COMMITTED' if action=='apply' else 'ROLLED_BACK'
    except Exception:
        for p in reversed(changed):
            if before[p] is not None and image(p) in (after[p],before[p]):replace(p,before[p])
        job['state']='FAILED_RESTORED' if all(image(p)==before[p] for p in before) else 'RECOVERY_REQUIRED'
        b.atomic(jobpath,json.dumps(job));raise
    b.atomic(jobpath,json.dumps(job))
    audit(b,actor,'TOOLING_RESULT',{'job':ident,'state':job['state'],'before_revision':job['before_revision'],'after_revision':job['after_revision']})
    return {'job':ident,'state':job['state'],'component':component}
