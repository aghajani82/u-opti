#!/usr/bin/env python3
"""Isolated transactional service+file recovery tests. No live host access."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, file: str):
    s = importlib.util.spec_from_file_location(name, ROOT / "modules" / file)
    module = importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(module)
    return module


engine = load("uopti_bh_tx_test", "smite-backhaul-sidecar-transaction-lab.py")
builder = load("uopti_bh_tx_builder", "smite-backhaul-sidecar.py")


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token_file = Path(self.temp.name) / "shared.token"
        self.token_file.write_text("T" * 48 + "\n")
        self.token_file.chmod(0o600)

    def fixture(self, role):
        temp = tempfile.TemporaryDirectory(prefix="uopti-bh-sandbox-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        engine.sb.bootstrap_mock(root, role)
        engine.bootstrap(root, role)
        stage = builder.prepare(role, self.token_file,
                                "ir.kolbe1.ir", "kh.kolbe1.ir")
        self.addCleanup(lambda p=stage: shutil.rmtree(p))
        return root, stage

    def assert_clean(self, root, role, original=None):
        self.assertFalse((root / engine.INTENT).exists())
        self.assertFalse((root / engine.lab.JOURNAL).exists())
        self.assertFalse((root / engine.lab.ORIGINAL).exists())
        self.assertEqual(engine._private_json(root / engine.RUNTIME),
                         engine.baseline(role))
        for path, op in engine.sb.rollback.ALLOW[role].items():
            target = root / path.lstrip("/")
            if op == "create":
                self.assertFalse(target.exists())
            else:
                self.assertEqual(target.read_bytes(), original)

    def original(self, root, role):
        if role == "ir":
            return (root / "etc/nginx/conf.d/u-opti-smite-panel-backend.conf").read_bytes()
        return None

    def test_successful_mock_install_and_owned_exact_rollback(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                root, stage = self.fixture(role)
                original = self.original(root, role)
                report = engine.deploy(root, stage, role)
                self.assertEqual("SYNTHETIC_ACTIVE", report["phase"])
                self.assertFalse(report["end_to_end_vless_verified"])
                self.assertEqual(report["file_count"], len(engine.sb.rollback.ALLOW[role]))
                evidence = engine.inspect(root)
                self.assertEqual("mock-reloaded", evidence["service_phase"])
                journal = (root / engine.INTENT).read_text()
                self.assertNotIn("T" * 48, journal)
                self.assertNotIn("T" * 48, (root / engine.lab.JOURNAL).read_text())
                with self.assertRaises(engine.TransactionRefused):
                    engine.deploy(root, stage, role)
                result = engine.rollback(root)
                self.assertIn("SYNTHETIC_ROLLBACK_OK", result)
                self.assert_clean(root, role, original)
                # In a clean state a fresh transaction is again possible.
                engine.deploy(root, stage, role)
                engine.rollback(root)
                self.assert_clean(root, role, original)

    def test_normal_failures_trigger_automatic_recovery(self):
        points = ("after-intent", "after-files", "validation", "after-sidecar",
                  "after-reload", "health")
        for role in ("ir", "kh"):
            for point in points:
                with self.subTest(role=role, point=point):
                    root, stage = self.fixture(role)
                    original = self.original(root, role)
                    with self.assertRaises(engine.TransactionRefused):
                        engine.deploy(root, stage, role, fail_at=point)
                    self.assert_clean(root, role, original)

    def test_power_loss_each_phase_and_resumable_rollback(self):
        points = ("after-intent", "after-files", "validation", "after-sidecar",
                  "after-reload", "health")
        for role in ("ir", "kh"):
            for point in points:
                with self.subTest(role=role, point=point):
                    root, stage = self.fixture(role)
                    original = self.original(root, role)
                    with self.assertRaises(engine.SimulatedPowerFailure):
                        engine.deploy(root, stage, role, interrupt_at=point)
                    self.assertTrue((root / engine.INTENT).is_file())
                    engine.inspect(root)
                    engine.rollback(root)
                    self.assert_clean(root, role, original)

    def test_crash_inside_each_file_write_recovers_after_restart(self):
        for role in ("ir", "kh"):
            count = len(engine.sb.rollback.ALLOW[role])
            for point in range(count + 1):
                with self.subTest(role=role, file_step=point):
                    root, stage = self.fixture(role)
                    original = self.original(root, role)
                    with self.assertRaises(engine.lab.SimulatedPowerLoss):
                        engine.deploy(root, stage, role, file_crash_after=point)
                    self.assertTrue((root / engine.INTENT).exists())
                    self.assertTrue((root / engine.lab.JOURNAL).exists())
                    engine.rollback(root)
                    self.assert_clean(root, role, original)

    def test_crash_between_file_journal_and_first_backup(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                root, stage = self.fixture(role)
                original = self.original(root, role)
                with self.assertRaises(engine.lab.SimulatedPowerLoss):
                    engine.deploy(root, stage, role,
                                  file_crash_before_backup=True)
                self.assertTrue((root / engine.INTENT).exists())
                self.assertTrue((root / engine.lab.JOURNAL).exists())
                engine.rollback(root)
                self.assert_clean(root, role, original)

    def test_invalid_fault_injection_rejected_before_journal(self):
        root, stage = self.fixture("ir")
        for kwargs in (
            {"file_crash_after": -1},
            {"file_crash_after": True},
            {"file_crash_after": 99},
            {"file_crash_after": 0, "file_crash_before_backup": True},
            {"file_crash_before_backup": "yes"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(engine.TransactionRefused):
                engine.deploy(root, stage, "ir", **kwargs)
            self.assertFalse((root / engine.INTENT).exists())

    def test_power_loss_during_rollback_can_resume_twice(self):
        for role in ("ir", "kh"):
            for cut in ("service", "files"):
                with self.subTest(role=role, cut=cut):
                    root, stage = self.fixture(role)
                    original = self.original(root, role)
                    engine.deploy(root, stage, role)
                    with self.assertRaises(engine.SimulatedPowerFailure):
                        engine.rollback(
                            root,
                            interrupt_after_service=(cut == "service"),
                            interrupt_after_files=(cut == "files"))
                    self.assertTrue((root / engine.INTENT).is_file())
                    engine.rollback(root)
                    self.assert_clean(root, role, original)

    def test_foreign_nginx_drift_refuses_before_service_rollback(self):
        root, stage = self.fixture("ir")
        engine.deploy(root, stage, "ir")
        victim = root / "etc/nginx/u-opti-sidecar/ir-control.inc"
        victim.write_bytes(victim.read_bytes() + b"\n# third-party change\n")
        service_before = (root / engine.RUNTIME).read_bytes()
        with self.assertRaises(engine.TransactionRefused):
            engine.rollback(root)
        self.assertEqual(service_before, (root / engine.RUNTIME).read_bytes())
        self.assertTrue((root / engine.INTENT).exists())

    def test_foreign_service_drift_refuses_without_file_changes(self):
        root, stage = self.fixture("kh")
        engine.deploy(root, stage, "kh")
        payload = engine._private_json(root / engine.RUNTIME)
        payload["frp"] = "disabled"
        engine._save(root, engine.RUNTIME, payload)
        old_files = {
            path: (root / path.lstrip("/")).read_bytes()
            for path in engine.sb.rollback.ALLOW["kh"]
        }
        with self.assertRaises(engine.TransactionRefused):
            engine.rollback(root)
        self.assertEqual(old_files, {
            path: (root / path.lstrip("/")).read_bytes() for path in old_files
        })

    def test_bad_state_or_symlink_refuses(self):
        root, stage = self.fixture("ir")
        engine.deploy(root, stage, "ir")
        intent = root / engine.INTENT
        saved = intent.read_bytes()
        intent.unlink()
        intent.symlink_to(root / engine.sb.MARKER)
        with self.assertRaises(engine.TransactionRefused):
            engine.rollback(root)
        intent.unlink()
        engine.lab._persist(intent, saved)
        state = engine._private_json(intent)
        state["sidecar"] = "smite-node"
        engine._save(root, engine.INTENT, state)
        with self.assertRaises(engine.TransactionRefused):
            engine.rollback(root)

    def test_no_host_files_network_or_service_commands(self):
        with tempfile.TemporaryDirectory(prefix="NOT-uopti-bh-sandbox-") as directory:
            with self.assertRaises(engine.sb.SandboxRefused):
                engine.bootstrap(Path(directory), "ir")
        source = (ROOT / "modules/smite-backhaul-sidecar-transaction-lab.py").read_text()
        self.assertNotIn("subprocess", source)
        self.assertNotIn("docker run", source)
        self.assertNotIn("nginx -s reload", source)


if __name__ == "__main__":
    unittest.main()
