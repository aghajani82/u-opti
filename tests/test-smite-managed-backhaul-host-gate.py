#!/usr/bin/env python3
"""Host Backhaul safety gate; no VPS mutation, no network/FRP control."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules" / "smite-managed-backhaul-host-gate.py"
spec = importlib.util.spec_from_file_location("bh_gate_review", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

COMPOSE = """services:
  smite-node:
    image: smite-node:stage15-local
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
"""


class ReadOnlyGate(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.node = self.root / "node"
        self.node.mkdir()
        self.cfg = self.node / "config"
        self.cfg.mkdir()
        self.data = self.root / "data"
        self.data.mkdir()
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)
        self.runtime = {
            "Name": "/smite-node",
            "State": {"Running": True},
            "Config": {"Image": "smite-node:stage15-local", "Env": ["TOKEN=DONT_PRINT"]},
            "HostConfig": {"NetworkMode": "host", "PortBindings": {}},
            "Mounts": [
                {"Type": "bind", "Destination": "/etc/smite-node", "Source": str(self.cfg)},
                {"Type": "volume", "Name": "smite-node-data", "Driver": "local",
                 "Destination": "/var/lib/smite-node", "Source": str(self.data)},
            ],
        }
        real = gate._local_file
        def runner_file(path, *, max_bytes, require_root=False):
            # CI fixtures have runner ownership; only skip UID gate here.
            return real(path, max_bytes=max_bytes, require_root=False)
        self._patch = patch.object(gate, "_local_file", side_effect=runner_file)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def report(self):
        return gate.audit(self.node, runtime=self.runtime, min_bytes=4096)

    def test_good_local_evidence_is_not_deployment_permission(self):
        status = self.report()
        self.assertEqual(status["NODE_ROLE"], "KH")
        self.assertEqual(status["LOCAL_CORE"], "MANAGED_STRICT")
        self.assertEqual(status["DOCKER_NODE"], "RUNNING_REVIEWED_IMAGE")
        self.assertEqual(status["PERSISTENT_DATA"], "LOCAL_NAMED_VOLUME_CONFIRMED")
        self.assertEqual(status["PERSISTED_TUNNELS"], "ZERO")
        self.assertEqual(status["DISK_SPACE"], "MINIMUM_AVAILABLE")
        self.assertEqual(status["HOST_PREFLIGHT"], "PASS_LOCAL_ONLY_INCOMPLETE")
        self.assertEqual(status["HOST_INSTALL_AUTHORIZED"], "NO")
        self.assertIn("UNVERIFIED", status["SNAPSHOT_AND_CONSOLE"])
        self.assertIn("UNVERIFIED", status["NGINX_443_AND_FIREWALL_EXPOSURE"])
        self.assertEqual(status["FRP_INSTALL_REQUIRED"], "NO")
        self.assertNotIn("DONT_PRINT", str(status))

    def test_existing_tunnels_block_recreation_even_when_engine_absent(self):
        (self.data / "tunnels.json").write_text(json.dumps({
            "live": {"core": "frp", "spec": {"mode": "client", "token": "DONT_PRINT"}}
        }))
        out = self.report()
        self.assertEqual(out["PERSISTED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(out["HOST_PREFLIGHT"], "HOLD_EXISTING_TUNNELS")
        self.assertEqual(out["HOST_INSTALL_AUTHORIZED"], "NO")
        self.assertNotIn("DONT_PRINT", str(out))

    def test_wrong_source_mount_and_docker_port_bindings_are_held(self):
        self.runtime["Mounts"][0]["Source"] = str(self.root / "wrong")
        self.assertEqual(self.report()["HOLD_REASON"], "WRONG_NODE_CONFIG_VOLUME")
        self.runtime["Mounts"][0]["Source"] = str(self.cfg)
        self.runtime["HostConfig"]["PortBindings"] = {"8888/tcp": [{"HostPort": "8888"}]}
        self.assertEqual(self.report()["HOLD_REASON"], "PUBLISHED_DOCKER_PORTS")

    def test_named_volume_mismatch_and_duplicate_mounts_fail_closed(self):
        data = self.runtime["Mounts"][1]
        data["Name"] = "unrelated-data-volume"
        self.assertEqual(self.report()["HOLD_REASON"], "WRONG_NODE_NAMED_VOLUME")
        data["Name"] = "smite-node-data"
        data["Type"] = "bind"
        self.assertEqual(self.report()["HOLD_REASON"], "WRONG_NODE_NAMED_VOLUME")
        data["Type"] = "volume"
        data["Driver"] = "local"
        self.runtime["Mounts"].append(dict(data))
        self.assertEqual(self.report()["HOLD_REASON"], "DUPLICATE_PERSISTENT_MOUNT")
        self.runtime["Mounts"].pop()

    def test_actual_compose_must_declare_named_volume(self):
        (self.node / "docker-compose.yml").write_text(
            COMPOSE.replace("      - node-data:/var/lib/smite-node\n", "")
        )
        self.assertEqual(self.report()["HOLD_REASON"], "UNTRUSTED_NODE_COMPOSE")

    def test_json_report_redacts_every_sensitive_source(self):
        with patch.object(gate, "read_only_docker_inspect", return_value=self.runtime):
            report = self.report()
        blob = json.dumps(report)
        self.assertNotIn("DONT_PRINT", blob)
        self.assertNotIn(str(self.data), blob)
        self.assertNotIn(str(self.cfg), blob)
        self.assertNotIn("TOKEN", blob)
        self.assertEqual(report["HOST_INSTALL_AUTHORIZED"], "NO")

    def test_not_running_unreviewed_image_and_bridge_mode_held(self):
        self.runtime["State"]["Running"] = False
        self.assertEqual(self.report()["HOLD_REASON"], "NODE_NOT_RUNNING")
        self.runtime["State"]["Running"] = True
        self.runtime["Config"]["Image"] = "unreviewed/node:latest"
        self.assertEqual(self.report()["HOLD_REASON"], "UNREVIEWED_NODE_IMAGE")
        self.runtime["Config"]["Image"] = "smite-node:stage15-local"
        self.runtime["HostConfig"]["NetworkMode"] = "bridge"
        self.assertEqual(self.report()["HOLD_REASON"], "UNEXPECTED_NODE_NETWORK")

    def test_duplicate_managed_env_and_unsafe_compose_fails_closed(self):
        (self.node / ".env").write_text(ENV + "SMITE_AGENT_AUTH_MODE=legacy\n")
        self.assertEqual(self.report()["HOLD_REASON"], "DUPLICATE_CORE_ENV")
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE + "    ports:\n      - 8888:8888\n")
        self.assertEqual(self.report()["HOLD_REASON"], "UNTRUSTED_NODE_COMPOSE")

    def test_invalid_saved_tunnels_symlink_and_low_disk_fails(self):
        saved = self.data / "tunnels.json"
        saved.write_text('{"a": {"spec": {"mode": "client"}}}')
        self.assertEqual(self.report()["HOLD_REASON"], "UNTRUSTED_TUNNEL_REGISTRY")
        saved.unlink()
        saved.symlink_to(self.node / ".env")
        self.assertEqual(self.report()["HOLD_REASON"], "LOCAL_SYMLINK")
        saved.unlink()
        self.assertEqual(
            gate.audit(self.node, runtime=self.runtime, min_bytes=10**15)["HOLD_REASON"],
            "INSUFFICIENT_FREE_DISK",
        )

    def test_node_env_and_docker_data_can_never_be_logged(self):
        cli = subprocess.run([sys.executable, "-B", str(SCRIPT), "--node-dir", str(self.node)],
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(cli.returncode, 2)  # Root ownership/real Docker gate.
        self.assertIn("HOST_INSTALL_AUTHORIZED=NO", cli.stdout)
        self.assertIn("BACKHAUL_ACTIVATION_GATE=HOLD", cli.stdout)
        self.assertNotIn("DONT_PRINT", cli.stdout + cli.stderr)

    def test_docker_inspect_command_is_the_only_allowed_read_only_probe(self):
        out = Mock(returncode=0, stdout=json.dumps([self.runtime]), stderr="DONT_PRINT")
        called = []
        def fake_run(args, **kwargs):
            called.append(args)
            return out
        found = gate.read_only_docker_inspect(runner=fake_run)
        self.assertEqual(found["Name"], "/smite-node")
        self.assertEqual(called, [["docker", "inspect", "--type=container", "smite-node"]])
        with self.assertRaises(gate.GateHold):
            gate.read_only_docker_inspect(name="smite-node;rm -rf /", runner=fake_run)
        self.assertEqual(len(called), 1)

    def test_no_service_mutations_in_gate(self):
        body = SCRIPT.read_text()
        for fragment in ("docker compose up", "docker restart", "systemctl restart",
                         "subprocess.Popen", "os.system(", "curl ", "iptables ",
                         "nginx -s", "ssh ", "sudo "):
            self.assertNotIn(fragment, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
