#!/usr/bin/env python3
"""Offline RC.2 FRP inventory transaction tests: no Docker or VPS changes."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "modules/smite-rc2-frp-bundled-enrollment.py"
spec = importlib.util.spec_from_file_location("rc2_frp_enrollment", SRC)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class EnrollmentTrial(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-frp-rc2-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.node = root / "node"
        self.node.mkdir(mode=0o700)
        self.config = self.node / "config"
        self.config.mkdir(mode=0o700)
        self.identity = root / "identity.json"
        self.identity.write_bytes(b"fixture-identity")
        self.replay = root / "agent-replay.sqlite3"
        self.replay.write_bytes(b"fixture-replay")
        self.lockpath = root / "lock"
        paths = {
            "NODE": self.node, "CONFIG": self.config,
            "MANIFEST_DIR": self.config / "engine-state",
            "MANIFEST": self.config / "engine-state" / "engines.json",
            "JOURNAL_DIR": self.node / "frp-rc2-enrollment-journal",
            "JOURNAL": self.node / "frp-rc2-enrollment-journal" / "record.json",
            "LOCK": self.lockpath, "IDENTITY": self.identity,
            "REPLAY": self.replay,
        }
        for name, path in paths.items():
            patcher = patch.object(mod, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls = []
        def fake_regular(p, **kwargs):
            if p.is_symlink() or not p.is_file():
                raise mod.Hold("UNSAFE_TEST_FILE")
            return p.read_bytes()
        def fake_dir(p, private=False):
            st = p.lstat()
            if not stat.S_ISDIR(st.st_mode):
                raise mod.Hold("UNSAFE_DIRECTORY")
            if private and stat.S_IMODE(st.st_mode) != 0o700:
                raise mod.Hold("UNSAFE_DIRECTORY_MODE")
        def fake_lock():
            return os.open(self.lockpath, os.O_RDWR | os.O_CREAT, 0o600)
        def fake_preflight(host):
            if host != "kh":
                raise mod.Hold("WRONG_HOST")
            return {
                "identity_sha256": hashlib.sha256(self.identity.read_bytes()).hexdigest(),
                "replay_identity": self.replay_key(),
            }
        def fake_probe(expected):
            self.calls.append(expected)
            actual = "ready" if mod.MANIFEST.is_file() else "not-installed"
            if actual != expected:
                raise mod.Hold("SIGNED_INVENTORY_FAILED")
        for name, fn in (
            ("regular", fake_regular), ("directory", fake_dir),
            ("lock", fake_lock), ("host_preflight", fake_preflight),
            ("signed_probe", fake_probe),
        ):
            patcher = patch.object(mod, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def replay_key(self):
        st = self.replay.lstat()
        return str(st.st_dev) + ":" + str(st.st_ino)

    def test_plan_has_no_mutations_or_signed_replay_request(self):
        with patch.object(mod, "local_probe", side_effect=lambda x: self.calls.append("local:"+x)):
            mod.plan("kh")
        self.assertEqual(self.calls, ["local:not-installed"])
        self.assertFalse(mod.MANIFEST_DIR.exists())
        self.assertFalse(mod.JOURNAL_DIR.exists())

    def test_enroll_verify_and_explicit_rollback(self):
        mod.enroll("kh")
        self.assertEqual(self.calls, ["not-installed", "ready"])
        self.assertEqual(mod.MANIFEST.read_bytes(), mod.expected_manifest())
        self.assertEqual(stat.S_IMODE(mod.MANIFEST_DIR.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(mod.MANIFEST.stat().st_mode), 0o600)
        self.assertEqual(mod.journal("kh")["replay_identity"], self.replay_key())
        mod.verify("kh")
        self.assertEqual(self.calls[-1], "ready")
        mod.rollback("kh")
        self.assertEqual(self.calls[-2:], ["ready", "not-installed"])
        self.assertFalse(mod.MANIFEST.exists())
        self.assertFalse(mod.JOURNAL.exists())
        self.assertEqual(self.identity.read_bytes(), b"fixture-identity")
        self.assertEqual(self.replay.read_bytes(), b"fixture-replay")

    def test_signed_activation_failure_rolls_back_to_absent(self):
        def reject_ready(expected):
            self.calls.append(expected)
            if expected == "ready":
                raise mod.Hold("SIGNED_READY_UNAVAILABLE")
            if mod.MANIFEST.exists():
                raise mod.Hold("NOT_ROLLED_BACK")
        with patch.object(mod, "signed_probe", side_effect=reject_ready):
            with self.assertRaisesRegex(mod.Hold, "ENROLLMENT_FAILED_ROLLED_BACK"):
                mod.enroll("kh")
        self.assertFalse(mod.MANIFEST.exists())
        self.assertFalse(mod.JOURNAL_DIR.exists())

    def test_manifest_drift_preserves_journal_for_manual_review(self):
        mod.enroll("kh")
        mod.MANIFEST.write_text('{"tampered":true}')
        with self.assertRaisesRegex(mod.Hold, "MANIFEST_EXTERNAL_DRIFT"):
            mod.rollback("kh")
        self.assertTrue(mod.JOURNAL.is_file())
        self.assertTrue(mod.MANIFEST.is_file())

    def test_incomplete_journal_never_auto_retries(self):
        mod.JOURNAL_DIR.mkdir(mode=0o700)
        with self.assertRaisesRegex(mod.Hold, "PREVIOUS_ENROLLMENT_PRESENT"):
            mod.enroll("kh")
        self.assertFalse(mod.MANIFEST.is_file())

    def test_replay_nonce_inserts_not_treated_as_tampering(self):
        proof = {"identity_sha256": hashlib.sha256(self.identity.read_bytes()).hexdigest(),
                 "replay_identity": self.replay_key()}
        # Authenticated inventory GET naturally appends durable replay nonces.
        with self.replay.open("ab") as out:
            out.write(b"valid-new-nonce")
        mod.unchanged(proof)
        replacement = self.replay.with_suffix(".replacement")
        replacement.write_bytes(b"different-db")
        os.replace(replacement, self.replay)
        with self.assertRaisesRegex(mod.Hold, "REPLAY_STORAGE_REPLACED"):
            mod.unchanged(proof)

    def test_protected_identity_change_blocks_rollback(self):
        mod.enroll("kh")
        self.identity.write_bytes(b"changed-identity")
        with self.assertRaisesRegex(mod.Hold, "IDENTITY_CHANGED"):
            mod.rollback("kh")
        self.assertTrue(mod.JOURNAL.is_file())
        self.assertTrue(mod.MANIFEST.is_file())

    def test_missing_engine_manifest_must_not_fake_ready(self):
        mod.enroll("kh")
        mod.MANIFEST.unlink()
        with self.assertRaisesRegex(mod.Hold, "MANIFEST_CHANGED"):
            mod.verify("kh")
        self.assertTrue(mod.JOURNAL.is_file())

    def test_no_docker_recreate_or_public_firewall_operations(self):
        source = SRC.read_text()
        for forbidden in ("--force-recreate", "iptables ", "ufw ",
                          "nginx -s", "docker compose up", "systemctl restart",
                          "SMITE_AGENT_AUTH_MODE=legacy", "/api/agent/tunnels/apply"):
            self.assertNotIn(forbidden, source)
        self.assertIn('SMITE_ENGINE_INVENTORY_MODE=managed', source)
        self.assertIn('SMITE_NODE_PANEL_AUTH_MODE=signed', source)
        self.assertIn('LOCK = Path("/run/lock/u-opti-smite-engine.lock")', source)
        self.assertIn('RC.2-only', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
