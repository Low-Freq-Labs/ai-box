"""Root audit/plan storage; collaborative paths are handled after privilege drop."""
import grp
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import tempfile
import uuid

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()

def worker(b,request,uid):
    # Root operator inspection uses an unprivileged shared-board group identity.
    if uid==0:uid=b.pwd.getpwnam('nobody').pw_uid
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE,(60000,60000))
        resource.setrlimit(resource.RLIMIT_CPU,(8,8))
    with tempfile.TemporaryFile() as output:
        process=subprocess.Popen(['/usr/bin/python3','-I','-B',str(Path(__file__).with_name('board_worker.py'))],
            stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,env=b.ENV,
            user=uid,group=grp.getgrnam('freq-agents').gr_gid,extra_groups=[],start_new_session=True,preexec_fn=limits)
        try:process.communicate(canonical(request),timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait();raise ValueError('Board worker timed out; inspect operation status before retry')
        output.seek(0);raw=output.read(60001)
    if len(raw)>60000:raise ValueError('Board response exceeds bound; request a smaller page')
    try:value=json.loads(raw)
    except ValueError:raise ValueError('Board worker failed without a complete receipt') from None
    if process.returncode or not value.get('ok'):raise ValueError(value.get('error','Board worker failed'))
    return value['result']

def dispatch(b,state,r,actor,uid,operator):
    from maintenance import authorize,audit
    grant=authorize(b,state,actor,uid,'board-maintenance','project:shared',operator)
    action=r['action'];root=b.ROOT/'private/board-reconciliation'
    if action in ('validate','operation-status','plan'):
        b.fields(r,{'validate':'area action project cursor limit','operation-status':'area action project operation','plan':'area action project operation'}[action])
        result=worker(b,r,uid)
        if action!='plan':return result
        core=result;digest=hashlib.sha256(canonical(core)).hexdigest();ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'board-reconcile:'+digest))
        saved={'plan_id':ident,'sha256':digest,'plan':core,'actor':actor,'uid':uid}
        root.mkdir(mode=0o700,exist_ok=True)
        path=root/(ident+'.json')
        if path.exists():
            old=json.loads(b.trusted(path))
            b.require(old==saved,'Plan already belongs to another actor')
        else:b.atomic(path,json.dumps(saved)+'\n')
        audit(b,actor,'BOARD_PLAN',{'scope':grant['scope'],'approval':grant['approval'],'plan_sha256':digest})
        return saved
    if action=='apply':
        b.fields(r,'area action plan expected_plan_sha256 approval')
        ident=str(uuid.UUID(r['plan']));saved=json.loads(b.trusted(root/(ident+'.json')))
        b.require(saved['sha256']==r['expected_plan_sha256']==hashlib.sha256(canonical(saved['plan'])).hexdigest(),'Plan digest mismatch')
        b.require(operator or saved['actor']==actor and saved['uid']==uid,'Plan belongs to another actor')
        b.require(r['approval']==grant['approval'] or operator and bool(r['approval']),'Scoped approval reference required')
        core=saved['plan'];event=audit(b,actor,'BOARD_RECOVERY',{'scope':grant['scope'],'approval':r['approval'],'plan_sha256':saved['sha256'],'state':'ADMITTED'})
        try:result=worker(b,{'action':'apply','project':core['project'],'operation':core['operation'],'plan':core,'approval':r['approval']},uid)
        except Exception:
            audit(b,actor,'BOARD_RECOVERY_RESULT',{'operation':event,'state':'FAILED_OR_UNCERTAIN'});raise
        audit(b,actor,'BOARD_RECOVERY_RESULT',{'operation':event,**result})
        return result
    raise ValueError('Unsupported board maintenance action')
