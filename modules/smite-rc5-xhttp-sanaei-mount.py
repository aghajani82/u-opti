#!/usr/bin/env python3
"""Enable the existing KH-only read-only Sanaei inventory mount.

The helper accepts only a registered U-OPTI instance ID, validates the
root-owned database file without opening it, and updates only the clean-RC
Node .env. It never queries Sanaei's API or copies client data. The Compose
mount targets the database directory so SQLite WAL/SHM companions are visible
read-only alongside x-ui.db.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile


INSTANCE_ID = re.compile(r"[0-9]{2}\Z")
MOUNT = "      - ${SMITE_SANAEI_DB_HOST_PATH:-/var/lib/u-opti/smite-sanaei-empty}:/run/smite-sanaei-ro:ro"
FLAG = "      - SMITE_SANAEI_INVENTORY_ENABLED=${SMITE_SANAEI_INVENTORY_ENABLED:-false}"
ENV_KEYS = {
    "SMITE_SANAEI_DB_HOST_PATH": None,
    "SMITE_SANAEI_INVENTORY_ENABLED": "true",
}


class MountHold(ValueError):
    pass


def _under(root: Path, absolute: str) -> Path:
    if not isinstance(absolute, str) or not absolute.startswith("/") or ".." in Path(absolute).parts:
        raise MountHold("UNAPPROVED_HOST_PATH")
    return root / absolute.lstrip("/")


def _trusted_regular(path: Path, *, owner_uid: int, allowed_modes: set[int] | None = None,
                     max_size: int = 128 * 1024 * 1024,
                     read_data: bool = True) -> tuple[os.stat_result, bytes]:
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner_uid
                or before.st_nlink != 1 or before.st_mode & 0o022
                or (allowed_modes is not None and stat.S_IMODE(before.st_mode) not in allowed_modes)
                or not 0 < before.st_size <= max_size):
            raise MountHold("UNTRUSTED_HOST_FILE")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
                raise MountHold("HOST_FILE_CHANGED")
            chunks = bytearray()
            if read_data:
                while len(chunks) <= max_size:
                    part = os.read(fd, min(65536, max_size + 1 - len(chunks)))
                    if not part:
                        break
                    chunks.extend(part)
            after = os.fstat(fd)
            if (after.st_dev, after.st_ino, after.st_size) != (
                    current.st_dev, current.st_ino, current.st_size):
                raise MountHold("HOST_FILE_CHANGED")
        finally:
            os.close(fd)
        if read_data and len(chunks) != before.st_size:
            raise MountHold("HOST_FILE_CHANGED")
        return before, bytes(chunks)
    except OSError as exc:
        raise MountHold("HOST_FILE_UNAVAILABLE") from exc


def _validate_instance_db(root: Path, instance_id: str) -> str:
    if type(instance_id) is not str or not INSTANCE_ID.fullmatch(instance_id):
        raise MountHold("INVALID_SANAEI_INSTANCE_ID")
    relative = f"/opt/3x-ui/instances/{instance_id}/db/x-ui.db"
    path = _under(root, relative)
    expected_dir = _under(root, f"/opt/3x-ui/instances/{instance_id}")
    owner_uid = 0 if root == Path("/") else os.geteuid()
    try:
        current = root
        for part in Path(relative.lstrip("/")).parts[:-1]:
            current = current / part
            info = current.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
                    or info.st_mode & 0o022):
                raise MountHold("UNTRUSTED_SANAEI_INSTANCE_DIRECTORY")
        if path.is_symlink() or expected_dir.is_symlink():
            raise MountHold("SANAEI_DATABASE_SYMLINK")
        _trusted_regular(path, owner_uid=owner_uid, read_data=False)
    except MountHold:
        raise
    except OSError as exc:
        raise MountHold("SANAEI_DATABASE_UNAVAILABLE") from exc
    return f"/opt/3x-ui/instances/{instance_id}/db"


def _write_env(root: Path, env_absolute: str, compose_absolute: str,
               instance_id: str) -> None:
    env_path = _under(root, env_absolute)
    compose_path = _under(root, compose_absolute)
    owner_uid = 0 if root == Path("/") else os.geteuid()
    env_stat, env_raw = _trusted_regular(
        env_path, owner_uid=owner_uid, allowed_modes={0o600}, max_size=256 * 1024
    )
    _compose_stat, compose_raw = _trusted_regular(
        compose_path, owner_uid=owner_uid, max_size=1024 * 1024
    )
    try:
        compose = compose_raw.decode("utf-8")
        env = env_raw.decode("utf-8")
    except UnicodeError as exc:
        raise MountHold("UNREADABLE_NODE_CONFIGURATION") from exc
    if compose.count(MOUNT) != 1 or compose.count(FLAG) != 1:
        raise MountHold("UNREVIEWED_NODE_COMPOSE_LAYOUT")

    values = {
        "SMITE_SANAEI_DB_HOST_PATH": f"/opt/3x-ui/instances/{instance_id}/db",
        "SMITE_SANAEI_INVENTORY_ENABLED": "true",
    }
    lines = env.splitlines(keepends=True)
    seen: set[str] = set()
    updated: list[str] = []
    for line in lines:
        key, separator, _value = line.partition("=")
        if separator and key in ENV_KEYS:
            if key in seen:
                raise MountHold("DUPLICATE_SANAEI_ENV_KEY")
            seen.add(key)
            updated.append(f"{key}={values[key]}\n")
        else:
            updated.append(line)
    if updated and not updated[-1].endswith(("\n", "\r")):
        updated[-1] += "\n"
    for key, value in values.items():
        if key not in seen:
            updated.append(f"{key}={value}\n")
    result = "".join(updated).encode("utf-8")

    fd, temp_name = tempfile.mkstemp(prefix=".smite-sanaei-env-", dir=env_path.parent)
    temp = Path(temp_name)
    try:
        os.fchown(fd, owner_uid, env_stat.st_gid)
        os.fchmod(fd, stat.S_IMODE(env_stat.st_mode))
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, env_path)
        dir_fd = os.open(env_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        temp.unlink(missing_ok=True)


def configure(*, root: Path, instance_id: str, node_env: str,
              node_compose: str, confirm_foreign_node: bool) -> None:
    if not confirm_foreign_node:
        raise MountHold("FOREIGN_NODE_CONFIRMATION_REQUIRED")
    if root != Path("/"):
        try:
            root_stat = root.lstat()
        except OSError as exc:
            raise MountHold("UNTRUSTED_TEST_ROOT") from exc
        if (root.is_symlink() or not stat.S_ISDIR(root_stat.st_mode)
                or root_stat.st_uid != os.geteuid()
                or stat.S_IMODE(root_stat.st_mode) != 0o700):
            raise MountHold("UNTRUSTED_TEST_ROOT")
    if root == Path("/") and os.geteuid() != 0:
        raise MountHold("ROOT_REQUIRED")
    host_path = _validate_instance_db(root, instance_id)
    _write_env(root, node_env, node_compose, instance_id)
    print("SANAEI_DB=PASS_REGISTERED_ROOT_OWNED_FILE")
    print("SANAEI_MOUNT=PASS_KH_NODE_READ_ONLY")
    print("SANAEI_HOST_PATH=" + host_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--node-env", required=True)
    parser.add_argument("--node-compose", required=True)
    parser.add_argument("--confirm-foreign-node", action="store_true")
    args = parser.parse_args()
    try:
        configure(
            root=args.root, instance_id=args.instance_id,
            node_env=args.node_env, node_compose=args.node_compose,
            confirm_foreign_node=args.confirm_foreign_node,
        )
        return 0
    except (MountHold, OSError) as exc:
        reason = str(exc) if isinstance(exc, MountHold) else "SANAEI_MOUNT_PREPARATION_FAILED"
        print(f"HOLD_{reason}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
