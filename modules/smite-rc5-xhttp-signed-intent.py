#!/usr/bin/env python3
"""Offline-only U-OPTI Smite XHTTP route-intent authentication contract.

This module DOES NOT listen on a socket, open an HTTP route, access secrets,
persist a replay nonce, write Nginx files, or execute a privileged action.

A future independently reviewed root-owned broker may call admit() only after
loading an authorized, independent TrustedGrant and a durable nonce snapshot.
Those two dependencies are NOT provided by a caller's JSON request.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from typing import Any


class IntentHold(ValueError):
    """Reject an invalid or unauthorized route intent without side effects."""


AUDIENCE = "u-opti:ir:xhttp-route:v1"
ACTION = "create"
MAX_RAW = 4096
MAX_TTL = 60
CLOCK_SKEW = 5
IDENT = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
NONCE = re.compile(r"[0-9a-f]{32}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
ROUTE = re.compile(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z")
FIELDS = frozenset({
    "schema", "audience", "action", "ir_node", "kh_node", "owner",
    "child", "lease", "port", "path", "owner_proof_sha256",
    "kh_inventory_sha256", "issued_at", "expires_at", "nonce",
})
WIRE_FIELDS = FIELDS | {"mac"}


@dataclass(frozen=True)
class TrustedGrant:
    """Independent root-owned authorization, NOT copied from request JSON.

    The broker/installer must securely provision this after independently
    verified Signed IR owner proof + Signed KH inventory + active unique lease.
    Until that independent attestation and durable replay store exist, no
    privilege may be granted even if this parser returns an authenticated ID.
    """
    ir_node: str
    kh_node: str
    owner: str
    child: str
    lease: str
    port: int
    path: str
    owner_proof_sha256: str
    kh_inventory_sha256: str


@dataclass(frozen=True)
class AuthenticatedIntent:
    ir_node: str
    kh_node: str
    owner: str
    child: str
    lease: str
    port: int
    path: str
    nonce: str
    expires_at: int


def _no_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise IntentHold("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def canonical(body: dict[str, Any]) -> bytes:
    return json.dumps(
        body, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _check_identity(data: dict[str, Any]) -> None:
    if (set(data) != FIELDS or type(data["schema"]) is not int
            or data["schema"] != 1 or data["audience"] != AUDIENCE
            or data["action"] != ACTION):
        raise IntentHold("UNSUPPORTED_INTENT_SCHEMA")
    for name in ("ir_node", "kh_node", "owner", "child", "lease"):
        if type(data[name]) is not str or not IDENT.fullmatch(data[name]):
            raise IntentHold("INVALID_ROUTE_BINDING")
    for name in ("owner_proof_sha256", "kh_inventory_sha256"):
        if type(data[name]) is not str or not HASH.fullmatch(data[name]):
            raise IntentHold("INVALID_EVIDENCE_HASH")
    if type(data["port"]) is not int or not 1024 <= data["port"] <= 65535:
        raise IntentHold("INVALID_PROXY_PORT")
    if data["port"] == 7000:
        raise IntentHold("FRPS_CONTROL_PORT_FORBIDDEN")
    route = data["path"]
    if (type(route) is not str or len(route) > 128 or not ROUTE.fullmatch(route)
            or not route.startswith(f"/{data['port']}/")):
        raise IntentHold("INVALID_XHTTP_PATH")
    if type(data["nonce"]) is not str or not NONCE.fullmatch(data["nonce"]):
        raise IntentHold("INVALID_NONCE")
    for name in ("issued_at", "expires_at"):
        if type(data[name]) is not int or not 0 <= data[name] < 2 ** 63:
            raise IntentHold("INVALID_TIMESTAMP")
    if not 1 <= data["expires_at"] - data["issued_at"] <= MAX_TTL:
        raise IntentHold("INVALID_EXPIRATION")


def admit(
    wire: bytes, *,
    key: bytes,
    expected: TrustedGrant,
    seen_nonces: frozenset[str],
    now: int,
) -> AuthenticatedIntent:
    """Validate an independently approved short-lived HMAC capability.

    This is an OFFLINE verification step only. It does NOT atomically register
    a nonce; the future broker MUST durably consume the nonce while holding
    its own privileged lock, before proceeding to any Nginx transaction.
    """
    if (type(key) is not bytes or len(key) != 32
            or type(now) is not int or now < 0
            or type(seen_nonces) is not frozenset
            or not isinstance(expected, TrustedGrant)):
        raise IntentHold("BROKER_TRUST_CONTEXT_UNAVAILABLE")
    if type(wire) is not bytes or not 0 < len(wire) <= MAX_RAW:
        raise IntentHold("INVALID_WIRE_SIZE")
    try:
        value = json.loads(
            wire.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(IntentHold("INVALID_JSON_NUMBER")),
        )
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise IntentHold("INVALID_WIRE_JSON") from exc
    if not isinstance(value, dict) or set(value) != WIRE_FIELDS:
        raise IntentHold("UNAPPROVED_WIRE_FIELDS")
    mac = value.pop("mac")
    if type(mac) is not str or not HASH.fullmatch(mac):
        raise IntentHold("INVALID_MAC")
    _check_identity(value)
    # One unique on-wire representation removes ambiguity between signers,
    # parsers and persisted audit records.
    if wire != canonical({**value, "mac": mac}):
        raise IntentHold("NON_CANONICAL_REQUEST")
    expected_mac = hmac.new(key, canonical(value), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected_mac):
        raise IntentHold("INVALID_SIGNATURE")
    if now < value["issued_at"] - CLOCK_SKEW or now > value["expires_at"]:
        raise IntentHold("EXPIRED_OR_FUTURE_INTENT")
    if value["nonce"] in seen_nonces:
        raise IntentHold("REPLAYED_INTENT")
    for name in (
        "ir_node", "kh_node", "owner", "child", "lease", "port", "path",
        "owner_proof_sha256", "kh_inventory_sha256",
    ):
        if getattr(expected, name) != value[name]:
            raise IntentHold("ROOT_APPROVAL_BINDING_MISMATCH")
    return AuthenticatedIntent(
        value["ir_node"], value["kh_node"], value["owner"], value["child"],
        value["lease"], value["port"], value["path"], value["nonce"],
        value["expires_at"],
    )
