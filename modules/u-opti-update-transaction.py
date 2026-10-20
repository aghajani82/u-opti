#!/usr/bin/env python3
"""Recoverable U-OPTI updater transaction, experimental closeout integration.

Real updater API: apply <staged-dir> <persistent-backup-dir> <module names...>
Startup guard: recover (BEFORE loading any U-OPTI module).

All candidate bytes are already downloaded, syntax/feature-validated and
backed up by u-opti. The transaction refuses ambiguous/foreign states.
No services, network, Nginx, Docker, Smite or shell source changes.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

INSTALL = Path("/usr/local/bin/u-opti")
LIB = Path("/usr/local/lib/u-opti")
TXN_NAME = ".uopti-update-pending"
LOCK_NAME = ".uopti-update-lock"
DONE_NAME = ".uopti-update-finished"
MAX_BYTES = 4 * 1024 * 1024
VALID_MODULE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z")
SCHEMA = 1


class Hold(RuntimeError):
    pass


class SimulatedCrash(BaseException):
    """Lab-injected interruption; intentionally bypasses Exception cleanup."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sync_dir(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                         | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _is_private_dir(path: Path) -> bool:
    try:
        s = path.lstat()
    except FileNotFoundError:
        return False
    return (stat.S_ISDIR(s.st_mode) and s.st_uid == os.geteuid()
            and stat.S_IMODE(s.st_mode) == 0o700)


def _read(path: Path, *, allow_missing=False) -> tuple[bytes | None, int | None]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        if allow_missing:
            return None, None
        raise Hold("REQUIRED_TRANSACTION_FILE_MISSING")
    except OSError as exc:
        raise Hold("UNSAFE_TRANSACTION_FILE") from exc
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_size > MAX_BYTES):
            raise Hold("UNTRUSTED_TRANSACTION_FILE")
        blob = file.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            raise Hold("OVERSIZED_TRANSACTION_FILE")
        return blob, stat.S_IMODE(info.st_mode)


def _atomic(path: Path, data: bytes, mode: int) -> None:
    if path.is_symlink() or path.parent.is_symlink() or not path.parent.is_dir():
        raise Hold("UNSAFE_UPDATE_TARGET")
    if path.exists():
        _read(path)
    fd, name = tempfile.mkstemp(prefix=".uopti-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), mode)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        _sync_dir(path.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


@contextlib.contextmanager
def _lock(lib: Path):
    if not lib.is_dir() or lib.is_symlink():
        raise Hold("INVALID_INSTALL_ROOT")
    lock = lib / LOCK_NAME
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise Hold("UNTRUSTED_UPDATE_LOCK")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _paths(lib: Path, install: Path, modules: list[str]) -> dict[str, Path]:
    if not modules or len(modules) != len(set(modules)):
        raise Hold("INVALID_MODULE_SET")
    if any(not VALID_MODULE.fullmatch(name) or name in
           ("u-opti", "VERSION", "common.sh") for name in modules):
        raise Hold("UNSAFE_MODULE_NAME")
    if (lib.is_symlink() or lib.joinpath("modules").is_symlink()
            or not lib.joinpath("modules").is_dir()
            or install.is_symlink() or install.parent.is_symlink()):
        raise Hold("UNSAFE_INSTALL_PATHS")
    items = {"u-opti": install, "common.sh": lib / "common.sh",
             "VERSION": lib / "VERSION"}
    items.update({name: lib / "modules" / name for name in modules})
    return items


def _manifest(txn: Path) -> dict:
    if not _is_private_dir(txn):
        raise Hold("UNTRUSTED_PENDING_TRANSACTION")
    raw, _ = _read(txn / "manifest.json")
    try:
        data = json.loads(raw)
        if (data["schema"] != SCHEMA
                or not isinstance(data["files"], dict)
                or not isinstance(data["backup"], str)
                or len(data["files"]) < 4):
            raise ValueError("invalid schema")
    except (ValueError, KeyError, TypeError) as exc:
        raise Hold("INVALID_RECOVERY_MANIFEST") from exc
    return data


def _recover_locked(lib: Path, install: Path) -> str:
    txn = lib / TXN_NAME
    if not txn.exists() and not txn.is_symlink():
        return "NO_PENDING_UPDATE"
    data = _manifest(txn)
    backup = Path(data["backup"])
    if (backup.parent != lib or not backup.name.startswith(".uopti-backup-")
            or not _is_private_dir(backup)):
        raise Hold("UNTRUSTED_RECOVERY_BACKUP")
    names = [k for k in data["files"] if k not in ("u-opti", "common.sh", "VERSION")]
    destinations = _paths(lib, install, names)

    restore = {}
    # Preflight ALL files before touching any: unknown operator changes HOLD.
    for name, record in data["files"].items():
        if not isinstance(record, dict) or set(record) != {
            "before", "after", "old_mode", "new_mode"
        }:
            raise Hold("UNTRUSTED_RECOVERY_ENTRY")
        dest = destinations[name]
        old = record["before"]
        expected_new = record["after"]
        if (old is not None and (not isinstance(old, str) or len(old) != 64)
                or not isinstance(expected_new, str) or len(expected_new) != 64):
            raise Hold("INVALID_RECOVERY_HASH")
        if old is None:
            if not (backup / ("." + name + "-was-missing")).is_file():
                raise Hold("MISSING_ORIGINAL_ABSENCE_MARKER")
            previous = None
        else:
            previous, _ = _read(backup / name)
            if _sha(previous) != old:
                raise Hold("BACKUP_CONTENT_DRIFT")
        current, _ = _read(dest, allow_missing=True)
        if current is not None and _sha(current) not in (old, expected_new):
            raise Hold("UNRECOGNIZED_LIVE_UPDATE_FILE")
        if current is None and old is not None:
            raise Hold("UNEXPECTED_MISSING_INSTALLED_FILE")
        restore[name] = (previous, record["old_mode"])

    for name, (previous, mode) in restore.items():
        dest = destinations[name]
        if previous is None:
            if dest.is_symlink():
                raise Hold("UNSAFE_NEW_UPDATE_TARGET")
            if dest.exists():
                dest.unlink()
                _sync_dir(dest.parent)
        else:
            if type(mode) is not int or not 0 < mode <= 0o777:
                raise Hold("UNTRUSTED_RECOVERY_MODE")
            _atomic(dest, previous, mode)
    # Persistent backup intentionally retained after recovered interruptions.
    _clear_pending(txn)
    return "ROLLED_BACK_FROM_DURABLE_JOURNAL"


def _clear_finished(done: Path) -> None:
    # Safe cleanup of fully committed/rolled-back transaction evidence.
    if not _is_private_dir(done) or sorted(p.name for p in done.iterdir()) != [
        "manifest.json", "rescue.py"
    ]:
        raise Hold("UNTRUSTED_FINISHED_TRANSACTION")
    for name in ("manifest.json", "rescue.py"):
        (done / name).unlink()
    _sync_dir(done)
    done.rmdir()
    _sync_dir(done.parent)


def _clear_pending(txn: Path) -> None:
    # IMPORTANT: Don't unlink manifest.json while its directory is still
    # named PENDING: a crash in the middle would destroy recovery metadata.
    # Rename PENDING -> FINISHED atomically only AFTER all target writes
    # and hashes have been verified, or the old state has been restored.
    done = txn.parent / DONE_NAME
    if done.exists() or done.is_symlink():
        _clear_finished(done)
    if not _is_private_dir(txn) or sorted(p.name for p in txn.iterdir()) != [
        "manifest.json", "rescue.py"
    ]:
        raise Hold("UNRECOGNIZED_PENDING_CONTENT")
    os.replace(txn, done)
    _sync_dir(done.parent)
    _clear_finished(done)


def recover(*, lib=LIB, install=INSTALL) -> str:
    with _lock(lib):
        return _recover_locked(lib, install)


def apply(stage: Path, backup: Path, module_names: list[str],
          *, lib=LIB, install=INSTALL, crash_after: int | None = None) -> str:
    """Install the already verified staged update atomically per file.

    A durable journal + bundled independent rescue code is written before
    the FIRST mutation. Crash recovery happens on next u-opti startup.
    """
    with _lock(lib):
        txn = lib / TXN_NAME
        if (lib / DONE_NAME).exists() or (lib / DONE_NAME).is_symlink():
            _clear_finished(lib / DONE_NAME)
        if txn.exists() or txn.is_symlink():
            raise Hold("PENDING_UPDATE_REQUIRES_RECOVERY")
        paths = _paths(lib, install, module_names)
        if (stage.is_symlink() or not _is_private_dir(stage)
                or backup.parent != lib or not backup.name.startswith(".uopti-backup-")
                or not _is_private_dir(backup)):
            raise Hold("UNTRUSTED_STAGE_OR_BACKUP")
        candidates = {}
        records = {}
        for name, dest in paths.items():
            candidate, _ = _read(stage / name)
            previous, old_mode = _read(dest, allow_missing=True)
            if previous is None:
                marker = backup / ("." + name + "-was-missing")
                if not marker.is_file() or marker.is_symlink():
                    raise Hold("MISSING_BACKUP_MARKER")
            else:
                saved, _ = _read(backup / name)
                if saved != previous:
                    raise Hold("BACKUP_IS_NOT_CURRENT_INSTALL")
            mode = 0o644 if name == "VERSION" else 0o755
            candidates[name] = candidate
            records[name] = {
                "before": _sha(previous) if previous is not None else None,
                "after": _sha(candidate), "old_mode": old_mode,
                "new_mode": mode,
            }

        txn.mkdir(mode=0o700)
        try:
            # Copy this already executing helper into a stable rescue location
            # so updating its own module cannot invalidate next-start recovery.
            rescue, _ = _read(Path(__file__))
            _atomic(txn / "rescue.py", rescue, 0o600)
            _atomic(txn / "manifest.json", (
                json.dumps({"schema": SCHEMA, "backup": str(backup),
                            "files": records}, sort_keys=True,
                           separators=(",", ":")) + "\n"
            ).encode(), 0o600)
            _sync_dir(txn)
            _sync_dir(lib)
        except Exception:
            # No installed paths have been touched yet; leave invalid
            # pre-journal state quarantined rather than delete evidence.
            raise

        for i, (name, dest) in enumerate(paths.items(), 1):
            _atomic(dest, candidates[name], records[name]["new_mode"])
            if crash_after is not None and i == crash_after:
                raise SimulatedCrash("LAB_POWER_LOSS_AFTER_ATOMIC_FILE")
        for name, dest in paths.items():
            existing, _ = _read(dest)
            if _sha(existing) != records[name]["after"]:
                raise Hold("FAILED_INSTALLED_CONTENT_VERIFICATION")
        _clear_pending(txn)
        return "VERIFIED_TRANSACTION_COMMIT"


def main() -> int:
    try:
        if len(sys.argv) == 2 and sys.argv[1] == "recover":
            print(recover())
            return 0
        if len(sys.argv) >= 5 and sys.argv[1] == "apply":
            print(apply(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4:]))
            return 0
        raise Hold("INVALID_UPDATER_TRANSACTION_COMMAND")
    except (Hold, OSError, ValueError) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
