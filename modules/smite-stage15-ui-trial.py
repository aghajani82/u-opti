#!/usr/bin/env python3
"""IR-only, static UI trial. No Docker lifecycle, backend, database or Nginx writes."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import zipfile

SOURCE = '3969855298ce7e63ea8a3f7824a0ae20aea09b2c'
STATE = Path('/var/lib/u-opti/smite-ui-trial')
ENGINE_LOCK = Path('/run/lock/u-opti-smite-engine.lock')
LIMIT = 32 * 1024 * 1024

class Hold(RuntimeError): pass

def need(value, reason):
    if not value: raise Hold(reason)

def digest(data): return hashlib.sha256(data).hexdigest()
def encoded(data): return base64.b64encode(data).decode('ascii')
def decoded(data): return base64.b64decode(data, validate=True)

def safe_name(name):
    return bool(re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name)) and all(x not in ('.','..') for x in name.split('/'))

def trusted(path, directory=False, private=False):
    s=path.lstat()
    need((stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)) and s.st_uid==0 and not s.st_mode & 0o022, 'UNTRUSTED_PATH')
    if not directory: need(s.st_nlink==1,'HARDLINK_DENIED')
    if private: need(stat.S_IMODE(s.st_mode)==(0o700 if directory else 0o600),'PRIVATE_MODE_REQUIRED')

def ancestors(path):
    for p in reversed((path, *path.parents)):
        trusted(p,directory=True)

def read_tree(root):
    ancestors(root)
    files={}; total=0
    for p in sorted(root.rglob('*')):
        trusted(p,directory=p.is_dir())
        if p.is_dir(): continue
        if p.name.startswith('.uopti-ui-'): continue  # Inert interrupted staging; never referenced.
        n=p.relative_to(root).as_posix(); need(safe_name(n),'UNSAFE_NAME')
        total+=p.stat().st_size; need(total<=LIMIT,'TREE_TOO_LARGE')
        files[n]=encoded(p.read_bytes())
    need('index.html' in files,'STATIC_INDEX_MISSING')
    return files

def hashes(files): return {n:digest(decoded(data)) for n,data in files.items()}

def backend(root, expected):
    need(isinstance(expected,dict) and 'main.py' in expected and len(expected)>10,'BACKEND_MANIFEST_REQUIRED')
    actual={p.relative_to(root).as_posix() for p in (root/'app').rglob('*.py')} | {'main.py'}
    need(actual==set(expected),'BACKEND_FILESET_MISMATCH')
    for n,h in expected.items():
        need(safe_name(n) and (n=='main.py' or n.startswith('app/')),'BACKEND_PATH_INVALID')
        p=root/n;ancestors(p.parent);trusted(p)
        need(digest(p.read_bytes())==h,'BACKEND_VERSION_MISMATCH')

def atomic_file(path, data):
    # A unique temp file on the same filesystem; never overwrite assets.
    fd,name=tempfile.mkstemp(prefix='.uopti-ui-',dir=path.parent)
    try:
        os.fchmod(fd,0o644)
        with os.fdopen(fd,'wb') as f: f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        if os.path.exists(name): os.unlink(name)

def worker(root, data):
    """Only /app/static can be written; all other inspected content is read-only."""
    backend(root,data['backend'])
    area=root/'static'; current=read_tree(area)
    need(stat.S_IMODE((area/'index.html').stat().st_mode)==0o644,'INDEX_MODE_MISMATCH')
    if data['action']=='snapshot': return current
    old=data['old']; new=data['new']; expected={**hashes(old),**hashes(new)}
    need(set(new)>={'index.html'} and all(n=='index.html' or n.startswith('assets/') for n in new),'STATIC_SCOPE_INVALID')
    need(all(safe_name(n) for n in set(old)|set(new)),'STATIC_PATH_INVALID')
    oldh=hashes(old); newh=hashes(new); currenth=hashes(current)
    # Candidate assets may coexist after an interrupted upload. Old assets stay.
    for n,h in currenth.items():
        if n.startswith('.uopti-ui-'): raise Hold('INTERRUPTED_TEMP_REQUIRES_REVIEW')
        if n=='index.html': need(h in (oldh[n],newh[n]),'INDEX_DRIFT')
        else: need(n in expected and h==expected[n],'ASSET_DRIFT')
    need(set(old)-{'index.html'} <= set(current),'OLD_ASSET_MISSING')
    need(all(oldh[n]==newh[n] for n in set(old)&set(new)-{'index.html'}),'ASSET_COLLISION')
    if data['action']=='verify':
        need(currenth.get('index.html')==newh['index.html'] and all(currenth.get(n)==h for n,h in newh.items()),'UI_VERIFY_FAILED')
        return {'status':'PASS'}
    if data['action']=='rollback':
        atomic_file(area/'index.html',decoded(old['index.html']))
        need(read_tree(area)['index.html']==old['index.html'],'ROLLBACK_VERIFY_FAILED')
        return {'status':'ROLLED_BACK'}
    need(data['action']=='apply' and currenth['index.html']==oldh['index.html'],'APPLY_STATE_INVALID')
    for n,blob in new.items():
        if n=='index.html': continue
        p=area/n
        need(len(p.relative_to(area).parts)==2,'ASSET_DEPTH_INVALID')
        if not p.parent.exists(): p.parent.mkdir(mode=0o755)
        ancestors(p.parent)
        if n in current: need(currenth[n]==newh[n],'ASSET_COLLISION');continue
        # A complete asset becomes visible through atomic hardlink, no partial asset.
        fd,tmp=tempfile.mkstemp(prefix='.uopti-ui-',dir=p.parent)
        try:
            os.fchmod(fd,0o644)
            with os.fdopen(fd,'wb') as f:f.write(decoded(blob));f.flush();os.fsync(f.fileno())
            os.link(tmp,p)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        d=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    # Recheck the entire original index and all assets just before the commit point.
    after=read_tree(area); ah=hashes(after)
    need(ah=={**oldh,**{n:h for n,h in newh.items() if n!='index.html'}},'PRECOMMIT_DRIFT')
    backend(root,data['backend'])
    atomic_file(area/'index.html',decoded(new['index.html']))
    return {'status':'APPLIED'}

def run(args, payload=None):
    p=subprocess.run(['/usr/bin/docker','--host','unix:///var/run/docker.sock',*args],
        input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
    need(p.returncode==0,'DOCKER_OPERATION_FAILED')
    need(len(p.stdout)<=LIMIT*2,'OUTPUT_TOO_LARGE')
    return p.stdout

def identity():
    rows=json.loads(run(['inspect','smite-panel','smite-node']))
    result=[]
    for row in rows:
        need(row['State']['Running'] and not row['State'].get('Paused'),'CONTAINER_NOT_RUNNING')
        need(row['State'].get('Health',{}).get('Status','healthy')=='healthy','CONTAINER_UNHEALTHY')
        result.append({k:row[k] for k in ('Id','Image','RestartCount','Mounts')})
        result[-1]['pid']=row['State']['Pid'];result[-1]['started']=row['State']['StartedAt']
    panel=rows[0]
    need(panel['Name']=='/smite-panel' and rows[1]['Name']=='/smite-node','CONTAINER_IDENTITY')
    need(not panel['HostConfig']['ReadonlyRootfs'],'READ_ONLY_PANEL_ROOT')
    for m in panel['Mounts']:
        d=m['Destination'].rstrip('/') or '/'
        need(not (d=='/' or d=='/app' or d.startswith('/app/static') or d=='/app/main.py' or d=='/app/app' or d.startswith('/app/app/')),'MOUNTED_UI_OR_BACKEND_HOLD')
    processes=run(['top','smite-node','-eo','pid,comm']).decode().splitlines()[1:]
    frp=sorted(line.split() for line in processes if line.split()[-1:] in (['frps'],['frpc']))
    need(sum(row[-1]=='frps' for row in frp)==1,'FRPS_SINGLETON_REQUIRED')
    result.append({'node_frp_processes':frp})
    return result

def remote(action, manifest, **kwargs):
    source=Path(__file__).read_text()
    payload=json.dumps(dict(action=action,backend=manifest['backend_sha256'],**kwargs)).encode()
    return json.loads(run(['exec','-i','smite-panel','python3','-c',source,'--container-worker'],payload))

def bundle(path, sha):
    need(re.fullmatch('[0-9a-f]{64}',sha or '') is not None,'PINNED_SHA256_REQUIRED')
    trusted(path);need(path.stat().st_size<=LIMIT,'BUNDLE_TOO_LARGE')
    raw=path.read_bytes();need(digest(raw)==sha,'BUNDLE_SHA256_MISMATCH')
    import io
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries=z.infolist();names=[i.filename for i in entries]
        need(len(names)==len(set(names)) and sum(i.file_size for i in entries)<=LIMIT,'UNTRUSTED_ZIP')
        need(all(safe_name(i.filename) and not i.is_dir() and i.external_attr>>16&0o170000!=0o120000 for i in entries),'UNTRUSTED_ZIP')
        manifest=json.loads(z.read('manifest.json'))
        need(manifest['schema']==1 and manifest['source_commit']==SOURCE and manifest['web_approval_enabled'] is False,'WRONG_UI_SOURCE')
        files=manifest['files_sha256']
        need(set(names)==set(files)|{'manifest.json'},'ZIP_MEMBER_MISMATCH')
        need(all(digest(z.read(n))==h for n,h in files.items()),'ZIP_CONTENT_MISMATCH')
        need(digest(Path(__file__).read_bytes())==files['ui-trial.py'],'HELPER_VERSION_MISMATCH')
        new={n[7:]:encoded(z.read(n)) for n in files if n.startswith('static/')}
    need('index.html' in new and all(n=='index.html' or re.fullmatch(r'assets/[A-Za-z0-9_.-]+',n) for n in new),'STATIC_SCOPE_INVALID')
    return manifest,new

def save(doc):
    target=STATE/'record.json'
    fd,name=tempfile.mkstemp(prefix='.record-',dir=STATE)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:json.dump(doc,f,sort_keys=True);f.flush();os.fsync(f.fileno())
        os.replace(name,target)
        d=os.open(STATE,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        if os.path.exists(name):os.unlink(name)

def main():
    if sys.argv[1:]==['--container-worker']:
        need(os.geteuid()==0,'ROOT_REQUIRED')
        print(json.dumps(worker(Path('/app'),json.load(sys.stdin))))
        return
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['preflight','backup','apply','verify','rollback'])
    p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True)
    a=p.parse_args()
    need(os.geteuid()==0 and os.uname().nodename.split('.')[0].lower()=='ir','IR_ROOT_ONLY')
    trusted(a.bundle)
    manifest,new=bundle(a.bundle.absolute(),a.sha256)
    initial=identity()
    if a.action=='preflight':
        old=remote('snapshot',manifest)
        need(identity()==initial,'RUNTIME_CHANGED')
        need(all(hashes(old)[n]==hashes(new)[n] for n in set(old)&set(new)-{'index.html'}),'ASSET_COLLISION')
        print('PREFLIGHT=PASS; LIVE_CHANGES=NONE; NO_RESTART=YES');return
    need(sys.stdin.isatty() or a.action=='verify','ROOT_TTY_REQUIRED')
    trusted(ENGINE_LOCK)
    with ENGINE_LOCK.open('r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if a.action=='backup':
            ancestors(STATE.parent)
            need(not STATE.exists() and not STATE.is_symlink(),'TRIAL_ALREADY_EXISTS')
            old=remote('snapshot',manifest);need(identity()==initial,'RUNTIME_CHANGED')
            STATE.mkdir(mode=0o700)
            save(dict(schema=1,phase='BACKED_UP',bundle_sha256=a.sha256,identity=initial,old=old,new_sha256=hashes(new)))
            print('BACKUP=PASS; STATIC_FILES_ONLY=YES');return
        ancestors(STATE);trusted(STATE,True,True);trusted(STATE/'record.json',private=True)
        doc=json.loads((STATE/'record.json').read_text())
        need(doc['schema']==1 and doc['bundle_sha256']==a.sha256 and doc['new_sha256']==hashes(new),'BACKUP_BUNDLE_MISMATCH')
        need(doc['identity']==initial,'RUNTIME_DRIFT')
        if a.action=='apply':
            need(doc['phase']=='BACKED_UP','REPEAT_APPLY_DENIED')
            need(input('Type APPLY-UI-ONLY: ')=='APPLY-UI-ONLY','CANCELLED')
            need(identity()==initial,'RUNTIME_DRIFT')
            doc['phase']='APPLYING';save(doc)
            remote('apply',manifest,old=doc['old'],new=new)
            need(identity()==initial,'RUNTIME_DRIFT')
            remote('verify',manifest,old=doc['old'],new=new)
            doc['phase']='COMMITTED';save(doc)
        elif a.action=='verify':
            need(doc['phase'] in ('APPLYING','COMMITTED'),'NOT_APPLIED')
            remote('verify',manifest,old=doc['old'],new=new)
            need(identity()==initial,'RUNTIME_DRIFT')
        else:
            need(doc['phase'] in ('APPLYING','COMMITTED','ROLLING_BACK','ROLLED_BACK'),'NOT_APPLIED')
            need(input('Type ROLLBACK-UI-ONLY: ')=='ROLLBACK-UI-ONLY','CANCELLED')
            doc['phase']='ROLLING_BACK';save(doc)
            remote('rollback',manifest,old=doc['old'],new=new)
            need(identity()==initial,'RUNTIME_DRIFT')
            doc['phase']='ROLLED_BACK';save(doc)
        print(a.action.upper()+'=PASS; BACKEND_UNCHANGED=YES; NODE_RESTART=NO; NGINX_RELOAD=NO')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('HOLD: '+(str(exc) if isinstance(exc,Hold) else type(exc).__name__),file=sys.stderr)
        sys.exit(2)
