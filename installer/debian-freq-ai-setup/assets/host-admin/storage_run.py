#!/usr/bin/python3 -I
"""Opt-in case-boundary reservation supervisor. Executes only as the invoking UID."""
import argparse,ctypes,hashlib,json,os,pathlib,signal,stat,struct,subprocess,time
SLOT=131072
HEADER=48
BUDGET='/usr/local/bin/storage-budget'

class Journal:
 def __init__(self,path,create=False):
  self.path=pathlib.Path(path).absolute()
  self.parentfd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
  self.fd=os.open(path,os.O_NOFOLLOW|(os.O_RDWR|os.O_CREAT|os.O_EXCL if create else os.O_RDONLY),0o600)
  s=os.fstat(self.fd)
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_nlink!=1:raise ValueError('unsafe receipt')
  if create:os.posix_fallocate(self.fd,0,2*SLOT);os.fsync(self.fd)
  if os.fstat(self.fd).st_size!=2*SLOT:raise ValueError('receipt size mismatch')
  self.generation=0
 def validate_path(self):
  s=os.fstat(self.fd);named=self.path.lstat();parent=self.path.parent.stat();opened=os.fstat(self.parentfd)
  if not stat.S_ISREG(named.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_size!=2*SLOT or (s.st_dev,s.st_ino)!=(named.st_dev,named.st_ino) or (parent.st_dev,parent.st_ino)!=(opened.st_dev,opened.st_ino):raise RuntimeError('durable receipt path lost or replaced; reservation retained')
 def write(self,value):
  self.validate_path()
  b=json.dumps(value,separators=(',',':'),sort_keys=True).encode()
  if len(b)>SLOT-HEADER:raise ValueError('bounded receipt overflow')
  self.generation+=1
  prefix=struct.pack('>QQ',self.generation,len(b))
  header=prefix+hashlib.sha256(prefix+b).digest()
  data=header+b+b'\0'*(SLOT-HEADER-len(b));offset=(self.generation%2)*SLOT
  while data:
   n=os.pwrite(self.fd,data,offset)
   if n<=0:raise OSError('short receipt write')
   data=data[n:];offset+=n
  os.fsync(self.fd);self.validate_path();os.fsync(self.parentfd)
 def read(self):
  self.validate_path()
  valid=[]
  for offset in [0,SLOT]:
   data=os.pread(self.fd,SLOT,offset)
   if len(data)!=SLOT:continue
   generation,n=struct.unpack('>QQ',data[:16]);b=data[HEADER:HEADER+n]
   if generation and n<=SLOT-HEADER and hashlib.sha256(data[:16]+b).digest()==data[16:HEADER]:
    valid.append((generation,json.loads(b)))
  if not valid:raise ValueError('no committed receipt slot')
  return max(valid,key=lambda x:x[0])[1]
 def close(self):os.close(self.fd);os.close(self.parentfd)

def budget(*args):
 p=subprocess.run([BUDGET,*map(str,args)],capture_output=True,text=True,timeout=30)
 if len(p.stdout)>65536 or len(p.stderr)>65536:raise RuntimeError('budget response overflow')
 if p.returncode:return None,{'exit':p.returncode,'boundary':'reservation checkpoint refused'}
 return json.loads(p.stdout),None

def children():
 return [int(x) for x in pathlib.Path('/proc/self/task/'+str(os.getpid())+'/children').read_text().split()]

def close_children():
 # Subreaper adopts descendants when their direct parent exits, even after setsid.
 deadline=time.monotonic()+10
 while time.monotonic()<deadline:
  ids=children()
  if not ids:return True
  for pid in ids:
   try:
    fd=os.pidfd_open(pid)
    try:signal.pidfd_send_signal(fd,signal.SIGKILL)
    finally:os.close(fd)
   except ProcessLookupError:pass
   try:os.waitpid(pid,os.WNOHANG)
   except ChildProcessError:pass
  time.sleep(.02)
 return not children()

def validate(plan):
 if not isinstance(plan,dict) or set(plan)!={'cases'} or not 0<len(plan['cases'])<=1000:raise ValueError('plan must contain1..1000 cases')
 ids=set()
 for c in plan['cases']:
  if set(c)!={'id','argv','timeout'}:raise ValueError('case schema')
  if not isinstance(c['id'],str) or not c['id'] or len(c['id'])>64 or c['id'] in ids:raise ValueError('case identity')
  ids.add(c['id'])
  if not isinstance(c['argv'],list) or not c['argv'] or len(c['argv'])>100 or any(not isinstance(x,str) or '\0' in x or len(x)>4096 for x in c['argv']):raise ValueError('argv bounds')
  if type(c['timeout'])is not int or not 1<=c['timeout']<=3600:raise ValueError('timeout bounds')

def run(args):
 with pathlib.Path(args.plan).open('rb') as f:raw=f.read(1024*1024+1)
 if len(raw)>1024*1024:raise ValueError('plan size')
 plan=json.loads(raw);validate(plan)
 if ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)!=0:raise OSError('subreaper unavailable')
 if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):raise RuntimeError('pidfd support required')
 output=pathlib.Path(args.output)
 row,error=budget('reserve','--project',args.project,'--run',args.run,'--output',output,'--estimated-output-bytes',args.bytes,'--estimated-inodes',args.inodes,'--policy','shared-output-v1','--idempotency-key',args.run)
 if error:raise RuntimeError(error)
 meta=output.stat()
 if meta.st_dev!=row['device'] or meta.st_ino!=row['inode'] or row['state']!='ACTIVE':raise RuntimeError('reservation identity')
 receipt=output/('storage-run-'+args.run+'.receipt')
 j=Journal(receipt,create=True)
 parent=os.open(output,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);os.fsync(parent)
 result={'schema':1,'run':args.run,'plan_sha256':hashlib.sha256(raw).hexdigest(),'reservation':row['id'],'revision':row['revision'],'supervisor_pid':os.getpid(),'supervisor_start':pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19],'state':'ADMITTED','completed':[],'failed':None,'running':None,'unrun':[c['id'] for c in plan['cases']],'writers_closed':False,'reservation_released':False}
 deadline=time.monotonic()+args.deadline
 def interrupted(signum,frame):raise InterruptedError('supervisor interrupted')
 signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
 try:
  j.write(result)
  for case in plan['cases']:
   if time.monotonic()>=deadline:result['state']='DEADLINE';break
   row,error=budget('renew',row['id'],'--expected-revision',row['revision'])
   if error:result['state']='SAFE_BOUNDARY_STOP';result['checkpoint_error']=error;break
   result['revision']=row['revision'];result['state']='RUNNING';result['running']=case['id'];result['unrun'].remove(case['id']);j.write(result)
   p=subprocess.Popen(case['argv'],cwd=output,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)
   try:code=p.wait(timeout=min(case['timeout'],max(.01,deadline-time.monotonic())))
   except subprocess.TimeoutExpired:code=None
   leaked=bool(children());closed=close_children();p.poll()
   result['running']=None
   if code!=0 or leaked or not closed:
    result['state']='CASE_FAILED';result['failed']={'id':case['id'],'exit':code,'descendants_after_main':leaked,'writers_closed':closed};break
   result['completed'].append(case['id']);result['state']='CHECKPOINT';j.write(result)
   next_row,error=budget('renew',row['id'],'--expected-revision',row['revision'])
   if error:result['state']='SAFE_BOUNDARY_STOP';result['checkpoint_error']=error;break
   row=next_row;result['revision']=row['revision'];j.write(result)
  else:result['state']='COMPLETED'
 except BaseException as e:
  result['state']='SUPERVISOR_FAILED';result['error_type']=type(e).__name__
 finally:
  signal.signal(signal.SIGTERM,signal.SIG_IGN);signal.signal(signal.SIGINT,signal.SIG_IGN)
  result['writers_closed']=close_children()
  if result['running'] is not None:
   result['failed']={'id':result['running'],'exit':None};result['running']=None
  result['finished_epoch']=time.time();j.write(result)
  if result['writers_closed']:
   j.validate_path()
   released,error=budget('release',result['reservation'],'--expected-revision',result['revision'])
   result['reservation_released']=error is None
   if error:result['release_error']=error
   j.write(result)
  j.close();os.close(parent)
 print(json.dumps({'receipt':str(receipt),'state':result['state'],'completed':len(result['completed']),'unrun':len(result['unrun']),'writers_closed':result['writers_closed'],'reservation_released':result['reservation_released']}))
 return 0 if result['state']=='COMPLETED' and result['writers_closed'] else 3

if __name__=='__main__':
 a=argparse.ArgumentParser();s=a.add_subparsers(dest='action',required=True)
 r=s.add_parser('run')
 for x in ['plan','project','run','output']:r.add_argument('--'+x,required=True)
 r.add_argument('--bytes',type=int,required=True);r.add_argument('--inodes',type=int,required=True);r.add_argument('--deadline',type=int,default=3600)
 q=s.add_parser('status');q.add_argument('receipt');args=a.parse_args()
 if args.action=='status':
  j=Journal(args.receipt);print(json.dumps(j.read(),indent=2));j.close()
 else:
  if not 1<=args.deadline<=86400:raise ValueError('deadline bounds')
  raise SystemExit(run(args))
