#!/usr/bin/env python3
"""Preserve the exact active reviewed Compose overlays in ordinary operations.

Prepared but inactive security candidates are never implicitly activated.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

class Hold(ValueError):pass


def trusted(path):
    for p in (path,*path.parents):
        s=p.lstat()
        if p.is_symlink() or s.st_uid!=0 or s.st_mode&0o022:
            raise Hold('UNTRUSTED_COMPOSE_PATH')
    if not stat.S_ISREG(path.lstat().st_mode):raise Hold('INVALID_COMPOSE_FILE')


def active_files(base, obj):
    service='smite-panel' if base.parent.name=='smite' else 'smite-node'
    allowed=({'docker-compose.signed-control.yml'} if service=='smite-panel' else
             {'docker-compose.security-candidate.yml','docker-compose.frp-stage15.yml'})|{'docker-compose.wss-stage15.yml'}
    labels=obj.get('Config',{}).get('Labels') or {}
    if labels.get('com.docker.compose.service')!=service:raise Hold('COMPOSE_SERVICE_DRIFT')
    raw=labels.get('com.docker.compose.project.config_files','').split(',')
    files=[Path(x) for x in raw]
    if not files or files[0]!=base or len(set(files))!=len(files):raise Hold('COMPOSE_BASE_OR_DUPLICATE_DRIFT')
    if any(p.parent!=base.parent or p.name not in allowed for p in files[1:]):raise Hold('UNREVIEWED_ACTIVE_COMPOSE_FILE')
    for p in files:trusted(p)
    return files


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('base',type=Path);ap.add_argument('args',nargs=argparse.REMAINDER);a=ap.parse_args()
    try:
        if a.base not in (Path('/opt/smite/docker-compose.yml'),Path('/opt/smite-node/docker-compose.yml')):raise Hold('UNREVIEWED_COMPOSE_BASE')
        if any(os.environ.get(k) for k in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_CONFIG','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH','COMPOSE_FILE','COMPOSE_PROFILES')):raise Hold('AMBIENT_DOCKER_CONFIGURATION')
        if not a.args or any(x in ('-f','--file','--project-directory','--env-file','--profile') or x.startswith(('--file=','--project-directory=','--env-file=','--profile=')) for x in a.args):raise Hold('UNREVIEWED_COMPOSE_ARGUMENT')
        trusted(a.base)
        docker=['docker','--host','unix:///var/run/docker.sock']
        service='smite-panel' if a.base.parent.name=='smite' else 'smite-node'
        # Distinguish absent container from daemon errors without parsing stderr.
        names=subprocess.run(docker+['ps','-a','--format','{{.Names}}'],capture_output=True,text=True,check=True,timeout=20).stdout.splitlines()
        if service in names:
            obj=json.loads(subprocess.run(docker+['inspect',service],capture_output=True,text=True,check=True,timeout=20).stdout)
            if len(obj)!=1:raise Hold('INVALID_CONTAINER_INSPECT')
            files=active_files(a.base,obj[0])
        else:
            # A removed container must not silently discard persisted signed state.
            if any(p.exists() or p.is_symlink() for p in a.base.parent.glob('docker-compose.*.yml')):raise Hold('CONTAINER_ABSENT_WITH_EXISTING_OVERLAYS')
            files=[a.base]
        command=docker+['compose']
        for p in files:command+=['-f',str(p)]
        return subprocess.run(command+a.args,check=False).returncode
    except (Hold,OSError,ValueError,KeyError,subprocess.SubprocessError):
        print('HOLD: Cannot preserve the verified active Compose set',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
