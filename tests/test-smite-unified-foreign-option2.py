"""End-to-end Foreign option-2 offline integration of EXISTING stage journals.

The only exercised actions are disposable test callbacks and the original
signed grant/identity promotion against an injected fake Panel. Never
starts a Node, touches a server, or claims Connected.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


host = load("option2_host_recovery",
            ROOT / "modules" / "smite-unified-foreign-host-recovery.py")
fixtures = load("option2_identity_fixture",
                ROOT / "tests" / "test-smite-unified-foreign-identity-phase.py")


class UnifiedForeignOption2(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IdentityPhase(
            methodName="test_real_client_promotion_and_no_duplicate_redemption")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tmp.cleanup)
        self.states = {"core": True, "sanaei": "ABSENT", "gateway": "ABSENT"}
        self.events = []
        self.fail_after = None
        self.fail_before = None

    def verify_core(self, scope):
        self.events.append("verify_core")
        self.assertEqual(scope["node_id"], self.fixture.doc["node_id"])
        return self.states["core"]

    def verify_sanaei(self, scope):
        self.events.append("verify_sanaei")
        return self.states["sanaei"]

    def verify_gateway(self, scope):
        self.events.append("verify_gateway")
        return self.states["gateway"]

    def install_sanaei(self, scope):
        self.events.append("install_sanaei")
        if self.fail_before == "sanaei":
            self.fail_before = None
            raise OSError("failure before Sanaei could be committed")
        self.states["sanaei"] = "READY"
        if self.fail_after == "sanaei":
            self.fail_after = None
            raise KeyboardInterrupt("power loss after Sanaei mount")

    def install_gateway(self, scope):
        self.events.append("install_gateway")
        if self.fail_before == "gateway":
            self.fail_before = None
            raise OSError("failure before Gateway could be committed")
        self.states["gateway"] = "READY"
        if self.fail_after == "gateway":
            self.fail_after = None
            raise KeyboardInterrupt("power loss after Gateway TLS/443")

    def rollback_sanaei(self, scope):
        self.events.append("rollback_sanaei")
        self.assertEqual(self.states["gateway"], "ABSENT")
        self.states["sanaei"] = "ABSENT"
        return "ROLLED_BACK_VERIFIED"

    def rollback_gateway(self, scope):
        self.events.append("rollback_gateway")
        self.assertEqual(self.states["sanaei"], "READY")
        self.states["gateway"] = "ABSENT"
        return "ROLLED_BACK_VERIFIED"

    def run_option2(self, **kwargs):
        p = self.fixture
        data = dict(
            directory=p.stage, packet_path=p.packet,
            state_path=p.state, gateway_path=p.gateway,
            node_env_path=p.env, live_identity=p.live,
            now=p.now, expected_panel=p.doc["panel_url"],
            expected_foreign=p.doc["origin"],
            expected_node=p.doc["node_name"],
            verify_core=self.verify_core, verify_sanaei=self.verify_sanaei,
            verify_gateway=self.verify_gateway,
            install_sanaei=self.install_sanaei,
            install_gateway=self.install_gateway,
            rollback_sanaei=self.rollback_sanaei,
            rollback_gateway=self.rollback_gateway,
            transport=p.mock_panel, disposable_capability=True,
        )
        data.update(kwargs)
        return host.rehearse_option2(**data)

    def assert_no_identity(self):
        self.assertFalse(self.fixture.live.exists())
        self.assertEqual(self.fixture.calls, [])
        self.assertFalse(
            (self.fixture.stage / "foreign-install-identity.json").exists())

    def test_full_sequence_sanaei_gateway_then_signed_redeem_no_activation(self):
        result = self.run_option2()
        self.assertEqual(result, {
            "phase": "FOREIGN_OPTION2_OFFLINE_READY",
            "host_journal": "GATEWAY_443_VERIFIED",
            "identity_journal": "IDENTITY_PROMOTED_OFFLINE",
            "node_id": "foreign-node-1234",
            "sanaei": "READ_ONLY_VERIFIED",
            "gateway": "EXACT_HTTPS_443_VERIFIED",
            "signed_panel_proof": "PASS",
            "runtime_activation": "NOT_PERFORMED",
            "activation_allowed": False,
            "connected": False,
        })
        self.assertEqual(self.events.count("install_sanaei"), 1)
        self.assertEqual(self.events.count("install_gateway"), 1)
        self.assertLess(self.events.index("install_sanaei"),
                        self.events.index("install_gateway"))
        self.assertEqual(self.fixture.calls, [
            "/api/foreign-install/redeem",
            "/api/node-control/installation-status",
            "/api/node-control/installation-status",
        ])
        before = self.fixture.live.read_bytes()
        self.fixture.calls.clear()
        self.events.clear()
        self.assertEqual(self.run_option2(), result)
        self.assertEqual(self.fixture.calls,
                         ["/api/node-control/installation-status"])
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)
        self.assertEqual(before, self.fixture.live.read_bytes())
        for receipt in (
            self.fixture.stage / host.JOURNAL,
            self.fixture.stage / "unified-foreign-transaction.json",
        ):
            raw = receipt.read_text()
            self.assertNotIn(self.fixture.doc["installation_code"], raw)
            self.assertNotIn("node_secret", raw)
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)

    def test_gateway_must_be_verified_before_any_code_redeem(self):
        self.fail_after = "gateway"
        with self.assertRaises(KeyboardInterrupt):
            self.run_option2()
        self.assert_no_identity()
        self.assertEqual(self.states["sanaei"], "READY")
        self.assertEqual(self.states["gateway"], "READY")
        self.assertEqual(
            json.loads((self.fixture.stage / host.JOURNAL).read_text())["phase"],
            "GATEWAY_INTENT")
        # Independently witnessed READY; retry commits with NO reinstallation.
        self.events.clear()
        self.run_option2()
        self.assertNotIn("install_gateway", self.events)
        self.assertNotIn("install_sanaei", self.events)
        self.assertTrue(self.fixture.live.exists())

    def test_interrupted_sanaei_witness_ready_is_not_reinstalled(self):
        self.fail_after = "sanaei"
        with self.assertRaises(KeyboardInterrupt):
            self.run_option2()
        self.assert_no_identity()
        self.events.clear()
        self.assertEqual(self.run_option2()["phase"],
                         "FOREIGN_OPTION2_OFFLINE_READY")
        self.assertEqual(self.events.count("install_sanaei"), 0)
        self.assertEqual(self.events.count("install_gateway"), 1)

    def test_gateway_failure_compensates_only_gateway_and_no_code(self):
        self.fail_before = "gateway"
        with self.assertRaises(host.Hold):
            self.run_option2()
        self.assert_no_identity()
        self.assertEqual(self.states["sanaei"], "READY")
        self.assertEqual(self.states["gateway"], "ABSENT")
        self.assertIn("rollback_gateway", self.events)
        self.assertNotIn("rollback_sanaei", self.events)
        self.assertEqual(
            json.loads((self.fixture.stage / host.JOURNAL).read_text())["phase"],
            "SANAEI_RO_VERIFIED")
        self.events.clear()
        self.run_option2()
        self.assertEqual(self.events.count("install_gateway"), 1)
        self.assertNotIn("install_sanaei", self.events)

    def test_sanaei_failure_rolls_back_own_stage_only_before_any_redeem(self):
        self.fail_before = "sanaei"
        with self.assertRaises(host.Hold):
            self.run_option2()
        self.assert_no_identity()
        self.assertEqual(self.states["sanaei"], "ABSENT")
        self.assertEqual(self.states["gateway"], "ABSENT")
        self.assertIn("rollback_sanaei", self.events)
        self.events.clear()
        self.run_option2()
        self.assertEqual(self.events.count("install_sanaei"), 1)
        self.assertEqual(self.events.count("install_gateway"), 1)

    def test_revoked_panel_proof_retains_verified_host_and_staged_secret(self):
        self.fixture.wrong_proof = True
        with self.assertRaises(ValueError):
            self.run_option2()
        self.assertEqual(self.states["sanaei"], "READY")
        self.assertEqual(self.states["gateway"], "READY")
        self.assertFalse(self.fixture.live.exists())
        self.assertTrue(
            (self.fixture.stage / "foreign-install-identity.json").is_file())
        self.assertEqual(
            json.loads((self.fixture.stage / host.JOURNAL).read_text())["phase"],
            "GATEWAY_443_VERIFIED")
        # A retry reuses the original key and never redoes Sanaei/Gateway.
        self.fixture.wrong_proof = False
        self.fixture.calls.clear()
        self.events.clear()
        self.assertEqual(self.run_option2()["signed_panel_proof"], "PASS")
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)

    def test_foreign_gateway_drift_after_redeem_blocks_success_without_rekey(self):
        original = self.verify_gateway
        count = [0]
        def transient(scope):
            count[0] += 1
            # Host recovery's verified receipt passes; post-identity
            # independent witness catches the later drift.
            if self.fixture.live.exists():
                return "DRIFT"
            return original(scope)
        self.verify_gateway = transient
        try:
            with self.assertRaises(host.Hold):
                self.run_option2()
        finally:
            self.verify_gateway = original
        self.assertTrue(self.fixture.live.exists())
        secret_before = self.fixture.live.read_bytes()
        self.fixture.calls.clear()
        self.run_option2()
        self.assertEqual(self.fixture.live.read_bytes(), secret_before)
        self.assertEqual(self.fixture.calls,
                         ["/api/node-control/installation-status"])

    def test_no_disposable_capability_or_unsafe_identity_path_never_runs_host(self):
        for change in (
            {"disposable_capability": False},
            {"transport": None},
            {"live_identity": Path("/etc/u-opti/smite/identities/node-identity.json")},
            {"packet_path": self.fixture.state},
            {"gateway_path": Path("/etc/nginx/conf.d/foreign.conf")},
        ):
            with self.subTest(change=change):
                with self.assertRaises((host.Hold, OSError, ValueError)):
                    self.run_option2(**change)
                self.assertEqual(self.events, [])
                self.assert_no_identity()

    def test_preinstalled_sanaei_and_gateway_are_only_reverified(self):
        self.states["sanaei"] = "READY"
        self.states["gateway"] = "READY"
        self.assertEqual(self.run_option2()["phase"],
                         "FOREIGN_OPTION2_OFFLINE_READY")
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)
        self.assertTrue(self.fixture.live.exists())

    def test_expired_code_never_starts_host_or_signed_redemption(self):
        self.fixture.now = self.fixture.doc["expires_at"]+1
        with self.assertRaises(host.Hold):
            self.run_option2()
        self.assertEqual(self.events, [])
        self.assert_no_identity()

    def test_public_cli_remains_status_only_and_never_claims_connected(self):
        source = (ROOT / "modules" /
                  "smite-unified-foreign-host-recovery.py").read_text()
        self.assertIn('parser.add_argument("--status"', source)
        self.assertNotIn('parser.add_argument("--apply"', source)
        self.assertNotIn('parser.add_argument("--activate"', source)
        self.assertNotIn("FOREIGN_CONNECTED=YES", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
