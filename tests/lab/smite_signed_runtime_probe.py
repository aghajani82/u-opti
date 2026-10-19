#!/usr/bin/env python3
"""Offline-only Signed Node runtime acceptance simulation.

No sockets, HTTP client, Docker, shell, server paths or credentials store.
The caller injects the signer from the exact reviewed Smite node_auth.py
SHA and a mock transport. This is NOT an operational HMAC/TLS probe.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import secrets
import time
from urllib.parse import urlsplit

EXPECTED_ENGINES = frozenset(("backhaul", "frp", "gost", "rathole", "chisel"))
STATES = frozenset(("not-installed", "unavailable", "ready"))
TARGETS = ("/api/agent/status", "/api/agent/engines")
NODE_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
HOST = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z][a-z0-9-]{1,62}$")
HEX_NONCE = re.compile(r"^[a-f0-9]{32}$")


class Hold(RuntimeError):
    """No acceptance when an independent observable contract is violated."""


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    tls_verified: bool
    origin: str
    target: str
    redirected: bool = False


def _origin(value: str) -> str:
    if not isinstance(value, str) or len(value) > 300:
        raise Hold("UNTRUSTED_SIGNED_NODE_ORIGIN")
    try:
        item = urlsplit(value)
        host = item.hostname
        port = item.port
    except ValueError as exc:
        raise Hold("UNTRUSTED_SIGNED_NODE_ORIGIN") from exc
    if (item.scheme != "https" or not host or not HOST.fullmatch(host)
            or value != f"https://{host}:443" or port != 443
            or item.username is not None or item.password is not None
            or item.path or item.query or item.fragment):
        raise Hold("UNTRUSTED_SIGNED_NODE_ORIGIN")
    return value


def _body(reply: Reply, target: str, origin: str) -> dict:
    if (not isinstance(reply, Reply) or type(reply.status) is not int
            or not isinstance(reply.body, bytes)
            or len(reply.body) > 8192 or not reply.tls_verified
            or reply.redirected or reply.origin != origin
            or reply.target != target):
        raise Hold("UNVERIFIED_TLS_OR_RESPONSE_TARGET")
    try:
        record = json.loads(reply.body)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise Hold("MALFORMED_SIGNED_NODE_RESPONSE") from exc
    if not isinstance(record, dict):
        raise Hold("UNRECOGNIZED_SIGNED_NODE_RESPONSE")
    return record


class MockOnlySignedRuntimeVerifier:
    """Independent read-only probe: never accepts a self-asserted 'signed' bit.

    A future production adapter must own real HTTPS certificate validation,
    redirect/proxy settings, credentials, timeout and response provenance.
    The injected transport is intentionally suitable ONLY for CI fixtures.
    """

    def __init__(self, *, node_id: str, secret: bytes, origin: str,
                 approved_origin: str, signer, transport):
        if not isinstance(node_id, str) or not NODE_ID.fullmatch(node_id):
            raise Hold("UNTRUSTED_PAIRED_NODE_ID")
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise Hold("PAIRED_HMAC_SECRET_UNAVAILABLE")
        if not callable(signer) or not callable(transport):
            raise Hold("INCOMPLETE_SIGNED_RUNTIME_ADAPTER")
        self.node_id = node_id
        self.secret = secret
        self.origin = _origin(origin)
        if self.origin != _origin(approved_origin):
            raise Hold("UNAPPROVED_SIGNED_NODE_ORIGIN")
        self.signer = signer
        self.transport = transport

    def _request(self, target, headers):
        if target not in TARGETS:
            raise Hold("UNAPPROVED_AGENT_TARGET")
        # Never auto-follow redirects or downgrade TLS, even in the fake API.
        try:
            reply = self.transport(
                origin=self.origin, target=target, method="GET", body=b"",
                headers=dict(headers), verify_tls=True,
                allow_redirects=False)
        except Exception as exc:
            raise Hold("SIGNED_NODE_TRANSPORT_UNAVAILABLE") from exc
        if not isinstance(reply, Reply):
            raise Hold("UNVERIFIED_TLS_OR_RESPONSE_TARGET")
        return reply

    def _require_code(self, target, headers, expected):
        reply = self._request(target, headers)
        if (not reply.tls_verified or reply.redirected
                or reply.origin != self.origin or reply.target != target):
            raise Hold("UNVERIFIED_TLS_OR_RESPONSE_TARGET")
        if type(reply.status) is not int or reply.status != expected:
            raise Hold("SIGNED_NODE_AUTH_POLICY_FAILED")
        if expected != 200:
            # Reject unexpected bodies from negative authentication tests.
            if not isinstance(reply.body, bytes) or len(reply.body) > 8192:
                raise Hold("UNRECOGNIZED_AUTH_REJECTION")
            return None
        return _body(reply, target, self.origin)

    def _headers(self, target, now):
        try:
            headers = self.signer(
                secret=self.secret, node_id=self.node_id,
                method="GET", target=target, body=b"",
                timestamp=now, nonce=secrets.token_hex(16))
        except Exception as exc:
            raise Hold("REVIEWED_SIGNER_UNAVAILABLE") from exc
        expected = {"X-Smite-Node-ID", "X-Smite-Timestamp",
                    "X-Smite-Nonce", "X-Smite-Signature"}
        if (not isinstance(headers, dict) or set(headers) != expected
                or headers["X-Smite-Node-ID"] != self.node_id
                or headers["X-Smite-Timestamp"] != str(now)
                or not HEX_NONCE.fullmatch(headers["X-Smite-Nonce"])
                or not re.fullmatch(r"[a-f0-9]{64}", headers["X-Smite-Signature"])):
            raise Hold("SIGNED_REQUEST_ENVELOPE_INVALID")
        return headers

    def check(self, expected_engines: dict[str, str], *,
              expected_active_tunnels: int = 0, now: int | None = None):
        if (not isinstance(expected_engines, dict)
                or set(expected_engines) != EXPECTED_ENGINES
                or any(state not in STATES for state in expected_engines.values())
                or type(expected_active_tunnels) is not int
                or expected_active_tunnels != 0):
            raise Hold("UNREVIEWED_EXPECTED_RUNTIME")
        now = int(time.time()) if now is None else now
        if type(now) is not int or now <= 0:
            raise Hold("UNTRUSTED_PROBE_CLOCK")
        # Strict guard MUST reject unsigned access. A 200 is never sufficient.
        self._require_code(TARGETS[0], {}, 401)
        signed = self._headers(TARGETS[0], now)
        status = self._require_code(TARGETS[0], signed, 200)
        if (set(status) != {"status", "active_tunnels", "tunnels"}
                or status["status"] != "ok"
                or type(status["active_tunnels"]) is not int
                or status["active_tunnels"] != expected_active_tunnels
                or status["tunnels"] != []):
            raise Hold("UNEXPECTED_SIGNED_NODE_STATUS")
        # Replay of the identical timestamp, nonce, target and HMAC must fail.
        self._require_code(TARGETS[0], signed, 401)
        # A different valid nonce must still work after replay rejection.
        again = self._headers(TARGETS[0], now)
        if again["X-Smite-Nonce"] == signed["X-Smite-Nonce"]:
            raise Hold("NONCE_COLLISION")
        second = self._require_code(TARGETS[0], again, 200)
        if second != status:
            raise Hold("UNSTABLE_SIGNED_NODE_STATUS")
        # Wrong secret must NOT be accepted, even though target is read-only.
        wrong = bytearray(self.secret)
        wrong[0] ^= 0xFF
        try:
            bogus = self.signer(
                secret=bytes(wrong), node_id=self.node_id,
                method="GET", target=TARGETS[0], body=b"",
                timestamp=now, nonce=secrets.token_hex(16))
        except Exception as exc:
            raise Hold("REVIEWED_SIGNER_UNAVAILABLE") from exc
        self._require_code(TARGETS[0], bogus, 401)
        inventory = self._require_code(
            TARGETS[1], self._headers(TARGETS[1], now), 200)
        if (set(inventory) != {"mode", "engines"}
                or inventory["mode"] != "managed"
                or not isinstance(inventory["engines"], dict)
                or set(inventory["engines"]) != EXPECTED_ENGINES
                or inventory["engines"] != expected_engines):
            raise Hold("SIGNED_ENGINE_INVENTORY_MISMATCH")
        return {
            "RESULT": "SIGNED_HMAC_AND_REPLAY_SIMULATION_PASS",
            "NODE_IDENTITY_SOURCE": "REVIEWED_PAIRED_KEY_AND_PINNED_MOCK_ORIGIN",
            "INVENTORY_MATCH": "YES",
            "REAL_TLS_443": "NOT_TESTED",
            "REAL_NODE_RESTART": "NOT_TESTED",
            "INSTALL_ALLOWED": "NO",
            "ACTIVATION_GATE": "HOLD",
        }
