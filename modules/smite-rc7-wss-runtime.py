#!/usr/bin/env python3
"""Transactional RC7/RC9 WSS runtime opt-in for signed test hosts.

This separately gated field-trial helper must never be used to modify Sanaei.
Grandoptical requires verified provider snapshots and independent console access.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import tempfile

HERE=Path(__file__).resolve().parent
STATE=Path('/var/lib/u-opti/smite-rc7-wss-runtime')
LOCK=Path('/run/lock/u-opti-smite-engine.lock')
OVERLAY='docker-compose.wss-rc7.yml'
EDGE=Path('/var/lib/u-opti/smite-rc7-wss-edge/record.json')
RC9_EDGE=Path('/var/lib/u-opti/smite-rc9-wss-edge/record.json')
RC9_ENROLLMENT=Path('/var/lib/u-opti/smite-rc9-frp-enrollment/record.json')
VERSION='RC7'
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
    spec=importlib.util.spec_from_file_location(Path(name).stem.replace('-', '_'),HERE/name)
    if spec is None or spec.loader is None:
        raise RuntimeError('REVIEWED_HELPER_UNAVAILABLE')
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name,None)
    return module
p=load('smite-rc7-wss-preflight.py')
Hold=p.Hold
need=p.need

def select_rc9():
    global VERSION, STATE, OVERLAY
    VERSION='RC9'
    STATE=Path('/var/lib/u-opti/smite-rc9-wss-runtime')
    OVERLAY='docker-compose.wss-rc9.yml'

def trusted_path(path, *, directory=False):
    for parent in reversed(path.parents):
        st=parent.lstat()
        need(stat.S_ISDIR(st.st_mode) and st.st_uid==0
             and not st.st_mode&0o022,'RC9_UNTRUSTED_PATH_PARENT')
    st=path.lstat()
    kind=stat.S_ISDIR if directory else stat.S_ISREG
    need(kind(st.st_mode) and st.st_uid==0 and not st.st_mode&0o022
         and (directory or st.st_nlink==1),'RC9_UNTRUSTED_PATH')
    return st

def rc9_signed_release():
    executable=shutil.which('cosign')
    need(executable is not None,'RC9_COSIGN_REQUIRED')
    path=Path(executable)
    trusted_path(path)
    with path.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    need(digest=='c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74',
         'RC9_COSIGN_DIGEST_MISMATCH')
    pairing=load('smite-node-pairing.py')
    try:
        pairing._require_unified_foreign_release()
    except pairing.WizardHold as exc:
        raise Hold('RC9_SIGNED_RELEASE_REQUIRED') from exc

def rc9_state(role):
    trusted_path(p.STATE)
    values=p.state(p.STATE)
    need(values.get('SMITE_ROLE')==('panel-iran' if role=='ir' else 'foreign')
         and values.get('SMITE_MANAGED_VERSION')=='2.0.0-rc.9'
         and values.get('SMITE_UPSTREAM_REF')=='e7f76185e9a7da51d7069d5d0a829dc192cc1e06'
         and values.get('SMITE_CONNECTION_MODE')=='standard',
         'RC9_RUNTIME_STATE_MISMATCH')
    return values

def rc9_service_gate(name,obj,doc):
    control=load('smite-managed-frp-control.py')
    image=control.RC9_PANEL_IMAGE if name=='smite-panel' else control.RC9_NODE_IMAGE
    config,host,state=obj['Config'],obj['HostConfig'],obj['State']
    image_id=obj.get('Image','')
    need(config.get('Image')==image and re.fullmatch(r'sha256:[0-9a-f]{64}',image_id)
         and image_id==doc['baseline'][name]['image_id']
         and image_id==p.run(['docker','image','inspect','-f','{{.Id}}',image]),
         'RC9_WSS_IMAGE_ID_DRIFT')
    need(state.get('Running') is True and state.get('Health',{}).get('Status')=='healthy',
         'SERVICE_NOT_HEALTHY')
    need(host.get('NetworkMode')=='host' and not host.get('PortBindings')
         and host.get('Privileged') is False,'NETWORK_PRIVILEGE_DRIFT')
    env=p.runtime_env(obj)
    domain=doc['domain']
    if name=='smite-panel':
        expected={'PANEL_DOMAIN':domain,'PANEL_HOST':'127.0.0.1',
                  'SMITE_PANEL_AGENT_AUTH_MODE':'signed',
                  'SMITE_ENGINE_MANAGEMENT_MODE':'managed'}
    else:
        expected={'PANEL_ADDRESS':domain+':443','SMITE_AGENT_AUTH_MODE':'strict',
                  'SMITE_NODE_PANEL_AUTH_MODE':'signed',
                  'SMITE_ENGINE_INVENTORY_MODE':'managed'}
        need(config.get('Cmd') in control.SAFE_NODE_COMMANDS,'NODE_API_NOT_LOOPBACK')
        required={'/etc/smite-node':(p.NODE/'config',True),
                  '/run/smite-node-identity':(Path('/etc/u-opti/smite/identities'),False),
                  '/var/lib/smite-node/auth':(Path('/var/lib/u-opti/smite-node-security/replay'),True)}
        if doc['role']=='foreign':
            expected.update(NODE_ROLE='foreign',SMITE_SANAEI_INVENTORY_ENABLED='true')
            required['/run/smite-sanaei-ro']=(Path('/opt/3x-ui/instances/01/db'),False)
        for target,(source,writable) in required.items():
            mounts=[item for item in obj.get('Mounts',[]) if item.get('Destination')==target]
            need(len(mounts)==1 and mounts[0].get('Type')=='bind'
                 and mounts[0].get('Source')==str(source)
                 and mounts[0].get('RW') is writable,'RC9_SIGNED_MOUNT_DRIFT')
    need(all(env.get(key)==value for key,value in expected.items()),
         'RC9_WSS_SIGNED_POLICY_DRIFT')

def run(args,timeout=150,input=None):
    need(not any(os.environ.get(key) for key in (
        'DOCKER_HOST','DOCKER_CONTEXT','DOCKER_CONFIG','DOCKER_TLS_VERIFY',
        'DOCKER_CERT_PATH','COMPOSE_FILE','COMPOSE_PROFILES','COMPOSE_ENV_FILES',
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

def archive_restored_journal(path):
    holding=Path(tempfile.mkdtemp(prefix=path.name+'-previous-',dir=path.parent))
    os.rename(path,holding/'journal')
    fsync_dir(holding)
    fsync_dir(path.parent)

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
    if VERSION=='RC9':
        need(stat.S_IMODE(trusted_path(STATE,directory=True).st_mode)==0o700,
             'UNTRUSTED_WSS_JOURNAL_DIRECTORY')
        trusted_path(path)
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
    if VERSION=='RC9':
        need(doc.get('version')==VERSION and rc9_state(doc['role']).get(
             'SMITE_PANEL_DOMAIN')==doc.get('domain'),'RC9_WSS_JOURNAL_SCOPE_DRIFT')
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
    if VERSION=='RC9':
        paths.add(str(p.STATE))
        if role=='ir':
            paths.add(str(p.PANEL/'panel/data/smite.db'))
    return sorted(paths)

def protected_receipt(paths):
    result={}
    for name in paths:
        path=Path(name)
        if VERSION=='RC9':
            trusted_path(path)
        need(path.is_file() and not path.is_symlink(),'PROTECTED_FILE_MISSING')
        st=path.stat()
        need(stat.S_ISREG(st.st_mode),'PROTECTED_FILE_UNSAFE')
        # Only root-owned configuration and identity are admitted.
        need(st.st_uid==0,'PROTECTED_FILE_OWNER_DRIFT')
        proof={'dev':st.st_dev,'inode':st.st_ino}
        if path.name=='agent-replay.sqlite3':
            proof['kind']='replay'
        elif VERSION=='RC9' and path.name=='smite.db':
            proof['kind']='sqlite'
        else:
            proof['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        result[name]=proof
    return result

def check_protected(doc):
    current=protected_receipt(doc['protected'].keys())
    need(current==doc['protected'],'PROTECTED_CONFIG_OR_IDENTITY_DRIFT')

DNS_EMPTY_FIELDS=('Dns','DnsOptions','DnsSearch')
DNS_EMPTY_POLICY='docker-dns-empty-v1'

def runtime_signature(obj, *, canonical_dns=False):
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
    if canonical_dns:
        # Moby Container.readHostConfig -> InitDNSHostConfig converts precisely
        # these three nil slices to empty slices on daemon reload. Missing keys
        # and nonempty values remain significant; no other HostConfig is ignored.
        for key in DNS_EMPTY_FIELDS:
            if key in norm and norm[key] is None:
                norm[key]=[]
    mounts=[{k:m.get(k) for k in ('Type','Source','Destination','RW')}
            for m in obj.get('Mounts',[])]
    return hashlib.sha256(json.dumps({
        'image':obj['Config']['Image'],
        'env':env,'command':obj['Config']['Cmd'],
        'entrypoint':obj['Config'].get('Entrypoint'),
        'host':norm,'mounts':sorted(mounts,key=lambda m:m['Destination'] or ''),
    },sort_keys=True,default=str).encode()).hexdigest()

def legacy_dns_proof(obj, signature):
    """Prove equality to the original digest; never bless a current digest.

    At most eight candidates, differing ONLY in present, empty DNS slices.
    A concurrent security change or an unknown field still prevents a match.
    """
    need(isinstance(signature,str) and re.fullmatch('[0-9a-f]{64}',signature),
         'INVALID_RUNTIME_SIGNATURE')
    host=obj['HostConfig']
    keys=[key for key in DNS_EMPTY_FIELDS
          if key in host and (host[key] is None or host[key]==[])]
    for values in itertools.product((None,[]),repeat=len(keys)):
        candidate=dict(obj)
        candidate['HostConfig']=dict(host,**dict(zip(keys,values)))
        if runtime_signature(candidate)==signature:
            return True
    return False

def check_runtime_signature(obj, baseline, *, allow_legacy_ir_dns_proof=False):
    policy=baseline.get('signature_policy')
    need(policy in (None,DNS_EMPTY_POLICY),'UNKNOWN_RUNTIME_SIGNATURE_POLICY')
    if policy==DNS_EMPTY_POLICY:
        valid=legacy_dns_proof(obj,baseline['signature'])
    else:
        valid=runtime_signature(obj)==baseline['signature']
        if not valid and allow_legacy_ir_dns_proof:
            # Trial-only IR compatibility for previously committed legacy
            # journals: prove the ORIGINAL digest with DNS empty-slice
            # permutations, not a freshly blessed runtime fingerprint.
            # Nonempty/missing DNS and every other HostConfig drift still HOLD.
            valid=legacy_dns_proof(obj,baseline['signature'])
    need(valid,'WSS_RUNTIME_SECURITY_DRIFT')

def signature_recovery(doc, *, commit=False, rollback=False):
    """Read-only proof or explicit, atomic policy opt-in/out; no Docker writes.

    Original signatures are retained byte-for-byte. Existing journals stay
    strict until the operator explicitly enables the bounded equivalence.
    No signed request, replay nonce, tunnel action or service restart is used.
    """
    need(doc['state']=='COMMITTED','WSS_RUNTIME_NOT_COMMITTED')
    need(not (STATE/'record.next').exists() and not (STATE/'record.next').is_symlink(),
         'PARTIAL_RECORD_NEEDS_REVIEW')
    check_protected(doc)
    candidate=json.loads(json.dumps(doc))
    for name in doc['services']:
        baseline=candidate['baseline'][name]
        need(baseline.get('signature_policy') in (None,DNS_EMPTY_POLICY),
             'UNKNOWN_RUNTIME_SIGNATURE_POLICY')
        baseline['signature_policy']=DNS_EMPTY_POLICY
        # Full existing image, health, signed-mode and Compose ownership gates.
        # The original digest is compared using only empty DNS alternatives.
        ensure_service(name,candidate,enabled=True)
    check_protected(doc)
    if rollback:
        for name in candidate['services']:
            candidate['baseline'][name].pop('signature_policy',None)
    if commit:
        atomic_record(candidate)
    print('RC7_WSS_SIGNATURE_'+('ROLLBACK' if rollback else 'RECOVERY')+
          ('=COMMITTED' if commit else '=PROVEN_READ_ONLY'))
    print('ORIGINAL_RUNTIME_SIGNATURES=RETAINED')
    print('SIGNED_REQUESTS_SENT=NO')
    print('CONTAINERS_RECREATED=NO')


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
    if VERSION=='RC9':
        rc9_service_gate(name,safe,doc)
    else:
        p.service_gate(name,safe,role=('panel-iran' if doc['role']=='ir' else 'foreign'),
                       domain=doc['domain'])
    project,files=p.compose_files(name,safe)
    need(project==doc['project'] and files==doc['baseline'][name]['files'],
         'WSS_COMPOSE_BASELINE_DRIFT')
    check_runtime_signature(obj,doc['baseline'][name],
                            allow_legacy_ir_dns_proof=(doc['role']=='ir' and
                                                       doc['state']=='COMMITTED'))
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

def compose_digest(config):
    return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()

def check_rc9_baseline_config(name,doc,effective):
    need(compose_digest(effective)==doc['baseline'][name]['compose_digest'],
         'RC9_EFFECTIVE_COMPOSE_DRIFT')

def check_rc9_compose(name,doc):
    check_protected(doc)
    base=compose(name,doc,False)
    effective=json.loads(run(base+['config','--format','json']))
    check_rc9_baseline_config(name,doc,effective)
    candidate=json.loads(run(compose(name,doc,True)+['config','--format','json']))
    p.only_wss_change(effective,candidate,name)

def no_tunnels():
    # A retained FRPC may still be forwarding even when no local FRPS binds.
    # Never disrupt an active forwarding process during activation/rollback.
    probe=subprocess.run(['pgrep','-x','frpc'],capture_output=True,text=True,
                         timeout=10,check=False)
    need(probe.returncode==1,'FRPC_PROCESS_PRESENT_OR_UNKNOWN')
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
    print(VERSION+'_WSS_RUNTIME_VERIFY=PASS_SIGNED_REPLAY')
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
    if VERSION=='RC9':
        control=load('smite-managed-frp-control.py')
        values=rc9_state(role)
        if role=='ir':
            need(peer_ip is not None,'PEER_IPV4_REQUIRED')
        try:
            readiness=control.rc9_readiness(p.NODE,state_path=p.STATE,run=run)
            control._rc9_wss_compose_plan(p.NODE,readiness['ROLE'],state_path=p.STATE,
                                          peer_ip=peer_ip,run=run)
        except (control.Hold,control.frp.shared.Hold) as exc:
            raise Hold('RC9_WSS_BASELINE_REVIEW_FAILED') from exc
        signed_probe()
        if role=='ir':
            panel_probe(values['SMITE_PANEL_DOMAIN'])
    else:
        p.inspect(role,peer_ip)  # all existing real-host checks, read-only
        values=p.state()
    no_tunnels()
    if VERSION=='RC9':
        trusted_path(STATE.parent,directory=True)
        if os.path.lexists(STATE):
            prior=record()
            need(prior['state']=='ROLLED_BACK' and prior['role']==role,
                 'WSS_RUNTIME_JOURNAL_EXISTS')
            need(not os.path.lexists(STATE/'record.next'),'PARTIAL_RECORD_NEEDS_REVIEW')
    else:
        need(not os.path.lexists(STATE),'WSS_RUNTIME_JOURNAL_EXISTS')
    names=['smite-panel','smite-node'] if role=='ir' else ['smite-node']
    domain=values['SMITE_PANEL_DOMAIN']
    baseline={}
    owner=None
    for name in names:
        obj=inspect_container(name)
        project,files=p.compose_files(name,obj)
        need(owner is None or project==owner,'PANEL_NODE_OWNER_MISMATCH')
        owner=project
        need(not overlay_path(name).exists() and not overlay_path(name).is_symlink(),
             'WSS_RC7_OVERLAY_ALREADY_EXISTS')
        baseline[name]={'files':files,
                        'signature':runtime_signature(obj,canonical_dns=True),
                        'signature_policy':DNS_EMPTY_POLICY}
        if VERSION=='RC9':
            args=['docker','compose','--project-name',project]
            for path in files:
                args+=['-f',path]
            before=json.loads(run(args+['config','--format','json']))
            after=json.loads(run(args+['-f','-','config','--format','json'],
                                 input=p.overlay_bytes(name)))
            p.only_wss_change(before,after,name)
            service=before['services'][name]
            # RC9 retains the upstream Compose build block alongside its
            # pinned image. Lifecycle calls explicitly disable build/pull.
            need(service.get('image')==obj['Config']['Image']
                 and service.get('network_mode')=='host'
                 and not service.get('ports'),
                 'RC9_EFFECTIVE_COMPOSE_SERVICE_DRIFT')
            baseline[name].update(image_id=obj['Image'],compose_digest=compose_digest(before))
    doc={'schema':1,'role':role,'state':'PREPARED','domain':domain,
            'peer':peer_ip if role=='ir' else None,'project':owner,
            'services':names,'baseline':baseline,
            'protected':protected_receipt(protected_paths(role))}
    if VERSION=='RC9':
        doc.update(version=VERSION)
        for name in names:
            ensure_service(name,doc,enabled=False)
    return doc

def apply(role,peer):
    with locked():
        if VERSION=='RC9':
            rc9_signed_release()
        doc=planned(role,peer)
        if VERSION=='RC9' and os.path.lexists(STATE):
            archive_restored_journal(STATE)
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
                if VERSION=='RC9':
                    check_rc9_compose(name,doc)
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
            print(VERSION+'_WSS_RUNTIME_APPLY=PASS_SIGNED')
            print('FRPS_STARTED=NO')
            print('SANAEI_CONTAINER_CHANGED=NO')
        except Exception:
            # Never conceal a partial transition. Recovery is explicitly
            # operator-gated and must preserve the protected files.
            doc['state']='HOLD'
            atomic_record(doc)
            if VERSION=='RC9':
                try:
                    restore(doc)
                except Exception as exc:
                    raise Hold('WSS_APPLY_HOLD_REVIEW_BEFORE_RECOVER') from exc
                raise Hold('RC9_WSS_APPLY_FAILED_STAGE_ROLLED_BACK')
            raise Hold('WSS_APPLY_HOLD_REVIEW_BEFORE_RECOVER')

def edge_absent():
    # Never remove WSS runtime while its public IR edge exists, even when
    # an edge journal is absent, damaged or was created outside this helper.
    alternate=Path('/etc/nginx/conf.d/u-opti-smite-panel-kh-wss.conf')
    need(not alternate.exists() and not alternate.is_symlink(),
         'ROLLBACK_EDGE_FIRST')
    paths=(EDGE,RC9_EDGE) if VERSION=='RC9' else (EDGE,)
    for path in paths:
        if os.path.lexists(path):
            if VERSION=='RC9':
                trusted_path(path)
            data=json.loads(path.read_text())
            need(data.get('state')=='ROLLED_BACK','ROLLBACK_EDGE_FIRST')

def restore(doc):
    edge_absent()
    if VERSION=='RC9' and os.path.lexists(RC9_ENROLLMENT):
        trusted_path(RC9_ENROLLMENT)
        need(json.loads(RC9_ENROLLMENT.read_text()).get('state')=='ROLLED_BACK',
             'ROLLBACK_FRP_ENROLLMENT_FIRST')
    no_tunnels()
    check_protected(doc)
    # Check every container and overlay before any mutation.
    recreate=[]
    for name in doc['services']:
        env=p.runtime_env(inspect_container(name))
        active=env.get('SMITE_FRP_STANDARD_WSS')=='1'
        ensure_service(name,doc,enabled=active,healthy=False)
        path=overlay_path(name)
        if path.exists() or path.is_symlink():
            need(path.is_file() and not path.is_symlink()
                 and path.read_bytes()==p.overlay_bytes(name).encode(),
                 'WSS_OVERLAY_CONTENT_DRIFT')
        if VERSION=='RC9':
            if active or inspect_container(name)['State'].get('Running') is not True:
                recreate.append(name)
            base=compose(name,doc,False)
            effective=json.loads(run(base+['config','--format','json']))
            check_rc9_baseline_config(name,doc,effective)
        else:
            recreate.append(name)
    doc['state']='ROLLING_BACK';atomic_record(doc)
    for name in reversed(recreate):
        if VERSION=='RC9':
            check_protected(doc)
            base=compose(name,doc,False)
            effective=json.loads(run(base+['config','--format','json']))
            check_rc9_baseline_config(name,doc,effective)
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
    if VERSION=='RC9':
        for name in doc['services']:
            ensure_service(name,doc,enabled=False)
        signed_probe()
    if doc['role']=='ir':panel_probe(doc['domain'])
    for name in doc['services']:
        path=overlay_path(name)
        if path.is_file():
            path.unlink()
            fsync_dir(path.parent)
    doc['state']='ROLLED_BACK';atomic_record(doc)
    print(VERSION+'_WSS_RUNTIME_ROLLBACK=PASS')
    print('IDENTITY_REPLAY_RETAINED=YES')

def recovery_console():
    """Require a foreground Linux console, not an SSH/PTY assertion."""
    need(not any(os.environ.get(k) for k in ('SSH_CONNECTION','SSH_CLIENT','SSH_TTY')),
         'DIRECT_RECOVERY_CONSOLE_REQUIRED')
    need(sys.stdin.isatty() and sys.stdout.isatty(),
         'DIRECT_RECOVERY_CONSOLE_REQUIRED')
    for stream in (sys.stdin,sys.stdout):
        fd=stream.fileno()
        name=os.ttyname(fd)
        need(re.fullmatch(r'/dev/(?:tty[1-9][0-9]*|ttyS[0-9]+|hvc[0-9]+|ttyAMA[0-9]+)',name)
             is not None and os.tcgetpgrp(fd)==os.getpgrp(),
             'DIRECT_RECOVERY_CONSOLE_REQUIRED')
    need(os.fstat(sys.stdin.fileno()).st_rdev==os.fstat(sys.stdout.fileno()).st_rdev,
         'DIRECT_RECOVERY_CONSOLE_REQUIRED')

def backup_bytes(path):
    # Resolve every component using directory FDs: no symlink traversal, even
    # through a parent. Do not extract archives or execute backup contents.
    target=Path(path)
    need(target.is_absolute() and '..' not in target.parts,'INVALID_BACKUP_PATH')
    directory=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in target.parts[1:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
            os.close(directory); directory=child
            st=os.fstat(directory)
            need(st.st_uid==0 and (not st.st_mode & 0o022 or st.st_mode & stat.S_ISVTX),
                 'UNTRUSTED_BACKUP_DIRECTORY')
        fd=os.open(target.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        with os.fdopen(fd,'rb') as stream:
            st=os.fstat(stream.fileno())
            need(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1
                 and stat.S_IMODE(st.st_mode)==0o600 and 0<st.st_size<=1048576,
                 'UNTRUSTED_RECOVERY_BACKUP')
            live=(STATE/'record.json').stat()
            need((st.st_dev,st.st_ino)!=(live.st_dev,live.st_ino),'BACKUP_IS_LIVE_JOURNAL')
            raw=stream.read(1048577)
            need(len(raw)==st.st_size,'RECOVERY_BACKUP_CHANGED')
            return raw
    finally:
        os.close(directory)

def unique_object(pairs):
    result={}
    for key,value in pairs:
        need(key not in result,'DUPLICATE_BACKUP_JSON_KEY')
        result[key]=value
    return result

def backup_recovery_proof(path, digest, doc):
    """Validate a restored original journal against an OFF-HOST digest.

    This proves bytes and a journal-only restore, not remote custody or whole
    host restoration. The operator separately attests independent custody.
    """
    need(re.fullmatch('[0-9a-f]{64}',digest or '') is not None,
         'INDEPENDENT_BACKUP_SHA256_REQUIRED')
    raw=backup_bytes(path)
    need(hashlib.sha256(raw).hexdigest()==digest,'RECOVERY_BACKUP_HASH_MISMATCH')
    original=json.loads(raw,object_pairs_hook=unique_object)
    expected=json.loads(json.dumps(doc))
    need(expected.get('state')=='COMMITTED','WSS_RUNTIME_NOT_COMMITTED')
    for name in expected['services']:
        baseline=expected['baseline'][name]
        need(baseline.get('signature_policy') in (None,DNS_EMPTY_POLICY),
             'UNKNOWN_RUNTIME_SIGNATURE_POLICY')
        baseline.pop('signature_policy',None)
    # Exact original document: includes role, project, protected receipts,
    # services and ORIGINAL fingerprints. No replacement/current-only backup.
    need(json.dumps(original,sort_keys=True)==json.dumps(expected,sort_keys=True),
         'BACKUP_NOT_ORIGINAL_WSS_JOURNAL')
    with tempfile.TemporaryDirectory(prefix='uopti-wss-restore-') as temp:
        restored=Path(temp)/'record.json'
        atomic_new(restored,raw)
        st=restored.stat()
        need(st.st_uid==0 and stat.S_IMODE(st.st_mode)==0o600
             and restored.read_bytes()==raw,'BACKUP_RESTORE_DRILL_FAILED')
        need(json.loads(restored.read_bytes(),object_pairs_hook=unique_object)==expected,
             'BACKUP_RESTORE_DRILL_FAILED')
    print('ORIGINAL_WSS_BACKUP_INTEGRITY=PASS')
    print('JOURNAL_ONLY_RESTORE_DRILL=PASS')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=('plan','apply','verify','rollback','recover',
                                          'signature-check','signature-recover',
                                          'signature-rollback'))
    ap.add_argument('--role',choices=('ir','foreign'),required=True)
    ap.add_argument('--rc9',action='store_true',help='Select the exact RC9 runtime and journal')
    ap.add_argument('--peer-ip')
    ap.add_argument('--snapshot-confirm',default='')
    ap.add_argument('--recovery-backup',help='Original WSS journal restored from independent backup')
    ap.add_argument('--backup-sha256',help='SHA-256 retained and obtained OFF HOST')
    args=ap.parse_args()
    try:
        need(os.geteuid()==0,'ROOT_REQUIRED')
        if args.rc9:
            need(not args.action.startswith('signature-'),'RC9_SIGNATURE_REPAIR_UNSUPPORTED')
            need(args.peer_ip is None or (args.role=='ir' and
                 args.action in ('plan','apply','verify')),'PEER_IP_ONLY_FOR_IR_WSS')
            select_rc9()
        backup_mode=args.recovery_backup is not None or args.backup_sha256 is not None
        if backup_mode:
            need(args.action in ('signature-recover','signature-rollback'),
                 'BACKUP_ALTERNATIVE_SIGNATURE_ONLY')
            need(args.recovery_backup and args.backup_sha256 and not args.snapshot_confirm,
                 'RECOVERY_PROOF_MODE_AMBIGUOUS_OR_INCOMPLETE')
            recovery_console()
        if not backup_mode and args.action not in ('verify','plan','signature-check'):
            need(sys.stdin.isatty() and args.snapshot_confirm=='SNAPSHOTS-CONSOLES-VERIFIED',
                 'PROVIDER_SNAPSHOT_AND_CONSOLE_REQUIRED')
            challenge=args.action.upper()+'-'+VERSION+'-WSS-'+args.role.upper()
            need(input('Type '+challenge+': ').strip()==challenge,'OPERATOR_CANCELLED')
        if args.action=='plan':
            with locked():
                planned(args.role,args.peer_ip)
            print(VERSION+'_WSS_RUNTIME_PLAN=PASS_READ_ONLY')
            print('LIVE_CHANGES=NONE')
        elif args.action=='apply':
            apply(args.role,args.peer_ip)
        else:
            with locked():
                doc=record()
                need(doc['role']==args.role,'WSS_ROLE_MISMATCH')
                if args.rc9 and args.peer_ip is not None:
                    need(args.peer_ip==doc['peer'],'PEER_MISMATCH')
                if backup_mode:
                    backup_recovery_proof(args.recovery_backup,args.backup_sha256,doc)
                    # Prove the entire runtime before requesting final consent.
                    signature_recovery(doc)
                    recovery_console()
                    challenge='OFF-HOST-RESTORE-VERIFIED '+args.backup_sha256
                    need(input('Confirm independent backup custody; type '+challenge+': ').strip()
                         ==challenge,'INDEPENDENT_BACKUP_NOT_CONFIRMED')
                    challenge=args.action.upper()+'-RC7-WSS-'+args.role.upper()
                    need(input('Type '+challenge+': ').strip()==challenge,'OPERATOR_CANCELLED')
                    # Consent may take time: do not commit using a removed or
                    # changed local restore copy, or a detached console.
                    recovery_console()
                    backup_recovery_proof(args.recovery_backup,args.backup_sha256,doc)
                if args.action.startswith('signature-'):
                    signature_recovery(doc,commit=args.action!='signature-check',
                                       rollback=args.action=='signature-rollback')
                elif args.action=='verify':
                    verify(doc)
                elif args.action=='rollback':
                    need(doc['state']=='COMMITTED','USE_RECOVER_FOR_INCOMPLETE_TRANSACTION')
                    restore(doc)
                else:
                    need(doc['state'] in ('PREPARED','APPLYING','HOLD','ROLLING_BACK'),
                         'RECOVERY_STATE_NOT_ALLOWED')
                    restore(doc)
        return 0
    except (Hold,OSError,ValueError,KeyError,TypeError,AttributeError,
            sqlite3.Error,EOFError,subprocess.SubprocessError) as exc:
        msg=str(exc)
        print('HOLD: '+(msg if re.fullmatch('[A-Z0-9_]{1,100}',msg)
                         else 'UNTRUSTED_WSS_RUNTIME_STATE'),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
