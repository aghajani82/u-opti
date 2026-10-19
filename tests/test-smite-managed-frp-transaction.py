#!/usr/bin/env python3
"""FRP lab journal tests: two binaries, crash injection and other-engine safety.

Uses synthetic, non-executable ELF fixtures inside a disposable temp tree;
NO network, production Docker, tunneling, service mutation or public ports.
"""
from __future__ import annotations
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def read(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


frp = read("frp_package_ci_lab", "modules/smite-managed-frp.py")
tx = read("frp_transaction_ci_lab", "modules/smite-managed-frp-transaction.py")

ENV = (
    "NODE_ROLE=foreign\nSMITE_ENGINE_INVENTORY_MODE=managed\n"
    "SMITE_AGENT_AUTH_MODE=strict\nSMITE_NODE_PANEL_AUTH_MODE=paused\n"
)
COMPOSE = (
    "services:\n  smite-node:\n    image: smite-node:reviewed\n"
    "    network_mode: host\n    volumes:\n"
    "      - ./config:/etc/smite-node\n"
)


def elf(kind):
    data = bytearray(128)
    data[:4] = b"\x7fELF"
    data[4] = 2
    data[5] = 1
    struct.pack_into("<H", data, 18, 62)
    return bytes(data) + kind.encode()


class FrpLabTransaction(unittest.TestCase):
    def setUp(self):
        self.outer = tempfile.TemporaryDirectory(prefix="uopti-frp-runner-")
        self.addCleanup(self.outer.cleanup)
        self.runner = Path(self.outer.name)
        self.root = Path(tempfile.mkdtemp(prefix="frp-txn-", dir=self.runner))
        self.root.chmod(0o700)
        (self.root / "EXPERIMENTAL-LAB").write_text(tx.MARKER)
        node = self.root / "node"
        node.mkdir(mode=0o700)
        cfg = node / "config"
        cfg.mkdir(mode=0o700)
        stages = self.root / "stages"
        stages.mkdir(mode=0o700)
        (node / ".env").write_text(ENV)
        (node / "docker-compose.yml").write_text(COMPOSE)
        self.node = node
        self.manifest = cfg / "engine-state/engines.json"
        self.archive = self.root / "synthetic.tar.gz"
        folder = "frp_0.71.0_linux_amd64"
        with tarfile.open(self.archive, "w:gz") as tf:
            for name in ("frpc", "frps"):
                blob = elf(name)
                info = tarfile.TarInfo(folder + "/" + name)
                info.size = len(blob)
                tf.addfile(info, io.BytesIO(blob))
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.stage = frp.prepare(node, self.archive, stages, arch="amd64",
                                 allowed_sha=digest)
        self.env = patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "aghajani82/u-opti",
            "RUNNER_TEMP": str(self.runner),
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def assert_clean(self):
        self.assertEqual((self.node / "docker-compose.yml").read_text(), COMPOSE)
        self.assertFalse(self.manifest.exists())
        self.assertFalse((self.root / "installed/frp/frpc").exists())
        self.assertFalse((self.root / "installed/frp/frps").exists())
        self.assertFalse((self.root / "frp-recovery-journal").exists())

    def test_install_pair_then_exact_rollback(self):
        with tx.lock(self.root):
            self.assertEqual(tx.activate(self.root, self.stage, fixture=True),
                             "FRP_LAB_DUAL_BINARIES_ENROLLED_NO_NODE_RESTART")
            self.assertTrue((self.root / "installed/frp/frpc").is_file())
            self.assertTrue((self.root / "installed/frp/frps").is_file())
            compiled = json.loads(self.manifest.read_text())
            self.assertEqual(set(compiled["engines"]), {"frp"})
            self.assertEqual(set(compiled["engines"]["frp"]), {"sha256", "server_sha256"})
            self.assertIn("/usr/local/bin/frpc:ro", (self.node / "docker-compose.yml").read_text())
            self.assertIn("/usr/local/bin/frps:ro", (self.node / "docker-compose.yml").read_text())
            self.assertEqual(tx.rollback(self.root),
                             "FRP_LAB_EXACT_ROLLBACK_CONFIRMED_NO_OTHER_ENGINE_CHANGED")
        self.assert_clean()

    def test_all_interruption_points_recovered(self):
        for point in ("after-journal", "after-frpc", "after-frps",
                      "after-compose", "after-manifest"):
            with self.subTest(point=point):
                with tx.lock(self.root):
                    with self.assertRaisesRegex(tx.Hold, "INJECTED_INTERRUPTION"):
                        tx.activate(self.root, self.stage, fixture=True, inject=point)
                    self.assertTrue((self.root / "frp-recovery-journal").is_dir())
                    self.assertEqual(tx.rollback(self.root),
                                     "FRP_LAB_EXACT_ROLLBACK_CONFIRMED_NO_OTHER_ENGINE_CHANGED")
                self.assert_clean()

    def test_existing_backhaul_declaration_and_files_survive_pair_transaction(self):
        state = self.manifest.parent
        state.mkdir(mode=0o700)
        before = {"schema": 1, "engines": {"backhaul": {"sha256": "a"*64}}}
        self.manifest.write_text(json.dumps(before))
        self.manifest.chmod(0o600)
        original_manifest = self.manifest.read_bytes()
        stable = COMPOSE + "      - /opt/u-opti/engines/backhaul/v0.7.2/backhaul:/usr/local/bin/backhaul:ro\n"
        (self.node / "docker-compose.yml").write_text(stable)
        # Regenerate a proposal tied to the old Compose and other engines.
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        stage = frp.prepare(self.node, self.archive, self.root / "stages",
                            arch="amd64", allowed_sha=digest)
        with tx.lock(self.root):
            tx.activate(self.root, stage, fixture=True)
            current = json.loads(self.manifest.read_text())
            self.assertEqual(current["engines"]["backhaul"], before["engines"]["backhaul"])
            self.assertIn("/usr/local/bin/backhaul:ro", (self.node / "docker-compose.yml").read_text())
            tx.rollback(self.root)
        self.assertEqual(self.manifest.read_bytes(), original_manifest)
        self.assertEqual((self.node / "docker-compose.yml").read_text(), stable)
        self.assertFalse((self.root / "installed/frp").exists())

    def test_saved_tunnel_is_hard_hold_before_mutation(self):
        data = self.root / "node-data"
        data.mkdir(mode=0o700)
        (data / "tunnels.json").write_text(
            '{"active-frp":{"core":"frp","token":"NEVER_LOG_THIS_SECRET"}}')
        with self.assertRaisesRegex(tx.Hold, "EXISTING_TUNNELS_NO_RECREATE"):
            tx.activate(self.root, self.stage, fixture=True)
        self.assertFalse((self.root / "frp-recovery-journal").exists())
        self.assertFalse((self.root / "installed").exists())

    def test_identity_change_refuses_unsafe_rollback(self):
        identity = self.node / "config/identity"
        identity.mkdir(mode=0o700)
        key = identity / "node-identity.json"
        key.write_text('{"private":"DO_NOT_ECHO_THIS"}')
        tx.activate(self.root, self.stage, fixture=True)
        key.write_text('{"private":"out-of-band-change"}')
        with self.assertRaisesRegex(tx.Hold, "PROTECTED_NODE_IDENTITY_OR_TUNNELS_CHANGED"):
            tx.rollback(self.root)
        self.assertTrue((self.root / "frp-recovery-journal").exists())

    def test_concurrent_lock_denied(self):
        with tx.lock(self.root):
            with self.assertRaisesRegex(tx.Hold, "ANOTHER_FRP_TRANSACTION_ACTIVE"):
                with tx.lock(self.root):
                    self.fail("concurrent transaction was not refused")

    def test_changed_compose_cannot_be_silently_overwritten(self):
        tx.activate(self.root, self.stage, fixture=True)
        with (self.node / "docker-compose.yml").open("a") as f:
            f.write("# someone else changed Compose\n")
        with self.assertRaisesRegex(tx.Hold, "COMPOSE_MODIFIED_EXTERNALLY_NO_OVERWRITE"):
            tx.rollback(self.root)
        self.assertTrue((self.root / "frp-recovery-journal").exists())

    def test_unverified_archive_denied_outside_pr_context(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaises(tx.lab.Hold):
                tx.activate(self.root, self.stage, fixture=True)
        self.assertFalse((self.root / "frp-recovery-journal").exists())
        with self.assertRaisesRegex(tx.Hold, "FRP_CANDIDATE_VERIFICATION_FAILED"):
            tx.activate(self.root, self.stage, fixture=False)
        self.assertFalse((self.root / "frp-recovery-journal").exists())
        command = subprocess.run([
            sys.executable, "-B", str(ROOT / "modules/smite-managed-frp-transaction.py"),
            "activate", "--lab-root", str(self.root), "--stage", str(self.stage),
        ], capture_output=True, text=True, timeout=15)
        self.assertEqual(command.returncode, 2)
        self.assertIn("HOLD", command.stderr)

    def test_no_real_host_executors_or_network(self):
        source = (ROOT / "modules/smite-managed-frp-transaction.py").read_text()
        for phrase in ("docker compose up", "subprocess.run", "systemctl ",
                       "nginx -s", "iptables ", "ssh ", "requests.",
                       "urllib.request", "socket."):
            self.assertNotIn(phrase, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
