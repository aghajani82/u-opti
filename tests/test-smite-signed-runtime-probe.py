#!/usr/bin/env python3
"""Offline pinned Smite HMAC-v1 protocol tests. No network/Node/VPS access."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".managed-smite-source/node/app/node_auth.py"
if not SRC.is_file():
    raise RuntimeError("PINNED_SMITE_SOURCE_NOT_CHECKED_OUT")
spec = importlib.util.spec_from_file_location("smite_pinned_hmac_v1_ci", SRC)
hmac_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hmac_source)

P = ROOT / "tests/lab/smite_signed_runtime_probe.py"
spec = importlib.util.spec_from_file_location("smite_runtime_probe_ci", P)
probe = importlib.util.module_from_spec(spec)
# Dataclasses require module registration when imported dynamically.
import sys
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)

LAB = ROOT / "tests/lab/smite_host_executor.py"
spec2 = importlib.util.spec_from_file_location("smite_recovery_probe_ci", LAB)
lab = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(lab)

NODE = "bbbbbbbb-1111-2222-3333-444444444444"
KEY = b"k" * 64
ORIGIN = "https://node-kh.example.test:443"
ZERO = {name: "not-installed" for name in probe.EXPECTED_ENGINES}
BACKHAUL_READY = dict(ZERO, backhaul="ready")
FRP_READY = dict(ZERO, frp="ready")


class PinnedMockAgent:
    """Mock receiver evaluates the real reviewed Smite verify_request."""
    def __init__(self, *, engine_states=None):
        self.engine_states = ZERO if engine_states is None else engine_states
        self.replay = hmac_source.NonceWindow()
        self.clock = 1730000000
        self.tls = True
        self.redirect = False
        self.disable_auth = False
        self.no_replay_check = False
        self.force_code = None
        self.status_body = None
        self.inventory_body = None
        self.sent = []

    def __call__(self, *, origin, target, method, body, headers,
                 verify_tls, allow_redirects):
        assert verify_tls is True
        assert allow_redirects is False
        assert method == "GET"
        assert body == b""
        self.sent.append((origin, target, dict(headers)))
        valid = self.disable_auth
        if not valid:
            try:
                # Verify the ACTUAL source code from the pinned Smite commit.
                valid = hmac_source.verify_request(
                    secret=KEY, node_id=NODE, method=method,
                    target=target, body=body, headers=headers,
                    replay=self.replay if not self.no_replay_check
                    else hmac_source.NonceWindow(),
                    now=self.clock)
            except Exception:
                valid = False
        status = 200 if valid else 401
        if self.force_code is not None:
            status = self.force_code
        data = b"{}"
        if status == 200:
            if target == "/api/agent/status":
                payload = (self.status_body if self.status_body is not None else
                           {"status": "ok", "active_tunnels": 0, "tunnels": []})
            else:
                payload = (self.inventory_body if self.inventory_body is not None else
                           {"mode": "managed", "engines": self.engine_states})
            data = json.dumps(payload).encode()
        return probe.Reply(status=status, body=data, tls_verified=self.tls,
                           origin=origin, target=target, redirected=self.redirect)


class SignedRuntimeProtocol(unittest.TestCase):
    def setUp(self):
        self.agent = PinnedMockAgent()
        self.verifier = probe.MockOnlySignedRuntimeVerifier(
            node_id=NODE, secret=KEY, origin=ORIGIN,
            approved_origin=ORIGIN, signer=hmac_source.sign_request,
            transport=self.agent)

    def check(self, states=ZERO):
        return self.verifier.check(states, now=self.agent.clock)

    def test_pinned_hmac_v1_unsigned_replay_wrong_key_and_inventory(self):
        result = self.check()
        self.assertEqual(result["RESULT"], "SIGNED_HMAC_AND_REPLAY_SIMULATION_PASS")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertEqual(result["REAL_TLS_443"], "NOT_TESTED")
        self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        self.assertEqual(len(self.agent.sent), 6)
        self.assertEqual(self.agent.sent[0][2], {})
        self.assertEqual(self.agent.sent[1][2], self.agent.sent[2][2])
        self.assertNotEqual(self.agent.sent[1][2]["X-Smite-Nonce"],
                            self.agent.sent[3][2]["X-Smite-Nonce"])
        self.assertEqual(self.agent.sent[-1][1], "/api/agent/engines")

    def test_both_engine_inventories_without_installer_approval(self):
        for states in (BACKHAUL_READY, FRP_READY,
                       dict(BACKHAUL_READY, frp="ready")):
            with self.subTest(states=states):
                agent = PinnedMockAgent(engine_states=states)
                verifier = probe.MockOnlySignedRuntimeVerifier(
                    node_id=NODE, secret=KEY, origin=ORIGIN,
                    approved_origin=ORIGIN, signer=hmac_source.sign_request,
                    transport=agent)
                self.assertEqual(verifier.check(states, now=agent.clock)["INVENTORY_MATCH"], "YES")

    def test_unsigned_endpoint_200_is_rejected(self):
        self.agent.disable_auth = True
        with self.assertRaisesRegex(probe.Hold, "SIGNED_NODE_AUTH_POLICY_FAILED"):
            self.check()

    def test_missing_replay_defense_is_rejected(self):
        self.agent.no_replay_check = True
        with self.assertRaisesRegex(probe.Hold, "SIGNED_NODE_AUTH_POLICY_FAILED"):
            self.check()

    def test_invalid_transport_tls_and_redirect_fail_closed(self):
        self.agent.tls = False
        with self.assertRaisesRegex(probe.Hold, "UNVERIFIED_TLS_OR_RESPONSE_TARGET"):
            self.check()
        self.agent.tls = True
        self.agent.redirect = True
        with self.assertRaisesRegex(probe.Hold, "UNVERIFIED_TLS_OR_RESPONSE_TARGET"):
            self.check()

    def test_unapproved_https_origin_and_cleartext_fail_before_request(self):
        variants = ("http://node-kh.example.test:443",
                    "https://node-kh.example.test:9443",
                    "https://127.0.0.1:443",
                    "https://user@node-kh.example.test:443",
                    "https://node-kh.example.test:443/api/agent/status",
                    "https://node-kh.example.test:443?foo=1",
                    "https://node-kh.example.test:443#foo",
                    "https://evil.example.test:443")
        for item in variants:
            with self.subTest(item=item), self.assertRaises(probe.Hold):
                probe.MockOnlySignedRuntimeVerifier(
                    node_id=NODE, secret=KEY, origin=item, approved_origin=ORIGIN,
                    signer=hmac_source.sign_request, transport=self.agent)
        self.assertEqual(self.agent.sent, [])

    def test_legacy_and_mismatched_engine_response_fail_closed(self):
        self.agent.inventory_body = {"mode": "legacy", "engines": ZERO}
        with self.assertRaisesRegex(probe.Hold, "SIGNED_ENGINE_INVENTORY_MISMATCH"):
            self.check()
        self.agent = PinnedMockAgent()
        self.verifier.transport = self.agent
        self.agent.inventory_body = {"mode": "managed", "engines": BACKHAUL_READY}
        with self.assertRaisesRegex(probe.Hold, "SIGNED_ENGINE_INVENTORY_MISMATCH"):
            self.check()

    def test_html_200_status_not_accepted(self):
        self.agent.status_body = {"status": "ok", "active_tunnels": 0,
                                  "tunnels": [], "signed": True}
        with self.assertRaisesRegex(probe.Hold, "UNEXPECTED_SIGNED_NODE_STATUS"):
            self.check()

    def test_unexpected_tunnels_block_host_acceptance(self):
        self.agent.status_body = {"status": "ok", "active_tunnels": 1,
                                  "tunnels": ["saved"]}
        with self.assertRaisesRegex(probe.Hold, "UNEXPECTED_SIGNED_NODE_STATUS"):
            self.check()

    def test_transport_failure_and_wrong_response_code(self):
        self.agent.force_code = 503
        with self.assertRaisesRegex(probe.Hold, "SIGNED_NODE_AUTH_POLICY_FAILED"):
            self.check()

        def outage(**kwargs):
            raise TimeoutError("simulated")
        self.verifier.transport = outage
        with self.assertRaisesRegex(probe.Hold, "SIGNED_NODE_TRANSPORT_UNAVAILABLE"):
            self.check()

    def test_mock_only_result_can_gate_sandbox_recovery(self):
        with tempfile.TemporaryDirectory(prefix="uopti-engine-txn-lab-") as folder:
            root = Path(folder)
            root.chmod(0o700)
            (root / ".LAB_ONLY").write_bytes(lab.MARKER)
            node = root / "node"
            (node / "config/engine-state").mkdir(parents=True, mode=0o700)
            (node / "docker-compose.yml").write_bytes(b"services:\n  smite-node:\n    image: pinned\n")
            (node / ".env").write_bytes(b"SMITE_AGENT_AUTH_MODE=strict\n")
            (node / "config/node-id").write_bytes(b"kept-node")
            (node / "config/replay.db").write_bytes(b"kept-replay")
            (node / "config/tunnels.json").write_bytes(b"[]\n")
            import hashlib
            manifest = {"schema": 1, "engines": {"backhaul": {"sha256": lab.sha(b"toy-bh")}}}
            overlay = b"services:\n  smite-node:\n    volumes: []\n"
            preview = {
                "STAGE_ADMISSION": "VERIFIED_PREVIEW_ONLY",
                "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
                "BINARIES_SHA256": [lab.sha(b"toy-bh")],
                "CANDIDATE_COMPOSE_OVERLAY_SHA256": lab.sha(overlay),
                "SOURCE_COMPOSE_SHA256": lab.sha((node / "docker-compose.yml").read_bytes()),
                "CANDIDATE_MANIFEST_SHA256": lab.sha(lab.canonical(manifest)),
                "OTHER_ENGINE": "NOT_INSTALLED",
            }
            def runtime(kind, engine):
                self.agent.engine_states = BACKHAUL_READY if kind == "new" else ZERO
                result = self.check(self.agent.engine_states)
                return {"signed": result["INVENTORY_MATCH"] == "YES",
                        "replay": result["RESULT"] == "SIGNED_HMAC_AND_REPLAY_SIMULATION_PASS"}
            result = lab.execute(root, "backhaul", {"backhaul": b"toy-bh"},
                                 overlay, preview, runtime)
            self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
            self.assertEqual(lab.recover(root, runtime), "COMMITTED")
            self.assertEqual((node / "config/node-id").read_bytes(), b"kept-node")
            self.assertEqual((node / "config/replay.db").read_bytes(), b"kept-replay")

    def test_signed_runtime_failure_compensates_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="uopti-engine-txn-lab-") as folder:
            root = Path(folder)
            root.chmod(0o700)
            (root / ".LAB_ONLY").write_bytes(lab.MARKER)
            node = root / "node"
            (node / "config/engine-state").mkdir(parents=True, mode=0o700)
            (node / "docker-compose.yml").write_bytes(b"compose")
            (node / "config/tunnels.json").write_bytes(b"[]\n")
            overlay = b"test-override"
            preview = {"STAGE_ADMISSION": "VERIFIED_PREVIEW_ONLY",
                       "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
                       "BINARIES_SHA256": [lab.sha(b"engine")],
                       "CANDIDATE_COMPOSE_OVERLAY_SHA256": lab.sha(overlay),
                       "SOURCE_COMPOSE_SHA256": lab.sha(b"compose"),
                       "CANDIDATE_MANIFEST_SHA256": lab.sha(
                           lab.canonical({"schema": 1, "engines": {
                               "backhaul": {"sha256": lab.sha(b"engine")}}})),
                       "OTHER_ENGINE": "NOT_INSTALLED"}
            def failing(kind, engine):
                self.agent.engine_states = ZERO
                if kind == "new":
                    # Successful HMAC but wrong enrollment; must still HOLD.
                    self.check(BACKHAUL_READY)
                else:
                    self.check(ZERO)
                return {"signed": True, "replay": True}
            with self.assertRaises(probe.Hold):
                lab.execute(root, "backhaul", {"backhaul": b"engine"},
                            overlay, preview, failing)
            self.assertEqual(lab.recover(root, failing), "ROLLED_BACK")
            self.assertFalse((node / "config/engine-state/engines.json").exists())

    def test_no_real_http_client_or_production_cli(self):
        contents = P.read_text()
        for name in ("import requests", "import httpx", "import urllib.request",
                     "subprocess.", "socket.", "paramiko", "docker compose",
                     "systemctl", "if __name__ =="):
            self.assertNotIn(name, contents)


if __name__ == "__main__":
    unittest.main(verbosity=2)
