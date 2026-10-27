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
import stat
import subprocess
import sys

HELPER_SHA256 = "acb66752f6aa8600f1c45a7d68f46006b0d4d26c55330925bd35359d3ca868e6"
PLANNER_SHA256 = "0c007ca049b95227588d2e4847020a53d5d0c155d28dc537341367a783d81c19"
BROKER_MODULE = "smite-rc5-xhttp-root-broker.py"
LEDGER_MODULE = "smite-rc5-xhttp-nonce-ledger.py"
HELPER_MODULE = "smite-xhttp-nginx-route"
PLANNER_MODULE = "smite_xhttp_nginx_plan.py"
SERVICE_NAME = "u-opti-smite-xhttp-broker.service"
PEER_GROUP_NAME = "u-opti-smite-peer"
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
    expected_text = expected_unit.decode("ascii")
    legacy_text = expected_text.replace(
        "ReadWritePaths=-/run/lock/u-opti-smite-engine.lock\n",
        "ReadWritePaths=/run/lock/u-opti-smite-engine.lock\n",
    ).replace(
        "ReadWritePaths=-/run/lock/smite-xhttp-nginx-route.lock\n",
        "ReadWritePaths=/run/lock/smite-xhttp-nginx-route.lock\n",
    )
    if unit == legacy_text:
        _replace_existing_trusted_file(service, expected_unit, 0o644)
        unit = expected_text
    elif unit != expected_text:
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
    for args, expected in ((("is-enabled", SERVICE_NAME), "enabled"),
                           (("is-active", SERVICE_NAME), "active")):
        try:
            result = runner(["systemctl", *args], check=False,
                            capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProvisionHold("BROKER_SYSTEMD_VERIFICATION_FAILED") from exc
        if result.returncode != 0 or result.stdout.strip() != expected:
            raise ProvisionHold("BROKER_SYSTEMD_VERIFICATION_FAILED")
    try:
        directory = sock_dir.lstat()
        sock = (sock_dir / "xhttp-broker.sock").lstat()
    except OSError as exc:
        raise ProvisionHold("BROKER_SOCKET_NOT_READY") from exc
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0
            or directory.st_gid != peer_gid or stat.S_IMODE(directory.st_mode) != 0o750
            or not stat.S_ISSOCK(sock.st_mode) or sock.st_uid != 0
            or sock.st_gid != peer_gid or stat.S_IMODE(sock.st_mode) != 0o660):
        raise ProvisionHold("BROKER_SOCKET_NOT_TRUSTED")
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
            or not GRANT_PATH.fullmatch(route) or not route.startswith(f"/{port}/")):
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
    encoded = (json.dumps(grant, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the IR-only Smite route broker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--peer-gid", type=int)
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
        if args.activate_existing:
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
