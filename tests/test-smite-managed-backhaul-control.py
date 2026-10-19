#!/usr/bin/env python3
"""Read-only Backhaul operator review plus CI-only transaction admission."""
from __future__ import annotations
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
FILE = ROOT / "modules/smite-managed-backhaul-control.py"
MENU = ROOT / "modules/smite-managed-backhaul-menu.sh"

spec = importlib.util.spec_from_file_location("uopti_bh_control_test", FILE)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)

COMPOSE = """services:
  smite-node:
    image: smite-node:stage15-local
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
"""
ENV = """NODE_ROLE=foreign
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
"""


class OperatorControl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-bh-operator-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.node = self.root / "node"
        self.node.mkdir(mode=0o700)
        (self.node / "config").mkdir(mode=0o700)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)

    def run_control(self, action: str, *args):
        return subprocess.run(
            [sys.executable, "-B", str(FILE), action, *map(str, args)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )

    def test_no_engine_is_declared_even_when_binaries_are_bundled(self):
        output = self.run_control("status", "--node-dir", self.node)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn("ROLE=KH", output.stdout)
        self.assertIn("STATE=NOT_INSTALLED", output.stdout)
        self.assertIn("SIGNED_NODE_STATUS=NOT_QUERIED", output.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_review_refuses_real_install_and_never_requests_frp_or_ports(self):
        output = self.run_control("review", "--node-dir", self.node)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn("INSTALL_ALLOWED=NO", output.stdout)
        self.assertIn("FRP_DEPENDENCY=NONE", output.stdout)
        self.assertIn("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED", output.stdout)
        self.assertIn("HOST_DOCKER_ACTIONS=NONE", output.stdout)
        output = self.run_control("install", "--node-dir", self.node)
        self.assertEqual(output.returncode, 2)
        self.assertIn("activation is NOT enabled", output.stderr)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_partial_install_fails_closed_without_silent_ready(self):
        compose = self.node / "docker-compose.yml"
        compose.write_text(COMPOSE + "      - /opt/u-opti/engines/backhaul/v0.7.2/backhaul:/usr/local/bin/backhaul:ro\n")
        state = control.inspect(self.node)
        self.assertEqual(state["state"], "UNAVAILABLE")
        self.assertEqual(state["reason"], "PARTIAL_INSTALL_OR_DRIFT")

    def test_manifest_without_verified_binary_is_unavailable(self):
        state = self.node / "config/engine-state"
        state.mkdir(mode=0o700)
        manifest = state / "engines.json"
        manifest.write_text(json.dumps({
            "schema": 1,
            "engines": {
                "gost": {"sha256": "c" * 64},
                "backhaul": {"sha256": "a" * 64},
            },
        }))
        manifest.chmod(0o600)
        self.assertEqual(control.inspect(self.node)["state"], "UNAVAILABLE")
        self.assertIn("gost", manifest.read_text())
        manifest.chmod(0o644)
        with self.assertRaises(control.package.Hold):
            control.inspect(self.node)

    def test_duplicate_critical_env_or_unsafe_compose_denied(self):
        (self.node / ".env").write_text(ENV + "SMITE_AGENT_AUTH_MODE=legacy\n")
        with self.assertRaises(control.Hold):
            control.inspect(self.node)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE + "    ports:\n      - 443:443\n")
        with self.assertRaises(control.Hold):
            control.inspect(self.node)

    def test_bogus_archive_candidate_cannot_be_promoted(self):
        stage = self.root / "stage"
        stage.mkdir(mode=0o700)
        with self.assertRaises(control.Hold):
            control.verified_candidate(stage)
        self.assertEqual(self.run_control("verify-stage", "--stage", stage).returncode, 2)

    def test_install_and_rollback_fail_outside_ci(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false", "RUNNER_TEMP": self.tmp.name}):
            with self.assertRaises(control.transaction.Hold):
                control.exercise(self.root, action="install", stage=self.root / "fake-stage")
            with self.assertRaises(control.transaction.Hold):
                control.exercise(self.root, action="rollback")
        self.assertFalse((self.root / ".backhaul-control.lock").exists())
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_menu_is_clear_and_inert(self):
        result = subprocess.run(
            ["bash", str(MENU), "--install"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Host installation disabled", result.stderr)
        result = subprocess.run(
            ["bash", str(MENU), "--status"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "SMITE_NODE_DIR": str(self.node)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOT_INSTALLED", result.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_no_network_or_live_service_actions_in_menu_or_controller(self):
        script = MENU.read_text()
        controller = FILE.read_text()
        for text in ("apt-get ", "curl ", "docker compose up", "systemctl ",
                     "iptables ", "ufw ", "ssh ", "nginx -s"):
            self.assertNotIn(text, script)
            self.assertNotIn(text, controller)
        parent = (ROOT / "modules/smite-backhaul-management.sh").read_text()
        self.assertIn('5) Independent Engines (Backhaul review)', parent)
        self.assertIn('smite_managed_bh_menu', parent)
        self.assertIn('4) docker_smite_advanced_menu', parent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
