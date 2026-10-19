#!/usr/bin/env python3
"""Safe Backhaul-only lifecycle rehearsal with fail-closed compensation.

Only callable after the independent transaction's marked GitHub PR runner
admission. No shell/network/Docker commands here: a CI harness supplies
separate signed Node health callbacks. Even SUCCESS ALWAYS rolls back
the installation and proves the previous inventory again.

This is deliberately NOT a production server installer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable
import importlib.util

MODULES = Path(__file__).resolve().parent


def _read(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, MODULES / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing reviewed lifecycle dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ctl = _read("bh_lifecycle_control", "smite-managed-backhaul-control.py")
tx = ctl.transaction


class Hold(RuntimeError):
    """No operator-supplied details or credentials are included."""


def _saved_tunnel_digest(root: Path) -> str | None:
    candidate = root / "node-data" / "tunnels.json"
    if not candidate.exists() and not candidate.is_symlink():
        return None
    blob = tx.checked(candidate, max_size=256 * 1024)
    try:
        saved = json.loads(blob)
    except (ValueError, UnicodeError) as exc:
        raise Hold("CORRUPT_SAVED_TUNNEL_REGISTRY") from exc
    if not isinstance(saved, dict):
        raise Hold("UNKNOWN_SAVED_TUNNEL_REGISTRY")
    if saved:
        raise Hold("EXISTING_TUNNELS_DO_NOT_RECREATE")
    return hashlib.sha256(blob).hexdigest()


def _identity_digest(root: Path) -> str | None:
    path = root / "node" / "config" / "identity" / "node-identity.json"
    if not path.exists() and not path.is_symlink():
        return None
    return hashlib.sha256(tx.checked(path, max_size=8192)).hexdigest()


def _unchanged_protected_data(root: Path, tunnels: str | None,
                              identity: str | None) -> bool:
    return _saved_tunnel_digest(root) == tunnels and _identity_digest(root) == identity


def run_lab_rehearsal(root: Path, stage: Path, *,
                      check_ready: Callable[[Path], bool],
                      check_absent: Callable[[Path], bool],
                      inject: str | None = None) -> dict[str, str]:
    """Proof callback MUST verify signed inventory and restart, not a status string.

    Callback truth is checked, but the caller's signed-API harness owns
    HMAC. A failing callback never authorizes a host mutation or Commit.
    """
    # Admission and lock predate ALL file mutations, including identity reads.
    tx.admission(root)
    with ctl._lab_lock(root):
        node = root / "node"
        binary = root / "installed" / "backhaul"
        compose, manifest, _, _ = tx.admission(root)
        if (root / "recovery-journal").exists() or (root / "recovery-journal").is_symlink():
            raise Hold("UNFINISHED_TRANSACTION_MUST_RECOVER_FIRST")
        if ctl.inspect(node, lab_binary=binary)["state"] != "NOT_INSTALLED":
            raise Hold("ENGINE_MUST_START_ABSENT")
        ctl.verified_candidate(stage)
        tx.candidate(root, stage)  # Double-check exact Compose+manifest binding.
        tunnels_before = _saved_tunnel_digest(root)
        identity_before = _identity_digest(root)
        compose_before = tx.checked(compose, max_size=131072)
        manifest_before = (tx.checked(manifest, max_size=8192)
                           if manifest.exists() or manifest.is_symlink() else None)
        ready_ok = False
        rollback_ok = False
        previous_runtime_ok = False
        failure = None
        try:
            tx.activate(root, stage, inject=inject or "")
            if ctl.inspect(node, lab_binary=binary)["state"] != "ENROLLED_UNVERIFIED":
                raise Hold("INSTALLED_BYTES_NOT_VERIFIED")
            if not _unchanged_protected_data(root, tunnels_before, identity_before):
                raise Hold("PROTECTED_NODE_DATA_CHANGED")
            if check_ready(root) is not True:
                raise Hold("SIGNED_READY_AND_RESTART_PROOF_FAILED")
            ready_ok = True
        except Exception:
            # The exact error is intentionally not reflected to operator logs.
            failure = "ACTIVATION_OR_SIGNED_HEALTH_FAILED"

        # Even on success: ALWAYS undo this rehearsal; no live engine is left.
        journal = root / "recovery-journal"
        try:
            if journal.exists() or journal.is_symlink():
                tx.rollback(root)
            else:
                if tx.checked(compose, max_size=131072) != compose_before:
                    raise Hold("COMPOSE_CHANGED_WITHOUT_JOURNAL")
            rollback_ok = (
                tx.checked(compose, max_size=131072) == compose_before
                and (tx.checked(manifest, max_size=8192)
                     if manifest.exists() or manifest.is_symlink() else None) == manifest_before
                and ctl.inspect(node, lab_binary=binary)["state"] == "NOT_INSTALLED"
                and _unchanged_protected_data(root, tunnels_before, identity_before)
            )
        except Exception:
            raise Hold("ROLLBACK_FAILED_MANUAL_REVIEW_REQUIRED") from None
        if not rollback_ok:
            raise Hold("ROLLBACK_BYTES_OR_PROTECTED_STATE_MISMATCH")

        # The previous runtime is probed even after failed installation.
        try:
            previous_runtime_ok = (check_absent(root) is True)
        except Exception:
            previous_runtime_ok = False
        if not previous_runtime_ok:
            raise Hold("PREVIOUS_SIGNED_NODE_RUNTIME_NOT_RESTORED")
        if failure is not None or not ready_ok:
            raise Hold("ACTIVATION_FAILED_EXACT_ROLLBACK_PROVED")
        return {
            "TRIAL_INSTALL": "SIGNED_READY_AFTER_RESTART_VERIFIED",
            "TRIAL_ROLLBACK": "BYTES_AND_MODES_RESTORED",
            "TRIAL_PREVIOUS_RUNTIME": "SIGNED_ABSENT_AFTER_RESTART_VERIFIED",
            "LIVE_HOST_INSTALL": "NEVER_ATTEMPTED",
            "PRODUCTION_ACTIVATION": "HOLD",
        }
