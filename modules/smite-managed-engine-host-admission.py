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
signed_pair = load("managed_engine_signed_pair", "smite-registry-pair-admission.py")


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
           min_bytes: int = host.MIN_FREE_BYTES,
           expected_node_image: str | None = None,
           signed_pair_manifest: Path | None = None,
           signed_pair_manifest_sha256: str | None = None,
           signed_pair_source_sha: str | None = None,
           signed_pair_publish_ref: str | None = None,
           signed_pair_trusted_root: Path | None = None) -> dict[str, str]:
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
        "SAVED_TUNNEL_REGISTRY_SHA256": "UNVERIFIED",
        "NODE_CONTAINER_ID_SHA256": "UNVERIFIED",
        "TARGET_ENGINE": "UNVERIFIED",
        "OTHER_ENGINE": "UNVERIFIED",
        "OTHER_ENGINE_LOCAL_REASON": "UNVERIFIED",
        "OTHER_ENGINE_ACTION": "NEVER_MODIFY",
        "SIGNED_REGISTRY_PAIR_PROOF": "NOT_SUPPLIED",
        "NODE_RUNTIME_BYTES_AND_REPLAY": "UNVERIFIED",
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
    # A locally reported Docker image digest is NOT proof of a signed
    # release. Use the already reviewed paired-registry Cosign verifier.
    # No implicit fallback to the old RC2 candidate or a mutable tag.
    supplied = (signed_pair_manifest, signed_pair_manifest_sha256,
                signed_pair_source_sha, signed_pair_publish_ref)
    if any(value is not None for value in supplied) or signed_pair_trusted_root is not None:
        if not all(value is not None for value in supplied):
            output["REASON"] = "INCOMPLETE_SIGNED_PAIR_PROOF"
            return output
        try:
            pair_evidence = signed_pair.verify_pair(
                manifest=signed_pair_manifest,
                manifest_sha256=signed_pair_manifest_sha256,
                source_sha=signed_pair_source_sha,
                publish_ref=signed_pair_publish_ref,
                trusted_root=signed_pair_trusted_root,
            )
            signed_node = pair_evidence["images"]["node"]
            if expected_node_image is not None and expected_node_image != signed_node:
                output["REASON"] = "SIGNED_PAIR_IMAGE_PIN_CONFLICT"
                return output
            expected_node_image = signed_node
            output["SIGNED_REGISTRY_PAIR_PROOF"] = "COSIGN_VERIFIED"
        except (signed_pair.AdmissionHold, OSError, ValueError, KeyError,
                TypeError, RuntimeError):
            # Fail closed without exposing registry details, tokens, or
            # verifier error bodies in a host report.
            output["SIGNED_REGISTRY_PAIR_PROOF"] = "REJECTED"
            output["REASON"] = "SIGNED_PAIR_PROOF_INVALID"
            return output
    else:
        # Legacy manual digest equality can still be reviewed, but it is
        # explicitly NOT a cryptographic registry signature.
        output["SIGNED_REGISTRY_PAIR_PROOF"] = "NOT_SUPPLIED"

    try:
        evidence = host.audit(
            node, runtime=runtime, min_bytes=min_bytes,
            expected_node_image=expected_node_image,
        )
        output["NODE_ROLE"] = evidence.get("NODE_ROLE", "UNVERIFIED")
        output["CORE_PROFILE"] = evidence.get("LOCAL_CORE", "UNVERIFIED")
        output["NODE_CONTAINER"] = evidence.get("DOCKER_NODE", "UNVERIFIED")
        output["PERSISTENT_STORAGE"] = evidence.get("PERSISTENT_DATA", "UNVERIFIED")
        output["SAVED_TUNNELS"] = evidence.get("PERSISTED_TUNNELS", "UNKNOWN")
        output["SAVED_TUNNEL_REGISTRY_SHA256"] = evidence.get(
            "PERSISTED_TUNNEL_REGISTRY_SHA256", "UNVERIFIED")
        output["NODE_CONTAINER_ID_SHA256"] = evidence.get(
            "NODE_CONTAINER_ID_SHA256", "UNVERIFIED")
        if evidence.get("HOST_PREFLIGHT") != "PASS_LOCAL_ONLY_INCOMPLETE":
            if evidence.get("HOST_PREFLIGHT") == "HOLD_EXISTING_TUNNELS":
                # Safe local inventory can still be shown on a production
                # Node, but its saved FRP tunnels remain an absolute
                # no-recreate HOLD. These are NOT signed engine claims.
                output["TARGET_ENGINE"] = local_state(engine, node)["state"]
                other_state = local_state(other, node)
                output["OTHER_ENGINE"] = other_state["state"]
                output["OTHER_ENGINE_LOCAL_REASON"] = other_state["reason"]
            output["REASON"] = evidence.get("HOLD_REASON") or (
                "SAVED_TUNNELS_PRESENT" if
                evidence.get("HOST_PREFLIGHT") == "HOLD_EXISTING_TUNNELS"
                else "HOST_PREFLIGHT_INCOMPLETE"
            )
            return output
        if evidence.get("IMAGE_REFERENCE_CLASS") != "OPERATOR_PINNED_DIGEST_UNATTESTED":
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
        output["OTHER_ENGINE_LOCAL_REASON"] = second["reason"]
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
            # Local binary SHA/mount evidence is enough to prepare a
            # NONAUTHORIZING, read-only transaction plan. It is NOT a
            # signed Node health attestation and never permits install.
            output["LOCAL_PREFLIGHT"] = "PASS_LOCAL_ONLY_INCOMPLETE"
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
    p.add_argument(
        "--expected-node-image",
        help="Exact independently reviewed ghcr.io/aghajani82/smite-node@sha256:... ref",
    )
    p.add_argument("--signed-pair-manifest", type=Path,
                   help="External exact Panel/Node signed registry candidate")
    p.add_argument("--signed-pair-manifest-sha256",
                   help="Independently reviewed SHA256 of candidate bytes")
    p.add_argument("--signed-pair-source-sha",
                   help="Exact independently reviewed Smite source commit")
    p.add_argument("--signed-pair-publish-ref",
                   help="Signed release publisher refs/tags/v... identity")
    p.add_argument("--signed-pair-trusted-root", type=Path,
                   help="Optional independently pinned Sigstore trusted-root JSON")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args()
    result = report(
        args.engine, args.node_dir,
        expected_node_image=args.expected_node_image,
        signed_pair_manifest=args.signed_pair_manifest,
        signed_pair_manifest_sha256=args.signed_pair_manifest_sha256,
        signed_pair_source_sha=args.signed_pair_source_sha,
        signed_pair_publish_ref=args.signed_pair_publish_ref,
        signed_pair_trusted_root=args.signed_pair_trusted_root,
    )
    if args.format == "json":
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        for key, value in result.items():
            print(f"{key}={value}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
