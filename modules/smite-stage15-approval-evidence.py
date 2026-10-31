#!/usr/bin/env python3
"""Fail-closed, root-side Stage15 approval evidence verifier (offline only).

This is NOT a Panel endpoint and NEVER installs a grant. The IR and KH Node
keys are distinct from the Panel signing key and from the Root broker key.
The dedicated read-only attestation protocol must be provisioned separately:
until both independently pinned Node public keys and all three fresh proofs
exist, approval is impossible. No network, service, port or FRP mutation.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from typing import Any

AUDIENCE = "u-opti:stage15:root-review-evidence:v1"
HEX = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
PATH = re.compile(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z")
REQUIRED = {"ir_node", "kh_node", "owner", "child", "lease", "port",
            "path", "owner_proof_sha256", "kh_inventory_sha256"}
MAX_AGE = 45
MAX_SIZE = 4096


class EvidenceHold(ValueError):
    pass


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def sha256(obj: object) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def _b64(s: str) -> bytes:
    if type(s) is not str or not 0 < len(s) <= 256 or not re.fullmatch(r"[A-Za-z0-9_-]+", s):
        raise EvidenceHold("INVALID_EVIDENCE_SIGNATURE")
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise EvidenceHold("INVALID_EVIDENCE_SIGNATURE") from exc


def check_binding(binding: dict[str, Any]) -> None:
    if type(binding) is not dict or set(binding) != REQUIRED:
        raise EvidenceHold("BINDING_SCHEMA_MISMATCH")
    for key in ("ir_node", "kh_node", "owner", "child", "lease"):
        if type(binding[key]) is not str or not IDENT.fullmatch(binding[key]):
            raise EvidenceHold("BINDING_IDENTITY_INVALID")
    if (type(binding["port"]) is not int or not 1024 <= binding["port"] <= 65535
            or binding["port"] == 7000 or type(binding["path"]) is not str
            or len(binding["path"]) > 128 or not PATH.fullmatch(binding["path"])):
        raise EvidenceHold("BINDING_ROUTE_INVALID")
    if binding["path"].split("/")[1].lower() in {
        "api", "auth", "admin", "assets", "docs", "health", "login",
        "metrics", "openapi", "redoc", "static", "sub", "ws",
    }:
        raise EvidenceHold("RESERVED_XHTTP_PATH")
    for key in ("owner_proof_sha256", "kh_inventory_sha256"):
        if type(binding[key]) is not str or not HEX.fullmatch(binding[key]):
            raise EvidenceHold("BINDING_DIGEST_INVALID")


def _proof(proof: object, *, kind: str, node: str,
           public_key: bytes, now: int, used_nonces: set[str]) -> dict:
    if (type(proof) is not dict or set(proof) != {
        "schema", "audience", "kind", "node", "issued_at", "expires_at",
        "nonce", "facts", "signature"
    } or len(canonical(proof)) > MAX_SIZE):
        raise EvidenceHold("ATTESTATION_SCHEMA_INVALID")
    if (type(proof["schema"]) is not int or proof["schema"] != 1
            or proof["audience"] != AUDIENCE or proof["kind"] != kind
            or proof["node"] != node or type(proof["nonce"]) is not str
            or not re.fullmatch(r"[0-9a-f]{32}", proof["nonce"])
            or type(proof["issued_at"]) is not int
            or type(proof["expires_at"]) is not int
            or not 0 < proof["expires_at"] - proof["issued_at"] <= MAX_AGE
            or proof["issued_at"] > now + 5 or proof["expires_at"] < now
            or proof["nonce"] in used_nonces or type(proof["facts"]) is not dict):
        raise EvidenceHold("ATTESTATION_EXPIRED_OR_REPLAYED")
    if type(public_key) is not bytes or len(public_key) != 32:
        raise EvidenceHold("INDEPENDENT_NODE_PIN_REQUIRED")
    signature = _b64(proof["signature"])
    if len(signature) != 64:
        raise EvidenceHold("ATTESTATION_SIGNATURE_INVALID")
    payload = {k: v for k, v in proof.items() if k != "signature"}
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, canonical(payload))
    except (ImportError, ValueError, TypeError) as exc:
        raise EvidenceHold("INDEPENDENT_SIGNATURE_VERIFIER_UNAVAILABLE") from exc
    except Exception as exc:
        raise EvidenceHold("ATTESTATION_SIGNATURE_INVALID") from exc
    used_nonces.add(proof["nonce"])
    return proof["facts"]


def verify_bundle(bundle: object, binding: dict[str, Any], *,
                  ir_public_key: bytes, kh_public_key: bytes,
                  lease_public_key: bytes | None = None,
                  now: int | None = None,
                  consumed_nonces: frozenset[str] = frozenset()) -> frozenset[str]:
    """Verify three fresh Node-signed attestations, never Panel declarations.

    The separate IR lease attestation must be produced from the live IR
    reconciled lease/FRPS state, not from a Panel POST. Caller must durably
    commit the returned attestation nonces before grant issuance. This function
    deliberately has no state mutation or grant side effects.
    """
    now = int(time.time()) if now is None else now
    if (type(now) is not int or type(consumed_nonces) is not frozenset
            or type(bundle) is not dict or set(bundle) != {"ir_owner", "ir_lease", "kh_inbound"}):
        raise EvidenceHold("UNTRUSTED_REVIEW_CONTEXT")
    check_binding(binding)
    used = set(consumed_nonces)
    owner = _proof(bundle["ir_owner"], kind="frps_owner", node=binding["ir_node"],
                   public_key=ir_public_key, now=now, used_nonces=used)
    inbound = _proof(bundle["kh_inbound"], kind="xhttp_inbound", node=binding["kh_node"],
                     public_key=kh_public_key, now=now, used_nonces=used)
    lease = _proof(bundle["ir_lease"], kind="active_lease", node=binding["ir_node"],
                   public_key=lease_public_key if lease_public_key is not None else ir_public_key,
                   now=now, used_nonces=used)
    expected_owner = {"tunnel_id": binding["owner"], "control_port": 7000,
                      "proxy_port": binding["port"]}
    expected_inbound = {"port": binding["port"], "listen": "127.0.0.1",
                        "protocol": "vless", "network": "xhttp",
                        "path": binding["path"], "enabled": True}
    expected_lease = {
        "ir_node": binding["ir_node"], "kh_node": binding["kh_node"],
        "owner": binding["owner"], "child": binding["child"],
        "lease": binding["lease"], "port": binding["port"],
        "role": "direct" if binding["owner"] == binding["child"] else "shared",
        "state": "active", "unique": True, "owner_count": 1,
        "proxy_port_count": 1,
    }
    if (owner != expected_owner or inbound != expected_inbound
            or lease != expected_lease or sha256(owner) != binding["owner_proof_sha256"]
            or sha256(inbound) != binding["kh_inventory_sha256"]):
        raise EvidenceHold("SIGNED_RUNTIME_OR_LEASE_DRIFT")
    return frozenset(used - set(consumed_nonces))
