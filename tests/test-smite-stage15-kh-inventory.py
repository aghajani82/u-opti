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
REAL_VALIDATE_COMPOSE = m.validate_compose
REAL_WAIT_HEALTHY = m.wait_healthy

class PowerLoss(BaseException):
    pass

def fake_signature(*, mounted=False):
    mounts = [
        {"Destination": "/var/lib/smite-node/auth",
         "Source": "/var/lib/u-opti/smite-node-security/replay",
         "RW": True, "Type": "bind"},
    ]
    binds = ["/var/lib/u-opti/smite-node-security/replay:/var/lib/smite-node/auth:rw"]
    if mounted:
        mounts.append({
            "Destination": "/run/smite-sanaei-ro",
            "Source": "/opt/smite-node/.sanaei-empty",
            "RW": False, "Type": "bind", "Mode": "ro",
            "Propagation": "rprivate",
        })
        binds.append("/opt/smite-node/.sanaei-empty:/run/smite-sanaei-ro:ro")
    return {
        "image": m.EXPECTED_IMAGE,
        "env": {"SMITE_SANAEI_INVENTORY_ENABLED": "false",
                "SMITE_AGENT_AUTH_MODE": "strict",
                "SMITE_NODE_PANEL_AUTH_MODE": "signed"},
        "mounts": sorted(mounts, key=lambda x: x["Destination"]),
        "command": ["uvicorn", "main:app", "--host", "127.0.0.1",
                    "--port", "8888"],
        "host": {
            "Binds": sorted(binds),
            "Mounts": None,
            "NetworkMode": "host", "Privileged": False, "PortBindings": {},
        },
    }


def simulated_after(before, *, long_mount=False):
    result = copy.deepcopy(before)
    result["env"]["SMITE_SANAEI_INVENTORY_ENABLED"] = "true"
    result["env"]["SMITE_SANAEI_DB_PATH"] = "/run/smite-sanaei-ro/x-ui.db"
    target = "/run/smite-sanaei-ro"
    items = [v for v in result["mounts"] if v["Destination"] == target]
    if items:
        items[0]["Source"] = str(m.DB_DIR)
        old = "/opt/smite-node/.sanaei-empty:" + target + ":ro"
        result["host"]["Binds"].remove(old)
    else:
        result["mounts"].append({
            "Destination": target, "Source": str(m.DB_DIR),
            "Type": "bind", "RW": False, "Mode": "ro",
            "Propagation": "rprivate",
        })
    new = str(m.DB_DIR) + ":" + target + ":ro"
    if long_mount:
        result["host"]["Mounts"] = [{
            "Target": target, "Source": str(m.DB_DIR), "Type": "bind",
            "ReadOnly": True, "BindOptions": {"CreateMountpoint": False},
        }]
    else:
        result["host"]["Binds"].append(new)
        result["host"]["Binds"].sort()
    result["mounts"] = sorted(result["mounts"], key=lambda x: x["Destination"])
    return result


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
        self.after = simulated_after(self.before)
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
            patch.object(m, "wait_healthy"),
            patch.object(m.w, "runtime"),
            patch.object(m.w, "health"),
            patch.object(m.h, "signed_inventory", side_effect=lambda status: self.operations.append("signed-registry:" + status)),
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

    def test_atomic_overlay_partial_after_kill_recovers_without_recreate(self):
        doc = m.plan()
        m.begin(doc)
        partial = self.overlay.with_name(self.overlay.name + ".next")
        partial.write_bytes(m.OVERLAY_BYTES[:34])
        partial.chmod(0o600)
        m.rollback()
        self.assertEqual(m.record()["phase"], "ROLLED_BACK")
        self.assertFalse(partial.exists())
        self.assertNotIn("node-only-recreate:True", self.operations)
        self.assertNotIn("node-only-recreate:False", self.operations)

    def test_truncated_or_unknown_overlay_denies_recovery(self):
        doc = m.plan()
        m.begin(doc)
        partial = self.overlay.with_name(self.overlay.name + ".next")
        partial.write_bytes(b"unexpected attacker content")
        partial.chmod(0o600)
        with self.assertRaises(m.Hold):
            m.rollback()
        self.assertTrue(partial.exists())
        self.assertEqual(self.mode, "before")

    def test_cutover_crash_after_node_restart_can_rollback(self):
        with patch.object(m, "signed_inbounds", side_effect=PowerLoss("after up")):
            with self.assertRaises(PowerLoss):
                m.apply()
        self.assertEqual(m.record()["phase"], "RECREATING")
        self.assertEqual(self.mode, "after")
        m.rollback()
        self.assertEqual(m.record()["phase"], "ROLLED_BACK")
        self.assertEqual(self.mode, "before")
        self.assertEqual(self.operations.count("node-only-recreate:True"), 1)
        self.assertEqual(self.operations.count("node-only-recreate:False"), 1)

    def test_only_reviewed_env_and_bind_delta_admitted_for_absent_or_dummy_mount(self):
        self.assertIs(m.admit_after(self.before, self.after), self.after)
        for mounted in (False, True):
            for long_mount in (False, True):
                with self.subTest(mounted=mounted, long_mount=long_mount):
                    before = fake_signature(mounted=mounted)
                    after = simulated_after(before, long_mount=long_mount)
                    self.assertEqual(m.admit_after(before, after), after)
                    tampered = copy.deepcopy(after)
                    tampered["host"]["NetworkMode"] = "bridge"
                    with self.assertRaises(m.Hold):
                        m.admit_after(before, tampered)
                    tampered = copy.deepcopy(after)
                    next(item for item in tampered["mounts"] if item["Destination"] == "/run/smite-sanaei-ro")["RW"] = True
                    with self.assertRaises(m.Hold):
                        m.admit_after(before, tampered)
                    tampered = copy.deepcopy(after)
                    tampered["env"]["SMITE_AGENT_AUTH_MODE"] = "legacy"
                    with self.assertRaises(m.Hold):
                        m.admit_after(before, tampered)
                    tampered = copy.deepcopy(before)
                    tampered["env"]["SMITE_SANAEI_INVENTORY_ENABLED"] = "true"
                    with self.assertRaises(m.Hold):
                        m.baseline(tampered)



    def test_effective_compose_unchanged_except_inventory_in_old_mount_or_absent(self):
        for mounted in (False, True):
            with self.subTest(mounted=mounted):
                base_mounts = [{"type": "bind", "source": "/tmp/replay", "target": "/auth",
                                "read_only": False}]
                if mounted:
                    base_mounts += [{"type": "bind",
                                     "source": "/opt/smite-node/.sanaei-empty",
                                     "target": m.TARGET, "read_only": True,
                                     "bind": {"create_host_path": True}}]
                before = {"services": {"smite-node": {
                    "image": "smite-node:stage15-local",
                    "environment": {"SMITE_SANAEI_INVENTORY_ENABLED": "false"},
                    "volumes": base_mounts,
                    "network_mode": "host",
                }}, "networks": {}}
                after = copy.deepcopy(before)
                after["services"]["smite-node"]["environment"] = {
                    "SMITE_SANAEI_INVENTORY_ENABLED": "true",
                    "SMITE_SANAEI_DB_PATH": m.TARGET + "/x-ui.db",
                }
                new_mount = {"type": "bind", "source": str(m.DB_DIR),
                             "target": m.TARGET, "read_only": True,
                             "bind": {"create_host_path": False}}
                if mounted:
                    after["services"]["smite-node"]["volumes"][-1] = new_mount
                else:
                    after["services"]["smite-node"]["volumes"].append(new_mount)
                with patch.object(m.h, "run", side_effect=[
                        json.dumps(before), json.dumps(after)]):
                    REAL_VALIDATE_COMPOSE()
                unsafe = copy.deepcopy(after)
                unsafe["services"]["smite-node"]["volumes"][-1]["read_only"] = False
                with patch.object(m.h, "run", side_effect=[
                        json.dumps(before), json.dumps(unsafe)]):
                    with self.assertRaises(m.Hold):
                        REAL_VALIDATE_COMPOSE()
                rogue = copy.deepcopy(after)
                rogue["services"]["smite-node"]["environment"]["SMITE_AGENT_AUTH_MODE"] = "legacy"
                with patch.object(m.h, "run", side_effect=[
                        json.dumps(before), json.dumps(rogue)]):
                    with self.assertRaises(m.Hold):
                        REAL_VALIDATE_COMPOSE()

    def test_recover_from_post_recreate_health_race_without_recreate(self):
        # Docker Compose up -d completed; first immediate health admission
        # failed before the Node reported healthy. A later fresh authenticated
        # review is valid, but the journal MUST NOT be hand-edited.
        with patch.object(m, "verify_runtime",
                          side_effect=m.Hold("SERVICE_NOT_HEALTHY")):
            with self.assertRaises(m.Hold):
                m.apply()
        self.assertEqual(self.mode, "after")
        self.assertEqual(m.record()["phase"], "RECREATING")
        self.assertIsNone(m.record()["after"])
        before = list(self.operations)
        m.finalize()
        self.assertEqual(m.record()["phase"], "COMMITTED")
        self.assertIsNotNone(m.record()["after"])
        self.assertEqual(
            sum(x.startswith("node-only-recreate:") for x in self.operations),
            1,
        )
        self.assertEqual(
            sum(x.startswith("node-only-recreate:") for x in before),
            1,
        )
        self.assertIn("signed-get-replay", self.operations)
        self.assertIn("signed-registry:ready", self.operations)
        m.verify()

    def test_finalization_not_allowed_before_recreation(self):
        doc = m.plan()
        m.begin(doc)
        m.publish_overlay()
        doc["phase"] = "RECREATING"
        m.save(doc)
        # The container is still on the original disabled inventory.
        with self.assertRaises(m.Hold):
            m.finalize()
        self.assertEqual(m.record()["phase"], "RECREATING")
        self.assertIsNone(m.record()["after"])
        self.assertNotIn("signed-registry:ready", self.operations)

    def test_finalization_requires_fresh_signed_inventory_proof(self):
        doc = m.plan()
        m.begin(doc)
        m.publish_overlay()
        doc["phase"] = "RECREATING"
        m.save(doc)
        self.mode = "after"
        with patch.object(m, "signed_inbounds",
                          side_effect=m.Hold("SIGNED_KH_INVENTORY_UNAVAILABLE")):
            with self.assertRaises(m.Hold):
                m.finalize()
        self.assertEqual(m.record()["phase"], "RECREATING")
        self.assertIsNone(m.record()["after"])
        self.assertNotIn("signed-registry:ready", self.operations)

    def test_finalization_refuses_security_drift_and_pending_write(self):
        doc = m.plan()
        m.begin(doc)
        m.publish_overlay()
        doc["phase"] = "RECREATING"
        m.save(doc)
        self.mode = "after"
        with patch.object(m, "frpc", return_value="DIFFERENT"):
            with self.assertRaises(m.Hold):
                m.finalize()
        with patch.object(m.w, "protected", return_value={"identity": "changed"}):
            with self.assertRaises(m.Hold):
                m.finalize()
        pending = self.state / "record.json.next"
        pending.write_bytes(b"unreviewed")
        with self.assertRaises(m.Hold):
            m.finalize()
        self.assertEqual(m.record()["phase"], "RECREATING")
        self.assertIsNone(m.record()["after"])

    def test_waits_for_healthy_without_recreating_or_weakening_admission(self):
        starting = {"State": {"Running": True, "Health": {"Status": "starting"}}}
        healthy = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
        with patch.object(m.w, "inspect", side_effect=[starting, healthy]), \
             patch.object(m.time, "sleep") as sleeping:
            REAL_WAIT_HEALTHY()
        sleeping.assert_called_once_with(3)
        self.assertEqual(self.operations, [])

    def test_finalize_committed_receipt_is_read_only_and_idempotent(self):
        m.apply()
        previous = list(self.operations)
        m.finalize()
        self.assertEqual(m.record()["phase"], "COMMITTED")
        self.assertEqual(
            [x for x in self.operations if x.startswith("node-only-recreate:")],
            [x for x in previous if x.startswith("node-only-recreate:")],
        )

    def test_no_image_swap_in_root_runbook(self):
        source = (ROOT / "modules/smite-stage15-kh-inventory.py").read_text()
        self.assertIn("--force-recreate", source)
        self.assertIn("--pull", source)
        self.assertIn('"never"', source)
        self.assertNotIn("image load", source.split("def recreate(")[1].split("def apply(")[0].lower())

if __name__ == "__main__":
    unittest.main()
