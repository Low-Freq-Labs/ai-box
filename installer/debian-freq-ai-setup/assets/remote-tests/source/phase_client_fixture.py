"""Pure phase response boundary; no SSH or transport implementation."""
import json,re
import phase_reader_fixture as reader
import phase_event_fixture as event
MAX_RESPONSE=4096
BASE={'schema','operation','nonce','owner','run_id','input_sha256','profile','classification','current_phase','closure_proven','retry_allowed'}
EXTRA={'last_observed_phase','observed_at','epoch','producer_invocation','producer_boot'}
def parse(raw,request):
 try:
  binding=reader.binding(request)
  if type(raw)is not bytes or len(raw)>MAX_RESPONSE:return dict(reader.UNKNOWN)
  v=json.loads(raw,object_pairs_hook=reader.unique)
  if type(v)is not dict:return dict(reader.UNKNOWN)
  if type(v.get('schema'))is not int or v['schema']!=1 or v.get('operation')!='phase-observation-v1':return dict(reader.UNKNOWN)
  if v.get('nonce')!=request['nonce'] or any(v.get(k)!=value for k,value in binding.items()):return dict(reader.UNKNOWN)
  if v.get('current_phase')!='unknown' or v.get('closure_proven') is not False or v.get('retry_allowed') is not False:return dict(reader.UNKNOWN)
  if v.get('classification')=='unknown' and set(v)==BASE:return dict(reader.UNKNOWN)
  if v.get('classification')!='historical_phase_observation' or set(v)!=BASE|EXTRA:return dict(reader.UNKNOWN)
  if not event.valid(dict(schema=1,**binding,phase=v['last_observed_phase'],epoch=v['epoch'],observed_at=v['observed_at'])):return dict(reader.UNKNOWN)
  if any(type(v[k])is not str or re.fullmatch('[a-f0-9]{32}',v[k])is None for k in ('producer_invocation','producer_boot')):return dict(reader.UNKNOWN)
  return {k:v[k] for k in set(reader.UNKNOWN)|EXTRA}
 except (ValueError,TypeError,KeyError,AttributeError,RecursionError):return dict(reader.UNKNOWN)
def request_phase(exchange,request):
 b=reader.binding(request)
 args=['phase-observation-v1',b['run_id'],b['input_sha256'],b['profile'],request['nonce']]
 # One read-only exchange; unsupported/lost response never retries/falls back.
 code,stdout,stderr,uncertain=exchange(b['owner'],args)
 if type(code)is not int or code!=0 or uncertain is not False:return dict(reader.UNKNOWN)
 return parse(stdout,request)
