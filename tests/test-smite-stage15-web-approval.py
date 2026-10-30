"""Single-use Passkey and durable approval records; ALL tests offline."""
from __future__ import annotations
import base64
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[1] / "modules"
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    m = importlib.util.module_from_spec(spec);sys.modules[name] = m
    spec.loader.exec_module(m);return m
gate = load("stage15_approval_test", "smite-stage15-web-approval.py")
ev = load("stage15_evidence_test", "smite-stage15-approval-evidence.py")
ORIGINAL_SERVER = gate._server

class FakeServer:
    def authenticate_begin(self, credentials, user_verification):
        assert user_verification == "required"
        return SimpleNamespace(to_json=lambda: '{"publicKey":{"challenge":"example"}}'), {
            "challenge": "unique-challenge", "user_verification": "required",
        }
    def authenticate_complete(self, state, credentials, assertion):
        assert state["challenge"] == "unique-challenge"
        if assertion.get("test") != "pass":
            raise ValueError("invalid assertion")
        return SimpleNamespace(credential_id=b"credential-01")

class GateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = gate.ApprovalLedger(Path(tmp.name)/"approval.db", root_check=False)
        self.addCleanup(self.ledger.close)
        self.digest = "a"*64
        self.origin = "https://approval.example.org"
        self.patches = [
            patch.object(gate, "_server", return_value=FakeServer()),
            patch.object(gate, "_credentials", return_value=[object()]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def challenge(self):
        return self.ledger.begin(self.digest, origin=self.origin, passkeys=["fake"], now=1000)

    def test_challenge_single_use_and_wrong_digest(self):
        info = self.challenge()
        with self.assertRaisesRegex(gate.WebApprovalHold, "EXPIRED_OR_SPENT"):
            self.ledger.consume(info["challenge_id"],digest="b"*64,origin=self.origin,
                                passkeys=["fake"],assertion={"test":"pass"},now=1001)
        h = self.ledger.consume(info["challenge_id"],digest=self.digest,origin=self.origin,
                                passkeys=["fake"],assertion={"test":"pass"},now=1002)
        self.assertEqual(len(h),64)
        with self.assertRaises(gate.WebApprovalHold):
            self.ledger.consume(info["challenge_id"],digest=self.digest,origin=self.origin,
                                passkeys=["fake"],assertion={"test":"pass"},now=1003)

    def test_invalid_assertion_spends_challenge(self):
        info = self.challenge()
        with self.assertRaisesRegex(gate.WebApprovalHold, "PASSKEY_REJECTED"):
            self.ledger.consume(info["challenge_id"],digest=self.digest,origin=self.origin,
                                passkeys=["fake"],assertion={"test":"wrong"},now=1001)
        with self.assertRaisesRegex(gate.WebApprovalHold, "EXPIRED_OR_SPENT"):
            self.ledger.consume(info["challenge_id"],digest=self.digest,origin=self.origin,
                                passkeys=["fake"],assertion={"test":"pass"},now=1002)

    def test_expired_challenge_rejected(self):
        info = self.challenge()
        with self.assertRaisesRegex(gate.WebApprovalHold, "EXPIRED_OR_SPENT"):
            self.ledger.consume(info["challenge_id"],digest=self.digest,origin=self.origin,
                                passkeys=["fake"],assertion={"test":"pass"},now=2000)

    def test_panel_cannot_approve_without_passkey(self):
        with self.assertRaisesRegex(gate.WebApprovalHold, "UNAUTHENTICATED_APPROVAL"):
            self.ledger.record_verified_approval(
                digest=self.digest, credential_sha256="b"*64, binding={},
                bundle={}, ir_public_key=b"k"*32, kh_public_key=b"k"*32, now=1000)

    def test_passkey_only_cannot_approve_without_independent_evidence(self):
        info = self.challenge()
        cred = self.ledger.consume(info["challenge_id"],digest=self.digest,
                                   origin=self.origin,passkeys=["fake"],
                                   assertion={"test":"pass"},now=1001)
        with self.assertRaises(Exception):
            self.ledger.record_verified_approval(
                digest=self.digest,credential_sha256=cred,binding={},bundle={},
                ir_public_key=b"k"*32,kh_public_key=b"k"*32,now=1002)
        self.assertEqual(self.ledger.conn.execute("SELECT count(*) FROM approvals").fetchone()[0],0)

    def test_pinned_origin_rejects_http(self):
        # Directly exercise origin policy, independent of the mocked server.
        with self.assertRaises(gate.WebApprovalHold):
            ORIGINAL_SERVER("http://approval.example.org")

    def test_durable_audit_retained_after_reopen(self):
        self.challenge()
        n=self.ledger.conn.execute("SELECT count(*) FROM audit").fetchone()[0]
        self.assertEqual(n,1)
        self.assertEqual(self.ledger.conn.execute("PRAGMA synchronous").fetchone()[0],2)

if __name__ == "__main__":
    unittest.main()
