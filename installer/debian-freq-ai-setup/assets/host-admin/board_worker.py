"""Board maintenance under the authenticated agent UID, never root authority."""
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'board-system/lib'))
sys.path.append('/usr/local/lib')
import freq_board as board
import freq_board_transaction as tx
from freq_board_inspect import inspect

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def snapshot(project,operation):
    operation=str(uuid.UUID(operation));folder=tx.journal_root(project)/operation
    if folder.is_symlink() or not folder.is_dir():raise ValueError('Unknown or unsafe operation')
    files={}
    for index,p in enumerate(sorted(folder.iterdir())):
        if index>=100:raise ValueError('Journal inspection bound exceeded')
        if p.name=='aborted.json':continue
        files[p.name]=tx.digest(tx.regular(p))
    value={'operation_id':operation,'project':project.name,'files':files}
    if 'committed.json' in files:value['state']='COMMITTED'
    elif 'prepared.json' in files:
        _,record=tx.record(project,operation)
        value.update(state='PREPARED',source=record['source'],target=record['target'])
        value['task_hashes']={}
        for relative in (record['source'],record['target']):
            p=tx.checked_path(project,relative)
            value['task_hashes'][relative]=tx.digest(tx.regular(p)) if p.exists() else None
    else:value['state']='NOT_PREPARED'
    if (folder/'notification.json').exists():value['notification']=json.loads(tx.regular(folder/'notification.json'))
    value['revision']=digest(value)
    if (folder/'aborted.json').exists():
        closed=json.loads(tx.regular(folder/'aborted.json'))
        if value['state']!='NOT_PREPARED' or closed.get('snapshot_sha256')!=value['revision']:
            raise ValueError('Abort receipt conflicts with journal')
        value['state']='ABORTED_BEFORE_PREPARE'
    return value

def handle(r):
    project=board.validate_project(r['project'])
    with board.locked(project,recover=False):
        if r['action']=='validate':
            report=inspect(project);cursor=r.get('cursor',0);limit=r.get('limit',25)
            if type(cursor)is not int or cursor<0 or type(limit)is not int or not 1<=limit<=50:raise ValueError('Invalid page')
            rows=report['tasks'];page=rows[cursor:cursor+limit]
            # Reasons can be large; validation reports metadata and errors only.
            for row in page:row.pop('reason',None)
            report.update(tasks=page,total=len(rows),next_cursor=cursor+limit if cursor+limit<len(rows) else None,
                          error_count=len(report['errors']),pending_count=len(report['pending_operations']))
            report['errors']=report['errors'][:50];report['pending_operations']=report['pending_operations'][:50]
            return report
        value=snapshot(project,r['operation'])
        if r['action']=='operation-status':return value
        if r['action']=='plan':
            if value['state'] not in ('NOT_PREPARED','PREPARED'):raise ValueError('Operation needs no task recovery; inspect notification separately')
            return {'schema':1,'project':project.name,'operation':value['operation_id'],
                    'expected_revision':value['revision'],'action':'CLOSE_UNPREPARED' if value['state']=='NOT_PREPARED' else 'FINISH_PREPARED',
                    'snapshot':value,'effect':'Preserve all evidence; no notification resend, acceptance or new task transition'}
        if r['action']=='apply':
            core=r['plan']
            folder=tx.journal_root(project)/value['operation_id']
            if core['action']=='CLOSE_UNPREPARED' and value['state']=='ABORTED_BEFORE_PREPARE':
                return {'state':value['state'],'operation_id':value['operation_id'],'replayed':True}
            if core['action']=='FINISH_PREPARED' and value['state']=='COMMITTED':
                return {'state':'COMMITTED','operation_id':value['operation_id'],'replayed':True}
            if value['revision']!=core['expected_revision']:raise ValueError('Stale operation revision; no recovery applied')
            if core['action']=='CLOSE_UNPREPARED' and value['state']=='NOT_PREPARED':
                tx.atomic(folder/'aborted.json',json.dumps({'schema':1,'state':'ABORTED_BEFORE_PREPARE',
                    'operation_id':value['operation_id'],'snapshot_sha256':value['revision'],
                    'actor':board.current_agent(),'approval':r['approval']},sort_keys=True).encode())
                return {'state':'ABORTED_BEFORE_PREPARE','operation_id':value['operation_id'],'originals_preserved':True}
            if core['action']=='FINISH_PREPARED' and value['state']=='PREPARED':
                _,record=tx.record(project,value['operation_id']);tx.finish(project,folder,record)
                return {'state':'COMMITTED','operation_id':value['operation_id'],'notification':'NOT_REPLAYED'}
            raise ValueError('Unsupported reconciliation state')
        raise ValueError('Unsupported board action')

if __name__=='__main__':
    try:print(json.dumps({'ok':True,'result':handle(json.loads(sys.stdin.buffer.read(65537)))},ensure_ascii=False))
    except Exception as error:print(json.dumps({'ok':False,'error':str(error)[:400]}));sys.exit(1)
