#!/usr/bin/env python3
"""Prepare inert clean-RC Compose mounts for the IR XHTTP Broker key.

This only edits freshly downloaded candidate Compose files. It never starts
containers, enables the Broker, or creates a TrustedGrant.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile


PANEL_MOUNT = (
    "      - /etc/u-opti/smite/route-broker.key:"
    "/run/secrets/smite-uopti-xhttp-broker.key:ro\n"
)
NODE_SOCKET_MOUNT = "      - /run/u-opti/smite:/run/u-opti/smite:ro\n"
NODE_USER = '    user: "0:${SMITE_UOPTI_BROKER_GID:-0}"\n'


class ComposeHold(RuntimeError):
    pass


def _read(path: Path) -> tuple[bytes, int]:
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_mode & 0o022):
            raise ComposeHold("UNTRUSTED_COMPOSE_CANDIDATE")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            actual = os.fstat(fd)
            if (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino):
                raise ComposeHold("COMPOSE_CANDIDATE_CHANGED")
            data = os.read(fd, 1024 * 1024 + 1)
        finally:
            os.close(fd)
        if len(data) != before.st_size or len(data) > 1024 * 1024:
            raise ComposeHold("COMPOSE_CANDIDATE_CHANGED")
        return data, stat.S_IMODE(before.st_mode)
    except OSError as exc:
        raise ComposeHold("COMPOSE_CANDIDATE_UNAVAILABLE") from exc


def _replace(path: Path, data: bytes, mode: int) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=".smite-broker-compose-", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        temp.unlink(missing_ok=True)


def prepare_panel(path: Path) -> None:
    raw, mode = _read(path)
    text = raw.decode("utf-8")
    marker = "  smite-panel:\n"
    if text.count(marker) != 1:
        raise ComposeHold("UNREVIEWED_PANEL_COMPOSE_LAYOUT")
    start = text.index(marker)
    next_service = re.search(r"^  [A-Za-z0-9_-]+:\s*$", text[start + len(marker):], re.M)
    end = start + len(marker) + next_service.start() if next_service else len(text)
    block = text[start:end]
    if block.count("    volumes:\n") != 1:
        raise ComposeHold("UNREVIEWED_PANEL_COMPOSE_LAYOUT")
    if PANEL_MOUNT.strip() in text:
        return
    if "/run/secrets/smite-uopti-xhttp-broker.key" in block:
        raise ComposeHold("CONFLICTING_PANEL_BROKER_MOUNT")
    anchor = "      - ./docker-compose.yml:/app/config/docker-compose.yml:ro\n"
    if block.count(anchor) != 1:
        raise ComposeHold("UNREVIEWED_PANEL_VOLUME_LAYOUT")
    index = start + block.index(anchor)
    updated = text[:index] + anchor + PANEL_MOUNT + text[index + len(anchor):]
    _replace(path, updated.encode("utf-8"), mode)


def verify_node(path: Path, peer_gid: int) -> None:
    raw, _mode = _read(path)
    text = raw.decode("utf-8")
    marker = "  smite-node:\n"
    if text.count(marker) != 1:
        raise ComposeHold("UNREVIEWED_NODE_COMPOSE_LAYOUT")
    start = text.index(marker)
    next_service = re.search(r"^  [A-Za-z0-9_-]+:\s*$", text[start + len(marker):], re.M)
    end = start + len(marker) + next_service.start() if next_service else len(text)
    block = text[start:end]
    if block.count(NODE_SOCKET_MOUNT) != 1 or block.count(NODE_USER) != 1:
        raise ComposeHold("NODE_BROKER_PEER_MOUNT_UNAVAILABLE")
    if not 1 <= peer_gid < 65536:
        raise ComposeHold("INVALID_BROKER_PEER_GID")
    if "/route-broker.key" in block:
        raise ComposeHold("BROKER_KEY_MUST_NOT_BE_MOUNTED_IN_NODE")


def prepare_node(path: Path, peer_gid: int) -> None:
    """Add the exact read-only Broker socket peer mount to a fresh Node candidate."""
    if not 1 <= peer_gid < 65536:
        raise ComposeHold("INVALID_BROKER_PEER_GID")
    raw, mode = _read(path)
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ComposeHold("UNREADABLE_COMPOSE_CANDIDATE") from exc
    marker = "  smite-node:\n"
    if text.count(marker) != 1:
        raise ComposeHold("UNREVIEWED_NODE_COMPOSE_LAYOUT")
    start = text.index(marker)
    next_service = re.search(r"^  [A-Za-z0-9_-]+:\s*$", text[start + len(marker):], re.M)
    end = start + len(marker) + next_service.start() if next_service else len(text)
    block = text[start:end]
    if "/route-broker.key" in block:
        raise ComposeHold("BROKER_KEY_MUST_NOT_BE_MOUNTED_IN_NODE")
    user_lines = re.findall(r"^    user:.*$", block, re.M)
    if user_lines and user_lines != [NODE_USER.rstrip("\n")]:
        raise ComposeHold("CONFLICTING_NODE_BROKER_USER")
    mount_lines = [line for line in block.splitlines(keepends=True)
                   if "/run/u-opti/smite" in line]
    if mount_lines and mount_lines != [NODE_SOCKET_MOUNT]:
        raise ComposeHold("CONFLICTING_NODE_BROKER_MOUNT")
    if block.count("    volumes:\n") != 1:
        raise ComposeHold("UNREVIEWED_NODE_VOLUME_LAYOUT")
    config_mount = "      - ./config:/etc/smite-node\n"
    if block.count(config_mount) != 1:
        raise ComposeHold("UNREVIEWED_NODE_CONFIG_MOUNT")
    container_anchor = "    container_name: smite-node\n"
    if not user_lines and block.count(container_anchor) != 1:
        raise ComposeHold("UNREVIEWED_NODE_CONTAINER_LAYOUT")
    updated = text
    if not user_lines:
        updated = updated.replace(container_anchor, container_anchor + NODE_USER, 1)
    if not mount_lines:
        updated = updated.replace(config_mount, config_mount + NODE_SOCKET_MOUNT, 1)
    if updated != text:
        _replace(path, updated.encode("utf-8"), mode)
    verify_node(path, peer_gid)

def set_node_broker_enabled(path: Path, enabled: bool) -> None:
    """Atomically toggle only the IR Node's root-broker forwarding flag."""
    if type(enabled) is not bool:
        raise ComposeHold("INVALID_NODE_BROKER_STATE")
    raw, mode = _read(path)
    if mode != 0o600:
        raise ComposeHold("UNTRUSTED_NODE_ENV")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ComposeHold("UNREADABLE_NODE_ENV") from exc
    key = "SMITE_UOPTI_ROUTE_BROKER_ENABLED"
    lines = text.splitlines(keepends=True)
    found = 0
    updated = []
    for line in lines:
        content = line.rstrip("\r\n")
        if content.startswith(key + "="):
            found += 1
            if content not in (f"{key}=false", f"{key}=true"):
                raise ComposeHold("INVALID_NODE_BROKER_STATE")
            updated.append(f"{key}={'true' if enabled else 'false'}\n")
        else:
            updated.append(line)
    if found != 1:
        raise ComposeHold("NODE_BROKER_FLAG_MISSING_OR_DUPLICATE")
    fd, temp_name = tempfile.mkstemp(prefix=".smite-broker-node-env-", dir=path.parent)
    temp = Path(temp_name)
    try:
        os.fchown(fd, os.geteuid(), os.getegid())
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write("".join(updated).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("panel", "node", "node-prepare", "node-env"))
    parser.add_argument("compose", type=Path, help="Compose file or Node .env for node-env")
    parser.add_argument("--peer-gid", type=int)
    parser.add_argument("--enabled", choices=("true", "false"))
    args = parser.parse_args()
    try:
        if args.operation == "node-env":
            if args.enabled is None or args.peer_gid is not None:
                raise ComposeHold("NODE_BROKER_STATE_ARGUMENTS_INVALID")
            set_node_broker_enabled(args.compose, args.enabled == "true")
            print("NODE_BROKER_FORWARDING=" + ("ENABLED" if args.enabled == "true" else "DISABLED"))
            return 0
        if args.peer_gid is None or not 1 <= args.peer_gid < 65536:
            raise ComposeHold("INVALID_BROKER_PEER_GID")
        if args.enabled is not None:
            raise ComposeHold("UNEXPECTED_NODE_BROKER_STATE")
        if args.operation == "panel":
            prepare_panel(args.compose)
            print("PANEL_BROKER_KEY_MOUNT=PASS_READ_ONLY")
        else:
            if args.operation == "node-prepare":
                prepare_node(args.compose, args.peer_gid)
            verify_node(args.compose, args.peer_gid)
            print("NODE_BROKER_SOCKET_PEER=PASS_UID0_DEDICATED_GID")
        print("BROKER_SERVICE=NOT_ACTIVATED")
        print("TRUSTED_GRANTS=NONE")
        return 0
    except (ComposeHold, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, ComposeHold) else "COMPOSE_PREPARATION_FAILED"
        print(f"HOLD_{reason}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
