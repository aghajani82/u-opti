"""Isolated KH Stage15 Inventory transaction: real private receipt, fake Docker.

No live Docker, Sanaei, FRP, Panel, filesystem outside TemporaryDirectory.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kh_inventory_test",
    ROOT / "modules/smite-stage15-kh-inventory.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

class PowerLoss(BaseException):
    pass

def fake_signature():
    return {
        "image": m.EXPECTED_IMAGE,
        "env": {"SMITE_SANAEI_INVENTORY_ENABLED": "false",
                "SMITE_SANAEI_DB_PATH": "/run/smite-sanaei-ro/x-ui.db",
                "SMITE_AGENT_AUTH_MODE": "strict",
                "SMITE_NODE_PANEL_AUTH_MODE": "signed"},
        "mounts": [
            {"Destination": "/run/smite-sanaei-ro",
             "Source": "/opt/smite-node/.sanaei-empty",
             "RW": False, "Type": "bind", "Mode": "ro", "Propagation": "rprivate"},
            {"Destination": "/var/lib/smite-node/auth",
             "Source": "/var/lib/u-opti/smite-node-security/replay",
             "RW": True, "Type": "bind"},
        ],
        "command": ["uvicorn", "main:app", "--host", "127.0.0.1",
                    "--port", "8888"],
        "host": {
            "Binds": [
                "/opt/smite-node/.sanaei-empty:/run/smite-sanaei-ro:ro",
                "/var/lib/u-opti/smite-node-security/replay:/var/lib/smite-node/auth:rw",
            ],
            "NetworkMode": "host", "Privileged": False, "PortBindings": {},
        },
    }

@unittest.skipUnless(os.geteuid() == 0, "root-owned receipt fixture")
class KHInventoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.root.chmod(0o700)
        self.state = self.root / "inventory"
        self.overlay = self.root / "docker-compose.sanaei-inventory.yml"
        self.wss = self.root / "wss"
        self.wss.mkdir(mode=0o700)
        (self.wss / "record.json").write_text("original immutable WSS record")
        (self.wss / "record.json").chmod(0o600)
        self.before = fake_signature()
        self.after = m.expected_signature(self.before)
        self.mode = "before"
        self.operations = []
        self.power = False
        self.wdoc = {"roles": ["node"], "state": "COMMITTED",
                     "runtime": {"node": copy.deepcopy(self.before)}}
        self.patches = [
            patch.object(m.os, "uname", return_value=type("KHHost", (), {"nodename": "kh"})()),
            patch.object(m, "STATE", self.state),
            patch.object(m, "OVERLAY", self.overlay),
            patch.object(m.w, "STATE", self.wss),
            patch.object(m.w, "read_record", side_effect=lambda: self.wdoc),
            patch.object(m.w, "protected", return_value={"identity": "signed",
                                                       "replay_inode": "99"}),
            patch.object(m, "database", return_value=[15, 16, 17]),
            patch.object(m, "frpc", return_value="single-original-frpc"),
            patch.object(m, "validate_compose"),
            patch.object(m.w, "runtime"),
            patch.object(m.w, "health"),
            patch.object(m.w, "inspect", side_effect=self.inspect),
            patch.object(m.w, "signature", side_effect=lambda _: copy.deepcopy(
                self.after if self.mode == "after" else self.before)),
            patch.object(m, "signed_inbounds", side_effect=lambda: self.operations.append("signed-get-replay")),
            patch.object(m, "recreate", side_effect=self.recreate),
            patch.object(m.h, "run", return_value=m.EXPECTED_IMAGE),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def inspect(self, role):
        self.assertEqual(role, "node")
        return {"Image": m.EXPECTED_IMAGE,
                "State": {"Health": {"Status": "healthy"}}}

    def recreate(self, enabled):
        self.operations.append("node-only-recreate:" + str(enabled))
        if self.power:
            self.power = False
            raise PowerLoss("kill at Docker cutover")
        self.mode = "after" if enabled else "before"

    def test_success_then_verify_and_rollback_without_owner_reapply(self):
        m.apply()
        self.assertEqual(m.record()["phase"], "COMMITTED")
        self.assertEqual(self.overlay.read_bytes(), m.OVERLAY_BYTES)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        m.verify()
        self.assertIn("signed-get-replay", self.operations)
        m.rollback()
        self.assertEqual(m.record()["phase"], "ROLLED_BACK")
        self.assertEqual(self.mode, "before")
        self.assertEqual(self.operations.count("node-only-recreate:True"), 1)
        self.assertEqual(self.operations.count("node-only-recreate:False"), 1)
        self.assertEqual((self.wss / "record.json").read_text(),
                         "original immutable WSS record")

    def test_power_loss_during_cutover_is_fail_closed_and_recoverable(self):
        self.power = True
        with self.assertRaises(PowerLoss):
            m.apply()
        self.assertEqual(m.record()["phase"], "RECREATING")
        with self.assertRaises(m.Hold):
            m.expectation(self.wdoc, m.EXPECTED_IMAGE)
        m.rollback()
        self.assertEqual(m.record()["phase"], "ROLLED_BACK")
        self.assertEqual(self.mode, "before")

    def test_external_overlay_mutation_denies_recovery(self):
        m.apply()
        self.overlay.write_text("services: {}\n")
        with self.assertRaises(m.Hold):
            m.rollback()
        self.assertEqual(self.mode, "after")
        self.assertEqual(self.operations.count("node-only-recreate:False"), 0)

    def test_signed_identity_or_wss_drift_denies_recovery(self):
        m.apply()
        self.wdoc["runtime"]["node"]["image"] = "sha256:bad"
        with self.assertRaises(m.Hold):
            m.rollback()
        self.assertEqual(self.mode, "after")

    def test_computed_runtime_allows_only_existing_read_only_mount_delta(self):
        self.assertEqual(self.after["image"], self.before["image"])
        self.assertEqual(self.after["env"]["SMITE_SANAEI_INVENTORY_ENABLED"], "true")
        self.assertEqual(self.after["mounts"][0]["RW"], False)
        self.assertEqual(self.after["mounts"][0]["Source"], str(m.DB_DIR))
        self.assertEqual(self.after["mounts"][1], self.before["mounts"][1])
        self.assertEqual(self.after["host"]["NetworkMode"], "host")
        changed = copy.deepcopy(self.before)
        changed["mounts"][0]["RW"] = True
        with self.assertRaises(m.Hold):
            m.expected_signature(changed)
        changed = copy.deepcopy(self.before)
        changed["env"]["SMITE_SANAEI_INVENTORY_ENABLED"] = "true"
        with self.assertRaises(m.Hold):
            m.expected_signature(changed)

    def test_no_image_swap_in_root_runbook(self):
        source = (ROOT / "modules/smite-stage15-kh-inventory.py").read_text()
        self.assertIn("--force-recreate", source)
        self.assertIn("--pull", source)
        self.assertIn('"never"', source)
        self.assertNotIn("image load", source.split("def recreate(")[1].split("def apply(")[0].lower())

if __name__ == "__main__":
    unittest.main()
