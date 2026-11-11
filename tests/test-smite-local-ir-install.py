#!/usr/bin/env python3
"""Local bootstrap failure/retry tests. No Docker, network or host writes."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pairing', ROOT / 'modules/smite-node-pairing.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
REAL_IR_COMPOSE = p._ir_node_compose_command

class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.private = root / 'pairing'
        self.private.mkdir(mode=0o700)
        self.identity = root / 'identities' / 'node-identity.json'
        self.identity.parent.mkdir(mode=0o700)
        self.db = root / 'panel.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE nodes (id TEXT)')
            db.execute('CREATE TABLE tunnels (id TEXT)')
        self.state = dict(SMITE_ROLE='panel-iran', SMITE_CONNECTION_MODE='standard',
                          SMITE_MANAGED_VERSION='2.0.0-rc.7',
                          SMITE_NODE_NAME='node-ir', SMITE_PANEL_DOMAIN='panel.example.com')
        self.events = []
        self.signed = False
        for key, value in [('PAIRING_PRIVATE_DIR', self.private),
                           ('IDENTITY_FILE', self.identity), ('PANEL_DB', self.db)]:
            self.enterContext(patch.object(p, key, value))
        for name in ['_field_trial_gate', '_require_no_active_engine_overlays',
                     '_panel_compose_command', '_ir_node_compose_command', 'prepare_store']:
            self.enterContext(patch.object(p, name))
        self.enable = self.enterContext(patch.object(p, 'enable_panel_field_trial',
            side_effect=lambda s: self.events.append('enable')))
        self.enterContext(patch.object(p, '_run', side_effect=self.run_host))
        self.redeem = self.enterContext(patch.object(p, 'redeem', side_effect=self.redeem_code))
        self.activate = self.enterContext(patch.object(p, 'activate_ir_node_field_trial',
            side_effect=lambda s: self.events.append('activate')))
        for name in ['_local_signed_replay_probe', '_wait_panel_signed_checkin', '_panel_to_ir_signed_probe']:
            self.enterContext(patch.object(p, name, side_effect=lambda *a, n=name: self.events.append(n)))

    def run_host(self, args, **kwargs):
        if '{{.Config.Image}}' in args:
            return p._FOREIGN_PANEL_IMAGE_RC7 if args[-1] == 'smite-panel' else p._FOREIGN_NODE_IMAGE_RC7
        if p._LOCAL_IR_RESERVE in args:
            self.events.append('reserve')
            return 'smn1_' + 'A' * 43
        return 'SMITE_AGENT_AUTH_MODE=strict\nSMITE_NODE_PANEL_AUTH_MODE=' + ('signed' if self.signed else 'paused')

    def redeem_code(self, **kwargs):
        self.events.append('redeem')
        p.store_identity(self.identity, kwargs['node_id'], 'a' * 64)

    def complete(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            p.complete_local_ir_install(self.state)
        return output.getvalue()

    def test_full_order_and_private_output(self):
        output = self.complete()
        self.assertEqual(self.events, ['enable', 'reserve', 'redeem', 'activate'])
        self.assertIn('VERIFIED_ACTIVE', output)
        self.assertNotIn('smn1_', output)
        self.assertNotIn('a' * 64, output)
        self.assertEqual(self.identity.stat().st_mode & 0o777, 0o600)

    def test_active_retry_verifies_without_rekey_or_restart(self):
        self.complete()
        original = self.identity.read_bytes()
        self.events.clear()
        self.signed = True
        self.complete()
        self.assertEqual(self.identity.read_bytes(), original)
        self.assertEqual(self.events, ['_local_signed_replay_probe',
                                      '_wait_panel_signed_checkin', '_panel_to_ir_signed_probe'])

    def test_active_retry_accepts_real_compose_ownership_guard(self):
        self.complete()
        self.signed = True
        base = self.private / 'node-compose.yml'
        candidate = self.private / 'node-candidate.yml'
        base.write_text('services: {}')
        original_run = self.run_host
        def host(args, **kwargs):
            if 'com.docker.compose.project.config_files' in args[3]:
                return str(base) + ',' + str(candidate)
            if 'com.docker.compose.project' in args[3]:
                return 'uopti_rc6_' + 'a' * 32
            if 'com.docker.compose.service' in args[3]:
                return 'smite-node'
            return original_run(args, **kwargs)
        with patch.object(p, 'NODE_COMPOSE', base), \
             patch.object(p, 'NODE_SECURITY_CANDIDATE', candidate), \
             patch.object(p, '_ir_node_compose_command', REAL_IR_COMPOSE), \
             patch.object(p, '_run', side_effect=host):
            self.assertIn('VERIFIED_ACTIVE', self.complete())

    def test_failed_activation_retries_same_identity(self):
        self.activate.side_effect = p.WizardHold('probe failed')
        with self.assertRaises(p.WizardHold):
            self.complete()
        original = self.identity.read_bytes()
        self.events.clear()
        self.activate.side_effect = lambda s: self.events.append('activate')
        self.complete()
        self.assertEqual(self.events, ['activate'])
        self.assertEqual(self.identity.read_bytes(), original)

    def test_existing_nodes_or_tunnels_rejected_before_enable(self):
        for table in ['nodes', 'tunnels']:
            with sqlite3.connect(self.db) as db:
                db.execute('INSERT INTO ' + table + ' VALUES (?)', ('existing',))
            with self.assertRaises(p.WizardHold):
                self.complete()
            self.enable.assert_not_called()
            with sqlite3.connect(self.db) as db:
                db.execute('DELETE FROM ' + table)

    def test_receipt_mismatch_and_symlink_fail_closed(self):
        self.complete()
        self.events.clear()
        self.state['SMITE_NODE_NAME'] = 'different'
        with self.assertRaises(p.WizardHold):
            self.complete()
        self.assertEqual(self.events, [])
        receipt = self.private / 'local-ir-install.json'
        receipt.unlink()
        receipt.symlink_to(self.identity)
        with self.assertRaises(p.WizardHold):
            self.complete()

    def test_tls_failure_never_activates(self):
        self.redeem.side_effect = p.WizardHold('TLS failed')
        with self.assertRaises(p.WizardHold):
            self.complete()
        self.activate.assert_not_called()
        self.assertFalse(self.identity.exists())
        receipt = (self.private / 'local-ir-install.json').read_bytes()
        with self.assertRaises(p.WizardHold):
            self.complete()
        self.assertEqual((self.private / 'local-ir-install.json').read_bytes(), receipt)

    def test_foreign_and_unselected_version_rejected(self):
        for key, bad in [('SMITE_ROLE', 'foreign'), ('SMITE_MANAGED_VERSION', '0.1.7'),
                         ('SMITE_CONNECTION_MODE', 'private')]:
            state = {**self.state, key: bad}
            with self.assertRaises(p.WizardHold):
                p.complete_local_ir_install(state)
        self.assertEqual(self.events, [])

if __name__ == '__main__':
    unittest.main()
