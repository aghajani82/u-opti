#!/usr/bin/env python3
"""Backhaul-only, crash-recoverable filesystem transaction — disposable CI lab.

This intentionally has NO production activation path. It can update only a
marked temporary sandbox under GitHub pull-request CI; it NEVER invokes Docker,
Nginx, SSH, systemctl, the Panel API, or touches real IR/KH installations.
After a passing transaction rehearsal, a separately reviewed host executor,
signed health preflight and operator confirmation will still be necessary.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("managed_backhaul_package", HERE / "smite-managed-backhaul.py")
assert _spec and _spec.loader
pkg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pkg)

MARKER = "U-OPTI-BACKHAUL-ISOLATED-LAB-V1\n"
SHA = re.compile(r"^[0-9a-f]{64}$")
MOUNT = "      - {binary}:/usr/local/bin/backhaul:ro\n"


class Hold(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked(path: Path, max_size: int = 50_000_000) -> bytes:
    try:
        if path.is_symlink():
            raise Hold("Symlink refused")
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > max_size:
            raise Hold("Unsafe file")
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise Hold("Missing required file") from exc


def private_dir(p: Path) -> None:
    if p.is_symlink() or not p.is_dir():
        raise Hold("Unexpected or symlinked directory")
    st = p.lstat()
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise Hold("Private directory must be caller-owned and mode 0700")


def ensure_in_lab(root: Path, path: Path) -> None:
    if not path.is_absolute() or path == root or root not in path.parents:
        raise Hold("Only paths inside disposable lab permitted")
    current = path
    while current != root:
        if current.is_symlink():
            raise Hold("Symlink inside lab refused")
        current = current.parent


def admission(root: Path) -> tuple[Path, Path, Path, Path]:
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_EVENT_NAME") != "pull_request"):
        raise Hold("DISPOSABLE GITHUB PR CI ONLY: live activation disabled")
    if not root.is_absolute() or root == Path("/") or root.is_symlink():
        raise Hold("Invalid isolated lab root")
    private_dir(root)
    if checked(root / "EXPERIMENTAL-LAB", 256).decode() != MARKER:
        raise Hold("Missing explicit lab-only marker")
    node = root / "node"
    config = node / "config"
    stages = root / "stages"
    for path in (node, config, stages):
        ensure_in_lab(root, path)
        private_dir(path)
    compose = node / "docker-compose.yml"
    manifest = config / "engine-state" / "engines.json"
    binary = root / "installed" / "backhaul"
    return compose, manifest, binary, stages


def parse_summary(stage: Path) -> dict[str, str]:
    try:
        entries = [line.split("=", 1) for line in checked(stage / "summary.txt", 4096).decode().splitlines()]
        if any(len(x) != 2 for x in entries):
            raise Hold("Invalid staged summary")
        found = dict(entries)
        if len(found) != len(entries):
            raise Hold("Duplicate summary keys")
        return found
    except UnicodeError as exc:
        raise Hold("Invalid staged summary") from exc


def candidate(root: Path, stage: Path, *, fixture: bool = False) -> tuple[bytes, bytes, bytes, bytes]:
    compose, manifest, binary, stages = admission(root)
    ensure_in_lab(root, stage)
    if stage.parent != stages:
        raise Hold("Candidate must be directly under the private stages directory")
    private_dir(stage)
    if not pkg.verify(stage):
        raise Hold("Candidate SHA256 verification failed")
    summary = parse_summary(stage)
    archive = summary.get("ARCHIVE_SHA256")
    architecture = summary.get("BACKHAUL_ARCH")
    if not fixture and (architecture not in pkg.OFFICIAL_TAR_SHA256
                        or archive != pkg.OFFICIAL_TAR_SHA256[architecture]):
        raise Hold("Candidate is not pinned to the approved official release")
    if summary.get("BACKHAUL_VERSION") != pkg.VERSION:
        raise Hold("Unexpected engine version")
    if summary.get("CANDIDATE_ONLY") != "YES":
        raise Hold("Not an inert package candidate")
    raw_bin = checked(stage / "backhaul.bin")
    raw_manifest = checked(stage / "engines.candidate.json", 8192)
    raw_compose = checked(compose, 131072)
    if summary.get("BACKHAUL_BINARY_SHA256") != digest(raw_bin):
        raise Hold("Staged binary SHA mismatch")
    if summary.get("ORIGINAL_COMPOSE_SHA256") != digest(raw_compose):
        raise Hold("Compose changed since preparation")
    try:
        new_manifest = json.loads(raw_manifest)
        existing = pkg._existing_manifest(root / "node" / "config")
    except (ValueError, UnicodeError, OSError) as exc:
        raise Hold("Untrusted manifest") from exc
    if (not isinstance(new_manifest, dict) or set(new_manifest) != {"schema", "engines"}
            or new_manifest["schema"] != 1
            or not isinstance(new_manifest["engines"], dict)
            or new_manifest["engines"].get("backhaul") != {"sha256": digest(raw_bin)}
            or {k: v for k, v in new_manifest["engines"].items() if k != "backhaul"} != existing
            or "backhaul" in existing):
        raise Hold("Candidate alters another engine or declares an unexpected digest")
    if not raw_bin.startswith(b"\x7fELF"):
        raise Hold("Non-Linux binary")
    try:
        baseline, others = pkg._core_preflight(root / "node")
    except (pkg.Hold, UnicodeError) as exc:
        raise Hold("Node not a strict clean-RC managed Core") from exc
    if baseline != raw_compose or others != existing:
        raise Hold("Node preflight drift")
    if "      - ./config:/etc/smite-node\n" not in raw_compose.decode():
        raise Hold("Unknown Compose bind target")
    mount_line = MOUNT.format(binary=binary)
    proposed = raw_compose.replace(
        b"      - ./config:/etc/smite-node\n",
        ("      - ./config:/etc/smite-node\n" + mount_line).encode(), 1,
    )
    if proposed.count(mount_line.encode()) != 1:
        raise Hold("Ambiguous Backhaul mount")
    if checked(stage / "compose.override.candidate.yml", 8192).count(b"/usr/local/bin/backhaul") != 1:
        raise Hold("Unknown staged mount proposal")
    return raw_compose, proposed, raw_manifest, raw_bin


def atomic(path: Path, data: bytes, mode: int) -> None:
    if path.is_symlink():
        raise Hold("Target symlinked")
    fd, tmp = tempfile.mkstemp(prefix=".uopti-new-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            os.fchmod(file.fileno(), mode)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def new_file(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as file:
        os.fchmod(file.fileno(), mode)
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def activate(root: Path, stage: Path, *, fixture: bool = False, inject: str = "") -> str:
    compose, manifest, binary, _ = admission(root)
    raw_compose, new_compose, new_manifest, new_bin = candidate(root, stage, fixture=fixture)
    journal = root / "recovery-journal"
    if journal.exists() or journal.is_symlink():
        raise Hold("Existing recovery journal: rollback/review before proceeding")
    if binary.exists() or binary.is_symlink():
        raise Hold("Backhaul binary already exists; refusing overwrite")
    state = manifest.parent
    if state.exists() or state.is_symlink():
        private_dir(state)
    prior_manifest = checked(manifest, 8192) if manifest.exists() or manifest.is_symlink() else None
    # State is documented before the first file mutation. Preserve exact bytes.
    journal.mkdir(mode=0o700)
    new_file(journal / "compose.before", raw_compose, 0o600)
    if prior_manifest is not None:
        new_file(journal / "manifest.before", prior_manifest, 0o600)
    record = {
        "schema": 1, "compose_old": digest(raw_compose), "compose_new": digest(new_compose),
        "manifest_old": digest(prior_manifest) if prior_manifest is not None else None,
        "manifest_new": digest(new_manifest), "binary_new": digest(new_bin),
        "binary_path": str(binary),
    }
    new_file(journal / "record.json", (json.dumps(record, sort_keys=True) + "\n").encode(), 0o600)
    # NO service restart and NO engine Apply, even when this rehearsal passes.
    binary.parent.mkdir(parents=True, mode=0o700, exist_ok=False)
    new_file(binary, new_bin, 0o755)
    if inject == "after-binary":
        raise Hold("Injected crash after binary; recovery required")
    atomic(compose, new_compose, 0o600)
    if inject == "after-compose":
        raise Hold("Injected crash after Compose; recovery required")
    if not state.exists():
        state.mkdir(mode=0o700)
    # Enroll last to ensure a Node is never declared ready before its
    # executable and Compose mount exist. This is a filesystem rehearsal.
    if prior_manifest is None:
        new_file(manifest, new_manifest, 0o600)
    else:
        atomic(manifest, new_manifest, 0o600)
    if inject == "after-manifest":
        raise Hold("Injected crash after manifest; recovery required")
    return "LAB_FILES_APPLIED_NO_DOCKER_NO_LIVE_ENGINE"


def rollback(root: Path) -> str:
    compose, manifest, binary, _ = admission(root)
    journal = root / "recovery-journal"
    private_dir(journal)
    record = json.loads(checked(journal / "record.json", 4096))
    if not isinstance(record, dict) or record.get("schema") != 1 or record.get("binary_path") != str(binary):
        raise Hold("Unrecognized transaction journal")
    for k in ("compose_old", "compose_new", "manifest_new", "binary_new"):
        if not isinstance(record.get(k), str) or SHA.fullmatch(record[k]) is None:
            raise Hold("Corrupt transaction journal")
    previous = checked(journal / "compose.before")
    prior_manifest = checked(journal / "manifest.before", 8192) if record["manifest_old"] else None
    if digest(previous) != record["compose_old"]:
        raise Hold("Backup Compose tampered")
    if prior_manifest is not None and digest(prior_manifest) != record["manifest_old"]:
        raise Hold("Backup manifest tampered")
    # Validate ALL existing files and ownership before any restoration.
    compose_bytes = checked(compose)
    if digest(compose_bytes) not in {record["compose_old"], record["compose_new"]}:
        raise Hold("Compose modified by another operator; do not overwrite")
    if binary.exists() or binary.is_symlink():
        if digest(checked(binary)) != record["binary_new"]:
            raise Hold("Engine binary modified by another operator")
    if manifest.exists() or manifest.is_symlink():
        current = digest(checked(manifest, 8192))
        acceptable = {record["manifest_new"]}
        if record["manifest_old"] is not None:
            acceptable.add(record["manifest_old"])
        if current not in acceptable:
            raise Hold("Registry modified by another operator")
    if digest(compose_bytes) != record["compose_old"]:
        atomic(compose, previous, 0o600)
    if prior_manifest is None:
        if manifest.exists():
            manifest.unlink()
    elif not manifest.exists() or checked(manifest, 8192) != prior_manifest:
        atomic(manifest, prior_manifest, 0o600)
    if binary.exists():
        binary.unlink()
    # Lab-only directories. Keep shared registry and other engines untouched.
    if binary.parent.exists() and not any(binary.parent.iterdir()):
        binary.parent.rmdir()
        if not any(binary.parent.parent.iterdir()):
            binary.parent.parent.rmdir()
    if manifest.parent.exists() and not any(manifest.parent.iterdir()):
        manifest.parent.rmdir()
    for p in journal.iterdir():
        p.unlink()
    journal.rmdir()
    return "LAB_EXACT_ROLLBACK_CONFIRMED"


def main() -> int:
    p = argparse.ArgumentParser(description="CI-only Backhaul installation + rollback rehearsal")
    p.add_argument("action", choices=["activate", "rollback"])
    p.add_argument("--lab-root", required=True, type=Path)
    p.add_argument("--stage", type=Path)
    args = p.parse_args()
    try:
        if args.action == "activate":
            if not args.stage:
                raise Hold("Missing stage")
            print(activate(args.lab_root, args.stage))
        else:
            print(rollback(args.lab_root))
        return 0
    except (Hold, pkg.Hold, OSError, ValueError, UnicodeError) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
