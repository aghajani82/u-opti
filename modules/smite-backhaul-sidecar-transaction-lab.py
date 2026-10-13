#!/usr/bin/env python3
"""Synthetic file+service transaction coordinator for Backhaul Sidecar.

EXCLUSIVELY a laboratory. Only direct /tmp/uopti-bh-sandbox-* trees bearing
the pre-existing fixture marker are writable. Docker, Nginx, networking,
systemd, /etc, SSH and real containers are NEVER accessed by this module.

A durable coordinator intent precedes the existing write-ahead FILE journal.
The service adapter is JSON-only and intentionally cannot execute commands.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

sys.dont_write_bytecode = True
DIR = Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, DIR / filename)
    obj = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(obj)
    return obj


lab = load("bh_coordinator_files", "smite-backhaul-sidecar-recovery-lab.py")
sb = lab.sandbox
INTENT = ".uopti-bh-coordinator-intent.json"
RUNTIME = ".uopti-bh-mock-runtime.json"
MUTEX = ".uopti-bh-coordinator-mutex"
VERSION = 1
ROLES = frozenset(("ir", "kh"))


class TransactionRefused(ValueError):
    pass


class SimulatedPowerFailure(BaseException):
    """Not a normal exception: emulate loss of process before recovery."""


def baseline(role: str) -> dict:
    if role not in ROLES:
        raise TransactionRefused("Unknown role")
    return {
        "role": role, "nginx_generation": 0, "sidecar": "absent",
        "smite": "unchanged", "frp": "unchanged", "xray": "unchanged",
    }


def service_state(role: str, sidecar: str, nginx_generation: int) -> dict:
    state = baseline(role)
    state.update(sidecar=sidecar, nginx_generation=nginx_generation)
    return state


def valid_service_states(role: str) -> tuple[dict, dict, dict]:
    return (
        baseline(role),
        service_state(role, "running", 0),
        service_state(role, "running", 1),
    )


def _private_json(path: Path, *, required: bool = True) -> dict | None:
    try:
        st = path.lstat()
    except FileNotFoundError:
        if not required:
            return None
        raise TransactionRefused("Missing private coordinator state")
    if (not stat.S_ISREG(st.st_mode) or st.st_size > 8192
            or stat.S_IMODE(st.st_mode) & 0o077):
        raise TransactionRefused("Unsafe coordinator state file")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise TransactionRefused("Unparseable coordinator state") from exc
    if not isinstance(parsed, dict):
        raise TransactionRefused("Invalid coordinator state")
    return parsed


def _save(root: Path, name: str, data: dict) -> None:
    # The recovery lab persists atomically and fsyncs the parent directory.
    if name not in (RUNTIME, INTENT):
        raise TransactionRefused("Unexpected simulation artifact")
    lab._persist(root / name, json.dumps(data, sort_keys=True).encode())


def _remove(root: Path, name: str) -> None:
    if name not in (RUNTIME, INTENT):
        raise TransactionRefused("Unexpected simulation artifact")
    lab._remove(root / name)


@contextmanager
def coordinator_lock(root: Path):
    root = sb.check_sandbox(root)
    fd = os.open(root / MUTEX, os.O_RDWR | os.O_CREAT |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
            raise TransactionRefused("Unsafe coordinator lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TransactionRefused("Concurrent simulation transaction") from exc
        yield root
    finally:
        os.close(fd)


def bootstrap(root: Path, role: str) -> None:
    """Create the fake service snapshot, only after sandbox.bootstrap_mock()."""
    with coordinator_lock(root) as safe:
        if role not in ROLES or any(
            (safe / name).exists() or (safe / name).is_symlink()
            for name in (INTENT, RUNTIME, lab.JOURNAL, lab.ORIGINAL,
                         sb.MANIFEST, sb.BACKUP)
        ):
            raise TransactionRefused("Non-empty or already installed simulation")
        _save(safe, RUNTIME, baseline(role))


def _read_runtime(root: Path, role: str) -> dict:
    state = _private_json(root / RUNTIME)
    if state not in valid_service_states(role):
        raise TransactionRefused("Unknown service state or foreign resource drift")
    return state


def _read_intent(root: Path) -> dict:
    intent = _private_json(root / INTENT)
    if (set(intent) != {"version", "role", "kind", "sidecar"}
            or intent["version"] != VERSION
            or intent["role"] not in ROLES
            or intent["kind"] != "SYNTHETIC_SIDE_CAR_ONLY"
            or intent["sidecar"] != sb.rollback.CONTAINER[intent["role"]]):
        raise TransactionRefused("Unknown transaction identity")
    return intent


def _revert_locked(root: Path, *, interrupt_after_service: bool = False,
                   interrupt_after_files: bool = False) -> list[str]:
    intent = _read_intent(root)
    role = intent["role"]
    state = _read_runtime(root, role)
    has_file_journal = (root / lab.JOURNAL).exists() or (
        root / lab.JOURNAL).is_symlink()
    if has_file_journal:
        # Preflight file recovery IN FULL before modifying any service state.
        try:
            lab.inspect_synthetic_recovery(root)
        except Exception as exc:
            raise TransactionRefused("Unverifiable file journal; manual review") from exc
    elif state != baseline(role):
        raise TransactionRefused("Sidecar service changed but file journal missing")

    if state != baseline(role):
        _save(root, RUNTIME, baseline(role))
    if interrupt_after_service:
        raise SimulatedPowerFailure("Synthetic crash after restoring mock services")
    if has_file_journal:
        lab.recover_synthetic_transaction(root)
    if interrupt_after_files:
        raise SimulatedPowerFailure("Synthetic crash after mock file recovery")
    if _read_runtime(root, role) != baseline(role) or (root / lab.JOURNAL).exists():
        raise TransactionRefused("Synthetic recovery incomplete; retain intent")
    _remove(root, INTENT)  # Journal LAST, allowing retry after an interruption.
    return [
        "SYNTHETIC_ROLLBACK_OK",
        "Mock Sidecar removed; fake Nginx generation restored",
        "Owned mock files restored via existing crash-safe file journal",
        "Smite/FRP/Xray left unchanged in the synthetic state",
        "ZERO live host service or Nginx operations",
    ]


def rollback(root: Path, *, interrupt_after_service: bool = False,
             interrupt_after_files: bool = False) -> list[str]:
    with coordinator_lock(root) as safe:
        return _revert_locked(
            safe, interrupt_after_service=interrupt_after_service,
            interrupt_after_files=interrupt_after_files,
        )


def deploy(root: Path, candidate: Path, role: str, *,
           fail_at: str | None = None, interrupt_at: str | None = None) -> dict:
    """Simulate prepare > file install > validation > sidecar > reload > verify.

    Normal injected failure auto-rolls back; BaseException power loss retains
    durable intent for a fresh independent rollback call. No services run.
    """
    allowed = {"after-intent", "after-files", "validation", "after-sidecar",
               "after-reload", "health"}
    if fail_at not in allowed | {None} or interrupt_at not in allowed | {None}:
        raise TransactionRefused("Unknown fault injection point")
    with coordinator_lock(root) as safe:
        if role not in ROLES or (safe / INTENT).exists() or (safe / INTENT).is_symlink():
            raise TransactionRefused("Another transaction exists or role invalid")
        state = _read_runtime(safe, role)
        if state != baseline(role) or any(
            (safe / x).exists() or (safe / x).is_symlink()
            for x in (lab.JOURNAL, lab.ORIGINAL, sb.MANIFEST, sb.BACKUP)
        ):
            raise TransactionRefused("Existing/partial installation: refuse overwrite")
        # All payload files and ownership checked BEFORE durable intent.
        sb.stage_payload(candidate, role)
        _save(safe, INTENT, {
            "version": VERSION, "role": role,
            "kind": "SYNTHETIC_SIDE_CAR_ONLY",
            "sidecar": sb.rollback.CONTAINER[role],
        })

        def checkpoint(point: str) -> None:
            if interrupt_at == point:
                raise SimulatedPowerFailure("Mock power loss: " + point)
            if fail_at == point:
                raise TransactionRefused("Injected service failure: " + point)

        try:
            checkpoint("after-intent")
            lab.begin_synthetic_transaction(safe, candidate, role)
            checkpoint("after-files")
            # Only mock validation, not a real Nginx syntax test. CI has a
            # separate isolated Nginx job checking the actual templates.
            checkpoint("validation")
            _save(safe, RUNTIME, service_state(role, "running", 0))
            checkpoint("after-sidecar")
            _save(safe, RUNTIME, service_state(role, "running", 1))
            checkpoint("after-reload")
            checkpoint("health")
            return {
                "phase": "SYNTHETIC_ACTIVE", "role": role,
                "file_count": len(sb.rollback.ALLOW[role]),
                "sidecar": sb.rollback.CONTAINER[role],
                "end_to_end_vless_verified": False,
                "note": "Offline mock only; durable intent retained for rollback",
            }
        except Exception:
            # A known failure is reversible only while ALL resources match
            # the expected simulated states. Drift raises and leaves intent.
            _revert_locked(safe)
            raise


def inspect(root: Path) -> dict:
    with coordinator_lock(root) as safe:
        intent = _read_intent(safe)
        role = intent["role"]
        service = _read_runtime(safe, role)
        if (safe / lab.JOURNAL).exists():
            evidence = lab.inspect_synthetic_recovery(safe)
            files = {"applied": evidence["applied"],
                     "original": evidence["original"]}
        else:
            files = {"applied": 0, "original": 0}
        return {
            "role": role, "service_phase": (
                "baseline" if service == baseline(role)
                else "mock-started" if service["nginx_generation"] == 0
                else "mock-reloaded"),
            "file_evidence": files,
            "mode": "OFFLINE_SYNTHETIC_ONLY",
        }
