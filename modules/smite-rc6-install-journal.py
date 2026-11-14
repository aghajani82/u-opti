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
IR_NODE_TARGETS = ('opt/smite-node', 'etc/u-opti/smite/state.env')
# Option 1 uses the EXISTING fresh-install journal as its durable resume
# cursor. Only NEW explicitly opted-in Iran installs may use these stages:
# legacy COMMITTED and all foreign journals are never adopted automatically.
IR_PHASES = (
    'CORE_COMMITTED', 'GATEWAY_VERIFIED', 'PAIRING_VERIFIED',
    'ADMIN_CREATED', 'COMPLETE',
)

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

    def save(self, data, destination=None):
        tmp = self.folder / 'next.json'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, sort_keys=True)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, destination or self.path)
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

    def begin(self, role, installer_pid=None, *, resumable_ir=False, ir_inputs=None):
        if type(resumable_ir) is not bool or (resumable_ir and role != 'panel-iran'):
            raise Hold('INVALID_RESUMABLE_INSTALL_ROLE')
        if ir_inputs is not None and not resumable_ir:
            raise Hold('INVALID_IR_CORE_INPUTS')
        archive = None
        if os.path.lexists(self.path):
            old = self.load()
            if old['state'] != 'ROLLED_BACK':
                raise Hold('EXISTING_TRANSACTION_USE_STATUS_OR_ROLLBACK')
            archive = self.folder / (old['id'] + '.json')
            if os.path.lexists(archive):
                trusted(archive)
                if not archive.is_file() or json.loads(archive.read_text()) != old:
                    raise Hold('ARCHIVE_CONFLICT')
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
        if resumable_ir:
            d['ir_resumable_version'] = 1
        if ir_inputs is not None:
            d['ir_inputs'] = dict(zip(('domain', 'name'), ir_inputs, strict=True))
            self.ir_inputs(d)
        if archive is not None and not archive.exists():
            self.save(old, destination=archive)
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
                protected = ('nodes', 'tunnels', 'frp_proxy_leases')
                if d.get('ir_inputs'):
                    protected += ('admins',)
                for table in protected:
                    if table in tables and conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]:
                        raise Hold('PANEL_HAS_MANAGED_STATE')
                if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise Hold('DATABASE_INVALID')
            finally:
                conn.close()
        unit = self.root / ('etc/systemd/system/' + SERVICE)
        if unit.exists():
            if d.get('role') != 'panel-iran':
                raise Hold('FOREIGN_BROKER_UNIT')
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

    def ir_inputs(self, d):
        if (d.get('role') != 'panel-iran' or d.get('source') != SOURCE
                or d.get('ir_resumable_version') != 1):
            raise Hold('INVALID_IR_CORE_OWNER')
        values = d.get('ir_inputs') or {}
        domain, name = values.get('domain', ''), values.get('name', '')
        if (not re.fullmatch(r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}', domain)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,62}', name)):
            raise Hold('INVALID_IR_CORE_INPUTS')
        return domain, name

    def panel_witness(self, d):
        domain, _ = self.ir_inputs(d)
        self._ir_container_witness(d, 'smite-panel', IMAGES['smite-panel'])
        directory = self.root / 'opt/smite'
        trusted(directory, True)
        env = directory / '.env'
        trusted(env)
        if (not env.is_file() or env.read_text().splitlines().count('PANEL_DOMAIN=' + domain) != 1):
            raise Hold('IR_PANEL_DOMAIN_DRIFT')

    def ir_commit_panel(self, installer_pid):
        d = self.load()
        if (d['state'] != 'INSTALLING' or d.get('ir_phase') is not None
                or not self.ir_installer_running(d, installer_pid)):
            raise Hold('INVALID_IR_PANEL_COMMIT')
        self.panel_witness(d)
        if {x['name'] for x in self.inspect_owned(d)} != {'smite-panel'}:
            raise Hold('INVALID_IR_PANEL_CONTAINER_SET')
        d['ir_phase'] = 'PANEL_COMMITTED'
        self.save(d)

    def ir_installer_running(self, d, installer_pid):
        return (installer_pid is not None and installer_pid == d.get('installer_pid')
                and d.get('installer_start') and process_start(installer_pid) == d['installer_start'])

    def ir_recover_core(self, installer_pid):
        d = self.load()
        if not d.get('ir_inputs') or d['state'] == 'COMMITTED':
            return
        domain, name = self.ir_inputs(d)
        if (not self.ir_installer_running(d, installer_pid)
                and self.ir_installer_running(d, d.get('installer_pid'))):
            raise Hold('INSTALLER_STILL_RUNNING')
        if d.get('ir_phase') == 'PANEL_COMMITTED':
            config = self.root / 'etc/u-opti/smite/route-broker.json'
            trusted(config)
            gid = json.loads(config.read_text())['peer_gid']
            if type(gid) != int or not 1 <= gid < 65536:
                raise Hold('IR_BROKER_GID_INVALID')
            self.rollback_ir_node(d)
            d.update(installer_pid=installer_pid, installer_start=process_start(installer_pid))
            self.save(d)
            return 'PANEL_COMMITTED', d['id'], domain, name, gid
        if d.get('ir_phase') is not None:
            raise Hold('INVALID_IR_CORE_PHASE')
        if d['state'] != 'ROLLED_BACK':
            # Before the Panel checkpoint the original quarantine is still
            # applicable, but there must be no Node belonging to this run.
            if any(x['name'] == 'smite-node' for x in self.inspect_owned(d)):
                raise Hold('IR_NODE_BEFORE_PANEL_COMMIT')
            self.rollback(installer_pid=installer_pid)
        return 'FRESH_ALLOWED', d['id'], domain, name

    def rollback_ir_node(self, d):
        if d['state'] != 'INSTALLING':
            raise Hold('INVALID_IR_NODE_ROLLBACK_STATE')
        self.panel_witness(d)
        service = self.inactive(d)
        if not service and self.root == Path('/'):
            raise Hold('IR_BROKER_UNIT_MISSING')
        nodes = [x for x in self.inspect_owned(d) if x['name'] == 'smite-node']
        if len(nodes) > 1:
            raise Hold('IR_NODE_OWNERSHIP_AMBIGUOUS')
        plan = d.get('ir_node_rollback')
        if plan is None:
            paths = self.rollback_paths(IR_NODE_TARGETS)
            if not nodes and not paths:
                return
            plan = dict(node=nodes[0]['id'] if nodes else None, paths=paths,
                        suffix='.rc6-rollback-' + d['id'] + '-' + uuid.uuid4().hex)
            d['ir_node_rollback'] = plan
            self.save(d)
        if nodes and nodes[0]['id'] != plan['node']:
            raise Hold('IR_NODE_OWNERSHIP_CHANGED')
        paths = self.verify_rollback_paths(plan['paths'], IR_NODE_TARGETS, plan['suffix'])
        if nodes:
            node = plan['node']
            self.docker('update', '--restart=no', node)
            self.docker('stop', node)
            self.inactive(d)
            # An unpaired attempt has no live identity. Keep all volumes;
            # Compose must not find the removed container by project label.
            self.docker('rm', node)
        if service:
            self.command(['systemctl', 'disable', '--now', SERVICE])
            state = self.command(['systemctl', 'show', SERVICE, '--property=ActiveState,UnitFileState'])
            if set(state.splitlines()) != {'ActiveState=inactive', 'UnitFileState=disabled'}:
                raise Hold('IR_NODE_BROKER_ROLLBACK_UNVERIFIED')
        self.quarantine_paths(paths)
        if any(os.path.lexists(self.root / rel) for rel in IR_NODE_TARGETS):
            raise Hold('IR_NODE_PATHS_REMAIN')
        if any(x['name'] == 'smite-node' for x in self.inspect_owned(d)):
            raise Hold('IR_NODE_CONTAINER_REMAINS')
        del d['ir_node_rollback']
        self.save(d)

    def rollback_paths(self, targets):
        paths = []
        for rel in targets:
            p = self.root / rel
            if os.path.lexists(p):
                st = trusted(p)
                paths.append(dict(path=rel, dev=st.st_dev, ino=st.st_ino))
        return paths

    def verify_rollback_paths(self, items, targets, suffix):
        paths = []
        if not re.fullmatch(r'\.rc6-rollback-uopti_rc6_[a-f0-9]{32}(?:-[a-f0-9]{32})?', suffix):
            raise Hold('INVALID_ROLLBACK_SUFFIX')
        for item in items:
            if item['path'] not in targets:
                raise Hold('INVALID_JOURNAL_PATH')
            p = self.root / item['path']
            dest = p.with_name(p.name + suffix)
            candidates = [x for x in (p, dest) if os.path.lexists(x)]
            if len(candidates) != 1:
                raise Hold('ROLLBACK_PATH_AMBIGUOUS')
            st = trusted(candidates[0])
            if (st.st_dev, st.st_ino) != (item['dev'], item['ino']):
                raise Hold('ROLLBACK_PATH_REPLACED')
            paths.append((p, dest))
        return paths

    def quarantine_paths(self, paths):
        for p, dest in paths:
            if os.path.lexists(p):
                os.rename(p, dest)
                sync_dir(p.parent)

    def rollback(self, *, installer_pid=None):
        d = self.load()
        if (not self.ir_installer_running(d, installer_pid)
                and self.ir_installer_running(d, d.get('installer_pid'))):
            raise Hold('INSTALLER_STILL_RUNNING')
        if d.get('ir_phase') == 'PANEL_COMMITTED':
            self.rollback_ir_node(d)
            return 'IR_NODE_ROLLBACK=PASS_PANEL_RETAINED'
        if d['state'] == 'ROLLED_BACK':
            return 'RC6_ROLLBACK=ALREADY_COMPLETE'
        if d['state'] == 'COMMITTED':
            raise Hold('COMPLETED_INSTALL_NOT_A_ROLLBACK_TARGET')
        if d['state'] == 'INSTALLING':
            containers = self.inspect_owned(d)
            service = self.inactive(d)
            paths = self.rollback_paths(TARGETS)
            for item in paths:
                p = self.root / item['path']
                if os.path.lexists(p.with_name(p.name + '.rc6-rollback-' + d['id'])):
                    raise Hold('ARCHIVE_PATH_CONFLICT')
            d.update(state='ROLLING_BACK', containers=containers, paths=paths, service=service)
            self.save(d)  # Durable plan before stopping or moving anything.
        # Revalidate identities on every retry; never select a replacement by name.
        owned = {x['id']: x for x in self.inspect_owned(d)}
        if set(owned) != {x['id'] for x in d['containers']}:
            raise Hold('CONTAINER_SET_CHANGED')
        paths = self.verify_rollback_paths(d['paths'], TARGETS, '.rc6-rollback-' + d['id'])
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
        self.quarantine_paths(paths)
        if d['service']:
            self.command(['systemctl', 'daemon-reload'])
        d['state'] = 'ROLLED_BACK'; self.save(d)
        return 'RC6_ROLLBACK=PASS_DATA_RETAINED'

    def commit(self):
        d = self.load()
        if d['state'] != 'INSTALLING':
            raise Hold('INVALID_COMMIT_STATE')
        if d.get('ir_inputs'):
            if d.get('ir_phase') != 'PANEL_COMMITTED' or 'ir_node_rollback' in d:
                raise Hold('IR_PANEL_CHECKPOINT_REQUIRED')
            self.panel_witness(d)
            self._ir_container_witness(d, 'smite-node', IMAGES['smite-node'])
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
        if d.get('ir_inputs'):
            domain, name = self.ir_inputs(d)
            if (lines.count('SMITE_PANEL_DOMAIN=' + domain) != 1
                    or lines.count('SMITE_NODE_NAME=' + name) != 1):
                raise Hold('IR_CORE_INPUT_DRIFT')
        d['state'] = 'COMMITTED'
        if d.get('ir_resumable_version') == 1:
            d['ir_phase'] = 'CORE_COMMITTED'
        self.save(d)
        return 'RC6_INSTALL_TRANSACTION=COMMITTED'

    def _ir_witness(self, d):
        """Read-only retained-install proof; never start/recreate containers."""
        if (d.get('state') != 'COMMITTED'
                or d.get('role') != 'panel-iran'
                or d.get('source') != SOURCE
                or d.get('ir_resumable_version') != 1
                or d.get('ir_phase') not in IR_PHASES):
            raise Hold('IR_RESUME_NOT_OWNED_BY_THIS_INSTALL')
        state = self.root / 'etc/u-opti/smite/state.env'
        trusted(state)
        values = {}
        for line in state.read_text().splitlines():
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if not sep or key in values:
                raise Hold('IR_RESUME_STATE_INVALID')
            values[key] = value
        if (values.get('SMITE_ROLE') != 'panel-iran'
                or values.get('SMITE_CONNECTION_MODE') != 'standard'
                or values.get('SMITE_MANAGED_VERSION') != VERSION
                or values.get('SMITE_UPSTREAM_REF') != SOURCE):
            raise Hold('IR_RESUME_STATE_DRIFT')
        names = set(self.docker('ps', '-a', '--format', '{{.Names}}').splitlines())
        if not {'smite-panel', 'smite-node'} <= names:
            raise Hold('IR_RESUME_CONTAINERS_MISSING')
        for name, ref in IMAGES.items():
            self._ir_container_witness(d, name, ref)

    def _ir_container_witness(self, d, name, ref):
        obj = json.loads(self.docker('inspect', name))[0]
        config = obj.get('Config') or {}
        labels = config.get('Labels') or {}
        if (config.get('Image') != ref
                or labels.get('com.docker.compose.project') != d['id']
                or labels.get('com.docker.compose.service') != name
                or not (obj.get('State') or {}).get('Running')
                or (obj.get('State') or {}).get('Health', {}).get('Status', 'healthy') != 'healthy'):
            raise Hold('IR_RESUME_CONTAINER_DRIFT')
        files = labels.get('com.docker.compose.project.config_files')
        base = '/opt/smite/docker-compose.yml' if name == 'smite-panel' else '/opt/smite-node/docker-compose.yml'
        overlay = ('/opt/smite/docker-compose.signed-control.yml' if name == 'smite-panel'
                   else '/opt/smite-node/docker-compose.security-candidate.yml')
        if files not in (base, base + ',' + overlay):
            raise Hold('IR_RESUME_COMPOSE_DRIFT')
        if name == 'smite-node':
            env = dict(line.split('=', 1) for line in config.get('Env', []) if '=' in line)
            auth = env.get('SMITE_NODE_PANEL_AUTH_MODE')
            if auth not in ('paused', 'signed'):
                raise Hold('IR_RESUME_UNKNOWN_NODE_AUTH')
            if (d.get('ir_phase') in IR_PHASES[2:] and auth != 'signed'
                    or auth == 'signed' and env.get('SMITE_AGENT_AUTH_MODE') != 'strict'):
                raise Hold('IR_RESUME_SIGNED_NODE_DRIFT')

    def ir_gateway_recovery_plan(self):
        """Authorize pending Gateway snapshot recovery before Docker health.

        A crash may leave the Node stopped mid-Gateway, so the full
        ir_resume witness runs only AFTER stage compensation completes.
        No untrusted/legacy/foreign journal is adopted here.
        """
        d = self.load()
        if d['state'] == 'ROLLED_BACK':
            return 'FRESH_ALLOWED', None
        if (d.get('state') != 'COMMITTED' or d.get('role') != 'panel-iran'
                or d.get('source') != SOURCE
                or d.get('ir_resumable_version') != 1
                or d.get('ir_phase') not in IR_PHASES):
            raise Hold('IR_GATEWAY_RECOVERY_NOT_ADMITTED')
        if (d.get('installer_start')
                and process_start(d.get('installer_pid')) == d['installer_start']):
            raise Hold('INSTALLER_STILL_RUNNING')
        return d['ir_phase'], d['id']

    def ir_resume(self):
        d = self.load()
        if d['state'] == 'ROLLED_BACK':
            return 'FRESH_ALLOWED', None
        if (d.get('installer_start')
                and process_start(d.get('installer_pid')) == d['installer_start']):
            raise Hold('INSTALLER_STILL_RUNNING')
        self._ir_witness(d)
        return d['ir_phase'], d['id']

    def ir_advance(self, phase):
        if phase not in IR_PHASES:
            raise Hold('INVALID_IR_STAGE')
        d = self.load()
        self._ir_witness(d)
        previous = d['ir_phase']
        if phase == previous:
            return phase
        if IR_PHASES.index(phase) != IR_PHASES.index(previous) + 1:
            raise Hold('IR_STAGE_OUT_OF_ORDER')
        if phase in IR_PHASES[2:]:
            # Completed pairing must be visible in the running Node before
            # a journal claim can be advanced. Existing signed probes occur
            # at the installer boundary, not here.
            obj = json.loads(self.docker('inspect', 'smite-node'))[0]
            env = (obj.get('Config') or {}).get('Env') or []
            if 'SMITE_NODE_PANEL_AUTH_MODE=signed' not in env or 'SMITE_AGENT_AUTH_MODE=strict' not in env:
                raise Hold('IR_PAIRING_RUNTIME_NOT_SIGNED')
        if phase in IR_PHASES[3:] and not self.ir_admin_present():
            raise Hold('IR_ADMIN_NOT_CREATED')
        d['ir_phase'] = phase
        self.save(d)
        return phase

    def ir_admin_present(self):
        """Read-only admin witness: a saved cursor is not proof of an admin."""
        db = self.root / 'opt/smite/panel/data/smite.db'
        if db.is_symlink() or not db.is_file():
            raise Hold('IR_ADMIN_DATABASE_MISSING')
        con = sqlite3.connect(db.absolute().as_uri() + '?mode=ro', uri=True, timeout=2)
        try:
            found = con.execute(
                "SELECT count(*) FROM admins WHERE length(username)>0 AND length(password_hash)>0"
            ).fetchone()[0]
        except sqlite3.Error as exc:
            raise Hold('IR_ADMIN_SCHEMA_MISMATCH') from exc
        finally:
            con.close()
        return found > 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('begin', 'status', 'commit', 'rollback',
                                       'resume-ir', 'advance-ir', 'admin-present', 'gateway-recover-ir',
                                       'prepare', 'recover-ir-core', 'commit-ir-panel'))
    ap.add_argument('--role', choices=('panel-iran', 'foreign'))
    ap.add_argument('--resumable-ir', action='store_true')
    ap.add_argument('--ir-inputs', nargs=2)
    ap.add_argument('--phase', choices=IR_PHASES)
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
                print(j.begin(a.role, a.installer_pid, resumable_ir=a.resumable_ir, ir_inputs=a.ir_inputs))
            elif a.action == 'prepare':
                fd = os.open(j.folder / 'operation.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            elif a.action == 'recover-ir-core':
                if not a.installer_pid or not process_start(a.installer_pid):
                    raise Hold('INSTALLER_PROCESS_REQUIRED')
                recovery = j.ir_recover_core(a.installer_pid)
                if recovery is not None:
                    print(*recovery, sep='\n')
            elif a.action == 'commit-ir-panel':
                j.ir_commit_panel(a.installer_pid)
            elif a.action == 'status':
                d=j.load()
                print('RC6_INSTALL_TRANSACTION=' + d['state'])
                if d.get('ir_resumable_version') == 1:
                    print('IR_OPTION_1_STAGE=' + d.get('ir_phase','CORE_NOT_VERIFIED'))
            elif a.action == 'commit':
                print(j.commit())
            elif a.action == 'gateway-recover-ir':
                stage, project = j.ir_gateway_recovery_plan()
                print('IR_GATEWAY_RECOVERY_STAGE=' + stage)
                if project is not None:
                    print('IR_GATEWAY_RECOVERY_PROJECT=' + project)
            elif a.action == 'resume-ir':
                stage, project = j.ir_resume()
                print('IR_INSTALL_STAGE=' + stage)
                if project is not None:
                    print('IR_INSTALL_PROJECT=' + project)
            elif a.action == 'advance-ir':
                if a.phase is None: raise Hold('IR_STAGE_REQUIRED')
                print('IR_INSTALL_STAGE=' + j.ir_advance(a.phase))
            elif a.action == 'admin-present':
                j._ir_witness(j.load())
                if j.ir_admin_present():
                    print('IR_ADMIN_PRESENT=VERIFIED_READ_ONLY')
                else:
                    print('IR_ADMIN_PRESENT=ABSENT_READ_ONLY')
                    return 3
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
