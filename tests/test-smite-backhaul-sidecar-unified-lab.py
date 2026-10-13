#!/usr/bin/env python3
"""Offline paired Backhaul/Nginx transaction tests, including KH public guard.

Fixtures, secrets and journals exist only in marker-guarded private /tmp.
No Docker/SSH/network/server access; service state is synthetic JSON.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "modules"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, MODULE / filename)
    obj = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(obj)
    return obj


engine = load("test_sidecar_unified", "smite-backhaul-sidecar-unified-lab.py")
pair = engine.pair
sidecar = pair.sidecar
nginx = pair.nginx

IR = b"""server {
    listen 127.0.0.1:8443 ssl;
    server_name ir.example.com;
    location = /~!frp {
        proxy_pass http://127.0.0.1:7000;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
"""
KH = b"""server {
    listen 443 ssl http2;
    server_name kh.example.com;
    location / { return 404; }
    location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {
        proxy_pass http://127.0.0.1:$fwdport$is_args$args;
    }
}
"""


class PairedInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token_path = Path(self.temp.name) / "token"
        self.token_path.write_text("Q" * 48 + "\n")
        self.token_path.chmod(0o600)

    def fixture(self, role):
        temp = tempfile.TemporaryDirectory(prefix="uopti-bh-sandbox-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        engine.sandbox.bootstrap_mock(root, "kh")  # Marker-only fixture
        original = IR if role == "ir" else KH
        vhost = nginx.IR_PATH if role == "ir" else nginx.KH_PATH
        target = engine.sandbox.check_path(root, vhost, create_parents=True)
        engine.legacy._persist(target, original)
        engine.bootstrap(root, role)
        stage = sidecar.prepare(role, self.token_path, "ir.example.com", "kh.example.com")
        self.addCleanup(lambda p=stage: shutil.rmtree(p))
        with patch.object(nginx, "original_bytes", return_value=original):
            nginx_stage = nginx.prepare(
                role, Path(vhost), "ir.example.com", "kh.example.com"
            )
        self.addCleanup(lambda p=nginx_stage: shutil.rmtree(p))
        return root, stage, nginx_stage, vhost, original

    def assert_restored(self, root, role, vhost, original):
        self.assertFalse((root / engine.JOURNAL).exists())
        self.assertFalse((root / engine.BACKUP).exists())
        self.assertEqual(engine._json_file(root / engine.RUNTIME),
                         engine.original_runtime(role))
        for path, (operation, _, _) in pair.LAYOUT[role].items():
            target = engine.sandbox.check_path(root, path)
            if operation == "create":
                self.assertFalse(target.exists())
            else:
                self.assertEqual(original, target.read_bytes())
        self.assertEqual(original, (root / vhost.lstrip("/")).read_bytes())

    def test_reconciliation_exact_including_kh_guard(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                root, stage, ng, vhost, old = self.fixture(role)
                resources = pair.reconcile(role, stage, ng)
                self.assertEqual(list(pair.LAYOUT[role]), [r["path"] for r in resources])
                edits = [r for r in resources if r["operation"] == "edit"]
                self.assertEqual(len(edits), 1)
                self.assertEqual(edits[0]["path"], vhost)
                self.assertEqual(edits[0]["before"], old)
                if role == "kh":
                    patched = edits[0]["after"].decode()
                    self.assertIn("location ~ ^/0*13080(/|$)", patched)
                    self.assertLess(patched.index("location ~ ^/0*13080(/|$)"),
                                    patched.index(nginx.KH_FWD_ANCHOR))
                report = engine.install_mock(root, stage, ng, role)
                self.assertEqual(report["status"], "SYNTHETIC_ACTIVE_NOT_DEPLOYED")
                self.assertFalse(report["authenticated_vless"])
                self.assertTrue((root / engine.JOURNAL).exists())
                self.assertNotIn("Q" * 48, (root / engine.JOURNAL).read_text())
                with self.assertRaises(engine.TransactionRefused):
                    engine.install_mock(root, stage, ng, role)
                engine.recover(root)
                self.assert_restored(root, role, vhost, old)

    def test_failures_auto_revert_and_every_file_power_loss_recovers(self):
        stops = ("after-journal", "after-backup", "after-files",
                 "after-sidecar", "after-reload", "health")
        for role in ("ir", "kh"):
            for stop in stops:
                with self.subTest(role=role, failure=stop):
                    root, stage, ng, vhost, old = self.fixture(role)
                    with self.assertRaises(engine.TransactionRefused):
                        engine.install_mock(root, stage, ng, role, fail_at=stop)
                    self.assert_restored(root, role, vhost, old)
                with self.subTest(role=role, crash=stop):
                    root, stage, ng, vhost, old = self.fixture(role)
                    with self.assertRaises(engine.SimulatedPowerLoss):
                        engine.install_mock(root, stage, ng, role, crash_at=stop)
                    engine.recover(root)
                    self.assert_restored(root, role, vhost, old)
            for cut in range(1, len(pair.LAYOUT[role]) + 1):
                with self.subTest(role=role, file_crash=cut):
                    root, stage, ng, vhost, old = self.fixture(role)
                    with self.assertRaises(engine.SimulatedPowerLoss):
                        engine.install_mock(root, stage, ng, role,
                                            crash_after_file=cut)
                    engine.recover(root)
                    self.assert_restored(root, role, vhost, old)

    def test_resume_crashed_recovery(self):
        for role in ("ir", "kh"):
            for case in ("service", "file", "backup"):
                with self.subTest(role=role, case=case):
                    root, stage, ng, vhost, old = self.fixture(role)
                    engine.install_mock(root, stage, ng, role)
                    kwargs = {
                        "crash_after_service": case == "service",
                        "crash_after_file": 1 if case == "file" else None,
                        "crash_after_backup": case == "backup",
                    }
                    with self.assertRaises(engine.SimulatedPowerLoss):
                        engine.recover(root, **kwargs)
                    self.assertTrue((root / engine.JOURNAL).exists())
                    engine.recover(root)
                    self.assert_restored(root, role, vhost, old)

    def test_foreign_file_change_blocks_service_and_all_other_recovery(self):
        for role in ("ir", "kh"):
            root, stage, ng, vhost, _ = self.fixture(role)
            engine.install_mock(root, stage, ng, role)
            target = root / vhost.lstrip("/")
            target.write_bytes(target.read_bytes() + b"\n# third-party change\n")
            saved_runtime = (root / engine.RUNTIME).read_bytes()
            any_created = next(path for path, (op, _, _) in pair.LAYOUT[role].items()
                               if op == "create")
            before = (root / any_created.lstrip("/")).read_bytes()
            with self.subTest(role=role), self.assertRaises(engine.TransactionRefused):
                engine.recover(root)
            self.assertEqual(saved_runtime, (root / engine.RUNTIME).read_bytes())
            self.assertEqual(before, (root / any_created.lstrip("/")).read_bytes())

    def test_foreign_mock_service_change_blocks_file_recovery(self):
        root, stage, ng, vhost, _ = self.fixture("kh")
        engine.install_mock(root, stage, ng, "kh")
        state = engine._json_file(root / engine.RUNTIME)
        state["frp"] = "stopped"
        engine._save(root, engine.RUNTIME, state)
        current = (root / vhost.lstrip("/")).read_bytes()
        with self.assertRaises(engine.TransactionRefused):
            engine.recover(root)
        self.assertEqual(current, (root / vhost.lstrip("/")).read_bytes())

    def test_edit_preserves_mode_owner_group_before_and_after_rollback(self):
        for role, mode in (("ir", 0o644), ("kh", 0o640)):
            with self.subTest(role=role, permissions=oct(mode)):
                root, stage, ng, vhost, original = self.fixture(role)
                target = root / vhost.lstrip("/")
                target.chmod(mode)
                before = target.stat()
                engine.install_mock(root, stage, ng, role)
                installed = target.stat()
                self.assertEqual(installed.st_mode & 0o777, mode)
                self.assertEqual((installed.st_uid, installed.st_gid),
                                 (before.st_uid, before.st_gid))
                journal = engine._json_file(root / engine.JOURNAL)
                edit = next(row for row in journal["resources"]
                            if row["operation"] == "edit")
                self.assertEqual(edit["mode"], mode)
                self.assertEqual(edit["uid"], before.st_uid)
                self.assertEqual(edit["gid"], before.st_gid)
                engine.recover(root)
                restored = target.stat()
                self.assertEqual(restored.st_mode & 0o777, mode)
                self.assertEqual((restored.st_uid, restored.st_gid),
                                 (before.st_uid, before.st_gid))
                self.assertEqual(target.read_bytes(), original)

    def test_file_permission_drift_blocks_entire_rollback(self):
        for role in ("ir", "kh"):
            root, stage, ng, vhost, _ = self.fixture(role)
            engine.install_mock(root, stage, ng, role)
            victim = root / vhost.lstrip("/")
            victim.chmod(0o644)
            before_runtime = (root / engine.RUNTIME).read_bytes()
            with self.subTest(role=role), self.assertRaises(engine.TransactionRefused):
                engine.recover(root)
            self.assertEqual((root / engine.RUNTIME).read_bytes(), before_runtime)
            self.assertTrue((root / engine.JOURNAL).exists())

    def test_unsafe_original_permissions_refused_before_journal(self):
        for role in ("ir", "kh"):
            root, stage, ng, vhost, _ = self.fixture(role)
            (root / vhost.lstrip("/")).chmod(0o666)
            with self.subTest(role=role), self.assertRaises(engine.TransactionRefused):
                engine.install_mock(root, stage, ng, role)
            self.assertFalse((root / engine.JOURNAL).exists())

    def test_tampered_journal_metadata_blocks_recovery(self):
        for role in ("ir", "kh"):
            root, stage, ng, _, _ = self.fixture(role)
            engine.install_mock(root, stage, ng, role)
            journal = engine._json_file(root / engine.JOURNAL)
            journal["resources"][0]["uid"] = -1
            engine._save(root, engine.JOURNAL, journal)
            before_runtime = (root / engine.RUNTIME).read_bytes()
            with self.subTest(role=role), self.assertRaises(engine.TransactionRefused):
                engine.recover(root)
            self.assertEqual(before_runtime, (root / engine.RUNTIME).read_bytes())

    def test_tampered_nginx_plan_blocked_before_transaction(self):
        for role in ("ir", "kh"):
            root, stage, ng, vhost, _ = self.fixture(role)
            p = ng / "patched.conf"
            p.write_bytes(p.read_bytes() + b"\n# outsider\n")
            with self.subTest(role=role), self.assertRaises(pair.ReconcileRefused):
                engine.install_mock(root, stage, ng, role)
            self.assertFalse((root / engine.JOURNAL).exists())
            self.assertEqual(engine._json_file(root / engine.RUNTIME),
                             engine.original_runtime(role))

    def test_missing_kh_bridge_guard_mismatch_private_permissions(self):
        root, stage, ng, _, _ = self.fixture("kh")
        patch_file = ng / "patched.conf"
        patch_file.write_bytes(patch_file.read_bytes().replace(
            b"location ~ ^/0*13080(/|$)", b"location ~ ^/9999(/|$)"))
        with self.assertRaises(pair.ReconcileRefused):
            pair.reconcile("kh", stage, ng)
        root2, stage2, ng2, _, _ = self.fixture("kh")
        (ng2 / "kh-bridge.conf").chmod(0o644)
        with self.assertRaises(pair.ReconcileRefused):
            pair.reconcile("kh", stage2, ng2)
        root3, stage3, ng3, _, _ = self.fixture("ir")
        (stage3 / "UNEXPECTED").write_text("extra")
        with self.assertRaises(pair.ReconcileRefused):
            pair.reconcile("ir", stage3, ng3)

    def test_journal_ownership_backup_and_symlink_tampering_fail_closed(self):
        for scenario in ("unknown_path", "missing_vhost_backup", "symlink_journal"):
            with self.subTest(scenario=scenario):
                root, stage, ng, vhost, _ = self.fixture("kh")
                engine.install_mock(root, stage, ng, "kh")
                if scenario == "unknown_path":
                    data = engine._json_file(root / engine.JOURNAL)
                    data["resources"][-1]["path"] = "/etc/smite-node/legacy.conf"
                    engine._save(root, engine.JOURNAL, data)
                elif scenario == "missing_vhost_backup":
                    (root / engine.BACKUP).unlink()
                else:
                    journal = root / engine.JOURNAL
                    journal.unlink()
                    journal.symlink_to(root / engine.sandbox.MARKER)
                runtime = (root / engine.RUNTIME).read_bytes()
                with self.assertRaises(engine.TransactionRefused):
                    engine.recover(root)
                self.assertEqual(runtime, (root / engine.RUNTIME).read_bytes())

    def test_invalid_sandbox_or_fault_position_refuses(self):
        with tempfile.TemporaryDirectory(prefix="ordinary-lab-") as tmp:
            with self.assertRaises(engine.sandbox.SandboxRefused):
                engine.bootstrap(Path(tmp), "ir")
        root, stage, ng, _, _ = self.fixture("ir")
        for value in (0, -1, True, 99):
            with self.subTest(value=value), self.assertRaises(engine.TransactionRefused):
                engine.install_mock(root, stage, ng, "ir", crash_after_file=value)
            self.assertFalse((root / engine.JOURNAL).exists())

    def test_journal_never_discloses_private_token(self):
        root, stage, ng, _, _ = self.fixture("ir")
        engine.install_mock(root, stage, ng, "ir")
        self.assertNotIn("Q" * 48, (root / engine.JOURNAL).read_text())
        self.assertNotIn("Q" * 48, (root / engine.RUNTIME).read_text())
        self.assertNotIn("Q" * 48, (root / engine.BACKUP).read_text())
        engine.recover(root)


if __name__ == "__main__":
    unittest.main()
