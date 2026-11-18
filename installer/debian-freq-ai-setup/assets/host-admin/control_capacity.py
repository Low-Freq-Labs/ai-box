#!/usr/bin/python3 -I
"""Root-owned emergency capacity; no workload deletion or process termination."""
import argparse,json,os,pathlib,stat,time,fcntl,subprocess
BASE=pathlib.Path('/var/lib/freq-control-capacity')
SIZE=64*1024*1024
INODES=4096
LOW_BYTES=128*1024*1024
HIGH_BYTES=20*1024**3
LOW_INODES=2048
HIGH_INODES=16384

def check_dir(p):
 s=p.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o077:raise RuntimeError('unsafe reserve directory')

def write_state(fd,value):
 data=json.dumps(value,sort_keys=True).encode()+b'\n'
 if len(data)>4096:raise RuntimeError('state overflow')
 if os.pwrite(fd,data+b' '*(4096-len(data)),0)!=4096:raise RuntimeError('short state write')
 os.fsync(fd)

def snapshot(base=BASE,size=SIZE,inodes=INODES):
 check_dir(base)
 p=base/'bytes';s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_nlink!=1:raise RuntimeError('unsafe byte reservoir')
 d=base/'inodes';check_dir(d)
 names=os.listdir(d)
 if any(not n.isdecimal() or not 0<=int(n)<inodes or str(int(n))!=n for n in names):raise RuntimeError('unexpected reserve entry')
 for n in names:
  t=(d/n).lstat()
  if not stat.S_ISREG(t.st_mode) or t.st_uid!=0 or t.st_nlink!=1 or t.st_size!=0:raise RuntimeError('unsafe inode reservoir')
 return {'filesystem_device':s.st_dev,'allocated_bytes':s.st_blocks*512,'logical_bytes':s.st_size,'reserved_inodes':len(names),'target_bytes':size,'target_inodes':inodes,'armed':s.st_size==size and s.st_blocks*512>=size and len(names)==inodes}

def maintain(base=BASE,size=SIZE,inodes=INODES,low_bytes=LOW_BYTES,high_bytes=HIGH_BYTES,low_inodes=LOW_INODES,high_inodes=HIGH_INODES):
 if os.geteuid()!=0:raise PermissionError('root maintenance only')
 check_dir(base)
 lock=os.open(base/'lock',os.O_RDWR|os.O_NOFOLLOW)
 try:
  fcntl.flock(lock,fcntl.LOCK_EX)
  statefd=os.open(base/'state',os.O_RDWR|os.O_NOFOLLOW)
  try:
   s=os.fstat(statefd)
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_nlink!=1 or s.st_size!=4096:raise RuntimeError('unsafe reserve state')
   before=snapshot(base,size,inodes);v=os.statvfs(base);free=v.f_bavail*v.f_frsize;action='unchanged'
   if free<low_bytes or v.f_favail<low_inodes:
    # Release only prevalidated root-owned reservoir resources.
    fd=os.open(base/'bytes',os.O_WRONLY|os.O_NOFOLLOW)
    try:os.ftruncate(fd,0);os.fsync(fd)
    finally:os.close(fd)
    for n in os.listdir(base/'inodes'):(base/'inodes'/n).unlink()
    action='released' if before['allocated_bytes'] or before['reserved_inodes'] else 'unchanged'
   elif not before['armed'] and free>high_bytes+size and v.f_favail>high_inodes+inodes:
    fd=os.open(base/'bytes',os.O_WRONLY|os.O_NOFOLLOW)
    try:os.posix_fallocate(fd,0,size);os.fsync(fd)
    finally:os.close(fd)
    for i in range(inodes):
     p=base/'inodes'/str(i)
     if not p.exists():
      fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
    action='armed'
   for p in [base/'inodes',base]:
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
   result={'checked_epoch':time.time(),'action':action,'before':before,'after':snapshot(base,size,inodes),'free_before':free,'free_inodes_before':v.f_favail,'scope':'Emergency headroom, not a quota or exclusive space after release'}
   write_state(statefd,result);return result
  finally:os.close(statefd)
 finally:os.close(lock)

def initialize(base=BASE):
 if os.geteuid()!=0:raise PermissionError('root only')
 base.mkdir(mode=0o700);os.chmod(base,0o700)
 (base/'inodes').mkdir(mode=0o700)
 for n in ['lock','bytes','state']:
  fd=os.open(base/n,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
  if n=='state':os.posix_fallocate(fd,0,4096);write_state(fd,{'state':'initializing'})
  os.close(fd)

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('action',choices=['initialize','maintain','status']);args=a.parse_args()
 if args.action=='initialize':initialize();print(json.dumps(maintain()))
 elif args.action=='maintain':
  result=maintain()
  print(json.dumps(result))
 else:print(json.dumps(snapshot()))
