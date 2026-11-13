#!/usr/bin/env python3
"""Failure injection for fresh-only recovery; no real host mutations."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('journal', ROOT / 'modules/smite-rc6-install-journal.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.objects = {}; self.calls = []
        self.j = m.Journal(self.root, self.run_command)
        self.j.folder.mkdir(parents=True, mode=0o700)
        self.tx = self.j.begin('foreign')

    def run_command(self, args, **kwargs):
        self.calls.append(args)
        out = ''
        if args[0] == 'docker':
            a = args[3:]
            if a[0] == 'ps': out = '\n'.join(x['Name'].lstrip('/') for x in self.objects.values())
            elif a[0] == 'inspect':
                obj = next(x for k, x in self.objects.items() if a[1] in (k, x['Name'].lstrip('/')))
                out = json.dumps([obj])
            elif a[0] == 'update': self.objects[a[-1]]['HostConfig']['RestartPolicy'] = {'Name': 'no'}
            elif a[0] == 'stop': self.objects[a[1]]['State']['Running'] = False
            elif a[0] == 'rename': self.objects[a[1]]['Name'] = '/' + a[2]
            else: raise AssertionError(a)
        elif args[0] != 'systemctl': raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, out, '')

    def install_partial(self):
        p = self.root / 'opt/smite-node'; p.mkdir(parents=True)
        (p / '.env').write_text('a-secret-preserved\n'); os.chmod(p / '.env', 0o600)
        self.objects['a'*64] = dict(Id='a'*64, Name='/smite-node', State={'Running': True},
            Config={'Image': m.IMAGES['smite-node'], 'Env': ['SMITE_NODE_PANEL_AUTH_MODE=paused'],
                    'Labels': {'com.docker.compose.project': self.tx}},
            HostConfig={'RestartPolicy': {'Name': 'unless-stopped'}})
        return p

    def assert_no_stop(self):
        self.assertFalse(any('stop' in a or 'rename' in a or 'disable' in a for a in self.calls))

    def test_before_files_rollback_and_retry(self):
        self.assertIn('PASS', self.j.rollback())
        self.assertIn('ALREADY', self.j.rollback())
        self.assertNotEqual(self.tx, self.j.begin('foreign'))
        self.assertTrue((self.j.folder / (self.tx+'.json')).exists())

    def test_partial_runtime_quarantines_preserving_bytes_modes_and_container(self):
        p = self.install_partial()
        self.assertIn('PASS', self.j.rollback())
        archived = p.with_name(p.name+'.rc6-rollback-'+self.tx)
        self.assertEqual((archived/'.env').read_text(), 'a-secret-preserved\n')
        self.assertEqual((archived/'.env').stat().st_mode & 0o777, 0o600)
        self.assertFalse(p.exists())
        self.assertFalse(self.objects['a'*64]['State']['Running'])
        self.assertEqual(len(self.objects), 1)
        self.assertFalse(any('rm' in a for a in self.calls))

    def test_foreign_or_signed_container_refuses_before_stop(self):
        self.install_partial()
        for field in ('project', 'auth', 'image'):
            obj = self.objects['a'*64]
            obj['Config']['Labels']['com.docker.compose.project'] = self.tx if field!='project' else 'foreign'
            obj['Config']['Env'] = ['SMITE_NODE_PANEL_AUTH_MODE='+('signed' if field=='auth' else 'paused')]
            obj['Config']['Image'] = m.IMAGES['smite-node'] if field!='image' else 'unverified'
            with self.assertRaises(m.Hold): self.j.rollback()
            self.assert_no_stop()

    def test_pairing_lease_grant_route_refuse(self):
        self.install_partial()
        for rel in ('etc/u-opti/smite/route-grants/child.json', 'etc/nginx/smite-xhttp-routes/child.conf',
                    'etc/u-opti/smite/pairing.env'):
            p=self.root/rel; p.parent.mkdir(parents=True, exist_ok=True);p.write_text('keep')
            with self.assertRaises(m.Hold): self.j.rollback()
            self.assert_no_stop(); p.unlink()
        p=self.root/'opt/smite/panel/data/smite.db';p.parent.mkdir(parents=True)
        with sqlite3.connect(p) as c:
            c.execute('CREATE TABLE frp_proxy_leases (id INTEGER)');c.execute('INSERT INTO frp_proxy_leases VALUES (1)')
        with self.assertRaises(m.Hold): self.j.rollback()
        self.assert_no_stop()

    def test_paused_but_enrolled_node_refuses(self):
        self.install_partial()
        identity=self.root/'opt/smite-node/config/identity'
        identity.mkdir(parents=True)
        (identity/'node-identity.json').write_text('preserve signed identity')
        with self.assertRaises(m.Hold): self.j.rollback()
        self.assert_no_stop()
        self.assertEqual((identity/'node-identity.json').read_text(), 'preserve signed identity')

    def test_identity_override_refuses(self):
        self.install_partial()
        self.objects['a'*64]['Config']['Env'].append('SMITE_AGENT_IDENTITY_PATH=/foreign/identity.json')
        with self.assertRaises(m.Hold): self.j.rollback()
        self.assert_no_stop()

    def test_production_identity_mount_guard_readonly(self):
        self.install_partial()
        checker=m.Journal(Path('/'), self.run_command)
        with self.assertRaises(m.Hold): checker.inspect_owned(self.j.load())
        self.objects['a'*64]['Mounts']=[dict(Type='bind', Source='/opt/smite-node/config', Destination='/etc/smite-node')]
        self.assertEqual(len(checker.inspect_owned(self.j.load())), 1)
        self.assert_no_stop()

    def test_live_installer_refuses(self):
        d=self.j.load();d.update(installer_pid=123, installer_start='fixture-start');self.j.save(d)
        with patch.object(m, 'process_start', return_value='fixture-start'):
            with self.assertRaises(m.Hold): self.j.rollback()
        self.assert_no_stop()

    def setup_partial_ir_broker_service(self, role='panel-iran'):
        self.install_partial()
        doc = self.j.load()
        doc['role'] = role
        self.j.save(doc)
        gid = 39100
        peer = self.root / 'etc/u-opti/smite'
        peer.mkdir(parents=True, mode=0o700)
        peer.chmod(0o700)
        config = peer / 'route-broker.json'
        config.write_text(json.dumps({'peer_gid': gid}))
        config.chmod(0o600)
        service = self.root / 'etc/systemd/system/u-opti-smite-xhttp-broker.service'
        service.parent.mkdir(parents=True, exist_ok=True)
        provider = ROOT / 'modules/smite-rc5-xhttp-broker-provision.py'
        spec = importlib.util.spec_from_file_location('rollback_broker_unit_fixture', provider)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        current = mod._service_unit(gid)
        legacy = current.replace(
            f'ConditionPathExists={mod.IR_INSTALL_JOURNAL}\n'.encode(),
            b'ConditionHost=ir*\n',
        )
        self.assertNotEqual(legacy, current)
        service.write_bytes(legacy)
        service.chmod(0o644)
        return service, mod

    def test_signed_rc7_legacy_hostname_unit_can_be_rolled_back_after_update(self):
        service, mod = self.setup_partial_ir_broker_service()
        self.assertIn(service.read_bytes(), mod.reviewed_service_unit_bytes(39100))
        result = self.j.rollback()
        self.assertEqual(result, 'RC6_ROLLBACK=PASS_DATA_RETAINED')
        self.assertFalse(self.objects['a'*64]['State']['Running'])
        self.assertTrue(any(
            a[:3] == ['systemctl', 'disable', '--now'] for a in self.calls
        ))
        archived = service.with_name(service.name + '.rc6-rollback-' + self.tx)
        self.assertTrue(archived.exists())
        self.assertEqual(archived.read_bytes().count(b'ConditionHost=ir*'), 1)

    def test_unknown_broker_unit_and_foreign_role_refuse_rollback(self):
        service, mod = self.setup_partial_ir_broker_service()
        legacy = service.read_bytes()
        service.write_bytes(legacy.replace(b'ConditionHost=ir*', b'ConditionHost=foreign*'))
        with self.assertRaisesRegex(m.Hold, 'BROKER_UNIT_CHANGED'):
            self.j.rollback()
        self.assert_no_stop()
        service.write_bytes(legacy)
        doc = self.j.load()
        doc['role'] = 'foreign'
        self.j.save(doc)
        with self.assertRaisesRegex(m.Hold, 'FOREIGN_BROKER_UNIT'):
            self.j.rollback()
        self.assert_no_stop()

    def test_legacy_rc6_rollback_survives_installer_update(self):
        self.install_partial()
        d = self.j.load(); d['source'] = m.LEGACY_SOURCE; self.j.save(d)
        self.objects['a'*64]['Config']['Image'] = m.LEGACY_IMAGES['smite-node']
        self.assertIn('PASS', self.j.rollback())
        self.assertFalse(self.objects['a'*64]['State']['Running'])

    def test_cross_candidate_image_is_not_owned(self):
        self.install_partial()
        self.objects['a'*64]['Config']['Image'] = m.LEGACY_IMAGES['smite-node']
        with self.assertRaises(m.Hold): self.j.rollback()
        self.assert_no_stop()

    def test_unknown_candidate_source_holds(self):
        d = self.j.load(); d['source'] = 'f'*40; self.j.save(d)
        with self.assertRaises(m.Hold): self.j.rollback()
        self.assert_no_stop()

    def prepare_retained_ir(self):
        """Real journal phase transitions with Docker/SQLite fixture only."""
        ir_root=self.root/'iran-fixture'
        ir_root.mkdir()
        journal=m.Journal(ir_root,self.run_command)
        journal.folder.mkdir(parents=True,mode=0o700)
        project=journal.begin('panel-iran',resumable_ir=True)
        self.objects.clear();self.calls.clear()
        for i,name in enumerate(('smite-panel','smite-node')):
            self.objects[('b' if i==0 else 'a')*64] = dict(
                Id=('b' if i==0 else 'a')*64,Name='/'+name,
                State={'Running':True,'Health':{'Status':'healthy'}},
                Config={'Image':m.IMAGES[name],
                        'Env':(['SMITE_NODE_PANEL_AUTH_MODE=paused',
                                'SMITE_AGENT_AUTH_MODE=strict'] if name=='smite-node' else []),
                        'Labels':{
                            'com.docker.compose.project':project,
                            'com.docker.compose.service':name,
                            'com.docker.compose.project.config_files':(
                                '/opt/smite/docker-compose.yml' if name=='smite-panel'
                                else '/opt/smite-node/docker-compose.yml')}},
                HostConfig={'RestartPolicy':{'Name':'unless-stopped'}})
        state=ir_root/'etc/u-opti/smite/state.env'
        state.parent.mkdir(parents=True)
        state.write_text(
            'SMITE_ROLE=panel-iran\n'
            'SMITE_CONNECTION_MODE=standard\n'
            'SMITE_MANAGED_VERSION='+m.VERSION+'\n'
            'SMITE_UPSTREAM_REF='+m.SOURCE+'\n')
        state.chmod(0o600)
        self.assertIn('COMMITTED',journal.commit())
        return journal,ir_root,project

    def test_ir_resume_from_each_verified_phase_and_complete(self):
        ir,root,project=self.prepare_retained_ir()
        self.assertEqual(ir.ir_resume(),('CORE_COMMITTED',project))
        with self.assertRaisesRegex(m.Hold,'OUT_OF_ORDER'):
            ir.ir_advance('PAIRING_VERIFIED')
        self.assertEqual(ir.ir_advance('GATEWAY_VERIFIED'),'GATEWAY_VERIFIED')
        self.assertEqual(m.Journal(root,self.run_command).ir_resume(),
                         ('GATEWAY_VERIFIED',project))
        with self.assertRaisesRegex(m.Hold,'NOT_SIGNED'):
            ir.ir_advance('PAIRING_VERIFIED')
        node=self.objects['a'*64]
        node['Config']['Env']=[
            'SMITE_NODE_PANEL_AUTH_MODE=signed','SMITE_AGENT_AUTH_MODE=strict']
        node['Config']['Labels']['com.docker.compose.project.config_files'] = (
            '/opt/smite-node/docker-compose.yml,'
            '/opt/smite-node/docker-compose.security-candidate.yml')
        self.assertEqual(ir.ir_advance('PAIRING_VERIFIED'),'PAIRING_VERIFIED')
        with self.assertRaisesRegex(m.Hold,'DATABASE_MISSING'):
            ir.ir_advance('ADMIN_CREATED')
        db=root/'opt/smite/panel/data/smite.db'
        db.parent.mkdir(parents=True)
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE TABLE admins(username TEXT, password_hash TEXT)')
            conn.execute("INSERT INTO admins VALUES('operator','hash-bcrypt')")
        self.assertTrue(ir.ir_admin_present())
        self.assertEqual(ir.ir_advance('ADMIN_CREATED'),'ADMIN_CREATED')
        self.assertEqual(ir.ir_advance('COMPLETE'),'COMPLETE')
        self.assertEqual(ir.ir_resume(),('COMPLETE',project))
        self.assertEqual(ir.ir_advance('COMPLETE'),'COMPLETE')
        self.assertEqual(ir.load()['ir_phase'],'COMPLETE')
        self.assert_no_stop()

    def test_pending_gateway_recovery_admitted_even_if_paused_node_stopped(self):
        ir,root,project=self.prepare_retained_ir()
        node=self.objects['a'*64]
        node['State']['Running']=False
        # An unclean stop during Gateway cannot pass full Node health,
        # but the same original journal may admit a private snapshot
        # rollback BEFORE any Node is repaired or next stage attempted.
        self.assertEqual(ir.ir_gateway_recovery_plan(),('CORE_COMMITTED',project))
        with self.assertRaises(m.Hold):
            ir.ir_resume()
        node['State']['Running']=True
        ir.ir_advance('GATEWAY_VERIFIED')
        self.assertEqual(ir.ir_gateway_recovery_plan(),('GATEWAY_VERIFIED',project))
        self.assert_no_stop()

    def test_pending_gateway_recovery_rejects_active_or_legacy_owner(self):
        ir,root,project=self.prepare_retained_ir()
        doc=ir.load()
        doc['installer_pid']=123
        doc['installer_start']='same-process'
        ir.save(doc)
        with patch.object(m,'process_start',return_value='same-process'):
            with self.assertRaisesRegex(m.Hold,'STILL_RUNNING'):
                ir.ir_gateway_recovery_plan()
        doc=ir.load()
        doc.pop('ir_resumable_version')
        ir.save(doc)
        with self.assertRaisesRegex(m.Hold,'NOT_ADMITTED'):
            ir.ir_gateway_recovery_plan()
        self.assert_no_stop()

    def test_ir_resume_holds_on_drift_and_does_not_recreate_node(self):
        ir,root,_=self.prepare_retained_ir()
        node=self.objects['a'*64]
        for key,value in (
            ('Image','ghcr.io/aghajani82/smite-node:latest'),
            ('project','unknown-owner'),
            ('service','unreviewed-service'),
            ('files','/tmp/foreign-compose.yml'),
        ):
            before_image=node['Config']['Image']
            before_labels=node['Config']['Labels'].copy()
            if key=='Image':node['Config']['Image']=value
            else:
                name={'project':'com.docker.compose.project',
                      'service':'com.docker.compose.service',
                      'files':'com.docker.compose.project.config_files'}[key]
                node['Config']['Labels'][name]=value
            with self.subTest(key=key),self.assertRaises(m.Hold):
                ir.ir_resume()
            node['Config']['Image']=before_image
            node['Config']['Labels']=before_labels
        node['State']['Running']=False
        with self.assertRaises(m.Hold):ir.ir_resume()
        node['State']['Running']=True
        state=root/'etc/u-opti/smite/state.env'
        state.write_text(state.read_text().replace(
            'SMITE_MANAGED_VERSION='+m.VERSION,'SMITE_MANAGED_VERSION=unverified'))
        with self.assertRaises(m.Hold):ir.ir_resume()
        self.assertEqual(ir.load()['ir_phase'],'CORE_COMMITTED')
        self.assert_no_stop()

    def test_legacy_or_foreign_installs_not_auto_adopted_by_ir_cursor(self):
        self.install_partial()
        state=self.root/'etc/u-opti/smite/state.env';state.parent.mkdir(parents=True)
        state.write_text('SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION='+m.VERSION+
                         '\nSMITE_UPSTREAM_REF='+m.SOURCE+'\n')
        self.j.commit()
        with self.assertRaisesRegex(m.Hold,'NOT_OWNED'):
            self.j.ir_resume()
        with self.assertRaisesRegex(m.Hold,'NOT_OWNED'):
            self.j.ir_advance('GATEWAY_VERIFIED')
        with self.assertRaisesRegex(m.Hold,'INVALID_RESUMABLE'):
            self.j.begin('foreign',resumable_ir=True)
        # Isolate the second simulated fresh host from the foreign Docker
        # fixture: a real host must never begin with existing containers.
        self.objects.clear()
        self.calls.clear()
        ir,_,_=self.prepare_retained_ir()
        d=ir.load();d.pop('ir_resumable_version');d.pop('ir_phase');ir.save(d)
        with self.assertRaisesRegex(m.Hold,'NOT_OWNED'):
            ir.ir_resume()

    def test_ir_resume_rejects_active_installer_same_process_identity(self):
        ir,_,_=self.prepare_retained_ir()
        d=ir.load();d['installer_pid']=101;d['installer_start']='start101';ir.save(d)
        with patch.object(m,'process_start',return_value='start101'):
            with self.assertRaisesRegex(m.Hold,'STILL_RUNNING'):
                ir.ir_resume()
        self.assert_no_stop()

    def test_completed_install_refuses(self):
        self.install_partial();p=self.root/'etc/u-opti/smite/state.env';p.parent.mkdir(parents=True)
        p.write_text('SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION='+m.VERSION+'\nSMITE_UPSTREAM_REF='+m.SOURCE+'\n')
        self.assertIn('COMMITTED', self.j.commit())
        with self.assertRaises(m.Hold): self.j.rollback()
        self.assert_no_stop()

    def test_crash_after_rename_before_checkpoint_retries(self):
        p=self.install_partial(); rename=m.os.rename
        def crash(src,dst):
            rename(src,dst)
            if Path(src)==p: raise RuntimeError('power loss')
        with patch.object(m.os, 'rename', side_effect=crash):
            with self.assertRaises(RuntimeError): self.j.rollback()
        self.assertEqual(self.j.load()['state'], 'ROLLING_BACK')
        self.assertIn('PASS', m.Journal(self.root,self.run_command).rollback())

    def test_replaced_path_after_crash_refuses(self):
        p=self.install_partial()
        with patch.object(m.Journal, 'inactive', side_effect=[False, RuntimeError('power loss')]):
            with self.assertRaises(RuntimeError): self.j.rollback()
        p.rename(p.with_name('preserved'));p.mkdir()
        with self.assertRaises(m.Hold): self.j.rollback()
        self.assert_no_stop()

    def test_symlink_and_bad_permissions_refuse(self):
        p=self.root/'opt/smite-node';p.parent.mkdir(parents=True);p.symlink_to(self.root/'absent')
        with self.assertRaises((m.Hold, FileNotFoundError)): self.j.rollback()
        p.unlink();os.chmod(self.j.path,0o666)
        with self.assertRaises(m.Hold): self.j.rollback()
        self.assert_no_stop()

    def test_existing_state_cannot_start_transaction(self):
        self.j.rollback();p=self.root/'opt/smite-node';p.mkdir(parents=True)
        with self.assertRaises(m.Hold): self.j.begin('foreign')
        self.assertTrue(p.exists())

if __name__ == '__main__': unittest.main()
