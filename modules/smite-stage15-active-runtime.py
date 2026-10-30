#!/usr/bin/env python3
"""IR Panel-only active-owner migration. Never recreate Node or restore live DBs.

A schema-1 receipt extends (never edits) the original WSS journal. Broker
admission is closed for every incomplete phase, including after host reboot.
"""
import argparse
import base64
import copy
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import socket
import stat
import errno
import sys
import time

HERE = Path(__file__).resolve().parent

def load(name, filename):
    loader = importlib.machinery.SourceFileLoader(name, str(HERE / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module
    loader.exec_module(module)
    return module

w = load('active_wss', 'smite-stage15-wss.py')
h = w.host
need = h.require
b = load('active_broker', 'smite-rc5-xhttp-root-broker.py')
p = load('active_provision', 'smite-rc5-xhttp-broker-provision.py')
v = load('active_bundle', 'smite-stage15-bundle-verify.py')
STATE = Path('/var/lib/u-opti/smite-stage15-active-runtime')
SOURCE = '8edbd4032ae657fe2bb38cd9b3290de5f1e07a54'
MANIFEST = '67672e362686b886a6e5653055ad808d1d878c514ee2e6c2f75f310eb77ef4cb'
ARCHIVE = '7b3d3172788d62f7d60f7103965e04db0df01606c4bc8d03760f904006ecf7c3'
INDEX = 'sha256:4abfd55d5c18d95119f8bae4c790cb2b687c54355836ea5529c8aff8a53dcd09'
CONFIG_ID = 'sha256:9e88d664bd42e5c1ccb09bfe36d22cce9c0ee84d3a0e44146ffacd2542307f06'
OLD = w.REVIEWED_IMAGES['panel']
DB = w.PANEL / 'panel/data/smite.db'
UNIT = Path("/etc/systemd/system") / p.SERVICE_NAME
TARGETS = (b.HELPER, b.PLANNER, b.CONFIG, UNIT)
MODES = (0o755, 0o755, 0o600, 0o644)
PHASES = ('PREPARING', 'BACKED_UP', 'CUTOVER', 'READY', 'COMMITTED', 'RECOVERING', 'RESTORED', 'ROLLED_BACK')


def canonical(doc): return (json.dumps(doc, sort_keys=True) + '\n').encode()
def encode(raw): return base64.b64encode(raw).decode('ascii')
def decode(raw): return base64.b64decode(raw, validate=True)
def present(path): return path.exists() or path.is_symlink()


def preserved_unit(raw):
    return raw.replace(b"RuntimeDirectoryMode=0750\n", b"RuntimeDirectoryMode=0750\nRuntimeDirectoryPreserve=yes\n")

def target_bytes(doc, side, path):
    # Keep the socket directory inode across stop/restart, including rollback.
    # Reverting this one service setting would orphan the unchanged Node bind.
    if path == UNIT and doc["backups"]: side = "after"
    return decode(doc[side][str(path)])

def validate(doc):
    need(set(doc) == {'schema', 'phase', 'source', 'wss_sha', 'runtime', 'protected', 'before', 'after', 'backups'}, 'RUNTIME_RECEIPT_FIELDS')
    need(doc['schema'] == 1 and doc['phase'] in PHASES and doc['source'] == SOURCE, 'RUNTIME_RECEIPT_VERSION')
    need(doc['runtime']['image'] == OLD, 'ORIGINAL_IMAGE_DRIFT')
    for side in ('before', 'after'):
        need(set(doc[side]) == {str(x) for x in TARGETS}, 'RUNTIME_TARGET_SET')
        for path in TARGETS:
            need(0 < len(decode(doc[side][str(path)])) < 100000, 'RUNTIME_TARGET_SIZE')
    old = json.loads(decode(doc['before'][str(b.CONFIG)]))
    new = json.loads(decode(doc['after'][str(b.CONFIG)]))
    unit = p._service_unit(old['peer_gid'])
    need(decode(doc['before'][str(UNIT)]) in (unit, preserved_unit(unit))
         and decode(doc['after'][str(UNIT)]) == preserved_unit(unit), 'BROKER_UNIT_MIGRATION_DRIFT')
    need(new == dict(old, helper_sha256=p.HELPER_SHA256, planner_sha256=p.PLANNER_SHA256), 'BROKER_CONFIG_MIGRATION_DRIFT')
    for target, field, expected in [(b.HELPER, 'helper_sha256', p.HELPER_SHA256), (b.PLANNER, 'planner_sha256', p.PLANNER_SHA256)]:
        need(h.digest(decode(doc['before'][str(target)])) == old[field]
             and h.digest(decode(doc['after'][str(target)])) == expected, 'WORKER_RECEIPT_HASH_DRIFT')
    need(set(doc['backups']) in (set(), {'panel.before.tar', 'panel.before.sqlite3', 'panel.candidate.tar.gz'}), 'BACKUP_SET_DRIFT')
    if doc['phase'] not in ('PREPARING', 'ROLLED_BACK'):
        need(bool(doc['backups']), 'VERIFIED_BACKUPS_REQUIRED')
    return doc


def record():
    h.directory(STATE, private=True)
    return validate(json.loads(h.file(STATE / 'record.json', mode=0o600, limit=1000000)))


def save(doc):
    validate(doc)
    writer = load('active_writer', 'smite-rc5-xhttp-bridge-install.py')
    writer.replace_file(STATE / 'record.json', canonical(doc), 0o600)


def admission():
    """Called by Broker before serving/dispatch; incomplete state never falls back."""
    if not present(STATE): return
    doc = record()
    need(doc['phase'] in ('COMMITTED', 'ROLLED_BACK'), 'ACTIVE_RUNTIME_RECOVERY_REQUIRED')
    Host().files(doc, 'after' if doc['phase'] == 'COMMITTED' else 'before')


def expectation(wss_doc, image):
    doc = record()
    need(doc['phase'] in ('COMMITTED', 'ROLLED_BACK'), 'ACTIVE_RUNTIME_RECOVERY_REQUIRED')
    need(h.digest(h.file(w.STATE / 'record.json', mode=0o600, limit=262144)) == doc['wss_sha']
         and wss_doc['runtime']['panel'] == doc['runtime'], 'WSS_RECEIPT_BINDING_DRIFT')
    allowed = {INDEX, CONFIG_ID} if doc['phase'] == 'COMMITTED' else {OLD}
    need(image in allowed, 'UNREVIEWED_MIGRATED_IMAGE')
    expected = copy.deepcopy(doc['runtime']); expected['image'] = image
    return expected


def execute(host, action, folder=None):
    """Crash-resumable coordinator. Recovery rolls back; never retries an Apply."""
    if action == 'plan': return host.plan(folder)
    if action == 'apply':
        doc = host.plan(folder)
        host.begin(doc)
        host.backup(doc, folder)
        doc['phase'] = 'BACKED_UP'; host.save(doc)
        host.check(doc); host.preserve_socket(doc); host.broker(False)
        doc['phase'] = 'CUTOVER'; host.save(doc)
        host.load_image(doc)
        host.check(doc); host.install(doc, 'after')
        host.panel(doc, True)
        host.health(doc, True); host.files(doc, 'after')
        doc['phase'] = 'READY'; host.save(doc)
        # Publish committed admission only after all checks. Restart failure is
        # recoverable; no route can pass while the coordinator holds engine lock.
        doc['phase'] = 'COMMITTED'; host.save(doc)
        host.broker(True)
        return doc
    doc = host.record()
    if action == 'verify':
        need(doc['phase'] == 'COMMITTED', 'RUNTIME_NOT_COMMITTED')
        host.health(doc, True); host.files(doc, 'after'); host.broker_check()
        return doc
    need(action in ('rollback', 'recover'), 'UNKNOWN_RUNTIME_ACTION')
    host.check(doc); host.recoverable(doc)
    if doc['phase'] == 'PREPARING' or (doc['phase'] == 'ROLLED_BACK' and not doc['backups']):
        # No target mutation is possible before durable BACKED_UP. Keep partial
        # backups for audit; do not restore any image, configuration or DB.
        host.files(doc, 'before'); host.health(doc, False)
        doc['phase'] = 'ROLLED_BACK'; host.save(doc)
        host.broker_check()
        return doc
    host.preserve_socket(doc); host.broker(False)
    doc['phase'] = 'RECOVERING'; host.save(doc)
    host.install(doc, 'before'); host.panel(doc, False)
    host.health(doc, False); host.files(doc, 'before')
    doc['phase'] = 'RESTORED'; host.save(doc)
    doc['phase'] = 'ROLLED_BACK'; host.save(doc)
    host.broker(True)
    return doc


class Host:
    def record(self): return record()
    def save(self, doc): save(doc)

    def db_facts(self):
        h.file(DB, limit=256*1024*1024)
        with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'PANEL_DB_CORRUPT')
            rows = db.execute('SELECT id,core,type,status,spec,node_id,iran_node_id,foreign_node_id FROM tunnels').fetchall()
            need(len(rows) == 1 and rows[0][1:4] == ('frp', 'tcp', 'active'), 'ONE_ACTIVE_OWNER_REQUIRED')
            spec = json.loads(rows[0][4]); ports = spec.get('ports')
            need(isinstance(ports, list) and len(ports) == 1 and type(ports[0]) is int and 1024 <= ports[0] <= 65535
                 and ports[0] != 7000 and spec.get('bind_port') == 7000 and not spec.get('shared_frps_owner')
                 and spec.get('local_ip', '127.0.0.1') == '127.0.0.1', 'OWNER_SPEC_UNAPPROVED')
            need(db.execute('SELECT count(*) FROM frp_proxy_leases').fetchone()[0] == 0, 'CHILD_LEASE_PRESENT')
            for key, raw in db.execute('SELECT key,value FROM settings'):
                if key not in ('frp', 'tunnel'): continue
                value = (json.loads(raw) if raw is not None else None) or {}
                if key == 'frp': need(isinstance(value, dict) and not value.get('enabled'), 'LEGACY_FRP_ENABLED')
                if key == 'tunnel': need(isinstance(value, dict) and not value.get('auto_reapply_enabled'), 'AUTO_REAPPLY_ENABLED')
            need(db.execute('SELECT count(*) FROM core_reset_config WHERE enabled=1').fetchone()[0] == 0, 'CORE_RESET_ENABLED')
            schema = db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        return dict(owner=rows[0][0], port=ports[0], rows_sha=h.digest(canonical(rows)), schema_sha=h.digest(canonical(schema)))

    def node_tunnel_storage(self, node):
        """Bind the existing tunnel registry to the mounted, persistent Node volume.

        The running Node writes /var/lib/smite-node/tunnels.json, NOT the
        /etc/smite-node config bind (/opt/smite-node/config on the host).
        Never synthesize or copy a missing registry, and never trust a path
        supplied by a tunnel request.
        """
        mounts = [item for item in node['Mounts']
                  if item.get('Destination') == '/var/lib/smite-node']
        need(len(mounts) == 1, 'NODE_TUNNEL_VOLUME_MOUNT_REQUIRED')
        mount = mounts[0]
        need(mount.get('Type') == 'volume' and mount.get('Name') == 'smite-node-data'
             and mount.get('RW') is True and isinstance(mount.get('Source'), str),
             'NODE_TUNNEL_VOLUME_UNTRUSTED')
        source = Path(mount['Source'])
        need(source.is_absolute() and '..' not in source.parts
             and source.name == '_data' and source.parent.name == mount['Name'],
             'NODE_TUNNEL_VOLUME_SOURCE_UNTRUSTED')
        h.directory(source)
        registry = source / 'tunnels.json'
        content = h.file(registry, limit=1048576)
        info = registry.lstat()
        # Pin inode as well as bytes: a registry replaced during migration is
        # drift even when a replacement happens to contain identical bytes.
        return {'path': str(registry), 'sha': h.digest(content),
                'inode': [info.st_dev, info.st_ino]}

    def protected(self):
        facts = self.db_facts(); node = w.inspect('node'); w.runtime('node', node, True)
        sys.path.insert(0, str(HERE))
        worker = load('active_socket_worker', 'smite-xhttp-nginx-route')
        pid, ports = worker._frps_socket_inventory()
        need(ports == frozenset({7000, facts['port']}), 'OWNER_SOCKET_DRIFT')
        need(set(re.findall(r'"frps",pid=(\d+)', h.run(['ss', '-Hlntp']))) == {str(pid)}, 'DUPLICATE_FRPS')
        start = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        files = {}
        for path in (w.STATE / 'record.json', Path('/var/lib/u-opti/smite-stage15-wss-edge/record.json'),
                     b.KEY,
                     w.overlay('panel'), w.overlay('node')):
            files[str(path)] = h.digest(h.file(path, limit=262144))
        tunnel_storage = self.node_tunnel_storage(node)
        trusted = Path('/etc/u-opti/smite/panel-trusted-nodes'); h.directory(trusted)
        for path in sorted(trusted.iterdir()): files[str(path)] = h.digest(h.file(path, limit=262144))
        ledger = b.LEDGER; h.file(ledger, mode=0o600, limit=80*1024*1024)
        st = ledger.stat()
        h.run(['nginx', '-t'])
        return dict(db=facts, node_id=node['Id'], node_pid=node['State']['Pid'], node_runtime=w.signature(node),
                    frp_processes=h.run(['ps', '-C', 'frps,frpc', '-o', 'pid=,comm=,lstart=']),
                    owner_pid=pid, owner_start=start, files=files, node_tunnel_storage=tunnel_storage,
                    broker_replay_inode=[st.st_dev, st.st_ino],
                    socket_dir_inode=[b.SOCKET.parent.stat().st_dev, b.SOCKET.parent.stat().st_ino],
                    nginx=h.digest(h.run(['nginx', '-T']).encode()), signed=w.protected(['panel', 'node']))

    def check(self, doc):
        need(self.protected() == doc['protected'], 'ACTIVE_OWNER_OR_PROTECTED_STATE_DRIFT')
        self.empty_routes()

    def empty_routes(self):
        # Runtime rollback is intentionally before first route/bridge publication.
        b._dir(b.GRANTS, mode=0o700)
        need(not any(b.GRANTS.iterdir()), 'REMOVE_GRANTS_BEFORE_RUNTIME_CHANGE')
        routes = Path('/etc/nginx/smite-xhttp-routes'); h.directory(routes)
        need(not any(routes.iterdir()), 'REMOVE_ROUTES_BEFORE_RUNTIME_CHANGE')
        need(not present(Path('/etc/nginx/smite-xhttp-bridge.conf')), 'ROLLBACK_BRIDGE_BEFORE_RUNTIME_CHANGE')

    def signed_owner(self, doc):
        # Local signed GET only: same identity, fresh nonce; unsigned and replay
        # rejected. Does not apply/delete/restart any tunnel or FRP process.
        probe = h.SIGNED_CHECK.replace('target="/api/agent/engines"', 'target="/api/agent/frp/owners"')
        probe = probe.replace('check(data["mode"]=="managed" and data["engines"]["frp"]==expected)',
            'check(data["owners"]==json.loads(expected))')
        expected = [dict(tunnel_id=doc['protected']['db']['owner'], control_port=7000, proxy_ports=[doc['protected']['db']['port']])]
        result = h.run(['docker', 'exec', 'smite-node', 'python', '-c', probe, json.dumps(expected)])
        need(result == 'SIGNED_FRP_INVENTORY=PASS', 'SIGNED_OWNER_PROOF_FAILED')

    def plan(self, folder):
        need(not present(STATE), 'EXISTING_RUNTIME_TRANSACTION')
        old = w.read_record(); need(old['state'] == 'COMMITTED' and old['roles'] == ['panel', 'node'], 'IR_WSS_REQUIRED')
        w.health(old, True)
        edge = load('active_edge', 'smite-stage15-wss-edge.py'); edge.verify(edge.state())
        self.empty_routes()
        bundle = v.verify(folder=folder, source_sha=SOURCE, manifest_sha=MANIFEST)
        item = bundle['images']['panel']; need(item['local_image_id'] == INDEX and item['archive_sha256'] == ARCHIVE, 'WRONG_PANEL_ARTIFACT')
        proof = v.inspect_archive(folder / item['file'], role='panel', source_sha=SOURCE, image_id=INDEX)
        need(proof['config_id'] == CONFIG_ID and proof['index_id'] == INDEX, 'WRONG_PANEL_CONTENT')
        config = b._configuration(); b._verify_helper(config); self.broker_check()
        need(h.run(['systemctl', 'show', p.SERVICE_NAME, '--property=DropInPaths', '--value']) == '', 'BROKER_UNIT_DROPINS_UNREVIEWED')
        need(h.run(['systemctl', 'show', p.SERVICE_NAME, '--property=FragmentPath', '--value']) == str(UNIT), 'BROKER_UNIT_SOURCE_DRIFT')
        panel = w.inspect('panel'); node = w.inspect('node')
        need(w.signature(panel) == old['runtime']['panel'], 'PANEL_SIGNATURE_DRIFT')
        mounts = {x['Destination']: x for x in panel['Mounts']}
        mount = mounts.get('/run/secrets/smite-uopti-xhttp-broker.key', {})
        need(mount.get('Source') == str(b.KEY) and mount.get('RW') is False, 'PANEL_BROKER_KEY_MOUNT_MISSING')
        env = w.environment(node)
        directory_id = b.SOCKET.parent.stat().st_ino
        mounted_id = h.run(['docker', 'exec', 'smite-node', 'python', '-c', "import os; print(os.stat('/run/u-opti/smite').st_ino)"])
        need(mounted_id == str(directory_id), 'NODE_SOCKET_DIRECTORY_ALREADY_ORPHANED')
        need(env.get('SMITE_UOPTI_ROUTE_BROKER_ENABLED') == 'true', 'NODE_FORWARDING_DISABLED')
        need(node['Config'].get('User') == str(config['peer_uid']) + ':' + str(config['peer_gid']), 'NODE_BROKER_PEER_DRIFT')
        mounts = {x['Destination']: x for x in node['Mounts']}
        socket_mount = mounts.get('/run/u-opti/smite', {})
        need(socket_mount.get('Source') == '/run/u-opti/smite' and socket_mount.get('RW') is False
             and socket_mount.get('Type') == 'bind', 'NODE_BROKER_SOCKET_MOUNT_MISSING')
        need(h.run(['docker', 'image', 'inspect', OLD, '--format', '{{.Id}}']) == OLD, 'OLD_IMAGE_MISSING')
        before = {str(path): encode(b._file(path, mode=mode, max_size=100000)) for path, mode in zip(TARGETS, MODES)}
        after = dict(before)
        for path, filename, field, digest in [(b.HELPER, p.HELPER_MODULE, 'helper_sha256', p.HELPER_SHA256), (b.PLANNER, p.PLANNER_MODULE, 'planner_sha256', p.PLANNER_SHA256)]:
            raw = h.file(HERE / filename); need(h.digest(raw) == digest, 'SOURCE_PIN_MISMATCH')
            after[str(path)] = encode(raw); config[field] = digest
        after[str(b.CONFIG)] = encode(canonical(config))
        after[str(UNIT)] = encode(preserved_unit(p._service_unit(config['peer_gid'])))
        doc = dict(schema=1, phase='PREPARING', source=SOURCE, runtime=old['runtime']['panel'],
                   wss_sha=h.digest(h.file(w.STATE / 'record.json', mode=0o600, limit=262144)),
                   protected=self.protected(), before=before, after=after, backups={})
        self.signed_owner(doc); self.check(doc)
        return validate(doc)

    def begin(self, doc):
        need(shutil.disk_usage(STATE.parent).free >= 2*1024**3, 'BACKUP_SPACE_REQUIRED')
        # Publish the initial directory only after its complete receipt is durable.
        # A kill before rename leaves an inert private staging directory, never
        # an active transaction without before-images.
        stage = Path(__import__('tempfile').mkdtemp(prefix='.smite-active-prepare-', dir=STATE.parent))
        h.directory(stage, private=True)
        h.new_file(stage / 'record.json', canonical(validate(doc)), 0o600)
        need(not present(STATE), 'EXISTING_RUNTIME_TRANSACTION')
        os.rename(stage, STATE); h.flush(STATE.parent)

    def backup(self, doc, folder):
        w.backup_panel(STATE / 'panel.before.sqlite3')
        archive = STATE / 'panel.before.tar'; h.new_file(archive, b'', 0o600)
        h.run(['docker', 'save', '-o', str(archive), OLD], timeout=240)
        # Reuse only the verified streaming copy primitive, never the old upgrader.
        copier = load('active_copy', 'smite-stage15-upgrade.py')
        copier.copy_archive(folder / v.FILES['panel'], STATE / 'panel.candidate.tar.gz', ARCHIVE)
        for name in ('panel.before.tar', 'panel.before.sqlite3', 'panel.candidate.tar.gz'):
            path = STATE / name
            with path.open('rb') as stream: os.fsync(stream.fileno())
            doc['backups'][name] = file_sha(path)
        h.flush(STATE)
        self.check(doc)

    def preserve_socket(self, doc):
        self.check(doc); self.recoverable(doc)
        p._replace_existing_trusted_file(UNIT, decode(doc['after'][str(UNIT)]), 0o644)
        h.run(['systemctl', 'daemon-reload'])
        need(h.run(['systemctl', 'show', p.SERVICE_NAME, '--property=RuntimeDirectoryPreserve', '--value']) == 'yes', 'SOCKET_DIRECTORY_PRESERVATION_REQUIRED')

    def broker_check(self):
        need(h.run(['systemctl', 'is-active', p.SERVICE_NAME]) == 'active', 'BROKER_NOT_ACTIVE')

    def broker(self, enabled):
        config = json.loads(h.file(b.CONFIG, mode=0o600))
        gid = config['peer_gid']
        before = socket_identity(b.SOCKET, gid) if not enabled else None
        h.run(['systemctl', 'restart' if enabled else 'stop', p.SERVICE_NAME])
        if enabled:
            self.broker_check()
            p._wait_for_broker_socket(b.SOCKET.parent, gid)
        else:
            need(h.run(['systemctl', 'show', p.SERVICE_NAME, '--property=ActiveState', '--value']) == 'inactive'
                 and h.run(['systemctl', 'show', p.SERVICE_NAME, '--property=MainPID', '--value']) == '0', 'BROKER_NOT_STOPPED')
            remove_stopped_socket(b.SOCKET, before, gid)

    def files(self, doc, side):
        for path, mode in zip(TARGETS, MODES):
            need(b._file(path, mode=mode, max_size=100000) == target_bytes(doc, side, path), 'BROKER_TARGET_DRIFT')

    def recoverable(self, doc):
        self.panel_state(doc)
        for path, mode in zip(TARGETS, MODES):
            raw = b._file(path, mode=mode, max_size=100000)
            need(raw in (decode(doc['before'][str(path)]), decode(doc['after'][str(path)])), 'EXTERNAL_BROKER_DRIFT')
        if doc['phase'] == 'PREPARING': return
        for name, digest in doc['backups'].items():
            need(file_sha(STATE / name) == digest, 'BACKUP_DIGEST_DRIFT')
        need(doc['backups']['panel.candidate.tar.gz'] == ARCHIVE, 'CANDIDATE_BACKUP_DRIFT')
        backup = STATE / 'panel.before.sqlite3'
        with sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True) as db:
            need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'BACKUP_CORRUPT')
        # Require the original immutable image to remain locally available.
        # Never silently load an unverified replacement during recovery.
        need(h.run(['docker', 'image', 'inspect', OLD, '--format', '{{.Id}}']) == OLD, 'OLD_IMAGE_MISSING')

    def load_image(self, doc):
        self.recoverable(doc)
        h.run(['docker', 'load', '-i', str(STATE / 'panel.candidate.tar.gz')], timeout=240)
        obj = json.loads(h.run(['docker', 'image', 'inspect', 'smite-panel:stage15-local']))[0]
        need(obj['Id'] in (INDEX, CONFIG_ID) and obj['Config']['Labels']['org.opencontainers.image.revision'] == SOURCE, 'LOADED_IMAGE_PROVENANCE_DRIFT')

    def install(self, doc, side):
        self.check(doc); self.recoverable(doc)
        for path, mode in zip(TARGETS, MODES):
            p._replace_existing_trusted_file(path, target_bytes(doc, side, path), mode)
        self.files(doc, side)

    def panel_state(self, doc):
        # Inspect all existing Panel security fields before touching its tag.
        # Missing container after interrupted compose is allowed only after CUTOVER.
        names = h.run(['docker', 'ps', '-a', '--filter', 'name=^/smite-panel$', '--format', '{{.Names}}'])
        need(names in ('', 'smite-panel'), 'AMBIGUOUS_PANEL_CONTAINER')
        obj = None
        if names:
            obj = w.inspect('panel'); w.runtime('panel', obj, True, healthy=False, allowed_images={OLD, INDEX, CONFIG_ID})
            expected = copy.deepcopy(doc['runtime']); expected['image'] = obj['Image']
            need(w.signature(obj) == expected, 'PANEL_SECURITY_DRIFT')
        else: need(doc['phase'] in ('CUTOVER', 'RECOVERING'), 'PANEL_MISSING_OUTSIDE_CUTOVER')
        return names, obj

    def panel(self, doc, new):
        self.check(doc)
        names, obj = self.panel_state(doc)
        image = OLD
        if new:
            candidate = json.loads(h.run(['docker', 'image', 'inspect', 'smite-panel:stage15-local']))[0]
            need(candidate['Id'] in (INDEX, CONFIG_ID), 'CANDIDATE_TAG_DRIFT'); image = candidate['Id']
        h.run(['docker', 'tag', image, 'smite-panel:stage15-local'])
        if not names or obj['Image'] != image or not obj['State']['Running']:
            h.run(w.compose('panel', True, ['up', '-d', '--no-build', '--no-deps', '--pull', 'never', '--force-recreate', 'smite-panel']), timeout=150)
        self.check(doc)

    def health(self, doc, new):
        self.check(doc)
        allowed = {INDEX, CONFIG_ID} if new else {OLD}
        for attempt in range(20):
            try:
                obj = w.inspect('panel'); w.runtime('panel', obj, True, allowed_images=allowed)
                expected = copy.deepcopy(doc['runtime']); expected['image'] = obj['Image']
                need(w.signature(obj) == expected, 'PANEL_SECURITY_DRIFT'); break
            except h.Hold:
                if attempt == 19: raise
                time.sleep(3)
        self.signed_owner(doc); h.signed_inventory('ready')
        dns = doc['runtime']['env']['PANEL_DOMAIN']
        h.run(['curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '12', '--resolve', dns + ':443:127.0.0.1', '--output', '/dev/null', 'https://' + dns + '/'], timeout=18)
        self.check(doc)


def socket_identity(path, gid):
    if not present(path): return None
    info = path.lstat()
    need(stat.S_ISSOCK(info.st_mode) and info.st_uid == 0 and info.st_gid == gid
         and stat.S_IMODE(info.st_mode) == 0o660 and info.st_nlink == 1, 'UNTRUSTED_BROKER_SOCKET')
    return (info.st_dev, info.st_ino)


def remove_stopped_socket(path, before, gid):
    """Only after systemd proves service inactive/MainPID=0. No live socket unlink."""
    if not present(path): return
    need(before is not None and socket_identity(path, gid) == before, 'BROKER_SOCKET_REPLACED')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        try:
            connection.connect(str(path))
        except OSError as exc:
            need(exc.errno == errno.ECONNREFUSED, 'BROKER_SOCKET_STATE_UNCERTAIN')
        else:
            raise h.Hold('BROKER_SOCKET_STILL_LISTENING')
    need(socket_identity(path, gid) == before, 'BROKER_SOCKET_REPLACED')
    path.unlink(); h.flush(path.parent)


def file_sha(path):
    h.trusted_parents(path)
    st = path.lstat()
    need(__import__('stat').S_ISREG(st.st_mode) and st.st_uid == 0 and st.st_nlink == 1
         and st.st_mode & 0o777 == 0o600 and st.st_size > 0, 'UNTRUSTED_BACKUP')
    digest = hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        opened = os.fstat(stream.fileno()); need((opened.st_dev, opened.st_ino) == (st.st_dev, st.st_ino), 'BACKUP_RACE')
        for block in iter(lambda: stream.read(1048576), b''): digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply', 'verify', 'recover', 'rollback'])
    parser.add_argument('--images', type=Path)
    args = parser.parse_args()
    try:
        need(os.geteuid() == 0 and os.uname().nodename.split('.')[0].lower() == 'ir', 'IR_ROOT_ONLY')
        if args.action in ('plan', 'apply'):
            need(args.images is not None and args.images.is_absolute(), 'ABSOLUTE_IMAGE_FOLDER_REQUIRED')
        if args.action in ('apply', 'recover', 'rollback'):
            need(sys.stdin.isatty(), 'INTERACTIVE_ROOT_APPROVAL_REQUIRED')
            challenge = args.action.upper() + '-IR-PANEL-ONLY-SNAPSHOT-CONSOLE'
            need(input('Type ' + challenge + ': ') == challenge, 'OPERATOR_CANCELLED')
        with h.exclusive(w.LOCK): execute(Host(), args.action, args.images)
        print('STAGE15_ACTIVE_RUNTIME_' + args.action.upper() + '=PASS')
        print('NODE_RECREATE=NO\nFRP_REAPPLY=NO\nLIVE_DATABASE_RESTORE=NO')
        return 0
    except Exception as exc:
        message = str(exc)
        print('HOLD: ' + (message if re.fullmatch('[A-Z0-9_]{1,100}', message) else 'ACTIVE_RUNTIME_REVIEW_REQUIRED'), file=sys.stderr)
        return 2

if __name__ == '__main__': raise SystemExit(main())
