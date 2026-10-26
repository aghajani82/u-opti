#!/usr/bin/env python3
"""One-time inert provisioner for the IR U-OPTI route broker.

Installs a dedicated key, empty TrustedGrant directory, durable nonce ledger,
pinned local worker/planner, root-owned config, and a systemd unit. It NEVER
creates grants from requests, enables/starts systemd, mounts secrets into the
Panel/Node, or changes Nginx. A missing grant keeps every route request HOLD.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import sys

HELPER_SHA256 = "acb66752f6aa8600f1c45a7d68f46006b0d4d26c55330925bd35359d3ca868e6"
PLANNER_SHA256 = "0c007ca049b95227588d2e4847020a53d5d0c155d28dc537341367a783d81c19"
BROKER_MODULE = "smite-rc5-xhttp-root-broker.py"
LEDGER_MODULE = "smite-rc5-xhttp-nonce-ledger.py"
HELPER_MODULE = "smite-xhttp-nginx-route"
PLANNER_MODULE = "smite_xhttp_nginx_plan.py"
SERVICE_NAME = "u-opti-smite-xhttp-broker.service"


class ProvisionHold(RuntimeError):
    pass


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
Before=smite-node.service

[Service]
Type=simple
User=root
Group={peer_gid}
WorkingDirectory=/usr/local/lib/u-opti/modules
ExecStart=/usr/bin/python3 -B /usr/local/lib/u-opti/modules/{BROKER_MODULE} --serve
RuntimeDirectory=u-opti/smite
RuntimeDirectoryMode=0750
UMask=0077
Restart=no
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=full
ReadWritePaths=/etc/nginx/smite-xhttp-routes
ReadWritePaths=/var/lib/u-opti/smite-xhttp-broker
ReadWritePaths=/run/lock/u-opti-smite-engine.lock
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
        ("etc", 0o755), ("etc/u-opti", 0o755),
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the IR-only Smite route broker")
    parser.add_argument("--peer-gid", required=True, type=int)
    parser.add_argument("--confirm-local-root", action="store_true")
    args = parser.parse_args()
    if not args.confirm_local_root:
        print("HOLD_EXPLICIT_LOCAL_ROOT_CONFIRMATION_REQUIRED")
        return 2
    try:
        result = provision(peer_gid=args.peer_gid)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ProvisionHold) else "BROKER_PROVISION_FAILED"
        print(f"HOLD_{reason}")
        return 2
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
