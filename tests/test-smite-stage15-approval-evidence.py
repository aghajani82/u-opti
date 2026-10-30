"""Offline Stage15 detached Node evidence verification: no privileged operations."""
import base64
import importlib.util
from pathlib import Path
import sys
import unittest

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
except ImportError:
    Ed25519PrivateKey = None

P = Path(__file__).resolve().parents[1] / "modules" / "smite-stage15-approval-evidence.py"
spec = importlib.util.spec_from_file_location("approval_evidence", P)
ev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ev
spec.loader.exec_module(ev)


@unittest.skipUnless(Ed25519PrivateKey, "cryptography test prerequisite")
class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.ir = Ed25519PrivateKey.generate()
        self.kh = Ed25519PrivateKey.generate()
        self.now = 10000
        self.binding = {
            "ir_node": "node-ir-0001", "kh_node": "node-kh-0001",
            "owner": "owner-0001", "child": "child-0001",
            "lease": "child-0001", "port": 38658,
            "path": "/38658/shop", "owner_proof_sha256": "",
            "kh_inventory_sha256": "",
        }
        self.owner = {"tunnel_id": "owner-0001", "control_port": 7000, "proxy_port": 38658}
        self.inbound = {"port": 38658, "listen": "127.0.0.1", "protocol": "vless",
                        "network": "xhttp", "path": "/38658/shop", "enabled": True}
        self.binding["owner_proof_sha256"] = ev.sha256(self.owner)
        self.binding["kh_inventory_sha256"] = ev.sha256(self.inbound)
        self.lease = {
            "ir_node": "node-ir-0001", "kh_node": "node-kh-0001",
            "owner": "owner-0001", "child": "child-0001", "lease": "child-0001",
            "port": 38658, "role": "shared", "state": "active", "unique": True,
            "owner_count": 1, "proxy_port_count": 1,
        }
        self.bundle = {
            "ir_owner": self.sign(self.ir, "frps_owner", "node-ir-0001", self.owner, "1"*32),
            "kh_inbound": self.sign(self.kh, "xhttp_inbound", "node-kh-0001", self.inbound, "2"*32),
            "ir_lease": self.sign(self.ir, "active_lease", "node-ir-0001", self.lease, "3"*32),
        }

    def pub(self, key):
        return key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    def sign(self, key, kind, node, facts, nonce):
        item = {"schema": 1, "audience": ev.AUDIENCE, "kind": kind,
                "node": node, "facts": dict(facts), "nonce": nonce,
                "issued_at": self.now, "expires_at": self.now + 30}
        item["signature"] = base64.urlsafe_b64encode(
            key.sign(ev.canonical(item))
        ).rstrip(b"=").decode("ascii")
        return item

    def check(self, binding=None, bundle=None, **kwargs):
        return ev.verify_bundle(
            self.bundle if bundle is None else bundle,
            self.binding if binding is None else binding,
            ir_public_key=kwargs.get("ir_public_key", self.pub(self.ir)),
            kh_public_key=kwargs.get("kh_public_key", self.pub(self.kh)),
            now=kwargs.get("now", self.now + 1),
            consumed_nonces=kwargs.get("consumed_nonces", frozenset()),
        )

    def test_shared_child_valid(self):
        self.assertEqual(self.check(), frozenset(("1"*32, "2"*32, "3"*32)))

    def test_direct_owner_valid(self):
        self.binding.update(child="owner-0001", lease="owner-0001", port=45121,
                            path="/45121/www")
        self.owner["proxy_port"] = 45121
        self.inbound.update(port=45121, path="/45121/www")
        self.lease.update(child="owner-0001", lease="owner-0001", port=45121, role="direct")
        self.binding["owner_proof_sha256"] = ev.sha256(self.owner)
        self.binding["kh_inventory_sha256"] = ev.sha256(self.inbound)
        self.bundle["ir_owner"] = self.sign(self.ir, "frps_owner", "node-ir-0001", self.owner, "1"*32)
        self.bundle["kh_inbound"] = self.sign(self.kh, "xhttp_inbound", "node-kh-0001", self.inbound, "2"*32)
        self.bundle["ir_lease"] = self.sign(self.ir, "active_lease", "node-ir-0001", self.lease, "3"*32)
        self.assertEqual(len(self.check()), 3)

    def test_wrong_child_rejected(self):
        self.lease["child"] = "other-child"
        self.bundle["ir_lease"] = self.sign(self.ir,"active_lease","node-ir-0001",self.lease,"3"*32)
        with self.assertRaisesRegex(ev.EvidenceHold, "DRIFT"): self.check()

    def test_wrong_owner_rejected(self):
        self.owner["tunnel_id"] = "other-owner"
        self.bundle["ir_owner"] = self.sign(self.ir,"frps_owner","node-ir-0001",self.owner,"1"*32)
        with self.assertRaises(ev.EvidenceHold): self.check()

    def test_wrong_port_or_path_rejected(self):
        for item in ("port", "path"):
            b = dict(self.binding);b[item] = 44000 if item == "port" else "/wrong/path"
            with self.subTest(field=item), self.assertRaises(ev.EvidenceHold): self.check(binding=b)

    def test_invalid_signature_rejected(self):
        self.bundle["ir_owner"]["signature"] = self.bundle["kh_inbound"]["signature"]
        with self.assertRaises(ev.EvidenceHold): self.check()

    def test_wrong_pinned_key_rejected(self):
        with self.assertRaises(ev.EvidenceHold):
            self.check(ir_public_key=self.pub(Ed25519PrivateKey.generate()))

    def test_stale_or_future_rejected(self):
        with self.assertRaises(ev.EvidenceHold): self.check(now=10100)
        with self.assertRaises(ev.EvidenceHold): self.check(now=9990)

    def test_replay_rejected(self):
        with self.assertRaises(ev.EvidenceHold): self.check(consumed_nonces=frozenset({"1"*32}))
        self.bundle["ir_lease"]["nonce"] = "1"*32
        self.bundle["ir_lease"] = self.sign(self.ir,"active_lease","node-ir-0001",self.lease,"1"*32)
        with self.assertRaises(ev.EvidenceHold): self.check()

    def test_panel_supplied_hash_not_an_attestation(self):
        with self.assertRaises(ev.EvidenceHold): self.check(bundle={})
        with self.assertRaises(ev.EvidenceHold): self.check(ir_public_key=b"")

    def test_lease_not_unique_rejected(self):
        self.lease["unique"] = False
        self.bundle["ir_lease"] = self.sign(self.ir,"active_lease","node-ir-0001",self.lease,"3"*32)
        with self.assertRaisesRegex(ev.EvidenceHold,"DRIFT"): self.check()


if __name__ == "__main__":
    unittest.main()
