"""Real private files/SQLite and journal recovery with simulated host boundaries.

No Docker/host-service execution. The fault injector models abrupt process loss,
including inside the multi-file pin transaction. Existing FRP identity must hold.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('migration_test', ROOT/'modules/smite-stage15-active-runtime.py')
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)

class Crash(BaseException): pass

class Fixture(m.Host):
    def __init__(self, root):
        self.root=root; self.operations=[]; self.fail=None; self.count=0
        self.image=m.OLD; self.broker_active=True; self.pid=31515
        self.key=root/'identity'; self.key.write_bytes(b'test-only-signed-identity'); self.key.chmod(0o600)
        self.replay=root/'replay.sqlite3'
        with sqlite3.connect(self.replay) as db: db.execute('CREATE TABLE nonces (nonce TEXT PRIMARY KEY)')
        self.replay.chmod(0o600)
        self.original_inode=self.replay.stat().st_ino
        config=dict(schema=1, instance_id='broker-test-0001', peer_uid=0, peer_gid=39100,
                    helper_sha256=m.h.digest(b'old worker'), planner_sha256=m.h.digest(b'old planner'))
        before=[b'old worker',b'old planner',m.canonical(config),m.p._service_unit(39100)]
        after_config=dict(config, helper_sha256=m.p.HELPER_SHA256,planner_sha256=m.p.PLANNER_SHA256)
        after=[(ROOT/'modules'/m.p.HELPER_MODULE).read_bytes(),(ROOT/'modules'/m.p.PLANNER_MODULE).read_bytes(),m.canonical(after_config),m.preserved_unit(before[3])]
        for target, raw, mode in zip(m.TARGETS,before,m.MODES):target.write_bytes(raw);target.chmod(mode)
        self.doc=dict(schema=1,phase='PREPARING',source=m.SOURCE,wss_sha='a'*64,runtime={'image':m.OLD},
                      protected=self.protected(),before={str(p):m.encode(x) for p,x in zip(m.TARGETS,before)},
                      after={str(p):m.encode(x) for p,x in zip(m.TARGETS,after)},backups={})
    def point(self,name):
        self.operations.append(name);self.count+=1
        if self.fail==self.count:raise Crash(name)
    def plan(self,folder):return m.validate(copy.deepcopy(self.doc))
    def begin(self,doc):m.STATE.mkdir(mode=0o700);m.save(doc);self.point('begin')
    def save(self,doc):m.save(doc);self.point('save:'+doc['phase'])
    def backup(self,doc,folder):
        for name,data in [('panel.before.tar',b'old-image'),('panel.before.sqlite3',b'consistent-test-backup'),('panel.candidate.tar.gz',b'new-image')]:
            path=m.STATE/name;path.write_bytes(data);path.chmod(0o600);doc['backups'][name]=m.file_sha(path)
        self.point('backup')
    def protected(self):return dict(owner_pid=self.pid,identity=m.h.digest(self.key.read_bytes()),replay_inode=self.replay.stat().st_ino)
    def check(self,doc):m.need(self.protected()==doc['protected'],'PROTECTED_DRIFT');self.point('check')
    def recoverable(self,doc):
        for path,mode in zip(m.TARGETS,m.MODES):
            raw=m.b._file(path,mode=mode,max_size=100000)
            m.need(raw in (m.decode(doc['before'][str(path)]),m.decode(doc['after'][str(path)])),'EXTERNAL_DRIFT')
        if doc['phase']!='PREPARING':
            for name,digest in doc['backups'].items():m.need(m.file_sha(m.STATE/name)==digest,'BACKUP_DRIFT')
        self.point('recoverable')
    def preserve_socket(self,doc):
        self.check(doc);self.recoverable(doc)
        m.p._replace_existing_trusted_file(m.UNIT,m.decode(doc['after'][str(m.UNIT)]),0o644)
        self.point('preserve-socket')
    def broker(self,enabled):self.broker_active=enabled;self.point('broker:'+str(enabled))
    def broker_check(self):m.need(self.broker_active,'BROKER_INACTIVE')
    def load_image(self,doc):self.recoverable(doc);self.point('load-image')
    def install(self,doc,side):
        self.recoverable(doc)
        for target,mode in zip(m.TARGETS,m.MODES):
            m.p._replace_existing_trusted_file(target,m.target_bytes(doc,side,target),mode)
            self.point('replace:'+target.name)
        self.files(doc,side)
    def panel(self,doc,new):self.image=m.CONFIG_ID if new else m.OLD;self.point('panel:'+str(new))
    def health(self,doc,new):
        self.check(doc);m.need(self.image==(m.CONFIG_ID if new else m.OLD),'WRONG_IMAGE')
        # Real durable nonce DB: acceptance once then rejection; never restored.
        with sqlite3.connect(self.replay) as db:
            nonce=__import__('secrets').token_hex(16);db.execute('INSERT INTO nonces VALUES (?)',(nonce,))
            try:db.execute('INSERT INTO nonces VALUES (?)',(nonce,))
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('Replay accepted')
        self.point('health')

@unittest.skipUnless(os.geteuid()==0,'root-owned fixture')
class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.root.chmod(0o700)
        targets=tuple(self.root/x for x in ('worker','planner','config','unit'))
        for module,name,value in [(m,'STATE',self.root/'transaction'),(m,'TARGETS',targets),(m,'UNIT',targets[3]),
                                  (m.b,'HELPER',targets[0]),(m.b,'PLANNER',targets[1]),(m.b,'CONFIG',targets[2])]:
            patcher=patch.object(module,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.host=Fixture(self.root)
    def test_success_then_verified_rollback_preserves_owner_identity_and_replay(self):
        identity=self.host.key.read_bytes();m.execute(self.host,'apply');self.assertEqual(m.record()['phase'],'COMMITTED')
        m.admission();m.execute(self.host,'verify')
        with sqlite3.connect(self.host.replay) as db:before=db.execute('SELECT nonce FROM nonces').fetchall()
        m.execute(self.host,'rollback');self.assertEqual(m.record()['phase'],'ROLLED_BACK');m.admission()
        self.assertEqual(self.host.image,m.OLD);self.assertEqual(self.host.key.read_bytes(),identity)
        self.assertEqual(self.host.replay.stat().st_ino,self.host.original_inode);self.assertEqual(self.host.pid,31515)
        with sqlite3.connect(self.host.replay) as db:
            for nonce in before:self.assertIsNotNone(db.execute('SELECT nonce FROM nonces WHERE nonce=?',nonce).fetchone())
        self.assertIn(b'RuntimeDirectoryPreserve=yes',m.UNIT.read_bytes())
    def test_every_apply_boundary_and_partial_pin_write_can_recover(self):
        m.execute(self.host,'apply');steps=self.host.count
        # Each subtest has a new real root-owned journal, config and replay DB.
        self.assertGreater(steps, 20)
        for failure in range(1,steps+1):
            with self.subTest(failure=failure):
                self.tearDownFixture()
                self.host=Fixture(self.root);self.host.fail=failure
                with self.assertRaises(Crash):m.execute(self.host,'apply')
                self.host.fail=None
                phase=m.record()['phase']
                if phase not in ('COMMITTED','ROLLED_BACK'):
                    with self.assertRaises(m.h.Hold):m.admission()
                m.execute(self.host,'recover')
                self.assertEqual(self.host.image,m.OLD);self.assertEqual(self.host.pid,31515)
                self.assertEqual(m.record()['phase'],'ROLLED_BACK')
    def tearDownFixture(self):
        import shutil
        if m.STATE.exists():shutil.rmtree(m.STATE) # private test fixture only
        for name in ('replay.sqlite3','replay.sqlite3-wal','replay.sqlite3-shm'):(self.root/name).unlink(missing_ok=True)
    def test_recovery_itself_can_be_interrupted_repeatedly(self):
        m.execute(self.host,'apply');self.host.count=0;m.execute(self.host,'recover');steps=self.host.count
        for failure in range(1,steps+1):
            with self.subTest(failure=failure):
                self.tearDownFixture();self.host=Fixture(self.root);m.execute(self.host,'apply')
                self.host.count=0;self.host.fail=failure
                with self.assertRaises(Crash):m.execute(self.host,'recover')
                self.host.fail=None;m.execute(self.host,'recover')
                self.assertEqual(m.record()['phase'],'ROLLED_BACK');self.assertEqual(self.host.pid,31515)
    def test_real_process_kill_during_pin_replacement_recovers_durable_receipt(self):
        child=os.fork()
        if child==0:
            def kill_after_pin(name):
                if name=='replace:worker':os.kill(os.getpid(),9)
            self.host.point=kill_after_pin
            m.execute(self.host,'apply')
            os._exit(99)
        _,status=os.waitpid(child,0)
        self.assertTrue(os.WIFSIGNALED(status));self.assertEqual(os.WTERMSIG(status),9)
        self.assertEqual(m.record()['phase'],'CUTOVER')
        self.assertNotEqual(m.TARGETS[0].read_bytes(),b'old worker')
        self.assertEqual(m.TARGETS[1].read_bytes(),b'old planner')
        with self.assertRaises(m.h.Hold):m.admission()
        m.execute(self.host,'recover')
        self.assertEqual(m.TARGETS[0].read_bytes(),b'old worker')
        self.assertEqual(m.record()['phase'],'ROLLED_BACK')

    def test_drift_stops_recovery_before_any_mutation(self):
        m.execute(self.host,'apply');self.host.pid+=1
        before=[p.read_bytes() for p in m.TARGETS];operations=len(self.host.operations)
        with self.assertRaises(m.h.Hold):m.execute(self.host,'recover')
        self.assertEqual([p.read_bytes() for p in m.TARGETS],before);self.assertEqual(len(self.host.operations),operations)
    def test_unknown_worker_or_backup_rejected(self):
        m.execute(self.host,'apply');m.TARGETS[0].write_bytes(b'unapproved')
        with self.assertRaises(m.h.Hold):m.execute(self.host,'recover')
        m.TARGETS[0].write_bytes(m.decode(m.record()['after'][str(m.TARGETS[0])]))
        (m.STATE/'panel.before.tar').write_bytes(b'corruption')
        with self.assertRaises(m.h.Hold):m.execute(self.host,'recover')
    def test_forged_new_pins_or_configuration_rejected(self):
        doc=copy.deepcopy(self.host.doc);conf=json.loads(m.decode(doc['after'][str(m.b.CONFIG)]));conf['peer_gid']=1
        doc['after'][str(m.b.CONFIG)]=m.encode(m.canonical(conf))
        with self.assertRaises(m.h.Hold):m.validate(doc)
        doc=copy.deepcopy(self.host.doc);doc['after'][str(m.b.HELPER)]=m.encode(b'forged')
        with self.assertRaises(m.h.Hold):m.validate(doc)
    def test_incomplete_and_symlink_receipt_fail_closed(self):
        m.STATE.mkdir(mode=0o700)
        with self.assertRaises(m.h.Hold):m.admission()
        (m.STATE/'record.json').symlink_to(self.host.key)
        with self.assertRaises(m.h.Hold):m.admission()
    def test_wss_extension_requires_exact_old_journal_and_reviewed_image(self):
        m.execute(self.host,'apply');doc=m.record();raw=b'original immutable WSS journal'
        doc['wss_sha']=m.h.digest(raw);m.save(doc)
        with patch.object(m.h,'file',return_value=raw):
            # Patch record to avoid replacing its reader with WSS fixture bytes.
            with patch.object(m,'record',return_value=doc):
                expected=m.expectation({'runtime':{'panel':doc['runtime']}},m.CONFIG_ID)
                self.assertEqual(expected['image'],m.CONFIG_ID)
                with self.assertRaises(m.h.Hold):m.expectation({'runtime':{'panel':doc['runtime']}},'sha256:'+'f'*64)
                with self.assertRaises(m.h.Hold):m.expectation({'runtime':{'panel':{'image':'wrong'}}},m.CONFIG_ID)
    def test_live_socket_never_unlinked_and_only_stale_exact_inode_removed(self):
        import socket
        path=self.root/'broker.sock'
        try:server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        except PermissionError:
            if os.environ.get('GITHUB_ACTIONS')=='true':raise
            self.skipTest('Local sandbox forbids AF_UNIX; mandatory in GitHub CI')
        self.addCleanup(server.close);server.bind(str(path));path.chmod(0o660);server.listen(2)
        identity=m.socket_identity(path,0)
        with self.assertRaises(m.h.Hold):m.remove_stopped_socket(path,identity,0)
        self.assertTrue(path.exists());server.close()
        with self.assertRaises(m.h.Hold):m.remove_stopped_socket(path,(identity[0],identity[1]+1),0)
        self.assertTrue(path.exists());m.remove_stopped_socket(path,identity,0)
        self.assertFalse(path.exists())

    def test_regular_file_cannot_be_removed_as_stale_socket(self):
        path=self.root/'broker.sock';path.write_bytes(b'keep');path.chmod(0o660)
        with self.assertRaises(m.h.Hold):m.socket_identity(path,0)
        self.assertEqual(path.read_bytes(),b'keep')

    def test_ordinary_backup_failure_keeps_preparing_and_recovery_is_idempotent(self):
        with patch.object(self.host,'backup',side_effect=OSError('fixture disk full')):
            with self.assertRaises(OSError):m.execute(self.host,'apply')
        self.assertEqual(m.record()['phase'],'PREPARING')
        m.execute(self.host,'recover');m.execute(self.host,'recover')
        self.assertEqual(self.host.image,m.OLD);self.assertEqual(self.host.pid,31515)

    def test_invalid_loaded_image_is_rejected(self):
        doc=self.host.doc
        for identity,source in [(m.CONFIG_ID,'0'*40),('sha256:'+'f'*64,m.SOURCE)]:
            def run(argv,**kwargs):
                if argv[1:3]==['image','inspect']:
                    return json.dumps([{'Id':identity,'Config':{'Labels':{'org.opencontainers.image.revision':source}}}])
                return ''
            with patch.object(m.Host,'recoverable'),patch.object(m.h,'run',side_effect=run):
                with self.assertRaises(m.h.Hold):m.Host().load_image(doc)

    def test_node_tunnel_registry_is_bound_to_running_named_volume(self):
        # The live Node persists this file in a Docker named volume, not in
        # /opt/smite-node/config. The migration must bind the actual mount.
        volume=self.root/'docker-volumes'/'smite-node-data'/'_data'
        volume.mkdir(parents=True)
        registry=volume/'tunnels.json'
        registry.write_text('{"active-owner":{"core":"frp"}}')
        node={'Mounts':[{'Destination':'/var/lib/smite-node',
                         'Source':str(volume),'Name':'smite-node-data',
                         'Type':'volume','RW':True}]}
        proof=m.Host().node_tunnel_storage(node)
        self.assertEqual(proof['path'],str(registry))
        self.assertEqual(proof['sha'],m.h.digest(registry.read_bytes()))
        self.assertEqual(proof['inode'],[registry.stat().st_dev,registry.stat().st_ino])
        registry.write_text('{"changed-owner":{"core":"frp"}}')
        self.assertNotEqual(m.Host().node_tunnel_storage(node)['sha'],proof['sha'])
        replacement=volume/'replacement.tmp'
        replacement.write_bytes(registry.read_bytes());replacement.replace(registry)
        changed=m.Host().node_tunnel_storage(node)
        self.assertNotEqual(changed['inode'],proof['inode'])

    def test_node_tunnel_registry_missing_or_untrusted_volume_fails_closed(self):
        volume=self.root/'docker-volumes'/'smite-node-data'/'_data'
        volume.mkdir(parents=True)
        good={'Destination':'/var/lib/smite-node','Source':str(volume),
              'Name':'smite-node-data','Type':'volume','RW':True}
        with self.assertRaises(m.h.Hold):
            m.Host().node_tunnel_storage({'Mounts':[good]})
        registry=volume/'tunnels.json'
        registry.write_text('{"active-owner":{"core":"frp"}}')
        for forged in [
            dict(good, Type='bind'),
            dict(good, Name='smite-node-data-shadow'),
            dict(good, RW=False),
            dict(good, Destination='/etc/smite-node'),
            dict(good, Source=str(self.root/'other-volume'/'_data')),
        ]:
            with self.subTest(forged=forged):
                with self.assertRaises(m.h.Hold):
                    m.Host().node_tunnel_storage({'Mounts':[forged]})
        with self.assertRaises(m.h.Hold):
            m.Host().node_tunnel_storage({'Mounts':[good,good]})
        registry.unlink()
        registry.symlink_to(self.host.key)
        with self.assertRaises(m.h.Hold):
            m.Host().node_tunnel_storage({'Mounts':[good]})

    def test_real_database_gate_rejects_duplicate_owner_and_unsafe_startup(self):
        path=self.root/'panel.sqlite3'
        with sqlite3.connect(path) as db:
            db.executescript("CREATE TABLE tunnels(id,core,type,status,spec,node_id,iran_node_id,foreign_node_id); CREATE TABLE frp_proxy_leases(id); CREATE TABLE settings(key,value); CREATE TABLE core_reset_config(enabled);")
            row=('owner-0001','frp','tcp','active',json.dumps({'ports':[49328],'bind_port':7000}),'ir','ir','kh')
            db.execute('INSERT INTO tunnels VALUES (?,?,?,?,?,?,?,?)',row)
        path.chmod(0o600)
        with patch.object(m,'DB',path):
            self.assertEqual(m.Host().db_facts()['port'],49328)
            with sqlite3.connect(path) as db:db.execute('INSERT INTO tunnels VALUES (?,?,?,?,?,?,?,?)',row)
            with self.assertRaises(m.h.Hold):m.Host().db_facts()
            with sqlite3.connect(path) as db:db.execute('DELETE FROM tunnels WHERE rowid=2')
            for key in ('frp','tunnel'):
                value={'enabled':True} if key=='frp' else {'auto_reapply_enabled':True}
                with sqlite3.connect(path) as db:db.execute('INSERT INTO settings VALUES (?,?)',(key,json.dumps(value)))
                with self.assertRaises(m.h.Hold):m.Host().db_facts()
                with sqlite3.connect(path) as db:db.execute('DELETE FROM settings')
            with sqlite3.connect(path) as db:db.execute('INSERT INTO frp_proxy_leases VALUES (1)')
            with self.assertRaises(m.h.Hold):m.Host().db_facts()
            with sqlite3.connect(path) as db:
                db.execute('DELETE FROM frp_proxy_leases');db.execute('INSERT INTO core_reset_config VALUES (1)')
            with self.assertRaises(m.h.Hold):m.Host().db_facts()

    def test_original_wss_journal_bytes_cannot_be_replaced(self):
        m.execute(self.host,'apply');doc=m.record()
        with patch.object(m,'record',return_value=doc),patch.object(m.h,'file',return_value=b'changed'):
            with self.assertRaises(m.h.Hold):m.expectation({'runtime':{'panel':doc['runtime']}},m.INDEX)

    def test_insecure_pin_mode_prevents_recovery(self):
        m.execute(self.host,'apply');m.TARGETS[0].chmod(0o777)
        with self.assertRaises(m.b.BrokerHold):m.execute(self.host,'recover')

    def test_host_panel_command_cannot_recreate_node(self):
        doc=self.host.doc;calls=[]
        obj={'Image':m.OLD,'State':{'Running':True}}
        def run(argv,**kwargs):
            calls.append(argv)
            if argv[1:3]==['ps','-a']:return 'smite-panel'
            if argv[1:3]==['image','inspect']:return json.dumps([{'Id':m.CONFIG_ID}])
            return ''
        with patch.object(m.Host,'check'),patch.object(m.w,'inspect',return_value=obj),patch.object(m.w,'runtime'),patch.object(m.w,'signature',return_value=doc['runtime']),patch.object(m.h,'run',side_effect=run):
            m.Host().panel(doc,True)
        compose=[x for x in calls if x[:2]==['docker','compose']]
        self.assertEqual(len(compose),1);self.assertEqual(compose[0][-1],'smite-panel')
        self.assertIn('--no-deps',compose[0]);self.assertIn('never',compose[0])
        self.assertFalse(any('smite-node' in x for x in calls))

if __name__=='__main__':unittest.main()
