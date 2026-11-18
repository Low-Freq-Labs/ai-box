"""Fixture prototype: best-effort bounded nonblocking record to an existing UNIX stream.
No disk writes, fsync, waits, retries, new socket connection or background collector.
Production journal routing/identity qualification is not established by this module.
"""
import ctypes,json,os,re,socket,stat,time
MAX_BYTES=1024
PREFIX=b'FREQ_PHASE_V1 '
PROFILES={'offline-python-v1','offline-browser-finite-v1','offline-browser-stream-v1'}
PHASES={'launch_requested','execution_observed','closing','preserving','recovery_closing','recovery_preserving'}
def valid(value):
 try:
  return (type(value)is dict and set(value)=={'schema','owner','run_id','input_sha256','profile','phase','epoch','observed_at'}
   and type(value['schema'])is int and value['schema']==1 and type(value['owner']) is str and re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', value['owner']) is not None
   and type(value['run_id'])is str and re.fullmatch('[a-z0-9][a-z0-9-]{0,47}',value['run_id'])is not None
   and type(value['input_sha256'])is str and re.fullmatch('[0-9a-f]{64}',value['input_sha256'])is not None
   and value['profile'] in PROFILES and value['phase'] in PHASES
   and type(value['epoch'])is str and re.fullmatch('[0-9a-f]{32}',value['epoch'])is not None
   and type(value['observed_at'])is int and value['observed_at']>0)
 except (KeyError,TypeError):return False
# Linux libc entry points avoid CPython socket-object timeout/flag policy.
# Prototypes checked against the installed sys/socket.h; socklen_t is unsigned int.
_LIBC=ctypes.CDLL(None,use_errno=True)
_SEND=_LIBC.send
_SEND.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int]
_SEND.restype=ctypes.c_ssize_t
_GETSOCKOPT=_LIBC.getsockopt
_GETSOCKOPT.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint)]
_GETSOCKOPT.restype=ctypes.c_int
def socket_option(fd,option):
 value=ctypes.c_int();length=ctypes.c_uint(ctypes.sizeof(value))
 if _GETSOCKOPT(fd,socket.SOL_SOCKET,option,ctypes.byref(value),ctypes.byref(length))!=0 or length.value!=ctypes.sizeof(value):return None
 return value.value
def emit(fd,binding,phase,epoch,observed_at=None):
 """One MSG_DONTWAIT send to a duplicate of already-provided socket; loss allowed.
 Return true means full local send only, never durable journal storage/receipt."""
 duplicate=None
 try:
  if type(binding)is not dict or set(binding)!={'owner','run_id','input_sha256','profile'}:return False
  value=dict(schema=1,**binding,phase=phase,epoch=epoch,observed_at=int(time.time()) if observed_at is None else observed_at)
  if not valid(value):return False
  payload=PREFIX+json.dumps(value,sort_keys=True,separators=(',',':')).encode()+b'\n'
  if len(payload)>MAX_BYTES:return False
  duplicate=os.dup(fd)
  if not stat.S_ISSOCK(os.fstat(duplicate).st_mode):return False
  if socket_option(duplicate,socket.SO_DOMAIN)!=socket.AF_UNIX or socket_option(duplicate,socket.SO_TYPE)!=socket.SOCK_STREAM:return False
  buffer=ctypes.create_string_buffer(payload)
  return _SEND(duplicate,buffer,len(payload),socket.MSG_DONTWAIT|socket.MSG_NOSIGNAL)==len(payload)
 except (OSError,ValueError,TypeError,KeyError):return False
 finally:
  if duplicate is not None:os.close(duplicate)
def decode(raw,binding):
 """Strict fixture frame classifier; caller authentication/journal origin external."""
 unknown={'classification':'unknown','current_phase':'unknown','closure_proven':False,'retry_allowed':False}
 try:
  if type(raw)is not bytes or len(raw)>MAX_BYTES or not raw.startswith(PREFIX) or not raw.endswith(b'\n'):return unknown
  value=json.loads(raw[len(PREFIX):])
  if not valid(value) or any(value[key]!=binding[key] for key in ('owner','run_id','input_sha256','profile')):return unknown
  return dict(classification='historical_phase_observation',last_observed_phase=value['phase'],epoch=value['epoch'],
   observed_at=value['observed_at'],current_phase='unknown',closure_proven=False,retry_allowed=False)
 except (ValueError,KeyError,TypeError):return unknown
