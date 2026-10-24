#!/usr/bin/env python3
"""Offline RC.2 signed FRP WSS Node opt-in, preserved overlays and rollback."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-rc2-frp-wss-node-activation.py"
SRC_PLAN = ROOT / "modules/smite-rc2-frp-wss-plan.py"
spec = importlib.util.spec_from_file_location("signed_wss_tx", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ps = importlib.util.spec_from_file_location("signed_wss_existing_plan", SRC_PLAN)
plan = importlib.util.module_from_spec(ps)
ps.loader.exec_module(plan)
ORIGINAL = {
    "SMITE_NODE_PANEL_AUTH_MODE": "signed",
    "SMITE_AGENT_AUTH_MODE": "strict",
    "SMITE_ENGINE_INVENTORY_MODE": "managed",
    "PANEL_ADDRESS": "ir.kolbe1.ir:443",
}
HOST = "ir"


class Helper:
    def __init__(self, parent):
        self.parent = parent
    def local_probe(self, expected):
        self.parent.probes.append("local:" + expected)
    def signed_probe(self, expected):
        self.parent.probes.append("signed:" + expected)


class NodeWssTrial(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="rc2-wss-signed-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.node = root / "node"
        self.node.mkdir(mode=0o700)
        self.config = self.node / "config"
        self.config.mkdir(mode=0o700)
        self.base = self.node / "docker-compose.yml"
        self.base.write_text("services:\n  smite-node:\n    image: pinned\n")
        self.signed = self.node / "docker-compose.security-candidate.yml"
        self.signed.write_text("services:\n  smite-node:\n    environment:\n      - SMITE_AGENT_AUTH_MODE=strict\n")
        self.signed.chmod(0o600)
        self.overlay = self.node / "docker-compose.frp-wss-rc2.yml"
        self.state_parent = root / "journal-base"
        self.state_parent.mkdir(mode=0o700)
        self.state = self.state_parent / "wss"
        self.idparent = root / "identity"
        self.idparent.mkdir(mode=0o700)
        self.identity = self.idparent / "node-identity.json"
        self.identity.write_bytes(b"fixture-identity")
        self.identity.chmod(0o600)
        self.replayparent = root / "replay"
        self.replayparent.mkdir(mode=0o700)
        self.replay = self.replayparent / "agent-replay.sqlite3"
        self.replay.write_bytes(b"fixture-replay")
        self.replay.chmod(0o600)
        self.manifest = self.config / "engine-state" / "engines.json"
        self.manifest.parent.mkdir(mode=0o700)
        self.manifest.write_text('{"schema":1,"engines":{"frp":{"sha256":"x"}}}')
        self.manifest.chmod(0o600)
        self.lockfile = root / "lock"
        self.probes = []
        self.events = []
        self.enabled = False
        self.recreation = 0
        self.break_on_enable = False
        self.fail_rollback = False
        fields = {
            "NODE": self.node, "BASE": self.base, "SIGNED": self.signed,
            "OVERLAY_PATH": self.overlay, "STATE_ROOT": self.state,
            "LOCK": self.lockfile, "IDENTITY": self.identity,
            "REPLAY": self.replay, "MANIFEST": self.manifest,
            "TUNNELS": self.config / "tunnels.json",
        }
        for name, val in fields.items():
            patcher = patch.object(module, name, val)
            patcher.start()
            self.addCleanup(patcher.stop)
        def fake_lock():
            return os.open(self.lockfile, os.O_RDWR | os.O_CREAT, 0o600)
        def load(name, filename):
            if filename == "smite-rc2-frp-wss-plan.py":
                return plan
            if filename == "smite-rc2-frp-bundled-enrollment.py":
                return Helper(self)
            raise AssertionError(filename)
        for name, value in (("lock", fake_lock), ("load", load),
                            ("inspect", self.runtime), ("run", self.run),
                            ("wait_health", self.wait_health),
                            ("signed_probe", self.signed_probe)):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def runtime(self):
        environment = dict(ORIGINAL)
        if self.enabled:
            environment["SMITE_FRP_STANDARD_WSS"] = "1"
        files = [str(self.base), str(self.signed)]
        if self.enabled:
            files.append(str(self.overlay))
        return {
            "Id": f"rc2-node-{self.recreation}",
            "Config": {
                "Image": module.IMAGES[HOST],
                "Env": [f"{k}={v}" for k, v in environment.items()],
                "Labels": {
                    "com.docker.compose.project.config_files": ",".join(files),
                },
            },
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "Mounts": [
                {"Destination": "/etc/smite-node",
                 "Source": str(self.config), "RW": True},
                {"Destination": "/run/smite-node-identity", "RW": False},
                {"Destination": "/var/lib/smite-node/auth", "RW": True},
            ]
        }

    def service(self, wss=False):
        env = dict(ORIGINAL)
        if wss:
            env["SMITE_FRP_STANDARD_WSS"] = "1"
        return {
            "image": module.IMAGES[HOST],
            "environment": env,
            "network_mode": "host",
            "command": ["uvicorn", "main:app", "--host", "127.0.0.1",
                        "--port", "8888"],
            "volumes": [
                {"target": "/etc/smite-node"},
                {"target": "/run/smite-node-identity"},
                {"target": "/var/lib/smite-node/auth"},
            ],
        }

    def run(self, argv, *, input_text=None, timeout=35):
        self.events.append(tuple(argv))
        if argv[0:2] == ["docker", "compose"] and "config" in argv:
            enabled = "-" in argv and input_text is not None
            return json.dumps({"services": {"smite-node": self.service(enabled)}})
        if argv[0:2] == ["docker", "compose"] and "up" in argv:
            self.recreation += 1
            flag = str(self.overlay) in argv
            if flag and self.break_on_enable:
                raise module.Hold("SIMULATED_NODE_RECREATE_FAILED")
            if not flag and self.fail_rollback:
                raise module.Hold("SIMULATED_ROLLBACK_FAILURE")
            self.enabled = flag
            return ""
        raise AssertionError("unexpected command " + str(argv))

    def wait_health(self, role, enabled):
        self.assertEqual(role, HOST)
        self.assertEqual(self.enabled, enabled)
        return self.runtime()

    def signed_probe(self, role, *, enabled):
        self.assertEqual(role, HOST)
        self.assertEqual(self.enabled, enabled)
        self.probes.append("signed:ready:" + str(enabled))

    def test_plan_only_evaluates_existing_signed_overlays(self):
        before = self.replay.read_bytes()
        current, proof = module.prerequisite(HOST, signed=False)
        self.assertEqual(current["Id"], "rc2-node-0")
        self.assertTrue(proof["manifest"])
        self.assertEqual(self.probes, ["local:ready"])
        self.assertEqual(self.replay.read_bytes(), before)
        self.assertFalse(self.overlay.exists())
        self.assertFalse(self.state.exists())

    def test_successful_signed_optin_and_exact_rollback(self):
        module.apply(HOST)
        self.assertTrue(self.enabled)
        self.assertEqual(self.recreation, 1)
        self.assertEqual(stat.S_IMODE(self.overlay.stat().st_mode), 0o600)
        self.assertEqual(module.journal(HOST)["state"], "COMMITTED")
        self.assertEqual(module.trusted(self.overlay), module.WSS_OVERLAY)
        self.assertEqual(self.probes[:2], ["signed:ready:False", "signed:ready:True"])
        self.assertEqual(module.verify(HOST), None)
        module.rollback(HOST)
        self.assertFalse(self.enabled)
        self.assertEqual(self.recreation, 2)
        self.assertFalse(self.overlay.exists())
        self.assertFalse(self.state.exists())
        self.assertFalse(self.signed.read_bytes().startswith(b"INVALID"))
        self.assertEqual(self.identity.read_bytes(), b"fixture-identity")
        self.assertEqual(self.replay.read_bytes(), b"fixture-replay")

    def test_apply_failure_restores_prior_signed_compose(self):
        self.break_on_enable = True
        with self.assertRaisesRegex(module.Hold, "WSS_NODE_ACTIVATION_ROLLED_BACK"):
            module.apply(HOST)
        self.assertFalse(self.enabled)
        self.assertFalse(self.overlay.exists())
        self.assertFalse(self.state.exists())
        self.assertEqual(self.probes[-1], "signed:ready:False")

    def test_crash_before_node_recreation_can_be_recovered_without_restart(self):
        current, proof = module.prerequisite(HOST)
        module.record(HOST, proof, current["Id"])
        module.new_file(self.overlay, module.WSS_OVERLAY)
        module.recover(HOST)
        self.assertEqual(self.recreation, 0)
        self.assertFalse(self.overlay.exists())
        self.assertFalse(self.state.exists())

    def test_interrupted_recreation_recovers_with_signed_overlay(self):
        current, proof = module.prerequisite(HOST)
        module.record(HOST, proof, current["Id"])
        module.new_file(self.overlay, module.WSS_OVERLAY)
        self.enabled = True
        self.recreation = 1
        module.recover(HOST)
        self.assertFalse(self.enabled)
        self.assertEqual(self.recreation, 2)
        self.assertFalse(self.overlay.exists())
        self.assertFalse(self.state.exists())

    def test_incomplete_journal_never_authorizes_retry(self):
        current, proof = module.prerequisite(HOST)
        module.record(HOST, proof, current["Id"])
        with self.assertRaisesRegex(module.Hold, "UNRESOLVED_WSS_NODE_TRANSACTION"):
            module.apply(HOST)
        self.assertEqual(self.recreation, 0)

    def test_identity_or_manifest_drift_blocks_destructive_rollback(self):
        module.apply(HOST)
        self.identity.write_bytes(b"tampered")
        with self.assertRaisesRegex(module.Hold, "PROTECTED_STATE_DRIFT"):
            module.rollback(HOST)
        self.assertTrue(self.overlay.exists())
        self.assertTrue(self.state.exists())

    def test_refuses_recreation_when_extra_compose_file_active(self):
        original = self.runtime
        def extra():
            doc = original()
            doc["Config"]["Labels"]["com.docker.compose.project.config_files"] += (
                ",/opt/smite-node/operator-custom.yml"
            )
            return doc
        with patch.object(module, "inspect", extra):
            with self.assertRaisesRegex(module.Hold, "UNREVIEWED_ACTIVE_COMPOSE_SET"):
                module.prerequisite(HOST)
        self.assertEqual(self.recreation, 0)

    def test_failed_rollback_retains_journal_and_signed_state(self):
        module.apply(HOST)
        self.fail_rollback = True
        with self.assertRaisesRegex(module.Hold, "SIMULATED_ROLLBACK_FAILURE"):
            module.rollback(HOST)
        self.assertTrue(self.overlay.is_file())
        self.assertTrue(self.state.is_dir())

    def test_no_nginx_firewall_panel_or_general_installer_commands(self):
        contents = SOURCE.read_text()
        for forbidden in ("nginx -s", "systemctl reload nginx", "iptables ",
                          "ufw ", "/api/agent/tunnels/apply",
                          "docker-compose.security-candidate.yml.unlink",
                          "docker compose -f /opt/smite-node/docker-compose.yml up"):
            self.assertNotIn(forbidden, contents)
        self.assertIn('SNAPSHOT = "SNAPSHOTS-AND-CONSOLES-VERIFIED"', contents)
        self.assertIn('SIGNED_POLICY_DRIFT', contents)


if __name__ == "__main__":
    unittest.main(verbosity=2)
