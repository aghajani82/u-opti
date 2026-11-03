#!/usr/bin/env python3
"""Explicit RC7 enrollment of official FRP 0.71.0 already in pinned Node image.

This is NOT a generic host FRP installer: verified image-bundled frpc+frps
are enrolled into the Node's strict root-owned engine inventory, preserving
all other engine entries. No Docker recreate, binary download, Nginx reload,
Sanaei change, FRPS start, public listener, or tunnel is ever performed.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path('/opt/smite-node/config')
MANIFEST=ROOT/'engine-state/engines.json'
JOURNAL=Path('/var/lib/u-opti/smite-rc7-frp-enrollment')
BIN_LIMIT=48*1024*1024
ENGINES={'backhaul','frp','gost','rathole','chisel'}
DIGEST=re.compile('[0-9a-f]{64}\\Z')

def module(alias,name):
    s=importlib.util.spec_from_file_location(alias,HERE/name)
    if not s or not s.loader:raise RuntimeError('REQUIRED_RC7_HELPER_MISSING')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

p=module('rc7_frp_readonly','smite-rc7-wss-preflight.py')
rt=module('rc7_frp_runtime','smite-rc7-wss-runtime.py')
need=p.need
Hold=p.Hold

def sha(data):return hashlib.sha256(data).hexdigest()

def read_private(path,max_size=8192):
    need(not path.is_symlink() and path.is_file(),'UNSAFE_PRIVATE_FILE')
    st=path.lstat()
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0
         and st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o600
         and 0 < st.st_size<=max_size,'UNSAFE_PRIVATE_FILE')
    return path.read_bytes()

def json_private(path):
    try: data=json.loads(read_private(path))
    except (ValueError,UnicodeError) as exc:raise Hold('INVALID_PRIVATE_JSON') from exc
    need(isinstance(data,dict),'INVALID_PRIVATE_JSON')
    return data

def safe_dir(path):
    need(not path.is_symlink() and path.is_dir(),'UNSAFE_ENGINE_DIRECTORY')
    st=path.lstat()
    need(stat.S_ISDIR(st.st_mode) and st.st_uid==0
         and stat.S_IMODE(st.st_mode)==0o700,'UNSAFE_ENGINE_DIRECTORY')

def manifest_before():
    safe_dir(ROOT)
    folder=MANIFEST.parent
    if folder.exists() or folder.is_symlink():
        safe_dir(folder)
    if not MANIFEST.exists() and not MANIFEST.is_symlink():
        return None,{}
    content=read_private(MANIFEST)
    try:data=json.loads(content)
    except (ValueError,UnicodeError) as exc:raise Hold('INVALID_ENGINE_MANIFEST') from exc
    need(isinstance(data,dict) and set(data)=={'schema','engines'}
         and data['schema']==1 and isinstance(data['engines'],dict),
         'INVALID_ENGINE_MANIFEST')
    engines=data['engines']
    need(set(engines)<=ENGINES and 'frp' not in engines,
         'FRP_ALREADY_ENROLLED_OR_UNREVIEWED')
    for name,item in engines.items():
        need(isinstance(item,dict)
             and set(item)==({'sha256','server_sha256'} if name=='frp' else {'sha256'})
             and all(isinstance(v,str) and DIGEST.fullmatch(v) for v in item.values()),
             'OTHER_ENGINE_MANIFEST_INVALID')
    return content,engines

def node_details():
    doc=rt.record()
    need(doc['state']=='COMMITTED' and doc['role'] in ('ir','foreign'),
         'WSS_RUNTIME_NOT_COMMITTED')
    rt.check_protected(doc)
    rt.ensure_service('smite-node',doc,enabled=True)
    runtime=rt.inspect_container('smite-node')
    mounts=[m for m in runtime.get('Mounts',[]) if
            m.get('Destination')=='/etc/smite-node']
    need(len(mounts)==1 and mounts[0].get('Type')=='bind'
         and mounts[0].get('Source')==str(ROOT)
         and mounts[0].get('RW') is True,
         'NODE_CONFIG_MOUNT_NOT_REVIEWED')
    need(not any(m.get('Destination') in (
         '/usr/local/bin','/usr/local/bin/frpc','/usr/local/bin/frps') or
         str(m.get('Destination','')).startswith('/usr/local/bin/frp/')
         for m in runtime.get('Mounts',[])),
         'FRP_BINARY_EXTERNAL_MOUNT')
    return doc

BINARY_AUDIT=r"""
import hashlib,json,os,stat
from app.config import settings
from app.engine_inventory import engine_inventory
assert settings.smite_engine_inventory_mode=='managed'
assert settings.smite_engine_manifest_path=='/etc/smite-node/engine-state/engines.json'
assert engine_inventory()['engines']['frp']=='not-installed'
result={}
for name in ('frpc','frps'):
    path='/usr/local/bin/'+name
    meta=os.lstat(path)
    assert stat.S_ISREG(meta.st_mode) and meta.st_uid==0
    assert not(meta.st_mode&0o022) and meta.st_mode&0o111
    assert 0<meta.st_size<48*1024*1024
    result[name]=hashlib.sha256(open(path,'rb').read()).hexdigest()
print(json.dumps(result,sort_keys=True))
"""
SIGNED_INVENTORY=r"""
import json,secrets,urllib.request,urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id,secret=read_identity('/run/smite-node-identity/node-identity.json')
target='/api/agent/engines'
headers=sign_request(secret=secret,node_id=node_id,method='GET',target=target,
                     body=b'',nonce=secrets.token_hex(16))
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
request=urllib.request.Request('http://127.0.0.1:8888'+target,headers=headers)
with opener.open(request,timeout=6) as response:
    data=json.load(response)
    assert response.status==200
    assert data.get('mode')=='managed'
    assert data.get('engines',{}).get('frp')==__import__('sys').argv[1]
print('SIGNED_FRP_INVENTORY=PASS')
"""

def binaries():
    raw=p.run(['docker','exec','smite-node','python3','-B','-c',BINARY_AUDIT])
    try:digests=json.loads(raw)
    except (ValueError,UnicodeError) as exc:raise Hold('BINARY_AUDIT_INVALID') from exc
    need(isinstance(digests,dict) and set(digests)=={'frpc','frps'}
         and all(isinstance(v,str) and DIGEST.fullmatch(v) for v in digests.values()),
         'BINARY_AUDIT_INVALID')
    for name in ('frpc','frps'):
        need(p.run(['docker','exec','smite-node',name,'--version'])=='0.71.0',
             'OFFICIAL_FRP_VERSION_MISMATCH')
    return digests

def signed_inventory(expected):
    need(rt.run(['docker','exec','smite-node','python3','-B','-c',
                 SIGNED_INVENTORY,expected],timeout=30)=='SIGNED_FRP_INVENTORY=PASS',
         'SIGNED_ENGINE_INVENTORY_FAILED')

def proposal():
    need(not JOURNAL.exists() and not JOURNAL.is_symlink(),
         'FRP_ENROLLMENT_JOURNAL_EXISTS')
    doc=node_details()
    rt.no_tunnels()
    prior,engines=manifest_before()
    hashes=binaries()
    contents=(json.dumps({'schema':1,'engines':{
        **engines,'frp':{'sha256':hashes['frpc'],
                        'server_sha256':hashes['frps']}}},
        sort_keys=True,indent=2)+'\n').encode()
    return doc,prior,contents,hashes

def make_record(record):
    path=JOURNAL/'record.next'
    need(not path.exists() and not path.is_symlink(),'FRP_RECORD_PARTIAL')
    rt.atomic_new(path,(json.dumps(record,sort_keys=True)+'\n').encode())
    os.replace(path,JOURNAL/'record.json')
    rt.fsync_dir(JOURNAL)

def state():
    safe_dir(JOURNAL)
    record=json_private(JOURNAL/'record.json')
    need(record.get('schema')==1
         and record.get('role') in ('ir','foreign')
         and record.get('state') in (
             'PREPARED','APPLYING','COMMITTED','HOLD','ROLLING_BACK','ROLLED_BACK')
         and isinstance(record.get('new'),str) and DIGEST.fullmatch(record['new'])
         and (record.get('old') is None or
              isinstance(record.get('old'),str) and DIGEST.fullmatch(record['old']))
         and isinstance(record.get('binaries'),dict)
         and set(record['binaries'])=={'frpc','frps'}
         and all(isinstance(v,str) and DIGEST.fullmatch(v)
                 for v in record['binaries'].values()),
         'INVALID_FRP_JOURNAL')
    return record

def verify_file(record):
    need(sha(read_private(MANIFEST))==record['new'],'ENROLLMENT_MANIFEST_DRIFT')
    doc=node_details()
    need(doc['role']==record['role'],'WSS_ROLE_MISMATCH')
    current={}
    # After enrollment the *not-installed* binary audit intentionally fails.
    # Verify pinned image and raw binary digests independently here.
    source=r"""
import hashlib,json,os,stat
from app.config import settings
assert settings.smite_engine_manifest_path=='/etc/smite-node/engine-state/engines.json'
out={}
for n in ('frpc','frps'):
 p='/usr/local/bin/'+n;s=os.lstat(p)
 assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_mode&0o111 and not s.st_mode&0o022
 out[n]=hashlib.sha256(open(p,'rb').read()).hexdigest()
print(json.dumps(out,sort_keys=True))
"""
    try: current=json.loads(p.run(['docker','exec','smite-node','python3','-B','-c',source]))
    except (ValueError,UnicodeError) as exc:raise Hold('FRP_BINARY_DIGEST_UNAVAILABLE') from exc
    need(current==record['binaries'],'FRP_BINARY_DIGEST_DRIFT')
    return doc

def enrolled_status():
    data=p.run(['docker','exec','smite-node','python3','-B','-c',
                "from app.engine_inventory import engine_inventory; print(engine_inventory()['engines']['frp'])"])
    need(data=='ready','FRP_NOT_READY')
    signed_inventory('ready')

def apply():
    with rt.locked():
        doc,prior,contents,hashes=proposal()
        JOURNAL.mkdir(mode=0o700)
        rt.fsync_dir(JOURNAL.parent)
        if prior is not None:
            rt.atomic_new(JOURNAL/'manifest.before',prior)
        entry={'schema':1,'role':doc['role'],'state':'PREPARED',
               'old':sha(prior) if prior is not None else None,
               'new':sha(contents),'binaries':hashes}
        make_record(entry)
        try:
            if not MANIFEST.parent.exists():
                MANIFEST.parent.mkdir(mode=0o700)
                rt.fsync_dir(MANIFEST.parent.parent)
            else:safe_dir(MANIFEST.parent)
            need(not MANIFEST.exists() and not MANIFEST.is_symlink()
                 if prior is None else sha(read_private(MANIFEST))==entry['old'],
                 'ENGINE_MANIFEST_CHANGED')
            entry['state']='APPLYING';make_record(entry)
            temp=MANIFEST.with_name('engines.json.rc7-next')
            need(not temp.exists() and not temp.is_symlink(),'PARTIAL_MANIFEST_TEMP')
            rt.atomic_new(temp,contents)
            os.replace(temp,MANIFEST)
            rt.fsync_dir(MANIFEST.parent)
            verify_file(entry)
            rt.signed_probe()
            enrolled_status()
            entry['state']='COMMITTED';make_record(entry)
            print('RC7_FRP_ENROLLMENT=PASS_SIGNED')
            print('FRPS_STARTED=NO')
            print('NODE_RESTARTED=NO')
            print('SANAEI_CHANGED=NO')
        except Exception:
            entry['state']='HOLD';make_record(entry)
            raise Hold('FRP_ENROLLMENT_HOLD_REVIEW_RECOVERY')

def restore(entry):
    need(entry['state'] in ('COMMITTED','PREPARED','APPLYING','HOLD','ROLLING_BACK'),
         'FRP_ROLLBACK_STATE_INVALID')
    doc=node_details()
    need(doc['role']==entry['role'],'WSS_ROLE_MISMATCH')
    rt.no_tunnels()
    before=None
    if entry['old'] is not None:
        before=read_private(JOURNAL/'manifest.before')
        need(sha(before)==entry['old'],'MANIFEST_BACKUP_TAMPERED')
    current=read_private(MANIFEST) if MANIFEST.exists() or MANIFEST.is_symlink() else None
    need(current is None and entry['old'] is None or
         current is not None and sha(current) in {entry['old'],entry['new']},
         'MANIFEST_UNREVIEWED_CHANGE')
    if current is not None and sha(current)==entry['new']:
        verify_file(entry)
    entry['state']='ROLLING_BACK';make_record(entry)
    if before is None:
        if MANIFEST.exists():
            MANIFEST.unlink();rt.fsync_dir(MANIFEST.parent)
    elif current!=before:
        temp=MANIFEST.with_name('engines.json.rc7-rollback-next')
        need(not temp.exists() and not temp.is_symlink(),'ROLLBACK_TEMP_UNSAFE')
        rt.atomic_new(temp,before)
        os.replace(temp,MANIFEST);rt.fsync_dir(MANIFEST.parent)
    rt.signed_probe()
    signed_inventory('not-installed')
    entry['state']='ROLLED_BACK';make_record(entry)
    print('RC7_FRP_ENROLLMENT_ROLLBACK=PASS')
    print('NODE_RESTARTED=NO')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','apply','verify','rollback','recover'))
    parser.add_argument('--role',choices=('ir','foreign'),required=True)
    parser.add_argument('--snapshot-confirm',default='')
    args=parser.parse_args()
    try:
        need(os.geteuid()==0,'ROOT_REQUIRED')
        if args.action not in ('plan','verify'):
            need(sys.stdin.isatty() and args.snapshot_confirm=='SNAPSHOTS-CONSOLES-VERIFIED',
                 'SNAPSHOT_AND_CONSOLE_REQUIRED')
            challenge=args.action.upper()+'-RC7-FRP-'+args.role.upper()
            need(input('Type '+challenge+': ').strip()==challenge,'OPERATOR_CANCELLED')
        if args.action=='plan':
            with rt.locked():
                doc,_,_,_=proposal()
                need(doc['role']==args.role,'ROLE_MISMATCH')
            print('RC7_FRP_ENROLLMENT_PLAN=PASS_READ_ONLY')
            print('BINARIES=PINNED_RC7_IMAGE_FRP_0.71.0')
            print('NODE_RESTARTED=NO')
            print('LIVE_CHANGES=NONE')
        elif args.action=='apply':
            with rt.locked():
                need(rt.record()['role']==args.role,'ROLE_MISMATCH')
            apply()
        else:
            with rt.locked():
                entry=state()
                need(entry['role']==args.role,'ROLE_MISMATCH')
                if args.action=='verify':
                    need(entry['state']=='COMMITTED','ENROLLMENT_NOT_COMMITTED')
                    verify_file(entry);rt.signed_probe();enrolled_status()
                    print('RC7_FRP_ENROLLMENT_VERIFY=PASS_SIGNED')
                    print('LIVE_CONFIG_CHANGES=NONE')
                else:
                    need(args.action=='recover' or entry['state']=='COMMITTED',
                         'RECOVER_INCOMPLETE_FIRST')
                    restore(entry)
        return 0
    except (Hold,RuntimeError,ValueError,OSError,KeyError,TypeError) as exc:
        msg=str(exc)
        print('HOLD: '+(msg if re.fullmatch('[A-Z0-9_]{1,100}',msg)
                         else 'UNTRUSTED_FRP_ENROLLMENT_STATE'),file=sys.stderr)
        return 2

if __name__=='__main__': raise SystemExit(main())
