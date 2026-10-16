#!/usr/bin/env python3
"""Pure offline, conservative host-port inventory audit for Sidecar design.

Accepts an explicitly provided JSON snapshot (NOT a live scanner). Nothing
is installed, started, stopped, or changed. A PASS is NOT activation approval.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path

REQUIRED = {
    "ir": {(443, "nginx"), (8443, "nginx"), (7000, "frps")},
    "kh": {(56053, "xray")},
}
NEW_LISTENERS = {"ir": (3080, 56053), "kh": (13080,)}
REQUIRED_LOOPBACK = {
    "ir": {(8443, "nginx"), (7000, "frps")},
    "kh": {(56053, "xray")},
}


class AuditError(ValueError):
    pass


def positive_port(port: object) -> int:
    if type(port) is not int or not (1 <= port <= 65535):
        raise AuditError("Invalid listener port")
    return port


def normalize_inventory(snapshot: object, role: str) -> list[dict]:
    if role not in REQUIRED:
        raise AuditError("Role must be ir or kh")
    if not isinstance(snapshot, dict):
        raise AuditError("Inventory must be JSON object")
    if snapshot.get("role") != role or snapshot.get("network_mode") != "host":
        raise AuditError("Role/network_mode mismatch; host networking required")
    listeners = snapshot.get("listeners")
    if not isinstance(listeners, list) or not listeners:
        raise AuditError("Missing listener inventory")
    valid = []
    for item in listeners:
        if not isinstance(item, dict):
            raise AuditError("Malformed listener")
        if set(item) != {"address", "port", "owner"}:
            raise AuditError("Listener requires address, port and owner only")
        try:
            addr = ipaddress.ip_address(item["address"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuditError("Invalid listener address") from exc
        port = positive_port(item["port"])
        owner = item["owner"]
        if not isinstance(owner, str) or not owner or len(owner) > 64:
            raise AuditError("Invalid listener owner")
        valid.append({"address": addr, "port": port, "owner": owner})
    if len(set((x["address"], x["port"], x["owner"]) for x in valid)) != len(valid):
        raise AuditError("Duplicate listener entries; inventory ambiguous")
    return valid


def audit(snapshot: object, role: str) -> list[str]:
    listeners = normalize_inventory(snapshot, role)
    findings = []
    # Conservative: any owner on a planned new port blocks, even if another
    # interface or IPv6 family might technically allow binding loopback.
    # Inventory cannot prove exclusive host-port ownership by itself.
    for port in NEW_LISTENERS[role]:
        conflicting = [x for x in listeners if x["port"] == port]
        if conflicting:
            findings.append(f"BLOCK: planned port {port} already has {len(conflicting)} listener(s)")
        else:
            findings.append(f"PASS: planned port {port} has no listener in snapshot")
    for port, owner in sorted(REQUIRED[role]):
        matching = [x for x in listeners if x["port"] == port and x["owner"] == owner]
        if not matching:
            findings.append(f"BLOCK: existing {owner} port {port} missing")
        elif (port, owner) in REQUIRED_LOOPBACK[role] and not any(
            x["address"] == ipaddress.ip_address("127.0.0.1") for x in matching
        ):
            findings.append(f"BLOCK: existing {owner} port {port} not bound on IPv4 loopback")
        else:
            findings.append(f"PASS: existing {owner} port {port} observed")
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("ir", "kh"), required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    try:
        # Limit file size to avoid loading arbitrary large inventories.
        with args.snapshot.open("rb") as inp:
            raw = inp.read(65537)
        if len(raw) > 65536:
            raise AuditError("Inventory file too large")
        data = json.loads(raw)
        findings = audit(data, args.role)
    except (AuditError, OSError, ValueError) as exc:
        parser.error(f"FAIL CLOSED: {type(exc).__name__}")
    print("OFFLINE SNAPSHOT REVIEW (NOT LIVE HOST STATUS)")
    for item in findings:
        print(item)
    if any(item.startswith("BLOCK:") for item in findings):
        raise SystemExit(1)
    print("PORT SNAPSHOT CHECK PASS; NOT AUTHORIZATION TO DEPLOY")


if __name__ == "__main__":
    main()
