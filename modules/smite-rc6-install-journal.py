#!/usr/bin/env python3
"""Fresh RC6/RC7 rollback journal (legacy path and confirmation retained). Never an active-install migration/recovery tool.

Rollback quarantines fresh files and retains stopped containers and volumes.
It refuses completed installs, foreign containers, pairing, grants and routes.
No secrets are printed. Packages, pulled images and the inert broker group stay.
"""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import uuid

SOURCE = '9a1270b31e8d44f13d09b71ab6b9798410b09c12'
IMAGES = {
    'smite-panel': 'ghcr.io/aghajani82/smite-panel@sha256:180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8',
    'smite-node': 'ghcr.io/aghajani82/smite-node@sha256:03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263',
}
VERSION = '2.0.0-rc.7'
LEGACY_SOURCE = '25ff25585be3f7ff1c8b73b39a23d0509f9a2312'
LEGACY_IMAGES = {
    'smite-panel': 'ghcr.io/aghajani82/smite-panel@sha256:1e5b34652abe24c5c1971dbbdb579bb270c6c571d289198ed15cd0373da1a0f4',
    'smite-node': 'ghcr.io/aghajani82/smite-node@sha256:60a7027b56b17ceb46348f7e107a3361723a95a9b1712634dc8d90b31f928388',
}
CANDIDATES = {SOURCE: (VERSION, IMAGES), LEGACY_SOURCE: ('2.0.0-rc.6', LEGACY_IMAGES)}
TARGETS = (
    'opt/smite', 'opt/smite-node', 'opt/u-opti-smite', 'etc/u-opti/smite',
    'var/lib/u-opti/smite-xhttp-broker', 'etc/nginx/smite-xhttp-routes',
    'usr/local/bin/smite', 'usr/local/bin/smite-node',
    'usr/local/libexec/smite-xhttp-nginx-route',
    'usr/local/libexec/smite_xhttp_nginx_plan.py',
    'etc/systemd/system/u-opti-smite-xhttp-broker.service',
)
SERVICE = 'u-opti-smite-xhttp-broker.service'

class Hold(RuntimeError):
    pass


def trusted(path, directory=False):
    st = path.lstat()
    if (stat.S_ISLNK(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022
            or (directory and not stat.S_ISDIR(st.st_mode))):
        raise Hold('UNTRUSTED_PATH')
    return st


def process_start(pid):
    if pid is None:
        return None
    try:
        return Path('/proc', str(int(pid)), 'stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, ValueError):
        return None


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Journal:
    def __init__(self, root=Path('/'), runner=subprocess.run):
        self.root, self.runner = root, runner
        self.folder = root / 'var/lib/u-opti/rc6-install-journal'
        self.path = self.folder / 'current.json'

    def command(self, args):
        p = self.runner(args, capture_output=True, text=True, check=False, timeout=60)
        if p.returncode:
            raise Hold('COMMAND_FAILED')
        return p.stdout

    def docker(self, *args):
        return self.command(['docker', '--host', 'unix:///var/run/docker.sock', *args])

    def save(self, data):
        tmp = self.folder / 'next.json'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, sort_keys=True)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, self.path)
        sync_dir(self.folder)

    def load(self):
        st = trusted(self.path)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600:
            raise Hold('UNTRUSTED_JOURNAL')
        d = json.loads(self.path.read_text())
        if (not isinstance(d, dict) or d.get('schema') != 1 or d.get('source') not in CANDIDATES or not re.fullmatch('uopti_rc6_[0-9a-f]{32}', d.get('id', ''))
                or d.get('role') not in ('panel-iran', 'foreign')
                or d.get('state') not in ('INSTALLING', 'ROLLING_BACK', 'ROLLED_BACK', 'COMMITTED')):
            raise Hold('INVALID_JOURNAL')
        return d

    def begin(self, role, installer_pid=None):
        if self.path.exists():
            old = self.load()
            if old['state'] != 'ROLLED_BACK':
                raise Hold('EXISTING_TRANSACTION_USE_STATUS_OR_ROLLBACK')
            archive = self.folder / (old['id'] + '.json')
            if archive.exists():
                raise Hold('ARCHIVE_CONFLICT')
            os.rename(self.path, archive); sync_dir(self.folder)
        for rel in TARGETS:
            p = self.root / rel
            if os.path.lexists(p):
                raise Hold('EXISTING_STATE_FRESH_INSTALL_REFUSED')
            for parent in p.parents:
                if parent == self.root.parent:
                    break
                if parent.exists():
                    trusted(parent, True)
        # Reject existing managed units/overrides and all Smite containers.
        if (self.root / ('etc/systemd/system/' + SERVICE + '.d')).exists():
            raise Hold('EXISTING_SERVICE_OVERRIDE')
        names = self.docker('ps', '-a', '--format', '{{.Names}}').splitlines()
        if any(n in IMAGES for n in names):
            raise Hold('EXISTING_CONTAINER')
        if self.root == Path('/'):
            unit = self.command(['systemctl', 'show', SERVICE, '--property=LoadState', '--value']).strip()
            if unit != 'not-found':
                raise Hold('EXISTING_SERVICE')
        d = dict(schema=1, source=SOURCE, id='uopti_rc6_' + uuid.uuid4().hex,
                 role=role, state='INSTALLING', installer_pid=installer_pid,
                 installer_start=process_start(installer_pid))
        self.save(d)
        return d['id']

    def inspect_owned(self, d):
        names = self.docker('ps', '-a', '--format', '{{.Names}}').splitlines()
        result = []
        for name, image in CANDIDATES[d['source']][1].items():
            archived = name + '-' + d['id']
            for current in (name, archived):
                if current not in names:
                    continue
                obj = json.loads(self.docker('inspect', current))[0]
                config = obj['Config']
                if (config.get('Image') != image or
                    (config.get('Labels') or {}).get('com.docker.compose.project') != d['id']):
                    raise Hold('FOREIGN_CONTAINER')
                if name == 'smite-node':
                    env = dict(x.split('=', 1) for x in config.get('Env', []) if '=' in x)
                    if env.get('SMITE_NODE_PANEL_AUTH_MODE') != 'paused':
                        raise Hold('NODE_NOT_PAUSED')
                    if env.get('SMITE_AGENT_IDENTITY_PATH', '/etc/smite-node/identity/node-identity.json') != '/etc/smite-node/identity/node-identity.json':
                        raise Hold('NODE_IDENTITY_PATH_CHANGED')
                    mounts = obj.get('Mounts', [])
                    if self.root == Path('/') and not any(
                        x.get('Type') == 'bind' and x.get('Source') == '/opt/smite-node/config'
                        and x.get('Destination') == '/etc/smite-node' for x in mounts):
                        raise Hold('NODE_IDENTITY_MOUNT_CHANGED')
                result.append(dict(id=obj['Id'], name=name, archived=archived,
                                   restart=obj['HostConfig']['RestartPolicy']))
        return result

    def inactive(self, d):
        # No enrollment/route state may be abandoned by this fresh-only tool.
        # Paused controls outbound registration, not absence of an enrolled
        # inbound agent identity. Refuse it independently before any stop.
        identity = self.root / 'opt/smite-node/config/identity'
        if os.path.lexists(identity):
            raise Hold('NODE_ENROLLMENT_IDENTITY_PRESENT')
        etc = self.root / 'etc/u-opti/smite'
        if etc.exists():
            for p in etc.iterdir():
                if p.name not in ('route-broker.json', 'route-broker.key', 'route-grants', 'state.env'):
                    raise Hold('POST_INSTALL_SECURITY_STATE')
            grants = etc / 'route-grants'
            if grants.exists() and any(grants.iterdir()):
                raise Hold('TRUSTED_GRANTS_PRESENT')
        routes = self.root / 'etc/nginx/smite-xhttp-routes'
        if routes.exists() and any(routes.iterdir()):
            raise Hold('ROUTES_PRESENT')
        db = self.root / 'opt/smite/panel/data/smite.db'
        if db.exists():
            trusted(db)
            conn = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
            try:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ('nodes', 'tunnels', 'frp_proxy_leases'):
                    if table in tables and conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]:
                        raise Hold('PANEL_HAS_MANAGED_STATE')
                if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise Hold('DATABASE_INVALID')
            finally:
                conn.close()
        unit = self.root / ('etc/systemd/system/' + SERVICE)
        if unit.exists():
            item = trusted(unit)
            if (not stat.S_ISREG(item.st_mode) or item.st_nlink != 1
                    or stat.S_IMODE(item.st_mode) != 0o644):
                raise Hold('BROKER_UNIT_CHANGED')
            cfg = etc / 'route-broker.json'
            trusted(cfg)
            gid = json.loads(cfg.read_text())['peer_gid']
            spec = importlib.util.spec_from_file_location('broker_provision', Path(__file__).with_name('smite-rc5-xhttp-broker-provision.py'))
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            # The signed installer may have stopped with the old exact
            # ConditionHost=ir* unit; its bytes stay a trusted rollback
            # input after the provisioner bugfix. Never bless unknown units.
            if unit.read_bytes() not in mod.reviewed_service_unit_bytes(gid):
                raise Hold('BROKER_UNIT_CHANGED')
        return unit.exists()

    def rollback(self):
        d = self.load()
        if d.get('installer_start') and process_start(d.get('installer_pid')) == d['installer_start']:
            raise Hold('INSTALLER_STILL_RUNNING')
        if d['state'] == 'ROLLED_BACK':
            return 'RC6_ROLLBACK=ALREADY_COMPLETE'
        if d['state'] == 'COMMITTED':
            raise Hold('COMPLETED_INSTALL_NOT_A_ROLLBACK_TARGET')
        if d['state'] == 'INSTALLING':
            containers = self.inspect_owned(d)
            service = self.inactive(d)
            paths = []
            for rel in TARGETS:
                p = self.root / rel
                if os.path.lexists(p):
                    st = trusted(p)
                    dest = p.with_name(p.name + '.rc6-rollback-' + d['id'])
                    if os.path.lexists(dest):
                        raise Hold('ARCHIVE_PATH_CONFLICT')
                    paths.append(dict(path=rel, dev=st.st_dev, ino=st.st_ino))
            d.update(state='ROLLING_BACK', containers=containers, paths=paths, service=service)
            self.save(d)  # Durable plan before stopping or moving anything.
        # Revalidate identities on every retry; never select a replacement by name.
        owned = {x['id']: x for x in self.inspect_owned(d)}
        if set(owned) != {x['id'] for x in d['containers']}:
            raise Hold('CONTAINER_SET_CHANGED')
        for item in d['paths']:
            if item['path'] not in TARGETS:
                raise Hold('INVALID_JOURNAL_PATH')
            p = self.root / item['path']; dest = p.with_name(p.name + '.rc6-rollback-' + d['id'])
            candidates = [x for x in (p, dest) if os.path.lexists(x)]
            if len(candidates) != 1:
                raise Hold('ROLLBACK_PATH_AMBIGUOUS')
            st = trusted(candidates[0])
            if (st.st_dev, st.st_ino) != (item['dev'], item['ino']):
                raise Hold('ROLLBACK_PATH_REPLACED')
        # Recheck before the first stop. Later retries may already have moved DBs.
        if not d.get('stopped'):
            self.inactive(d)
            for item in d['containers']:
                self.docker('update', '--restart=no', item['id'])
                self.docker('stop', item['id'])
            if d['service']:
                self.command(['systemctl', 'disable', '--now', SERVICE])
            self.inactive(d)
            d['stopped'] = True; self.save(d)
        for item in d['containers']:
            obj = json.loads(self.docker('inspect', item['id']))[0]
            if obj['State']['Running']:
                raise Hold('CONTAINER_RESTARTED')
            if obj['Name'].lstrip('/') == item['name']:
                self.docker('rename', item['id'], item['archived'])
        for item in d['paths']:
            p = self.root / item['path']; dest = p.with_name(p.name + '.rc6-rollback-' + d['id'])
            if os.path.lexists(p):
                os.rename(p, dest); sync_dir(p.parent)
        if d['service']:
            self.command(['systemctl', 'daemon-reload'])
        d['state'] = 'ROLLED_BACK'; self.save(d)
        return 'RC6_ROLLBACK=PASS_DATA_RETAINED'

    def commit(self):
        d = self.load()
        if d['state'] != 'INSTALLING':
            raise Hold('INVALID_COMMIT_STATE')
        expected = set(IMAGES) if d['role'] == 'panel-iran' else {'smite-node'}
        if {x['name'] for x in self.inspect_owned(d)} != expected:
            raise Hold('INCOMPLETE_CONTAINER_SET')
        state = self.root / 'etc/u-opti/smite/state.env'
        trusted(state)
        lines = state.read_text().splitlines()
        if ('SMITE_UPSTREAM_REF=' + d['source'] not in lines or
            'SMITE_MANAGED_VERSION=' + CANDIDATES[d['source']][0] not in lines or
            'SMITE_ROLE=' + d['role'] not in lines):
            raise Hold('STATE_MISMATCH')
        d['state'] = 'COMMITTED'; self.save(d)
        return 'RC6_INSTALL_TRANSACTION=COMMITTED'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('begin', 'status', 'commit', 'rollback'))
    ap.add_argument('--role', choices=('panel-iran', 'foreign'))
    ap.add_argument('--confirm', default='')
    ap.add_argument('--installer-pid', type=int)
    a = ap.parse_args()
    try:
        if os.geteuid() != 0:
            raise Hold('ROOT_REQUIRED')
        if any(os.environ.get(x) for x in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_CONFIG','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')):
            raise Hold('AMBIENT_DOCKER_CONFIGURATION')
        j = Journal()
        for p in j.folder.parents:
            if p.exists(): trusted(p, True)
        j.folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        for p in (j.folder, *j.folder.parents):
            trusted(p, True)
        if stat.S_IMODE(j.folder.stat().st_mode) != 0o700:
            raise Hold('JOURNAL_PERMISSIONS')
        fd = os.open(j.folder / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if a.action == 'begin':
                if not a.role: raise Hold('ROLE_REQUIRED')
                if not a.installer_pid or not process_start(a.installer_pid):
                    raise Hold('INSTALLER_PROCESS_REQUIRED')
                print(j.begin(a.role, a.installer_pid))
            elif a.action == 'status':
                print('RC6_INSTALL_TRANSACTION=' + j.load()['state'])
            elif a.action == 'commit':
                print(j.commit())
            else:
                if a.confirm != 'ROLLBACK-RC6': raise Hold('CONFIRMATION_REQUIRED')
                operation = os.open(j.folder / 'operation.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                with os.fdopen(operation, 'w') as running_lock:
                    fcntl.flock(running_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    print(j.rollback())
    except (Hold, OSError, ValueError, KeyError, TypeError, IndexError, sqlite3.Error, subprocess.SubprocessError):
        print('HOLD: RC6 journal/recovery validation failed; retained state must not be deleted.', file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
