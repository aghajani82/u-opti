#!/usr/bin/env python3
"""Minimum IR-only UNIX socket broker for one approved XHTTP route.

Not installed or enabled by the current U-OPTI release. Runs only on a
separately provisioned disposable host with root-owned config, unique broker
key, an independently approved TrustedGrant, and the pinned local Smite
Nginx helper. No public TCP/HTTP listener, arbitrary command or shell.

All state/mutations below are host-local. Failure is HOLD and cannot retry
an ambiguous Nginx apply using the same nonce.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import sys
import time
from contextlib import contextmanager

HERE = Path(__file__).resolve().parent
CONFIG = Path("/etc/u-opti/smite/route-broker.json")
KEY = Path("/etc/u-opti/smite/route-broker.key")
GRANTS = Path("/etc/u-opti/smite/route-grants")
LEDGER = Path("/var/lib/u-opti/smite-xhttp-broker/nonce.db")
SOCKET = Path("/run/u-opti/smite/xhttp-broker.sock")
WEB_MODE_MARKER = Path("/etc/u-opti/smite/web-approval-mode.json")
WEB_QUEUE_DIR = Path("/var/lib/u-opti/smite-xhttp-broker/approval-pending")
ENGINE_LOCK = Path("/run/lock/u-opti-smite-engine.lock")
HELPER = Path("/usr/local/libexec/smite-xhttp-nginx-route")
PLANNER = Path("/usr/local/libexec/smite_xhttp_nginx_plan.py")
IDENT = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
HEX = re.compile(r"[a-f0-9]{64}\Z")
MAX_INPUT = 4096


class BrokerHold(RuntimeError):
    pass


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BrokerHold("DEPENDENCY_MISSING")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _ledger_module():
    return _load_module("uopti_broker_nonce_ledger", HERE / "smite-rc5-xhttp-nonce-ledger.py")


def _contract_module():
    return _ledger_module()._contract_module()


def _file(path: Path, *, mode: int, max_size: int = 4096) -> bytes:
    try:
        original = path.lstat()
        if (not stat.S_ISREG(original.st_mode) or original.st_uid != 0
                or original.st_nlink != 1
                or stat.S_IMODE(original.st_mode) != mode
                or not 0 < original.st_size <= max_size):
            raise BrokerHold("UNTRUSTED_BROKER_FILE")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
                raise BrokerHold("BROKER_FILE_CHANGED")
            data = os.read(fd, max_size + 1)
        finally:
            os.close(fd)
        if len(data) != original.st_size:
            raise BrokerHold("BROKER_FILE_SIZE_CHANGED")
        return data
    except OSError as exc:
        raise BrokerHold("BROKER_FILE_UNAVAILABLE") from exc


def _dir(path: Path, *, mode: int, gid: int | None = None) -> None:
    try:
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != mode
                or (gid is not None and info.st_gid != gid)):
            raise BrokerHold("UNTRUSTED_BROKER_DIRECTORY")
    except OSError as exc:
        raise BrokerHold("BROKER_DIRECTORY_UNAVAILABLE") from exc


def _json(data: bytes, expected: set[str]) -> dict:
    def reject_duplicate(pairs):
        out = {}
        for k, value in pairs:
            if k in out:
                raise BrokerHold("DUPLICATE_BROKER_FIELD")
            out[k] = value
        return out
    try:
        item = json.loads(data, object_pairs_hook=reject_duplicate)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise BrokerHold("MALFORMED_BROKER_JSON") from exc
    if not isinstance(item, dict) or set(item) != expected:
        raise BrokerHold("BROKER_SCHEMA_MISMATCH")
    return item


def _configuration() -> dict:
    migration = Path('/var/lib/u-opti/smite-stage15-active-runtime')
    if migration.exists() or migration.is_symlink():
        try:
            active = _load_module('broker_active_runtime', HERE / 'smite-stage15-active-runtime.py')
            active.admission()
        except Exception as exc:
            raise BrokerHold('ACTIVE_RUNTIME_RECOVERY_REQUIRED') from exc
    _dir(CONFIG.parent, mode=0o700)
    config = _json(_file(CONFIG, mode=0o600), {
        "schema", "instance_id", "peer_uid", "peer_gid",
        "helper_sha256", "planner_sha256",
    })
    uid = config.get("peer_uid")
    gid = config.get("peer_gid")
    # Smite's tunnel adapters require UID 0 in the container. For the broker
    # socket, pair that UID only with a dedicated non-zero primary GID that
    # U-OPTI provisions and mounts into this one container. Root:root is never
    # accepted; the independent HMAC, root grant and replay ledger still gate
    # every route transaction.
    peer_identity_ok = (
        type(uid) is int and (uid == 0 or 1 <= uid < 65536)
        and type(gid) is int and 1 <= gid < 65536
        and not (uid == 0 and gid == 0)
    )
    if (type(config["schema"]) is not int or config["schema"] != 1
            or type(config["instance_id"]) is not str
            or not IDENT.fullmatch(config["instance_id"])
            or not peer_identity_ok
            or any(type(config[n]) is not str or not HEX.fullmatch(config[n])
                   for n in ("helper_sha256", "planner_sha256"))):
        raise BrokerHold("INVALID_BROKER_CONFIG")
    return config


def _approved_grant(child: str):
    if not isinstance(child, str) or not IDENT.fullmatch(child):
        raise BrokerHold("INVALID_CHILD_ID")
    _dir(GRANTS, mode=0o700)
    fields = {
        "schema", "ir_node", "kh_node", "owner", "child", "lease",
        "port", "path", "owner_proof_sha256", "kh_inventory_sha256",
    }
    grant_path = GRANTS / f"{child}.json"
    try:
        grant_path.lstat()
    except FileNotFoundError as exc:
        raise BrokerHold("ROOT_OPERATOR_GRANT_REQUIRED") from exc
    except OSError as exc:
        raise BrokerHold("BROKER_GRANT_UNAVAILABLE") from exc
    item = _json(_file(grant_path, mode=0o600), fields)
    if type(item["schema"]) is not int or item["schema"] != 1 or item["child"] != child:
        raise BrokerHold("UNAPPROVED_GRANT")
    contract = _contract_module()
    try:
        return contract.TrustedGrant(**{k: item[k] for k in fields - {"schema"}})
    except (TypeError, ValueError) as exc:
        raise BrokerHold("INVALID_ROOT_GRANT") from exc


def _verify_helper(config: dict) -> None:
    # Prevent a non-root user from replacing a previously hashed executable
    # between verification and exec. The trusted worker directory is static.
    _dir(HELPER.parent, mode=0o755)
    if HELPER.parent != PLANNER.parent:
        raise BrokerHold("HELPER_PACKAGE_SPLIT")
    for path, digest_field in (
        (HELPER, "helper_sha256"), (PLANNER, "planner_sha256")
    ):
        if (not path.is_absolute() or not path.parent.is_dir()
                or path.is_symlink()):
            raise BrokerHold("HELPER_NOT_PINNED")
        raw = _file(path, mode=0o755, max_size=100_000)
        if hashlib.sha256(raw).hexdigest() != config[digest_field]:
            raise BrokerHold("HELPER_DIGEST_MISMATCH")


def _verify_bridge() -> None:
    stage15 = Path("/var/lib/u-opti/smite-stage15-xhttp-bridge")
    if stage15.exists() or stage15.is_symlink():
        host = _load_module("uopti_broker_stage15_bridge", HERE / "smite-stage15-xhttp-bridge.py")
        host.verify()  # No fallback for prepared, corrupt or rolled-back state.
        return
    host = _load_module(
        "uopti_broker_bridge_install",
        HERE / "smite-rc5-xhttp-bridge-install.py"
    )
    host.verify()  # read-only effective nginx -T, TLS probe, committed journal


def _apply_route(port: int, path: str) -> None:
    # Exact fixed, digest-pinned root tool. No shell, no arbitrary executable.
    try:
        p = subprocess.run(
            [str(HELPER), "--port", str(port), "--path", path,
             "--apply", "--confirm-local-root"],
            capture_output=True, timeout=35, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrokerHold("ROUTE_APPLY_UNCERTAIN") from exc
    if p.returncode != 0 or b"RESULT=PASS_LOCAL_NGINX_ROUTE_CREATED" not in p.stdout:
        raise BrokerHold("ROUTE_APPLY_UNCERTAIN")


@contextmanager
def _lock():
    # Same exclusive engine lock as the U-OPTI bridge installer.
    fd = os.open(ENGINE_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        s = os.fstat(fd)
        if (not stat.S_ISREG(s.st_mode) or s.st_uid != 0
                or stat.S_IMODE(s.st_mode) != 0o600):
            raise BrokerHold("UNTRUSTED_ENGINE_LOCK")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError as exc:
        raise BrokerHold("ENGINE_BUSY") from exc
    finally:
        os.close(fd)


def stage_approval_request(wire: bytes, key: bytes, hint: dict) -> None:
    """Store only an authenticated proposal; this grants no route authority.

    Root must separately review the exact binding on its authenticated console.
    Never put caller-controlled content in a path or consume a route nonce here.
    """
    contract = _contract_module()
    fields = contract.TrustedGrant.__dataclass_fields__
    proposal = contract.TrustedGrant(**{k: hint[k] for k in fields})
    contract.admit(wire, key=key, expected=proposal,
                   seen_nonces=frozenset(), now=int(time.time()))
    directory = LEDGER.parent
    _dir(directory, mode=0o700)
    # Independent Web Approval is explicitly opt-in. Default behavior is
    # exactly the existing authenticated root TTY review. The marker is
    # root-owned and NEVER received from the Panel or Node request.
    marker = WEB_MODE_MARKER
    if marker.exists() or marker.is_symlink():
        mode = _json(_file(marker, mode=0o600), {"schema", "enabled", "queue_dir"})
        if (type(mode["schema"]) is not int or mode["schema"] != 1
                or mode["enabled"] is not True
                or mode["queue_dir"] != str(WEB_QUEUE_DIR)):
            raise BrokerHold("WEB_APPROVAL_MARKER_UNTRUSTED")
        queue = _load_module(
            "uopti_stage15_independent_queue",
            HERE / "smite-stage15-approval-queue.py")
        queue.stage(directory=Path(mode["queue_dir"]), wire=wire,
                    key=key, now=int(time.time()))
        return
    target = directory / "approval-request.json"
    writer = _load_module("uopti_broker_request_writer", HERE / "smite-rc5-xhttp-bridge-install.py")
    if target.exists() or target.is_symlink():
        _file(target, mode=0o600)
    writer.replace_file(target, wire, 0o600)


def process(wire: bytes, *, peer_uid: int, peer_gid: int) -> str:
    """Bounded local dispatch. Returns PASS only after local route tool PASS.

    Grant files must be separately installed from independently verified
    signed IR/KH evidence and an active unique lease, NEVER from wire.
    A consumed nonce plus failed apply means HOLD for explicit reconciliation.
    """
    if os.geteuid() != 0 or os.uname().nodename.split(".")[0].lower() != "ir":
        raise BrokerHold("IR_ROOT_ONLY")
    config = _configuration()
    if ((peer_uid, peer_gid) != (config["peer_uid"], config["peer_gid"])
            or type(wire) is not bytes or not 0 < len(wire) <= MAX_INPUT):
        raise BrokerHold("UNAUTHORIZED_LOCAL_PEER")
    # Decode only a strict child lookup hint; HMAC and exact fields verified
    # independently afterward. JSON cannot influence any directory prefix.
    hint = _json(wire, set(_contract_module().WIRE_FIELDS))
    child = hint.get("child")
    if type(child) is not str or not IDENT.fullmatch(child):
        raise BrokerHold("UNAPPROVED_CHILD_LOOKUP")
    with _lock():
        key = _file(KEY, mode=0o600, max_size=32)
        if len(key) != 32:
            raise BrokerHold("INVALID_BROKER_KEY")
        _verify_helper(config)
        _verify_bridge()
        try:
            expected = _approved_grant(child)
        except BrokerHold as exc:
            if str(exc) != "ROOT_OPERATOR_GRANT_REQUIRED":
                raise
            stage_approval_request(wire, key, hint)
            raise
        nonce_ledger = _ledger_module().DurableNonceLedger(
            LEDGER, instance_id=config["instance_id"]
        )
        approved = nonce_ledger.authenticate_and_consume(
            wire, key=key, expected=expected, now=int(time.time())
        )
        try:
            _apply_route(approved.port, approved.path)
        except Exception as exc:
            raise BrokerHold("ROUTE_APPLY_HOLD_RECONCILE_NO_RETRY") from exc
        return "PASS_ROUTE_ADDED"


def _receive(connection: socket.socket) -> bytes:
    connection.settimeout(5)
    frame = bytearray()
    while len(frame) <= MAX_INPUT:
        piece = connection.recv(min(1024, MAX_INPUT + 1 - len(frame)))
        if not piece:
            raise BrokerHold("INCOMPLETE_LOCAL_FRAME")
        frame.extend(piece)
        if b"\n" in piece:
            head, _, tail = bytes(frame).partition(b"\n")
            if tail or not head or len(head) > MAX_INPUT:
                raise BrokerHold("INVALID_LOCAL_FRAME")
            return head
    raise BrokerHold("OVERSIZED_LOCAL_FRAME")


def _send_reply(connection: socket.socket, response: str) -> None:
    """An early-disconnecting health probe must never kill the root broker."""
    try:
        connection.sendall((response + "\n").encode("ascii"))
    except (BrokenPipeError, ConnectionResetError):
        # The peer has gone away; no route action is retried or authorized.
        pass


def serve() -> None:
    """Explicit local root service command. No TCP listener, no auto-install."""
    if os.geteuid() != 0 or os.uname().nodename.split(".")[0].lower() != "ir":
        raise BrokerHold("IR_ROOT_ONLY")
    config = _configuration()
    _dir(SOCKET.parent, mode=0o750, gid=config["peer_gid"])
    if SOCKET.exists() or SOCKET.is_symlink():
        raise BrokerHold("SOCKET_EXISTS_REQUIRES_OPERATOR")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(SOCKET))
        try:
            os.chown(SOCKET, 0, config["peer_gid"])
            os.chmod(SOCKET, 0o660)
            server.listen(4)
            while True:
                with server.accept()[0] as connection:
                    try:
                        creds = connection.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED,
                            struct.calcsize("3i"),
                        )
                        pid, uid, gid = struct.unpack("3i", creds)
                        if pid <= 0:
                            raise BrokerHold("INVALID_PEER_PROCESS")
                        result = process(_receive(connection),
                                         peer_uid=uid, peer_gid=gid)
                        response = result
                    except BrokerHold as exc:
                        # Expose only this pre-transaction state to the Node so
                        # the Panel can guide a separate root approval. Other
                        # broker details remain private and ambiguous failures
                        # are never converted into retryable instructions.
                        response = ("HOLD_ROOT_OPERATOR_GRANT_REQUIRED"
                                    if str(exc) == "ROOT_OPERATOR_GRANT_REQUIRED"
                                    else "HOLD")
                    except Exception:
                        response = "HOLD"
                    _send_reply(connection, response)
        finally:
            # Remove only our socket entry; never replace a pre-existing path.
            SOCKET.unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.argv != [sys.argv[0], "--serve"]:
        raise SystemExit("HOLD_USE_EXPLICIT_SERVE_ONLY")
    try:
        serve()
    except Exception:
        raise SystemExit("HOLD_NO_SERVER_STARTED")
