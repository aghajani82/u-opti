#!/usr/bin/env python3
"""Host transaction PLAN ONLY for independent Backhaul or FRP.

This file never alters a host, loads secrets into output, restarts Docker,
contacts GitHub/the Panel, installs binaries or approves activation.
It binds a private staged artifact to the exact reviewed Compose and
preflight, and produces a deterministic *non-authorizing* rollback contract.

Not a host installer. Install/rollback requests always return HOLD.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
ENGINES = ("backhaul", "frp")
SHA = re.compile(r"^[0-9a-f]{64}$")
ROOT_STAGE = Path("/var/lib/u-opti/smite-engine-staging")


def load(name: str, source: str):
    spec = importlib.util.spec_from_file_location(name, HERE / source)
    if spec is None or spec.loader is None:
        raise RuntimeError("MISSING_REVIEWED_MODULE")
    item = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(item)
    return item


admission = load("independent_engines_preview_gate", "smite-managed-engine-host-admission.py")
backhaul = load("independent_engines_preview_bh", "smite-managed-backhaul.py")
frp = load("independent_engines_preview_frp", "smite-managed-frp.py")

# Order is explicit. The real executor, when separately implemented,
# MUST journal state BEFORE touching binary/Compose/manifest and MUST
# verify signed Node status AFTER restart, or compensate and HOLD.
CHECKPOINTS = (
    "LOCK_BOTH_ENGINES_AND_RECHECK_ALL_HOST_EVIDENCE",
    "VERIFY_CLOUD_SNAPSHOT_AND_CONSOLE_EXTERNALLY",
    "RECHECK_PINNED_PACKAGE_AND_COMPOSE_NO_DRIFT",
    "PERSIST_PRIVATE_CRASH_RECOVERY_JOURNAL_FIRST",
    "STAGE_TARGET_ENGINE_BINARIES_WITH_ROLLBACK",
    "RECREATE_ONLY_REVIEWED_SMITE_NODE",
    "VERIFY_SIGNED_HMAC_INVENTORY_AND_REPLAY",
    "ROLLBACK_ON_FAILURE_THEN_VERIFY_SIGNED_PRIOR_RUNTIME",
    "COMMIT_ONLY_AFTER_INDEPENDENT_OPERATOR_APPROVAL",
)


class Hold(ValueError):
    pass


def strict_bytes(path: Path, *, limit: int) -> bytes:
    if path.is_symlink():
        raise Hold("UNTRUSTED_STAGE_SYMLINK")
    try:
        meta = path.lstat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1
                or meta.st_size < 1 or meta.st_size > limit):
            raise Hold("UNTRUSTED_STAGE_FILE")
        return path.read_bytes()
    except OSError as exc:
        raise Hold("STAGE_READ_FAILED") from exc


def staging(stage: Path, root: Path) -> None:
    # Source candidates are private and owned by the caller. Production
    # executor will have its OWN independent trust/identity admission.
    if (not root.is_absolute() or root == Path("/") or root.is_symlink()
            or not stage.is_absolute() or stage.parent != root
            or stage.is_symlink()):
        raise Hold("STAGE_OUTSIDE_PRIVATE_STAGING_ROOT")
    for path in (root, stage):
        try:
            st = path.lstat()
        except OSError as exc:
            raise Hold("MISSING_PRIVATE_STAGING_ROOT") from exc
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) & 0o077):
            raise Hold("STAGING_OWNER_OR_PERMISSIONS_UNTRUSTED")


def _safe_summary(path: Path) -> dict[str, str]:
    try:
        rows = [line.split("=", 1) for line in
                strict_bytes(path, limit=4096).decode().splitlines()]
    except UnicodeError as exc:
        raise Hold("UNREADABLE_CANDIDATE_SUMMARY") from exc
    if (not rows or any(len(row) != 2 for row in rows)
            or len(rows) != len({row[0] for row in rows})
            or any(not re.fullmatch(r"[A-Z0-9_]{1,60}", row[0])
                   for row in rows)):
        raise Hold("UNKNOWN_CANDIDATE_SUMMARY")
    return dict(rows)


def review(engine: str, node: Path, stage: Path, *,
           staging_root: Path = ROOT_STAGE,
           host_status: dict[str, str] | None = None) -> dict[str, str | list[str]]:
    if engine not in ENGINES:
        raise Hold("UNKNOWN_ENGINE")
    result: dict[str, str | list[str]] = {
        "ENGINE": engine.upper(),
        "PLAN": "HOST_TRANSACTION_CONTRACT_ONLY",
        "STAGE_ADMISSION": "HOLD",
        "ARTIFACT_PROVENANCE": "UNVERIFIED",
        "PRIOR_NODE_RUNTIME": "UNVERIFIED",
        "SIGNED_NODE_RESTART_AND_REPLAY": "UNVERIFIED",
        "CLOUD_SNAPSHOT_RESTORE": "UNVERIFIED",
        "EMERGENCY_CONSOLE": "UNVERIFIED",
        "ROLLBACK_EXECUTOR": "NOT_ENABLED",
        "OTHER_ENGINE_POLICY": "NEVER_TOUCH",
        "PORT_AND_TUNNEL_CONFIGURATION": "AFTER_INSTALL_IN_SMITE",
        "PUBLIC_PORT_CHANGE": "NONE",
        "INSTALL_ALLOWED": "NO",
        "ACTIVATION_GATE": "HOLD",
        "CHECKPOINTS": list(CHECKPOINTS),
    }
    try:
        inspection = host_status if host_status is not None else admission.report(engine, node)
        if (not isinstance(inspection, dict)
                or inspection.get("ENGINE") != engine.upper()
                or inspection.get("INSTALL_ALLOWED") != "NO"
                or inspection.get("ACTIVATION_GATE") != "HOLD"
                or inspection.get("LOCAL_PREFLIGHT") != "PASS_LOCAL_ONLY_INCOMPLETE"
                or inspection.get("TARGET_ENGINE") != "NOT_INSTALLED"
                or inspection.get("OTHER_ENGINE") != "NOT_INSTALLED"
                or inspection.get("SAVED_TUNNELS") != "ZERO"
                or inspection.get("CORE_PROFILE") != "MANAGED_STRICT"
                or inspection.get("NODE_CONTAINER") != "RUNNING_REVIEWED_IMAGE"):
            raise Hold("HOST_ADMISSION_INCOMPLETE")
        staging(stage, staging_root)
        summary = _safe_summary(stage / "summary.txt")
        # Bounded byte reads; no token or user config ever enters output.
        source = admission.host._local_file(
            node / "docker-compose.yml", max_bytes=131072, require_root=True)
        source_sha = hashlib.sha256(source).hexdigest()
        if engine == "frp":
            if not frp.verify(stage, official_only=True):
                raise Hold("FRP_OFFICIAL_ARCHIVE_NOT_VERIFIED")
            version, arch, digest = "v0.71.0", summary.get("FRP_ARCH"), summary.get("ARCHIVE_SHA256")
            expected = frp.OFFICIAL_TAR_SHA256
            binaries = ("frpc.bin", "frps.bin")
            claimed_compose = summary.get("ORIGINAL_COMPOSE_SHA256")
        else:
            if not backhaul.verify(stage):
                raise Hold("BACKHAUL_STAGE_UNTRUSTED")
            version, arch, digest = "v0.7.2", summary.get("BACKHAUL_ARCH"), summary.get("ARCHIVE_SHA256")
            expected = backhaul.OFFICIAL_TAR_SHA256
            binaries = ("backhaul.bin",)
            claimed_compose = summary.get("ORIGINAL_COMPOSE_SHA256")
        if (arch not in expected or digest != expected[arch]
                or claimed_compose != source_sha):
            raise Hold("SOURCE_COMPOSE_OR_ARCHIVE_DRIFT")
        if (summary.get("CANDIDATE_ONLY") != "YES"
                or (engine == "frp" and summary.get("PORT_OR_TUNNEL_INPUT") != "NOT_REQUIRED")):
            raise Hold("NONINERT_ENGINE_CANDIDATE")
        declaration = json.loads(strict_bytes(stage / "engines.candidate.json", limit=8192))
        existing = backhaul._existing_manifest(node / "config")
        if (not isinstance(declaration, dict) or set(declaration) != {"schema", "engines"}
                or declaration.get("schema") != 1
                or not isinstance(declaration.get("engines"), dict)
                or engine not in declaration["engines"]
                or {k: v for k, v in declaration["engines"].items() if k != engine} != existing
                or engine in existing):
            raise Hold("OTHER_ENGINE_MANIFEST_CHANGED")
        binary_hashes = [hashlib.sha256(strict_bytes(stage / name, limit=frp.BINARY_MAX)).hexdigest()
                         for name in binaries]
        own_record = declaration["engines"][engine]
        expected_record = ({"sha256": binary_hashes[0], "server_sha256": binary_hashes[1]}
                           if engine == "frp" else {"sha256": binary_hashes[0]})
        if own_record != expected_record:
            raise Hold("CANDIDATE_ENGINE_DIGEST_MISMATCH")
        if engine == "backhaul":
            # Historical Backhaul candidate only has editable SHA256SUMS
            # and an official archive *digest string*, not archive bytes.
            # It is insufficient to prove the staged ELF came from that
            # official archive. Do NOT attest a valid production candidate.
            result["ARTIFACT_PROVENANCE"] = "NOT_ARCHIVE_BOUND"
            raise Hold("BACKHAUL_ARCHIVE_BINDING_REQUIRED")
        result["ARTIFACT_PROVENANCE"] = "OFFICIAL_FRP_ARCHIVE_VERIFIED"
        result["SOURCE_COMPOSE_SHA256"] = source_sha
        result["CANDIDATE_MANIFEST_SHA256"] = hashlib.sha256(
            strict_bytes(stage / "engines.candidate.json", limit=8192)).hexdigest()
        result["BINARIES_SHA256"] = binary_hashes
        # Digest is a change-detector, NOT a signature or install ticket.
        plan_fingerprint = {
            "engine": engine, "arch": arch, "version": version,
            "compose": source_sha, "manifest": result["CANDIDATE_MANIFEST_SHA256"],
            "binary_hashes": binary_hashes,
        }
        result["PLAN_SHA256_NOT_AUTHORIZATION"] = hashlib.sha256(
            json.dumps(plan_fingerprint, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result["STAGE_ADMISSION"] = "VERIFIED_PREVIEW_ONLY"
        result["REASON"] = "SNAPSHOT_SIGNED_RUNTIME_HOST_EXECUTOR_UNVERIFIED"
    except (Hold, OSError, ValueError, RuntimeError, UnicodeError) as exc:
        why = str(exc) if isinstance(exc, Hold) else "UNTRUSTED_STAGE_OR_HOST"
        result["REASON"] = why if re.fullmatch(r"[A-Z0-9_]{1,90}", why) else "UNTRUSTED_STAGE_OR_HOST"
    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only host transaction proposal, ALWAYS HOLD")
    p.add_argument("action", choices=("review", "install", "rollback"))
    p.add_argument("--engine", choices=ENGINES, required=True)
    p.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    p.add_argument("--stage", type=Path)
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args()
    if args.action != "review" or args.stage is None:
        print("HOLD: HOST_INSTALL_AND_ROLLBACK_DISABLED", file=sys.stderr)
        return 2
    result = review(args.engine, args.node_dir, args.stage)
    if args.format == "json":
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        for key, value in result.items():
            if isinstance(value, list):
                # Print only bounded, built-in safe labels, not arbitrary input.
                value = ",".join(value)
            print(f"{key}={value}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
