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
            if self.state['SMITE_MANAGED_VERSION'] == '2.0.0-rc.9':
                return (p._FOREIGN_PANEL_IMAGE_UNIFIED_TRIAL
                        if args[-1] == 'smite-panel' else
                        p._FOREIGN_NODE_IMAGE_UNIFIED_TRIAL)
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

    def test_rc9_bootstrap_and_resumed_signed_probe_preserve_identity(self):
        self.state['SMITE_MANAGED_VERSION'] = '2.0.0-rc.9'
        self.assertIn('VERIFIED_ACTIVE', self.complete())
        original = self.identity.read_bytes()
        self.assertEqual(self.events, ['enable', 'reserve', 'redeem', 'activate'])
        self.signed = True
        self.events.clear()
        self.assertIn('VERIFIED_ACTIVE', self.complete())
        self.assertEqual(self.identity.read_bytes(), original)
        self.assertEqual(self.events, ['_local_signed_replay_probe',
                                      '_wait_panel_signed_checkin', '_panel_to_ir_signed_probe'])

    def test_rc9_mixed_rc7_image_holds_before_reservation(self):
        self.state['SMITE_MANAGED_VERSION'] = '2.0.0-rc.9'
        with patch.object(p, '_run', return_value=p._FOREIGN_NODE_IMAGE_RC7):
            with self.assertRaisesRegex(p.WizardHold, 'pinned version pair'):
                self.complete()
        self.assertEqual(self.events, [])
        self.assertFalse(self.identity.exists())

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


class SelectedFreshIranForeignReadyTests(unittest.TestCase):
    """Exact original renderer/config snapshots; never touches host Docker."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="smite-ir-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "rc6-install-journal"
        self.folder.mkdir(mode=0o700)
        self.stage = self.folder / "iran-foreign-ready"
        self.panel_env = self.root / ".env"
        self.backend = self.root / "u-opti-smite-panel-backend.conf"
        fixture_spec = importlib.util.spec_from_file_location(
            "ir_foreign_test_baseline", ROOT / "tests/test-smite-foreign-install-panel-ingress.py")
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        self.old_backend = fixture.baseline("panel.example.com")
        self.old_env = (
            "PANEL_DOMAIN=panel.example.com\n"
            "DB_TYPE=sqlite\n"
            "DB_PATH=./data/smite.db\n"
            "SMITE_NODE_REGISTRATION_MODE=signed\n"
            "SMITE_PANEL_AGENT_AUTH_MODE=signed\n"
            "SMITE_NODE_PAIRING_PREVIEW_ENABLED=true\n"
            "SMITE_NODE_PAIRING_MASTER_KEY=" + "A"*43 + "=\n"
            "SMITE_NODE_PAIRING_INGRESS_TOKEN=" + "b"*64 + "\n"
            "SMITE_FOREIGN_INSTALL_ENABLED=false\n"
            "SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED=false\n"
        ).encode()
        self.panel_env.write_bytes(self.old_env)
        self.panel_env.chmod(0o600)
        self.backend.write_bytes(self.old_backend)
        self.backend.chmod(0o644)
        self.events = []
        self.fail_next_nginx = False
        self.enterContext(patch.object(p, "PANEL_ENV", self.panel_env))
        self.enterContext(patch.object(p, "NGINX_BACKEND", self.backend))
        self.enterContext(patch.object(p, "_run", side_effect=self.host))
        self.enterContext(patch.object(p, "_wait_container",
                                      side_effect=lambda *args: self.events.append("panel-healthy")))

    def host(self, args, **kwargs):
        if args[:3] == ["docker", "exec", "smite-panel"]:
            self.events.append("runtime-flags")
            env = self.panel_env.read_text()
            if ("SMITE_FOREIGN_INSTALL_ENABLED=true" in env
                    and "SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED=true" in env):
                return "PANEL_FOREIGN_INSTALL_RUNTIME=READY"
            raise p.WizardHold("fixture Panel has original flags")
        if args == ["nginx", "-t"]:
            self.events.append("nginx-test")
            if self.fail_next_nginx:
                self.fail_next_nginx = False
                raise p.WizardHold("injected nginx failure")
            return ""
        if args == ["systemctl", "reload", "nginx"]:
            self.events.append("nginx-reloaded")
            return ""
        if args[:2] == ["docker", "compose"]:
            self.events.append("panel-recreated")
            self.assertIn("--no-deps", args)
            self.assertEqual(args[-1], "smite-panel")
            return ""
        self.fail("Unexpected host command: " + repr(args))

    def apply(self, *, fixture_capability=True):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            p._fresh_ir_foreign_ready_config(
                stage_dir=self.stage, project="uopti_rc6_"+"a"*32,
                domain="panel.example.com", compose=["docker", "compose"],
                fixture_capability=fixture_capability)
        return output.getvalue()

    def test_selected_ir_uses_existing_signed_renderers_without_node_recreation(self):
        self.assertIn("IR_FOREIGN_INSTALL=READY_SIGNED_443", self.apply())
        self.assertIn(b"SMITE_FOREIGN_INSTALL_ENABLED=true", self.panel_env.read_bytes())
        self.assertIn(b"SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED=true",
                      self.panel_env.read_bytes())
        self.assertEqual(self.backend.read_bytes().count(
            b"location = /api/foreign-install/redeem {"), 1)
        self.assertEqual(self.backend.read_bytes().count(
            b"location = /api/node-control/installation-status {"), 1)
        self.assertIn("panel-recreated", self.events)
        self.assertEqual(self.events.count("panel-recreated"), 1)
        self.assertTrue((self.stage/"complete").exists())
        self.events.clear()
        self.apply()
        self.assertNotIn("panel-recreated", self.events)
        self.assertNotIn("nginx-reloaded", self.events)

    def test_completed_ir_foreign_runtime_drift_never_recreates_panel(self):
        self.apply()
        before_env = self.panel_env.read_bytes()
        before_backend = self.backend.read_bytes()
        checkpoint = (self.stage/"complete").read_bytes()
        self.events.clear()

        # Keep the original sealed env and TLS/443 renderer intact, but
        # simulate a stale/nonmatching effective container runtime. The
        # already COMPLETED option-1 stage must not force-recreate Panel.
        old_host = self.host
        def drifted_host(args, **kwargs):
            if args[:3] == ["docker", "exec", "smite-panel"]:
                self.events.append("runtime-flags-drift")
                return "PANEL_FOREIGN_INSTALL_RUNTIME=NOT_READY"
            return old_host(args, **kwargs)
        with patch.object(p, "_run", side_effect=drifted_host):
            with self.assertRaisesRegex(
                    p.WizardHold, "Completed Foreign Iran Panel runtime drift"):
                self.apply()
        self.assertEqual(self.events, ["runtime-flags-drift"])
        self.assertEqual(self.panel_env.read_bytes(), before_env)
        self.assertEqual(self.backend.read_bytes(), before_backend)
        self.assertEqual((self.stage/"complete").read_bytes(), checkpoint)

    def test_original_step_snapshot_compensates_nginx_failure_only(self):
        self.fail_next_nginx = True
        with self.assertRaisesRegex(p.WizardHold, "compensated"):
            self.apply()
        self.assertEqual(self.panel_env.read_bytes(), self.old_env)
        self.assertEqual(self.backend.read_bytes(), self.old_backend)
        self.assertTrue((self.stage/"receipt.json").exists())
        self.assertFalse((self.stage/"complete").exists())
        self.apply()
        self.assertIn(b"SMITE_FOREIGN_INSTALL_ENABLED=true",
                      self.panel_env.read_bytes())

    def test_crash_after_one_file_can_resume_same_journal_without_new_identity(self):
        self.apply()
        (self.stage/"complete").unlink()
        self.backend.write_bytes(self.old_backend)
        self.backend.chmod(0o644)
        self.events.clear()
        self.assertIn("READY_SIGNED_443", self.apply())
        self.assertEqual(self.events.count("panel-recreated"), 1)
        self.assertTrue((self.stage/"complete").exists())

    def test_signed_checkpoint_drift_and_modified_live_config_fail_closed(self):
        self.apply()
        self.panel_env.write_bytes(self.old_env)
        self.panel_env.chmod(0o600)
        self.events.clear()
        with self.assertRaisesRegex(p.WizardHold, "Completed.*drift"):
            self.apply()
        self.assertEqual(self.panel_env.read_bytes(), self.old_env)
        self.assertNotIn("panel-recreated", self.events)
        self.panel_env.write_bytes((self.stage/"after-env").read_bytes())
        corrupted = self.stage/"before-nginx"
        corrupted.write_bytes(b"malicious")
        corrupted.chmod(0o600)
        with self.assertRaisesRegex(p.WizardHold, "integrity mismatch"):
            self.apply()

    def test_fixture_cannot_authorize_live_root_path(self):
        with self.assertRaisesRegex(p.WizardHold, "original root journal"):
            self.apply(fixture_capability=False)
        self.assertFalse(self.stage.exists())


if __name__ == '__main__':
    unittest.main()
