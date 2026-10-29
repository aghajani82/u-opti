#!/usr/bin/env python3
"""Journaled WSS opt-in for reviewed Stage15 FRP images on disposable IR/KH.

The engine must already be enrolled. No owner, child, route, firewall or tunnel
is created. Preserve every admitted Compose file, identity and Replay inode.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

HERE = Path(__file__).resolve().parent

def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module);return module

host=load('stage15_wss_host','smite-stage15-frp-host-executor.py')
need=host.require
Hold=host.Hold
run=host.run
# Filled only after independent image/transport CI and artifact verification.
REVIEWED_IMAGES = {'panel': 'sha256:e2345c7a4bf17cd9507ecf065cc736f4c2abfbe276a8c334805f4e52bb3808b5', 'node': 'sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265'}
# Smite 6981bd91, run 40830661751, artifact 12878322384; independently
# verified archive hashes, OCI hash chain, real TLS/token rejection and replay CI.
STATE=Path('/var/lib/u-opti/smite-stage15-wss')
LOCK=Path('/run/lock/u-opti-smite-engine.lock')
NODE=Path('/opt/smite-node')
PANEL=Path('/opt/smite')


def environment(obj):
    raw=obj['Config']['Env']; result={}
    for line in raw:
        key,value=line.split('=',1)
        need(key not in result,'DUPLICATE_RUNTIME_ENV');result[key]=value
    return result


def domain(value):
    need(isinstance(value,str) and len(value)<=253 and '.' in value and all(
        re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in value.split('.')),
        'INVALID_PANEL_DOMAIN')
    return value


def service_files(role,enrolled=True):
    if role=='node':return [NODE/'docker-compose.yml',NODE/'docker-compose.security-candidate.yml']+([NODE/'docker-compose.frp-stage15.yml'] if enrolled else [])
    return [PANEL/'docker-compose.yml',PANEL/'docker-compose.signed-control.yml']


def overlay(role):return (NODE if role=='node' else PANEL)/'docker-compose.wss-stage15.yml'

def overlay_bytes(role):
    return ('services:\n  smite-'+role+':\n    environment:\n      SMITE_FRP_STANDARD_WSS: "1"\n').encode()


def compose(role, enabled, args):
    cmd=['docker','compose']
    for p in service_files(role)+([overlay(role)] if enabled else []):cmd+=['-f',str(p)]
    return cmd+args


def inspect(role):
    data=json.loads(run(['docker','inspect','smite-'+role]))
    need(isinstance(data,list) and len(data)==1,'UNTRUSTED_CONTAINER_INSPECT')
    return data[0]


def runtime(role,obj,enabled,healthy=True,*,enrolled=True,allowed_images=None):
    need(obj['Image'] in (allowed_images if allowed_images is not None else {REVIEWED_IMAGES[role]}), 'UNREVIEWED_WSS_IMAGE')
    need(obj['Config']['Image']=='smite-'+role+':stage15-local','UNREVIEWED_IMAGE_REFERENCE')
    need(obj['HostConfig']['NetworkMode']=='host' and not obj['HostConfig'].get('PortBindings')
         and obj['HostConfig'].get('Privileged') is False,'UNSAFE_RUNTIME_NETWORK')
    if healthy:need(obj['State']['Running'] and obj['State'].get('Health',{}).get('Status')=='healthy','SERVICE_NOT_HEALTHY')
    env=environment(obj)
    keys={'SMITE_AGENT_AUTH_MODE':'strict','SMITE_NODE_PANEL_AUTH_MODE':'signed','SMITE_ENGINE_INVENTORY_MODE':'managed'} if role=='node' else {'SMITE_PANEL_AGENT_AUTH_MODE':'signed','SMITE_ENGINE_MANAGEMENT_MODE':'managed'}
    need(all(env.get(k)==v for k,v in keys.items()),'SIGNED_POLICY_DRIFT')
    need(env.get('SMITE_FRP_STANDARD_WSS')=='1' if enabled else 'SMITE_FRP_STANDARD_WSS' not in env,'WSS_POLICY_DRIFT')
    labels=obj['Config'].get('Labels') or {}
    files=labels.get('com.docker.compose.project.config_files','').split(',')
    wanted=[str(p) for p in service_files(role,enrolled)+([overlay(role)] if enabled else [])]
    need(files==wanted,'COMPOSE_ORDER_OR_FILES_DRIFT')
    mounts=obj['Mounts'];bydest={m['Destination']:m for m in mounts}
    need(len(bydest)==len(mounts),'DUPLICATE_RUNTIME_MOUNT')
    if role=='node':
        need(obj['Config']['Cmd']==['uvicorn','main:app','--host','127.0.0.1','--port','8888'],'NODE_API_NOT_LOOPBACK')
        need(env.get('SMITE_AGENT_IDENTITY_PATH')=='/run/smite-node-identity/node-identity.json'
             and env.get('SMITE_AGENT_REPLAY_DB')=='/var/lib/smite-node/auth/agent-replay.sqlite3','IDENTITY_PATH_DRIFT')
        address=env.get('PANEL_ADDRESS','');need(address.endswith(':443'),'PANEL_NOT_443');dns=domain(address[:-4])
        required={
            '/etc/smite-node':(str(NODE/'config'),True),
            '/run/smite-node-identity':('/etc/u-opti/smite/identities',False),
            '/var/lib/smite-node/auth':('/var/lib/u-opti/smite-node-security/replay',True),
            '/usr/local/bin/frpc':(str(host.Paths().binaries/'frpc'),False),
            '/usr/local/bin/frps':(str(host.Paths().binaries/'frps'),False),
        }
    else:
        need(env.get('PANEL_HOST')=='127.0.0.1' and env.get('DB_PATH') in ('./data/smite.db','/app/data/smite.db'),'PANEL_BIND_OR_DB_PATH_DRIFT')
        dns=domain(env.get('PANEL_DOMAIN',''))
        required={'/app/data':(str(PANEL/'panel/data'),True),'/etc/smite-panel/trusted-nodes':('/etc/u-opti/smite/panel-trusted-nodes',False)}
    if role=='node' and not enrolled:
        required.pop('/usr/local/bin/frpc');required.pop('/usr/local/bin/frps')
        need(not any(p in bydest for p in ('/usr/local/bin/frpc','/usr/local/bin/frps')),'UNEXPECTED_ENGINE_MOUNTS')
    for dest,(source,rw) in required.items():
        m=bydest.get(dest,{})
        need(m.get('Source')==source and m.get('RW') is rw and m.get('Type')=='bind','SECURITY_MOUNT_DRIFT')
    return dns


def signature(obj):
    """Changes beyond WSS/Compose labels are rejected, including extra mounts."""
    env=environment(obj);env.pop('SMITE_FRP_STANDARD_WSS',None)
    return {'image':obj['Image'],'env':env,'mounts':sorted(obj['Mounts'],key=lambda m:m['Destination']),
            'command':obj['Config']['Cmd'],'host':obj['HostConfig']}


def no_tunnels():
    path=NODE/'config/tunnels.json'
    if path.exists() or path.is_symlink():
        need(json.loads(host.file(path,limit=1048576))=={},'REMOVE_TUNNELS_BEFORE_WSS_CHANGE')
    need(not run(['ss','-H','-lnt','( sport = :7000 )']).strip(),'FRPS_OWNER_STILL_RUNNING')
    # An Owner can use a non-default control port. Detect any host-network
    # frps listener as well; the 7000 check remains a fail-closed fallback.
    need(not re.search(r'(?<![A-Za-z0-9_])frps(?![A-Za-z0-9_])',
                       run(['ss','-H','-lntp'])),'FRPS_OWNER_STILL_RUNNING')


def protected(roles,enrolled=True):
    result={}
    for role in roles:
        for p in service_files(role,enrolled)+[(NODE if role=='node' else PANEL)/'.env']:
            result[str(p)]={'sha':host.digest(host.file(p))}
    p=host.Paths()
    for path in (p.identity,p.replay):
        host.file(path,limit=80*1024*1024,mode=0o600);st=path.lstat()
        result[str(path)]={'inode':[st.st_dev,st.st_ino]}
        if path==p.identity:result[str(path)]['sha']=host.digest(host.file(path,mode=0o600))
    if enrolled:result[str(p.manifest)]={'sha':host.digest(host.file(p.manifest,mode=0o600))}
    return result


def write_atomic(path,data):
    host.trusted_parents(path)
    tmp=path.with_name(path.name+'.next')
    need(not tmp.exists() and not tmp.is_symlink(),'UNRESOLVED_TEMP_FILE')
    host.new_file(tmp,data,0o600);os.replace(tmp,path);host.flush(path.parent)


def discard_partial(path, expected):
    temp=path.with_name(path.name+'.next')
    if temp.exists() or temp.is_symlink():
        raw=host.file(temp,mode=0o600,limit=262144)
        need(any(value.startswith(raw) for value in expected),'UNRECOGNIZED_PARTIAL_WRITE')
        temp.unlink();host.flush(temp.parent)


def discard_record_partial(doc):
    candidates=[(json.dumps(dict(doc,state=state),sort_keys=True)+'\n').encode()
                for state in ('PREPARED','COMMITTED','RECOVERING','ROLLED_BACK')]
    discard_partial(STATE/'record.json',candidates)


def save(doc):write_atomic(STATE/'record.json',(json.dumps(doc,sort_keys=True)+'\n').encode())


def read_record():
    host.directory(STATE,private=True)
    doc=json.loads(host.file(STATE/'record.json',mode=0o600,limit=262144))
    need(doc.get('schema')==1 and doc.get('roles') in (['node'],['panel','node'])
         and doc.get('state') in ('PREPARED','COMMITTED','RECOVERING','ROLLED_BACK'),'INVALID_WSS_JOURNAL')
    need(protected(doc['roles'])==doc['protected'],'PROTECTED_STATE_DRIFT')
    return doc


def health(doc,enabled):
    for role in doc['roles']:
        for attempt in range(20):
            try:
                obj=inspect(role);runtime(role,obj,enabled)
                need(signature(obj)==doc['runtime'][role],'RUNTIME_SECURITY_DRIFT');break
            except Hold:
                if attempt==19:raise
                time.sleep(3)
    host.signed_inventory('ready')
    if 'panel' in doc['roles']:
        dns=doc['domain']
        run(['curl','--noproxy','*','--fail','--silent','--max-time','12','--resolve',dns+':443:127.0.0.1',
             '--output','/dev/null','https://'+dns+'/'],timeout=18)


def plan(role):
    roles=['panel','node'] if role=='IR' else ['node']
    need(not STATE.exists() and not STATE.is_symlink(),'EXISTING_WSS_JOURNAL')
    p=host.Paths();engine=host.receipt(p)
    need(engine['state']=='COMMITTED','FRP_ENGINE_NOT_COMMITTED')
    host.ensure_protected(p,engine['protected']);host.verify_artifacts(p,engine,complete=True)
    host.runtime(p,True);host.signed_inventory('ready')
    no_tunnels()
    doc={'schema':1,'state':'PREPARED','roles':roles,'runtime':{},'protected':protected(roles)}
    for component in roles:
        need(not overlay(component).exists() and not overlay(component).is_symlink(),'EXISTING_WSS_OVERLAY')
        obj=inspect(component);dns=runtime(component,obj,False)
        if 'domain' in doc:need(doc['domain']==dns,'PANEL_NODE_DOMAIN_MISMATCH')
        doc['domain']=dns;doc['runtime'][component]=signature(obj)
        need(run(['docker','image','inspect','smite-'+component+':stage15-local','--format','{{.Id}}'])==obj['Image'],'LOCAL_TAG_DRIFT')
        # Resolve an in-memory candidate before making any changes.
        before=json.loads(run(compose(component,False,['config','--format','json'])))
        after=json.loads(run(compose(component,False,['-f','-','config','--format','json']),input=overlay_bytes(component).decode()))
        service='smite-'+component
        need(after['services'][service]['environment'].pop('SMITE_FRP_STANDARD_WSS',None)=='1','WSS_OVERLAY_NOT_EFFECTIVE')
        need(before==after,'UNEXPECTED_COMPOSE_CHANGE')
    return doc


def backup_panel(destination=None):
    db=PANEL/'panel/data/smite.db';host.file(db,limit=256*1024*1024)
    path=destination if destination is not None else STATE/'panel.before.sqlite3';host.new_file(path,b'',0o600)
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as source:
        with sqlite3.connect(path) as target:
            source.backup(target)
            need(target.execute('PRAGMA integrity_check').fetchone()[0]=='ok','BACKUP_INTEGRITY_FAILED')
    with path.open('rb') as f:os.fsync(f.fileno())
    host.flush(path.parent)


def restore(doc):
    no_tunnels()
    edge_record=Path('/var/lib/u-opti/smite-stage15-wss-edge/record.json')
    if edge_record.exists() or edge_record.is_symlink():
        need(json.loads(host.file(edge_record,mode=0o600))['state']=='ROLLED_BACK','ROLLBACK_EDGE_FIRST')
    need(protected(doc['roles'])==doc['protected'],'PROTECTED_STATE_DRIFT')
    # Check every service before mutating any of them; stopped services are recoverable.
    for role in doc['roles']:
        current=inspect(role)
        enabled=environment(current).get('SMITE_FRP_STANDARD_WSS')=='1'
        runtime(role,current,enabled,healthy=False)
        need(signature(current)==doc['runtime'][role],'RECOVERY_SECURITY_DRIFT')
        need(run(['docker','image','inspect','smite-'+role+':stage15-local','--format','{{.Id}}'])==current['Image'],'ROLLBACK_TAG_DRIFT')
        if overlay(role).exists() or overlay(role).is_symlink():
            need(host.file(overlay(role),mode=0o600)==overlay_bytes(role),'WSS_OVERLAY_DRIFT')
    discard_record_partial(doc)
    for role in doc['roles']:discard_partial(overlay(role),[overlay_bytes(role)])
    doc['state']='RECOVERING';save(doc)
    for role in reversed(doc['roles']):
        run(compose(role,False,['up','-d','--no-build','--no-deps','--pull','never','--force-recreate','smite-'+role]),timeout=150)
    health(doc,False)
    for role in doc['roles']:
        if overlay(role).exists():overlay(role).unlink();host.flush(overlay(role).parent)
    doc['state']='ROLLED_BACK';save(doc)
    # Retain receipt and private SQLite backup. Never overwrite the live DB.


def apply(role):
    with host.exclusive(LOCK):
        doc=plan(role)
        host.new_dir(STATE);save(doc)
        try:
            if role=='IR':backup_panel()
            for component in doc['roles']:
                write_atomic(overlay(component),overlay_bytes(component))
                run(compose(component,True,['up','-d','--no-build','--no-deps','--pull','never','--force-recreate','smite-'+component]),timeout=150)
            health(doc,True)
            need(protected(doc['roles'])==doc['protected'],'PROTECTED_STATE_DRIFT')
            doc['state']='COMMITTED';save(doc)
        except Exception:
            restore(doc);raise Hold('WSS_ACTIVATION_ROLLED_BACK')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['plan','apply','verify','rollback','recover'])
    args=ap.parse_args()
    try:
        role=os.uname().nodename.split('.')[0].upper()
        need(os.geteuid()==0 and role in ('IR','KH'),'DISPOSABLE_IR_KH_ROOT_ONLY')
        if args.action in ('apply','rollback','recover'):
            need(sys.stdin.isatty(),'INTERACTIVE_CONFIRMATION_REQUIRED')
            challenge=args.action.upper()+'-WSS-'+role+'-SNAPSHOT-CONSOLE'
            need(input('Type '+challenge+': ').strip()==challenge,'OPERATOR_CANCELLED')
        if args.action=='plan':
            with host.exclusive(LOCK):plan(role)
        elif args.action=='apply':apply(role)
        else:
            with host.exclusive(LOCK):
                doc=read_record()
                if args.action=='verify':
                    need(doc['state']=='COMMITTED','WSS_NOT_COMMITTED');health(doc,True)
                else:restore(doc)
        print('STAGE15_WSS_'+args.action.upper()+'=PASS')
        print('TUNNEL_CREATED=NO')
        return 0
    except (Hold,OSError,ValueError,KeyError,TypeError) as exc:
        msg=str(exc)
        print('HOLD: '+(msg if re.fullmatch('[A-Z0-9_]{1,100}',msg) else 'UNTRUSTED_WSS_STATE'),file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(main())
