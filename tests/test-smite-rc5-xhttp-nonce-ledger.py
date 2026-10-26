#!/usr/bin/env python3
"""Offline root-only nonce ledger tests. NEVER access host Nginx, FRPS or Node."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "modules" / "smite-rc5-xhttp-nonce-ledger.py"
spec = importlib.util.spec_from_file_location("uopti_rc5_root_nonce_ledger_test", MODULE)
ledger_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ledger_module
spec.loader.exec_module(ledger_module)
intent = ledger_module._contract_module()

KEY = bytes(range(32))
NOW = 1_798_000_000
INSTANCE_ID = "broker-ir-0001"


def approved():
    return {
        "schema": 1, "audience": intent.AUDIENCE, "action": "create",
        "ir_node": "node-ir-0001", "kh_node": "node-kh-0001",
        "owner": "trial-frp-45121", "child": "trial-frp-49328",
        "lease": "lease-49328-00001", "port": 49328, "path": "/49328/sso",
        "owner_proof_sha256": "a" * 64, "kh_inventory_sha256": "b" * 64,
        "issued_at": NOW, "expires_at": NOW + 30, "nonce": "c" * 32,
    }


def wire(body):
    mac = hmac.new(KEY, intent.canonical(body), hashlib.sha256).hexdigest()
    return intent.canonical({**body, "mac": mac})


def root_grant(body):
    return intent.TrustedGrant(**{
        k: body[k] for k in (
            "ir_node", "kh_node", "owner", "child", "lease",
            "port", "path", "owner_proof_sha256", "kh_inventory_sha256",
        )
    })


class RootNonceLedgerTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.geteuid(), 0, "These tests use root-owned temp 0700 fixtures only")
        self.temp = tempfile.TemporaryDirectory(prefix="uopti-broker-ledger-")
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.parent.chmod(0o700)
        self.db = self.parent / "nonce.db"
        self.ledger = ledger_module.DurableNonceLedger(
            self.db, instance_id=INSTANCE_ID
        )
        self.binding = approved()
        self.grant = root_grant(self.binding)

    def provision(self):
        ledger_module.DurableNonceLedger.bootstrap_new(
            self.db, instance_id=INSTANCE_ID
        )

    def test_missing_ledger_never_auto_created_during_request(self):
        with self.assertRaisesRegex(ledger_module.LedgerHold, "BROKER_LEDGER_MISSING"):
            self.ledger.authenticate_and_consume(
                wire(self.binding), key=KEY, expected=self.grant, now=NOW + 1,
            )
        self.assertFalse(self.db.exists())

    def test_one_time_explicit_bootstrap_and_private_storage(self):
        self.provision()
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        with self.assertRaises((OSError, ledger_module.LedgerHold)):
            self.provision()
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone(), (1,))
            self.assertEqual(
                conn.execute("SELECT instance_id FROM broker_identity").fetchall(),
                [(INSTANCE_ID,)],
            )

    def test_signed_intent_is_consumed_once_and_persists_after_restart(self):
        self.provision()
        signed = wire(self.binding)
        accepted = self.ledger.authenticate_and_consume(
            signed, key=KEY, expected=self.grant, now=NOW + 1
        )
        self.assertEqual(accepted.port, 49328)
        self.assertEqual(accepted.path, "/49328/sso")
        fresh_instance = ledger_module.DurableNonceLedger(
            self.db, instance_id=INSTANCE_ID
        )
        with self.assertRaisesRegex(ledger_module.LedgerHold, "BROKER_NONCE_ALREADY_CONSUMED"):
            fresh_instance.authenticate_and_consume(
                signed, key=KEY, expected=self.grant, now=NOW + 2
            )
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute(
                "SELECT nonce, request_sha256 FROM consumed_nonces"
            ).fetchall()
        self.assertEqual(rows, [("c" * 32, hashlib.sha256(signed).hexdigest())])

    def test_invalid_signature_or_untrusted_grant_never_consumes(self):
        self.provision()
        signed = wire(self.binding)
        with self.assertRaises(intent.IntentHold):
            self.ledger.authenticate_and_consume(
                signed, key=b"y" * 32, expected=self.grant, now=NOW + 1
            )
        with self.assertRaises(ledger_module.LedgerHold):
            self.ledger.authenticate_and_consume(
                signed, key=KEY, expected=self.binding, now=NOW + 1
            )
        with self.assertRaises(intent.IntentHold):
            self.ledger.authenticate_and_consume(
                signed, key=KEY,
                expected=replace(self.grant, lease="lease-49328-00002"),
                now=NOW + 1
            )
        with self.assertRaises(intent.IntentHold):
            self.ledger.authenticate_and_consume(
                signed, key=KEY, expected=self.grant, now=NOW + 31
            )
        with sqlite3.connect(self.db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM consumed_nonces").fetchone()[0]
        self.assertEqual(count, 0)
        self.ledger.authenticate_and_consume(
            signed, key=KEY, expected=self.grant, now=NOW + 2
        )

    def test_concurrent_same_nonce_accepts_exactly_one(self):
        self.provision()
        signed = wire(self.binding)
        def claim():
            try:
                self.ledger.authenticate_and_consume(
                    signed, key=KEY, expected=self.grant, now=NOW + 2
                )
                return "PASS"
            except ledger_module.LedgerHold as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(results.count("PASS"), 1, results)
        self.assertEqual(results.count("BROKER_NONCE_ALREADY_CONSUMED"), 1, results)

    def test_capacity_refuses_next_message_without_deleting_history(self):
        self.provision()
        one = ledger_module.DurableNonceLedger(
            self.db, instance_id=INSTANCE_ID, max_entries=1
        )
        one.authenticate_and_consume(
            wire(self.binding), key=KEY, expected=self.grant, now=NOW + 1
        )
        another = {**self.binding, "nonce": "d" * 32}
        with self.assertRaisesRegex(ledger_module.LedgerHold, "CAPACITY_HOLD"):
            one.authenticate_and_consume(
                wire(another), key=KEY, expected=self.grant, now=NOW + 2
            )
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM consumed_nonces").fetchone(), (1,))

    def test_wrong_instance_id_and_corrupt_schema_hold(self):
        self.provision()
        other = ledger_module.DurableNonceLedger(
            self.db, instance_id="broker-ir-0002"
        )
        with self.assertRaisesRegex(ledger_module.LedgerHold, "IDENTITY_MISMATCH"):
            other.authenticate_and_consume(
                wire(self.binding), key=KEY, expected=self.grant, now=NOW + 1
            )
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA user_version=0")
        with self.assertRaisesRegex(ledger_module.LedgerHold, "VERSION_MISMATCH"):
            self.ledger.authenticate_and_consume(
                wire(self.binding), key=KEY, expected=self.grant, now=NOW + 1
            )

    def test_unsafe_permissions_symlink_and_missing_private_parent_hold(self):
        self.provision()
        self.db.chmod(0o666)
        with self.assertRaises(ledger_module.LedgerHold):
            self.ledger.consume("c" * 32, "a" * 64, now=NOW)
        self.db.chmod(0o600)
        self.parent.chmod(0o755)
        with self.assertRaises(ledger_module.LedgerHold):
            self.ledger.consume("c" * 32, "a" * 64, now=NOW)
        self.parent.chmod(0o700)
        link = self.parent / "alias.db"
        link.symlink_to(self.db)
        with self.assertRaises(ledger_module.LedgerHold):
            ledger_module.DurableNonceLedger(
                link, instance_id=INSTANCE_ID
            ).consume("c" * 32, "a" * 64, now=NOW)

    def test_reject_boolean_nonce_malformed_sha_and_untrusted_configuration(self):
        for nonce, digest in (
            (True, "a" * 64), ("short", "a" * 64),
            ("c" * 32, "broken"), ("d" * 32, True),
        ):
            with self.subTest(nonce=nonce, digest=digest), self.assertRaises(ledger_module.LedgerHold):
                self.ledger.consume(nonce, digest, now=NOW)
        with self.assertRaises(ledger_module.LedgerHold):
            ledger_module.DurableNonceLedger(
                self.db, instance_id="short"
            )
        with self.assertRaises(ledger_module.LedgerHold):
            ledger_module.DurableNonceLedger(
                self.db, instance_id=INSTANCE_ID, max_entries=True
            )

    def test_does_not_make_root_routes_or_start_services(self):
        src = MODULE.read_text()
        for forbidden in (
            "subprocess.run(", "systemctl", "nginx -s reload",
            "sudo ", "docker exec", "socket.socket(", "FastAPI(",
        ):
            self.assertNotIn(forbidden, src)
        self.assertFalse((self.parent / "smite-xhttp-routes").exists())


if __name__ == "__main__":
    unittest.main()
