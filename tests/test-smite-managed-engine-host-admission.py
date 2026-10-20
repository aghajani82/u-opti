#!/usr/bin/env python3
"""Independent read-only host gate, synthetic Docker and confidential state."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules/smite-managed-engine-host-admission.py"
spec = importlib.util.spec_from_file_location("joint_host_admission_test", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

COMPOSE = """services:
  smite-node:
    image: ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
      - node-data:/var/lib/smite-node
volumes:
  node-data:
    name: smite-node-data
"""
ENV = """NODE_ROLE=foreign
SMITE_NODE_PANEL_AUTH_MODE=signed
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
PANEL_SECRET=DO_NOT_PRINT_ME
"""


class SharedHostAdmission(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="two-engine-host-gate-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / "node"
        self.node.mkdir()
        self.config = self.node / "config"
        self.config.mkdir()
        self.data = self.base / "node-data"
        self.data.mkdir()
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)
        self.runtime = {
            "Name": "/smite-node",
            "State": {"Running": True},
            "Config": {"Image": "ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e",
                       "Env": ["SECRET=DO_NOT_PRINT_ME"]},
            "HostConfig": {"NetworkMode": "host", "PortBindings": {}},
            "Mounts": [
                {"Type": "bind", "Destination": "/etc/smite-node",
                 "Source": str(self.config)},
                {"Type": "volume", "Destination": "/var/lib/smite-node",
                 "Name": "smite-node-data", "Driver": "local",
                 "Source": str(self.data)},
            ],
        }
        genuine = gate.host._local_file

        def fixture_read(path, *, max_bytes, require_root=False):
            # Simulated test user is not root, never bypass in production.
            return genuine(path, max_bytes=max_bytes, require_root=False)

        patcher = patch.object(gate.host, "_local_file", side_effect=fixture_read)
        patcher.start()
        self.addCleanup(patcher.stop)

    def report(self, engine):
        return gate.report(engine, self.node, runtime=self.runtime, min_bytes=4096)

    def test_backhaul_and_frp_clean_core_never_grant_install(self):
        for engine in ("backhaul", "frp"):
            with self.subTest(engine=engine):
                result = self.report(engine)
                self.assertEqual(result["ENGINE"], engine.upper())
                self.assertEqual(result["NODE_ROLE"], "KH")
                self.assertEqual(result["CORE_PROFILE"], "MANAGED_STRICT")
                self.assertEqual(result["NODE_CONTAINER"], "RUNNING_REVIEWED_IMAGE")
                self.assertEqual(result["PERSISTENT_STORAGE"], "LOCAL_NAMED_VOLUME_CONFIRMED")
                self.assertEqual(result["SAVED_TUNNELS"], "ZERO")
                self.assertEqual(result["TARGET_ENGINE"], "NOT_INSTALLED")
                self.assertEqual(result["OTHER_ENGINE"], "NOT_INSTALLED")
                self.assertEqual(result["LOCAL_PREFLIGHT"], "PASS_LOCAL_ONLY_INCOMPLETE")
                self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
                self.assertEqual(result["SNAPSHOT_RESTORE"], "UNVERIFIED")
                self.assertEqual(result["HOST_TRANSACTION_AND_ROLLBACK"], "NOT_IMPLEMENTED")
                self.assertNotIn("DO_NOT_PRINT_ME", str(result))
        self.assertFalse((self.config / "engine-state").exists())

    def test_existing_other_engine_requires_signed_verification_not_uninstall(self):
        with patch.object(gate, "local_state", side_effect=lambda engine, node:
                          {"state": "ENROLLED_UNVERIFIED", "reason": "SIGNED_NODE_RECHECK_REQUIRED"}
                          if engine == "backhaul" else
                          {"state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}):
            r = self.report("frp")
            self.assertEqual(r["TARGET_ENGINE"], "NOT_INSTALLED")
            self.assertEqual(r["OTHER_ENGINE"], "ENROLLED_UNVERIFIED")
            self.assertEqual(r["OTHER_ENGINE_ACTION"], "NEVER_MODIFY")
            self.assertEqual(r["REASON"], "OTHER_ENGINE_SIGNED_STATUS_REQUIRED")
            self.assertEqual(r["LOCAL_PREFLIGHT"], "PASS_LOCAL_ONLY_INCOMPLETE")
            self.assertEqual(r["OTHER_ENGINE_ACTION"], "NEVER_MODIFY")
            self.assertEqual(r["SIGNED_NODE_HEALTH_AND_REPLAY"], "UNVERIFIED")
            self.assertEqual(r["INSTALL_ALLOWED"], "NO")
            self.assertEqual(r["ACTIVATION_GATE"], "HOLD")
        with patch.object(gate, "local_state", side_effect=lambda engine, node:
                          {"state": "UNAVAILABLE", "reason": "MISSING_READONLY_MOUNT"}
                          if engine == "frp" else
                          {"state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}):
            r = self.report("backhaul")
            self.assertEqual(r["REASON"], "OTHER_ENGINE_INCOMPLETE")

    def test_existing_target_never_suggested_for_reinstallation(self):
        with patch.object(gate, "local_state", side_effect=lambda engine, node:
                          {"state": "ENROLLED_UNVERIFIED", "reason": "SIGNED_NODE_RECHECK_REQUIRED"}
                          if engine == "frp" else
                          {"state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}):
            out = self.report("frp")
        self.assertEqual(out["REASON"], "TARGET_ENGINE_ALREADY_PRESENT")

    def test_persisted_tunnel_prevents_engine_install_preflight(self):
        (self.data / "tunnels.json").write_text(json.dumps({
            "saved": {"core": "frp", "spec": {"secret": "DO_NOT_PRINT_ME"}}
        }))
        result = self.report("backhaul")
        self.assertEqual(result["SAVED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(result["REASON"], "SAVED_TUNNELS_PRESENT")
        self.assertNotIn("DO_NOT_PRINT_ME", str(result))

    def test_unreviewed_image_or_published_docker_ports_are_hold(self):
        self.runtime["Config"]["Image"] = "smite-node:stage15-local"
        out = self.report("frp")
        self.assertEqual(out["REASON"], "NODE_IMAGE_NOT_DIGEST_PINNED")
        self.runtime["HostConfig"]["PortBindings"] = {"8888/tcp": [
            {"HostPort": "8888", "HostIp": "0.0.0.0"}]}
        out = self.report("backhaul")
        self.assertEqual(out["REASON"], "PUBLISHED_DOCKER_PORTS")
        self.assertEqual(out["INSTALL_ALLOWED"], "NO")

    def test_unmanaged_legacy_profile_fails_closed(self):
        (self.node / ".env").write_text(ENV.replace(
            "SMITE_AGENT_AUTH_MODE=strict", "SMITE_AGENT_AUTH_MODE=legacy"))
        out = self.report("frp")
        self.assertEqual(out["REASON"], "NOT_MANAGED_STRICT_CORE")

    def test_compose_change_during_review_halts_without_mutation(self):
        base_reader = gate.host._local_file
        calls = [0]

        def drifting(path, *, max_bytes, require_root=False):
            if path == self.node / "docker-compose.yml":
                calls[0] += 1
                if calls[0] >= 3:
                    return b"changed-other-compose"
            return base_reader(path, max_bytes=max_bytes, require_root=require_root)

        with patch.object(gate.host, "_local_file", side_effect=drifting):
            result = self.report("frp")
        self.assertEqual(result["REASON"], "COMPOSE_CHANGED_DURING_REVIEW")
        self.assertEqual((self.node / "docker-compose.yml").read_text(), COMPOSE)

    def test_no_external_executor_or_snapshot_proof(self):
        body = SCRIPT.read_text()
        for dangerous in ("docker compose up", "docker restart", "systemctl",
                          "subprocess.run", "subprocess.Popen", "os.system(",
                          "ssh ", "curl ", "iptables ", "nginx -s"):
            self.assertNotIn(dangerous, body)
        for engine in ("backhaul", "frp"):
            out = self.report(engine)
            self.assertEqual(out["INSTALL_ALLOWED"], "NO")
            self.assertEqual(out["ACTIVATION_GATE"], "HOLD")

    def test_cli_real_host_probe_always_hold_even_on_missing_node(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--engine", "frp",
                            "--node-dir", str(self.node), "--format", "json"],
                           text=True, capture_output=True, timeout=15)
        self.assertEqual(p.returncode, 2)
        parsed = json.loads(p.stdout)
        self.assertEqual(parsed["INSTALL_ALLOWED"], "NO")
        self.assertNotIn("DO_NOT_PRINT_ME", p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
