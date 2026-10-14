#!/usr/bin/env python3
"""Real Nginx apply/rollback controller, LOCKED to disposable GitHub Docker labs.

This is NOT a VPS installer. It refuses to operate outside a GitHub-hosted
pull-request runner and a marker-protected private direct-child /tmp workspace.
It only controls a labeled, running Nginx container on an internal Docker
network with no published ports and an exact workspace bind mount. No Docker
run/rm/stop, host Nginx, host networking, or production paths are supported.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
MARKER = "UOPTI_BACKHAUL_DOCKER_LAB_V1\n"
JOURNAL = ".uopti-lab-transaction.json"
BACKUP = ".uopti-lab-original.conf"
LOCK = ".uopti-lab-lock"
BASE = "baseline.conf"
ACTIVE = "active.conf"
CURRENT = "nginx.conf"


class LabRefused(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_environment() -> tuple[str, str]:
    required = {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": "aghajani82/u-opti",
    }
    if any(os.environ.get(key) != expected for key, expected in required.items()):
        raise LabRefused("Only an ephemeral GitHub-hosted PR runner is allowed")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not re.fullmatch(r"[0-9]{1,18}", run_id) or not re.fullmatch(r"[0-9]{1,4}", attempt):
        raise LabRefused("Missing GitHub-run identity")
    return run_id, attempt


def _lstat_regular(path: Path, *, max_bytes: int = 64_000) -> os.stat_result:
    try:
        st = path.lstat()
    except OSError as exc:
        raise LabRefused("Required private fixture or backup missing") from exc
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) != 0o600
            or not 0 < st.st_size <= max_bytes):
        raise LabRefused("Unsafe fixture/journal file")
    return st


def workspace(path: Path) -> Path:
    # Root must have exactly one /tmp component (no relative paths, dotdot).
    if (not path.is_absolute() or path.parent != Path("/tmp")
            or not path.name.startswith("uopti-bh-executor-")
            or not re.fullmatch(r"uopti-bh-executor-[A-Za-z0-9_-]{6,50}", path.name)):
        raise LabRefused("Not a disposable lab workspace")
    st = path.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) != 0o700):
        raise LabRefused("Unsafe lab workspace permissions")
    mark = path / ".uopti-lab-marker"
    _lstat_regular(mark)
    if mark.read_text() != MARKER:
        raise LabRefused("Marker mismatch")
    for filename in (BASE, ACTIVE, CURRENT):
        _lstat_regular(path / filename)
    return path


def command(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=12, check=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        # Never leak Docker config/mount details or the Nginx config content.
        raise LabRefused("Isolated Docker check or Nginx command failed") from exc


def validate_container(name: str, root: Path, run_id: str, attempt: str) -> str:
    allowed = f"uopti-ng-executor-{run_id}-{attempt}"
    network = f"uopti-net-executor-{run_id}-{attempt}"
    if name != allowed:
        raise LabRefused("Container is not the current lab's exact Nginx")
    try:
        obj = json.loads(command(["docker", "inspect", name]))
        if not isinstance(obj, list) or len(obj) != 1:
            raise LabRefused("Invalid container inspection response")
        x = obj[0]
        if (x["Name"] != "/" + allowed
                or x["State"]["Running"] is not True
                or x["Config"]["Labels"].get("uopti.lab") != "backhaul-executor-v1"
                or x["HostConfig"]["NetworkMode"] != network
                or x["HostConfig"]["PortBindings"] not in (None, {})
                or x["HostConfig"]["Privileged"] is not False
                or x["HostConfig"].get("PidMode") == "host"
                or len(x["Mounts"]) != 1):
            raise LabRefused("Container ownership/isolation verification failed")
        mount = x["Mounts"][0]
        if (mount["Type"] != "bind"
                or mount["Source"] != str(root)
                or mount["Destination"] != "/run/uopti-lab"
                or mount.get("RW") is not True):
            raise LabRefused("Container workspace mount not isolated")
        net = json.loads(command(["docker", "network", "inspect", network]))
        if (not isinstance(net, list) or len(net) != 1
                or net[0]["Name"] != network
                or net[0]["Internal"] is not True):
            raise LabRefused("Docker network is not private/internal")
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise LabRefused("Cannot verify lab isolation") from exc
    return allowed


def atomic_bytes(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".uopti-lab-stage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        dirfd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_journal(root: Path) -> dict | None:
    path = root / JOURNAL
    if not path.exists() and not path.is_symlink():
        return None
    _lstat_regular(path, max_bytes=4096)
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError) as exc:
        raise LabRefused("Invalid recovery journal") from exc
    if (not isinstance(value, dict) or set(value) != {
        "version", "container", "original_sha", "active_sha"
    } or value["version"] != 1 or
            any(not isinstance(value[k], str) or not re.fullmatch(r"[a-f0-9]{64}", value[k])
                for k in ("original_sha", "active_sha"))):
        raise LabRefused("Unrecognized recovery journal")
    return value


def nginx(name: str, action: str) -> None:
    if action not in ("-t", "-s"):
        raise LabRefused("Unknown Nginx operation")
    args = ["docker", "exec", name, "nginx"]
    if action == "-t":
        args += ["-t", "-c", "/run/uopti-lab/nginx.conf"]
    else:
        args += ["-s", "reload", "-c", "/run/uopti-lab/nginx.conf"]
    command(args)


def rollback(root: Path, container: str, *, require_journal: bool = True) -> str:
    info = read_journal(root)
    if info is None:
        if require_journal:
            raise LabRefused("No transaction journal")
        return "NOTHING_TO_RESTORE"
    if info["container"] != container:
        raise LabRefused("Journal belongs to another container")
    baseline = (root / BASE).read_bytes()
    current = (root / CURRENT).read_bytes()
    if digest(baseline) != info["original_sha"]:
        raise LabRefused("Baseline changed; manual review required")
    if digest(current) not in (info["active_sha"], info["original_sha"]):
        raise LabRefused("Third-party config drift: NO automatic overwrite")
    backup = root / BACKUP
    _lstat_regular(backup)
    if digest(backup.read_bytes()) != info["original_sha"]:
        raise LabRefused("Original backup mismatch")
    if digest(current) != info["original_sha"]:
        atomic_bytes(root / CURRENT, backup.read_bytes())
    # A syntax failure keeps journal+backup; operator can inspect/retry.
    nginx(container, "-t")
    nginx(container, "-s")
    if digest((root / CURRENT).read_bytes()) != info["original_sha"]:
        raise LabRefused("Rollback could not verify original configuration")
    backup.unlink()
    (root / JOURNAL).unlink()  # Last: interrupted rollback remains resumable.
    return "ROLLED_BACK_TO_EXACT_BASELINE"


def apply(root: Path, container: str, *, simulate_crash: bool = False) -> str:
    if read_journal(root) is not None or (root / BACKUP).exists() or (root / BACKUP).is_symlink():
        raise LabRefused("Existing or incomplete transaction must be recovered first")
    original = (root / BASE).read_bytes()
    desired = (root / ACTIVE).read_bytes()
    current = (root / CURRENT).read_bytes()
    if current != original or desired == original:
        raise LabRefused("Missing exact baseline or invalid desired configuration")
    nginx(container, "-t")  # Existing config must pass BEFORE any writes.
    journal = {
        "version": 1, "container": container,
        "original_sha": digest(original), "active_sha": digest(desired),
    }
    atomic_bytes(root / JOURNAL, json.dumps(journal, sort_keys=True).encode())
    try:
        atomic_bytes(root / BACKUP, original)
        atomic_bytes(root / CURRENT, desired)
        if simulate_crash:
            # A hard process exit, deliberately leaving the durable journal.
            os._exit(88)
        nginx(container, "-t")
        nginx(container, "-s")
        if digest((root / CURRENT).read_bytes()) != journal["active_sha"]:
            raise LabRefused("Applied config changed during reload")
        return "APPLIED_WITH_RECOVERY_JOURNAL"
    except Exception:
        # If this fails, the journal remains; no invented rollback success.
        rollback(root, container)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--container", required=True)
    ap.add_argument("--action", choices=("apply", "rollback", "status"), required=True)
    ap.add_argument("--simulate-crash-after-write", action="store_true")
    args = ap.parse_args()
    try:
        run_id, attempt = safe_environment()
        root = workspace(args.workspace)
        if args.simulate_crash_after_write and args.action != "apply":
            raise LabRefused("Fault injection is only supported during lab apply")
        container = validate_container(args.container, root, run_id, attempt)
        lockpath = root / LOCK
        fd = os.open(lockpath, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with os.fdopen(fd, "r+", closefd=True):
                if args.action == "apply":
                    report = apply(root, container,
                                   simulate_crash=args.simulate_crash_after_write)
                elif args.action == "rollback":
                    report = rollback(root, container)
                else:
                    info = read_journal(root)
                    report = "RECOVERY_JOURNAL_PRESENT" if info else "NO_PENDING_LAB_TRANSACTION"
        finally:
            # fdopen context closes fd; if exception before fdopen, clean up.
            try:
                os.close(fd)
            except OSError:
                pass
        print(report)
        return 0
    except (LabRefused, OSError, BlockingIOError):
        print("REFUSED: isolated Docker lab safety or transaction verification failed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
