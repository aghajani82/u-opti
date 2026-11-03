#!/usr/bin/env python3
"""RC7 IR-only journaled source-IP/SNI-scoped FRP WSS/443 edge.

Does not start FRPS or publish an XHTTP route. Restricted to the pinned
Foreign peer and the existing IR TLS backend, with explicit rollback.
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
import time

HERE=Path(__file__).resolve().parent
STATE=Path('/var/lib/u-opti/smite-rc7-wss-edge')
RUNTIME=Path('/var/lib/u-opti/smite-rc7-wss-runtime/record.json')
LOCK=Path('/run/lock/u-opti-smite-engine.lock')

def load(alias,name):
    spec=importlib.util.spec_from_file_location(alias,HERE/name)
    if spec is None or spec.loader is None: raise RuntimeError('REQUIRED_HELPER_MISSING')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

p=load('rc7_wss_read_only','smite-rc7-wss-preflight.py')
q=load('rc7_wss_edge_renderer','smite-rc2-frp-wss-edge-plan.py')
rt=load('rc7_wss_runtime_controller','smite-rc7-wss-runtime.py')
Hold=p.Hold
need=p.need

def sha(data):
    return hashlib.sha256(data).hexdigest()

def file(path,mode=None):
    need(path.is_file() and not path.is_symlink(),'REQUIRED_FILE_UNSAFE')
    st=path.stat()
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1
         and not(stat.S_IMODE(st.st_mode)&0o022),
         'UNTRUSTED_FILE')
    if mode is not None: need(stat.S_IMODE(st.st_mode)==mode,'FILE_MODE_DRIFT')
    return path.read_bytes()

def write_new(path,contents,mode):
    rt.atomic_new(path,contents,mode)

def atomic_replace(path,contents,mode):
    temp=path.with_name(path.name+'.rc7-next')
    need(not temp.exists() and not temp.is_symlink(),'UNRECOGNIZED_TEMP_FILE')
    write_new(temp,contents,mode)
    os.replace(temp,path)
    rt.fsync_dir(path.parent)

def save(doc):
    temp=STATE/'record.next'
    need(not temp.exists() and not temp.is_symlink(),'PARTIAL_RECORD_NEEDS_REVIEW')
    write_new(temp,(json.dumps(doc,sort_keys=True)+'\n').encode(),0o600)
    os.replace(temp,STATE/'record.json')
    rt.fsync_dir(STATE)

def journal():
    doc=json.loads(file(STATE/'record.json',0o600))
    need(doc.get('schema')==1 and doc.get('state') in (
        'PREPARED','APPLYING','COMMITTED','HOLD','ROLLING_BACK','ROLLED_BACK'
    ) and re.fullmatch(r'[a-z0-9.-]{1,253}',doc.get('domain',''))
       and re.fullmatch(r'[0-9.]{7,15}',doc.get('peer','')),
       'INVALID_EDGE_JOURNAL')
    return doc

def expected_runtime(domain,peer):
    doc=rt.record()
    need(doc['role']=='ir' and doc['state']=='COMMITTED' and
         doc['domain']==domain and doc['peer']==peer,'IR_RUNTIME_WSS_NOT_COMMITTED')
    rt.check_protected(doc)
    for name in doc['services']:
        rt.ensure_service(name,doc,enabled=True)
    # FRPS not yet running on initial edge Apply, so this can probe replay.
    return doc

def render(domain,peer,*,before=None,stream=None,mapping=None):
    need(p.DOMAIN.fullmatch(domain) is not None,'PANEL_DOMAIN_INVALID')
    try:
        ip=ipaddress.IPv4Address(peer)
    except ValueError as exc: raise Hold('PEER_IPV4_INVALID') from exc
    need(ip.is_global,'PEER_IPV4_NOT_GLOBAL')
    q.DOMAIN=domain
    current=(before.decode() if before is not None else q.read_safe(q.TLS_SOURCE))
    streams=(stream.decode() if stream is not None else q.read_safe(q.STREAM_SOURCE))
    original=(mapping.decode() if mapping is not None else q.read_safe(q.FRP_MAP))
    try:
        q.stream_gate(streams)
        alt=q.render_alt(current).encode()
        mapping_new=q.render_map(original,str(ip)).encode()
    except q.Hold as exc:
        reason=str(exc)
        raise Hold(reason if re.fullmatch('[A-Z0-9_]{1,100}',reason)
                   else 'EDGE_RENDER_REJECTED') from exc
    return alt,mapping_new

def alternate_probe(domain):
    # Verify the *new* TLS backend, not only the pre-existing default Panel.
    rt.run(['curl','--noproxy','*','-4','-fsS',
            '--connect-timeout','3','--max-time','12',
            '--resolve',domain+':8444:127.0.0.1',
            '-o','/dev/null','https://'+domain+':8444/'],timeout=17)

def no_owner_or_data_port():
    rt.no_tunnels()
    need(not p.run(['ss','-H','-lnt','( sport = :20182 )']).strip(),
         'IR_DATA_PORT_IN_USE')

def preview(peer):
    need(os.geteuid()==0,'ROOT_REQUIRED')
    need(not STATE.exists() and not STATE.is_symlink(),'EDGE_JOURNAL_EXISTS')
    values=p.state()
    need(values.get('SMITE_ROLE')=='panel-iran'
         and values.get('SMITE_MANAGED_VERSION')=='2.0.0-rc.7',
         'IR_RC7_STATE_INVALID')
    domain=values['SMITE_PANEL_DOMAIN']
    expected_runtime(domain,peer)
    no_owner_or_data_port()
    need(not q.ALT_CANDIDATE.exists() and not q.ALT_CANDIDATE.is_symlink(),
         'ALTERNATE_TLS_BACKEND_ALREADY_EXISTS')
    before=file(q.TLS_SOURCE)
    stream=file(q.STREAM_SOURCE)
    original=file(q.FRP_MAP)
    alt,new=render(domain,peer,before=before,stream=stream,mapping=original)
    need(new!=original and alt!=before,'EDGE_PLAN_IDENTICAL')
    q.loopback_port_free(8444)
    p.run(['nginx','-t'])
    mode=stat.S_IMODE(q.FRP_MAP.stat().st_mode)
    need(mode in (0o600,0o640,0o644),'FRP_MAP_MODE_UNSAFE')
    return {'schema':1,'state':'PREPARED','domain':domain,'peer':peer,
            'tls_before':sha(before),'stream':sha(stream),
            'map_before':sha(original),'map_after':sha(new),
            'alternate':sha(alt),'map_mode':mode},original,alt,new

def validate_committed(doc):
    need(doc['state']=='COMMITTED','EDGE_NOT_COMMITTED')
    expected_runtime(doc['domain'],doc['peer'])
    original=file(STATE/'map.before',0o600)
    need(sha(original)==doc['map_before'],'MAP_BACKUP_DRIFT')
    current=file(q.TLS_SOURCE)
    stream=file(q.STREAM_SOURCE)
    need(sha(current)==doc['tls_before'] and sha(stream)==doc['stream'],
         'EXISTING_PANEL_GATEWAY_DRIFT')
    alt,new=render(doc['domain'],doc['peer'],before=current,stream=stream,
                   mapping=original)
    need(sha(alt)==doc['alternate'] and sha(new)==doc['map_after'],
         'EDGE_JOURNAL_RENDER_DRIFT')
    need(file(q.ALT_CANDIDATE,0o644)==alt and
         file(q.FRP_MAP,doc['map_mode'])==new,'LIVE_EDGE_DRIFT')
    p.run(['nginx','-t'])
    rt.panel_probe(doc['domain'])
    alternate_probe(doc['domain'])
    print('RC7_WSS_EDGE_VERIFY=PASS_READ_ONLY')
    print('PEER_ONLY='+doc['peer'])
    print('FRPS_TOUCHED=NO')

def apply(peer):
    with rt.locked():
        doc,original,alt,new=preview(peer)
        STATE.mkdir(mode=0o700)
        rt.fsync_dir(STATE.parent)
        write_new(STATE/'map.before',original,0o600)
        save(doc)
        try:
            doc['state']='APPLYING';save(doc)
            write_new(q.ALT_CANDIDATE,alt,0o644)
            atomic_replace(q.FRP_MAP,new,doc['map_mode'])
            p.run(['nginx','-t'])
            p.run(['systemctl','reload','nginx'])
            rt.panel_probe(doc['domain'])
            alternate_probe(doc['domain'])
            # Verify exact content before committing.
            need(file(q.FRP_MAP,doc['map_mode'])==new
                 and file(q.ALT_CANDIDATE,0o644)==alt,'EDGE_POSTCONDITION_FAILED')
            doc['state']='COMMITTED';save(doc)
            print('RC7_WSS_EDGE_APPLY=PASS')
            print('FRPS_TOUCHED=NO')
            print('XHTTP_ROUTE_PUBLISHED=NO')
        except Exception:
            doc['state']='HOLD';save(doc)
            raise Hold('EDGE_APPLY_HOLD_REVIEW_BEFORE_RECOVER')

def restore(doc):
    need(doc['state'] in ('COMMITTED','PREPARED','APPLYING','HOLD','ROLLING_BACK'),
         'EDGE_ROLLBACK_STATE_INVALID')
    expected_runtime(doc['domain'],doc['peer'])
    no_owner_or_data_port()
    before=file(STATE/'map.before',0o600)
    need(sha(before)==doc['map_before'],'MAP_BACKUP_DRIFT')
    tls=file(q.TLS_SOURCE)
    stream=file(q.STREAM_SOURCE)
    need(sha(tls)==doc['tls_before'] and sha(stream)==doc['stream'],
         'PANEL_GATEWAY_SOURCE_DRIFT')
    alt,new=render(doc['domain'],doc['peer'],before=tls,stream=stream,
                   mapping=before)
    need(sha(alt)==doc['alternate'] and sha(new)==doc['map_after'],
         'EDGE_JOURNAL_RENDER_DRIFT')
    current=file(q.FRP_MAP,doc['map_mode'])
    need(current in (before,new),'UNREVIEWED_MAP_DRIFT')
    if q.ALT_CANDIDATE.exists() or q.ALT_CANDIDATE.is_symlink():
        need(file(q.ALT_CANDIDATE,0o644)==alt,'UNREVIEWED_ALT_BACKEND_DRIFT')
    # Check all mutations before touching any live state.
    doc['state']='ROLLING_BACK';save(doc)
    if current != before:
        atomic_replace(q.FRP_MAP,before,doc['map_mode'])
    if q.ALT_CANDIDATE.is_file():
        q.ALT_CANDIDATE.unlink()
        rt.fsync_dir(q.ALT_CANDIDATE.parent)
    p.run(['nginx','-t'])
    p.run(['systemctl','reload','nginx'])
    rt.panel_probe(doc['domain'])
    need(file(q.FRP_MAP,doc['map_mode'])==before,'MAP_RESTORE_FAILED')
    doc['state']='ROLLED_BACK';save(doc)
    print('RC7_WSS_EDGE_ROLLBACK=PASS')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=('plan','apply','verify','rollback','recover'))
    ap.add_argument('--peer-ip',default='')
    ap.add_argument('--snapshot-confirm',default='')
    args=ap.parse_args()
    try:
        need(os.geteuid()==0 and os.uname().nodename.split('.')[0].lower()=='ir',
             'IR_ROOT_ONLY')
        if args.action in ('apply','rollback','recover'):
            need(sys.stdin.isatty() and args.snapshot_confirm=='SNAPSHOTS-CONSOLES-VERIFIED',
                 'PROVIDER_SNAPSHOT_AND_CONSOLE_REQUIRED')
            expected=args.action.upper()+'-RC7-WSS-EDGE'
            need(input('Type '+expected+': ').strip()==expected,
                 'OPERATOR_CANCELLED')
        if args.action=='plan':
            with rt.locked():
                preview(args.peer_ip)
            print('RC7_WSS_EDGE_PLAN=PASS_READ_ONLY')
            print('LIVE_CHANGES=NONE')
        elif args.action=='apply':
            apply(args.peer_ip)
        else:
            with rt.locked():
                doc=journal()
                if args.peer_ip:
                    need(doc['peer']==args.peer_ip,'PEER_MISMATCH')
                if args.action=='verify':
                    validate_committed(doc)
                elif args.action=='rollback':
                    need(doc['state']=='COMMITTED','USE_RECOVER_FOR_INCOMPLETE_EDGE')
                    restore(doc)
                else:
                    need(doc['state'] in ('PREPARED','APPLYING','HOLD','ROLLING_BACK'),
                         'RECOVERY_NOT_ALLOWED')
                    restore(doc)
        return 0
    except (Hold,q.Hold,OSError,ValueError,KeyError,TypeError) as exc:
        msg=str(exc)
        print('HOLD: '+(msg if re.fullmatch('[A-Z0-9_]{1,100}',msg)
                         else 'UNTRUSTED_WSS_EDGE_STATE'),file=sys.stderr)
        return 2

if __name__=='__main__': raise SystemExit(main())
