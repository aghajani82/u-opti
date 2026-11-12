"""Existing Foreign core/Sanaei/Gateway phase recovery, no host mutation.

The callbacks model the ALREADY INSTALLED and reviewed U-OPTI helpers.
This suite deliberately asserts that a journal never authorizes silent
recreation of a paused Node, re-installation of Sanaei or Gateway changes.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "uopti_foreign_host_recovery",
    ROOT / "modules/smite-unified-foreign-host-recovery.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class HostRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "foreign-fixture"
        self.stage = self.base / "foreign-staging"
        self.base.mkdir(mode=0o700)
        self.stage.mkdir(mode=0o700)
        self.packet = self.stage / "foreign-install-packet.json"
        self.now = 1850000000
        self.doc = {
            "protocol": "smi1",
            "panel_url": "https://panel.example.com:443",
            "node_id": "foreign-node-1234",
            "node_name": "node-kh",
            "origin": "https://kh.example.com:443",
            "control_url": "https://kh.example.com:443/smite-node/" + "a"*32,
            "installation_code": "smi1_" + "b"*43,
            "expires_at": self.now + 7200,
        }
        self.save_packet()
        self.states = {"core": True, "sanaei": "ABSENT", "gateway": "ABSENT"}
        self.events = []
        self.fail_sanaei = None
        self.fail_gateway = None

    def save_packet(self):
        self.packet.write_text(json.dumps(self.doc))
        self.packet.chmod(0o600)

    def journal_path(self):
        return self.stage / mod.JOURNAL

    def journal(self):
        return json.loads(self.journal_path().read_text())

    def verify_core(self, scope):
        self.events.append("verify_core")
        self.assertEqual(scope["node_name"], "node-kh")
        return self.states["core"]

    def verify_sanaei(self, scope):
        self.events.append("verify_sanaei")
        return self.states["sanaei"]

    def verify_gateway(self, scope):
        self.events.append("verify_gateway")
        self.assertEqual(scope["control_url"], self.doc["control_url"])
        return self.states["gateway"]

    def install_sanaei(self, scope):
        self.events.append("install_sanaei")
        self.states["sanaei"] = "READY"
        if self.fail_sanaei == "crash":
            raise KeyboardInterrupt("simulate process interrupted after install")
        if self.fail_sanaei == "error":
            self.states["sanaei"] = "ABSENT"
            raise OSError("simulate incomplete Sanaei operation")

    def install_gateway(self, scope):
        self.events.append("install_gateway")
        self.states["gateway"] = "READY"
        if self.fail_gateway == "crash":
            raise KeyboardInterrupt("simulate process interrupted after Nginx applied")
        if self.fail_gateway == "error":
            self.states["gateway"] = "ABSENT"
            raise OSError("simulate incomplete Gateway operation")

    def tx(self, **changes):
        kwargs = dict(
            directory=self.stage, packet_path=self.packet, now=self.now,
            expected_panel="https://panel.example.com:443",
            expected_foreign="https://kh.example.com:443",
            expected_node="node-kh",
            verify_core=self.verify_core, verify_sanaei=self.verify_sanaei,
            verify_gateway=self.verify_gateway,
            install_sanaei=self.install_sanaei,
            install_gateway=self.install_gateway,
            disposable_capability=True)
        kwargs.update(changes)
        return mod.rehearse(**kwargs)

    def assert_no_install(self):
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)

    def test_full_sequence_and_nonsecret_journal(self):
        result = self.tx()
        self.assertEqual(result["phase"], "GATEWAY_443_VERIFIED")
        self.assertEqual(result["sanaei"], "READ_ONLY_VERIFIED")
        self.assertFalse(result["identity_promoted"])
        self.assertFalse(result["connected"])
        self.assertEqual(result["runtime_activation"], "NOT_PERFORMED")
        self.assertEqual(self.events.count("install_sanaei"), 1)
        self.assertEqual(self.events.count("install_gateway"), 1)
        self.assertLess(self.events.index("install_sanaei"),
                        self.events.index("install_gateway"))
        record = self.journal()
        self.assertEqual(record["phase"], "GATEWAY_443_VERIFIED")
        self.assertEqual(record["packet_sha256"],
                         hashlib.sha256(self.packet.read_bytes()).hexdigest())
        self.assertEqual(record["scope"]["node_id"], self.doc["node_id"])
        raw = self.journal_path().read_text()
        self.assertNotIn("installation_code", raw)
        self.assertNotIn("node_secret", raw)
        self.assertNotIn(self.doc["installation_code"], raw)
        self.assertEqual(self.journal_path().stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.stage/mod.LOCK).stat().st_mode & 0o777, 0o600)

    def test_resume_completed_independently_rechecks_no_writes(self):
        self.tx()
        self.events.clear()
        self.assertEqual(self.tx()["phase"], "GATEWAY_443_VERIFIED")
        self.assert_no_install()
        self.assertGreaterEqual(self.events.count("verify_core"), 3)
        self.assertGreaterEqual(self.events.count("verify_gateway"), 3)

    def test_initial_existing_exact_inventory_is_not_reinstalled(self):
        self.states["sanaei"] = "READY"
        self.states["gateway"] = "READY"
        self.assertEqual(self.tx()["phase"], "GATEWAY_443_VERIFIED")
        self.assert_no_install()

    def test_crash_after_sanaei_is_resumed_only_when_inventory_ready(self):
        self.fail_sanaei = "crash"
        with self.assertRaises(KeyboardInterrupt): self.tx()
        self.assertEqual(self.journal()["phase"], "SANAEI_INTENT")
        self.assertEqual(self.states["sanaei"], "READY")
        self.fail_sanaei = None
        self.events.clear()
        self.assertEqual(self.tx()["phase"], "GATEWAY_443_VERIFIED")
        self.assertEqual(self.events.count("install_sanaei"), 0)
        self.assertEqual(self.events.count("install_gateway"), 1)

    def test_crash_after_gateway_is_resumed_without_node_recreation(self):
        self.fail_gateway = "crash"
        with self.assertRaises(KeyboardInterrupt): self.tx()
        self.assertEqual(self.journal()["phase"], "GATEWAY_INTENT")
        self.assertEqual(self.states["gateway"], "READY")
        self.fail_gateway = None
        self.events.clear()
        self.assertEqual(self.tx()["phase"], "GATEWAY_443_VERIFIED")
        self.assert_no_install()

    def test_ambiguous_partial_sanaei_never_blindly_reruns(self):
        self.fail_sanaei = "error"
        with self.assertRaises(mod.Hold): self.tx()
        self.assertEqual(self.journal()["phase"], "SANAEI_INTENT")
        self.fail_sanaei = None
        self.events.clear()
        with self.assertRaises(mod.Hold): self.tx()
        self.assert_no_install()
        self.assertEqual(self.journal()["phase"], "SANAEI_INTENT")

    def test_ambiguous_partial_gateway_never_blindly_reloads(self):
        self.fail_gateway = "error"
        with self.assertRaises(mod.Hold): self.tx()
        self.assertEqual(self.journal()["phase"], "GATEWAY_INTENT")
        self.fail_gateway = None
        self.events.clear()
        with self.assertRaises(mod.Hold): self.tx()
        self.assert_no_install()
        self.assertEqual(self.journal()["phase"], "GATEWAY_INTENT")

    def test_drift_after_complete_never_trusts_stale_journal(self):
        self.tx()
        for component in ("core", "sanaei", "gateway"):
            self.events.clear()
            before = self.states[component]
            self.states[component] = False if component == "core" else "DRIFT"
            with self.subTest(component=component), self.assertRaises(mod.Hold):
                self.tx()
            self.assert_no_install()
            self.assertEqual(self.journal()["phase"], "GATEWAY_443_VERIFIED")
            self.states[component] = before

    def test_missing_completed_gateway_never_auto_recreated(self):
        self.tx()
        self.states["gateway"] = "ABSENT"
        self.events.clear()
        with self.assertRaises(mod.Hold): self.tx()
        self.assert_no_install()

    def test_unknown_or_conflicting_preflight_blocks_before_writes(self):
        for component, value in (("core",False),
                                 ("sanaei","DRIFT"),
                                 ("gateway","DRIFT")):
            previous = self.states[component]
            self.states[component] = value
            self.events.clear()
            with self.subTest(component=component), self.assertRaises(mod.Hold):
                self.tx()
            self.assert_no_install()
            self.assertFalse(self.journal_path().exists())
            self.states[component] = previous

    def test_gateway_ready_without_sanaei_is_inconsistent(self):
        self.states["gateway"] = "READY"
        with self.assertRaises(mod.Hold): self.tx()
        self.assert_no_install()
        self.assertFalse(self.journal_path().exists())

    def test_exact_packet_swap_does_not_reuse_prior_phase(self):
        self.tx()
        self.doc["installation_code"] = "smi1_" + "c"*43
        self.save_packet()
        self.events.clear()
        with self.assertRaises(mod.Hold): self.tx()
        self.assert_no_install()

    def test_corrupt_journal_refuses_external_stage_ops(self):
        self.tx()
        self.journal_path().write_text("{}")
        self.journal_path().chmod(0o600)
        self.events.clear()
        with self.assertRaises(mod.Hold): self.tx()
        self.assert_no_install()

    def test_hardlink_or_symlink_journal_refused(self):
        self.tx()
        old = self.journal_path().read_bytes()
        self.journal_path().unlink()
        linked = self.base / "original-journal"
        linked.write_bytes(old)
        linked.chmod(0o600)
        os.link(linked, self.journal_path())
        with self.assertRaises(mod.Hold): self.tx()
        self.journal_path().unlink()
        self.journal_path().symlink_to(linked)
        with self.assertRaises(mod.Hold): self.tx()
        self.assertEqual(linked.read_bytes(), old)

    def test_held_operation_lock_does_not_start_any_mutation(self):
        lock = self.stage / mod.LOCK
        with open(lock, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(mod.Hold): self.tx()
            self.assert_no_install()
            self.assertFalse(self.journal_path().exists())
        self.assertEqual(self.tx()["phase"], "GATEWAY_443_VERIFIED")

    def test_expired_code_wrong_domain_node_or_scope_cannot_start(self):
        for changes in ({"now":self.doc["expires_at"]+1},
                        {"expected_panel":"https://evil.example.com"},
                        {"expected_foreign":"https://wrong.example.com"},
                        {"expected_node":"other-node"}):
            self.events.clear()
            with self.subTest(changes=changes), self.assertRaises(mod.Hold):
                self.tx(**changes)
            self.assert_no_install()
            self.assertFalse(self.journal_path().exists())

    def test_untrusted_fixture_and_missing_capability_refuse_operation(self):
        with self.assertRaises(mod.Hold):
            self.tx(disposable_capability=False)
        with self.assertRaises(mod.Hold):
            self.tx(directory=Path("/etc/u-opti/smite/foreign-staging"))
        self.base.chmod(0o755)
        try:
            with self.assertRaises(mod.Hold): self.tx()
        finally:
            self.base.chmod(0o700)
        self.assertFalse(self.journal_path().exists())

    def test_status_only_cli_never_exposes_live_stage_execution(self):
        script = ROOT/"modules/smite-unified-foreign-host-recovery.py"
        ok = subprocess.run([sys.executable, "-B", str(script), "--status"],
                            capture_output=True, text=True, check=True)
        self.assertIn("HOST_STAGE_EXECUTION=NOT_AUTHORIZED", ok.stdout)
        self.assertIn("FOREIGN_CONNECTED=NOT_PROVEN", ok.stdout)
        bad = subprocess.run([sys.executable, "-B", str(script), "--install"],
                             capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
