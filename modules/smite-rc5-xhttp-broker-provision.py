#!/usr/bin/env python3
"""Provision and explicitly activate the IR U-OPTI route broker.

Installs a dedicated key, empty TrustedGrant directory, durable nonce ledger,
pinned local worker/planner, root-owned config, and a systemd unit. Provisioning
is inert; a separate explicit activation enables the persistent service. Neither
mode creates grants from requests, mounts secrets into Panel/Node, or changes
Nginx. A missing grant keeps every route request HOLD.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import socket
import stat
import subprocess
import sys
import time

HELPER_SHA256 = "12eaff0492b184025199c7a266c6a8a592fd63f4baf6ddc86171884554ae32e2"
PLANNER_SHA256 = "dbb07f59266f6e4f35d3d5ed6c9d9ec808eb35cfbf29e52ef0ae2e4f58a127b5"
BROKER_MODULE = "smite-rc5-xhttp-root-broker.py"
LEDGER_MODULE = "smite-rc5-xhttp-nonce-ledger.py"
HELPER_MODULE = "smite-xhttp-nginx-route"
PLANNER_MODULE = "smite_xhttp_nginx_plan.py"
SERVICE_NAME = "u-opti-smite-xhttp-broker.service"
PEER_GROUP_NAME = "u-opti-smite-peer"
BROKER_STARTUP_TIMEOUT = 10.0
BROKER_STARTUP_POLL = 0.1
IDENT = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
GRANT_PATH = re.compile(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z")


class ProvisionHold(RuntimeError):
    pass


def _ensure_peer_group(peer_gid: int, runner) -> None:
    """Ensure the Node's primary GID resolves to a dedicated host group."""
    def lookup(key: str) -> str | None:
        try:
            result = runner(["getent", "group", key], check=False,
                            capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProvisionHold("BROKER_PEER_GROUP_LOOKUP_FAILED") from exc
        if result.returncode != 0:
            return None
        fields = result.stdout.strip().split(":")
        if len(fields) < 3 or not fields[2].isascii() or not fields[2].isdecimal():
            raise ProvisionHold("BROKER_PEER_GROUP_LOOKUP_INVALID")
        return result.stdout.strip()

    by_name = lookup(PEER_GROUP_NAME)
    by_gid = lookup(str(peer_gid))
    if by_name is None and by_gid is None:
        try:
            result = runner(["groupadd", "--system", "--gid", str(peer_gid),
                             PEER_GROUP_NAME], check=False,
                            capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProvisionHold("BROKER_PEER_GROUP_CREATE_FAILED") from exc
        if result.returncode != 0:
            raise ProvisionHold("BROKER_PEER_GROUP_CREATE_FAILED")
        by_name = lookup(PEER_GROUP_NAME)
        by_gid = lookup(str(peer_gid))
    def matches(entry: str | None) -> bool:
        if entry is None:
            return False
        fields = entry.split(":")
        return fields[0] == PEER_GROUP_NAME and fields[2] == str(peer_gid)

    if not matches(by_name) or not matches(by_gid):
        raise ProvisionHold("BROKER_PEER_GROUP_COLLISION")


def _check_root(root: Path) -> None:
    if not root.is_absolute() or ".." in root.parts or root.is_symlink():
        raise ProvisionHold("UNTRUSTED_PROVISION_ROOT")
    try:
        info = root.lstat()
    except OSError as exc:
        raise ProvisionHold("PROVISION_ROOT_UNAVAILABLE") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
        raise ProvisionHold("PROVISION_ROOT_NOT_ROOT_OWNED")
    if root != Path("/") and stat.S_IMODE(info.st_mode) != 0o700:
        raise ProvisionHold("TEST_ROOT_MUST_BE_PRIVATE")


def _ensure_dir(root: Path, relative: str, mode: int) -> Path:
    target = root / relative
    current = root
    parts = Path(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        final = index == len(parts) - 1
        wanted = mode if final else 0o755
        existed = current.exists() or current.is_symlink()
        try:
            current.mkdir(mode=wanted)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ProvisionHold("BROKER_DIRECTORY_CREATE_FAILED") from exc
        if not existed:
            try:
                os.chmod(current, wanted, follow_symlinks=False)
            except OSError as exc:
                raise ProvisionHold("BROKER_DIRECTORY_MODE_SET_FAILED") from exc
            _CREATED_DIRS.add(current)
        try:
            item = current.lstat()
        except OSError as exc:
            raise ProvisionHold("BROKER_DIRECTORY_UNAVAILABLE") from exc
        if not stat.S_ISDIR(item.st_mode) or item.st_uid != 0:
            raise ProvisionHold("UNTRUSTED_BROKER_DIRECTORY")
        if item.st_mode & 0o022:
            raise ProvisionHold("BROKER_DIRECTORY_WRITABLE_BY_OTHERS")
        if final and stat.S_IMODE(item.st_mode) != mode:
            # The RC6/RC7 install journal creates /var/lib/u-opti with
            # mode 0700 before this broker runs. Earlier broker-only setups
            # used 0755. Both are trusted root-owned and not group-writable.
            # Accept the narrower existing mode ONLY at this exact parent;
            # never chmod it wider, and keep all private children strict.
            journal_private_parent = (
                relative == "var/lib/u-opti"
                and mode == 0o755
                and stat.S_IMODE(item.st_mode) == 0o700
            )
            if not journal_private_parent:
                raise ProvisionHold("BROKER_DIRECTORY_MODE_MISMATCH")
    return target


def _validate_nginx_config_dir(root: Path) -> Path:
    """Require the real root-owned Nginx config directory; never create it."""
    nginx_config_dir = root / "etc/nginx"
    try:
        info = nginx_config_dir.lstat()
    except OSError as exc:
        raise ProvisionHold("NGINX_CONFIG_DIRECTORY_MISSING") from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022):
        raise ProvisionHold("NGINX_CONFIG_DIRECTORY_UNTRUSTED")
    return nginx_config_dir


def _ensure_nginx_route_dir(root: Path) -> Path:
    """Ensure only the dedicated empty route include directory exists."""
    nginx_config_dir = _validate_nginx_config_dir(root)
    route_dir = nginx_config_dir / "smite-xhttp-routes"
    created = False
    try:
        route_dir.mkdir(mode=0o755)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise ProvisionHold("BROKER_NGINX_ROUTE_DIRECTORY_CREATE_FAILED") from exc
    if created:
        try:
            os.chmod(route_dir, 0o755, follow_symlinks=False)
        except OSError as exc:
            raise ProvisionHold("BROKER_NGINX_ROUTE_DIRECTORY_MODE_SET_FAILED") from exc
    try:
        info = route_dir.lstat()
    except OSError as exc:
        raise ProvisionHold("BROKER_NGINX_ROUTE_DIRECTORY_UNAVAILABLE") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ProvisionHold("BROKER_NGINX_ROUTE_DIRECTORY_UNTRUSTED")
    if stat.S_IMODE(info.st_mode) != 0o755:
        raise ProvisionHold("BROKER_NGINX_ROUTE_DIRECTORY_MODE_MISMATCH")
    return route_dir


def _write_new(path: Path, data: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise ProvisionHold("BROKER_TARGET_EXISTS_REQUIRES_REVIEW") from exc
    except OSError as exc:
        raise ProvisionHold("BROKER_FILE_CREATE_FAILED") from exc
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=False) as out:
            out.write(data)
            out.flush()
            os.fsync(fd)
    except OSError as exc:
        raise ProvisionHold("BROKER_FILE_WRITE_FAILED_PARTIAL_STATE") from exc
    finally:
        os.close(fd)
    dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _replace_existing_trusted_file(path: Path, data: bytes, mode: int) -> None:
    """Atomically replace a known root-owned file without following path links."""
    parent = path.parent
    try:
        parent_info = parent.lstat()
        before = path.lstat()
    except OSError as exc:
        raise ProvisionHold("BROKER_UNIT_REPAIR_TARGET_MISSING") from exc
    if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != 0
            or parent_info.st_mode & 0o022):
        raise ProvisionHold("BROKER_UNIT_REPAIR_DIRECTORY_UNTRUSTED")
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != mode):
        raise ProvisionHold("BROKER_UNIT_REPAIR_TARGET_UNTRUSTED")

    dir_fd = -1
    fd = -1
    temp_name = f".{path.name}.uopti-{secrets.token_hex(8)}"
    try:
        dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     mode, dir_fd=dir_fd)
        os.fchown(fd, 0, 0)
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=False) as out:
            out.write(data)
            out.flush()
            os.fsync(fd)
        current = os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise ProvisionHold("BROKER_UNIT_REPAIR_TARGET_CHANGED")
        os.replace(temp_name, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
    except Exception as exc:
        if dir_fd >= 0:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except OSError:
                pass
        if isinstance(exc, ProvisionHold):
            raise
        raise ProvisionHold("BROKER_UNIT_REPAIR_FAILED") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if dir_fd >= 0:
            os.close(dir_fd)


def _ledger(source_dir: Path):
    path = source_dir / LEDGER_MODULE
    spec = importlib.util.spec_from_file_location("uopti_provision_ledger", path)
    if spec is None or spec.loader is None:
        raise ProvisionHold("BROKER_LEDGER_MODULE_MISSING")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _service_unit(peer_gid: int) -> bytes:
    body = f"""[Unit]
Description=U-OPTI Smite local XHTTP route broker
ConditionHost=ir*
After=local-fs.target
StartLimitIntervalSec=60s
StartLimitBurst=3

[Service]
Type=simple
User=root
Group={peer_gid}
WorkingDirectory=/usr/local/lib/u-opti/modules
ExecStart=/usr/bin/python3 -B /usr/local/lib/u-opti/modules/{BROKER_MODULE} --serve
RuntimeDirectory=u-opti/smite
RuntimeDirectoryMode=0750
RuntimeDirectoryPreserve=yes
UMask=0077
Restart=on-failure
RestartSec=3s
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=full
ReadWritePaths=/etc/nginx/smite-xhttp-routes
ReadWritePaths=/var/lib/u-opti/smite-xhttp-broker
ReadWritePaths=-/run/lock/u-opti-smite-engine.lock
ReadWritePaths=-/run/lock/smite-xhttp-nginx-route.lock
ReadWritePaths=/run/u-opti/smite
ReadWritePaths=/var/log/nginx

[Install]
WantedBy=multi-user.target
"""
    return body.encode("ascii")


def provision(*, peer_gid: int, root: Path = Path("/"),
              source_dir: Path | None = None,
              instance_id: str | None = None) -> dict[str, str]:
    """Prepare inert broker state; no daemon reload, enable, start or grant."""
    if type(peer_gid) is not int or not 1 <= peer_gid < 65536:
        raise ProvisionHold("INVALID_DEDICATED_PEER_GID")
    _check_root(root)
    if root == Path("/"):
        if os.geteuid() != 0 or os.uname().nodename.split(".")[0].lower() != "ir":
            raise ProvisionHold("IR_ROOT_ONLY")
    source_dir = source_dir or Path(__file__).resolve().parent
    if not source_dir.is_absolute() or source_dir.is_symlink():
        raise ProvisionHold("UNTRUSTED_BROKER_SOURCE_DIR")

    # The systemd unit binds this exact path writable while ProtectSystem=full
    # is enabled. Require a real, trusted Nginx config directory before
    # provisioning any broker state.
    _validate_nginx_config_dir(root)

    helper_source = source_dir / HELPER_MODULE
    planner_source = source_dir / PLANNER_MODULE
    broker_source = source_dir / BROKER_MODULE
    for path in (helper_source, planner_source, broker_source,
                 source_dir / LEDGER_MODULE,
                 source_dir / "smite-rc5-xhttp-signed-intent.py",
                 source_dir / "smite-rc5-xhttp-bridge-install.py",
                 source_dir / "smite-rc5-xhttp-bridge-admission.py"):
        try:
            item = path.lstat()
            raw = path.read_bytes()
        except OSError as exc:
            raise ProvisionHold("BROKER_SOURCE_UNAVAILABLE") from exc
        if (not stat.S_ISREG(item.st_mode) or item.st_mode & 0o022
                or (root == Path("/") and item.st_uid != 0)):
            raise ProvisionHold("UNTRUSTED_BROKER_SOURCE")
        if path == helper_source and hashlib.sha256(raw).hexdigest() != HELPER_SHA256:
            raise ProvisionHold("HELPER_SOURCE_DIGEST_MISMATCH")
        if path == planner_source and hashlib.sha256(raw).hexdigest() != PLANNER_SHA256:
            raise ProvisionHold("PLANNER_SOURCE_DIGEST_MISMATCH")

    if instance_id is None:
        instance_id = "broker-ir-" + secrets.token_urlsafe(18)
    if (not isinstance(instance_id, str)
            or not __import__("re").fullmatch(r"[A-Za-z0-9_-]{8,80}", instance_id)):
        raise ProvisionHold("INVALID_BROKER_INSTANCE")

    # The only directories this operation may create. Existing paths must
    # already have the required owner/mode; they are never chmod'd or replaced.
    global _CREATED_DIRS
    _CREATED_DIRS = set()
    for relative, mode in (
        ("etc", 0o755), ("etc/nginx/smite-xhttp-routes", 0o755),
        ("etc/u-opti", 0o755),
        ("etc/u-opti/smite", 0o700), ("etc/u-opti/smite/route-grants", 0o700),
        ("var", 0o755), ("var/lib", 0o755), ("var/lib/u-opti", 0o755),
        ("var/lib/u-opti/smite-xhttp-broker", 0o700),
        ("usr", 0o755), ("usr/local", 0o755), ("usr/local/lib", 0o755),
        ("usr/local/libexec", 0o755), ("etc/systemd", 0o755),
        ("etc/systemd/system", 0o755),
    ):
        path = root / relative
        existed = path.exists() or path.is_symlink()
        _ensure_dir(root, relative, mode)
        if not existed:
            _CREATED_DIRS.add(path)
            os.chmod(path, mode)

    etc = root / "etc/u-opti/smite"
    state = root / "var/lib/u-opti/smite-xhttp-broker"
    libexec = root / "usr/local/libexec"
    module_target = root / "usr/local/lib/u-opti/modules" / BROKER_MODULE
    targets = (
        etc / "route-broker.json", etc / "route-broker.key",
        state / "nonce.db", libexec / "smite-xhttp-nginx-route",
        libexec / "smite_xhttp_nginx_plan.py",
        root / "etc/systemd/system" / SERVICE_NAME,
    )
    if any(p.exists() or p.is_symlink() for p in targets):
        raise ProvisionHold("BROKER_PARTIAL_OR_EXISTING_STATE_REQUIRES_REVIEW")
    try:
        module_stat = module_target.lstat()
    except OSError as exc:
        raise ProvisionHold("BROKER_MODULE_NOT_STAGED") from exc
    if (not stat.S_ISREG(module_stat.st_mode) or module_stat.st_uid != 0
            or module_stat.st_mode & 0o022):
        raise ProvisionHold("BROKER_MODULE_NOT_TRUSTED")

    key = secrets.token_bytes(32)
    config = {
        "schema": 1,
        "instance_id": instance_id,
        "peer_uid": 0,
        "peer_gid": peer_gid,
        "helper_sha256": HELPER_SHA256,
        "planner_sha256": PLANNER_SHA256,
    }
    config_bytes = (json.dumps(config, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ledger_module = _ledger(source_dir)
    ledger_module.DurableNonceLedger.bootstrap_new(
        state / "nonce.db", instance_id=instance_id
    )

    # Commit immutable inputs before the config advertises them. Any interrupted
    # or conflicting partial state stays HOLD and is never auto-retried/reset.
    _write_new(libexec / "smite-xhttp-nginx-route", helper_source.read_bytes(), 0o755)
    _write_new(libexec / "smite_xhttp_nginx_plan.py", planner_source.read_bytes(), 0o755)
    _write_new(etc / "route-broker.key", key, 0o600)
    _write_new(etc / "route-broker.json", config_bytes, 0o600)
    _write_new(root / "etc/systemd/system" / SERVICE_NAME,
               _service_unit(peer_gid), 0o644)
    return {
        "BROKER_PROVISIONING": "PASS_INERT",
        "BROKER_INSTANCE": instance_id,
        "NODE_PRIMARY_GID": str(peer_gid),
        "TRUSTED_GRANTS": "NONE",
        "SERVICE_UNIT": "INSTALLED_NOT_ENABLED",
        "SERVICE_START": "NOT_PERFORMED",
        "NODE_ENABLEMENT": "NOT_PERFORMED",
        "LIVE_ROUTE_CHANGE": "NO",
    }


def _probe_broker_socket(socket_path: Path) -> None:
    """A successful connect proves the owner-checked UDS is listening."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(1.0)
            connection.connect(str(socket_path))
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout) as exc:
        raise ProvisionHold("BROKER_SOCKET_NOT_READY") from exc
    except OSError as exc:
        raise ProvisionHold("BROKER_SOCKET_CONNECT_FAILED") from exc


def _wait_for_broker_socket(sock_dir: Path, peer_gid: int) -> None:
    """Wait for the actual listener; Type=simple does not imply UDS readiness.

    Retry only the known transient NOT_READY state. Wrong ownership, modes or
    other access errors HOLD immediately, even during first boot.
    """
    deadline = time.monotonic() + BROKER_STARTUP_TIMEOUT
    socket_path = sock_dir / "xhttp-broker.sock"
    while True:
        try:
            directory = sock_dir.lstat()
            sock = socket_path.lstat()
        except FileNotFoundError as exc:
            failure = ProvisionHold("BROKER_SOCKET_NOT_READY")
            failure.__cause__ = exc
        except OSError as exc:
            raise ProvisionHold("BROKER_SOCKET_NOT_TRUSTED") from exc
        else:
            if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0
                    or directory.st_gid != peer_gid or stat.S_IMODE(directory.st_mode) != 0o750
                    or not stat.S_ISSOCK(sock.st_mode) or sock.st_uid != 0
                    or sock.st_gid != peer_gid):
                raise ProvisionHold("BROKER_SOCKET_NOT_TRUSTED")
            # Between bind() and chmod(0660), systemd's UMask=0077
            # creates an owner-only (0700) socket. This narrow, more
            # restrictive intermediate mode is NOT readiness. Never connect
            # or enable the Node until the exact final 0660 mode is verified.
            if stat.S_IMODE(sock.st_mode) == 0o700:
                failure = ProvisionHold("BROKER_SOCKET_NOT_READY")
            elif stat.S_IMODE(sock.st_mode) != 0o660:
                raise ProvisionHold("BROKER_SOCKET_NOT_TRUSTED")
            else:
                try:
                    _probe_broker_socket(socket_path)
                except ProvisionHold as exc:
                    if str(exc) != "BROKER_SOCKET_NOT_READY":
                        raise
                    failure = exc
                else:
                    return
        if time.monotonic() >= deadline:
            raise failure
        time.sleep(BROKER_STARTUP_POLL)


def activate(*, root: Path = Path("/"), runner=subprocess.run) -> dict[str, str]:
    """Enable/start the prepared IR broker without grants or live route entries."""
    _check_root(root)
    if root == Path("/"):
        if os.geteuid() != 0 or os.uname().nodename.split(".")[0].lower() != "ir":
            raise ProvisionHold("IR_ROOT_ONLY")
    elif runner is subprocess.run:
        raise ProvisionHold("ACTIVATION_TEST_ROOT_REQUIRES_MOCKED_RUNNER")

    etc = root / "etc/u-opti/smite"
    state = root / "var/lib/u-opti/smite-xhttp-broker"
    config_path = etc / "route-broker.json"
    key_path = etc / "route-broker.key"
    grants = etc / "route-grants"
    ledger = state / "nonce.db"
    service = root / "etc/systemd/system" / SERVICE_NAME
    sock_dir = root / "run/u-opti/smite"

    def trusted_file(path: Path, mode: int, max_size: int) -> bytes:
        try:
            before = path.lstat()
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                    or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != mode
                    or not 0 < before.st_size <= max_size):
                raise ProvisionHold("BROKER_ACTIVATION_INPUT_UNTRUSTED")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise ProvisionHold("BROKER_ACTIVATION_INPUT_CHANGED")
                raw = os.read(fd, max_size + 1)
            finally:
                os.close(fd)
            if len(raw) != before.st_size:
                raise ProvisionHold("BROKER_ACTIVATION_INPUT_CHANGED")
            return raw
        except OSError as exc:
            raise ProvisionHold("BROKER_ACTIVATION_INPUT_MISSING") from exc

    config_raw = trusted_file(config_path, 0o600, 4096)
    key = trusted_file(key_path, 0o600, 64)
    trusted_file(ledger, 0o600, 64 * 1024 * 1024)
    unit = trusted_file(service, 0o644, 8192).decode("ascii", "strict")
    try:
        config = json.loads(config_raw)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ProvisionHold("BROKER_ACTIVATION_CONFIG_INVALID") from exc
    peer_gid = config.get("peer_gid") if isinstance(config, dict) else None
    if (len(key) != 32 or not isinstance(config, dict)
            or set(config) != {"schema", "instance_id", "peer_uid", "peer_gid",
                               "helper_sha256", "planner_sha256"}
            or type(config.get("schema")) is not int or config["schema"] != 1
            or type(config.get("peer_uid")) is not int or config["peer_uid"] != 0
            or type(peer_gid) is not int or not 1 <= peer_gid < 65536
            or config.get("helper_sha256") != HELPER_SHA256
            or config.get("planner_sha256") != PLANNER_SHA256
            or f"Group={peer_gid}\n" not in unit
            or "User=root\n" not in unit
            or "Restart=on-failure\n" not in unit
            or f"ExecStart=/usr/bin/python3 -B /usr/local/lib/u-opti/modules/{BROKER_MODULE} --serve\n" not in unit
            or "NoNewPrivileges=yes\n" not in unit
            or "ProtectSystem=full\n" not in unit):
        raise ProvisionHold("BROKER_ACTIVATION_CONFIG_INVALID")

    # Older provisioners wrote exact lock-file ReadWritePaths entries. Those
    # files are intentionally created lazily under /run/lock, so systemd must
    # tolerate their absence when the persistent broker service starts.
    expected_unit = _service_unit(peer_gid)
    # Exactly the previous U-OPTI units are eligible for in-place upgrade:
    # old optional-lock syntax, with or without runtime preservation. Do not
    # bless any other service text, symlinks, drop-ins, or changed credentials.
    current_text = expected_unit.decode("ascii")
    old_text = current_text.replace("RuntimeDirectoryPreserve=yes\n", "")
    lock_old = lambda value: value.replace(
        "ReadWritePaths=-/run/lock/u-opti-smite-engine.lock\n",
        "ReadWritePaths=/run/lock/u-opti-smite-engine.lock\n",
    ).replace(
        "ReadWritePaths=-/run/lock/smite-xhttp-nginx-route.lock\n",
        "ReadWritePaths=/run/lock/smite-xhttp-nginx-route.lock\n",
    )
    known_old = {old_text, lock_old(old_text), lock_old(current_text)}
    if unit in known_old:
        _replace_existing_trusted_file(service, expected_unit, 0o644)
        unit = current_text
    elif unit != current_text:
        raise ProvisionHold("BROKER_ACTIVATION_UNIT_REQUIRES_REVIEW")

    helper = trusted_file(root / "usr/local/libexec" / HELPER_MODULE, 0o755, 1024 * 1024)
    planner = trusted_file(root / "usr/local/libexec" / PLANNER_MODULE, 0o755, 1024 * 1024)
    broker_module = trusted_file(
        root / "usr/local/lib/u-opti/modules" / BROKER_MODULE, 0o644, 1024 * 1024
    )
    if (hashlib.sha256(helper).hexdigest() != HELPER_SHA256
            or hashlib.sha256(planner).hexdigest() != PLANNER_SHA256
            or b"def serve()" not in broker_module):
        raise ProvisionHold("BROKER_ACTIVATION_PINNED_INPUT_MISMATCH")
    for path in (etc, grants, state):
        try:
            item = path.lstat()
        except OSError as exc:
            raise ProvisionHold("BROKER_ACTIVATION_DIRECTORY_MISSING") from exc
        if (not stat.S_ISDIR(item.st_mode) or item.st_uid != 0
                or stat.S_IMODE(item.st_mode) != 0o700):
            raise ProvisionHold("BROKER_ACTIVATION_DIRECTORY_UNTRUSTED")

    # Recovery may encounter a service unit left behind by an older
    # provisioner that did not create this path. Repair only the dedicated,
    # empty include directory before systemd's ReadWritePaths sandbox is set up.
    _ensure_nginx_route_dir(root)

    # systemd's Group= numeric credential lookup requires a host NSS group
    # entry. The Node container's primary GID alone does not create one here.
    _ensure_peer_group(peer_gid, runner)

    commands = (
        ("daemon-reload",), ("enable", SERVICE_NAME),
        ("reset-failed", SERVICE_NAME), ("start", SERVICE_NAME),
    )
    for args in commands:
        try:
            result = runner(["systemctl", *args], check=False,
                            capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProvisionHold("BROKER_SYSTEMD_COMMAND_FAILED") from exc
        if result.returncode != 0:
            raise ProvisionHold("BROKER_SYSTEMD_COMMAND_FAILED")
    try:
        result = runner(["systemctl", "is-enabled", SERVICE_NAME], check=False,
                        capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProvisionHold("BROKER_SYSTEMD_VERIFICATION_FAILED") from exc
    if result.returncode != 0 or result.stdout.strip() != "enabled":
        raise ProvisionHold("BROKER_SYSTEMD_VERIFICATION_FAILED")

    # systemd Type=simple returns from start before the Python process binds
    # and listens. Wait for the only acceptable transient state ("activating"),
    # never treating inactive/failed as recoverable.
    active_deadline = time.monotonic() + BROKER_STARTUP_TIMEOUT
    while True:
        try:
            result = runner(["systemctl", "is-active", SERVICE_NAME], check=False,
                            capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProvisionHold("BROKER_SYSTEMD_VERIFICATION_FAILED") from exc
        if result.returncode == 0 and result.stdout.strip() == "active":
            break
        if result.stdout.strip() != "activating" or time.monotonic() >= active_deadline:
            raise ProvisionHold("BROKER_SYSTEMD_VERIFICATION_FAILED")
        time.sleep(BROKER_STARTUP_POLL)

    _wait_for_broker_socket(sock_dir, peer_gid)
    return {
        "SERVICE_ACTIVATION": "PASS_ACTIVE_PERSISTENT",
        "SERVICE_ENABLED": "YES",
        "BROKER_SOCKET": "READY",
        "TRUSTED_GRANTS": "UNCHANGED",
        "LIVE_ROUTE_CHANGE": "NO",
    }


def _grant_context(root: Path) -> Path:
    """Require the existing private broker grant directory without creating it."""
    _check_root(root)
    if root == Path("/"):
        if os.geteuid() != 0 or os.uname().nodename.split(".")[0].lower() != "ir":
            raise ProvisionHold("IR_ROOT_ONLY")
    etc = root / "etc/u-opti/smite"
    grants = etc / "route-grants"
    for path in (etc, grants):
        try:
            item = path.lstat()
        except OSError as exc:
            raise ProvisionHold("BROKER_GRANT_DIRECTORY_MISSING") from exc
        if (not stat.S_ISDIR(item.st_mode) or item.st_uid != 0
                or stat.S_IMODE(item.st_mode) != 0o700):
            raise ProvisionHold("BROKER_GRANT_DIRECTORY_UNTRUSTED")
    return grants


def _checked_grant(data: dict[str, object], *, confirmed_child: str) -> dict[str, object]:
    fields = {
        "ir_node", "kh_node", "owner", "child", "lease", "port", "path",
        "owner_proof_sha256", "kh_inventory_sha256",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise ProvisionHold("BROKER_GRANT_SCHEMA_MISMATCH")
    if (type(data["child"]) is not str or data["child"] != confirmed_child
            or not IDENT.fullmatch(data["child"])):
        raise ProvisionHold("BROKER_GRANT_CHILD_CONFIRMATION_MISMATCH")
    for name in ("ir_node", "kh_node", "owner", "lease"):
        if type(data[name]) is not str or not IDENT.fullmatch(data[name]):
            raise ProvisionHold("BROKER_GRANT_INVALID_IDENTITY")
    port = data["port"]
    route = data["path"]
    if (type(port) is not int or not 1024 <= port <= 65535 or port == 7000
            or type(route) is not str or len(route) > 128
            or not GRANT_PATH.fullmatch(route)
            or route.split("/")[1].lower() in {"api", "docs", "redoc", "openapi", "assets", "static", "auth", "login", "admin", "health", "metrics", "sub", "ws"}):
        raise ProvisionHold("BROKER_GRANT_INVALID_ROUTE")
    for name in ("owner_proof_sha256", "kh_inventory_sha256"):
        if type(data[name]) is not str or not HASH.fullmatch(data[name]):
            raise ProvisionHold("BROKER_GRANT_INVALID_EVIDENCE_HASH")
    # Stable ordering and exact schema are part of the local root grant file.
    return {name: data[name] for name in (
        "ir_node", "kh_node", "owner", "child", "lease", "port", "path",
        "owner_proof_sha256", "kh_inventory_sha256",
    )}


def install_grant(data: dict[str, object], *, confirmed_child: str,
                  root: Path = Path("/")) -> dict[str, str]:
    """Install one human-approved per-child grant; never derive it from a request.

    The root operator must first compare the IDs, selected inbound and evidence
    hashes with current authenticated Signed IR/KH results and the active Panel
    lease. This local CLI records that separate approval; it does not claim to
    cryptographically verify remote evidence on behalf of the operator.
    """
    grants = _grant_context(root)
    grant = _checked_grant(data, confirmed_child=confirmed_child)
    target = grants / f"{grant['child']}.json"
    encoded = (json.dumps({"schema": 1, **grant}, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    _write_new(target, encoded, 0o600)
    return {
        "TRUSTED_GRANT": "INSTALLED_ROOT_OPERATOR_APPROVED",
        "GRANT_CHILD": str(grant["child"]),
        "EVIDENCE_VERIFICATION": "OPERATOR_ASSERTED",
        "LIVE_ROUTE_CHANGE": "NO",
    }


def revoke_grant(child: str, *, root: Path = Path("/")) -> dict[str, str]:
    """Remove one exact root-owned child grant after explicit local approval."""
    if type(child) is not str or not IDENT.fullmatch(child):
        raise ProvisionHold("BROKER_GRANT_INVALID_CHILD")
    grants = _grant_context(root)
    target = grants / f"{child}.json"
    try:
        info = target.lstat()
    except OSError as exc:
        raise ProvisionHold("BROKER_GRANT_NOT_FOUND") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
        raise ProvisionHold("BROKER_GRANT_FILE_UNTRUSTED")
    try:
        target.unlink()
        dir_fd = os.open(grants, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise ProvisionHold("BROKER_GRANT_REVOKE_FAILED") from exc
    return {
        "TRUSTED_GRANT": "REVOKED",
        "GRANT_CHILD": child,
        "LIVE_ROUTE_CHANGE": "NO",
    }


def _interactive_grant() -> tuple[dict[str, object], str]:
    print("Before approving, independently verify the current Signed IR FRPS owner,\n"
          "Signed KH XHTTP inbound and active unique Panel lease. This root-only\n"
          "approval is per child; the broker will not create grants from requests.")
    fields = ("ir_node", "kh_node", "owner", "child", "lease", "port", "path")
    values: dict[str, object] = {}
    for name in fields:
        answer = input(f"{name}: ").strip()
        if name == "port" and answer.isascii() and answer.isdecimal():
            values[name] = int(answer)
        else:
            values[name] = answer
    child = values["child"]
    confirmation = input(f"Type APPROVE {child} to install this root grant: ").strip()
    if confirmation != f"APPROVE {child}":
        raise ProvisionHold("BROKER_GRANT_APPROVAL_NOT_CONFIRMED")
    port = values["port"]
    if type(port) is not int:
        raise ProvisionHold("BROKER_GRANT_INVALID_ROUTE")
    # These canonical hashes match the Panel's selected-owner and selected-
    # inbound evidence projections. Their input facts remain operator-entered
    # after review of current authenticated Signed Node results.
    owner_facts = {
        "tunnel_id": values["owner"], "control_port": 7000,
        "proxy_port": port,
    }
    inbound_facts = {
        "port": port, "listen": "127.0.0.1", "protocol": "vless",
        "network": "xhttp", "path": values["path"], "enabled": True,
    }
    values["owner_proof_sha256"] = hashlib.sha256(json.dumps(
        owner_facts, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")).hexdigest()
    values["kh_inventory_sha256"] = hashlib.sha256(json.dumps(
        inbound_facts, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")).hexdigest()
    return values, child  # type: ignore[return-value]



def _socket_recovery_command(runner, argv: list[str], *, timeout: int = 20) -> str:
    """No shell, no implicit retries, and never expose command output."""
    try:
        result = runner(argv, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProvisionHold("BROKER_SOCKET_RECOVERY_COMMAND_FAILED") from exc
    if result.returncode != 0 or len(result.stdout) > 1024 * 1024:
        raise ProvisionHold("BROKER_SOCKET_RECOVERY_COMMAND_FAILED")
    return result.stdout.strip()


def _socket_recovery_evidence(runner) -> dict:
    """Read-only, fail-closed proof. No publication or nonce consumption."""
    broker = _load_recovery_broker()
    config = broker._configuration()
    broker._verify_helper(config)
    broker._verify_bridge()
    gid = config["peer_gid"]
    key = broker._file(broker.KEY, mode=0o600)
    if len(key) != 32:
        raise ProvisionHold("BROKER_HMAC_KEY_INVALID")
    ledger = broker._ledger_module()
    ledger._trusted_db(broker.LEDGER)
    with sqlite3.connect(broker.LEDGER.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        if (db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
                or db.execute("PRAGMA user_version").fetchone() != (ledger.SCHEMA_VERSION,)
                or db.execute("PRAGMA application_id").fetchone() != (ledger.APPLICATION_ID,)
                or db.execute("SELECT instance_id FROM broker_identity").fetchall()
                != [(config["instance_id"],)]):
            raise ProvisionHold("BROKER_REPLAY_LEDGER_INVALID")
    service = Path("/etc/systemd/system") / SERVICE_NAME
    unit = broker._file(service, mode=0o644, max_size=8192)
    current = _service_unit(gid)
    legacy = current.replace(b"RuntimeDirectoryPreserve=yes\n", b"")
    old_locks = lambda raw: raw.replace(
        b"ReadWritePaths=-/run/lock/u-opti-smite-engine.lock\n",
        b"ReadWritePaths=/run/lock/u-opti-smite-engine.lock\n").replace(
        b"ReadWritePaths=-/run/lock/smite-xhttp-nginx-route.lock\n",
        b"ReadWritePaths=/run/lock/smite-xhttp-nginx-route.lock\n")
    if unit not in (current, legacy, old_locks(current), old_locks(legacy)):
        raise ProvisionHold("BROKER_SERVICE_UNIT_DRIFT")
    if (_socket_recovery_command(runner, ["systemctl", "show", SERVICE_NAME,
                                         "-p", "FragmentPath", "--value"]) != str(service)
            or _socket_recovery_command(runner, ["systemctl", "show", SERVICE_NAME,
                                                 "-p", "DropInPaths", "--value"]) != ""
            or _socket_recovery_command(runner, ["systemctl", "is-active", SERVICE_NAME]) != "active"):
        raise ProvisionHold("BROKER_SERVICE_OVERRIDE_OR_INACTIVE")
    effective = _socket_recovery_command(runner, ["systemctl", "show", SERVICE_NAME,
                                                 "-p", "RuntimeDirectoryPreserve", "--value"])
    if effective not in ("yes", "no"):
        raise ProvisionHold("BROKER_SERVICE_RUNTIME_UNKNOWN")
    if unit == current and effective != "yes":
        raise ProvisionHold("BROKER_SERVICE_RUNTIME_NOT_LOADED")

    broker._dir(broker.GRANTS, mode=0o700)
    broker._dir(broker.LEDGER.parent, mode=0o700)
    route_dir = Path("/etc/nginx/smite-xhttp-routes")
    broker._dir(route_dir, mode=0o755)
    # Hash protected inputs AND directory entries, including absent queue.
    # A concurrent route/nonce/approval mutation is never silently accepted.
    protected = [broker.KEY, broker.CONFIG, broker.LEDGER, service,
                 broker.LEDGER.parent / "approval-request.json"]
    # Include transient SQLite WAL/SHM and all existing Broker journals, not
    # only the main .db. A changed or newly created entry means HOLD.
    for folder in (broker.GRANTS, route_dir, broker.LEDGER.parent):
        for entry in sorted(folder.iterdir()):
            if not entry.name or entry.is_symlink() or not entry.is_file():
                raise ProvisionHold("BROKER_PROTECTED_ENTRY_UNTRUSTED")
            if entry not in protected:
                protected.append(entry)
    volume = None

    def inspect(name):
        data = json.loads(_socket_recovery_command(
            runner, ["docker", "inspect", name]))
        if not isinstance(data, list) or len(data) != 1:
            raise ProvisionHold("BROKER_CONTAINER_INSPECT_INVALID")
        item = data[0]
        if (item.get("Name") != "/" + name
                or not item.get("State", {}).get("Running")
                or item.get("State", {}).get("Health", {}).get("Status", "healthy") != "healthy"
                or item.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") != name):
            raise ProvisionHold("BROKER_CONTAINER_IDENTITY_DRIFT")
        return item

    node = inspect("smite-node")
    panel = inspect("smite-panel")
    mounts = [x for x in node["Mounts"] if x.get("Destination") == "/run/u-opti/smite"]
    if (len(mounts) != 1 or mounts[0].get("Source") != "/run/u-opti/smite"
            or mounts[0].get("Type") != "bind" or mounts[0].get("RW") is not False
            or node["Config"].get("User") != f"0:{gid}"):
        raise ProvisionHold("BROKER_NODE_MOUNT_OR_GID_DRIFT")
    if any("/run/u-opti/smite" in str(x) for x in panel.get("Mounts", [])):
        raise ProvisionHold("BROKER_PANEL_UNEXPECTED_SOCKET_MOUNT")
    # The existing FRPS and persistent tunnel registry must survive in place.
    vols = [x for x in node["Mounts"] if x.get("Destination") == "/var/lib/smite-node"]
    if (len(vols) != 1 or vols[0].get("Type") != "volume"
            or vols[0].get("RW") is not True or vols[0].get("Name") != "smite-node-data"):
        raise ProvisionHold("BROKER_NODE_TUNNEL_VOLUME_DRIFT")
    volume = Path(vols[0]["Source"])
    if (volume.name != "_data" or volume.parent.name != "smite-node-data"
            or not volume.is_absolute() or ".." in volume.parts):
        raise ProvisionHold("BROKER_NODE_TUNNEL_VOLUME_DRIFT")
    protected.append(volume / "tunnels.json")

    def fingerprint(path):
        if not path.exists() and not path.is_symlink():
            return None
        st = path.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1
                or st.st_mode & 0o022 or st.st_size > 80 * 1024 * 1024):
            raise ProvisionHold("BROKER_PROTECTED_FILE_DRIFT")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
                raise ProvisionHold("BROKER_PROTECTED_FILE_CHANGED")
            digest = hashlib.sha256()
            while block := os.read(fd, 1024 * 1024):
                digest.update(block)
        finally:
            os.close(fd)
        return (st.st_dev, st.st_ino, st.st_size, digest.hexdigest())

    files = {str(path): fingerprint(path) for path in protected}
    if files[str(volume / "tunnels.json")] is None:
        raise ProvisionHold("BROKER_NODE_TUNNEL_REGISTRY_MISSING")
    # Do not change WSS/Bridge. Their existing validators must still pass.
    module_dir = Path("/usr/local/lib/u-opti/modules")
    for module in ("smite-rc7-wss-edge.py", "smite-stage15-xhttp-bridge.py"):
        _socket_recovery_command(runner, ["python3", "-B", str(module_dir / module),
                                           "verify"], timeout=35)
    frps = _socket_recovery_command(runner, ["ss", "-Hlnpt"])
    owners = [line for line in frps.splitlines()
              if re.search(r":7000\s", line) and '"frps"' in line]
    if len(owners) != 1:
        raise ProvisionHold("BROKER_FRPS_OWNER_PROOF_MISSING")
    # A Node-only restart can change the FRPS PID without changing its
    # single owner socket. Pin the TCP bind identity, not a volatile PID/fd.
    owner_address = owners[0].split()[3]
    host = broker.SOCKET.parent.lstat()
    sock = broker.SOCKET.lstat()
    if (not stat.S_ISDIR(host.st_mode) or host.st_uid != 0
            or host.st_gid != gid or stat.S_IMODE(host.st_mode) != 0o750
            or not stat.S_ISSOCK(sock.st_mode) or sock.st_uid != 0
            or sock.st_gid != gid or stat.S_IMODE(sock.st_mode) != 0o660):
        raise ProvisionHold("BROKER_HOST_SOCKET_UNTRUSTED")
    _probe_broker_socket(broker.SOCKET)
    try:
        peer = json.loads(_socket_recovery_command(
            runner, ["docker", "exec", "smite-node", "python", "-c",
                     ("import os,json,stat; d=os.lstat('/run/u-opti/smite'); "
                      "p='/run/u-opti/smite/xhttp-broker.sock'; "
                      "s=os.lstat(p) if os.path.lexists(p) else None; "
                      "print(json.dumps([d.st_dev,d.st_ino, "
                      "None if s is None else [s.st_uid,s.st_gid,"
                      "stat.S_IMODE(s.st_mode),stat.S_ISSOCK(s.st_mode)]]))")]))
    except (ValueError, KeyError) as exc:
        raise ProvisionHold("BROKER_NODE_SOCKET_PROOF_INVALID") from exc
    host_inode = (host.st_dev, host.st_ino)
    peer_inode = tuple(peer[:2])
    if len(peer) != 3:
        raise ProvisionHold("BROKER_NODE_SOCKET_PROOF_INVALID")
    mounted = peer_inode == host_inode and peer[2] == [0, gid, 0o660, True]
    # Configuration/mount/volume must remain byte-identical. Container ID and
    # image also must not change (docker restart, NEVER compose up/recreate).
    identity = (node["Id"], node["Image"], node["Config"], node["HostConfig"],
                node["Mounts"], panel["Id"], panel["Image"])
    return dict(ready=mounted, preserve=unit == current, effective=effective,
                gid=gid, host_inode=host_inode, peer_inode=peer_inode,
                files=files, identity=identity, owner=owner_address)


def _load_recovery_broker():
    path = Path("/usr/local/lib/u-opti/modules") / BROKER_MODULE
    spec = importlib.util.spec_from_file_location("uopti_broker_socket_recovery", path)
    if spec is None or spec.loader is None:
        raise ProvisionHold("BROKER_RECOVERY_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def recover_node_socket(*, approved: bool = False, runner=subprocess.run) -> dict[str, str]:
    """Read-only audit unless separately approved in a maintenance window.

    In-place systemd unit repair + restart of ONLY the existing smite-node.
    No new container, no route submission, no nonce reset, no FRP reapply.
    Interruption leaves the durable state intact and requires a fresh audit.
    """
    if os.geteuid() != 0 or os.uname().nodename.split(".")[0].lower() != "ir":
        raise ProvisionHold("IR_ROOT_ONLY")
    broker = _load_recovery_broker()
    if not approved:
        proof = _socket_recovery_evidence(runner)
        return {"BROKER_RUNTIME_PRESERVED": "YES" if proof["preserve"] else "NO",
                "NODE_SOCKET_BIND": "PASS" if proof["ready"] else "STALE_HOLD",
                "RESTART_PERFORMED": "NO", "LIVE_CHANGES": "NONE"}
    if not sys.stdin.isatty():
        raise ProvisionHold("BROKER_SOCKET_REPAIR_REQUIRES_ROOT_TTY")
    with broker._lock():
        before = _socket_recovery_evidence(runner)
        if before["preserve"] and before["ready"]:
            return {"BROKER_SOCKET_RECOVERY": "ALREADY_BOUND_NO_ACTION",
                    "LIVE_CHANGES": "NONE"}
        # Operator must have independently captured and verified a provider
        # snapshot and recovery console; a challenge is NOT a snapshot itself.
        challenge = "REATTACH-IR-SMITE-NODE-SNAPSHOT-VERIFIED"
        if input("Maintenance window, verified snapshot and console. Type "
                 + challenge + ": ").strip() != challenge:
            raise ProvisionHold("BROKER_SOCKET_RECOVERY_NOT_AUTHORIZED")
        if not before["preserve"]:
            unit_path = Path("/etc/systemd/system") / SERVICE_NAME
            original_unit = broker._file(unit_path, mode=0o644, max_size=8192)
            _replace_existing_trusted_file(
                unit_path, _service_unit(before["gid"]), 0o644)
            try:
                _socket_recovery_command(runner, ["systemctl", "daemon-reload"])
                if (_socket_recovery_command(runner, ["systemctl", "show", SERVICE_NAME,
                                                      "-p", "RuntimeDirectoryPreserve", "--value"])
                        != "yes"):
                    raise ProvisionHold("BROKER_SOCKET_RUNTIME_PRESERVE_NOT_LOADED")
            except ProvisionHold:
                # The service has NOT restarted yet. Only here is it safe to
                # atomically restore the exact reviewed unit before-image.
                _replace_existing_trusted_file(unit_path, original_unit, 0o644)
                _socket_recovery_command(runner, ["systemctl", "daemon-reload"])
                raise ProvisionHold("BROKER_UNIT_RESTORED_BEFORE_RESTART_HOLD")
        # Broker restart first. This must not replace the runtime directory.
        _socket_recovery_command(runner, ["systemctl", "restart", SERVICE_NAME], timeout=35)
        _wait_for_broker_socket(Path("/run/u-opti/smite"), before["gid"])
        after_broker = _socket_recovery_evidence(runner)
        if (after_broker["host_inode"] != before["host_inode"]
                or after_broker["files"] != {**before["files"],
                    str(Path("/etc/systemd/system") / SERVICE_NAME):
                    after_broker["files"][str(Path("/etc/systemd/system") / SERVICE_NAME)]}
                or after_broker["identity"] != before["identity"]
                or after_broker["owner"] != before["owner"]):
            raise ProvisionHold("BROKER_POST_RESTART_DRIFT_REQUIRES_REVIEW")
        if not after_broker["ready"]:
            # docker restart retains the exact existing container and image;
            # no docker compose up, image pull, FRPS/FRPC or Panel restart.
            _socket_recovery_command(
                runner, ["docker", "restart", "--time", "25", "smite-node"], timeout=65)
            # Docker restart returns when the existing container is running,
            # not necessarily when its strict healthcheck is healthy. Wait
            # only for health readiness; NEVER retry restart or publication.
            until = time.monotonic() + 60
            while True:
                raw = _socket_recovery_command(runner, ["docker", "inspect", "smite-node"])
                details = json.loads(raw)
                if not isinstance(details, list) or len(details) != 1:
                    raise ProvisionHold("BROKER_NODE_POST_RESTART_INSPECT_INVALID")
                state = details[0].get("State", {})
                if not state.get("Running"):
                    raise ProvisionHold("BROKER_NODE_POST_RESTART_STOPPED")
                health = state.get("Health", {}).get("Status", "healthy")
                if health == "healthy":
                    break
                if health != "starting" or time.monotonic() >= until:
                    raise ProvisionHold("BROKER_NODE_HEALTH_NOT_READY_HOLD")
                time.sleep(1)
        final = _socket_recovery_evidence(runner)
        if (not final["ready"] or not final["preserve"]
                or final["host_inode"] != before["host_inode"]
                or final["files"] != after_broker["files"]
                or final["identity"] != before["identity"]
                or final["owner"] != before["owner"]):
            raise ProvisionHold("BROKER_RECOVERY_PARTIAL_HOLD_MANUAL_REVIEW")
        return {"BROKER_SOCKET_RECOVERY": "PASS_SAME_NODE_REATTACHED",
                "BROKER_HOST_NODE_INODE": "MATCH",
                "BROKER_RUNTIME_PRESERVED": "YES",
                "FRPS_AND_DURABLE_EVIDENCE": "UNCHANGED",
                "ROUTE_REPUBLISH": "NOT_PERFORMED"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the IR-only Smite route broker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--peer-gid", type=int)
    mode.add_argument("--audit-node-socket", action="store_true",
                      help="Read-only host/container Broker inode and state audit")
    mode.add_argument("--recover-node-socket", action="store_true",
                      help="Explicit IR-only maintenance recovery; restarts only Broker/Node")
    mode.add_argument("--activate-existing", action="store_true",
                      help="Enable and start an already provisioned IR broker")
    mode.add_argument("--approve-grant", action="store_true",
                      help="Interactively install one separately root-approved child grant")
    mode.add_argument("--revoke-grant", metavar="CHILD_ID",
                      help="Interactively revoke one exact child grant")
    parser.add_argument("--confirm-local-root", action="store_true")
    args = parser.parse_args()
    if not args.confirm_local_root:
        print("HOLD_EXPLICIT_LOCAL_ROOT_CONFIRMATION_REQUIRED")
        return 2
    try:
        if args.audit_node_socket:
            result = recover_node_socket(approved=False)
        elif args.recover_node_socket:
            result = recover_node_socket(approved=True)
        elif args.activate_existing:
            result = activate()
        elif args.approve_grant:
            if not sys.stdin.isatty():
                raise ProvisionHold("BROKER_GRANT_REQUIRES_INTERACTIVE_ROOT_TTY")
            values, child = _interactive_grant()
            result = install_grant(values, confirmed_child=child)
        elif args.revoke_grant:
            if not sys.stdin.isatty():
                raise ProvisionHold("BROKER_GRANT_REQUIRES_INTERACTIVE_ROOT_TTY")
            confirmation = input(
                f"Type REVOKE {args.revoke_grant} to remove this root grant: "
            ).strip()
            if confirmation != f"REVOKE {args.revoke_grant}":
                raise ProvisionHold("BROKER_GRANT_REVOKE_NOT_CONFIRMED")
            result = revoke_grant(args.revoke_grant)
        elif args.peer_gid is not None:
            result = provision(peer_gid=args.peer_gid)
        else:
            print("HOLD_SELECT_PROVISION_OR_ACTIVATION")
            return 2
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProvisionHold) else "BROKER_PROVISION_FAILED"
        print(f"HOLD_{reason}")
        return 2
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
