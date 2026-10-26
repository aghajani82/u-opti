#!/usr/bin/env python3
"""Read-only FRP managed engine status / review; no live install path.

A local digest match is not signed Node evidence. "Install" stays HOLD until
the separately reviewed host lifecycle is integrated and accepted on two
disposable machines with snapshots. Does not inspect or alter Backhaul.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

MODULE_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("managed_frp_candidate", MODULE_DIR / "smite-managed-frp.py")
assert _spec and _spec.loader
frp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(frp)


class Hold(ValueError):
    pass


def inspect(node: Path, *, binaries: dict[str, Path] | None = None) -> dict[str, str]:
    if not node.is_absolute() or node.is_symlink() or not node.is_dir():
        raise Hold("UNSAFE_NODE_DIR")
    raw = frp.shared._file(node / ".env", max_size=16384).decode()
    settings = {}
    for line in raw.splitlines():
        if line.lstrip().startswith("#") or not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ("NODE_ROLE", "SMITE_ENGINE_INVENTORY_MODE",
                   "SMITE_AGENT_AUTH_MODE", "SMITE_NODE_PANEL_AUTH_MODE"):
            if key in settings:
                raise Hold("DUPLICATE_CORE_ENV")
            settings[key] = value
    if (settings.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            or settings.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or settings.get("SMITE_NODE_PANEL_AUTH_MODE") not in ("paused", "signed")
            or settings.get("NODE_ROLE") not in ("iran", "panel-iran", "foreign")):
        raise Hold("MANAGED_STRICT_CORE_REQUIRED")
    role = "KH" if settings["NODE_ROLE"] == "foreign" else "IR"
    compose = frp.shared._file(node / "docker-compose.yml", max_size=131072).decode()
    if (len(re.findall(r"(?m)^  smite-node:\s*$", compose)) != 1
            or not re.search(r"(?m)^    network_mode: host\s*$", compose)
            or re.search(r"(?m)^    ports:\s*$", compose)
            or "      - ./config:/etc/smite-node\n" not in compose):
        raise Hold("UNREVIEWED_NODE_COMPOSE")
    declared = frp.shared._existing_manifest(node / "config")
    if "frp" not in declared:
        if any(target in compose for target in frp.BINARY_PATHS.values()):
            return {"role": role, "state": "UNAVAILABLE", "reason": "PARTIAL_FRP_MOUNT"}
        return {"role": role, "state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}
    record = declared["frp"]
    binaries = binaries if binaries is not None else {
        name: frp.INSTALL_ROOT / name for name in frp.BINARY_PATHS
    }
    if set(binaries) != set(frp.BINARY_PATHS) or "server_sha256" not in record:
        return {"role": role, "state": "UNAVAILABLE", "reason": "DUAL_FRP_DIGEST_REQUIRED"}
    for name, dest in frp.BINARY_PATHS.items():
        binpath = binaries[name]
        mount = f"      - {binpath}:{dest}:ro"
        if compose.splitlines().count(mount) != 1:
            return {"role": role, "state": "UNAVAILABLE", "reason": "MISSING_READONLY_MOUNT"}
        try:
            st = binpath.lstat()
            if (binpath.is_symlink() or not stat.S_ISREG(st.st_mode)
                    or st.st_uid != 0 or not st.st_mode & 0o111
                    or st.st_mode & 0o022 or st.st_nlink != 1):
                return {"role": role, "state": "UNAVAILABLE", "reason": "UNSAFE_FRP_BINARY"}
            expected = record["sha256"] if name == "frpc" else record["server_sha256"]
            if hashlib.sha256(frp.shared._file(binpath, max_size=frp.BINARY_MAX)).hexdigest() != expected:
                return {"role": role, "state": "UNAVAILABLE", "reason": "FRP_SHA256_MISMATCH"}
        except (OSError, frp.shared.Hold):
            return {"role": role, "state": "UNAVAILABLE", "reason": "FRP_BINARY_MISSING"}
    return {"role": role, "state": "ENROLLED_UNVERIFIED", "reason": "SIGNED_NODE_RECHECK_REQUIRED"}


def main() -> int:
    parser = argparse.ArgumentParser(description="FRP independent managed-engine read-only operator review")
    parser.add_argument("action", choices=("status", "review", "verify-stage", "install", "rollback"))
    parser.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    parser.add_argument("--stage", type=Path)
    args = parser.parse_args()
    if args.action in ("install", "rollback"):
        print("HOLD: Real-host FRP engine activation is NOT enabled; no server changed", file=sys.stderr)
        return 2
    try:
        if args.action == "verify-stage":
            if args.stage is None or not frp.verify(args.stage):
                raise Hold("ONLY_OFFICIAL_FRP_CANDIDATE_ALLOWED")
            print("FRP_STAGE_VERIFIED=YES")
        else:
            for key, val in inspect(args.node_dir).items():
                print(f"{key.upper()}={val}")
            print("SIGNED_NODE_STATUS=NOT_QUERIED")
            if args.action == "review":
                print("INSTALL_ALLOWED=NO")
                print("BACKHAUL_DEPENDENCY=NONE")
                print("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED")
                print("HOST_DOCKER_ACTIONS=NONE")
        return 0
    except (Hold, frp.shared.Hold, OSError, UnicodeError) as exc:
        value = str(exc)
        print("HOLD: " + (value if re.fullmatch(r"[A-Z0-9_]+", value) else "UNTRUSTED_LOCAL_STATE"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
