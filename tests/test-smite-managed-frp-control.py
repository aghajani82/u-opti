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
        process = subprocess.run(["bash", str(MENU), "--menu"], input="1\n2\n3\n4\n0\n",
                                 capture_output=True, text=True, timeout=15, env=env)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("STATE=NOT_INSTALLED", process.stdout)
        self.assertIn("BACKHAUL_DEPENDENCY=NONE", process.stdout)
        self.assertIn("HOLD: Disposable IR/KH root only", process.stdout)
        install = subprocess.run(["bash", str(MENU), "--install"], capture_output=True,
                                 text=True, timeout=15, env=env)
        self.assertEqual(install.returncode, 2)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_stage15_readiness_is_read_only_and_never_authorizes_install(self):
        signed = self.node / "docker-compose.security-candidate.yml"
        signed.write_text("services:\\n  smite-node:\\n    environment:\\n")
        signed.chmod(0o600)
        values = {
            "SMITE_NODE_PANEL_AUTH_MODE": "signed",
            "SMITE_AGENT_AUTH_MODE": "strict",
            "SMITE_ENGINE_INVENTORY_MODE": "managed",
            "PANEL_ADDRESS": "02ir.kolbe1.ir:443",
        }
        runtime = {
            "Config": {
                "Image": "smite-node:stage15-local",
                "Env": [f"{k}={v}" for k, v in values.items()],
                "Cmd": ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"],
                "Labels": {
                    "com.docker.compose.project.config_files":
                        str(self.node / "docker-compose.yml") + "," + str(signed),
                },
            },
            "Image": control.STAGE15_NODE_ID,
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "HostConfig": {"NetworkMode": "host", "PortBindings": None, "Privileged": False},
            "Mounts": [
                {"Destination": "/etc/smite-node", "RW": True},
                {"Destination": "/run/smite-node-identity", "RW": False},
                {"Destination": "/var/lib/smite-node/auth", "RW": True},
            ],
        }
        calls = []
        def fake_run(argv):
            calls.append(argv)
            if argv[:3] == ["docker", "inspect", "smite-node"]:
                return json.dumps([runtime])
            if argv[:3] == ["docker", "image", "inspect"]:
                return control.STAGE15_NODE_ID
            if argv[:3] == ["docker", "exec", "smite-node"]:
                return "0.65.0"
            raise AssertionError(argv)

        result = control.stage15_readiness(self.node, run=fake_run)
        self.assertEqual(result["STAGE15_IMAGE"], "PINNED_TEST_ID_MATCH")
        self.assertEqual(result["HOST_FRP_INSTALL"], "HOLD_VERSION_AND_SIGNED_WSS_ADMISSION")
        self.assertEqual(result["FRP_BINARIES"], "STAGE15_BUNDLED_0_65_0")
        self.assertEqual(result["FRP_0_71_MANAGED_MATCH"], "NO")
        self.assertEqual(result["BUNDLED_FRP_PROVENANCE"], "NOT_ATTESTED")
        self.assertEqual(result["LIVE_CHANGES"], "NONE")
        self.assertEqual(result["FRP_ENGINE_ENROLLED"], "NO")
        self.assertFalse(any("restart" in argv or "up" in argv for argv in calls))

        # The current Standard installer uses the reviewed 9-token command.
        runtime["Image"] = control.STAGE15_FRP071_NODE_ID
        runtime["Config"]["Cmd"] = list(control.SAFE_NODE_COMMANDS[1])
        def new_image_run(argv):
            result = fake_run(argv)
            if argv[:3] == ["docker", "image", "inspect"]:
                return control.STAGE15_FRP071_NODE_ID
            if argv[:3] == ["docker", "exec", "smite-node"]:
                return "0.71.0"
            return result
        modern = control.stage15_readiness(self.node, run=new_image_run)
        self.assertEqual(modern["FRP_BINARIES"], "STAGE15_BUNDLED_0_71_0")
        for invalid in (
            list(control.SAFE_NODE_COMMANDS[1]) + ["--proxy-headers"],
            ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8888"],
            ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8899",
             "--log-level", "info", "--access-log"],
        ):
            runtime["Config"]["Cmd"] = invalid
            with self.assertRaisesRegex(control.Hold, "STAGE15_NODE_LOOPBACK_DRIFT"):
                control.stage15_readiness(self.node, run=new_image_run)
        runtime["Config"]["Cmd"] = list(control.SAFE_NODE_COMMANDS[0])
        runtime["Image"] = control.STAGE15_NODE_ID

        original = runtime["Image"]
        runtime["Image"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(control.Hold, "STAGE15_IMAGE_ID_MISMATCH"):
            control.stage15_readiness(self.node, run=fake_run)
        runtime["Image"] = original

        runtime["Config"]["Env"].append("SMITE_FRP_STANDARD_WSS=1")
        with self.assertRaisesRegex(control.Hold, "STAGE15_WSS_FLAG_UNREVIEWED"):
            control.stage15_readiness(self.node, run=fake_run)
        runtime["Config"]["Env"].pop()

        runtime["HostConfig"]["PortBindings"] = {"8888/tcp": [{"HostPort": "8888"}]}
        with self.assertRaisesRegex(control.Hold, "STAGE15_NODE_NETWORK_DRIFT"):
            control.stage15_readiness(self.node, run=fake_run)
        runtime["HostConfig"]["PortBindings"] = None

        runtime["Config"]["Labels"]["com.docker.compose.project.config_files"] = str(self.node / "docker-compose.yml")
        with self.assertRaisesRegex(control.Hold, "STAGE15_SIGNED_COMPOSE_NOT_ACTIVE"):
            control.stage15_readiness(self.node, run=fake_run)

    def test_stage15_readiness_rejects_incomplete_unsigned_core(self):
        (self.node / ".env").write_text(ENV.replace(
            "SMITE_AGENT_AUTH_MODE=strict",
            "SMITE_AGENT_AUTH_MODE=legacy"))
        calls = []
        def run(argv):
            calls.append(argv)
            raise AssertionError("Docker should not be queried for invalid Core")
        with self.assertRaisesRegex(control.Hold, "MANAGED_STRICT_CORE_REQUIRED"):
            control.stage15_readiness(self.node, run=run)
        self.assertEqual(calls, [])

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
