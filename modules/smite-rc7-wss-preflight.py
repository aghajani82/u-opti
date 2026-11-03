#!/usr/bin/env python3
"""Read-only RC7 signed WSS/443 admission for an existing IR/Foreign pair.

No install, Apply, Docker mutation, Nginx reload or exposure of credentials.
"""
from __future__ import annotations
import argparse
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
STATE=Path('/etc/u-opti/smite/state.env')
PANEL=Path('/opt/smite')
NODE=Path('/opt/smite-node')
PANEL_IMAGE=('ghcr.io/aghajani82/smite-panel@sha256:'
             '180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8')
NODE_IMAGE=('ghcr.io/aghajani82/smite-node@sha256:'
            '03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263')
DOMAIN=re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\Z')
PROJECT=re.compile(r'uopti_rc6_[a-f0-9]{32}\Z')

class Hold(Exception):
    pass

def need(ok, reason):
    if not ok:
        raise Hold(reason)

def run(args, *, input=None):
    need(not any(os.environ.get(key) for key in (
        'DOCKER_HOST','DOCKER_CONTEXT','DOCKER_CONFIG','DOCKER_TLS_VERIFY',
        'DOCKER_CERT_PATH','COMPOSE_FILE','COMPOSE_PROFILES'
    )), 'AMBIENT_DOCKER_OVERRIDE')
    try:
        result=subprocess.run(args,input=input,text=True,stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,timeout=35,check=False)
    except (OSError,subprocess.SubprocessError) as exc:
        raise Hold('READ_ONLY_COMMAND_FAILED') from exc
    need(result.returncode==0 and len(result.stdout)<=512000,'READ_ONLY_COMMAND_FAILED')
    return result.stdout.strip()

def state(path=STATE):
    need(path.is_file() and not path.is_symlink(),'STATE_UNAVAILABLE')
    values={}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        key,sep,value=line.partition('=')
        need(sep and key not in values and re.fullmatch('[A-Z0-9_]+',key),
             'STATE_INVALID')
        values[key]=value
    return values

def runtime_env(obj):
    values={}
    raw=obj.get('Config',{}).get('Env',[])
    need(isinstance(raw,list),'RUNTIME_ENV_INVALID')
    for line in raw:
        need(isinstance(line,str) and '=' in line,'RUNTIME_ENV_INVALID')
        key,value=line.split('=',1)
        need(key not in values,'RUNTIME_ENV_DUPLICATED')
        values[key]=value
    return values

def compose_files(name,obj):
    labels=obj.get('Config',{}).get('Labels') or {}
    project=labels.get('com.docker.compose.project','')
    need(PROJECT.fullmatch(project) is not None,'COMPOSE_OWNER_MISMATCH')
    ambient=os.environ.get('COMPOSE_PROJECT_NAME','')
    need(not ambient or ambient==project,'AMBIENT_PROJECT_CONFLICT')
    need(labels.get('com.docker.compose.service')==name,'COMPOSE_SERVICE_MISMATCH')
    active=(labels.get('com.docker.compose.project.config_files') or '').split(',')
    root=PANEL if name=='smite-panel' else NODE
    base=str(root/'docker-compose.yml')
    signed=str(root/('docker-compose.signed-control.yml' if name=='smite-panel'
                     else 'docker-compose.security-candidate.yml'))
    need(active in ([base],[base,signed]),'COMPOSE_FILE_SET_MISMATCH')
    for path in active:
        p=Path(path)
        need(p.is_file() and not p.is_symlink(),'COMPOSE_FILE_UNSAFE')
    return project,active

def service_gate(name,obj,*,role,domain):
    need(obj.get('Config',{}).get('Image')==
         (PANEL_IMAGE if name=='smite-panel' else NODE_IMAGE),
         'UNREVIEWED_RC7_IMAGE')
    state=obj.get('State',{})
    need(state.get('Running') is True and state.get('Health',{}).get('Status')=='healthy',
         'SERVICE_NOT_HEALTHY')
    host=obj.get('HostConfig') or {}
    need(host.get('NetworkMode')=='host' and not host.get('PortBindings')
         and host.get('Privileged') is not True,
         'NETWORK_PRIVILEGE_DRIFT')
    env=runtime_env(obj)
    need('SMITE_FRP_STANDARD_WSS' not in env,'WSS_ALREADY_CONFIGURED')
    if name=='smite-panel':
        need(env.get('SMITE_PANEL_AGENT_AUTH_MODE')=='signed'
             and env.get('SMITE_ENGINE_MANAGEMENT_MODE')=='managed'
             and env.get('PANEL_DOMAIN')==domain
             and env.get('PANEL_HOST')=='127.0.0.1',
             'PANEL_SIGNED_POLICY_DRIFT')
    else:
        need(env.get('SMITE_AGENT_AUTH_MODE')=='strict'
             and env.get('SMITE_NODE_PANEL_AUTH_MODE')=='signed'
             and env.get('SMITE_ENGINE_INVENTORY_MODE')=='managed'
             and env.get('PANEL_ADDRESS')==domain+':443',
             'NODE_SIGNED_POLICY_DRIFT')
        cmd=obj.get('Config',{}).get('Cmd') or []
        need(cmd[:6]==['uvicorn','main:app','--host','127.0.0.1','--port','8888'],
             'NODE_API_NOT_LOOPBACK')
        if role=='foreign':
            need(env.get('NODE_ROLE')=='foreign'
                 and env.get('SMITE_SANAEI_INVENTORY_ENABLED')=='true',
                 'FOREIGN_INVENTORY_NOT_ENABLED')
            mounts=obj.get('Mounts') or []
            found=[m for m in mounts if m.get('Destination')=='/run/smite-sanaei-ro']
            need(len(found)==1 and found[0].get('Type')=='bind'
                 and found[0].get('Source')=='/opt/3x-ui/instances/01/db'
                 and found[0].get('RW') is False,
                 'FOREIGN_SANAEI_NOT_READ_ONLY')

def only_wss_change(before,after,name):
    """Only SMITE_FRP_STANDARD_WSS=1 may be added to the effective config."""
    need(before.keys()==after.keys(),'COMPOSE_TOP_LEVEL_DRIFT')
    need(isinstance(before.get('services'),dict)
         and before['services'].keys()==after['services'].keys()
         and name in before['services'],'COMPOSE_SERVICES_DRIFT')
    original=json.loads(json.dumps(before))
    candidate=json.loads(json.dumps(after))
    env_before=original['services'][name].get('environment') or {}
    env_after=candidate['services'][name].get('environment') or {}
    need(isinstance(env_before,dict) and isinstance(env_after,dict)
         and 'SMITE_FRP_STANDARD_WSS' not in env_before
         and env_after.pop('SMITE_FRP_STANDARD_WSS',None)=='1',
         'WSS_FLAG_NOT_EXCLUSIVE')
    need(env_before==env_after,'ENVIRONMENT_DRIFT')
    candidate['services'][name]['environment']=env_before
    need(original==candidate,'EFFECTIVE_COMPOSE_DRIFT')

def overlay_bytes(name):
    return ('services:\n  '+name+':\n    environment:\n'
            '      SMITE_FRP_STANDARD_WSS: "1"\n')

def prove_service(name,role,domain):
    docs=json.loads(run(['docker','inspect',name]))
    need(isinstance(docs,list) and len(docs)==1,'CONTAINER_INSPECT_INVALID')
    obj=docs[0]
    service_gate(name,obj,role=role,domain=domain)
    project,files=compose_files(name,obj)
    args=['docker','compose','--project-name',project]
    for path in files:
        args+=['-f',path]
    before=json.loads(run(args+['config','--format','json']))
    after=json.loads(run(args+['-f','-','config','--format','json'],
                         input=overlay_bytes(name)))
    only_wss_change(before,after,name)
    need(run(['docker','exec','smite-node',
              ('frps' if role=='panel-iran' else 'frpc'),
              '--version'])=='0.71.0','FRP_BINARY_VERSION_MISMATCH')
    return project

def nginx_candidate(domain,peer):
    path=HERE/'smite-rc2-frp-wss-edge-plan.py'
    need(path.is_file(),'NGINX_EDGE_RENDERER_MISSING')
    spec=importlib.util.spec_from_file_location('rc7_wss_renderer',path)
    need(spec is not None and spec.loader is not None,
         'NGINX_EDGE_RENDERER_MISSING')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DOMAIN=domain
    try:
        tls=mod.read_safe(mod.TLS_SOURCE)
        stream=mod.read_safe(mod.STREAM_SOURCE)
        mapping=mod.read_safe(mod.FRP_MAP)
        mod.stream_gate(stream)
        rendered=mod.render_alt(tls)
        mapped=mod.render_map(mapping,peer)
        mod.loopback_port_free(8444)
    except (mod.Hold,OSError,ValueError) as exc:
        message=str(exc)
        raise Hold(message if re.fullmatch('[A-Z0-9_]{1,100}',message)
                   else 'NGINX_RENDERER_REJECTED') from exc
    need(rendered!=tls and mapped!=mapping,'NGINX_CANDIDATE_NOT_DISTINCT')
    need(not run(['ss','-H','-lnt','( sport = :7000 )']).strip(),
         'FRPS_CONTROL_PORT_IN_USE')
    need(not run(['ss','-H','-lnt','( sport = :20182 )']).strip(),
         'IR_DATA_PORT_IN_USE')
    run(['nginx','-t'])

def inspect(role,peer_ip=None):
    need(os.geteuid()==0,'ROOT_REQUIRED')
    values=state()
    expected='panel-iran' if role=='ir' else 'foreign'
    need(values.get('SMITE_ROLE')==expected
         and values.get('SMITE_MANAGED_VERSION')=='2.0.0-rc.7'
         and values.get('SMITE_CONNECTION_MODE')=='standard',
         'RC7_MANAGED_ROLE_MISMATCH')
    domain=values.get('SMITE_PANEL_DOMAIN','')
    need(DOMAIN.fullmatch(domain) is not None and len(domain)<=253,
         'PANEL_DOMAIN_INVALID')
    print('RC7_ROLE=PASS')
    owner=prove_service('smite-node',expected,domain)
    print('RC7_NODE_COMPOSE_WSS_ONLY=PASS')
    if role=='ir':
        need(peer_ip is not None,'PEER_IPV4_REQUIRED')
        try:
            peer=ipaddress.IPv4Address(peer_ip)
        except ipaddress.AddressValueError as exc:
            raise Hold('PEER_IPV4_INVALID') from exc
        need(peer.is_global,'PEER_IPV4_NOT_GLOBAL')
        panel_owner=prove_service('smite-panel',expected,domain)
        need(owner==panel_owner,'PANEL_NODE_OWNER_MISMATCH')
        print('RC7_PANEL_COMPOSE_WSS_ONLY=PASS')
        nginx_candidate(domain,str(peer))
        print('RC7_NGINX_WSS_IN_MEMORY=PASS')
        print('RC7_PEER_ALLOW_IPV4='+str(peer))
    else:
        print('RC7_FOREIGN_SANAEI_READ_ONLY=PASS')
    print('RC7_WSS_PLAN=PASS_READ_ONLY')
    print('RC7_WSS_ACTIVATION=NOT_IMPLEMENTED')
    print('LIVE_CHANGES=NONE')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('plan',))
    parser.add_argument('--role',choices=('ir','foreign'),required=True)
    parser.add_argument('--peer-ip')
    args=parser.parse_args()
    try:
        inspect(args.role,args.peer_ip)
        return 0
    except (Hold,KeyError,ValueError,TypeError) as exc:
        msg=str(exc)
        if not re.fullmatch('[A-Z0-9_]{1,100}',msg):
            msg='UNTRUSTED_PRECHECK_STATE'
        print('HOLD: '+msg,file=sys.stderr)
        print('LIVE_CHANGES=NONE')
        return 2

if __name__=='__main__':
    raise SystemExit(main())
