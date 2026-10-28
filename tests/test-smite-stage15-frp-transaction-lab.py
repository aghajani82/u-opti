#!/usr/bin/env python3
"""Stage15 FRP signed lifecycle — synthetic CI-only crash/recovery regression.

Never runs Docker, opens sockets, installs software or changes a real host.
Every test uses a private marked CI-style filesystem under TemporaryDirectory.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-stage15-frp-transaction-lab.py"
spec = importlib.util.spec_from_file_location("stage15_frp_txn_lab", SOURCE)
assert spec and spec.loader
tx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)


class SignedFrpLab(unittest.TestCase):
    def setUp(self):
        self.runner = tempfile.TemporaryDirectory(prefix="stage15-ci-runner-")
        self.addCleanup(self.runner.cleanup)
        self.root = Path(self.runner.name) / "uopti-stage15-frp-example"
        self.root.mkdir(mode=0o700)
        (self.root / "EXPERIMENTAL-LAB").write_bytes(tx.MARKER)
        self.node = self.root / "node"
        self.node.mkdir(mode=0o700)
        (self.node / "config").mkdir(mode=0o700)
        (self.root / "stages").mkdir(mode=0o700)
        (self.root / "protected").mkdir(mode=0o700)
        (self.node / "docker-compose.yml").write_text(
            "services:\n  smite-node:\n    image: smite-node:stage15-local\n"
            "    command: uvicorn main:app --host 127.0.0.1 --port 8888\n"
            "    network_mode: host\n    volumes:\n"
            "      - ./config:/etc/smite-node\n"
        )
        (self.node / "docker-compose.security-candidate.yml").write_text(
            "services:\n  smite-node:\n    environment:\n"
            "      - SMITE_AGENT_AUTH_MODE=strict\n"
            "      - SMITE_NODE_PANEL_AUTH_MODE=signed\n"
        )
        (self.node / ".env").write_text(
            "NODE_ROLE=foreign\nSMITE_AGENT_AUTH_MODE=strict\n"
            "SMITE_NODE_PANEL_AUTH_MODE=signed\n"
            "SMITE_ENGINE_INVENTORY_MODE=managed\n"
        )
        (self.root / "protected/identity.json").write_bytes(b'{"secret":"never-print"}')
        (self.root / "protected/replay.db").write_bytes(b"persistent-replay-store")
        self.frpc = b"CI-FRPC-0.71.0-DUAL-ROLE-BINARY"
        self.frps = b"CI-FRPS-0.71.0-DUAL-ROLE-BINARY"
        self.stage = self.root / "stages" / "frp-plan-test"
        self.stage.mkdir(mode=0o700)
        (self.stage / "frpc.bin").write_bytes(self.frpc)
        (self.stage / "frps.bin").write_bytes(self.frps)
        (self.stage / "compose.override.candidate.yml").write_bytes(
            tx.plan.STAGED_OVERLAY.encode()
        )
        self.manifest = {
            "schema": 1, "engines": {"frp": {
                "sha256": hashlib.sha256(self.frpc).hexdigest(),
                "server_sha256": hashlib.sha256(self.frps).hexdigest(),
            }}
        }
        (self.stage / "engines.candidate.json").write_text(
            json.dumps(self.manifest)
        )
        self.env = patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "aghajani82/u-opti",
            "RUNNER_TEMP": self.runner.name,
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.statuses = []

    def signed_probe(self, expected):
        self.statuses.append(expected)
        return "PASS"

    def activate(self, **kwargs):
        return tx.activate(self.root, self.stage,
                           official_verify=lambda _: True,
                           signed_probe=self.signed_probe, **kwargs)

    def rollback(self):
        return tx.rollback(self.root, signed_probe=self.signed_probe)

    def assert_restored(self):
        f = tx.paths(self.root)
        for name in ("overlay", "frpc", "frps", "manifest", "journal"):
            self.assertFalse(f[name].exists(), name)
        self.assertTrue(f["base"].is_file())
        self.assertTrue(f["signed"].is_file())
        self.assertEqual(f["identity"].read_bytes(), b'{"secret":"never-print"}')
        self.assertEqual(f["replay"].read_bytes(), b"persistent-replay-store")

    def test_dual_engine_pair_signed_state_retained_and_exact_rollback(self):
        with tx.lock(self.root):
            self.assertEqual(self.activate(), "CI_SIGNED_FRP_DUAL_PAIR_STAGED_NO_NODE_RESTART")
            f = tx.paths(self.root)
            self.assertEqual(f["frpc"].read_bytes(), self.frpc)
            self.assertEqual(f["frps"].read_bytes(), self.frps)
            self.assertIn(b"create_host_path: false", f["overlay"].read_bytes())
            self.assertEqual(json.loads(f["manifest"].read_text()), self.manifest)
            self.assertEqual(self.rollback(), "CI_SIGNED_FRP_EXACT_ROLLBACK_AND_REPLAY_PRESERVED")
        self.assertEqual(self.statuses, ["not-installed", "ready", "not-installed"])
        self.assert_restored()

    def test_crashes_at_each_checkpoint_are_recoverable(self):
        for point in ("journal", "frpc", "frps", "overlay", "manifest"):
            with self.subTest(point=point):
                self.statuses.clear()
                with tx.lock(self.root):
                    with self.assertRaises(tx.Interrupted):
                        self.activate(interrupt=point)
                    self.assertTrue(tx.paths(self.root)["journal"].exists())
                    self.assertEqual(self.rollback(), "CI_SIGNED_FRP_EXACT_ROLLBACK_AND_REPLAY_PRESERVED")
                self.assert_restored()

    def test_signed_probe_failure_triggers_compensating_rollback(self):
        def fail_ready(expected):
            self.statuses.append(expected)
            return "BAD" if expected == "ready" else "PASS"
        with tx.lock(self.root):
            with self.assertRaisesRegex(tx.Hold, "ENROLLMENT_FAILED_LAB_ROLLED_BACK"):
                tx.activate(self.root, self.stage, official_verify=lambda _: True,
                            signed_probe=fail_ready)
        self.assert_restored()
        self.assertEqual(self.statuses, ["not-installed", "ready", "not-installed"])

    def test_tampered_identity_blocks_rollback_without_erasing_journal(self):
        with tx.lock(self.root):
            self.activate()
            tx.paths(self.root)["identity"].write_bytes(b'{"secret":"changed"}')
            with self.assertRaisesRegex(tx.Hold, "SIGNED_IDENTITY_REPLAY_DRIFT"):
                self.rollback()
            self.assertTrue(tx.paths(self.root)["journal"].is_dir())

    def test_replaced_replay_inode_blocks_rollback(self):
        with tx.lock(self.root):
            self.activate()
            key = tx.paths(self.root)["replay"]
            key.unlink()
            key.write_bytes(b"persistent-replay-store")
            with self.assertRaisesRegex(tx.Hold, "SIGNED_IDENTITY_REPLAY_DRIFT"):
                self.rollback()
            self.assertTrue(tx.paths(self.root)["manifest"].exists())

    def test_existing_manifest_and_external_overlay_change_refused(self):
        f = tx.paths(self.root)
        state = f["manifest"].parent
        state.mkdir(mode=0o700)
        f["manifest"].write_text(json.dumps({
            "schema": 1, "engines": {"backhaul": {"sha256": "a" * 64}}
        }))
        self.manifest = json.loads((self.stage / "engines.candidate.json").read_text())
        self.manifest["engines"]["backhaul"] = {"sha256": "a" * 64}
        (self.stage / "engines.candidate.json").write_text(json.dumps(self.manifest))
        with tx.lock(self.root):
            with self.assertRaisesRegex(tx.Hold, "OTHER_ENGINE_REAL_HOST_TRANSACTION_HOLD"):
                self.activate()
        self.assertFalse(f["journal"].exists())
        self.assertFalse(f["overlay"].exists())

        f["manifest"].unlink()
        state.rmdir()
        self.manifest["engines"].pop("backhaul")
        (self.stage / "engines.candidate.json").write_text(json.dumps(self.manifest))
        with tx.lock(self.root):
            self.activate()
            f["overlay"].write_text("modified by another process")
            with self.assertRaisesRegex(tx.Hold, "STAGED_COMPONENT_EXTERNAL_DRIFT"):
                self.rollback()
            self.assertTrue(f["journal"].is_dir())

    def test_untrusted_official_stage_or_outside_ci_rejected(self):
        with tx.lock(self.root):
            with self.assertRaisesRegex(tx.Hold, "OFFICIAL_FRP_PAIR_NOT_VERIFIED"):
                tx.activate(self.root, self.stage, official_verify=lambda _: False,
                            signed_probe=self.signed_probe)
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaisesRegex(tx.Hold, "PR_CI_ONLY"):
                self.activate()
        self.assertFalse(tx.paths(self.root)["journal"].exists())

    def test_same_engine_lock_is_exclusive(self):
        with tx.lock(self.root):
            with self.assertRaisesRegex(tx.Hold, "ENGINE_TXN_LOCK_BUSY"):
                with tx.lock(self.root):
                    self.fail("Second transaction should be rejected")

    def test_module_has_no_live_host_cli(self):
        p = subprocess.run(
            [sys.executable, "-B", str(SOURCE), "activate", "--lab-root",
             str(self.root)],
            capture_output=True, text=True, timeout=12,
        )
        self.assertEqual(p.returncode, 2)
        self.assertIn("HOST_EXECUTOR_NOT_RELEASED", p.stderr)
        source = SOURCE.read_text()
        for forbidden in ("docker compose up", "docker restart",
                          "systemctl start", "nginx -s", "iptables ",
                          "urllib.request", "ssh "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
