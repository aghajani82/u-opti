#!/usr/bin/env python3
"""Pinned static-only RC7 UI update. No service restart, image or database mutation."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

BUNDLE_SHA = 'ad92e819a4a47e80b1991b5d52e1873bb5b08db48118a86e660fe15f979286e1'
SOURCE = '5e7a289071e446345ac27e4255994daf3446430a'
IMAGE = 'ghcr.io/aghajani82/smite-panel@sha256:180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8'
STATE = Path('/var/lib/u-opti/smite-panel-ui')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= 100 or 'index.html' not in files:
        raise ValueError('invalid static file set')
    total = 0
    for name, encoded in files.items():
        if not re.fullmatch(r'(index\.html|vite\.svg|assets/[A-Za-z0-9_.-]+\.(js|css|png|svg|woff2?))', name):
            raise ValueError('unsafe static path')
        data = base64.b64decode(encoded, validate=True)
        total += len(data)
    if total > 16 * 1024 * 1024:
        raise ValueError('oversized static file set')
    return files


def bundle(path):
    if path.is_symlink(): raise ValueError('unsafe bundle path')
    raw = path.read_bytes()
    if digest(raw) != BUNDLE_SHA:
        raise ValueError('UI bundle SHA256 mismatch; update U-OPTI before retrying')
    obj = json.loads(raw)
    if obj['source_sha'] != SOURCE:
        raise ValueError('UI source mismatch')
    return validate(obj['files'])


# Runs only inside the admitted Panel. Stage assets first, publish index last.
# Keep old content-addressed assets so already-open browser tabs remain usable.
STATIC_SCRIPT = r'''
import base64, hashlib, json, os, pathlib, tempfile, sys
p=pathlib.Path('/app/static')
if not p.is_dir() or p.is_symlink(): raise RuntimeError('unsafe static root')
for f in p.rglob('*'):
    if f.is_symlink() or (not f.is_file() and not f.is_dir()): raise RuntimeError('unsafe static entry')
request=json.load(sys.stdin)
if request['action']=='snapshot':
    files={str(f.relative_to(p)):base64.b64encode(f.read_bytes()).decode() for f in p.rglob('*') if f.is_file() and not f.name.startswith('.uopti-ui-')}
    print(json.dumps(files)); sys.exit(0)
current=(p/'index.html').read_bytes()
if hashlib.sha256(current).hexdigest()!=request['expected_index']: raise RuntimeError('UI changed during operation')
files=request['files']
for name,encoded in files.items():
    if name=='index.html': continue
    target=p/name; data=base64.b64decode(encoded,validate=True)
    if target.exists() and target.read_bytes()!=data: raise RuntimeError('immutable asset collision')
for name in sorted(files, key=lambda n:n=='index.html'):
    target=p/name; data=base64.b64decode(files[name],validate=True)
    target.parent.mkdir(exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.uopti-ui-',dir=str(target.parent))
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        os.chmod(tmp,0o644); os.replace(tmp,target)
        fd=os.open(str(target.parent),os.O_RDONLY); os.fsync(fd); os.close(fd)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
print('STATIC_INDEX_COMMITTED')
'''


def docker(*args, data=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DOCKER_', 'COMPOSE_'))}
    return subprocess.run(['docker', '--host', 'unix:///var/run/docker.sock', *args],
                          input=data, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=90, check=True, env=env).stdout


def admit(container):
    c = json.loads(docker('inspect', container))[0]
    image = json.loads(docker('image', 'inspect', IMAGE))[0]
    if c['Image'] != image['Id'] or not c['State']['Running']:
        raise ValueError('only the running reviewed RC7 Panel image is supported')
    if c['State'].get('Health', {}).get('Status') == 'unhealthy':
        raise ValueError('Panel is unhealthy')
    for mount in c.get('Mounts', []):
        dest = mount['Destination'].rstrip('/') or '/'
        if dest == '/' or dest == '/app' or dest.startswith('/app/static'):
            raise ValueError('static directory bind/volume overlays are not supported')
    return c['Id']


def snapshot(cid):
    return validate(json.loads(docker('exec', '-i', cid, 'python', '-c', STATIC_SCRIPT,
                                      data=json.dumps({'action': 'snapshot'}))))


def index_hash(files):
    return digest(base64.b64decode(files['index.html'], validate=True))


def publish(cid, files, expected):
    validate(files)
    docker('exec', '-i', cid, 'python', '-c', STATIC_SCRIPT,
           data=json.dumps({'action': 'publish', 'files': files, 'expected_index': expected}))
    actual = snapshot(cid)
    if any(actual.get(n) != value for n, value in files.items()):
        raise ValueError('post-write static verification failed; backup retained')


def write_json(path, value):
    tmp = path.with_suffix('.tmp')
    if tmp.is_symlink() or path.is_symlink():
        raise ValueError('unsafe journal path')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(value, f, sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, 0o600); os.replace(tmp, path)
    fd = os.open(str(path.parent), os.O_RDONLY); os.fsync(fd); os.close(fd)


def operate(action, bundle_path, state=STATE, container='smite-panel'):
    # Root-owned durable journal. The lock serializes menu and fresh-install calls.
    for p in [state, *state.parents]:
        if p.is_symlink():
            raise ValueError('symlink in journal path')
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state.stat().st_uid != os.geteuid() or state.stat().st_mode & 0o077:
        raise ValueError('journal directory must be private and owned by the operator')
    if (state/'operation.lock').is_symlink():
        raise ValueError('unsafe lock')
    with open(state/'operation.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = state/'current.json'
        if journal.is_symlink(): raise ValueError('unsafe journal')
        previous = json.loads(journal.read_text()) if journal.exists() else None
        if action == 'status':
            print('UI_SOURCE=' + SOURCE)
            print('UI_JOURNAL=' + (previous['status'] if previous else 'NONE'))
            return
        cid = admit(container)
        current = snapshot(cid)
        if action == 'rollback':
            if not previous or previous['container_id'] != cid:
                raise ValueError('no matching container backup; nothing changed')
            backup = validate(previous['before'])
            if index_hash(current) not in [index_hash(backup), previous['after_index']]:
                raise ValueError('current UI differs from recorded transaction; review required')
            publish(cid, backup, index_hash(current))
            previous['status'] = 'ROLLED_BACK'; write_json(journal, previous)
            print('UI_ROLLBACK=PASS; containers, backend, pairing and databases unchanged')
            return
        target = bundle(bundle_path)
        if all(current.get(n) == value for n, value in target.items()):
            if previous and previous['container_id'] == cid and previous['status'] == 'APPLYING':
                previous['status'] = 'APPLIED'; write_json(journal, previous)
            print('UI_UPDATE=ALREADY_CURRENT'); return
        if previous and previous['status'] == 'APPLYING':
            raise ValueError('interrupted UI update; use the rollback menu before retrying')
        if previous:
            write_json(state/(uuid.uuid4().hex+'.json'), previous)
        record = {'status': 'APPLYING', 'container_id': cid, 'source_sha': SOURCE,
                  'before': current, 'after_index': index_hash(target)}
        write_json(journal, record)  # Durable backup BEFORE any write to the Panel.
        publish(cid, target, index_hash(current))
        record['status'] = 'APPLIED'; write_json(journal, record)
        print('UI_UPDATE=PASS; source=' + SOURCE + '; restart=NO')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'rollback', 'status'])
    args = parser.parse_args()
    if os.geteuid() != 0: raise ValueError('root required')
    os.umask(0o077)
    operate(args.action, Path(__file__).with_name('smite-panel-ui.json'))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as exc:
        print('HOLD: UI operation did not complete; backup retained. ' + str(exc).splitlines()[0][:180], file=sys.stderr)
        sys.exit(2)
