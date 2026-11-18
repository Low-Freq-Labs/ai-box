"""Versioned, explicitly scoped grants. Legacy 'all' never includes these."""
from datetime import datetime,timezone
import hashlib
import json
import re
import time
import uuid

CAPABILITIES={'board-maintenance','coms-maintenance','tooling-maintenance','runtime-maintenance','storage-maintenance'}


def reference(value):
    if not isinstance(value,str) or not re.fullmatch('[a-zA-Z0-9._:/-]{1,160}',value):
        raise ValueError('A bounded approval/scope reference is required')
    return value


def audit(b,actor,action,details):
    root=b.ROOT/'private/maintenance-audit'
    root.mkdir(mode=0o700,exist_ok=True)
    ident=str(uuid.uuid4())
    value={'schema':1,'id':ident,'time':datetime.now(timezone.utc).isoformat(),
           'actor':actor,'action':action,**details}
    b.atomic(root/(ident+'.json'),json.dumps(value,sort_keys=True)+'\n')
    return ident


def grant(b,state,request,actor,names):
    action=request['action']
    if action=='show-scoped':
        b.fields(request,'area action agent')
        return json.dumps(state.get('maintenance_grants',{}).get(request['agent'],{}),indent=2)
    if action=='approve-plan':
        b.fields(request,'area action agent plan_sha256 approval')
        b.require(request['agent'] in names,'Unknown agent')
        b.require(re.fullmatch('[0-9a-f]{64}',request['plan_sha256']) is not None,'Invalid plan digest')
        ref=reference(request['approval'])
        approved={'actor':request['agent'],'plan_sha256':request['plan_sha256']}
        old=state.setdefault('maintenance_approvals',{}).get(ref)
        b.require(old is None or old==approved,'Approval reference is already bound to another plan')
        audit(b,actor,'APPROVE_PLAN',{'approval':ref,**approved})
        state['maintenance_approvals'][ref]=approved;b.save(state)
        return 'Exact plan approval recorded'
    b.require(action in ('grant-scoped','revoke-scoped'),'Unknown scoped grant operation')
    b.fields(request,'area action agent capability scope approval until' if action=='grant-scoped' else 'area action agent capability')
    b.require(request['agent'] in names and request['capability'] in CAPABILITIES,'Unknown agent or capability')
    entries=state.setdefault('maintenance_grants',{}).setdefault(request['agent'],{})
    before=entries.get(request['capability'])
    if action=='revoke-scoped':
        audit(b,actor,'REVOKE',{'agent':request['agent'],'capability':request['capability'],'before':before})
        entries.pop(request['capability'],None)
    else:
        scope=reference(request['scope']);approval=reference(request['approval'])
        expected={'board-maintenance':'project:', 'coms-maintenance':'coms:',
                  'tooling-maintenance':'component:', 'runtime-maintenance':'runtime:', 'storage-maintenance':'vm:'}[request['capability']]
        b.require(scope.startswith(expected) and len(scope)>len(expected),'Scope does not match capability')
        b.require(request['capability']!='storage-maintenance' or scope=='vm:206','Storage maintenance is VM206-only')
        expires=None
        if request['until']:
            expires=datetime.fromisoformat(request['until'].replace('Z','+00:00'))
            b.require(expires.tzinfo is not None and expires.timestamp()>time.time(),'Grant expiry must be a future timezone-aware time')
            expires=expires.timestamp()
        entry={'schema':1,'uid':b.pwd.getpwnam(request['agent']).pw_uid,'scope':scope,
               'approval':approval,'until':expires,'revision':(before or {}).get('revision',0)+1}
        audit(b,actor,'GRANT',{'agent':request['agent'],'capability':request['capability'],'before':before,'after':entry})
        entries[request['capability']]=entry
    b.save(state)
    return json.dumps(entries,indent=2)


def authorize(b,state,actor,uid,capability,scope,operator):
    if operator: return {'scope':scope,'approval':'authenticated-operator'}
    entry=state.get('maintenance_grants',{}).get(actor,{}).get(capability,{})
    b.require(entry.get('uid')==uid and entry.get('scope')==scope and
        (entry.get('until') is None or entry['until']>time.time()),'Scoped maintenance capability not granted or expired')
    return entry


def dispatch(b,state,r,actor,uid,operator):
    area=r['area']
    if area in ('coms-maintenance','coms-status'):
        import coms_maintenance
        return json.dumps(coms_maintenance.dispatch(b,r,actor,uid,operator,state),indent=2)
    if area=='storage-budget':
        # Every registered agent may reserve its own work; no elevated grant or
        # permission to release peer commitments is conferred.
        import storage_budget
        return json.dumps(storage_budget.dispatch(b,r,actor,uid,operator),indent=2)
    if area=='board-maintenance':
        import board_api
        return json.dumps(board_api.dispatch(b,state,r,actor,uid,operator),ensure_ascii=False,indent=2)
    raise ValueError('Maintenance area not implemented; no implied authority')
