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
