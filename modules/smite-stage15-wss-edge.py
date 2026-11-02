#!/usr/bin/env python3
"""Stage15 peer-scoped TLS/443 WSS edge with preserved Panel vhost and rollback."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
import importlib.util
spec=importlib.util.spec_from_file_location('stage15_wss',HERE/'smite-stage15-wss.py')
wss=importlib.util.module_from_spec(spec);spec.loader.exec_module(wss)
host=wss.host;need=host.require
edge=wss.load('stage15_edge_render','smite-rc2-frp-wss-edge-plan.py')
STATE=Path('/var/lib/u-opti/smite-stage15-wss-edge')


def bridge_source(current, *, committed=False):
    path=Path('/var/lib/u-opti/smite-stage15-xhttp-bridge')
    if path.exists() or path.is_symlink():
        bridge=wss.load('stage15_edge_bridge', 'smite-stage15-xhttp-bridge.py')
        return bridge.original_backend(current, committed=committed)
    return current


def state():
    host.directory(STATE,private=True)
    doc=json.loads(host.file(STATE/'record.json',mode=0o600))
    need(set(doc)=={'schema','state','domain','peer','backend','stream','old_map','new_map','alt','mode'}
         and doc['schema']==1 and doc['state'] in ('PREPARED','COMMITTED','RECOVERING','ROLLED_BACK'), 'INVALID_EDGE_JOURNAL')
    edge.DOMAIN=wss.domain(doc['domain']);edge.kh_ip(doc['peer'])
    need(doc['new_map']==edge.render_map(doc['old_map'],doc['peer']),'EDGE_JOURNAL_MAP_DRIFT')
    need(doc['alt']==edge.render_alt(bridge_source(host.file(edge.TLS_SOURCE)).decode()),'EDGE_JOURNAL_ALT_DRIFT')
    need(doc['mode'] in (0o600,0o640,0o644),'EDGE_MAP_MODE_DRIFT')
    return doc


def save(doc):wss.write_atomic(STATE/'record.json',(json.dumps(doc,sort_keys=True)+'\n').encode())


def protected(doc):
    need(host.digest(bridge_source(host.file(edge.TLS_SOURCE),committed=True))==doc['backend'] and
         host.digest(host.file(edge.STREAM_SOURCE))==doc['stream'],'NGINX_SOURCE_DRIFT')


def atomic(path,raw,mode):
    wss.write_atomic(path,raw);os.chmod(path,mode);host.flush(path.parent)


def plan(peer):
    need(not STATE.exists() and not STATE.is_symlink(),'EXISTING_EDGE_JOURNAL')
    signed=wss.read_record();need(signed['state']=='COMMITTED' and signed['roles']==['panel','node'],'IR_WSS_NOT_COMMITTED')
    wss.health(signed,True)
    # Do not install a new edge over an already-running FRPS owner or tunnel.
    wss.no_tunnels()
    edge.DOMAIN=wss.domain(signed['domain']);peer=edge.kh_ip(peer)
    source=host.file(edge.TLS_SOURCE).decode();stream=host.file(edge.STREAM_SOURCE).decode();mapping=host.file(edge.FRP_MAP).decode()
    edge.stream_gate(stream)
    need(not edge.ALT_CANDIDATE.exists() and not edge.ALT_CANDIDATE.is_symlink(),'EXISTING_EDGE_BACKEND')
    edge.loopback_port_free(edge.ALT_PORT);host.run(['nginx','-t'])
    mode=edge.FRP_MAP.stat().st_mode&0o777
    need(mode in (0o600,0o640,0o644),'UNSAFE_EDGE_MAP')
    return {'schema':1,'state':'PREPARED','domain':edge.DOMAIN,'peer':peer,
            'backend':host.digest(source.encode()),'stream':host.digest(stream.encode()),
            'old_map':mapping,'new_map':edge.render_map(mapping,peer),'alt':edge.render_alt(source),'mode':mode}


def restore(doc):
    # Edge rollback is only safe after all children and their FRPS owner are
    # removed. Otherwise KH would lose its active signed transport.
    wss.no_tunnels()
    need(host.digest(host.file(edge.TLS_SOURCE))==doc['backend'], 'ROLLBACK_BRIDGE_FIRST')
    protected(doc)
    need(host.file(edge.FRP_MAP).decode() in (doc['old_map'],doc['new_map']),'EXTERNAL_MAP_DRIFT')
    if edge.ALT_CANDIDATE.exists() or edge.ALT_CANDIDATE.is_symlink():
        need(host.file(edge.ALT_CANDIDATE).decode()==doc['alt'],'EXTERNAL_BACKEND_DRIFT')
    wss.discard_partial(STATE/'record.json',[(json.dumps(dict(doc,state=s),sort_keys=True)+'\n').encode() for s in ('PREPARED','COMMITTED','RECOVERING','ROLLED_BACK')])
    wss.discard_partial(edge.FRP_MAP,[doc['old_map'].encode(),doc['new_map'].encode()])
    wss.discard_partial(edge.ALT_CANDIDATE,[doc['alt'].encode()])
    doc['state']='RECOVERING';save(doc)
    atomic(edge.FRP_MAP,doc['old_map'].encode(),doc['mode'])
    if edge.ALT_CANDIDATE.exists():edge.ALT_CANDIDATE.unlink();host.flush(edge.ALT_CANDIDATE.parent)
    host.run(['nginx','-t']);host.run(['systemctl','reload','nginx'])
    doc['state']='ROLLED_BACK';save(doc)


def apply(peer):
    with host.exclusive(wss.LOCK):
        doc=plan(peer);host.new_dir(STATE);save(doc)
        try:
            atomic(edge.ALT_CANDIDATE,doc['alt'].encode(),0o644)
            atomic(edge.FRP_MAP,doc['new_map'].encode(),doc['mode'])
            host.run(['nginx','-t']);host.run(['systemctl','reload','nginx'])
            protected(doc);doc['state']='COMMITTED';save(doc)
        except Exception:
            restore(doc);raise host.Hold('EDGE_FAILURE_ROLLED_BACK')


def verify(doc):
    # A syntactically valid Nginx map alone is not operational proof.
    signed=wss.read_record()
    need(signed['state']=='COMMITTED' and signed['roles']==['panel','node']
         and signed['domain']==doc['domain'],'IR_WSS_NOT_COMMITTED')
    wss.health(signed,True)
    protected(doc)
    need(host.file(edge.FRP_MAP).decode()==doc['new_map']
         and host.file(edge.ALT_CANDIDATE).decode()==doc['alt'],'EDGE_DRIFT')
    host.run(['nginx','-t'])


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['plan','apply','verify','rollback','recover']);ap.add_argument('--kh-ip',default='');args=ap.parse_args()
    try:
        need(os.geteuid()==0 and os.uname().nodename.split('.')[0].lower()=='ir','IR_ROOT_ONLY')
        if args.action in ('apply','rollback','recover'):
            need(sys.stdin.isatty(),'INTERACTIVE_CONFIRMATION_REQUIRED')
            challenge=args.action.upper()+'-IR-WSS-EDGE-SNAPSHOT-CONSOLE'
            need(input('Verify KH egress IPv4 ownership. Type '+challenge+': ').strip()==challenge,'OPERATOR_CANCELLED')
        if args.action=='plan':plan(args.kh_ip)
        elif args.action=='apply':apply(args.kh_ip)
        else:
            with host.exclusive(wss.LOCK):
                doc=state()
                if args.action=='verify':
                    need(doc['state']=='COMMITTED','EDGE_NOT_COMMITTED');verify(doc)
                else:restore(doc)
        print('STAGE15_WSS_EDGE_'+args.action.upper()+'=PASS');print('PUBLIC_CONTROL_PORTS_OPENED=NO');return 0
    except (host.Hold,edge.Hold,OSError,ValueError,KeyError,TypeError) as exc:
        msg=str(exc);print('HOLD: '+(msg if re.fullmatch('[A-Z0-9_]{1,100}',msg) else 'UNTRUSTED_EDGE_STATE'),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
