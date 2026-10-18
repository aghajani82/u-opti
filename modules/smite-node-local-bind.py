#!/usr/bin/env python3
"""Prepare a persistent, restricted Smite Node API listener in Docker Compose.

Smite's pinned node image starts Uvicorn with --host 0.0.0.0; setting an env
variable does not fix it. This overrides the CMD in the existing Compose.
Standard (HTTPS/443) binds to loopback; Private Network binds to its explicitly
configured private IPv4, preserving private-mode connectivity.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import ipaddress
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile


def bind_host(mode: str, private_ip: str) -> str:
    if mode == "standard":
        if private_ip:
            raise ValueError("Standard mode does not use a private Node API IPv4")
        return "127.0.0.1"
    if mode == "private":
        if not private_ip:
            raise ValueError("Private mode needs its already-configured private IPv4")
        address = ipaddress.ip_address(private_ip)
        if address.version != 4 or address.is_unspecified or address.is_loopback or address.is_multicast:
            raise ValueError("Private mode requires a real private-network IPv4")
        return str(address)
    raise ValueError("Unknown connection mode")


def command_line(host: str) -> str:
    # $$ escapes Compose interpolation; shell expands NODE_API_PORT at runtime.
    return (
        '    command: ["/bin/sh", "-c", '
        f"'exec uvicorn main:app --host {host} --port "
        "\"$${NODE_API_PORT:-8888}\" --log-level info --access-log']\n"
    )


def transform(original: str, host: str) -> tuple[str, bool]:
    anchor = "    container_name: smite-node\n"
    if original.count("  smite-node:\n") != 1 or original.count(anchor) != 1:
        raise ValueError("Expected exactly one Smite Node service")
    if original.count("    network_mode: host\n") != 1:
        raise ValueError("Expected host-network Smite Node; refusing unknown layout")
    start = original.index("  smite-node:\n")
    rest = original[start + len("  smite-node:\n"):]
    boundary = re.search(r"^(?:  [a-zA-Z][\w-]*|[a-zA-Z][\w-]*):[^\n]*$", rest, re.M)
    block = rest[:boundary.start()] if boundary else rest

    target = command_line(host)
    commands = re.findall(r"^    command:.*$", block, re.M)
    if commands:
        if len(commands) == 1 and commands[0] == target.strip():
            return original, False
        raise ValueError("Existing Smite Node command conflicts with safe bind")
    if re.search(r"^    entrypoint:", block, re.M):
        raise ValueError("Unexpected Smite Node entrypoint")
    return original.replace(anchor, anchor + target, 1), True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("compose", type=Path)
    ap.add_argument("--mode", choices=("standard", "private"), required=True)
    ap.add_argument("--private-ip", default="")
    args = ap.parse_args()
    try:
        host = bind_host(args.mode, args.private_ip)
        path = args.compose
        if path.is_symlink() or not path.is_file():
            raise ValueError("Expected existing regular Compose file, not a symlink")
        updated, changed = transform(path.read_text(encoding="utf-8"), host)
        if not changed:
            print(f"SMITE_NODE_BIND=UNCHANGED host={host}")
            return 0

        backup = path.with_name(path.name + ".bind-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".bak")
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
        original_mode = stat.S_IMODE(path.stat().st_mode)
        stage = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=".smite-node-local-",
                delete=False
            ) as f:
                stage = Path(f.name)
                f.write(updated)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(stage, original_mode)
            os.replace(stage, path)
            stage = None
        finally:
            if stage is not None:
                stage.unlink(missing_ok=True)
        print(f"SMITE_NODE_BIND=PREPARED host={host}")
        print(f"BACKUP={backup}")
        print("Restart smite-node to activate.")
        return 0
    except (ValueError, OSError) as e:
        print(f"HOLD: No listener change: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
