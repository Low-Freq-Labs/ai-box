"""Pure bounded journal-frame reader fixture. Does not run journalctl or authenticate SSH.
Caller must supply a successfully bounded reverse-order journal read with genuine
journal-origin metadata. Fixture inputs alone do not establish those conditions.
"""
import json,re,uuid
import phase_event_fixture as event
MAX_BYTES=65536
MAX_ROWS=64
RECOVERY_UNIT='freq-remote-tests-recover.service'
UNKNOWN=dict(classification='unknown',current_phase='unknown',closure_proven=False,retry_allowed=False)
def unique(pairs):
 value={}
 for key,item in pairs:
  if key in value:raise ValueError('Duplicate JSON key')
  value[key]=item
 return value
def binding(request):
 if type(request)is not dict or set(request)!={'nonce','owner','run_id','input_sha256','profile'}:raise ValueError('Invalid request')
 if str(uuid.UUID(request['nonce']))!=request['nonce']:raise ValueError('Invalid nonce')
 b={k:request[k] for k in ('owner','run_id','input_sha256','profile')}
 if not event.valid(dict(schema=1,**b,phase='closing',epoch='0'*32,observed_at=1)):raise ValueError('Invalid binding')
 return b
def command(request):
 b=binding(request)
 return ['journalctl','--no-pager','--reverse','--output=json','--lines=65',
  '--output-fields=MESSAGE,_UID,_SYSTEMD_UNIT,_SYSTEMD_INVOCATION_ID,_BOOT_ID,__MONOTONIC_TIMESTAMP',
  '--case-sensitive=yes',
  '--grep=^FREQ_PHASE_V1 .*"owner":"'+b['owner']+'".*"run_id":"'+b['run_id']+'"',
  '_SYSTEMD_UNIT=freq-test-controller-'+b['owner']+'-'+b['run_id']+'.service',
  '+','_SYSTEMD_UNIT='+RECOVERY_UNIT]
def observe(raw,request,authenticated_owner,stored_state,read_succeeded=True):
 try:
  b=binding(request)
  if authenticated_owner!=b['owner'] or read_succeeded is not True:return dict(UNKNOWN)
  if type(stored_state)is not dict or any(stored_state.get(k)!=v for k,v in b.items()):return dict(UNKNOWN)
  if type(raw)is not bytes or len(raw)>MAX_BYTES:return dict(UNKNOWN)
  lines=raw.splitlines()
  if len(lines)>MAX_ROWS:return dict(UNKNOWN)
  rows=[json.loads(line,object_pairs_hook=unique) for line in lines]
  if any(type(row)is not dict for row in rows):return dict(UNKNOWN)
  allowed={'freq-test-controller-'+b['owner']+'-'+b['run_id']+'.service',RECOVERY_UNIT}
  for row in rows:
   if type(row)is not dict:return dict(UNKNOWN)
   if row.get('_UID')!='0' or type(row.get('_SYSTEMD_UNIT'))is not str or row['_SYSTEMD_UNIT'] not in allowed:continue
   if any(type(row.get(k))is not str or re.fullmatch('[a-f0-9]{32}',row[k])is None for k in ('_SYSTEMD_INVOCATION_ID','_BOOT_ID')):return dict(UNKNOWN)
   tick=row.get('__MONOTONIC_TIMESTAMP')
   if type(tick)is not str or not tick.isascii() or not tick.isdigit():return dict(UNKNOWN)
   message=row.get('MESSAGE')
   if type(message)is not str:return dict(UNKNOWN)
   if not message.startswith(event.PREFIX.decode()):continue
   frame=message.encode()
   if not frame.endswith(b'\n'):frame+=b'\n'
   if len(frame)>event.MAX_BYTES:return dict(UNKNOWN)
   value=json.loads(frame[len(event.PREFIX):],object_pairs_hook=unique)
   if not event.valid(value):return dict(UNKNOWN)
   if any(value[k]!=v for k,v in b.items()):continue
   return dict(classification='historical_phase_observation',last_observed_phase=value['phase'],observed_at=value['observed_at'],
    epoch=value['epoch'],producer_invocation=row['_SYSTEMD_INVOCATION_ID'],producer_boot=row['_BOOT_ID'],
    current_phase='unknown',closure_proven=False,retry_allowed=False)
 except (ValueError,TypeError,KeyError,AttributeError,RecursionError):return dict(UNKNOWN)
 return dict(UNKNOWN)
