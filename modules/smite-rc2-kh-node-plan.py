#!/usr/bin/env python3
"""Fail-closed KH RC.1 -> RC.2 Node image-only read-only plan.

Never writes a file or performs Docker pull/up/restart. Does NOT authorize
foreign signed pairing, Node activation or any server upgrade. No secrets
or resolved Compose values are printed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

NODE_COMPOSE = Path("/opt/smite-node/docker-compose.yml")
STATE = Path("/etc/u-opti/smite/state.env")
RC1_NODE = ("ghcr.io/aghajani82/smite-node@sha256:"
            "9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec")
RC2_NODE = ("ghcr.io/aghajani82/smite-node@sha256:"
            "2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78")
COMPOSE_SHA = "ab0f360f288c4659a52ec5e4f5b67afd22ec21dcc29a328d72cd8829b91eae6f"
SANAEI_IMAGE = "sha256:6c7e73c5bc4b6d7d70866616f78d6c9866b4904defad3077c1e2b5c1c89c2ec1"
BACKUPS = {
    "/root/kh-sanaei-pre-rc2-20261023T150429Z/x-ui.db":
        "4b58350aa982389daf0953ef7e447577c8a9fcee40e27f1bfd66c1243a96e740",
    "/root/kh-sanaei-pre-rc2-20261023T150429Z/kh-private-config.tar.gz":
        "3fe92f5f1bbb7804e7d34d25110d290aa24c4771e6b3d0b827fb0cea0857f719",
}
SECURITY = {
    "SMITE_NODE_PANEL_AUTH_MODE": "paused",
    "SMITE_AGENT_AUTH_MODE": "strict",
    "SMITE_ENGINE_INVENTORY_MODE": "managed",
}


class Hold(Exception):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise Hold(message)


def safe_file(path: Path, *, limit: int = 256000) -> bytes:
    try:
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0
                and before.st_nlink == 1 and not (before.st_mode & 0o022)
                and before.st_size <= limit, "Unsafe file metadata")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as f:
            now = os.fstat(f.fileno())
            require((now.st_dev, now.st_ino) == (before.st_dev, before.st_ino)
                    and now.st_size <= limit, "File changed during inspection")
            value = f.read(limit + 1)
        require(len(value) <= limit, "Unexpected file size")
        return value
    except OSError as exc:
        raise Hold("Reviewed file unavailable") from exc


def sha256_file(path: Path, expected: str) -> None:
    # Chunked, open-no-follow inspection of larger read-only backups.
    try:
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0
                and before.st_nlink == 1 and not (before.st_mode & 0o022),
                "Backup file metadata unsafe")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as f:
            now = os.fstat(f.fileno())
            require((now.st_dev, now.st_ino) == (before.st_dev, before.st_ino),
                    "Backup file changed")
            digest = hashlib.sha256()
            while True:
                part = f.read(1024 * 1024)
                if not part:
                    break
                digest.update(part)
        require(digest.hexdigest() == expected, "Backup SHA256 mismatch")
    except OSError as exc:
        raise Hold("Reviewed backup unavailable") from exc


def exact_node_image_plan(original: bytes) -> bytes:
    require(hashlib.sha256(original).hexdigest() == COMPOSE_SHA,
            "Frozen KH Compose SHA256 mismatch")
    old = ("    image: " + RC1_NODE + "\n").encode()
    new = ("    image: " + RC2_NODE + "\n").encode()
    lines = original.splitlines(keepends=True)
    indexes = [i for i, line in enumerate(lines) if line == old]
    require(len(indexes) == 1, "Expected exact whole Node image line unavailable")
    lines[indexes[0]] = new
    candidate = b"".join(lines)
    lines[indexes[0]] = old
    require(b"".join(lines) == original, "Node Compose round-trip failed")
    return candidate


def run(command: list[str]) -> str:
    try:
        out = subprocess.run(command, capture_output=True, text=True,
                             check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("Read-only runtime check unavailable") from exc
    require(out.returncode == 0 and len(out.stdout) < 1_000_000,
            "Read-only runtime check failed")
    return out.stdout.strip()


def read_state(raw: bytes) -> dict[str, str]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise Hold("Managed state encoding invalid") from exc
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        require(bool(sep) and bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", key))
                and key not in values, "Managed state malformed")
        values[key] = value
    return values


def audit(*, read_file=safe_file, execute=run, check_backup=sha256_file) -> dict[str, str]:
    original = read_file(NODE_COMPOSE)
    candidate = exact_node_image_plan(original)

    state = read_state(read_file(STATE, limit=16384))
    require(state.get("SMITE_ROLE") == "foreign"
            and state.get("SMITE_CONNECTION_MODE") == "standard"
            and state.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.1",
            "KH exact paused RC.1 state not present")

    for name, expected in BACKUPS.items():
        check_backup(Path(name), expected)

    raw = execute(["docker", "compose", "-f", str(NODE_COMPOSE),
                   "config", "--format", "json"])
    try:
        compose = json.loads(raw)
        node = compose["services"]["smite-node"]
    except (KeyError, ValueError, TypeError) as exc:
        raise Hold("Effective KH Node Compose invalid") from exc
    require(node.get("image") == RC1_NODE, "KH Compose Node image not RC.1")
    require(node.get("container_name") == "smite-node"
            and node.get("network_mode") == "host"
            and "healthcheck" in node, "KH Node Compose layout changed")
    require(isinstance(node.get("environment"), dict),
            "KH effective Node auth environment unavailable")
    for key, value in SECURITY.items():
        require(node["environment"].get(key) == value,
                "KH paused/strict/managed Node security drift")

    require(execute(["docker", "inspect", "-f", "{{.Config.Image}}", "smite-node"])
            == RC1_NODE, "Running KH Node digest drift")
    require(execute(["docker", "inspect", "-f", "{{.State.Health.Status}}", "smite-node"])
            == "healthy", "Running KH Node not healthy")
    require(execute(["docker", "inspect", "-f", "{{.Image}}", "3xui-01"])
            == SANAEI_IMAGE, "Sanaei image ID drift")
    require(execute(["docker", "inspect", "-f", "{{.State.Status}}", "3xui-01"])
            == "running", "Sanaei is not running")

    listening = execute(["ss", "-H", "-lnt"])
    found = [line.split()[3] for line in listening.splitlines()
             if len(line.split()) >= 4 and line.split()[3].endswith(":8888")]
    require(found and all(local in ("127.0.0.1:8888", "[::1]:8888")
                          for local in found), "Node 8888 not exclusively loopback")
    execute(["nginx", "-t"])
    guard = execute(["python3", "-B",
                     "/usr/local/lib/u-opti/modules/docker-3xui-xhttp-guard.py",
                     "--instance", "01", "--check"])
    require("XHTTP_REVIEW=PASS" in guard and "ROUTES=1" in guard
            and "LEGACY_ROUTE=NO" in guard, "Sanaei XHTTP guard changed")

    return {
        "KH_NODE_RC1_BASELINE": "PASS",
        "KH_NODE_SECURITY": "PAUSED_STRICT_MANAGED",
        "KH_SANAEI_AND_XHTTP": "UNCHANGED",
        "KH_BACKUP_HASHES": "PASS",
        "KH_ORIGINAL_COMPOSE_SHA256": COMPOSE_SHA,
        "KH_PROPOSED_COMPOSE_SHA256": hashlib.sha256(candidate).hexdigest(),
        "KH_NODE_IMAGE_DIFF": "EXACT_ONE_LINE_REVERSIBLE",
        "KH_RC2_SIGNATURES": "PREVIOUSLY_VERIFIED_NOT_RECHECKED_HERE",
        "KH_RC2_UPGRADE_AUTHORIZED": "NO",
        "KH_FOREIGN_PAIRING": "NOT_ACTIVATED",
        "LIVE_CHANGES": "NONE",
    }


def main() -> int:
    print("===== KH RC2 NODE READ-ONLY PLAN =====")
    try:
        require(os.geteuid() == 0, "Root required for safe audit")
        for key, value in audit().items():
            print(key + "=" + value)
    except (Hold, OSError, ValueError, TypeError):
        print("KH_RC2_NODE_PLAN=HOLD")
        print("LIVE_CHANGES=NONE")
        return 2
    print("KH_RC2_NODE_PLAN=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
