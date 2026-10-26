#!/usr/bin/env python3
"""Independent Backhaul operator control. Live host actions deliberately OFF.

The public status/review/verify paths are READ ONLY. install/rollback invoke
ONLY the already gated disposable GitHub PR filesystem transaction. There
is NO production activation, Docker/FRP/Nginx operation, network request,
tunnel configuration or remote server operation in this module.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

MODULES = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, MODULES / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("U-OPTI managed Backhaul helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = _load("uopti_bh_preparer", "smite-managed-backhaul.py")
transaction = _load("uopti_bh_tx", "smite-managed-backhaul-transaction.py")

ENGINES = ("backhaul", "frp", "gost", "rathole", "chisel")
ROLE = {"iran": "IR", "panel-iran": "IR", "foreign": "KH"}
EXPECTED_PROD_BINARY = package.INSTALL_BINARY
EXPECTED_TARGET = package.CONTAINER_BINARY
NODE_DEFAULT = Path("/opt/smite-node")


class Hold(ValueError):
    pass


def _trusted_env(node: Path) -> tuple[str, dict[str, str]]:
    raw = package._file(node / ".env", max_size=16384).decode("utf-8")
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key in {
            "NODE_ROLE", "SMITE_ENGINE_INVENTORY_MODE",
            "SMITE_AGENT_AUTH_MODE", "SMITE_NODE_PANEL_AUTH_MODE",
        }:
            if key in values:
                raise Hold("Duplicate protected Node environment setting")
            values[key] = value
    if (values.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            or values.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or values.get("SMITE_NODE_PANEL_AUTH_MODE") not in ("paused", "signed")):
        raise Hold("Managed strict Smite Core is required; no legacy migration")
    return ROLE.get(values.get("NODE_ROLE"), "UNVERIFIED"), values


def inspect(node: Path, *, lab_binary: Path | None = None) -> dict[str, str]:
    """Local installation evidence, NOT a signed or running Node report."""
    if not node.is_absolute() or node.is_symlink() or not node.is_dir():
        raise Hold("Expected absolute, regular Smite Node directory")
    role, _ = _trusted_env(node)
    if role == "UNVERIFIED":
        raise Hold("Unknown Smite Node IR/KH role")
    compose = package._file(node / "docker-compose.yml", max_size=131072).decode("utf-8")
    if (len(re.findall(r"(?m)^  smite-node:\s*$", compose)) != 1
            or not re.search(r"(?m)^    network_mode: host\s*$", compose)
            or not re.search(r"(?m)^    image: \S+", compose)
            or not re.search(r"(?m)^\s+- ./config:/etc/smite-node\s*$", compose)
            or re.search(r"(?m)^    ports:\s*$", compose)):
        raise Hold("Unknown or unsafe Smite Node Compose layout")
    cfg = node / "config"
    if cfg.is_symlink() or not cfg.is_dir():
        raise Hold("Smite Core config bind absent or symlinked")
    declared = package._existing_manifest(cfg)
    binary = lab_binary if lab_binary is not None else EXPECTED_PROD_BINARY
    if not binary.is_absolute() or binary.is_symlink():
        raise Hold("Unsafe engine binary path")
    required_mount = f"      - {binary}:{EXPECTED_TARGET}:ro"
    has_mount = required_mount in compose.splitlines()
    any_backhaul_target = EXPECTED_TARGET in compose
    backhaul_is_declared = "backhaul" in declared
    path_exists = binary.exists() or binary.is_symlink()

    if not backhaul_is_declared:
        if any_backhaul_target or path_exists:
            return {"role": role, "state": "UNAVAILABLE", "reason": "PARTIAL_INSTALL_OR_DRIFT"}
        return {"role": role, "state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}
    if not has_mount or compose.count(EXPECTED_TARGET) != 1 or not path_exists:
        return {"role": role, "state": "UNAVAILABLE", "reason": "MISSING_TRUSTED_READONLY_MOUNT"}

    st = binary.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or st.st_uid != 0 or not (st.st_mode & 0o111)
            or st.st_mode & 0o022 or st.st_size > package.MAX_BINARY_BYTES):
        return {"role": role, "state": "UNAVAILABLE", "reason": "INVALID_BINARY_PERMISSIONS"}
    value = package._file(binary, max_size=package.MAX_BINARY_BYTES)
    if hashlib.sha256(value).hexdigest() != declared["backhaul"]["sha256"]:
        return {"role": role, "state": "UNAVAILABLE", "reason": "BINARY_SHA256_MISMATCH"}
    return {"role": role, "state": "ENROLLED_UNVERIFIED", "reason": "SIGNED_NODE_RECHECK_REQUIRED"}


def verified_candidate(stage: Path) -> dict[str, str]:
    if stage.is_symlink() or not stage.is_absolute():
        raise Hold("Unsafe candidate path")
    if not package.verify(stage):
        raise Hold("Unverified or corrupted Backhaul candidate")
    summary = transaction.parse_summary(stage)
    arch = summary.get("BACKHAUL_ARCH")
    if (arch not in package.OFFICIAL_TAR_SHA256
            or summary.get("ARCHIVE_SHA256") != package.OFFICIAL_TAR_SHA256[arch]
            or summary.get("BACKHAUL_VERSION") != package.VERSION
            or summary.get("CANDIDATE_ONLY") != "YES"):
        raise Hold("Only officially pinned Backhaul v0.7.2 candidates allowed")
    return {"state": "VERIFIED_CANDIDATE_ONLY", "engine": "backhaul", "arch": arch}


def _format(status: dict[str, str]) -> None:
    for key, value in status.items():
        print(f"{key.upper()}={value}")


@contextmanager
def _lab_lock(root: Path):
    # No lock creation is possible until the PR-only lab admission passes.
    transaction.admission(root)
    # All managed engines mutate the SAME Node Compose and manifest.
    # FRP and Backhaul installs are independent, not concurrently writable.
    file = root / ".smite-engine-transaction.lock"
    fd = os.open(file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1):
            raise Hold("Unsafe transaction lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold("Another Backhaul engine transaction is in progress") from exc
        yield
    finally:
        os.close(fd)


def exercise(root: Path, *, action: str, stage: Path | None = None) -> dict[str, str]:
    """Only operates on a marked, private, disposable GitHub runner lab."""
    if action not in ("install", "rollback"):
        raise Hold("Unknown experimental action")
    with _lab_lock(root):
        node = root / "node"
        bin_file = root / "installed" / "backhaul"
        if action == "install":
            if stage is None:
                raise Hold("Verified stage required")
            verified_candidate(stage)
            before = inspect(node, lab_binary=bin_file)
            if before["state"] != "NOT_INSTALLED":
                raise Hold("Backhaul not cleanly absent; repair is separate")
            transaction.activate(root, stage)
            result = inspect(node, lab_binary=bin_file)
            if result["state"] != "ENROLLED_UNVERIFIED":
                raise Hold("Post-transaction evidence mismatch: recovery journal retained")
            return {"state": "LAB_INSTALLED_UNVERIFIED",
                    "next": "SIGNED_NODE_RUNTIME_PROOF_REQUIRED"}
        # Never erase another engine if the backup record is untrusted.
        transaction.rollback(root)
        result = inspect(node, lab_binary=bin_file)
        if result["state"] != "NOT_INSTALLED":
            raise Hold("Rollback evidence incomplete")
        return {"state": "LAB_EXACT_ROLLBACK_CONFIRMED",
                "next": "NO_LIVE_SERVICES_TOUCHED"}


def main() -> int:
    arg = argparse.ArgumentParser(description="Managed Backhaul: safe review, CI-only activation")
    arg.add_argument("action", choices=("status", "review", "verify-stage", "install", "rollback"))
    arg.add_argument("--node-dir", type=Path, default=NODE_DEFAULT)
    arg.add_argument("--stage", type=Path)
    arg.add_argument("--lab-root", type=Path)
    args = arg.parse_args()
    try:
        if args.action in ("install", "rollback"):
            if args.lab_root is None:
                raise Hold("Real host engine activation is NOT enabled; no server changed")
            _format(exercise(args.lab_root, action=args.action, stage=args.stage))
        elif args.action == "verify-stage":
            if args.stage is None:
                raise Hold("--stage required")
            _format(verified_candidate(args.stage))
        elif args.action == "status":
            _format(inspect(args.node_dir))
            print("SIGNED_NODE_STATUS=NOT_QUERIED")
        elif args.action == "review":
            result = inspect(args.node_dir)
            _format(result)
            print("INSTALL_ALLOWED=NO")
            print("HOST_DOCKER_ACTIONS=NONE")
            print("FRP_DEPENDENCY=NONE")
            print("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED")
            print("NEXT=CI_ONLY_UNTIL_HOST_ROLLBACK_APPROVAL")
        return 0
    except (Hold, package.Hold, transaction.Hold, OSError, ValueError, UnicodeError) as error:
        print(f"HOLD: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
