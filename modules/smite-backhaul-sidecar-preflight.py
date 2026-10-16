#!/usr/bin/env python3
"""Offline-only, conservative Sidecar final-preflight evidence reviewer.

Does NOT read a live host, modify anything, invoke Docker/Nginx or open a
network connection. Only consumes a private JSON evidence snapshot created
separately by a reviewed READ-ONLY collector. Never constitutes authorization
to install, start, reload, stop, or merge production changes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

_MODULE = Path(__file__).resolve().with_name("smite-backhaul-sidecar-audit.py")
_spec = importlib.util.spec_from_file_location("backhaul_port_audit", _MODULE)
_port = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_port)

MAX_AGE = timedelta(minutes=15)
FUTURE_SKEW = timedelta(minutes=2)
EXPECTED = {
    "ir": (
        "nginx_config_syntax_ok",
        "smite_node_running",
        "smite_panel_running",
        "frp_controller_unchanged",
        "stream_443_nginx_owned",
        "stream_sni_and_canary_reviewed",
        "https_backend_8443_tls",
        "https_backend_vhost_reviewed",
        "include_location_collisions_excluded",
        "tls_certificate_valid",
        "sidecar_names_unallocated",
        "sidecar_files_absent",
    ),
    "kh": (
        "nginx_config_syntax_ok",
        "smite_node_running",
        "xray_56053_unchanged",
        "legacy_backhaul_clients_untouched",
        "https_ir_route_verified",
        "tls_certificate_chain_verified",
        "sidecar_names_unallocated",
        "sidecar_files_absent",
    ),
}


class PreflightRefused(ValueError):
    pass


def _read_clock(value: object, now: datetime) -> None:
    if not isinstance(value, str):
        raise PreflightRefused("Missing snapshot timestamp")
    try:
        stamped = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreflightRefused("Invalid timestamp format") from exc
    if stamped.tzinfo is None or stamped.utcoffset() is None:
        raise PreflightRefused("Timestamp must have UTC offset")
    current = now.astimezone(timezone.utc)
    age = current - stamped.astimezone(timezone.utc)
    if age > MAX_AGE or age < -FUTURE_SKEW:
        raise PreflightRefused("Evidence expired or future-dated")


def review(snapshot: object, role: str, now: datetime | None = None) -> list[str]:
    """Fail-closed offline review of user-provided evidence, never deployment."""
    if role not in EXPECTED or not isinstance(snapshot, dict):
        raise PreflightRefused("Unsupported role or input shape")
    if set(snapshot) != {"role", "observed_at", "ports", "checks", "versions", "baseline"}:
        raise PreflightRefused("Missing/unexpected evidence fields")
    if snapshot["role"] != role:
        raise PreflightRefused("Role mismatch")
    _read_clock(snapshot["observed_at"], now or datetime.now(timezone.utc))
    checks = snapshot["checks"]
    if not isinstance(checks, dict) or set(checks) != set(EXPECTED[role]):
        raise PreflightRefused("Incomplete or unexpected safety checks")
    if not isinstance(snapshot["versions"], dict) or set(snapshot["versions"]) != {
        "backhaul", "smite"
    }:
        raise PreflightRefused("Missing or unexpected version evidence")
    if snapshot["versions"]["backhaul"] != "v0.7.2" or snapshot["versions"]["smite"] != "v0.1.7":
        raise PreflightRefused("Unexpected pinned tool versions")
    baseline = snapshot["baseline"]
    if not isinstance(baseline, dict) or set(baseline) != {"legacy_clients"}:
        raise PreflightRefused("Missing baseline")
    if type(baseline["legacy_clients"]) is not int:
        raise PreflightRefused("Invalid legacy client inventory")
    if (role == "kh" and baseline["legacy_clients"] != 4) or (
        role == "ir" and baseline["legacy_clients"] != 0
    ):
        raise PreflightRefused("Legacy client baseline changed; manual review required")
    ports = snapshot["ports"]
    if not isinstance(ports, dict):
        raise PreflightRefused("Missing port inventory")
    try:
        issues = _port.audit(ports, role)
    except _port.AuditError as exc:
        raise PreflightRefused("Invalid port inventory") from exc
    if any(item.startswith("BLOCK:") for item in issues):
        raise PreflightRefused("Conflicting or missing port owner")
    for key in EXPECTED[role]:
        if checks[key] is not True:
            raise PreflightRefused("Safety evidence incomplete: " + key)
    return [
        "OFFLINE EVIDENCE SNAPSHOT PASSED STRUCTURAL REVIEW ONLY",
        f"ROLE: {role.upper()} — data age <=15 min",
        "Ports: snapshot-only inventory, not a live recheck",
        "Existing Smite, FRP, Xray and KH legacy clients remain out of scope",
        "MANUAL HOST REVIEW, PRODUCTION INSTALLER AND VERIFIED ROLLBACK STILL REQUIRED",
        "NOT AUTHORIZED TO DEPLOY OR MERGE",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=sorted(EXPECTED), required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.snapshot.is_symlink() or args.snapshot.stat().st_size > 65536:
            raise PreflightRefused("Linked or oversized evidence input")
        content = json.loads(args.snapshot.read_text(encoding="utf-8"))
        messages = review(content, args.role)
    except (OSError, ValueError) as exc:
        parser.error("FAIL CLOSED: " + str(exc))
    print("\n".join(messages))


if __name__ == "__main__":
    main()
