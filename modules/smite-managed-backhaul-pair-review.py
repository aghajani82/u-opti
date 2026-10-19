#!/usr/bin/env python3
"""Compare two redacted, *untrusted* IR/KH host-admission reports offline.

The reports are NOT signed remote attestation or proof of a cloud snapshot.
Even clean reports NEVER grant install privileges. No SSH, network, shell,
Docker or file writes. Never echo input report strings or exceptions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import stat
import sys

MAX_REPORT = 8192
SAFE_SHA = re.compile(r"^[0-9a-f]{64}$")
SAFE_REASON = re.compile(r"^[A-Z0-9_]{1,96}$")
REQUIRED = {
    "NODE_ROLE", "LOCAL_CORE", "DOCKER_NODE", "PERSISTENT_DATA",
    "PERSISTED_TUNNELS", "DISK_SPACE", "ENGINE",
    "FRP_INSTALL_REQUIRED", "NEW_PUBLIC_PORTS",
    "SNAPSHOT_AND_CONSOLE", "SIGNED_NODE_POST_RESTART",
    "PAIRING_AND_REPLAY_PRESERVATION", "NGINX_443_AND_FIREWALL_EXPOSURE",
    "TUNNEL_RECOVERY_AFTER_RESTART", "HOST_INSTALL_AUTHORIZED",
    "HOST_PREFLIGHT", "BACKHAUL_ACTIVATION_GATE",
}
OPTIONAL = {"HOLD_REASON", "COMPOSE_SHA256", "IMAGE_REFERENCE_CLASS"}
NO_PROOF = "UNVERIFIED_MANUAL_OR_SEPARATE_SIGNED_TEST"


class Hold(ValueError):
    pass


def read_report(path: Path) -> dict:
    # Exact file contents never appear in exception or output.
    if path.is_symlink():
        raise Hold("REPORT_SYMLINK")
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_REPORT:
            raise Hold("INVALID_REPORT_FILE")
        report = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Hold("REPORT_UNREADABLE") from exc
    if not isinstance(report, dict) or not REQUIRED.issubset(report):
        raise Hold("INVALID_REPORT_SCHEMA")
    if not set(report).issubset(REQUIRED | OPTIONAL):
        raise Hold("UNEXPECTED_REPORT_FIELDS")
    if (not all(isinstance(x, str) and len(x) <= 128 for x in report.values())
            or report["NODE_ROLE"] not in {"IR", "KH"}
            or report["HOST_INSTALL_AUTHORIZED"] != "NO"
            or report["BACKHAUL_ACTIVATION_GATE"] != "HOLD"
            or report["ENGINE"] != "BACKHAUL_ONLY"
            or report["FRP_INSTALL_REQUIRED"] != "NO"
            or report["NEW_PUBLIC_PORTS"] != "NONE_PLANNED"):
        raise Hold("INVALID_REPORT_VALUES")
    for field in (
        "SNAPSHOT_AND_CONSOLE", "SIGNED_NODE_POST_RESTART",
        "PAIRING_AND_REPLAY_PRESERVATION", "NGINX_443_AND_FIREWALL_EXPOSURE",
        "TUNNEL_RECOVERY_AFTER_RESTART",
    ):
        if report[field] != NO_PROOF:
            # Reject spoofed snapshot/443 approval until a distinct trusted
            # attestation and two-host verification mechanism is reviewed.
            raise Hold("UNTRUSTED_APPROVAL_CLAIM")
    if ("COMPOSE_SHA256" in report and
            SAFE_SHA.fullmatch(report["COMPOSE_SHA256"]) is None):
        raise Hold("INVALID_COMPOSE_HASH")
    if ("HOLD_REASON" in report and
            SAFE_REASON.fullmatch(report["HOLD_REASON"]) is None):
        raise Hold("INVALID_HOLD_REASON")
    if report["HOST_PREFLIGHT"] not in (
            "PASS_LOCAL_ONLY_INCOMPLETE", "HOLD_EXISTING_TUNNELS", "HOLD"):
        raise Hold("UNKNOWN_HOST_PREFLIGHT")
    return report


def compare(ir: dict, kh: dict) -> dict[str, str]:
    if ir["NODE_ROLE"] != "IR" or kh["NODE_ROLE"] != "KH":
        raise Hold("WRONG_NODE_PAIR_ROLES")

    def local_ok(report: dict) -> bool:
        return all((
            report["HOST_PREFLIGHT"] == "PASS_LOCAL_ONLY_INCOMPLETE",
            report["LOCAL_CORE"] == "MANAGED_STRICT",
            report["DOCKER_NODE"] == "RUNNING_REVIEWED_IMAGE",
            report["PERSISTENT_DATA"] == "LOCAL_NAMED_VOLUME_CONFIRMED",
            report["PERSISTED_TUNNELS"] == "ZERO",
            report["DISK_SPACE"] == "MINIMUM_AVAILABLE",
            report.get("IMAGE_REFERENCE_CLASS") == "REVIEWED_DIGEST_UNATTESTED",
            SAFE_SHA.fullmatch(report.get("COMPOSE_SHA256", "")) is not None,
        ))

    ir_good = local_ok(ir)
    kh_good = local_ok(kh)
    if any(x["PERSISTED_TUNNELS"] == "EXISTING_DO_NOT_RESTART"
           for x in (ir, kh)):
        reason = "EXISTING_TUNNELS_NO_RESTART"
    elif not (ir_good and kh_good):
        reason = "LOCAL_EVIDENCE_INCOMPLETE"
    else:
        reason = "SNAPSHOT_CONSOLE_AND_SIGNED_443_UNVERIFIED"
    return {
        "IR_LOCAL_PREFLIGHT": "PASS_LOCAL_ONLY" if ir_good else "HOLD",
        "KH_LOCAL_PREFLIGHT": "PASS_LOCAL_ONLY" if kh_good else "HOLD",
        "ROLE_PAIRING": "IR_AND_KH_REPORTED",
        "REPORT_TRUST": "USER_SUPPLIED_UNAUTHENTICATED",
        "CLOUD_SNAPSHOT_RESTORE": "UNVERIFIED",
        "EMERGENCY_CONSOLE_ACCESS": "UNVERIFIED",
        "SIGNED_PANEL_NODE_PAIRING": "UNVERIFIED",
        "TLS_443_AND_FIREWALL": "UNVERIFIED",
        "EXISTING_TUNNEL_CONTINUITY": "UNVERIFIED",
        "NEXT": reason,
        "HOST_INSTALL_AUTHORIZED": "NO",
        "BACKHAUL_ACTIVATION_GATE": "HOLD",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Backhaul IR/KH offline preflight comparison only")
    p.add_argument("--ir-report", required=True, type=Path)
    p.add_argument("--kh-report", required=True, type=Path)
    args = p.parse_args()
    try:
        result = compare(read_report(args.ir_report), read_report(args.kh_report))
        for key, value in result.items():
            print(f"{key}={value}")
    except Hold as exc:
        reason = str(exc)
        print(f"PAIR_CHECK=HOLD_{reason}", file=sys.stderr)
        print("HOST_INSTALL_AUTHORIZED=NO")
        print("BACKHAUL_ACTIVATION_GATE=HOLD")
    # Deliberately always nonzero: an offline comparison never approves
    # changes on the real servers.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
