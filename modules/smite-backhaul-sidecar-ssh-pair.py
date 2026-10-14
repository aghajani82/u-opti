#!/usr/bin/env python3
"""Opt-in, TEST-HOST ONLY Backhaul token pairing over pre-trusted SSH.

Run --send-ir on IR to generate (if missing) and deliver the private token to
a trusted KH host; run --receive-kh only via an already authenticated SSH
session on KH. This does not set up SSH credentials, enroll host keys, install
the Sidecar or change Nginx/FRP/Smite/Xray. Refuses unknown/active hosts.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
STATE = Path("/etc/u-opti/smite/state.env")
PRIVATE_DIR = Path("/etc/u-opti/backhaul-sidecar")
TOKEN = PRIVATE_DIR / "shared.token"
REMOTE_TOOL = "/usr/local/lib/u-opti/modules/smite-backhaul-sidecar-ssh-pair.py"
PATTERN = re.compile(rb"[A-Za-z0-9_-]{24,128}\Z")


def _load(alias: str, name: str):
    spec = importlib.util.spec_from_file_location(alias, HERE / name)
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing local Backhaul module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


token_tool = _load("pair_token", "smite-backhaul-sidecar-token.py")
readiness = _load("pair_readiness", "smite-backhaul-sidecar-readiness.py")
sidecar = _load("pair_sidecar", "smite-backhaul-sidecar.py")


class PairingHold(ValueError):
    pass


def _trusted_role(role: str) -> None:
    if os.geteuid() != 0 or role not in ("ir", "kh"):
        raise PairingHold("Root and correct role required")
    info = STATE.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_gid != 0 or info.st_size > 4096
            or stat.S_IMODE(info.st_mode) & 0o022):
        raise PairingHold("Smite state file ownership or mode invalid")
    lines = STATE.read_text(encoding="utf-8").splitlines()
    settings: dict[str, str] = {}
    for line in lines:
        if line.startswith(("SMITE_ROLE=", "SMITE_CONNECTION_MODE=")):
            k, v = line.partition("=")[::2]
            if k in settings:
                raise PairingHold("Duplicate Smite state key")
            settings[k] = v.strip().strip('"').strip("'")
    expected = "panel-iran" if role == "ir" else "foreign"
    if (settings.get("SMITE_ROLE") != expected
            or settings.get("SMITE_CONNECTION_MODE") != "standard"):
        raise PairingHold("Not the requested standard-mode Smite role")


def _fresh(role: str) -> None:
    issues = readiness.inspect_local(role, "new")
    if issues:
        raise PairingHold("Fresh-host readiness HOLD; never change a running Sidecar")


def _safe_parents() -> None:
    for parent in (Path("/etc/u-opti"), PRIVATE_DIR):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            if parent == PRIVATE_DIR:
                continue
            raise PairingHold("U-OPTI installation directory missing")
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_gid != 0 or stat.S_IMODE(info.st_mode) & 0o022):
            raise PairingHold("Private token ancestor is unsafe")


def _payload(raw: bytes) -> bytes:
    if not raw or len(raw) > 130:
        raise PairingHold("Invalid pairing stream length")
    value = raw[:-1] if raw.endswith(b"\n") else raw
    if not PATTERN.fullmatch(value):
        raise PairingHold("Invalid pairing stream format")
    return value


def receive_kh(reader) -> str:
    """Create token exactly once on an authenticated, fresh KH host."""
    _trusted_role("kh")
    _safe_parents()
    value = _payload(reader.read(131))
    if TOKEN.exists() or TOKEN.is_symlink():
        if not token_tool.inspect(TOKEN):
            raise PairingHold("Existing KH token unsafe; no overwrite")
        if not secrets.compare_digest(_payload(TOKEN.read_bytes()), value):
            raise PairingHold("Existing KH token differs; no overwrite")
        return "KH_PAIRING_ALREADY_MATCHED_NO_CHANGE"
    _fresh("kh")
    if not PRIVATE_DIR.exists():
        PRIVATE_DIR.mkdir(mode=0o700)
    if not token_tool.secure_dir(PRIVATE_DIR):
        raise PairingHold("Private KH token directory not secure")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(TOKEN, flags, 0o600)
    with os.fdopen(fd, "wb") as dst:
        os.fchmod(dst.fileno(), 0o600)
        dst.write(value + b"\n")
        dst.flush()
        os.fsync(dst.fileno())
    if not token_tool.inspect(TOKEN):
        raise PairingHold("KH token post-write verification failed")
    parent_fd = os.open(PRIVATE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return "KH_PAIRING_RECEIVED_PRIVATE_AND_VALID"


def _ssh_args(host: str, port: int) -> list[str]:
    sidecar.validated_domain(host)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise PairingHold("SSH port must be 1-65535")
    # -F /dev/null prevents unsafe client config options overriding policy.
    # Existing pinned known_hosts and key-only auth are mandatory. Never TOFU.
    return [
        "ssh", "-T", "-F", "/dev/null", "-p", str(port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "UserKnownHostsFile=/root/.ssh/known_hosts",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "PreferredAuthentications=publickey",
        "-o", "ForwardAgent=no",
        "-o", "ClearAllForwardings=yes",
        "-o", "ConnectTimeout=8",
        "-o", "ConnectionAttempts=1",
        "-o", "LogLevel=ERROR",
        "root@" + host,
        "python3", "-B", REMOTE_TOOL,
        "--receive-kh", "--confirm", "RECEIVE-KH-PAIRING",
    ]


def send_ir(host: str, port: int) -> str:
    """Only the token is sent over SSH stdin. Never on argv/stdout/logs."""
    _trusted_role("ir")
    _safe_parents()
    argv = _ssh_args(host, port)
    _fresh("ir")
    if not TOKEN.exists() and not TOKEN.is_symlink():
        token_tool.generate()
    if not token_tool.inspect(TOKEN):
        raise PairingHold("IR token absent or unsafe")
    data = TOKEN.read_bytes()
    _payload(data)
    try:
        result = subprocess.run(
            argv, input=data, capture_output=True, timeout=25, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PairingHold("Authenticated SSH pairing unavailable") from exc
    # Do not echo untrusted remote output or SSH error messages. Only exact
    # predefined success codes may be shown to the operator.
    allowed = {b"KH_PAIRING_RECEIVED_PRIVATE_AND_VALID\n",
               b"KH_PAIRING_ALREADY_MATCHED_NO_CHANGE\n"}
    if result.returncode or result.stdout not in allowed:
        raise PairingHold("KH pairing HOLD: trusted SSH, remote role or token check failed")
    return "IR_TO_KH_PRIVATE_SSH_PAIRING_PASSED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--send-ir", action="store_true")
    mode.add_argument("--receive-kh", action="store_true")
    parser.add_argument("--kh-host")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.send_ir:
        if args.confirm != "PAIR-KH-TEST-HOST" or not args.kh_host:
            print("HOLD: Exact IR pairing consent and KH host required.")
            return 2
        try:
            result = send_ir(args.kh_host, args.ssh_port)
        except Exception:
            print("HOLD: Secure pairing refused; existing files are never overwritten.")
            print("Verify trusted SSH host key and key-only access; no secret displayed.")
            return 2
    else:
        if args.confirm != "RECEIVE-KH-PAIRING":
            print("HOLD: Exact KH receive consent required.")
            return 2
        try:
            result = receive_kh(sys.stdin.buffer)
        except Exception:
            print("HOLD: KH pairing refused; no existing token replaced.")
            return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
