#!/usr/bin/env python3
"""Offline-only host-origin Ed25519 evidence protocol prototype.

Distinct audience, roles, signature pins and kinds from Node attestation.
This module has NO runtime collector, NO HTTP/UDS server, NO durable nonce
ledger, NO approval grant/publish and NO production integration. Successful
verification DOES NOT permit a live approval. See no-restart boundary doc.
"""
from __future__ import annotations

import base64
import json
import re
import time

AUDIENCE = "u-opti:stage15:host-review-evidence:offline-v1"
ROLES = {"ir_host": "host_frps_owner", "kh_host": "host_xhttp_inbound"}
IDENT = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
NONCE = re.compile(r"[0-9a-f]{32}\Z")
ROUTE = re.compile(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z")
RESERVED = {"admin", "api", "assets", "auth", "docs", "health",
            "login", "metrics", "openapi", "redoc", "static", "sub", "ws"}
MAX_PROOF_BYTES = 4096


class HostEvidenceHold(ValueError):
    pass


def ensure(value: bool, code: str) -> None:
    if not value:
        raise HostEvidenceHold(code)


def canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise HostEvidenceHold("UNTRUSTED_PROOF_DATA") from exc


def _binding(value: dict) -> None:
    ensure(type(value) is dict and set(value) == {
        "ir_node", "kh_node", "owner", "child", "lease", "port", "path"},
        "UNTRUSTED_HOST_BINDING")
    for name in ("ir_node", "kh_node", "owner", "child", "lease"):
        ensure(type(value[name]) is str and bool(IDENT.fullmatch(value[name])),
               "UNTRUSTED_HOST_BINDING")
    ensure(type(value["port"]) is int and 1024 <= value["port"] <= 65535
           and value["port"] != 7000, "UNTRUSTED_HOST_PORT")
    path = value["path"]
    ensure(type(path) is str and len(path) <= 128
           and bool(ROUTE.fullmatch(path))
           and path.split("/")[1].lower() not in RESERVED,
           "UNTRUSTED_HOST_PATH")
    ensure((value["owner"] == value["child"]) ==
           (value["lease"] == value["owner"]), "HOST_LEASE_ROLE_DRIFT")


def _facts(role: str, facts: dict) -> None:
    ensure(type(facts) is dict, "UNTRUSTED_HOST_FACTS")
    if role == "ir_host":
        required = {"node", "tunnel_id", "control_port", "proxy_port",
                    "owner_pid", "owner_start_ticks", "node_container_id",
                    "registry_sha256", "listener_ports"}
        ensure(set(facts) == required, "IR_HOST_FACTS_SCHEMA_MISMATCH")
        ensure(type(facts["tunnel_id"]) is str
               and bool(IDENT.fullmatch(facts["tunnel_id"]))
               and facts["control_port"] == 7000
               and type(facts["control_port"]) is int
               and type(facts["proxy_port"]) is int
               and 1024 <= facts["proxy_port"] <= 65535
               and facts["proxy_port"] != 7000,
               "IR_HOST_FACTS_INVALID")
        ports = facts["listener_ports"]
        ensure(type(ports) is list and len(ports) >= 2 and len(ports) <= 32
               and all(type(p) is int and 1 <= p <= 65535 for p in ports)
               and sorted(set(ports)) == ports
               and 7000 in ports and facts["proxy_port"] in ports,
               "IR_HOST_LISTENERS_INVALID")
        for key in ("node_container_id", "registry_sha256"):
            ensure(type(facts[key]) is str and bool(HEX64.fullmatch(facts[key])),
                   "IR_HOST_PROVENANCE_UNTRUSTED")
        for key in ("owner_pid", "owner_start_ticks"):
            ensure(type(facts[key]) is int and 0 < facts[key] < 2**63,
                   "IR_HOST_GENERATION_UNTRUSTED")
    elif role == "kh_host":
        required = {"node", "port", "listen", "protocol", "network", "path",
                    "enabled", "xray_pid", "xray_start_ticks",
                    "sanaei_container_id", "db_view_sha256", "frpc_count"}
        ensure(set(facts) == required, "KH_HOST_FACTS_SCHEMA_MISMATCH")
        ensure(type(facts["port"]) is int and 1024 <= facts["port"] <= 65535
               and facts["port"] != 7000 and facts["listen"] == "127.0.0.1"
               and facts["protocol"] == "vless" and facts["network"] == "xhttp"
               and facts["enabled"] is True
               and type(facts["path"]) is str
               and len(facts["path"]) <= 128
               and bool(ROUTE.fullmatch(facts["path"]))
               and facts["path"].split("/")[1].lower() not in RESERVED,
               "KH_HOST_INBOUND_INVALID")
        for key in ("sanaei_container_id", "db_view_sha256"):
            ensure(type(facts[key]) is str and bool(HEX64.fullmatch(facts[key])),
                   "KH_HOST_PROVENANCE_UNTRUSTED")
        for key in ("xray_pid", "xray_start_ticks"):
            ensure(type(facts[key]) is int and 0 < facts[key] < 2**63,
                   "KH_HOST_GENERATION_UNTRUSTED")
        ensure(type(facts["frpc_count"]) is int
               and facts["frpc_count"] == 3, "KH_HOST_FRPC_DRIFT")
    else:
        raise HostEvidenceHold("UNKNOWN_HOST_EVIDENCE_ROLE")
    ensure(type(facts["node"]) is str and bool(IDENT.fullmatch(facts["node"])),
           "HOST_NODE_IDENTITY_UNTRUSTED")


def sign_offline_fixture(*, role: str, facts: dict, key, nonce: str, issued_at: int) -> dict:
    """Create synthetic proof ONLY for offline tests, never from live input.

    A future production signer MUST derive facts independently from kernel,
    registry, SQLite WAL and container/process generation and use a different
    reviewed protocol. This API is not an endpoint and cannot create a grant.
    """
    ensure(role in ROLES and type(nonce) is str
           and bool(NONCE.fullmatch(nonce)) and type(issued_at) is int
           and 0 <= issued_at < 2**63 - 30, "UNTRUSTED_HOST_FIXTURE_CONTEXT")
    _facts(role, facts)
    proof = {"schema": 1, "audience": AUDIENCE, "role": role,
             "kind": ROLES[role], "node": facts["node"],
             "issued_at": issued_at, "expires_at": issued_at + 30,
             "nonce": nonce, "facts": facts.copy(), "provenance": "host-root"}
    try:
        raw = key.sign(canonical(proof))
    except (AttributeError, TypeError, ValueError) as exc:
        raise HostEvidenceHold("HOST_FIXTURE_SIGNER_UNAVAILABLE") from exc
    ensure(type(raw) is bytes and len(raw) == 64, "HOST_FIXTURE_SIGNER_INVALID")
    proof["signature"] = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    ensure(len(canonical(proof)) <= MAX_PROOF_BYTES, "HOST_EVIDENCE_TOO_LARGE")
    return proof


def _verify(proof: object, role: str, public: bytes, now: int, seen: set[str]) -> dict:
    ensure(type(proof) is dict and set(proof) == {
        "schema", "audience", "role", "kind", "node", "issued_at",
        "expires_at", "nonce", "facts", "provenance", "signature"
    } and len(canonical(proof)) <= MAX_PROOF_BYTES, "HOST_PROOF_SCHEMA_INVALID")
    ensure(type(proof["schema"]) is int and proof["schema"] == 1
           and proof["audience"] == AUDIENCE
           and proof["role"] == role and proof["kind"] == ROLES[role]
           and proof["provenance"] == "host-root"
           and type(proof["issued_at"]) is int
           and type(proof["expires_at"]) is int
           and proof["expires_at"] - proof["issued_at"] == 30
           and proof["issued_at"] <= now + 5
           and now <= proof["expires_at"]
           and type(proof["nonce"]) is str
           and bool(NONCE.fullmatch(proof["nonce"]))
           and proof["nonce"] not in seen,
           "HOST_PROOF_STALE_OR_REPLAYED")
    ensure(type(public) is bytes and len(public) == 32,
           "HOST_PUBLIC_PIN_REQUIRED")
    _facts(role, proof["facts"])
    ensure(proof["node"] == proof["facts"]["node"], "HOST_PROOF_NODE_MISMATCH")
    signature = proof["signature"]
    ensure(type(signature) is str and bool(re.fullmatch(r"[A-Za-z0-9_-]{86}", signature)),
           "HOST_PROOF_SIGNATURE_INVALID")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        raw = base64.urlsafe_b64decode(signature + "==")
        ensure(len(raw) == 64, "HOST_PROOF_SIGNATURE_INVALID")
        Ed25519PublicKey.from_public_bytes(public).verify(
            raw, canonical({k: v for k, v in proof.items() if k != "signature"}))
    except (ValueError, TypeError, ImportError) as exc:
        raise HostEvidenceHold("HOST_PROOF_SIGNATURE_INVALID") from exc
    except Exception as exc:
        raise HostEvidenceHold("HOST_PROOF_SIGNATURE_INVALID") from exc
    seen.add(proof["nonce"])
    return proof["facts"]


def verify_offline_pair(*, pair: dict, binding: dict,
                        ir_host_public: bytes, kh_host_public: bytes,
                        consumed_nonces: frozenset[str] = frozenset(),
                        now: int | None = None) -> frozenset[str]:
    """OFFLINE ONLY. Returned nonces must NOT be treated as durable receipts.

    The existing Node attestation verifier is deliberately NOT extended here.
    No live approval, real attestation or runtime eligibility is established.
    """
    now = int(time.time()) if now is None else now
    ensure(type(now) is int and type(pair) is dict
           and set(pair) == {"ir_host", "kh_host"}
           and type(consumed_nonces) is frozenset
           and all(type(n) is str and bool(NONCE.fullmatch(n))
                   for n in consumed_nonces),
           "UNTRUSTED_HOST_VERIFICATION_CONTEXT")
    _binding(binding)
    ensure(ir_host_public != kh_host_public, "HOST_PINS_NOT_INDEPENDENT")
    seen = set(consumed_nonces)
    ir = _verify(pair["ir_host"], "ir_host", ir_host_public, now, seen)
    kh = _verify(pair["kh_host"], "kh_host", kh_host_public, now, seen)
    ensure(ir["node"] == binding["ir_node"]
           and ir["tunnel_id"] == binding["owner"]
           and ir["proxy_port"] == binding["port"]
           and kh["node"] == binding["kh_node"]
           and kh["port"] == binding["port"]
           and kh["path"] == binding["path"],
           "HOST_BINDING_EVIDENCE_DRIFT")
    return frozenset(seen - set(consumed_nonces))


if __name__ == "__main__":
    raise SystemExit("OFFLINE_LIBRARY_ONLY_NO_HOST_SERVICE_OR_GRANT")
