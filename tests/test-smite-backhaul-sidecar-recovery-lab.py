#!/usr/bin/env python3
"""Fail-closed synthetic crash+restart+recovery tests; never uses host /etc."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    s = importlib.util.spec_from_file_location(name, ROOT / "modules" / filename)
    module = importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(module)
    return module


lab = load("uopti_recovery_lab_test", "smite-backhaul-sidecar-recovery-lab.py")
sidecar = load("uopti_sidecar_generator_test", "smite-backhaul-sidecar.py")


class RecoveryLabTests(unittest.TestCase):
    def setUp(self):
        self.tokens = tempfile.TemporaryDirectory()
        self.addCleanup(self.tokens.cleanup)
        self.token_file = Path(self.tokens.name) / "private-token"
        self.token_file.write_text("A" * 48 + "\n")
        self.token_file.chmod(0o600)

    def fixture(self, role):
        tmp = tempfile.TemporaryDirectory(prefix="uopti-bh-sandbox-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        lab.sandbox.bootstrap_mock(root, role)
        stage = sidecar.prepare(role, self.token_file, "ir.kolbe1.ir", "kh.kolbe1.ir")
        self.addCleanup(lambda p=stage: shutil.rmtree(p))
        return root, stage

    def target(self, root, path):
        return root / path.lstrip("/")

    def assert_reverted(self, root, role, original=None):
        self.assertFalse((root / lab.JOURNAL).exists())
        self.assertFalse((root / lab.ORIGINAL).exists())
        for path, operation in lab.sandbox.rollback.ALLOW[role].items():
            dest = self.target(root, path)
            if operation == "create":
                self.assertFalse(dest.exists())
            else:
                self.assertEqual(dest.read_bytes(), original)

    def test_complete_apply_and_later_recovery_without_live_services(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                root, stage = self.fixture(role)
                before = None
                if role == "ir":
                    before = self.target(
                        root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
                    ).read_bytes()
                record = lab.begin_synthetic_transaction(root, stage, role)
                self.assertEqual(set(record), {"version", "role", "container", "resources"})
                self.assertEqual(record["role"], role)
                self.assertNotIn("A" * 48, json.dumps(record))
                self.assertNotIn("A" * 48, (root / lab.JOURNAL).read_text())
                status = lab.inspect_synthetic_recovery(root)
                self.assertEqual(status["applied"], len(record["resources"]))
                result = lab.recover_synthetic_transaction(root)
                self.assertIn("NO Docker/Smite/FRP/Xray/Nginx operations", result)
                self.assert_reverted(root, role, before)

    def test_any_interrupted_install_can_recover_in_new_call(self):
        for role in ("ir", "kh"):
            size = len(lab.sandbox.rollback.ALLOW[role])
            for interrupted_at in range(0, size+1):
                with self.subTest(role=role, cut=interrupted_at):
                    root, stage = self.fixture(role)
                    original = (
                        self.target(
                            root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
                        ).read_bytes() if role == "ir" else None
                    )
                    with self.assertRaises(lab.SimulatedPowerLoss):
                        lab.begin_synthetic_transaction(
                            root, stage, role, crash_after=interrupted_at
                        )
                    self.assertTrue((root / lab.JOURNAL).is_file())
                    self.assertTrue(lab.inspect_synthetic_recovery(root)["recoverable"])
                    lab.recover_synthetic_transaction(root)
                    self.assert_reverted(root, role, original)

    def test_interruption_between_journal_and_original_backup(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                root, stage = self.fixture(role)
                prior = (
                    self.target(
                        root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
                    ).read_bytes() if role == "ir" else None
                )
                with self.assertRaises(lab.SimulatedPowerLoss):
                    lab.begin_synthetic_transaction(
                        root, stage, role, crash_after_journal_only=True
                    )
                self.assertTrue((root / lab.JOURNAL).exists())
                self.assertFalse((root / lab.ORIGINAL).exists())
                info = lab.inspect_synthetic_recovery(root)
                self.assertEqual(info["applied"], 0)
                lab.recover_synthetic_transaction(root)
                self.assert_reverted(root, role, prior)

    def test_interrupted_recovery_is_idempotently_resumable(self):
        for role in ("ir", "kh"):
            size = len(lab.sandbox.rollback.ALLOW[role])
            for cut in range(0, size+1):
                with self.subTest(role=role, cut=cut):
                    root, stage = self.fixture(role)
                    before = (
                        self.target(root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf").read_bytes()
                        if role == "ir" else None
                    )
                    lab.begin_synthetic_transaction(root, stage, role)
                    with self.assertRaises(lab.SimulatedPowerLoss):
                        lab.recover_synthetic_transaction(root, crash_after_restored=cut)
                    assert (root / lab.JOURNAL).is_file()
                    lab.recover_synthetic_transaction(root)
                    self.assert_reverted(root, role, before)

    def test_finalization_crash_keeps_journal_until_cleanup_completes(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                root, stage = self.fixture(role)
                before = (
                    self.target(
                        root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
                    ).read_bytes() if role == "ir" else None
                )
                lab.begin_synthetic_transaction(root, stage, role)
                with self.assertRaises(lab.SimulatedPowerLoss):
                    lab.recover_synthetic_transaction(
                        root, crash_during_finalization=True
                    )
                self.assertTrue((root / lab.JOURNAL).is_file())
                self.assertFalse((root / lab.ORIGINAL).exists())
                status = lab.inspect_synthetic_recovery(root)
                self.assertEqual(status["applied"], 0)
                with self.assertRaises(lab.RecoveryRefused):
                    lab.begin_synthetic_transaction(root, stage, role)
                lab.recover_synthetic_transaction(root)
                self.assert_reverted(root, role, before)

    def test_drift_detected_before_touching_any_other_resource(self):
        for role in ("ir", "kh"):
            root, stage = self.fixture(role)
            lab.begin_synthetic_transaction(root, stage, role)
            targets = lab.sandbox.rollback.ALLOW[role]
            paths = list(targets)
            victim = self.target(root, paths[0])
            original_bytes = victim.read_bytes()
            victim.write_bytes(original_bytes + b"\n# synthetic external drift\n")
            last = self.target(root, paths[-1]).read_bytes()
            with self.subTest(role=role), self.assertRaises(lab.RecoveryRefused):
                lab.recover_synthetic_transaction(root)
            self.assertEqual(victim.read_bytes(), original_bytes + b"\n# synthetic external drift\n")
            self.assertEqual(self.target(root, paths[-1]).read_bytes(), last)
            self.assertTrue((root / lab.JOURNAL).exists())

    def test_invalid_journal_unknown_path_and_missing_backup_fail_closed(self):
        for tamper in ("unknown_target", "invalid_hash", "missing_backup", "symlink_journal"):
            with self.subTest(tamper=tamper):
                root, stage = self.fixture("ir")
                lab.begin_synthetic_transaction(root, stage, "ir")
                journal = root / lab.JOURNAL
                state = json.loads(journal.read_text())
                if tamper == "unknown_target":
                    state["resources"][0]["path"] = "/etc/smite-node/backhaul/legacy.toml"
                elif tamper == "invalid_hash":
                    state["resources"][1]["applied_sha256"] = "a"
                elif tamper == "missing_backup":
                    (root / lab.ORIGINAL).unlink()
                elif tamper == "symlink_journal":
                    journal.unlink()
                    journal.symlink_to(root / lab.sandbox.MARKER)
                if tamper in ("unknown_target", "invalid_hash"):
                    lab.sandbox.atomic_write(journal, json.dumps(state).encode())
                old = self.target(root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf").read_bytes()
                with self.assertRaises((lab.RecoveryRefused, lab.sandbox.rollback.RollbackUnsafe)):
                    lab.recover_synthetic_transaction(root)
                self.assertEqual(
                    self.target(root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf").read_bytes(),
                    old,
                )

    def test_reject_non_sandbox_and_refuse_double_install(self):
        other = tempfile.TemporaryDirectory(prefix="unrelated-")
        self.addCleanup(other.cleanup)
        root, stage = self.fixture("kh")
        with self.assertRaises(lab.sandbox.SandboxRefused):
            lab.begin_synthetic_transaction(Path(other.name), stage, "kh")
        lab.begin_synthetic_transaction(root, stage, "kh")
        with self.assertRaises(lab.RecoveryRefused):
            lab.begin_synthetic_transaction(root, stage, "kh")
        lab.recover_synthetic_transaction(root)

    def test_backup_tampering_refuses_every_file_change(self):
        root, stage = self.fixture("ir")
        lab.begin_synthetic_transaction(root, stage, "ir")
        path = root / lab.ORIGINAL
        path.write_bytes(b"not an original backend")
        snapshot = {
            name: self.target(root, name).read_bytes()
            for name in lab.sandbox.rollback.ALLOW["ir"]
        }
        with self.assertRaises(lab.RecoveryRefused):
            lab.recover_synthetic_transaction(root)
        self.assertEqual(
            snapshot,
            {name: self.target(root, name).read_bytes() for name in snapshot},
        )


if __name__ == "__main__":
    unittest.main()
