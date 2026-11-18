"""Narrow reason-only repair. Plans and before-images are operator protected."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.append('/usr/local/lib')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def dispatch(broker, request, actor, is_operator):
    import freq_board as board
    import freq_board_transaction as tx
    from freq_board_inspect import inspect
    action = request['action']
    state_root = broker.ROOT / 'private/board-maintenance'
    if action == 'validate':
        broker.fields(request, 'area action project')
        project = board.validate_project(request['project'])
        with board.locked(project, recover=False):
            return inspect(project)
    if action == 'operation-status':
        broker.fields(request, 'area action operation')
        operation = str(uuid.UUID(request['operation']))
        for project in (board.board_root()/'projects').iterdir():
            if project.is_symlink() or not project.is_dir() or project.name.startswith('.'):
                continue
            folder = tx.journal_root(project) / operation
            if folder.exists():
                with board.locked(project, recover=False):
                    _, value = tx.record(project, operation)
                    result = {k:value[k] for k in ('operation_id','task_id','source','target','actor','old_revision','new_revision')}
                    result['project'] = project.name
                    result['state'] = 'COMMITTED' if (folder/'committed.json').exists() else 'PREPARED'
                    result['notification'] = json.loads(tx.regular(folder/'notification.json')) if (folder/'notification.json').exists() else {'state':'PENDING' if value['notification'] else 'NONE'}
                    return result
        raise ValueError('Unknown operation')
    if action == 'plan':
        broker.fields(request, 'area action project task expected_revision intent incident')
        project = board.validate_project(request['project'])
        intent = request['intent']
        broker.require(isinstance(intent, dict), 'Owner-confirmed intent document required')
        for field in ('project','task','responsibility','reason','source_message','provenance'):
            broker.require(isinstance(intent.get(field),str) and intent[field], 'Missing owner-intent field: '+field)
        broker.require(intent['project']==project.name and intent['task']==request['task'], 'Intent task mismatch')
        board.validate_reason(intent['reason'])
        broker.require(intent.get('intended_state')=='blocked', 'Only blocked reason repair is supported')
        broker.require(isinstance(request['incident'],str) and re.fullmatch('[a-zA-Z0-9._-]{1,100}',request['incident']), 'Invalid incident')
        with board.locked(project, recover=False):
            location=board.locate(project,request['task'])
            broker.require(location['status']=='blocked', 'Reason repair cannot move or reassign a task')
            before=tx.regular(location['path'])
            content=before.decode('utf-8')
            broker.require('FREQ_BOARD_BLOCKED_BEGIN' not in content, 'Existing or damaged reason requires a different reviewed repair')
            owners=re.findall(r'^- (?:Assigned to|Transferred to): `([a-z][a-z0-9_-]*)`$',content,re.M)
            broker.require(bool(owners) and owners[-1]==intent['responsibility'], 'Recorded responsibility does not match owner intent')
            old_revision=tx.revision(project,location['path'])
            broker.require(old_revision==request['expected_revision'], 'Stale task revision; no plan created')
            after=board.set_blocked_reason(content,intent['reason'])
            # Deterministic plan content; no timestamp makes a second plan invent history.
            after=board.append_history(after, '- **REASON REPAIR** — owner-confirmed current wording; incident `'+request['incident']+'`; responsibility `'+owners[-1]+'`; no completion, acceptance or reassignment.')
            core={'schema':1,'project':project.name,'task':request['task'],
                  'path':str(location['path'].relative_to(project)), 'before_revision':old_revision,
                  'before_sha256':sha(before),'after_sha256':sha(after.encode()),
                  'responsibility':owners[-1],'intent_sha256':sha(canonical(intent)),
                  'intent':intent,'incident':request['incident'],'after':after,
                  'diff':''.join(difflib.unified_diff(content.splitlines(True),after.splitlines(True),fromfile='before',tofile='after')),
                  'planner':actor}
            digest=sha(canonical(core)); plan_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'freq-board-plan:'+digest))
            plan={'plan_id':plan_id,'sha256':digest,'plan':core}
            state_root.mkdir(mode=0o700,parents=True,exist_ok=True)
            target=state_root/(plan_id+'.json')
            if target.exists():
                broker.require(json.loads(broker.trusted(target))==plan,'Plan identity conflict')
            else:
                broker.atomic(target,json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
            return plan
    if action == 'apply':
        broker.fields(request,'area action plan expected_plan_sha256 approval')
        plan_id=str(uuid.UUID(request['plan']))
        saved=json.loads(broker.trusted(state_root/(plan_id+'.json')))
        core=saved['plan']
        broker.require(sha(canonical(core))==saved['sha256']==request['expected_plan_sha256'],'Plan digest mismatch')
        broker.require(bool(request['approval']) and isinstance(request['approval'],str),'Approval reference required')
        if not is_operator:
            approved=broker.load().get('maintenance_approvals',{}).get(request['approval'],{})
            broker.require(approved.get('plan_sha256')==saved['sha256'] and approved.get('actor')==actor,
                           'Operator-pinned exact repair approval required')
        project=board.validate_project(core['project'])
        with board.locked(project, recover=False):
            # Idempotent application uses the plan UUID as its transaction ID.
            existing=tx.journal_root(project)/plan_id
            if (existing/'prepared.json').exists():
                _,value=tx.record(project,plan_id)
                broker.require(value.get('audit',{}).get('plan_sha256')==saved['sha256'],'Repair operation identity conflict')
                tx.finish(project,existing,value)
                return {'operation_id':plan_id,'state':'COMMITTED','replayed':True}
            path=tx.checked_path(project,core['path'])
            broker.require(tx.revision(project,path)==core['before_revision'],'Stale task revision; no repair applied')
            # Root-protected before-image independent of the collaborative task journal.
            backup=state_root/(plan_id+'.before')
            if not backup.exists():
                tx.write_new(backup,tx.regular(path),0o600);tx.sync(state_root)
            broker.require(sha(tx.regular(backup))==core['before_sha256'],'Before-image mismatch')
            tx.CONTEXT.clear()
            tx.CONTEXT.update(operation_id=plan_id,expected_revision=core['before_revision'])
            try:
                result=tx.transition(project,board.task_location(project,path),'blocked',core['after'],
                    audit={'actor':actor,'approval':request['approval'],'plan_sha256':saved['sha256'],
                           'backup':str(backup),'responsibility':core['responsibility']})
            finally:
                tx.CONTEXT.clear()
            return {'operation_id':result['operation_id'],'state':'COMMITTED','backup':str(backup),
                    'responsibility':core['responsibility'],'changed_fields':['blocked_reason','repair_history']}
    raise ValueError('Unsupported board maintenance action')
