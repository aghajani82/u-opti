#!/usr/bin/env python3
"""Crash-recovery laboratory for *synthetic* Backhaul Sidecar files.

NOT AN INSTALLER. Only a marker-protected direct child of /tmp is writable.
No network access, Docker, Nginx, system service, or host /etc modifications.
Journal and snapshots contain hashes, never token-bearing config contents.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat

_MODULE = Path(__file__).resolve().with_name("smite-backhaul-sidecar-sandbox.py")
_spec = importlib.util.spec_from_file_location("uopti_backhaul_sandbox_lab", _MODULE)
sandbox = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(sandbox)

JOURNAL = ".sidecar-recovery-lab-journal.json"
ORIGINAL = ".sidecar-recovery-lab-original"
LOCK = ".sidecar-recovery-lab-lock"


class RecoveryRefused(ValueError):
    pass


class SimulatedPowerLoss(BaseException):
    """Deliberately bypass ordinary Exception handlers: represents a crash."""


@contextmanager
def exclusive(root: Path):
    """Separate file lock, not shared with the older sandbox prototype."""
    root = sandbox.check_sandbox(root)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(root / LOCK, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise RecoveryRefused("Unsafe lock-file permissions")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryRefused("Concurrent synthetic recovery forbidden") from exc
        yield root
    finally:
        os.close(fd)


def _regular_private(root: Path, name: str) -> Path:
    dest = root / name
    info = dest.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise RecoveryRefused("Recovery state must be a private regular file")
    return dest


def _journal(root: Path) -> dict:
    file = _regular_private(root, JOURNAL)
    if file.stat().st_size > 16384:
        raise RecoveryRefused("Unreasonably large recovery journal")
    try:
        document = json.loads(file.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise RecoveryRefused("Recovery journal invalid") from exc
    if not isinstance(document, dict) or set(document) != {
        "version", "role", "container", "resources"
    }:
        raise RecoveryRefused("Recovery journal has unknown/missing fields")
    role = document["role"]
    if not isinstance(role, str) or role not in sandbox.rollback.ALLOW:
        raise RecoveryRefused("Unsupported journal role")
    if document["version"] != 1 or document["container"] != sandbox.rollback.CONTAINER[role]:
        raise RecoveryRefused("Unexpected journal version/container")
    resources = document["resources"]
    if not isinstance(resources, list) or len(resources) != len(sandbox.rollback.ALLOW[role]):
        raise RecoveryRefused("Incomplete journal resource list")
    owned = sandbox.rollback.ALLOW[role]
    if [r.get("path") if isinstance(r, dict) else None for r in resources] != list(owned):
        raise RecoveryRefused("Recovery resource order/scope changed")
    for r in resources:
        if not isinstance(r, dict) or set(r) != {
            "path", "operation", "before_sha256", "applied_sha256"
        } or r["operation"] != owned[r["path"]]:
            raise RecoveryRefused("Invalid recovery resource operation")
        sandbox.rollback._sha(r["applied_sha256"], "applied")
        if r["operation"] == "create":
            if r["before_sha256"] is not None:
                raise RecoveryRefused("Created resource must have absent baseline")
        else:
            sandbox.rollback._sha(r["before_sha256"], "baseline")
            if r["before_sha256"] == r["applied_sha256"]:
                raise RecoveryRefused("Edited resource has no recorded difference")
    return document


def _observed(root: Path, document: dict) -> dict[str, str]:
    """Read hashes only. Any unexpected resource blocks the entire recovery."""
    states = {}
    for r in document["resources"]:
        target = sandbox.check_path(root, r["path"])
        if target.exists():
            found = sandbox.digest(target.read_bytes())
            if found == r["applied_sha256"]:
                states[r["path"]] = "applied"
            elif r["operation"] == "edit" and found == r["before_sha256"]:
                states[r["path"]] = "original"
            else:
                raise RecoveryRefused("Resource drift detected: refuse all restoration")
        elif r["operation"] == "create":
            states[r["path"]] = "original"
        else:
            raise RecoveryRefused("Previously existing resource disappeared")
    return states


def _verify_original(root: Path, document: dict) -> bytes | None:
    if document["role"] == "kh":
        if (root / ORIGINAL).exists() or (root / ORIGINAL).is_symlink():
            raise RecoveryRefused("Unexpected KH original backup")
        return None
    try:
        backup = _regular_private(root, ORIGINAL).read_bytes()
    except FileNotFoundError as exc:
        raise RecoveryRefused("Original synthetic backend backup missing") from exc
    edits = [r for r in document["resources"] if r["operation"] == "edit"]
    if len(edits) != 1 or sandbox.digest(backup) != edits[0]["before_sha256"]:
        raise RecoveryRefused("Original synthetic backend backup hash mismatch")
    return backup


def _validate_locked(root: Path) -> tuple[dict, dict[str, str], bytes | None]:
    document = _journal(root)
    # Complete validation happens BEFORE touching ANY resource.
    states = _observed(root, document)
    backup = _verify_original(root, document)
    return document, states, backup


def begin_synthetic_transaction(
    root: Path, stage: Path, role: str, crash_after: int | None = None
) -> dict:
    """Write durable simulated journal BEFORE creating/editing synthetic files.

    crash_after=0 raises after journal commit but before the first file.
    crash_after=N raises immediately after the Nth file replacement.
    The intentionally interrupted transaction MUST be recovered independently.
    """
    if role not in sandbox.CANDIDATES:
        raise RecoveryRefused("Invalid role")
    if crash_after is not None and (
        type(crash_after) is not int or not 0 <= crash_after <= len(sandbox.CANDIDATES[role]) + (1 if role == "ir" else 0)
    ):
        raise RecoveryRefused("Invalid synthetic failure point")
    with exclusive(root) as safe:
        if any((safe / p).exists() or (safe / p).is_symlink()
               for p in (JOURNAL, ORIGINAL, sandbox.MANIFEST, sandbox.BACKUP)):
            raise RecoveryRefused("Another synthetic transaction already exists")
        files = sandbox.stage_payload(stage, role)
        targets = sandbox._prepare(safe, role, files)
        rows = [
            {
                "path": path, "operation": op,
                "before_sha256": sandbox.digest(before) if before is not None else None,
                "applied_sha256": sandbox.digest(after),
            }
            for path, (_, op, before, after) in targets.items()
        ]
        journal = {
            "version": 1, "role": role,
            "container": sandbox.rollback.CONTAINER[role],
            "resources": rows,
        }
        # Original mock backend and hashes are persisted before the first edit.
        for _, (_, op, before, _) in targets.items():
            if op == "edit":
                sandbox.atomic_write(safe / ORIGINAL, before)
        sandbox.atomic_write(
            safe / JOURNAL, json.dumps(journal, sort_keys=True).encode()
        )
        _validate_locked(safe)
        if crash_after == 0:
            raise SimulatedPowerLoss("Injected synthetic crash after journal")
        for index, (path, (target, _, _, data)) in enumerate(targets.items(), 1):
            sandbox.check_path(safe, path, create_parents=True)
            sandbox.atomic_write(target, data)
            if crash_after == index:
                raise SimulatedPowerLoss("Injected synthetic crash after file replacement")
        # Treat the fully written state as *unactivated*; journal is retained
        # deliberately for later recovery. Never runs service commands.
        _validate_locked(safe)
        return journal


def inspect_synthetic_recovery(root: Path) -> dict:
    with exclusive(root) as safe:
        document, states, _ = _validate_locked(safe)
        return {
            "role": document["role"],
            "applied": sum(v == "applied" for v in states.values()),
            "original": sum(v == "original" for v in states.values()),
            "recoverable": True,
            "note": "SANDBOX ONLY; NO LIVE HOST STATUS OR DEPLOYMENT AUTHORIZATION",
        }


def recover_synthetic_transaction(
    root: Path, crash_after_restored: int | None = None
) -> list[str]:
    """Recover after interruption. Prevalidates all resources, then undoes.

    Repeat invocation is safe after a *second* interruption. Unknown content,
    paths, symlinks, missing backups or mismatched hashes stop before any undo.
    """
    with exclusive(root) as safe:
        document, observed, original = _validate_locked(safe)
        resources = document["resources"]
        if crash_after_restored is not None and (
            type(crash_after_restored) is not int
            or not 0 <= crash_after_restored <= len(resources)
        ):
            raise RecoveryRefused("Invalid synthetic rollback fault position")
        if crash_after_restored == 0:
            raise SimulatedPowerLoss("Injected crash before recovery changes")
        restored = 0
        for row in reversed(resources):
            path = row["path"]
            if observed[path] == "applied":
                target = sandbox.check_path(safe, path)
                if row["operation"] == "create":
                    target.unlink()
                else:
                    sandbox.atomic_write(target, original)
                restored += 1
                if restored == crash_after_restored:
                    raise SimulatedPowerLoss("Injected crash while reversing files")
        # A full state re-evaluation before dropping the recovery record.
        _, states, _ = _validate_locked(safe)
        if any(s != "original" for s in states.values()):
            raise RecoveryRefused("Not all mock resources restored")
        (safe / JOURNAL).unlink()
        if document["role"] == "ir":
            (safe / ORIGINAL).unlink()
        return [
            "RECOVERED ONLY SYNTHETIC /tmp SANDBOX FILES",
            "Journal and verified backup were removed after restoration",
            "NO Docker/Smite/FRP/Xray/Nginx operations",
            "NOT AN INSTALLER; NOT APPROVED FOR LIVE IR/KH",
        ]
