#!/usr/bin/python3 -I
"""Opt-in Jarvis root transport. Never part of ordinary agent creation."""
import argparse,base64,hashlib,json,os,pwd,shutil,stat,subprocess,tempfile,time
from pathlib import Path

HERE=Path(__file__).resolve().parent
def sha(raw):return hashlib.sha256(raw).hexdigest()
def parent(path,owner=0):
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:-1]:
            try:nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            except FileNotFoundError:
                os.mkdir(part,0o700 if str(path).startswith('/home/jarvis/') else 0o755,dir_fd=fd)
                nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.fchown(nxt,owner,owner_gid if owner else 0)
            m=os.fstat(nxt)
            if m.st_uid not in (0,owner) or m.st_mode&0o022:
                os.close(nxt);raise ValueError('Unsafe destination parent')
            os.close(fd);fd=nxt
        return fd
    except BaseException:os.close(fd);raise
def read(fd,name):
    try:f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    except FileNotFoundError:return None
    try:
        m=os.fstat(f)
        if not stat.S_ISREG(m.st_mode) or m.st_nlink!=1 or m.st_size>1048576:raise ValueError('Unsafe target file')
        with os.fdopen(os.dup(f),'rb') as stream:data=stream.read()
        return {'data':data,'uid':m.st_uid,'gid':m.st_gid,'mode':stat.S_IMODE(m.st_mode),
                'xattrs':{k:base64.b64encode(os.getxattr(f,k)).decode() for k in os.listxattr(f)}}
    finally:os.close(f)
def write(fd,name,data,metadata):
    tmp='.'+name+'.vm-root-'+str(time.time_ns())
    f=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
    try:
        with os.fdopen(f,'wb') as stream:
            stream.write(data);os.fchown(stream.fileno(),metadata['uid'],metadata['gid'])
            for k in os.listxattr(stream.fileno()):os.removexattr(stream.fileno(),k)
            for k,v in metadata.get('xattrs',{}).items():os.setxattr(stream.fileno(),k,base64.b64decode(v))
            os.fchmod(stream.fileno(),metadata['mode']);stream.flush();os.fsync(stream.fileno())
        os.rename(tmp,name,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
    finally:
        try:os.unlink(tmp,dir_fd=fd)
        except FileNotFoundError:pass

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grant-jarvis-root',action='store_true',required=True)
    parser.add_argument('--approval',required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root required')
    if not args.approval or len(args.approval)>160:raise SystemExit('Approval reference required')
    account=pwd.getpwnam('jarvis');owner_gid=account.pw_gid
    assert account.pw_dir=='/home/jarvis'
    ssh=subprocess.check_output(['/usr/sbin/sshd','-T','-C','user=root,host=localhost,addr=127.0.0.1'],text=True)
    assert 'port 22\n' in ssh and 'pubkeyauthentication yes\n' in ssh and 'forcecommand none\n' in ssh
    assert any('permitrootlogin '+v+'\n' in ssh for v in ('yes','without-password','prohibit-password'))
    assert 'authorizedkeysfile .ssh/authorized_keys' in ssh
    backup=Path('/var/backups')/('freq-jarvis-root-'+str(time.time_ns()))
    backup.mkdir(mode=0o700);(backup/'private').mkdir(mode=0o700)
    key=backup/'private/generated-key'
    subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-C','jarvis-ai-box-root-20261006','-f',str(key)],check=True)
    public=key.with_suffix('.pub').read_text().strip()
    fingerprint=subprocess.check_output(['/usr/bin/ssh-keygen','-lf',str(key.with_suffix('.pub'))],text=True).split()[1]
    hostkey=Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()
    additions=[]
    def add(path,data,uid=0,gid=0,mode=0o644,append=False):
        fd=parent(path,uid)
        try:
            before=read(fd,Path(path).name)
            if before and not append:raise ValueError('Target already exists: '+path)
            if before and before['uid']!=uid:raise ValueError('Unexpected target owner')
            if append and before:data=before['data'].rstrip(b'\n')+b'\n'+data
            metadata={k:before[k] for k in ('uid','gid','mode','xattrs')} if before else {'uid':uid,'gid':gid,'mode':mode,'xattrs':{}}
            i=len(additions)
            if before:(backup/'private'/str(i)).write_bytes(before['data']);(backup/'private'/str(i)).chmod(0o600)
            additions.append({'path':path,'before_sha256':sha(before['data']) if before else None,'after_sha256':sha(data),'metadata':metadata,'backup':str(i) if before else None})
            write(fd,Path(path).name,data,metadata)
        finally:os.close(fd)
    try:
        add('/home/jarvis/.local/share/freq-vm-admin/id_ed25519',key.read_bytes(),account.pw_uid,owner_gid,0o600)
        add('/etc/freq-ai-setup/vm-root/known_hosts',('freq-ai-box-local-root '+hostkey[0]+' '+hostkey[1]+'\n').encode())
        add('/usr/local/bin/vm-root',(HERE/'vm-root').read_bytes(),mode=0o755)
        for root,uid,gid in [('/opt/freq-agents/skills',0,0),('/home/jarvis/.codex/skills',account.pw_uid,owner_gid)]:
            for item in ('SKILL.md','agents/openai.yaml'):
                add(root+'/vm-admin/'+item,(HERE/'skills/vm-admin'/item).read_bytes(),uid,gid)
        notice=b'\n## ai-box root administration (Sonny, 2026-10-06)\n\nSonny has explicitly granted Jarvis unrestricted root administration on ai-box,\nincluding writing and deploying new repairs. Read the vm-admin skill at\n/home/jarvis/.codex/skills/vm-admin/SKILL.md and use vm-root from this session.\nThis supersedes older scoped-tooling-only restrictions for Jarvis on this VM.\nThe existing scoped commands remain useful; they do not limit this root grant.\nRoutine VM repairs do not require Codex intervention or repeated approval.\nPreserve recovery evidence, verify results, honor task intent and coordinate\ndisruption; do not expose credentials or silently grant peers root access.\n'
        add('/home/jarvis/.codex/AGENTS.md',notice,account.pw_uid,owner_gid,append=True)
        # Enable the root key last, after command, host pin and documentation exist.
        line='from="127.0.0.1,::1",no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-user-rc '+public+'\n'
        add('/root/.ssh/authorized_keys',line.encode(),mode=0o600,append=True)
        state='COMMITTED'
    except BaseException:
        state='PARTIAL_REQUIRES_OPERATOR_REVIEW';raise
    finally:
        receipt={'state':state,'actor':'root','agent':'jarvis','approval':args.approval,'root_key_fingerprint':fingerprint,'backup':str(backup),'files':additions}
        (backup/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2))
