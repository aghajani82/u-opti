#!/usr/bin/env python3
"""STRICTLY OFFLINE transaction/rollback simulator for Backhaul Sidecar.

The only writable tree is a specially marked, direct child of /tmp.
Never touches host /etc, starts containers, reloads Nginx or opens sockets.
This is NOT an installer and cannot be used on a production server.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile

MODULE = Path(__file__).resolve().with_name("smite-backhaul-sidecar-rollback.py")
spec = importlib.util.spec_from_file_location("sidecar_rollback_offline", MODULE)
rollback = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(rollback)

MARKER = ".UOPTI_SIDECAR_OFFLINE_SANDBOX_ONLY"
MAGIC = "OFFLINE MOCK ONLY: NOT A PRODUCTION HOST\n"
HOOK = "    # UOPTI_SIDECAR_TEST_HOOK"
INCLUDE = "    include /etc/nginx/u-opti-sidecar/*.inc;"
MANIFEST = ".sidecar-simulation-manifest.json"
BACKUP = ".sidecar-simulation-original-backend"
CANDIDATES = {
    "ir": {
        "/etc/u-opti/backhaul-sidecar/ir.toml": "ir.toml",
        "/etc/u-opti/backhaul-sidecar/compose-ir.yml": "compose.candidate.yaml",
        "/etc/nginx/u-opti-sidecar/ir-control.inc": "ir-control.inc",
        "/etc/nginx/u-opti-sidecar/ir-xhttp.inc": "ir-xhttp.inc",
    },
    "kh": {
        "/etc/u-opti/backhaul-sidecar/kh.toml": "kh.toml",
        "/etc/u-opti/backhaul-sidecar/compose-kh.yml": "compose.candidate.yaml",
        "/etc/nginx/conf.d/u-opti-backhaul-kh-bridge.conf": "kh-bridge.conf",
    },
}


class SandboxRefused(ValueError):
    pass


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def check_sandbox(root: Path) -> Path:
    root = Path(root).absolute()
    if root.parent != Path("/tmp") or not root.name.startswith("uopti-bh-sandbox-"):
        raise SandboxRefused("Only a direct /tmp/uopti-bh-sandbox-* directory is accepted")
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise SandboxRefused("Sandbox must be a private directory, not a symlink")
    marker = root / MARKER
    if not marker.is_file() or marker.is_symlink() or marker.read_text() != MAGIC:
        raise SandboxRefused("Missing explicit synthetic-only sandbox marker")
    return root


def check_path(root: Path, path: str, *, create_parents: bool = False) -> Path:
    if not path.startswith("/") or ".." in Path(path).parts:
        raise SandboxRefused("Unsafe resource path")
    target = root / path.lstrip("/")
    ancestor = root
    for component in Path(path.lstrip("/")).parts[:-1]:
        ancestor = ancestor / component
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            if create_parents:
                ancestor.mkdir(mode=0o700)
                info = ancestor.lstat()
            else:
                continue
        if not stat.S_ISDIR(info.st_mode):
            raise SandboxRefused("Non-directory or symlink ancestor")
    if target.exists() or target.is_symlink():
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise SandboxRefused("Resource must be regular file, not symlink")
    return target


def atomic_write(target: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".sidecar-mock-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def stage_payload(stage: Path, role: str) -> dict[str, bytes]:
    if role not in CANDIDATES:
        raise SandboxRefused("Unsupported role")
    stage = Path(stage)
    if not stage.is_dir() or stage.is_symlink():
        raise SandboxRefused("Candidate stage must be a real directory")
    result = {}
    for dest, source in CANDIDATES[role].items():
        original = stage / source
        if original.is_symlink() or not original.is_file():
            raise SandboxRefused("Missing or linked candidate")
        if stat.S_IMODE(original.stat().st_mode) & 0o077:
            raise SandboxRefused("Candidate must be private")
        result[dest] = original.read_bytes()
    return result


def bootstrap_mock(root: Path, role: str) -> None:
    """Create only a safe synthetic fixture under a fresh /tmp sandbox."""
    root = Path(root)
    if root.parent != Path("/tmp") or not root.name.startswith("uopti-bh-sandbox-"):
        raise SandboxRefused("Refusing non-sandbox root")
    root.mkdir(mode=0o700)
    if any(root.iterdir()):
        raise SandboxRefused("Sandbox fixture must start empty")
    atomic_write(root / MARKER, MAGIC.encode())
    if role == "ir":
        target = check_path(
            root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf",
            create_parents=True,
        )
        mock = (
            "server {\n"
            "    listen 127.0.0.1:8443 ssl;\n"
            "    server_name ir.kolbe1.ir;\n"
            f"{HOOK}\n"
            "    location / { proxy_pass http://127.0.0.1:8000; }\n"
            "}\n"
        ).encode()
        atomic_write(target, mock)


def _prepare(root: Path, role: str, files: dict[str, bytes]):
    targets = {}
    for path, expected in rollback.ALLOW[role].items():
        target = check_path(root, path)
        if expected == "create":
            if path not in files or target.exists():
                raise SandboxRefused("Unexpected existing or missing created file")
            payload = files[path]
            before = None
        else:
            if not target.is_file() or path in files:
                raise SandboxRefused("Synthetic backend required for edit")
            before = target.read_bytes()
            text = before.decode("utf-8")
            if text.count(HOOK) != 1 or INCLUDE in text:
                raise SandboxRefused("Exact mock insertion marker missing or already patched")
            payload = text.replace(HOOK, INCLUDE + "\n" + HOOK).encode()
        targets[path] = (target, expected, before, payload)
    if set(targets) != set(rollback.ALLOW[role]):
        raise SandboxRefused("Incomplete owned file set")
    return targets


def simulate_apply(root: Path, stage: Path, role: str, *, fail_after: int = 0) -> dict:
    """Atomic *file* writes in synthetic fixture; automatically undo failures."""
    root = check_sandbox(root)
    if role not in rollback.ALLOW:
        raise SandboxRefused("Unsupported role")
    if (root / MANIFEST).exists() or (root / BACKUP).exists():
        raise SandboxRefused("Transaction already exists")
    files = stage_payload(stage, role)
    targets = _prepare(root, role, files)
    completed: list[tuple[Path, bytes | None, bytes]] = []
    backup_file = root / BACKUP
    try:
        for path, (target, operation, before, payload) in targets.items():
            check_path(root, path, create_parents=True)
            if operation == "edit":
                atomic_write(backup_file, before)
            atomic_write(target, payload)
            completed.append((target, before, payload))
            if fail_after and len(completed) == fail_after:
                raise RuntimeError("Injected offline sandbox failure")
        rows = []
        for path, (_, operation, before, payload) in targets.items():
            rows.append({
                "path": path, "operation": operation,
                "before_sha256": digest(before) if before is not None else None,
                "backup_sha256": digest(before) if before is not None else None,
                "applied_sha256": digest(payload),
            })
        result = {
            "role": role, "container_name": rollback.CONTAINER[role],
            "resources": rows,
        }
        observed = {
            "container_name": rollback.CONTAINER[role],
            "resources": {p: digest(v[3]) for p, v in targets.items()},
        }
        rollback.plan_reversal(result, observed)
        atomic_write(root / MANIFEST, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception:
        # Undo only files created/changed by this invocation; never touch Smite
        # or FRP, and refuse to silently overwrite unexpected drift.
        for target, before, payload in reversed(completed):
            if not target.is_file() or digest(target.read_bytes()) != digest(payload):
                raise SandboxRefused("Failure injection found drift; manual sandbox review")
            if before is None:
                target.unlink()
            else:
                atomic_write(target, before)
        backup_file.unlink(missing_ok=True)
        raise


def simulate_rollback(root: Path) -> list[str]:
    """Fail-closed sandbox reversal with no Docker, Nginx or system effects."""
    root = check_sandbox(root)
    manifest_file = root / MANIFEST
    if manifest_file.is_symlink() or not manifest_file.is_file():
        raise SandboxRefused("No valid simulation manifest")
    manifest = json.loads(manifest_file.read_text())
    role = manifest.get("role")
    if role not in rollback.ALLOW:
        raise SandboxRefused("Invalid manifest role")
    observed = {"container_name": rollback.CONTAINER[role], "resources": {}}
    for path in rollback.ALLOW[role]:
        target = check_path(root, path)
        if not target.is_file():
            raise SandboxRefused("Missing or changed owned file")
        observed["resources"][path] = digest(target.read_bytes())
    plan = rollback.plan_reversal(manifest, observed)
    original = None
    if role == "ir":
        backup = root / BACKUP
        if backup.is_symlink() or not backup.is_file():
            raise SandboxRefused("Missing original backend backup")
        original = backup.read_bytes()
        edit_row = next(row for row in manifest["resources"] if row["operation"] == "edit")
        if digest(original) != edit_row["backup_sha256"]:
            raise SandboxRefused("Backup content no longer matches original")
    # Prevalidation is complete. Only owned synthetic files are touched.
    for row in reversed(manifest["resources"]):
        target = check_path(root, row["path"])
        if row["operation"] == "create":
            target.unlink()
        else:
            atomic_write(target, original)
    (root / BACKUP).unlink(missing_ok=True)
    manifest_file.unlink()
    return plan
