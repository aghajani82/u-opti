#!/usr/bin/env python3
"""Transactional RC7 WSS *runtime* opt-in; no Nginx edge, FRPS or tunnel Apply.

This separately gated field-trial helper must never be used to modify Sanaei.
Grandoptical requires verified provider snapshots and independent console access.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
STATE=Path('/var/lib/u-opti/smite-rc7-wss-runtime')
LOCK=Path('/run/lock/u-opti-smite-engine.lock')
OVERLAY='docker-compose.wss-rc7.yml'
EDGE=Path('/var/lib/u-opti/smite-rc7-wss-edge/record.json')
SIGNED_PROBE=r'''
import json, secrets, urllib.error, urllib.request
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id, secret = read_identity("/run/smite-node-identity/node-identity.json")
target="/api/agent/status"
headers=sign_request(secret=secret,node_id=node_id,method="GET",target=target,
                     body=b"",nonce=secrets.token_hex(16))
url="http://127.0.0.1:8888"+target
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
req=urllib.request.Request(url,headers=headers)
with opener.open(req,timeout=6) as resp:
    data=json.load(resp)
    assert resp.status==200 and data.get("status")=="ok"
try:
    opener.open(req,timeout=6)
except urllib.error.HTTPError as exc:
    assert exc.code==401
else:
    raise SystemExit(2)
print("RC7_SIGNED_HMAC_REPLAY=PASS")
'''

def load(name):
    spec=importlib.util.spec_from_file_location('rc7_wss_admission',HERE/name)
    if spec is None or spec.loader is None:
        raise RuntimeError('REVIEWED_HELPER_UNAVAILABLE')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
p=load('smite-rc7-wss-preflight.py')
Hold=p.Hold
need=p.need

def run(args,timeout=150,input=None):
    need(not any(os.environ.get(key) for key in (
        'DOCKER_HOST','DOCKER_CONTEXT','DOCKER_CONFIG','DOCKER_TLS_VERIFY',
        'DOCKER_CERT_PATH','COMPOSE_FILE','COMPOSE_PROFILES',
    )),'AMBIENT_DOCKER_OVERRIDE')
    try:
        x=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                         input=input,text=True,timeout=timeout,check=False)
    except (OSError,subprocess.SubprocessError) as exc:
        raise Hold('EXECUTION_FAILED') from exc
    need(x.returncode==0 and len(x.stdout)<262144,'EXECUTION_FAILED')
    return x.stdout.strip()

def atomic_new(path,data,mode=0o600):
    need(not path.exists() and not path.is_symlink(),'UNEXPECTED_EXISTING_FILE')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),mode)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        fsync_dir(path.parent)

def fsync_dir(directory):
    fd=os.open(directory,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try: os.fsync(fd)
    finally: os.close(fd)

def atomic_record(doc):
    # Persist every mutation boundary; an unknown partial record HOLDS.
    raw=(json.dumps(doc,sort_keys=True,separators=(',',':'))+'\n').encode()
    tmp=STATE/'record.next'
    need(not tmp.exists() and not tmp.is_symlink(),'PARTIAL_RECORD_NEEDS_REVIEW')
    atomic_new(tmp,raw)
    os.replace(tmp,STATE/'record.json')
    fsync_dir(STATE)

def record():
    path=STATE/'record.json'
    need(path.is_file() and not path.is_symlink(),'WSS_JOURNAL_UNAVAILABLE')
    st=path.stat()
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0 and
         stat.S_IMODE(st.st_mode)==0o600,'UNTRUSTED_WSS_JOURNAL')
    doc=json.loads(path.read_text())
    need(doc.get('schema')==1 and doc.get('role') in ('ir','foreign')
         and doc.get('state') in ('PREPARED','APPLYING','COMMITTED',
                                  'ROLLING_BACK','ROLLED_BACK','HOLD')
         and isinstance(doc.get('services'),list)
         and doc.get('services')==(['smite-panel','smite-node'] if doc['role']=='ir'
                                   else ['smite-node']),
         'INVALID_WSS_JOURNAL')
    return doc

@contextlib.contextmanager
def locked():
    LOCK.parent.mkdir(exist_ok=True)
    fd=os.open(LOCK,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        st=os.fstat(fd)
        need(st.st_uid==0 and stat.S_IMODE(st.st_mode)==0o600
             and stat.S_ISREG(st.st_mode) and st.st_nlink==1,
             'UNSAFE_ENGINE_LOCK')
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise Hold('ENGINE_LOCK_BUSY') from exc
        yield
    finally:
        os.close(fd)

def inspect_container(name):
    docs=json.loads(p.run(['docker','inspect',name]))
    need(isinstance(docs,list) and len(docs)==1,'CONTAINER_INSPECT_INVALID')
    return docs[0]

def overlay_path(name):
    return (p.PANEL if name=='smite-panel' else p.NODE)/OVERLAY

def protected_paths(role):
    names=['smite-node'] if role=='foreign' else ['smite-panel','smite-node']
    paths=set()
    for name in names:
        obj=inspect_container(name)
        _,files=p.compose_files(name,obj)
        paths.update(files)
        root=p.PANEL if name=='smite-panel' else p.NODE
        paths.add(str(root/'.env'))
    paths.add('/etc/u-opti/smite/identities/node-identity.json')
    paths.add('/var/lib/u-opti/smite-node-security/replay/agent-replay.sqlite3')
    return sorted(paths)

def protected_receipt(paths):
    result={}
    for name in paths:
        path=Path(name)
        need(path.is_file() and not path.is_symlink(),'PROTECTED_FILE_MISSING')
        st=path.stat()
        need(stat.S_ISREG(st.st_mode),'PROTECTED_FILE_UNSAFE')
        # Only root-owned configuration and identity are admitted.
        need(st.st_uid==0,'PROTECTED_FILE_OWNER_DRIFT')
        proof={'dev':st.st_dev,'inode':st.st_ino}
        if path.name=='agent-replay.sqlite3':
            proof['kind']='replay'
        else:
            proof['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        result[name]=proof
    return result

def check_protected(doc):
    current=protected_receipt(doc['protected'].keys())
    need(current==doc['protected'],'PROTECTED_CONFIG_OR_IDENTITY_DRIFT')

def runtime_signature(obj):
    # Hash sensitive values privately without exposing them in output/logs.
    host=obj['HostConfig']
    env=p.runtime_env(obj)
    env.pop('SMITE_FRP_STANDARD_WSS',None)
    binds=host.get('Binds')
    norm=dict(host)
    if binds is not None:
        need(isinstance(binds,list) and all(isinstance(x,str) for x in binds),
             'UNSAFE_HOST_BINDS')
        norm['Binds']=sorted(binds)
    mounts=[{k:m.get(k) for k in ('Type','Source','Destination','RW')}
            for m in obj.get('Mounts',[])]
    return hashlib.sha256(json.dumps({
        'image':obj['Config']['Image'],
        'env':env,'command':obj['Config']['Cmd'],
        'entrypoint':obj['Config'].get('Entrypoint'),
        'host':norm,'mounts':sorted(mounts,key=lambda m:m['Destination'] or ''),
    },sort_keys=True,default=str).encode()).hexdigest()

def ensure_service(name,doc,*,enabled,healthy=True):
    obj=inspect_container(name)
    # Validate all security parameters against the exact reviewed baseline
    # with the one permitted WSS flag stripped solely for admission.
    safe=json.loads(json.dumps(obj))
    env=p.runtime_env(obj)
    if enabled:
        need(env.get('SMITE_FRP_STANDARD_WSS')=='1','WSS_ENV_NOT_ACTIVE')
        safe['Config']['Env']=[x for x in safe['Config']['Env']
                               if not x.startswith('SMITE_FRP_STANDARD_WSS=')]
    else:
        need('SMITE_FRP_STANDARD_WSS' not in env,'UNEXPECTED_WSS_ENV')
    labels=safe['Config']['Labels']
    active=labels.get('com.docker.compose.project.config_files','').split(',')
    overlay=str(overlay_path(name))
    if enabled:
        need(active and active[-1]==overlay and active.count(overlay)==1,
             'WSS_COMPOSE_OWNER_DRIFT')
        labels['com.docker.compose.project.config_files']=','.join(active[:-1])
    else:
        need(overlay not in active,'WSS_OVERLAY_UNEXPECTED')
    if not healthy:
        safe['State']['Running']=True
        safe['State']['Health']={'Status':'healthy'}
    p.service_gate(name,safe,role=('panel-iran' if doc['role']=='ir' else 'foreign'),
                   domain=doc['domain'])
    project,files=p.compose_files(name,safe)
    need(project==doc['project'] and files==doc['baseline'][name]['files'],
         'WSS_COMPOSE_BASELINE_DRIFT')
    need(runtime_signature(obj)==doc['baseline'][name]['signature'],
         'WSS_RUNTIME_SECURITY_DRIFT')
    return project,files

def compose(name,doc,enabled):
    args=['docker','compose','--project-name',doc['project']]
    for path in doc['baseline'][name]['files']:
        args+=['-f',path]
    if enabled:
        path=overlay_path(name)
        need(path.is_file() and not path.is_symlink()
             and path.read_bytes()==p.overlay_bytes(name).encode(),
             'WSS_OVERLAY_CONTENT_DRIFT')
        args+=['-f',str(path)]
    return args

def no_tunnels():
    for root in (p.PANEL,p.NODE):
        item=root/'config/tunnels.json'
        if item.is_file() or item.is_symlink():
            need(not item.is_symlink() and json.loads(item.read_text())=={},
                 'TUNNELS_MUST_BE_REMOVED_FIRST')
    need(not p.run(['ss','-H','-lnt','( sport = :7000 )']).strip(),
         'FRPS_OWNER_RUNNING')
    need(not re.search(r'(?<![A-Za-z0-9_])frps(?![A-Za-z0-9_])',
                       p.run(['ss','-H','-lntp'])),'FRPS_OWNER_RUNNING')

def signed_probe():
    need(run(['docker','exec','smite-node','python3','-c',SIGNED_PROBE],
             timeout=30)=='RC7_SIGNED_HMAC_REPLAY=PASS',
         'NODE_SIGNED_HMAC_REPLAY_FAILED')

def panel_probe(domain):
    run(['curl','--noproxy','*','-4','-fsS','--connect-timeout','3',
         '--max-time','12','--resolve',domain+':443:127.0.0.1',
         '-o','/dev/null','https://'+domain+'/'],timeout=17)

def verify(doc):
    need(doc['state']=='COMMITTED','WSS_RUNTIME_NOT_COMMITTED')
    check_protected(doc)
    # Verification is safe even after an independently approved FRPS owner.
    # Rollback alone must require no active tunnels or data listeners.
    for name in doc['services']:
        ensure_service(name,doc,enabled=True)
    signed_probe()
    if doc['role']=='ir':
        panel_probe(doc['domain'])
    print('RC7_WSS_RUNTIME_VERIFY=PASS_SIGNED_REPLAY')
    print('LIVE_CONFIG_CHANGES=NONE')

def backup_panel():
    db=p.PANEL/'panel/data/smite.db'
    need(db.is_file() and not db.is_symlink(),'PANEL_DB_UNAVAILABLE')
    target=STATE/'panel-before.sqlite3'
    atomic_new(target,b'')
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst)
            need(dst.execute('PRAGMA integrity_check').fetchone()==('ok',),
                 'PANEL_DB_BACKUP_INVALID')
    fsync_dir(STATE)

def planned(role,peer_ip):
    p.inspect(role,peer_ip)  # all existing real-host checks, read-only
    need(not STATE.exists() and not STATE.is_symlink(),'WSS_RUNTIME_JOURNAL_EXISTS')
    names=['smite-panel','smite-node'] if role=='ir' else ['smite-node']
    domain=p.state()['SMITE_PANEL_DOMAIN']
    baseline={}
    owner=None
    for name in names:
        obj=inspect_container(name)
        project,files=p.compose_files(name,obj)
        need(owner is None or project==owner,'PANEL_NODE_OWNER_MISMATCH')
        owner=project
        need(not overlay_path(name).exists() and not overlay_path(name).is_symlink(),
             'WSS_RC7_OVERLAY_ALREADY_EXISTS')
        baseline[name]={'files':files,'signature':runtime_signature(obj)}
    return {'schema':1,'role':role,'state':'PREPARED','domain':domain,
            'peer':peer_ip if role=='ir' else None,'project':owner,
            'services':names,'baseline':baseline,
            'protected':protected_receipt(protected_paths(role))}

def apply(role,peer):
    with locked():
        doc=planned(role,peer)
        need(not STATE.exists(),'WSS_RUNTIME_JOURNAL_EXISTS')
        STATE.mkdir(mode=0o700)
        fsync_dir(STATE.parent)
        atomic_record(doc)
        try:
            if role=='ir': backup_panel()
            for name in doc['services']:
                atomic_new(overlay_path(name),p.overlay_bytes(name).encode())
            doc['state']='APPLYING';atomic_record(doc)
            for name in doc['services']:
                ensure_service(name,doc,enabled=False)
                run(compose(name,doc,True)+[
                    'up','-d','--no-build','--no-deps','--pull','never',
                    '--force-recreate',name],timeout=180)
                # Inspect and replay-probe only when the new Node is healthy.
                if name=='smite-node':
                    for attempt in range(25):
                        try:
                            ensure_service(name,doc,enabled=True)
                            signed_probe()
                            break
                        except Hold:
                            if attempt==24:raise
                            time.sleep(2)
                else:
                    for attempt in range(25):
                        try:
                            ensure_service(name,doc,enabled=True)
                            break
                        except Hold:
                            if attempt==24:raise
                            time.sleep(2)
            check_protected(doc)
            if role=='ir':panel_probe(doc['domain'])
            doc['state']='COMMITTED';atomic_record(doc)
            print('RC7_WSS_RUNTIME_APPLY=PASS_SIGNED')
            print('FRPS_STARTED=NO')
            print('SANAEI_CONTAINER_CHANGED=NO')
        except Exception:
            # Never conceal a partial transition. Recovery is explicitly
            # operator-gated and must preserve the protected files.
            doc['state']='HOLD'
            atomic_record(doc)
            raise Hold('WSS_APPLY_HOLD_REVIEW_BEFORE_RECOVER')

def edge_absent():
    # Prevent removing a runtime while its IR public WSS edge is active.
    if EDGE.exists():
        data=json.loads(EDGE.read_text())
        need(data.get('state')=='ROLLED_BACK','ROLLBACK_EDGE_FIRST')

def restore(doc):
    edge_absent()
    no_tunnels()
    check_protected(doc)
    # Check every container and overlay before any mutation.
    for name in doc['services']:
        env=p.runtime_env(inspect_container(name))
        active=env.get('SMITE_FRP_STANDARD_WSS')=='1'
        ensure_service(name,doc,enabled=active,healthy=False)
        path=overlay_path(name)
        if path.exists() or path.is_symlink():
            need(path.is_file() and not path.is_symlink()
                 and path.read_bytes()==p.overlay_bytes(name).encode(),
                 'WSS_OVERLAY_CONTENT_DRIFT')
    doc['state']='ROLLING_BACK';atomic_record(doc)
    for name in reversed(doc['services']):
        run(compose(name,doc,False)+[
            'up','-d','--no-build','--no-deps','--pull','never',
            '--force-recreate',name],timeout=180)
        for attempt in range(25):
            try:
                ensure_service(name,doc,enabled=False)
                if name=='smite-node':signed_probe()
                break
            except Hold:
                if attempt==24:raise
                time.sleep(2)
    check_protected(doc)
    if doc['role']=='ir':panel_probe(doc['domain'])
    for name in doc['services']:
        path=overlay_path(name)
        if path.is_file():
            path.unlink()
            fsync_dir(path.parent)
    doc['state']='ROLLED_BACK';atomic_record(doc)
    print('RC7_WSS_RUNTIME_ROLLBACK=PASS')
    print('IDENTITY_REPLAY_RETAINED=YES')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=('apply','verify','rollback','recover'))
    ap.add_argument('--role',choices=('ir','foreign'),required=True)
    ap.add_argument('--peer-ip')
    ap.add_argument('--snapshot-confirm',default='')
    args=ap.parse_args()
    try:
        need(os.geteuid()==0,'ROOT_REQUIRED')
        if args.action!='verify':
            need(sys.stdin.isatty() and args.snapshot_confirm=='SNAPSHOTS-CONSOLES-VERIFIED',
                 'PROVIDER_SNAPSHOT_AND_CONSOLE_REQUIRED')
            challenge=args.action.upper()+'-RC7-WSS-'+args.role.upper()
            need(input('Type '+challenge+': ').strip()==challenge,'OPERATOR_CANCELLED')
        if args.action=='apply':
            apply(args.role,args.peer_ip)
        else:
            with locked():
                doc=record()
                need(doc['role']==args.role,'WSS_ROLE_MISMATCH')
                if args.action=='verify':
                    verify(doc)
                elif args.action=='rollback':
                    need(doc['state']=='COMMITTED','USE_RECOVER_FOR_INCOMPLETE_TRANSACTION')
                    restore(doc)
                else:
                    need(doc['state'] in ('PREPARED','APPLYING','HOLD','ROLLING_BACK'),
                         'RECOVERY_STATE_NOT_ALLOWED')
                    restore(doc)
        return 0
    except (Hold,OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
        msg=str(exc)
        print('HOLD: '+(msg if re.fullmatch('[A-Z0-9_]{1,100}',msg)
                         else 'UNTRUSTED_WSS_RUNTIME_STATE'),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
