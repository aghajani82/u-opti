#!/usr/bin/env python3
"""Offline adversarial contract tests: no socket, host writer or secret file."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import unittest


FILE = Path(__file__).resolve().parents[1] / "modules" / "smite-rc5-xhttp-signed-intent.py"
spec = importlib.util.spec_from_file_location("uopti_rc5_route_intent", FILE)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)

KEY = bytes(range(32))
T = 1_798_000_000


def sample():
    return {
        "schema": 1,
        "audience": policy.AUDIENCE,
        "action": "create",
        "ir_node": "node-ir-0001",
        "kh_node": "node-kh-0001",
        "owner": "trial-frp-45121",
        "child": "trial-frp-49328",
        "lease": "lease-49328-00001",
        "port": 49328,
        "path": "/49328/sso",
        "owner_proof_sha256": "a" * 64,
        "kh_inventory_sha256": "b" * 64,
        "issued_at": T,
        "expires_at": T + 30,
        "nonce": "c" * 32,
    }


def grant(payload):
    return policy.TrustedGrant(**{
        k: payload[k] for k in (
            "ir_node", "kh_node", "owner", "child", "lease", "port",
            "path", "owner_proof_sha256", "kh_inventory_sha256",
        )
    })


def signed(payload, key=KEY):
    mac = hmac.new(key, policy.canonical(payload), hashlib.sha256).hexdigest()
    return policy.canonical({**payload, "mac": mac})


class IntentContractTests(unittest.TestCase):
    def setUp(self):
        self.msg = sample()
        self.root_grant = grant(self.msg)

    def authorize(self, payload=None, **kwargs):
        return policy.admit(
            signed(payload or self.msg), key=kwargs.pop("key", KEY),
            expected=kwargs.pop("expected", self.root_grant),
            now=kwargs.pop("now", T + 1),
            seen_nonces=kwargs.pop("seen_nonces", frozenset()),
            **kwargs,
        )

    def test_correct_envelope_is_authenticated_only_not_executed(self):
        x = self.authorize()
        self.assertEqual(x.port, 49328)
        self.assertEqual(x.path, "/49328/sso")
        self.assertEqual(x.child, "trial-frp-49328")
        self.assertEqual(x.nonce, "c" * 32)
        self.assertFalse(hasattr(x, "command"))
        self.assertFalse(hasattr(x, "nginx"))

    def test_strict_node_owner_lease_port_and_evidence_binding(self):
        for name, value in (
            ("ir_node", "node-ir-0002"),
            ("kh_node", "node-kh-0002"),
            ("owner", "trial-frp-00002"),
            ("child", "trial-frp-52000"),
            ("lease", "lease-49328-00002"),
            ("port", 52000),
            ("path", "/49328/other"),
            ("owner_proof_sha256", "d" * 64),
            ("kh_inventory_sha256", "e" * 64),
        ):
            with self.subTest(name=name), self.assertRaises(policy.IntentHold):
                self.authorize({**self.msg, name: value})

    def test_signed_wrong_path_and_public_or_control_port_are_rejected(self):
        for patch in (
            {"port": 7000, "path": "/7000/control"},
            {"port": 443, "path": "/443/x"},
            {"path": "/49328/../sso"},
            {"path": "/49328/sso/"},
            {"path": "/49328/sso?token=hidden"},
            {"path": "/49328/sso;return"},
            {"path": "/45121/sso"},
            {"port": True},
            {"port": "49328"},
            {"port": 65536},
        ):
            with self.subTest(patch=patch), self.assertRaises(policy.IntentHold):
                self.authorize({**self.msg, **patch})

    def test_bad_mac_wrong_key_tampered_wire_and_noncanonical_fail(self):
        good = signed(self.msg)
        broken = good.replace(b'"port":49328', b'"port":52000')
        with self.assertRaises(policy.IntentHold):
            policy.admit(broken, key=KEY, expected=self.root_grant,
                         seen_nonces=frozenset(), now=T + 1)
        with self.assertRaises(policy.IntentHold):
            self.authorize(key=b"z" * 32)
        with self.assertRaises(policy.IntentHold):
            policy.admit(good + b"\n", key=KEY, expected=self.root_grant,
                         seen_nonces=frozenset(), now=T + 1)
        with self.assertRaises(policy.IntentHold):
            policy.admit(b' ' + good, key=KEY, expected=self.root_grant,
                         seen_nonces=frozenset(), now=T + 1)

    def test_no_duplicate_json_keys_unknown_fields_or_extra_actions(self):
        good = signed(self.msg)
        duplicate = good.replace(b'"port":49328', b'"port":49328,"port":49328')
        with self.assertRaises(policy.IntentHold):
            policy.admit(duplicate, key=KEY, expected=self.root_grant,
                         seen_nonces=frozenset(), now=T + 1)
        for patch in (
            {"action": "delete"},
            {"action": "restart-frps"},
            {"audience": "u-opti:kh:xhttp-route:v1"},
            {"schema": 2},
            {"extra_shell": "/bin/sh"},
        ):
            with self.subTest(patch=patch), self.assertRaises(policy.IntentHold):
                self.authorize({**self.msg, **patch})

    def test_timestamps_short_lived_expired_future_and_replay(self):
        with self.assertRaises(policy.IntentHold):
            self.authorize(now=T + 31)
        with self.assertRaises(policy.IntentHold):
            self.authorize(now=T - 6)
        with self.assertRaises(policy.IntentHold):
            self.authorize(seen_nonces=frozenset({"c" * 32}))
        for expires in (T + 61, T, T - 1):
            with self.subTest(expires=expires), self.assertRaises(policy.IntentHold):
                self.authorize({**self.msg, "expires_at": expires})
        for issued in (True, -1, 3.5):
            with self.subTest(issued=issued), self.assertRaises(policy.IntentHold):
                self.authorize({**self.msg, "issued_at": issued})

    def test_untrusted_context_absent_wrong_type_or_short_key(self):
        message = signed(self.msg)
        for changes in (
            {"key": b"x" * 16},
            {"key": b"x" * 64},
            {"key": "x" * 32},
            {"expected": self.msg},
            {"expected": None},
            {"seen_nonces": set()},
            {"now": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(policy.IntentHold):
                params = {
                    "key": KEY, "expected": self.root_grant,
                    "seen_nonces": frozenset(), "now": T + 1,
                }
                params.update(changes)
                policy.admit(message, **params)

    def test_unsafe_json_massive_payload_and_wire_types(self):
        for wire in (
            b"null", b"{}", b"[]", b'{"port":NaN}',
            b"[" * 5000, b"\xff\xfe", signed(self.msg) * 5,
            "{}",
        ):
            with self.subTest(wire=str(wire)[:40]), self.assertRaises(policy.IntentHold):
                policy.admit(wire, key=KEY, expected=self.root_grant,
                             seen_nonces=frozenset(), now=T + 1)

    def test_replay_rejection_is_read_only_and_broker_must_consume_durably(self):
        seen = frozenset({"d" * 32})
        result = self.authorize(seen_nonces=seen)
        self.assertEqual(result.nonce, "c" * 32)
        self.assertEqual(seen, frozenset({"d" * 32}))
        # AuthenticatedIntent is not an authorization to execute root steps.
        with self.assertRaises(Exception):
            result.port = 1234


if __name__ == "__main__":
    unittest.main()
