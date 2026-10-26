#!/usr/bin/env python3
"""U-OPTI RC5 Smite Bridge: guarded local IR-only one-time host transaction.

Not a remotely callable endpoint, not a release installer, not authorized for
deployment on the existing field-trial servers. U-OPTI owns the TLS backend;
no modifications are made to the working legacy XHTTP routes or FRPS.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ADMISSION_FILE = HERE / "smite-rc5-xhttp-bridge-admission.py"
spec = importlib.util.spec_from_file_location("uopti_rc5_bridge_admission", ADMISSION_FILE)
if spec is None or spec.loader is None:
    raise SystemExit("HOLD_ADMISSION_MODULE_MISSING")
admission = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = admission
spec.loader.exec_module(admission)

BACKEND = admission.BACKEND
BRIDGE = admission.BRIDGE
ROUTE_DIR = admission.ROUTE_DIR
LOCK = Path("/run/lock/u-opti-smite-engine.lock")
TX_ROOT = Path("/var/lib/u-opti/smite-rc5-xhttp-bridge")
TX_DIR = TX_ROOT / "ir"
BACKUP = TX_DIR / "backend.before"
JOURNAL = TX_DIR / "journal.json"
BRIDGE_BYTES = b"include /etc/nginx/smite-xhttp-routes/*.conf;\n"
NGINX = admission.NGINX
CONSENT = "AUTHORIZE-IR-RC5-XHTTP-BRIDGE"
OPTIN = "UOPTI_RC5_IR_XHTTP_BRIDGE_TRIAL"


class Hold(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise Hold(code)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def absent(path: Path) -> bool:
    return not path.exists() and not path.is_symlink()


def trusted_dir(path: Path, *, mode: int | None = None) -> None:
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
            and not info.st_mode & 0o022, "UNTRUSTED_DIRECTORY")
    if mode is not None:
        require(stat.S_IMODE(info.st_mode) == mode, "UNTRUSTED_DIRECTORY_MODE")


def trusted_file(path: Path, limit: int = 131072, *, mode: int | None = None) -> bytes:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and info.st_nlink == 1 and not info.st_mode & 0o022
            and 0 < info.st_size <= limit, "UNTRUSTED_FILE")
    if mode is not None:
        require(stat.S_IMODE(info.st_mode) == mode, "UNTRUSTED_FILE_MODE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        actual = os.fstat(fd)
        require((actual.st_dev, actual.st_ino) == (info.st_dev, info.st_ino),
                "FILE_RACE")
        raw = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    require(len(raw) <= limit, "FILE_TOO_LARGE")
    return raw


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def new_file(path: Path, data: bytes, mode: int) -> None:
    require(absent(path), "TARGET_ALREADY_EXISTS")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as out:
        os.fchmod(out.fileno(), mode)
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    sync_dir(path.parent)


def replace_file(path: Path, data: bytes, mode: int) -> None:
    # Caller already holds shared host engine lock and verifies existing SHA.
    fd, name = tempfile.mkstemp(prefix=".smite-rc5-stage-", dir=path.parent)
    stage = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), mode)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(stage, path)
        sync_dir(path.parent)
    finally:
        if not absent(stage):
            stage.unlink()


def command(args: list[str]) -> None:
    try:
        proc = subprocess.run(args, capture_output=True, timeout=25)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("HOST_CHECK_UNAVAILABLE") from exc
    require(proc.returncode == 0, "HOST_CHECK_FAILED")


def nginx_test() -> None:
    command([NGINX, "-t"])


def nginx_reload() -> None:
    command(["/usr/bin/systemctl", "reload", "nginx"])


def probe_panel(domain: str) -> None:
    # Validate TLS and host routing via actual localhost public 443 (no -k).
    args = [
        "/usr/bin/curl", "-q", "--noproxy", "*", "-4",
        "--http1.1", "--connect-timeout", "6", "--max-time", "15",
        "--fail", "--silent", "--show-error", "--output", "/dev/null",
        "--resolve", f"{domain}:443:127.0.0.1",
        f"https://{domain}/",
    ]
    command(args)


def host_gate() -> None:
    require(os.geteuid() == 0
            and os.uname().nodename.split(".")[0].lower() == "ir",
            "IR_ROOT_ONLY")
    trusted_dir(BACKEND.parent)
    trusted_dir(BRIDGE.parent)
    trusted_dir(LOCK.parent)
    trusted_dir(TX_ROOT.parent)


def lock_host() -> int:
    require(absent(LOCK) or not LOCK.is_symlink(), "HOST_LOCK_SYMLINK")
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                and stat.S_IMODE(info.st_mode) == 0o600,
                "UNTRUSTED_HOST_LOCK")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold("HOST_ENGINE_LOCK_BUSY") from exc
        return fd
    except Exception:
        os.close(fd)
        raise


def journal_payload(state: str, plan: admission.BridgePlan) -> dict:
    return {
        "schema": 1,
        "state": state,
        "domain": plan.domain,
        "before_sha": digest(plan.original),
        "after_sha": digest(plan.candidate),
        "bridge_sha": digest(BRIDGE_BYTES),
    }


def private_txdir() -> None:
    if absent(TX_ROOT):
        TX_ROOT.mkdir(mode=0o700)
        sync_dir(TX_ROOT.parent)
    trusted_dir(TX_ROOT, mode=0o700)
    require(absent(TX_DIR), "EXISTING_TX_REQUIRES_REVIEW")
    TX_DIR.mkdir(mode=0o700)
    sync_dir(TX_ROOT)
    trusted_dir(TX_DIR, mode=0o700)


def prepare(plan: admission.BridgePlan) -> dict:
    private_txdir()
    new_file(BACKUP, plan.original, 0o600)
    record = journal_payload("PREPARED", plan)
    new_file(JOURNAL, (json.dumps(record, sort_keys=True) + "\n").encode(), 0o600)
    return record


def read_record() -> tuple[dict, bytes, bytes]:
    trusted_dir(TX_ROOT, mode=0o700)
    trusted_dir(TX_DIR, mode=0o700)
    raw = trusted_file(JOURNAL, 8192, mode=0o600)
    original = trusted_file(BACKUP, mode=0o600)
    try:
        record = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise Hold("INVALID_TRANSACTION_JOURNAL") from exc
    require(isinstance(record, dict) and set(record) == {
        "schema", "state", "domain", "before_sha", "after_sha", "bridge_sha",
    } and record["schema"] == 1
        and record["state"] in ("PREPARED", "COMMITTED", "ROLLED_BACK")
        and isinstance(record["domain"], str)
        and admission.DOMAIN.fullmatch(record["domain"])
        and all(isinstance(record[k], str) and len(record[k]) == 64
                and all(ch in "0123456789abcdef" for ch in record[k])
                for k in ("before_sha", "after_sha", "bridge_sha")),
        "INVALID_TRANSACTION_RECORD")
    candidate = original.replace(admission.ROOT_LOCATION,
                                 admission.INCLUDE + b"\n" + admission.ROOT_LOCATION, 1)
    require(original.count(admission.ROOT_LOCATION) == 1
            and digest(original) == record["before_sha"]
            and digest(candidate) == record["after_sha"]
            and record["bridge_sha"] == digest(BRIDGE_BYTES),
            "TRANSACTION_BACKUP_MISMATCH")
    return record, original, candidate


def update_record(record: dict, state: str) -> None:
    current, _, _ = read_record()
    require(current == record, "JOURNAL_CHANGED")
    value = dict(record, state=state)
    replace_file(JOURNAL, (json.dumps(value, sort_keys=True) + "\n").encode(), 0o600)


def rollback_known(record: dict, original: bytes, candidate: bytes) -> None:
    # Refuse to destroy any routes installed after bridge creation, even on
    # an explicit operator rollback; those need independent ownership review.
    current_backend = trusted_file(BACKEND, mode=0o644)
    require(current_backend in (original, candidate), "BACKEND_EXTERNAL_DRIFT")
    if not absent(BRIDGE):
        require(trusted_file(BRIDGE, mode=0o644) == BRIDGE_BYTES,
                "BRIDGE_EXTERNAL_DRIFT")
    if not absent(ROUTE_DIR):
        trusted_dir(ROUTE_DIR, mode=0o700)
        require(not any(ROUTE_DIR.iterdir()), "MANAGED_ROUTES_REQUIRE_REVIEW")

    if current_backend == candidate:
        replace_file(BACKEND, original, 0o644)
    if not absent(BRIDGE):
        BRIDGE.unlink()
        sync_dir(BRIDGE.parent)
    if not absent(ROUTE_DIR):
        ROUTE_DIR.rmdir()
        sync_dir(ROUTE_DIR.parent)

    nginx_test()
    nginx_reload()
    probe_panel(record["domain"])
    update_record(record, "ROLLED_BACK")


def plan() -> admission.BridgePlan:
    host_gate()
    require(absent(TX_DIR) and absent(JOURNAL),
            "EXISTING_TX_REQUIRES_REVIEW")
    require(absent(BRIDGE) and absent(ROUTE_DIR), "BRIDGE_ALREADY_PRESENT")
    result = admission.audit_read_only()
    require(trusted_file(BACKEND, mode=0o644) == result.original,
            "BACKEND_CHANGED")
    return result


def apply() -> None:
    host_gate()
    lockfd = lock_host()
    try:
        result = plan()
        probe_panel(result.domain)
        record = prepare(result)
        try:
            # No route is published here: empty directory + bridge only.
            require(absent(ROUTE_DIR) and absent(BRIDGE), "BRIDGE_ALREADY_PRESENT")
            ROUTE_DIR.mkdir(mode=0o700)
            sync_dir(ROUTE_DIR.parent)
            trusted_dir(ROUTE_DIR, mode=0o700)
            new_file(BRIDGE, BRIDGE_BYTES, 0o644)
            require(trusted_file(BACKEND, mode=0o644) == result.original,
                    "BACKEND_CHANGED_BEFORE_COMMIT")
            replace_file(BACKEND, result.candidate, 0o644)
            nginx_test()
            nginx_reload()
            probe_panel(result.domain)
            require(trusted_file(BACKEND, mode=0o644) == result.candidate
                    and trusted_file(BRIDGE, mode=0o644) == BRIDGE_BYTES,
                    "POSTCOMMIT_CONTENT_DRIFT")
            update_record(record, "COMMITTED")
        except Exception as exc:
            # If rollback is not safe (drift or partial reload), HOLD with
            # prepared journal intact for explicit operator recovery.
            rollback_known(record, result.original, result.candidate)
            raise Hold("APPLY_FAILED_ROLLED_BACK") from exc
        print("RESULT=PASS_BRIDGE_COMMITTED")
        print("XHTTP_ROUTES_CREATED=NONE")
        print("LEGACY_XHTTP_FILE=UNCHANGED")
        print("FRPS_RESTART=NO")
    finally:
        os.close(lockfd)


def verify() -> None:
    host_gate()
    record, original, candidate = read_record()
    require(record["state"] == "COMMITTED", "TX_NOT_COMMITTED")
    require(trusted_file(BACKEND, mode=0o644) == candidate
            and trusted_file(BRIDGE, mode=0o644) == BRIDGE_BYTES,
            "BRIDGE_CONTENT_DRIFT")
    trusted_dir(ROUTE_DIR, mode=0o700)
    nginx_test()
    # This verification does not assert route existence or client traffic.
    print("RESULT=PASS_BRIDGE_VERIFY_READ_ONLY")
    print("LEGACY_XHTTP_FILE=UNCHANGED_BY_INSTALLER")
    print("LIVE_CHANGES=NONE")


def rollback() -> None:
    host_gate()
    lockfd = lock_host()
    try:
        record, original, candidate = read_record()
        require(record["state"] in ("PREPARED", "COMMITTED"),
                "TX_NOT_ROLLBACKABLE")
        rollback_known(record, original, candidate)
        print("RESULT=PASS_BRIDGE_ROLLED_BACK")
    finally:
        os.close(lockfd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "verify", "rollback"))
    args = parser.parse_args()
    try:
        if args.action == "plan":
            plan()
            print("RESULT=PASS_BRIDGE_PLAN_READ_ONLY")
            print("LIVE_CHANGES=NONE")
        elif args.action == "verify":
            verify()
        else:
            require(sys.stdin.isatty(), "INTERACTIVE_APPROVAL_REQUIRED")
            require(os.environ.get(OPTIN) == "YES", "EXPLICIT_OPTIN_REQUIRED")
            require(input(f"Type {CONSENT} to authorize: ").strip() == CONSENT,
                    "OPERATOR_CANCELLED")
            if args.action == "apply":
                apply()
            else:
                rollback()
        return 0
    except (Hold, admission.BridgeHold, OSError, ValueError, TypeError, KeyError,
            UnicodeError, subprocess.SubprocessError) as exc:
        reason = str(exc)
        if not reason or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789"
                             for ch in reason):
            reason = "UNTRUSTED_TRANSACTION_STATE"
        print("HOLD: " + reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
