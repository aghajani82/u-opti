#!/usr/bin/env python3
"""Independent Backhaul/FRP real-host admission report (READ ONLY, HOLD).

A preview for operators and installers, not an install authorization.
Reads only a small allowlisted Core profile, original Compose, trusted
engine inventory, Docker inspect and persistent tunnel *presence*.
Never reads or prints auth secrets, contacts providers, opens ports,
executes Docker Compose or changes a VPS. No snapshot/443 proof exists.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

MOD = Path(__file__).resolve().parent
ENGINES = ("backhaul", "frp")
SAFE_REASON = re.compile(r"^[A-Z0-9_]{1,90}$")


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, MOD / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("MISSING_REVIEWED_GATE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


host = load("managed_engine_common_host", "smite-managed-backhaul-host-gate.py")
backhaul = load("managed_engine_bh_review", "smite-managed-backhaul-control.py")
frp = load("managed_engine_frp_review", "smite-managed-frp-control.py")


class Hold(ValueError):
    pass


def local_state(engine: str, node: Path) -> dict[str, str]:
    """Do not trust inspect metadata to claim API readiness."""
    if engine not in ENGINES:
        raise Hold("UNKNOWN_ENGINE")
    try:
        state = backhaul.inspect(node) if engine == "backhaul" else frp.inspect(node)
    except (OSError, ValueError, UnicodeError, RuntimeError):
        return {"state": "UNAVAILABLE", "reason": "ENGINE_LOCAL_REVIEW_FAILED"}
    if not isinstance(state, dict) or state.get("state") not in (
            "NOT_INSTALLED", "UNAVAILABLE", "ENROLLED_UNVERIFIED"):
        return {"state": "UNAVAILABLE", "reason": "ENGINE_LOCAL_REVIEW_FAILED"}
    reason = state.get("reason", "")
    if not isinstance(reason, str) or not SAFE_REASON.fullmatch(reason):
        reason = "ENGINE_LOCAL_REVIEW_FAILED"
    return {"state": state["state"], "reason": reason}


def report(engine: str, node: Path, *, runtime: dict | None = None,
           min_bytes: int = host.MIN_FREE_BYTES) -> dict[str, str]:
    if engine not in ENGINES:
        raise Hold("UNKNOWN_ENGINE")
    other = "frp" if engine == "backhaul" else "backhaul"
    output = {
        "ENGINE": engine.upper(),
        "NODE_ROLE": "UNVERIFIED",
        "CORE_PROFILE": "UNVERIFIED",
        "NODE_CONTAINER": "UNVERIFIED",
        "PERSISTENT_STORAGE": "UNVERIFIED",
        "SAVED_TUNNELS": "UNKNOWN",
        "TARGET_ENGINE": "UNVERIFIED",
        "OTHER_ENGINE": "UNVERIFIED",
        "OTHER_ENGINE_ACTION": "NEVER_MODIFY",
        "SNAPSHOT_RESTORE": "UNVERIFIED",
        "EMERGENCY_CONSOLE": "UNVERIFIED",
        "SIGNED_NODE_HEALTH_AND_REPLAY": "UNVERIFIED",
        "TLS_443_AND_FIREWALL": "UNVERIFIED",
        "HOST_TRANSACTION_AND_ROLLBACK": "NOT_IMPLEMENTED",
        "PUBLIC_PORT_CHANGE": "NONE_REQUESTED",
        "TUNNEL_PORT_OR_PATH_REQUIRED": "NO",
        "INSTALL_ALLOWED": "NO",
        "ACTIVATION_GATE": "HOLD",
    }
    try:
        evidence = host.audit(node, runtime=runtime, min_bytes=min_bytes)
        output["NODE_ROLE"] = evidence.get("NODE_ROLE", "UNVERIFIED")
        output["CORE_PROFILE"] = evidence.get("LOCAL_CORE", "UNVERIFIED")
        output["NODE_CONTAINER"] = evidence.get("DOCKER_NODE", "UNVERIFIED")
        output["PERSISTENT_STORAGE"] = evidence.get("PERSISTENT_DATA", "UNVERIFIED")
        output["SAVED_TUNNELS"] = evidence.get("PERSISTED_TUNNELS", "UNKNOWN")
        if evidence.get("HOST_PREFLIGHT") != "PASS_LOCAL_ONLY_INCOMPLETE":
            output["REASON"] = evidence.get("HOLD_REASON") or (
                "SAVED_TUNNELS_PRESENT" if
                evidence.get("HOST_PREFLIGHT") == "HOLD_EXISTING_TUNNELS"
                else "HOST_PREFLIGHT_INCOMPLETE"
            )
            return output
        if evidence.get("IMAGE_REFERENCE_CLASS") != "REVIEWED_DIGEST_UNATTESTED":
            output["REASON"] = "NODE_IMAGE_NOT_DIGEST_PINNED"
            return output
        original = host._local_file(
            node / "docker-compose.yml", max_bytes=131072, require_root=True)
        first_hash = hashlib.sha256(original).hexdigest()
        if first_hash != evidence.get("COMPOSE_SHA256"):
            output["REASON"] = "COMPOSE_CHANGED_DURING_REVIEW"
            return output
        # Local engine inspectors only read files. No shell execution.
        first = local_state(engine, node)
        second = local_state(other, node)
        output["TARGET_ENGINE"] = first["state"]
        output["OTHER_ENGINE"] = second["state"]
        if hashlib.sha256(host._local_file(
                node / "docker-compose.yml", max_bytes=131072,
                require_root=True)).hexdigest() != first_hash:
            output["REASON"] = "COMPOSE_CHANGED_DURING_REVIEW"
        elif first["state"] != "NOT_INSTALLED":
            output["REASON"] = (
                "TARGET_ENGINE_ALREADY_PRESENT" if
                first["state"] == "ENROLLED_UNVERIFIED" else
                "TARGET_ENGINE_INCOMPLETE")
        elif second["state"] == "UNAVAILABLE":
            output["REASON"] = "OTHER_ENGINE_INCOMPLETE"
        elif second["state"] == "ENROLLED_UNVERIFIED":
            output["REASON"] = "OTHER_ENGINE_SIGNED_STATUS_REQUIRED"
        else:
            output["LOCAL_PREFLIGHT"] = "PASS_LOCAL_ONLY_INCOMPLETE"
            output["REASON"] = "SNAPSHOT_SIGNED_NODE_AND_HOST_EXECUTOR_UNVERIFIED"
    except (host.GateHold, Hold, OSError, ValueError, UnicodeError):
        output["REASON"] = "UNTRUSTED_LOCAL_STATE"
    # Never set INSTALL_ALLOWED or ACTIVATION_GATE to success: a server-side
    # signed health probe, independent snapshot proof, journaled recovery
    # and explicit operator approval are required in a DIFFERENT workflow.
    return output


def main() -> int:
    p = argparse.ArgumentParser(
        description="Backhaul/FRP standalone host admission, ALWAYS read-only HOLD")
    p.add_argument("--engine", choices=ENGINES, required=True)
    p.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args()
    result = report(args.engine, args.node_dir)
    if args.format == "json":
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        for key, value in result.items():
            print(f"{key}={value}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
