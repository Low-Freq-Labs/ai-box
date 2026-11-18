"""Isolated advisory model; not an installed board command or approved wire schema."""
import hashlib,json,uuid
MAX_TASKS=10000
MAX_LINKS=32
def identity(project,title):
 from freq_board import board_root
 from freq_task_identity import identity as stable_identity
 return stable_identity(board_root()/'projects'/project,title)
def validate(project,tasks):
 if len(tasks)>MAX_TASKS:raise ValueError('Analysis incomplete: task bound exceeded')
 indexed={}
 for t in tasks:
  key=t['task_id']
  if key!=identity(project,t['title']) or key in indexed:raise ValueError('Ambiguous or invalid task identity')
  indexed[key]=t
 for t in tasks:
  links=t.get('links',[])
  if len(links)>MAX_LINKS:raise ValueError('Link bound exceeded')
  seen=set()
  for link in links:
   key=link['task_id']
   if link['project']!=project:raise ValueError('Cross-project link unsupported')
   if key!=identity(project,link['title']):raise ValueError('Link identity mismatch')
   if key==t['task_id'] or key in seen:raise ValueError('Self or duplicate link')
   seen.add(key)
 # iterative graph walk, bounded by tasks/links, missing links stay unresolved
 color={}
 for key in indexed:
  stack=[(key,False)]
  while stack:
   node,exit=stack.pop()
   if node not in indexed:continue
   if exit:color[node]=2;continue
   if color.get(node)==1:raise ValueError('Cycle')
   if color.get(node)==2:continue
   color[node]=1;stack.append((node,True))
   for link in reversed(indexed[node].get('links',[])):stack.append((link['task_id'],False))
 return indexed
def fingerprint(project,task,indexed):
 values=[]
 for link in task.get('links',[]):
  other=indexed.get(link['task_id'])
  if other is None:return None
  if other['title']!=link['title'] or other.get('errors'):return None
  values.append({'id':other['task_id'],'title':other['title'],'revision':other['revision'],'status':other['status'],'scope':link['scope']})
 value={'project':project,'prerequisites':sorted(values,key=lambda x:x['id'])}
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def candidate(project,task,indexed,committed):
 if task['status']!='blocked' or not task.get('links'):return {'state':'not_candidate'}
 fp=fingerprint(project,task,indexed)
 if fp is None:return {'state':'unknown','needs_review':True}
 review=task.get('review')
 if review:
  operation=committed.get(review['operation_id'])
  if operation and operation['task_id']==task['task_id'] and operation['state']=='COMMITTED' and operation['new_revision']==task['revision'] and review['fingerprint']==fp:
   return {'state':'reviewed_unchanged','needs_review':False}
 return {'state':'needs_reassessment','needs_review':True,'fingerprint':fp}
def may_edit(status,actor,owner,assigned,expected,actual):
 if expected!=actual:return False
 return (status=='active' and actor==owner) or (status=='blocked' and actor in assigned)
