#!/usr/bin/env python3
"""Managed FRP operator status / menu, no actual Docker operations."""
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
SOURCE = ROOT / "modules/smite-managed-frp-control.py"
MENU = ROOT / "modules/smite-managed-frp-menu.sh"
BH_MENU = ROOT / "modules/smite-managed-backhaul-menu.sh"
spec = importlib.util.spec_from_file_location("managed_frp_operator_tests", SOURCE)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
COMPOSE = (
    "services:\n  smite-node:\n    image: smite-node:reviewed\n"
    "    network_mode: host\n    volumes:\n"
    "      - ./config:/etc/smite-node\n"
)
ENV = (
    "NODE_ROLE=foreign\nSMITE_AGENT_AUTH_MODE=strict\n"
    "SMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_ENGINE_INVENTORY_MODE=managed\n"
)


class FrpOperator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="frp-review-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.node = self.root / "node"
        self.node.mkdir()
        (self.node / "config").mkdir()
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)

    def cli(self, action):
        return subprocess.run(
            [sys.executable, "-B", str(SOURCE), action, "--node-dir", str(self.node)],
            capture_output=True, text=True, timeout=15,
        )

    def test_clean_managed_frp_status_and_review(self):
        out = self.cli("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("STATE=NOT_INSTALLED", out.stdout)
        self.assertIn("ROLE=KH", out.stdout)
        self.assertIn("SIGNED_NODE_STATUS=NOT_QUERIED", out.stdout)
        out = self.cli("review")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("BACKHAUL_DEPENDENCY=NONE", out.stdout)
        self.assertIn("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED", out.stdout)
        self.assertIn("INSTALL_ALLOWED=NO", out.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_host_install_and_rollback_always_denied(self):
        for action in ("install", "rollback"):
            with self.subTest(action=action):
                out = self.cli(action)
                self.assertEqual(out.returncode, 2)
                self.assertIn("NOT enabled", out.stderr)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_frp_status_preserves_preexisting_backhaul(self):
        directory = self.node / "config/engine-state"
        directory.mkdir(mode=0o700)
        manifest = directory / "engines.json"
        original = {"schema": 1, "engines": {"backhaul": {"sha256": "b" * 64}}}
        manifest.write_text(json.dumps(original))
        manifest.chmod(0o600)
        status = self.cli("review")
        self.assertEqual(status.returncode, 0)
        self.assertIn("STATE=NOT_INSTALLED", status.stdout)
        self.assertIn("BACKHAUL_DEPENDENCY=NONE", status.stdout)
        self.assertEqual(json.loads(manifest.read_text()), original)

    def test_partial_frp_mount_and_missing_server_denied(self):
        manifest_dir = self.node / "config/engine-state"
        manifest_dir.mkdir(mode=0o700)
        manifest = manifest_dir / "engines.json"
        manifest.write_text(json.dumps({"schema": 1, "engines": {
            "frp": {"sha256": "a" * 64, "server_sha256": "b" * 64}
        }}))
        manifest.chmod(0o600)
        status = self.cli("status")
        self.assertEqual(status.returncode, 0)
        self.assertIn("STATE=UNAVAILABLE", status.stdout)
        self.assertIn("MISSING_READONLY_MOUNT", status.stdout)
        manifest.write_text(json.dumps({"schema": 1, "engines": {
            "frp": {"sha256": "a" * 64}
        }}))
        self.assertIn("DUAL_FRP_DIGEST_REQUIRED", self.cli("status").stdout)

    def test_duplicate_env_and_untrusted_ports_rejected(self):
        (self.node / ".env").write_text(ENV + "SMITE_AGENT_AUTH_MODE=legacy\n")
        self.assertEqual(self.cli("status").returncode, 2)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE + "    ports:\n      - 8888:8888\n")
        self.assertEqual(self.cli("status").returncode, 2)

    def test_frp_menu_beginner_walkthrough_and_host_install_hold(self):
        env = {**os.environ, "SMITE_NODE_DIR": str(self.node), "TERM": "dumb"}
        process = subprocess.run(["bash", str(MENU), "--menu"], input="1\n2\n3\n0\n",
                                 capture_output=True, text=True, timeout=15, env=env)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("STATE=NOT_INSTALLED", process.stdout)
        self.assertIn("BACKHAUL_DEPENDENCY=NONE", process.stdout)
        self.assertIn("installation on real IR/KH is disabled", process.stdout)
        install = subprocess.run(["bash", str(MENU), "--install"], capture_output=True,
                                 text=True, timeout=15, env=env)
        self.assertEqual(install.returncode, 2)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_parent_has_separate_frp_and_existing_backhaul(self):
        source = BH_MENU.read_text()
        self.assertIn('5) FRP — Independent install/review', source)
        self.assertIn('smite_managed_frp_menu', source)
        self.assertIn('smite_managed_bh_menu', source)
        self.assertIn('3) Install Backhaul (not enabled yet)', source)
        for body in (SOURCE.read_text(), MENU.read_text()):
            for forbidden in ("docker compose up", "docker restart", "systemctl start",
                              "iptables ", "ufw ", "nginx -s", "ssh ", "curl "):
                self.assertNotIn(forbidden, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
