"""Synthetic host-origin protocol tests: no Docker, Node, root, network or live grants."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

BASE = Path(__file__).resolve().parents[1] / "modules"


def module(filename, name):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


host = module("smite-stage15-host-evidence-offline.py", "host_evidence_offline")
node = module("smite-stage15-approval-evidence.py", "node_evidence_verifier_for_host_test")


class HostEvidencePrototypeTests(unittest.TestCase):
    def setUp(self):
        self.ir_key = Ed25519PrivateKey.generate()
        self.kh_key = Ed25519PrivateKey.generate()
        self.ir_pin = self.ir_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.kh_pin = self.kh_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.binding = {
            "ir_node": "node-ir-0001", "kh_node": "node-kh-0001",
            "owner": "FRP-IR-KH-45121", "child": "frp10", "lease": "frp10",
            "port": 38658, "path": "/38658/shop",
        }
        self.ir_facts = {
            "node": "node-ir-0001", "tunnel_id": self.binding["owner"],
            "control_port": 7000, "proxy_port": 38658,
            "owner_pid": 512, "owner_start_ticks": 192837,
            "node_container_id": "a" * 64, "registry_sha256": "b" * 64,
            "listener_ports": [7000, 28897, 38658, 45121],
        }
        self.kh_facts = {
            "node": "node-kh-0001", "port": 38658, "listen": "127.0.0.1",
            "protocol": "vless", "network": "xhttp", "path": "/38658/shop",
            "enabled": True, "xray_pid": 777, "xray_start_ticks": 62718,
            "sanaei_container_id": "c" * 64, "db_view_sha256": "d" * 64,
            "frpc_count": 3,
        }
        self.pair = {
            "ir_host": host.sign_offline_fixture(
                role="ir_host", facts=self.ir_facts, key=self.ir_key,
                nonce="1" * 32, issued_at=1000),
            "kh_host": host.sign_offline_fixture(
                role="kh_host", facts=self.kh_facts, key=self.kh_key,
                nonce="2" * 32, issued_at=1000),
        }

    def verify(self, pair=None, **kwargs):
        return host.verify_offline_pair(
            pair=self.pair if pair is None else pair,
            binding=kwargs.pop("binding", self.binding),
            ir_host_public=kwargs.pop("ir_host_public", self.ir_pin),
            kh_host_public=kwargs.pop("kh_host_public", self.kh_pin),
            now=kwargs.pop("now", 1001),
            **kwargs)

    def test_real_ed25519_two_distinct_host_keys_roundtrip(self):
        added = self.verify()
        self.assertEqual(added, frozenset(("1" * 32, "2" * 32)))
        self.assertNotEqual(host.AUDIENCE, node.AUDIENCE)

    def test_no_cross_protocol_node_proof_acceptance(self):
        with self.assertRaises(node.EvidenceHold):
            node.verify_bundle({
                "ir_owner": self.pair["ir_host"],
                "kh_inbound": self.pair["kh_host"],
                "ir_lease": self.pair["ir_host"],
            }, {
                **self.binding,
                "owner_proof_sha256": "a" * 64,
                "kh_inventory_sha256": "b" * 64,
            }, ir_public_key=self.ir_pin,
               kh_public_key=self.kh_pin, lease_public_key=self.ir_pin, now=1001)

    def test_signature_tampering_fails_closed(self):
        pair = copy.deepcopy(self.pair)
        pair["ir_host"]["facts"]["owner_pid"] = 513
        with self.assertRaisesRegex(host.HostEvidenceHold, "SIGNATURE"):
            self.verify(pair)

    def test_swapped_key_and_equal_pins_rejected(self):
        with self.assertRaises(host.HostEvidenceHold):
            self.verify(ir_host_public=self.kh_pin, kh_host_public=self.ir_pin)
        with self.assertRaisesRegex(host.HostEvidenceHold, "PINS_NOT_INDEPENDENT"):
            self.verify(kh_host_public=self.ir_pin)

    def test_stale_future_and_replayed_proof_fail_closed(self):
        for now in (9999, 990):
            with self.subTest(now=now), self.assertRaisesRegex(
                    host.HostEvidenceHold, "STALE_OR_REPLAYED"):
                self.verify(now=now)
        with self.assertRaisesRegex(host.HostEvidenceHold, "STALE_OR_REPLAYED"):
            self.verify(consumed_nonces=frozenset({"2" * 32}))
        pair = copy.deepcopy(self.pair)
        pair["kh_host"] = host.sign_offline_fixture(
            role="kh_host", facts=self.kh_facts, key=self.kh_key,
            nonce="1" * 32, issued_at=1000)
        with self.assertRaisesRegex(host.HostEvidenceHold, "STALE_OR_REPLAYED"):
            self.verify(pair)

    def test_binding_path_node_and_port_mismatches_rejected(self):
        for changed in (
            {"path": "/38658/else"},
            {"port": 38659},
            {"ir_node": "node-ir-other"},
            {"kh_node": "node-kh-other"},
            {"owner": "other-owner"},
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(host.HostEvidenceHold,
                                            "HOST_BINDING_EVIDENCE_DRIFT"):
                    self.verify(binding={**self.binding, **changed})

    def test_ir_must_have_pinned_loopback_owner_and_generation(self):
        for key, invalid in (
            ("owner_pid", 0),
            ("owner_start_ticks", -1),
            ("registry_sha256", "f" * 63),
            ("node_container_id", "not-a-container"),
            ("listener_ports", [7000, 38658, 38658]),
            ("listener_ports", [38658, 45121]),
            ("control_port", 7001),
        ):
            with self.subTest(key=key), self.assertRaises(host.HostEvidenceHold):
                host.sign_offline_fixture(role="ir_host",
                    facts={**self.ir_facts, key: invalid},
                    key=self.ir_key, nonce="4" * 32, issued_at=1000)

    def test_kh_requires_strict_sanaei_and_three_frpc(self):
        for key, invalid in (
            ("path", "/api/connect"),
            ("listen", "0.0.0.0"),
            ("protocol", "trojan"),
            ("network", "tcp"),
            ("enabled", False),
            ("frpc_count", 2),
            ("db_view_sha256", "f" * 20),
            ("xray_pid", 0),
        ):
            with self.subTest(key=key), self.assertRaises(host.HostEvidenceHold):
                host.sign_offline_fixture(role="kh_host",
                    facts={**self.kh_facts, key: invalid},
                    key=self.kh_key, nonce="4" * 32, issued_at=1000)

    def test_unknown_and_extra_provenance_rejected(self):
        pair = copy.deepcopy(self.pair)
        pair["ir_host"]["unreviewed"] = True
        with self.assertRaisesRegex(host.HostEvidenceHold, "SCHEMA"):
            self.verify(pair)
        pair = copy.deepcopy(self.pair)
        pair["kh_host"]["audience"] = node.AUDIENCE
        with self.assertRaises(host.HostEvidenceHold):
            self.verify(pair)

    def test_no_public_endpoint_or_grant_connectors_present(self):
        source = (BASE / "smite-stage15-host-evidence-offline.py").read_text()
        for forbidden in ("docker run", "subprocess.", "socket.", "httpx.",
                          "install_grant(", "create_grant(", "serve_forever(",
                          "FRPS_RESTART=YES"):
            self.assertNotIn(forbidden, source)
        self.assertIn("OFFLINE_LIBRARY_ONLY_NO_HOST_SERVICE_OR_GRANT", source)


if __name__ == "__main__":
    unittest.main()
