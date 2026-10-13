#!/usr/bin/env python3
"""Synthetic unified IR/KH Sidecar transaction and crash recovery laboratory.

NO live deployment: refuses any write outside a marker-protected private
/tmp/uopti-bh-sandbox-* root. Fake service state is JSON; no Docker, systemd,
nginx, network or SSH actions are used. Candidate inputs must be private
and byte-for-byte reconciled with the Nginx/Sidecar compilers.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    obj = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(obj)
    return obj


pair = load("unified_pair", "smite-backhaul-sidecar-reconcile.py")
legacy = load("unified_legacy_recovery", "smite-backhaul-sidecar-recovery-lab.py")
sandbox = legacy.sandbox

JOURNAL = ".uopti-unified-transaction-journal.json"
BACKUP = ".uopti-unified-original-vhost"
RUNTIME = ".uopti-unified-mock-runtime.json"
LOCK = ".uopti-unified-exclusive-lock"
HEX = re.compile(r"[a-f0-9]{64}\Z")


class TransactionRefused(ValueError):
    pass


class SimulatedPowerLoss(BaseException):
    pass


def original_runtime(role: str) -> dict:
    if role not in pair.LAYOUT:
        raise TransactionRefused("Unsupported role")
    return {"role": role, "sidecar": "absent", "nginx_generation": 0,
            "smite": "unchanged", "frp": "unchanged", "xray": "unchanged"}


def runtime_state(role: str, generation: int) -> dict:
    item = original_runtime(role)
    if generation not in (0, 1):
        raise TransactionRefused("Unsupported generation")
    item.update(sidecar="running", nginx_generation=generation)
    return item


def _json_file(path: Path) -> dict:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_size > 32768
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise TransactionRefused("Private journal/runtime invalid")
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise TransactionRefused("Unreadable journal/runtime") from exc
    if not isinstance(content, dict):
        raise TransactionRefused("Unexpected journal/runtime")
    return content


def _save(root: Path, filename: str, value: dict) -> None:
    if filename not in (JOURNAL, RUNTIME):
        raise TransactionRefused("Unexpected write target")
    legacy._persist(root / filename, json.dumps(value, sort_keys=True).encode())


def _unlink(root: Path, filename: str) -> None:
    if filename not in (JOURNAL, BACKUP):
        raise TransactionRefused("Unexpected removal target")
    legacy._remove(root / filename)


@contextmanager
def mutex(root: Path):
    root = sandbox.check_sandbox(root)
    descriptor = os.open(root / LOCK, os.O_RDWR | os.O_CREAT |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077):
            raise TransactionRefused("Lock file unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TransactionRefused("Concurrent synthetic transaction blocked") from exc
        yield root
    finally:
        os.close(descriptor)


def bootstrap(root: Path, role: str) -> None:
    """Requires existing marker-only sandbox fixture, initialized by tests."""
    with mutex(root) as safe:
        if role not in pair.LAYOUT or any(
            (safe / fn).exists() or (safe / fn).is_symlink()
            for fn in (JOURNAL, BACKUP, RUNTIME)
        ):
            raise TransactionRefused("Already initialized or unknown role")
        _save(safe, RUNTIME, original_runtime(role))


def _read_runtime(root: Path, role: str) -> dict:
    state = _json_file(root / RUNTIME)
    if state not in (original_runtime(role),
                     runtime_state(role, 0), runtime_state(role, 1)):
        raise TransactionRefused("Unexpected mock service state; refuse mutation")
    return state


def _journal(root: Path) -> dict:
    doc = _json_file(root / JOURNAL)
    if not isinstance(doc, dict) or set(doc) != {
        "version", "role", "container", "resources"
    }:
        raise TransactionRefused("Journal schema mismatch")
    role = doc["role"]
    if (role not in pair.LAYOUT or doc["version"] != 2
            or doc["container"] != f"uopti-backhaul-sidecar-{role}"):
        raise TransactionRefused("Journal ownership mismatch")
    rows = doc["resources"]
    if not isinstance(rows, list) or len(rows) != len(pair.LAYOUT[role]):
        raise TransactionRefused("Journal lacks all owned files, including KH guard")
    for row, (name, (action, _, _)) in zip(rows, pair.LAYOUT[role].items()):
        if not isinstance(row, dict) or set(row) != {
            "path", "operation", "before_sha256", "applied_sha256"
        } or row["path"] != name or row["operation"] != action:
            raise TransactionRefused("Journal has unknown/duplicated owned resources")
        if not isinstance(row["applied_sha256"], str) or not HEX.fullmatch(row["applied_sha256"]):
            raise TransactionRefused("Invalid applied SHA256")
        before = row["before_sha256"]
        if action == "create":
            if before is not None:
                raise TransactionRefused("Created resource had unexpected baseline")
        elif (not isinstance(before, str) or not HEX.fullmatch(before)
              or before == row["applied_sha256"]):
            raise TransactionRefused("Invalid original vhost SHA256")
    return doc


def _states(root: Path, doc: dict) -> dict[str, str]:
    states = {}
    for item in doc["resources"]:
        target = sandbox.check_path(root, item["path"])
        if target.is_file():
            payload = target.read_bytes()
            actual = pair.sha(payload)
            if actual == item["applied_sha256"]:
                states[item["path"]] = "applied"
            elif item["operation"] == "edit" and actual == item["before_sha256"]:
                states[item["path"]] = "original"
            else:
                raise TransactionRefused("Unknown third-party file drift detected")
        elif item["operation"] == "create" and not target.is_symlink():
            states[item["path"]] = "original"
        else:
            raise TransactionRefused("Missing previously existing vhost or unsafe path")
    return states


def _verified_backup(root: Path, doc: dict, states: dict) -> bytes | None:
    backup_path = root / BACKUP
    if not backup_path.exists() and not backup_path.is_symlink():
        if all(x == "original" for x in states.values()):
            return None
        raise TransactionRefused("Original vhost backup missing; refuse rollback")
    info = backup_path.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077):
        raise TransactionRefused("Unsafe original backup")
    backup = backup_path.read_bytes()
    rows = [row for row in doc["resources"] if row["operation"] == "edit"]
    if len(rows) != 1 or pair.sha(backup) != rows[0]["before_sha256"]:
        raise TransactionRefused("Original vhost backup hash mismatch")
    return backup


def _validate(root: Path) -> tuple[dict, dict[str, str], bytes, dict]:
    doc = _journal(root)
    state = _read_runtime(root, doc["role"])
    files = _states(root, doc)
    original = _verified_backup(root, doc, files)
    return doc, files, original, state


def install_mock(root: Path, sidecar_dir: Path, nginx_dir: Path, role: str, *,
                 crash_at: str | None = None,
                 crash_after_file: int | None = None,
                 fail_at: str | None = None) -> dict:
    """Simulates journal -> backup -> files -> fake Sidecar -> fake Nginx.

    Normal injected errors attempt recovery; intentional BaseException crashes
    retain durable records for independent restart/recovery.
    """
    stages = ("after-journal", "after-backup", "after-files",
              "after-sidecar", "after-reload", "health")
    if (crash_at not in (*stages, None) or fail_at not in (*stages, None)
            or role not in pair.LAYOUT
            or crash_after_file is not None and (
                type(crash_after_file) is not int
                or not 1 <= crash_after_file <= len(pair.LAYOUT[role])
            )):
        raise TransactionRefused("Invalid fault point")
    # Preflight both byte-identical private candidates BEFORE any transaction.
    resources = pair.reconcile(role, sidecar_dir, nginx_dir)
    with mutex(root) as safe:
        if _read_runtime(safe, role) != original_runtime(role) or any(
            (safe / x).exists() or (safe / x).is_symlink()
            for x in (JOURNAL, BACKUP)
        ):
            raise TransactionRefused("Existing/partial Sidecar; refuse overwrite")
        for row in resources:
            target = sandbox.check_path(safe, row["path"])
            if row["operation"] == "create":
                if target.exists() or target.is_symlink():
                    raise TransactionRefused("Created target already exists")
            elif not target.is_file() or target.read_bytes() != row["before"]:
                raise TransactionRefused("Original vhost does not match reviewed backup")
        rows = [
            {"path": r["path"], "operation": r["operation"],
             "before_sha256": pair.sha(r["before"]) if r["before"] is not None else None,
             "applied_sha256": pair.sha(r["after"])}
            for r in resources
        ]
        journal = {"version": 2, "role": role,
                   "container": f"uopti-backhaul-sidecar-{role}",
                   "resources": rows}
        _save(safe, JOURNAL, journal)  # Journal is durable FIRST.

        def checkpoint(point: str) -> None:
            if crash_at == point:
                raise SimulatedPowerLoss("Synthetic power loss at " + point)
            if fail_at == point:
                raise TransactionRefused("Synthetic install fault at " + point)

        try:
            checkpoint("after-journal")
            before = next(x["before"] for x in resources if x["operation"] == "edit")
            legacy._persist(safe / BACKUP, before)  # Original backup SECOND.
            checkpoint("after-backup")
            for i, row in enumerate(resources, 1):
                target = sandbox.check_path(safe, row["path"], create_parents=True)
                legacy._persist(target, row["after"])
                if crash_after_file == i:
                    raise SimulatedPowerLoss("Synthetic mid-file power loss")
            checkpoint("after-files")
            _save(safe, RUNTIME, runtime_state(role, 0))
            checkpoint("after-sidecar")
            _save(safe, RUNTIME, runtime_state(role, 1))
            checkpoint("after-reload")
            checkpoint("health")
            return {"status": "SYNTHETIC_ACTIVE_NOT_DEPLOYED",
                    "role": role, "files": len(resources),
                    "authenticated_vless": False}
        except Exception:
            _recover_locked(safe)
            raise


def _recover_locked(root: Path, *, crash_after_service: bool = False,
                    crash_after_file: int | None = None,
                    crash_after_backup: bool = False) -> list[str]:
    doc, states, backup, runtime = _validate(root)
    if crash_after_file is not None and (
        type(crash_after_file) is not int
        or not 1 <= crash_after_file <= len(doc["resources"])
    ):
        raise TransactionRefused("Invalid recovery fault position")
    role = doc["role"]
    if runtime != original_runtime(role):
        _save(root, RUNTIME, original_runtime(role))
    if crash_after_service:
        raise SimulatedPowerLoss("Synthetic crash while reverting fake services")
    restored = 0
    for item in reversed(doc["resources"]):
        if states[item["path"]] == "applied":
            target = sandbox.check_path(root, item["path"])
            if item["operation"] == "create":
                legacy._remove(target)
            else:
                if backup is None:
                    raise TransactionRefused("Missing original backup for edit")
                legacy._persist(target, backup)
            restored += 1
            if restored == crash_after_file:
                raise SimulatedPowerLoss("Synthetic crash while recovering a file")
    # Recheck the FULL resource set before deleting the last journal.
    _, checked, _, runtime_now = _validate(root)
    if any(x != "original" for x in checked.values()) or runtime_now != original_runtime(role):
        raise TransactionRefused("Recovery incomplete; journal retained")
    if (root / BACKUP).exists():
        _unlink(root, BACKUP)
    if crash_after_backup:
        raise SimulatedPowerLoss("Synthetic crash after removing original backup")
    _unlink(root, JOURNAL)  # Delete journal LAST for resumable recovery.
    return ["SYNTHETIC_UNIFIED_ROLLBACK_COMPLETE",
            "Included IR backend or KH guarded public vhost",
            "Fake Sidecar, Nginx, FRP and Smite preserved/restored",
            "NO real system resources changed"]


def recover(root: Path, *, crash_after_service: bool = False,
            crash_after_file: int | None = None,
            crash_after_backup: bool = False) -> list[str]:
    with mutex(root) as safe:
        return _recover_locked(safe, crash_after_service=crash_after_service,
                               crash_after_file=crash_after_file,
                               crash_after_backup=crash_after_backup)


if __name__ == "__main__":
    raise SystemExit("Offline lab only. No live installation or rollback CLI.");
