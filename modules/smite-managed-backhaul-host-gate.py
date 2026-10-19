#!/usr/bin/env python3
"""Read-only gate before ANY future real-host Backhaul-only installation.

No installation authority can be produced by this tool. It never updates
Smite, Docker, Nginx, firewall, engine state, tunnels or credentials, and it
does NOT query the cloud snapshot provider or signed Panel API. Even a fully
passing local inventory returns HOLD with explicit unresolved prerequisites.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

MAX_INSPECT_BYTES = 1024 * 1024
MAX_TUNNELS_BYTES = 256 * 1024
MIN_FREE_BYTES = 256 * 1024 * 1024
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
KNOWN_NODE_IMAGES = {
    "smite-node:stage15-local",
    "ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e",
}
PRIVATE_PROFILES = {"managed", "strict"}
NO_PROOF = "UNVERIFIED_MANUAL_OR_SEPARATE_SIGNED_TEST"


class GateHold(ValueError):
    pass


def _local_file(path: Path, *, max_bytes: int, require_root: bool = False) -> bytes:
    if path.is_symlink():
        raise GateHold("LOCAL_SYMLINK")
    try:
        st = path.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_size > max_bytes or st.st_size < 0):
            raise GateHold("UNTRUSTED_LOCAL_FILE")
        if require_root and st.st_uid != 0:
            raise GateHold("UNTRUSTED_OWNERSHIP")
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise GateHold("MISSING_LOCAL_FILE") from exc
    except OSError as exc:
        raise GateHold("LOCAL_IO_FAILURE") from exc


def _node_profile(env_data: bytes) -> str:
    try:
        lines = env_data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise GateHold("INVALID_CORE_ENV") from exc
    protected = {"NODE_ROLE", "SMITE_ENGINE_INVENTORY_MODE",
                 "SMITE_AGENT_AUTH_MODE", "SMITE_NODE_PANEL_AUTH_MODE"}
    found = {}
    for line in lines:
        if not line or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if key in protected and sep:
            if key in found:
                raise GateHold("DUPLICATE_CORE_ENV")
            found[key] = value
    if (found.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            or found.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or found.get("SMITE_NODE_PANEL_AUTH_MODE") not in ("paused", "signed")):
        raise GateHold("NOT_MANAGED_STRICT_CORE")
    if found.get("NODE_ROLE") in ("iran", "panel-iran"):
        return "IR"
    if found.get("NODE_ROLE") == "foreign":
        return "KH"
    raise GateHold("UNRECOGNIZED_CORE_ROLE")


def read_only_docker_inspect(*, name: str = "smite-node", runner=subprocess.run) -> dict:
    """The single subprocess permitted in this module: 'docker inspect'."""
    if not NAME.fullmatch(name):
        raise GateHold("UNSAFE_CONTAINER_NAME")
    try:
        result = runner(
            ["docker", "inspect", "--type=container", name],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateHold("DOCKER_INSPECT_UNAVAILABLE") from exc
    if result.returncode != 0 or len(result.stdout) > MAX_INSPECT_BYTES:
        raise GateHold("DOCKER_INSPECT_UNAVAILABLE")
    try:
        parsed = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise GateHold("DOCKER_INSPECT_MALFORMED") from exc
    if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
        raise GateHold("DOCKER_INSPECT_MALFORMED")
    return parsed[0]


def check_runtime(report: dict, *, node_dir: Path) -> tuple[str, Path]:
    """Inspect exact container identity and its persistent mounts."""
    if (report.get("Name") != "/smite-node" or
            not isinstance(report.get("State"), dict)
            or report["State"].get("Running") is not True):
        raise GateHold("NODE_NOT_RUNNING")
    config = report.get("Config")
    host = report.get("HostConfig")
    if not isinstance(config, dict) or not isinstance(host, dict):
        raise GateHold("DOCKER_METADATA_INCOMPLETE")
    image = config.get("Image")
    if image not in KNOWN_NODE_IMAGES:
        raise GateHold("UNREVIEWED_NODE_IMAGE")
    if host.get("NetworkMode") != "host":
        raise GateHold("UNEXPECTED_NODE_NETWORK")
    if host.get("PortBindings"):
        raise GateHold("PUBLISHED_DOCKER_PORTS")
    mounts = report.get("Mounts")
    if not isinstance(mounts, list):
        raise GateHold("DOCKER_MOUNT_INVENTORY_MISSING")
    mapping = {}
    for mount in mounts:
        if not isinstance(mount, dict):
            raise GateHold("UNTRUSTED_NODE_MOUNT")
        dest = mount.get("Destination")
        if dest in ("/etc/smite-node", "/var/lib/smite-node"):
            if dest in mapping or mount.get("Type") != "bind":
                raise GateHold("UNTRUSTED_NODE_MOUNT")
            source = mount.get("Source")
            if not isinstance(source, str) or not source.startswith("/"):
                raise GateHold("UNTRUSTED_NODE_MOUNT")
            mapping[dest] = Path(source)
    config_mount = mapping.get("/etc/smite-node")
    data_mount = mapping.get("/var/lib/smite-node")
    if (config_mount is None or data_mount is None
            or config_mount != node_dir / "config"):
        raise GateHold("WRONG_NODE_CONFIG_VOLUME")
    if (config_mount.is_symlink() or data_mount.is_symlink()
            or not config_mount.is_dir() or not data_mount.is_dir()):
        raise GateHold("INVALID_PERSISTENT_VOLUMES")
    return image, data_mount


def tunnel_count(data_dir: Path) -> int:
    saved = data_dir / "tunnels.json"
    if not saved.exists() and not saved.is_symlink():
        return 0
    blob = _local_file(saved, max_bytes=MAX_TUNNELS_BYTES, require_root=True)
    try:
        tunnels = json.loads(blob)
    except (ValueError, UnicodeError) as exc:
        raise GateHold("TUNNEL_REGISTRY_CORRUPT") from exc
    if not isinstance(tunnels, dict) or len(tunnels) > 5000:
        raise GateHold("UNTRUSTED_TUNNEL_REGISTRY")
    for value in tunnels.values():
        if (not isinstance(value, dict) or
                not isinstance(value.get("core"), str) or
                not isinstance(value.get("spec"), dict)):
            raise GateHold("UNTRUSTED_TUNNEL_REGISTRY")
    return len(tunnels)


def audit(node: Path, *, runtime: dict | None = None, runner=subprocess.run,
          min_bytes: int = MIN_FREE_BYTES) -> dict[str, str]:
    """No mutable actions and no secret-bearing result strings."""
    result = {
        "NODE_ROLE": "HOLD",
        "LOCAL_CORE": "HOLD",
        "DOCKER_NODE": "HOLD",
        "PERSISTED_TUNNELS": "UNKNOWN",
        "DISK_SPACE": "HOLD",
        "ENGINE": "BACKHAUL_ONLY",
        "FRP_INSTALL_REQUIRED": "NO",
        "NEW_PUBLIC_PORTS": "NONE_PLANNED",
        "SNAPSHOT_AND_CONSOLE": NO_PROOF,
        "SIGNED_NODE_POST_RESTART": NO_PROOF,
        "PAIRING_AND_REPLAY_PRESERVATION": NO_PROOF,
        "NGINX_443_AND_FIREWALL_EXPOSURE": NO_PROOF,
        "TUNNEL_RECOVERY_AFTER_RESTART": NO_PROOF,
        "HOST_INSTALL_AUTHORIZED": "NO",
    }
    try:
        if not node.is_absolute() or node.is_symlink() or not node.is_dir():
            raise GateHold("UNSAFE_NODE_ROOT")
        role = _node_profile(_local_file(node / ".env", max_bytes=16384, require_root=True))
        result["NODE_ROLE"] = role
        result["LOCAL_CORE"] = "MANAGED_STRICT"
        compose = _local_file(node / "docker-compose.yml", max_bytes=131072,
                              require_root=True).decode("utf-8")
        if (len(re.findall(r"(?m)^  smite-node:\s*$", compose)) != 1
                or not re.search(r"(?m)^\s+network_mode: host\s*$", compose)
                or re.search(r"(?m)^\s+ports:\s*$", compose)
                or not re.search(r"(?m)^\s+- ./config:/etc/smite-node\s*$", compose)):
            raise GateHold("UNTRUSTED_NODE_COMPOSE")
        result["COMPOSE_SHA256"] = hashlib.sha256(compose.encode("utf-8")).hexdigest()
        node_report = runtime if runtime is not None else read_only_docker_inspect(runner=runner)
        image, data_dir = check_runtime(node_report, node_dir=node)
        result["DOCKER_NODE"] = "RUNNING_REVIEWED_IMAGE"
        result["IMAGE_REFERENCE_CLASS"] = (
            "LOCAL_TAG_UNATTESTED" if image == "smite-node:stage15-local"
            else "REVIEWED_DIGEST_UNATTESTED"
        )
        count = tunnel_count(data_dir)
        result["PERSISTED_TUNNELS"] = "ZERO" if count == 0 else "EXISTING_DO_NOT_RESTART"
        try:
            free = os.statvfs(node).f_bavail * os.statvfs(node).f_frsize
        except OSError as exc:
            raise GateHold("DISK_SPACE_UNREADABLE") from exc
        if free < min_bytes:
            raise GateHold("INSUFFICIENT_FREE_DISK")
        result["DISK_SPACE"] = "MINIMUM_AVAILABLE"
        result["HOST_PREFLIGHT"] = (
            "HOLD_EXISTING_TUNNELS" if count else "PASS_LOCAL_ONLY_INCOMPLETE"
        )
    except (GateHold, UnicodeError, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, GateHold) else "UNTRUSTED_LOCAL_DATA"
        result["HOST_PREFLIGHT"] = "HOLD"
        # Never print exception arguments from external processes or secrets.
        result["HOLD_REASON"] = reason if re.fullmatch(r"[A-Z0-9_]+", reason) else "UNVERIFIED"
    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Backhaul host preflight READ ONLY; never authorizes installation")
    p.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    args = p.parse_args()
    report = audit(args.node_dir)
    for key, value in report.items():
        print(f"{key}={value}")
    print("BACKHAUL_ACTIVATION_GATE=HOLD")
    # Never make this look like an install-capable PASS.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
