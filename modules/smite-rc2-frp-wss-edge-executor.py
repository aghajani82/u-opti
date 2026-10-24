#!/usr/bin/env python3
"""IR-only RC.2 WSS Nginx edge transaction (no Node/Compose changes).

A signed Smite Node must be separately prepared before a tunnel is created.
The existing TLS/8443 Panel vhost is NEVER modified here. Nginx stream
permits only exact SNI+KH IPv4 into an alternate TLS/8444 clone; regular
connections continue to 8443. This trial requires operator-confirmed KH IP,
pinned preflight hashes, provider snapshot/console, and a separate manual
interactive grant for any mutation. Not wired to U-OPTI beginner menu.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "uopti_rc2_wss_edge_plan", HERE / "smite-rc2-frp-wss-edge-plan.py"
)
assert SPEC and SPEC.loader
edge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(edge)

STATE = Path("/var/lib/u-opti/smite-rc2-frp-wss-edge")
JOURNAL = STATE / "record.json"
OLD_MAP = STATE / "stream-map.before"
LOCK = Path("/run/lock/u-opti-smite-engine.lock")
TRIAL_FLAG = "UOPTI_SMITE_RC2_WSS_EDGE_TRIAL"
SNAPSHOT_CONFIRM = "SNAPSHOTS-AND-IR-CONSOLE-VERIFIED"
CONFIRM = {
    "apply": "ACTIVATE-IR-RC2-WSS-EDGE",
    "rollback": "ROLLBACK-IR-RC2-WSS-EDGE",
    "recover": "RECOVER-IR-RC2-WSS-EDGE",
}
SHA = re.compile(r"^[a-f0-9]{64}$")
MAX_BYTES = 262144


class Hold(Exception):
    pass


def require(value: bool, reason: str) -> None:
    if not value:
        raise Hold(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_file(path: Path, limit: int = MAX_BYTES) -> bytes:
    try:
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                and info.st_nlink == 1 and not info.st_mode & 0o022
                and 0 <= info.st_size <= limit, "UNTRUSTED_FILE")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            st = os.fstat(f.fileno())
            require((info.st_dev, info.st_ino) == (st.st_dev, st.st_ino),
                    "FILE_DRIFT")
            data = f.read(limit + 1)
        require(len(data) <= limit, "FILE_OVERSIZED")
        return data
    except OSError as error:
        raise Hold("FILE_READ_FAILED") from error


def safe_dir(path: Path, private: bool = False) -> None:
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0,
            "UNSAFE_STATE_DIRECTORY")
    mode = stat.S_IMODE(info.st_mode)
    require(mode == 0o700 if private else not mode & 0o022,
            "UNSAFE_STATE_DIRECTORY_MODE")


def absent(path: Path) -> bool:
    return not path.exists() and not path.is_symlink()


def sync_parent(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_mkdir(path: Path) -> None:
    require(absent(path), "TARGET_ALREADY_EXISTS")
    safe_dir(path.parent)
    path.mkdir(mode=0o700)
    safe_dir(path, private=True)
    sync_parent(path.parent)


def new_file(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as out:
        os.fchmod(out.fileno(), mode)
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    sync_parent(path.parent)


def atomic_file(path: Path, data: bytes, mode: int) -> None:
    require(not path.is_symlink(), "DESTINATION_SYMLINK")
    fd, temp = tempfile.mkstemp(prefix=".uopti-rc2-wss-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), mode)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        sync_parent(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def lock():
    require(not LOCK.is_symlink(), "ENGINE_LOCK_SYMLINK")
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and stat.S_IMODE(info.st_mode) == 0o600,
            "UNTRUSTED_ENGINE_LOCK")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise Hold("ANOTHER_ENGINE_TRANSACTION_ACTIVE") from exc
    return fd


def run(command: list[str], timeout: int = 30) -> None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
        require(result.returncode == 0, "SERVICE_OPERATION_FAILED")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Hold("SERVICE_OPERATION_FAILED") from error


def verify_host() -> None:
    require(os.geteuid() == 0 and os.uname().nodename.split(".")[0].lower() == "ir",
            "IR_ROOT_ONLY")
    safe_dir(edge.TLS_SOURCE.parent)
    safe_dir(edge.STREAM_SOURCE.parent)
    safe_dir(edge.FRP_MAP.parent)


def candidate(ip: str, original_backend_sha: str, original_map_sha: str
              ) -> tuple[bytes, bytes, bytes, bytes, bytes, int]:
    peer = edge.kh_ip(ip)
    require(SHA.fullmatch(original_backend_sha) is not None
            and SHA.fullmatch(original_map_sha) is not None,
            "PINNED_DIGESTS_REQUIRED")
    source = safe_file(edge.TLS_SOURCE)
    stream = safe_file(edge.STREAM_SOURCE)
    mapping = safe_file(edge.FRP_MAP)
    require(sha(source) == original_backend_sha
            and sha(mapping) == original_map_sha, "PINNED_SOURCE_DRIFT")
    edge.stream_gate(stream.decode())
    alt = edge.render_alt(source.decode()).encode()
    new_map = edge.render_map(mapping.decode(), peer).encode()
    require(absent(edge.ALT_CANDIDATE), "ALT_TLS_BACKEND_EXISTS")
    edge.loopback_port_free(edge.ALT_PORT)
    return source, stream, mapping, alt, new_map, stat.S_IMODE(edge.FRP_MAP.lstat().st_mode)


def journal_record() -> dict:
    safe_dir(STATE, private=True)
    require(absent(STATE / ".record.next"), "UNRESOLVED_JOURNAL_SWAP")
    data = safe_file(JOURNAL, 8192)
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise Hold("JOURNAL_CORRUPT") from error
    keys = {"schema", "state", "peer_ip", "backend_old",
            "stream_old", "map_old", "map_new", "alt_new", "map_mode"}
    require(isinstance(doc, dict) and set(doc) == keys
            and doc["schema"] == 1 and doc["state"] in ("PREPARED", "COMMITTED")
            and doc["map_mode"] in (0o600, 0o640, 0o644)
            and all(isinstance(doc[k], str) and SHA.fullmatch(doc[k])
                    for k in ("backend_old", "stream_old", "map_old",
                              "map_new", "alt_new")),
            "JOURNAL_CORRUPT")
    require(edge.kh_ip(doc["peer_ip"]) == doc["peer_ip"], "JOURNAL_BAD_PEER")
    return doc


def prepare_journal(ip: str, source: bytes, stream: bytes, mapping: bytes,
                    alt: bytes, new_map: bytes, mode: int) -> None:
    private_mkdir(STATE)
    new_file(OLD_MAP, mapping)
    doc = {
        "schema": 1, "state": "PREPARED", "peer_ip": ip,
        "backend_old": sha(source), "stream_old": sha(stream),
        "map_old": sha(mapping), "map_new": sha(new_map),
        "alt_new": sha(alt), "map_mode": mode,
    }
    new_file(JOURNAL, (json.dumps(doc, sort_keys=True) + "\n").encode())


def commit_journal(doc: dict) -> None:
    require(doc["state"] == "PREPARED", "JOURNAL_ALREADY_COMMITTED")
    updated = dict(doc, state="COMMITTED")
    tmp = STATE / ".record.next"
    new_file(tmp, (json.dumps(updated, sort_keys=True) + "\n").encode())
    os.replace(tmp, JOURNAL)
    sync_parent(STATE)


def check_protected(doc: dict) -> None:
    require(sha(safe_file(edge.TLS_SOURCE)) == doc["backend_old"]
            and sha(safe_file(edge.STREAM_SOURCE)) == doc["stream_old"],
            "PROTECTED_NGINX_INPUT_DRIFT")
    backup = safe_file(OLD_MAP)
    require(sha(backup) == doc["map_old"], "MAP_BACKUP_DRIFT")


def rollback_locked(doc: dict) -> None:
    check_protected(doc)
    current_map = safe_file(edge.FRP_MAP)
    require(sha(current_map) in (doc["map_new"], doc["map_old"]),
            "EXTERNAL_STREAM_MAP_DRIFT")
    if not absent(edge.ALT_CANDIDATE):
        require(sha(safe_file(edge.ALT_CANDIDATE)) == doc["alt_new"],
                "EXTERNAL_TLS_BACKEND_DRIFT")
    else:
        require(doc["state"] == "PREPARED" or sha(current_map) == doc["map_old"],
                "COMMITTED_BACKEND_MISSING")
    if sha(current_map) != doc["map_old"]:
        atomic_file(edge.FRP_MAP, safe_file(OLD_MAP), doc["map_mode"])
    if not absent(edge.ALT_CANDIDATE):
        edge.ALT_CANDIDATE.unlink()
        sync_parent(edge.ALT_CANDIDATE.parent)
    run(["nginx", "-t"])
    run(["systemctl", "reload", "nginx"])
    require(sha(safe_file(edge.FRP_MAP)) == doc["map_old"]
            and absent(edge.ALT_CANDIDATE), "ROLLBACK_DRIFT")
    JOURNAL.unlink()
    OLD_MAP.unlink()
    sync_parent(STATE)
    STATE.rmdir()
    sync_parent(STATE.parent)


def apply(ip: str, backend_sha: str, map_sha: str, *, inject: str = "") -> None:
    fd = lock()
    try:
        verify_host()
        require(absent(STATE), "UNRESOLVED_WSS_JOURNAL")
        source, stream, mapping, alt, new_map, mode = candidate(
            ip, backend_sha, map_sha)
        require(mode in (0o600, 0o640, 0o644), "MAP_MODE_NOT_REVIEWED")
        run(["nginx", "-t"])
        prepare_journal(ip, source, stream, mapping, alt, new_map, mode)
        try:
            # Stage the nginx .conf outside included path and publish only
            # complete bytes with os.replace (without overwriting an owner file).
            fd_tmp, tmp = tempfile.mkstemp(
                prefix=".uopti-rc2-alt-", dir=edge.ALT_CANDIDATE.parent)
            try:
                with os.fdopen(fd_tmp, "wb") as out:
                    os.fchmod(out.fileno(), 0o644)
                    out.write(alt)
                    out.flush()
                    os.fsync(out.fileno())
                require(absent(edge.ALT_CANDIDATE), "ALT_BACKEND_RACE")
                os.replace(tmp, edge.ALT_CANDIDATE)
                sync_parent(edge.ALT_CANDIDATE.parent)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            if inject == "after-alt":
                raise RuntimeError("SIMULATED_POWER_LOSS_AFTER_ALT")
            atomic_file(edge.FRP_MAP, new_map, mode)
            if inject == "after-map":
                raise RuntimeError("SIMULATED_POWER_LOSS_AFTER_MAP")
            run(["nginx", "-t"])
            run(["systemctl", "reload", "nginx"])
            check_protected(journal_record())
            require(sha(safe_file(edge.FRP_MAP)) == sha(new_map)
                    and sha(safe_file(edge.ALT_CANDIDATE)) == sha(alt),
                    "POST_RELOAD_SOURCE_DRIFT")
            commit_journal(journal_record())
            print("IR_RC2_WSS_EDGE=COMMITTED")
            print("PUBLIC_NON_443_PORT_CHANGE=NONE")
            print("NODE_RESTART=NO")
            print("WSS_PEER_IP=" + ip)
            print("FRP_TUNNEL=NOT_CREATED")
        except RuntimeError:
            # Test-only power loss injection. Leave PREPARED journal for
            # explicitly authorized recovery and do not auto-retry.
            raise
        except Exception as exc:
            try:
                rollback_locked(journal_record())
            except Exception as recovery:
                raise Hold("CRITICAL_MANUAL_EDGE_RECOVERY_REQUIRED") from recovery
            raise Hold("EDGE_ACTIVATION_FAILED_ROLLED_BACK") from exc
    finally:
        os.close(fd)


def verify() -> None:
    verify_host()
    doc = journal_record()
    require(doc["state"] == "COMMITTED", "EDGE_TRANSACTION_INCOMPLETE")
    check_protected(doc)
    require(sha(safe_file(edge.FRP_MAP)) == doc["map_new"]
            and sha(safe_file(edge.ALT_CANDIDATE)) == doc["alt_new"],
            "ACTIVE_EDGE_DRIFT")
    run(["nginx", "-t"])
    print("IR_RC2_WSS_EDGE_VERIFY=PASS_READ_ONLY")
    print("KH_IP_MAP=" + doc["peer_ip"])
    print("NODE_RESTART=NO")
    print("LIVE_CHANGES=NONE")


def rollback() -> None:
    fd = lock()
    try:
        verify_host()
        doc = journal_record()
        require(doc["state"] == "COMMITTED", "USE_RECOVER_FOR_INTERRUPTED")
        rollback_locked(doc)
        print("IR_RC2_WSS_EDGE_ROLLBACK=PASS")
    finally:
        os.close(fd)


def recover() -> None:
    fd = lock()
    try:
        verify_host()
        doc = journal_record()
        require(doc["state"] == "PREPARED", "USE_ROLLBACK_FOR_COMMITTED")
        rollback_locked(doc)
        print("IR_RC2_WSS_EDGE_RECOVERY=PASS")
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("apply", "verify", "rollback", "recover"))
    parser.add_argument("--kh-ip", default="")
    parser.add_argument("--backend-sha", default="")
    parser.add_argument("--map-sha", default="")
    parser.add_argument("--confirm-snapshot", default="")
    args = parser.parse_args()
    try:
        if args.action != "verify":
            require(os.environ.get(TRIAL_FLAG) == "YES", "TRIAL_FLAG_REQUIRED")
            require(args.confirm_snapshot == SNAPSHOT_CONFIRM,
                    "SNAPSHOT_AND_CONSOLE_CONFIRMATION_REQUIRED")
            require(sys.stdin.isatty(), "INTERACTIVE_CONFIRMATION_REQUIRED")
            require(input("Type " + CONFIRM[args.action] + " to authorize: ").strip()
                    == CONFIRM[args.action], "OPERATOR_CANCELLED")
        if args.action == "apply":
            apply(args.kh_ip, args.backend_sha, args.map_sha)
        elif args.action == "verify":
            verify()
        elif args.action == "rollback":
            rollback()
        else:
            recover()
        return 0
    except (Hold, OSError, ValueError, TypeError, KeyError, UnicodeError,
            subprocess.SubprocessError, RuntimeError) as exc:
        value = str(exc)
        if not re.fullmatch(r"[A-Z0-9_]{1,100}", value):
            value = "UNTRUSTED_EDGE_TRANSACTION"
        print("HOLD: " + value, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
