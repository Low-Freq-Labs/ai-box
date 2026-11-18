"""Isolated proposed-envelope validator. No SSH, submission, cleanup or fallback."""
import json
MAX_BYTES=4096
BINDING=('nonce','owner','run_id','input_sha256','profile')
CODES={'retention_limit','busy','profile_disabled','capacity_limit','identity_conflict'}
def decode_wire(raw):
 if type(raw)is not bytes or len(raw)>MAX_BYTES:raise ValueError('Response byte bound')
 text=raw.decode('utf-8');depth=0;quoted=False;escaped=False
 for char in text:
  if quoted:
   if escaped:escaped=False
   elif char=='\\':escaped=True
   elif char=='"':quoted=False
  elif char=='"':quoted=True
  elif char in '[{':
   depth+=1
   if depth>32:raise ValueError('Response nesting bound')
  elif char in ']}':depth-=1
 def pairs(items):
  value={}
  for key,item in items:
   if key in value:raise ValueError('Duplicate response key')
   value[key]=item
  return value
 def constant(value):raise ValueError('Non-finite response constant')
 try:return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)
 except RecursionError as error:raise ValueError('Response nesting bound') from error

def classify(raw,request,authenticated=True,exit_code=0):
 uncertain={'classification':'uncertain','retry_allowed':False}
 if not authenticated or exit_code!=0 or not isinstance(raw,bytes) or len(raw)>MAX_BYTES:return uncertain
 try:
  value=decode_wire(raw)
  if set(value)!={'schema','request','observation'} or type(value['schema'])is not int or value['schema']!=1:return uncertain
  binding=value['request']
  if type(binding)is not dict or set(binding)!=set(BINDING):return uncertain
  if any(type(binding[k])is not str or binding[k]!=request[k] for k in BINDING):return uncertain
  o=value['observation']
  if type(o)is not dict or type(o.get('observed_at'))is not int or o['observed_at']<=0:return uncertain
  if o.get('kind')=='refused' and set(o)=={'kind','observed_at','code','boundary'} and o['code'] in CODES and o['boundary']=='before_admission':
   return {'classification':'definite_refusal','code':o['code'],'observed_at':o['observed_at'],'retry_allowed':False}
  if o.get('kind')=='state' and set(o)=={'kind','observed_at','lifecycle'} and o['lifecycle'] in {'uploading','accepted','preparing','running','closed','cleaned','reconciliation-required'}:
   return {'classification':'state_observation','lifecycle':o['lifecycle'],'observed_at':o['observed_at'],'closure_proven':False,'retry_allowed':False}
  if o.get('kind')=='absent' and set(o)=={'kind','observed_at','boundary'} and o['boundary']=='admission_lock':
   return {'classification':'absent_at_observation','observed_at':o['observed_at'],'retry_allowed':False}
 except (ValueError,TypeError,KeyError):pass
 return uncertain
