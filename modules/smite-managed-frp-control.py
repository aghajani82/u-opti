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
import json
import os
from pathlib import Path
import re
import stat
import subprocess
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


# The two local Stage15 archives were independently checked for the KH
# signed-pairing field trial. This is a test-image ID, NOT an OCI digest or
# a production provenance attestation. RC.2 lanes keep their original pins.
STAGE15_NODE_ID = (
    "sha256:a417e8c28426da5eaf16d59925d5c89b52dbf7849ca560dfa9a765a1266b3991"
)


def _read_only(argv: list[str]) -> str:
    """Bounded argv-only reads. No shell, network, Docker recreation or writes."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20,
                           check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("STAGE15_READ_ONLY_COMMAND_FAILED") from exc
    if p.returncode or len(p.stdout) > 262144:
        raise Hold("STAGE15_READ_ONLY_COMMAND_FAILED")
    return p.stdout.strip()


def stage15_readiness(node: Path, *, run=None) -> dict[str, str]:
    """Read-only signed Stage15 Node readiness; never authorizes FRP apply.

    Enforces the specific running and tagged image ID, signed runtime,
    composed security overlay, loopback-only API, and bundled version.
    An image-ID match alone is NOT signed health, replay or live tunnel proof.
    """
    if run is None:
        run = _read_only
    previous = inspect(node)
    if previous["state"] != "NOT_INSTALLED":
        raise Hold("STAGE15_FRP_ENROLLMENT_REQUIRES_REVIEW")
    signed = node / "docker-compose.security-candidate.yml"
    frp.shared._file(signed, max_size=131072)
    try:
        entries = json.loads(run(["docker", "inspect", "smite-node"]))
        if not isinstance(entries, list) or len(entries) != 1:
            raise Hold("STAGE15_NODE_INSPECT_INVALID")
        runtime = entries[0]
        config = runtime["Config"]
        host = runtime["HostConfig"]
        env_raw = config["Env"]
        if not isinstance(env_raw, list):
            raise Hold("STAGE15_ENV_INVALID")
        values: dict[str, str] = {}
        for line in env_raw:
            if not isinstance(line, str) or "=" not in line:
                raise Hold("STAGE15_ENV_INVALID")
            key, value = line.split("=", 1)
            if key in values:
                raise Hold("STAGE15_DUPLICATE_ENV")
            values[key] = value
        if (config["Image"] != "smite-node:stage15-local"
                or runtime["Image"] != STAGE15_NODE_ID
                or run(["docker", "image", "inspect", "-f", "{{.Id}}",
                        "smite-node:stage15-local"]) != STAGE15_NODE_ID):
            raise Hold("STAGE15_IMAGE_ID_MISMATCH")
        if (runtime["State"]["Running"] is not True
                or runtime["State"]["Health"]["Status"] != "healthy"):
            raise Hold("STAGE15_NODE_UNHEALTHY")
        if (host["NetworkMode"] != "host" or host.get("PortBindings")
                or host.get("Privileged") is True):
            raise Hold("STAGE15_NODE_NETWORK_DRIFT")
        if config.get("Cmd") != [
            "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"
        ]:
            raise Hold("STAGE15_NODE_LOOPBACK_DRIFT")
        for key, expected in {
            "SMITE_NODE_PANEL_AUTH_MODE": "signed",
            "SMITE_AGENT_AUTH_MODE": "strict",
            "SMITE_ENGINE_INVENTORY_MODE": "managed",
        }.items():
            if values.get(key) != expected:
                raise Hold("STAGE15_SIGNED_POLICY_DRIFT")
        if not re.fullmatch(r"[a-z0-9.-]+:443", values.get("PANEL_ADDRESS", "")):
            raise Hold("STAGE15_PANEL_TRANSPORT_DRIFT")
        if "SMITE_FRP_STANDARD_WSS" in values:
            raise Hold("STAGE15_WSS_FLAG_UNREVIEWED")
        active_files = {
            f.strip() for f in config.get("Labels", {}).get(
                "com.docker.compose.project.config_files", ""
            ).split(",") if f.strip()
        }
        if active_files != {str(node / "docker-compose.yml"), str(signed)}:
            raise Hold("STAGE15_SIGNED_COMPOSE_NOT_ACTIVE")
        mounts = {m["Destination"]: m for m in runtime["Mounts"]}
        for target, writable in {
            "/etc/smite-node": True,
            "/run/smite-node-identity": False,
            "/var/lib/smite-node/auth": True,
        }.items():
            if target not in mounts or mounts[target].get("RW") is not writable:
                raise Hold("STAGE15_SIGNED_MOUNT_DRIFT")
        for name in ("frpc", "frps"):
            version = run(["docker", "exec", "smite-node",
                           "/usr/local/bin/" + name, "--version"])
            if version.strip().lstrip("v") != "0.71.0":
                raise Hold("STAGE15_FRP_BINARY_VERSION_DRIFT")
    except (TypeError, KeyError, IndexError, AttributeError, ValueError,
            json.JSONDecodeError) as exc:
        if isinstance(exc, Hold):
            raise
        raise Hold("STAGE15_RUNTIME_EVIDENCE_INVALID") from exc
    return {
        "ROLE": previous["role"],
        "STAGE15_IMAGE": "PINNED_TEST_ID_MATCH",
        "SIGNED_NODE": "HEALTHY_LOCAL_RUNTIME_ONLY",
        "FRP_BINARIES": "BUNDLED_0_71_0",
        "FRP_ENGINE_ENROLLED": "NO",
        "WSS_ACTIVATION": "NOT_ENABLED",
        "SIGNED_HMAC_REPLAY_PROOF": "NOT_QUERIED",
        "HOST_FRP_INSTALL": "HOLD",
        "PUBLIC_PORTS_CHANGED": "NO",
        "LIVE_CHANGES": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="FRP independent managed-engine read-only operator review")
    parser.add_argument("action", choices=("status", "review", "stage15", "verify-stage", "install", "rollback"))
    parser.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    parser.add_argument("--stage", type=Path)
    args = parser.parse_args()
    if args.action in ("install", "rollback"):
        print("HOLD: Real-host FRP engine activation is NOT enabled; no server changed", file=sys.stderr)
        return 2
    try:
        if args.action == "stage15":
            for key, value in stage15_readiness(args.node_dir).items():
                print(f"{key}={value}")
        elif args.action == "verify-stage":
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
    except (Hold, frp.shared.Hold, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        value = str(exc)
        print("HOLD: " + (value if re.fullmatch(r"[A-Z0-9_]+", value) else "UNTRUSTED_LOCAL_STATE"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
