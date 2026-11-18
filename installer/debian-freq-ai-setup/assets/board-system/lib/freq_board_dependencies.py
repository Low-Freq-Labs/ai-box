#!/usr/bin/env python3
"""Dependency operations core; invoked through a fixed-path caller entry."""
import argparse,fcntl,hashlib,json,os,re,stat,sys,tempfile,uuid
from pathlib import Path
import freq_board as board
import freq_board_transaction as tx
from freq_board_inspect import inspect
import freq_dependency_model as model
BEGIN='<!-- FREQ_DEPENDENCIES_V1_BEGIN -->'
END='<!-- FREQ_DEPENDENCIES_V1_END -->'
MAX_METADATA=8192
# Counts task paths plus retained transaction directories and before/after images.
# Independent task/link/report limits remain unchanged.
MAX_SCAN_ENTRIES=100000
MAX_SCAN_BYTES=256*1024*1024
MAX_REPORT_BYTES=65536
HEX=re.compile(r'^[a-f0-9]{64}$')
def encoded(value):
 return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).replace('<','\\u003c')
def decode_metadata(raw):
 if type(raw) is not str or len(raw.encode('utf-8'))>MAX_METADATA:raise ValueError('Metadata byte limit')
 depth=0;quoted=False;escaped=False
 for char in raw:
  if quoted:
   if escaped:escaped=False
   elif char=='\\':escaped=True
   elif char=='"':quoted=False
  elif char=='"':quoted=True
  elif char in '[{':
   depth+=1
   if depth>64:raise ValueError('Metadata nesting limit')
  elif char in ']}':depth-=1
 def pairs(items):
  value={}
  for key,item in items:
   if key in value:raise ValueError('Duplicate metadata key')
   value[key]=item
  return value
 def constant(value):raise ValueError('Non-finite metadata value')
 try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
 except RecursionError as error:raise ValueError('Metadata nesting limit') from error

def checked_metadata(meta):
 if type(meta)is not dict or set(meta)!={'schema','kind','links','review'} or type(meta['schema'])is not int or meta['schema']!=1:raise ValueError('Unknown metadata schema')
 if meta['kind'] not in ('task-dependency','mixed'):raise ValueError('Unknown blocker kind')
 links=meta['links']
 if type(links)is not list or len(links)>model.MAX_LINKS:raise ValueError('Invalid link bound')
 for link in links:
  if type(link)is not dict or set(link)!={'project','task_id','title','scope'}:raise ValueError('Invalid link fields')
  if any(type(v)is not str for v in link.values()):raise ValueError('Invalid link types')
  board.validate_project_id(link['project']);board.validate_task_name(link['title'])
  if not link['scope'].strip() or len(link['scope'])>160 or '\n' in link['scope']:raise ValueError('Invalid evidence scope')
 review=meta['review']
 if review is not None:
  if type(review)is not dict or set(review)!={'operation_id','fingerprint','disposition','reviewer'}:raise ValueError('Invalid review fields')
  uuid.UUID(review['operation_id'])
  if not HEX.fullmatch(review['fingerprint']) or review['disposition'] not in ('still-blocked','superseded') or not board.AGENT_RE.fullmatch(review['reviewer']):raise ValueError('Invalid review values')
 if len(encoded(meta).encode())>MAX_METADATA:raise ValueError('Metadata byte limit')
 return meta
def parse(content):
 if BEGIN not in content and END not in content:return None,content
 if content.count(BEGIN)!=1 or content.count(END)!=1:raise ValueError('Ambiguous metadata blocks')
 start=content.index(BEGIN);end=content.index(END,start)+len(END)
 raw=content[start+len(BEGIN):end-len(END)].strip()
 if len(raw.encode())>MAX_METADATA:raise ValueError('Metadata byte limit')
 meta=checked_metadata(decode_metadata(raw))
 return meta,content[:start]+content[end:]
def bounded_preflight(project):
 entries=total=0
 roots=[project/status for status in board.STATUSES]
 journal=tx.journal_root(project)
 if journal.exists():roots.append(journal)
 stack=[(root,0) for root in roots]
 while stack:
  directory,depth=stack.pop()
  with os.scandir(directory) as scan:
   for entry in scan:
    entries+=1
    if entries>MAX_SCAN_ENTRIES:raise ValueError('Analysis incomplete: entry bound exceeded')
    info=entry.stat(follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode):raise ValueError('Analysis incomplete: symlink')
    if stat.S_ISDIR(info.st_mode):
     if depth>=2:raise ValueError('Analysis incomplete: directory depth')
     stack.append((Path(entry.path),depth+1))
    elif stat.S_ISREG(info.st_mode):
     total+=info.st_size
     if total>MAX_SCAN_BYTES:raise ValueError('Analysis incomplete: byte scan bound exceeded')
    else:raise ValueError('Analysis incomplete: nonregular entry')
def output(value):
 raw=(json.dumps(value,ensure_ascii=False)+'\n').encode()
 if len(raw)>MAX_REPORT_BYTES:raise ValueError('Analysis incomplete: report bound exceeded')
 sys.stdout.buffer.write(raw)
def observe(project):
 bounded_preflight(project)
 report=inspect(project)
 if not report['complete']:raise ValueError('Incomplete board observation')
 tasks=report['tasks']
 if len(tasks)>model.MAX_TASKS:raise ValueError('Analysis task limit')
 for row in tasks:
  content=tx.regular(project/row['path']).decode()
  metadata,_=parse(content)
  row['metadata']=metadata
  if metadata:
   row['links']=metadata['links']
   if metadata['review']:row['review']=metadata['review']
 return tasks,model.validate(project.name,tasks)
def committed(project,tasks):
 records={}
 for row in tasks:
  if not row.get('review'):continue
  op=row['review']['operation_id'];folder=tx.journal_root(project)/op
  if not (folder/'committed.json').exists():continue
  folder,value=tx.record(project,op);receipt=json.loads(tx.regular(folder/'committed.json'))
  if receipt.get('state')!='COMMITTED' or receipt.get('operation_id')!=op or receipt.get('revision')!=value['new_revision']:raise ValueError('Mismatched committed disposition')
  records[op]={'state':'COMMITTED','task_id':value['task_id'],'new_revision':value['new_revision']}
 return records
def parse_options(args):
 parser=argparse.ArgumentParser(allow_abbrev=False)
 actions=parser.add_subparsers(dest='action',required=True)
 for action in ('list','set','review'):
  command=actions.add_parser(action,allow_abbrev=False)
  command.add_argument('project')
  if action!='list':
   command.add_argument('--title',required=True)
   command.add_argument('--expected-revision',required=True)
   command.add_argument('--operation-id')
  if action=='set':
   command.add_argument('--links',required=True)
   command.add_argument('--kind',choices=('task-dependency','mixed'),default='mixed')
  if action=='review':
   command.add_argument('--fingerprint',required=True)
   command.add_argument('--disposition',choices=('still-blocked','superseded'),default='still-blocked')
 options=parser.parse_args(args)
 if options.action!='list':
  board.validate_task_name(options.title)
  if not HEX.fullmatch(options.expected_revision):raise ValueError('Expected revision must be SHA256')
  if options.operation_id is not None:options.operation_id=str(uuid.UUID(options.operation_id))
 if options.action=='review' and not HEX.fullmatch(options.fingerprint):raise ValueError('Fingerprint must be SHA256')
 return options

def run(args):
 options=parse_options(args)
 project=board.validate_project(options.project)
 fd=os.open(project,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  fcntl.flock(fd,fcntl.LOCK_SH if options.action=='list' else fcntl.LOCK_EX)
  tasks,index=observe(project)
  if options.action=='list':
   receipts=committed(project,tasks)
   rows=[dict(task_id=row['task_id'],title=row['title'],revision=row['revision'],**model.candidate(project.name,row,index,receipts)) for row in tasks if row['status']=='blocked' and row.get('links')]
   output({'complete':True,'candidates':rows});return
  row=next((r for r in tasks if r['title']==options.title),None)
  if row is None:raise ValueError('Exact task not found')
  actor=board.current_agent()
  assigned=[actor] if (project/'active'/actor).is_dir() and not (project/'active'/actor).is_symlink() else []
  if not model.may_edit(row['status'],actor,row['owner'],assigned,options.expected_revision,row['revision']):raise ValueError('Authority or revision conflict')
  operation=options.operation_id if options.operation_id is not None else str(uuid.uuid4())
  if (tx.journal_root(project)/operation).exists():raise ValueError('Existing operation: inspect receipt; no automatic replay')
  if options.action=='set':
   if not options.links or len(options.links.encode())>MAX_METADATA:raise ValueError('Bounded links JSON required')
   metadata=checked_metadata(dict(schema=1,kind=options.kind,links=decode_metadata(options.links),review=None))
   row['links']=metadata['links']
   model.validate(project.name,tasks)
   if any(link['task_id'] not in index for link in row['links']):raise ValueError('New link target must currently exist')
  else:
   if row['status']!='blocked' or not row.get('metadata') or not row.get('links'):raise ValueError('Review requires linked blocked task')
   fingerprint=model.fingerprint(project.name,row,index)
   if fingerprint is None or fingerprint!=options.fingerprint:raise ValueError('Prerequisite fingerprint changed or unknown')
   metadata=row['metadata']
   metadata['review']={'operation_id':operation,'fingerprint':fingerprint,'disposition':options.disposition,'reviewer':actor}
   checked_metadata(metadata)
  content=tx.regular(project/row['path']).decode()
  _,body=parse(content)
  body=board.append_history(body,board.history_entry(actor,'DEPENDENCY_'+options.action.upper(),options.disposition if options.action=='review' else options.kind))
  content=body.rstrip()+'\n'+BEGIN+'\n'+encoded(metadata)+'\n'+END+'\n'
  tx.CONTEXT.clear();tx.CONTEXT.update(expected_revision=options.expected_revision,operation_id=operation)
  result=tx.transition(project,{'path':project/row['path'],'status':row['status'],'owner':row['owner']},row['status'],content,owner=row['owner'])
  output({'operation_id':result['operation_id'],'task_id':row['task_id'],'status':row['status'],'revision':tx.revision(project,result['path'])})
 finally:os.close(fd)
