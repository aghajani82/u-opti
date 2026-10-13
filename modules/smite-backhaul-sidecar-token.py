#!/usr/bin/env python3
"""Root-only, opt-in IR token initialization; never print or transmit the token.

For pairing KH, transfer /etc/u-opti/backhaul-sidecar/shared.token with an
authenticated SFTP client, then verify permissions on KH. No passwords or
tokens are passed as command-line arguments or written into history.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import secrets
import stat

TOKEN_DIR = Path("/etc/u-opti/backhaul-sidecar")
TOKEN_FILE = TOKEN_DIR / "shared.token"


class TokenRefused(ValueError):
    pass


def secure_dir(directory: Path) -> bool:
    try:
        info = directory.lstat()
        return (stat.S_ISDIR(info.st_mode) and info.st_uid == 0
                and info.st_gid == 0
                and stat.S_IMODE(info.st_mode) & 0o077 == 0)
    except OSError:
        return False


def inspect(path: Path = TOKEN_FILE) -> bool:
    try:
        item = path.lstat()
        if (not secure_dir(path.parent)
                or not stat.S_ISREG(item.st_mode)
                or item.st_uid != 0 or item.st_gid != 0
                or stat.S_IMODE(item.st_mode) != 0o600
                or not 25 <= item.st_size <= 130):
            return False
        value = path.read_bytes().strip()
        return 24 <= len(value) <= 128 and all(
            (48 <= c <= 57) or (65 <= c <= 90) or (97 <= c <= 122) or c in b"_-"
            for c in value)
    except (OSError, ValueError):
        return False


def generate(directory: Path = TOKEN_DIR) -> None:
    if os.geteuid() != 0:
        raise TokenRefused("Root required")
    if directory.is_symlink():
        raise TokenRefused("Unsafe token directory")
    if not directory.exists():
        directory.mkdir(mode=0o700)
    if not secure_dir(directory):
        raise TokenRefused("Existing private token directory has unsafe ownership/mode")
    path = directory / "shared.token"
    value = secrets.token_urlsafe(32).encode("ascii") + b"\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
    except FileExistsError as exc:
        raise TokenRefused("Pairing token already exists; NO OVERWRITE") from exc
    with os.fdopen(fd, "wb") as file:
        os.fchmod(file.fileno(), 0o600)
        file.write(value)
        file.flush()
        os.fsync(file.fileno())
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate-ir", action="store_true")
    group.add_argument("--verify", action="store_true")
    parser.add_argument("--confirm", default="")
    opts = parser.parse_args()
    if opts.verify:
        if inspect():
            print("PRIVATE_PAIRING_TOKEN_PRESENT_AND_VALID")
            return 0
        print("HOLD: Pairing token missing or unsafe.")
        return 2
    if opts.confirm != "CREATE-IR-PAIRING-TOKEN":
        print("HOLD: IR token creation requires exact confirmation.")
        return 2
    try:
        generate()
    except (OSError, TokenRefused):
        print("HOLD: Token creation refused; no secret disclosed.")
        return 2
    print("IR pairing token created privately (no token shown).")
    print("Transfer securely to KH using authenticated SFTP, never chat/logs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
