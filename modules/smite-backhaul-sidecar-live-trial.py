#!/usr/bin/env python3
"""EXPERIMENTAL opt-in Backhaul Sidecar install/rollback for fresh TEST hosts.

Never use on existing Sidecar hosts. Only the fixed, reconciled IR/KH
resource set is allowed. An explicit operator gate is required to activate.
The transaction journal and original Nginx vhost backup survive successful
installation and are reused for a separately approved rollback.

NOT a general installer. A GitHub CI mock cannot certify the running VPS,
its external DNS/certificates or the full VLESS/XHTTP tunnel.
"""
from __future__ import annotations

from contextlib import contextmanager
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
MODULE = Path(__file__).resolve().parent
STATE_ROOT = Path("/var/lib/u-opti/backhaul-trial")
LOCK = Path("/run/lock/u-opti-backhaul-trial.lock")
BACKUP = "original-nginx.conf"
JOURNAL = "journal.json"
IMAGE = ("ghcr.io/zzedix/smite-node@sha256:"
         "967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e")
ROLES = {"ir", "kh"}


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, MODULE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


paired = load("trial_pair", "smite-backhaul-sidecar-reconcile.py")
admission = load("trial_admission", "smite-backhaul-sidecar-admission.py")


class TrialRefused(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(argv: list[str], *, capture: bool = False) -> str:
    """Exactly enumerated external operations, no shell or inherited secrets."""
    allowed = (
        argv[:2] == ["nginx", "-t"],
        argv[:3] == ["systemctl", "is-active", "nginx"],
        argv[:3] == ["systemctl", "reload", "nginx"],
        argv[:2] == ["docker", "pull"] and len(argv) == 3 and argv[2] == IMAGE,
        argv[:2] == ["docker", "ps"] and len(argv) == 7,
        argv[:2] == ["docker", "inspect"] and len(argv) >= 4,
        argv[:2] == ["docker", "run"] and len(argv) >= 4,
        argv[:3] == ["docker", "rm", "-f"] and len(argv) == 4,
    )
    if not any(allowed):
        raise TrialRefused("Command not permitted in experimental trial")
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=45, check=True)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise TrialRefused("Command failed or timed out: " + argv[0]) from exc
    return result.stdout.strip() if capture else ""


def _read_docker(name: str) -> tuple[str, str, str] | None:
    # A failed docker inspect MUST NOT be interpreted as a missing container:
    # Docker daemon downtime during rollback could otherwise bypass ownership.
    listed = run(["docker", "ps", "-a", "--filter",
                  "name=^/" + name + "$", "--format", "{{.Names}}"],
                 capture=True)
    if not listed:
        return None
    if listed != name:
        raise TrialRefused("Ambiguous Docker container name")
    fmt = '{{.Id}}|{{.Config.Image}}|{{index .Config.Labels "uopti.backhaul.trial"}}'
    out = run(["docker", "inspect", "-f", fmt, name], capture=True)
    fields = out.split("|")
    if len(fields) != 3:
        raise TrialRefused("Unexpected Docker ownership evidence")
    return tuple(fields)


@contextmanager
def mutex():
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise TrialRefused("Unsafe installer lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError as exc:
        raise TrialRefused("Another trial transaction is running") from exc
    finally:
        os.close(fd)


def _root(role: str, *, create: bool = False) -> Path:
    if role not in ROLES:
        raise TrialRefused("Unknown role")
    # A dedicated state root prevents accidental interaction with Smite files.
    for part in (STATE_ROOT.parent, STATE_ROOT):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or (
                    stat.S_IMODE(info.st_mode) & 0o022):
                raise TrialRefused("Unsafe state ancestor")
        elif create:
            part.mkdir(mode=0o700)
    target = STATE_ROOT / role
    if create:
        target.mkdir(mode=0o700)
    if target.exists() or target.is_symlink():
        info = target.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or (
                stat.S_IMODE(info.st_mode) & 0o077):
            raise TrialRefused("Unsafe state journal directory")
    return target


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(path: Path, contents: bytes, *, mode: int = 0o600,
                 replace: bool = True) -> None:
    if path.is_symlink():
        raise TrialRefused("Refusing symlink target")
    fd, temp = tempfile.mkstemp(prefix=".uopti-backhaul-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as writer:
            os.fchmod(writer.fileno(), mode)
            writer.write(contents)
            writer.flush()
            os.fsync(writer.fileno())
        if replace:
            os.replace(temp, path)
        else:
            os.link(temp, path, follow_symlinks=False)
            os.unlink(temp)
        sync_dir(path.parent)
    except FileExistsError as exc:
        raise TrialRefused("Another installer created a conflicting file") from exc
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def _safe_file(path: Path, *, owner: int = 0,
               mode: int | None = None) -> tuple[bytes, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_gid != 0:
        raise TrialRefused("File identity changed; recovery on HOLD")
    permissions = stat.S_IMODE(info.st_mode)
    if mode is not None and permissions != mode:
        raise TrialRefused("File permissions changed; recovery on HOLD")
    if permissions not in (0o600, 0o640, 0o644):
        raise TrialRefused("Unsafe file permissions; recovery on HOLD")
    return path.read_bytes(), permissions


def _journal_read(root: Path) -> dict:
    contents, _ = _safe_file(root / JOURNAL, mode=0o600)
    try:
        doc = json.loads(contents)
    except (ValueError, UnicodeError) as exc:
        raise TrialRefused("Unreadable trial journal") from exc
    if not isinstance(doc, dict) or set(doc) != {
            "version", "role", "trial_id", "resources", "phase"}:
        raise TrialRefused("Unexpected trial journal schema")
    role = doc["role"]
    if role not in ROLES or doc["version"] != 1 or (
            not isinstance(doc["trial_id"], str) or
            len(doc["trial_id"]) != 24 or
            not isinstance(doc["resources"], list) or
            len(doc["resources"]) != len(paired.LAYOUT[role])):
        raise TrialRefused("Trial journal identity invalid")
    for row, (expected, (operation, _, _)) in zip(
            doc["resources"], paired.LAYOUT[role].items()):
        if not isinstance(row, dict) or set(row) != {
                "path", "operation", "before", "after", "mode"}:
            raise TrialRefused("Resource journal schema invalid")
        if row["path"] != expected or row["operation"] != operation or (
                not isinstance(row["after"], str) or
                len(row["after"]) != 64 or
                not all(ch in "0123456789abcdef" for ch in row["after"])):
            raise TrialRefused("Resource journal identity invalid")
        if operation == "edit" and (
                not isinstance(row["before"], str) or len(row["before"]) != 64
                or row["mode"] not in (0o600, 0o640, 0o644)):
            raise TrialRefused("Original Nginx journal invalid")
        if operation == "create" and (
                row["before"] is not None or row["mode"] != 0o600):
            raise TrialRefused("Created resource journal invalid")
    return doc


def _journal_store(root: Path, doc: dict) -> None:
    write_atomic(root / JOURNAL, (json.dumps(doc, sort_keys=True) + "\n").encode())


def _check_targets(resources: list[dict], role: str) -> list[dict]:
    if [r["path"] for r in resources] != list(paired.LAYOUT[role]):
        raise TrialRefused("Unrecognized resource paths")
    rows = []
    for r in resources:
        target = Path(r["path"])
        if not admission._existing_ancestors_safe(target):
            raise TrialRefused("Unsafe directory ancestor")
        if r["operation"] == "edit":
            content, mode = _safe_file(target)
            if content != r["before"]:
                raise TrialRefused("Nginx original changed since planning")
        else:
            if target.exists() or target.is_symlink():
                raise TrialRefused("Resource already exists")
            mode = 0o600
        rows.append({"path": r["path"], "operation": r["operation"],
                     "before": sha(r["before"]) if r["before"] is not None else None,
                     "after": sha(r["after"]), "mode": mode})
    return rows


def _verify_resource_states(doc: dict) -> dict[str, str]:
    found = {}
    for row in doc["resources"]:
        target = Path(row["path"])
        if not admission._existing_ancestors_safe(target):
            raise TrialRefused("Unsafe target ancestor; recovery blocked")
        if target.exists() or target.is_symlink():
            payload, _ = _safe_file(target, mode=row["mode"])
            signature = sha(payload)
            if signature == row["after"]:
                found[row["path"]] = "applied"
            elif row["operation"] == "edit" and signature == row["before"]:
                found[row["path"]] = "original"
            else:
                raise TrialRefused("Foreign file drift; recovery blocked")
        elif row["operation"] == "create":
            found[row["path"]] = "original"
        else:
            raise TrialRefused("Original vhost missing; recovery blocked")
    return found


def _docker_owned(doc: dict) -> bool:
    name = f"uopti-backhaul-sidecar-{doc['role']}"
    found = _read_docker(name)
    if found is None:
        return False
    _, image, label = found
    if image != IMAGE or label != doc["trial_id"]:
        raise TrialRefused("Foreign Docker container; recovery blocked")
    return True


def _recover_locked(root: Path) -> None:
    doc = _journal_read(root)
    states = _verify_resource_states(doc)  # VALIDATE EVERYTHING before changes
    image_container_present = _docker_owned(doc)
    edited = [r for r in doc["resources"] if r["operation"] == "edit"]
    if len(edited) != 1:
        raise TrialRefused("Missing original vhost in recovery journal")
    backup_path = root / BACKUP
    if backup_path.exists() or backup_path.is_symlink():
        backup, _ = _safe_file(backup_path, mode=0o600)
        if sha(backup) != edited[0]["before"]:
            raise TrialRefused("Original vhost backup mismatch")
    elif any(value != "original" for value in states.values()):
        raise TrialRefused("Backup missing during partial install; recovery blocked")
    else:
        backup = None
    if image_container_present:
        run(["docker", "rm", "-f", f"uopti-backhaul-sidecar-{doc['role']}"])
    for row in reversed(doc["resources"]):
        if states[row["path"]] != "applied":
            continue
        target = Path(row["path"])
        if row["operation"] == "create":
            target.unlink()
            sync_dir(target.parent)
        else:
            if backup is None:
                raise TrialRefused("Backup absent for Nginx rollback")
            write_atomic(target, backup, mode=row["mode"])
    run(["nginx", "-t"])
    run(["systemctl", "reload", "nginx"])
    # A crashed recovery can resume when every target is back at baseline.
    if any(value != "original" for value in _verify_resource_states(doc).values()):
        raise TrialRefused("Recovery incomplete")
    if backup_path.exists():
        backup_path.unlink()
        sync_dir(root)
    (root / JOURNAL).unlink()
    sync_dir(root)
    root.rmdir()


def _create_dirs(resources: list[dict]) -> None:
    # Never create an unjournaled directory before the install journal.
    # Candidate preparation already requires shared.token in this private dir.
    allowed = Path("/etc/u-opti/backhaul-sidecar")
    info = allowed.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or info.st_gid != 0 or stat.S_IMODE(info.st_mode) & 0o077):
        raise TrialRefused("Private token directory must pre-exist with mode 0700")
    secret = allowed / "shared.token"
    token, mode = _safe_file(secret, mode=0o600)
    if not token or len(token) > 256:
        raise TrialRefused("Private shared.token missing or invalid")
    for row in resources:
        if not admission._existing_ancestors_safe(Path(row["path"])):
            raise TrialRefused("Unsafe directory during install")


def install(role: str, sidecar_dir: Path, nginx_dir: Path) -> str:
    if os.geteuid() != 0:
        raise TrialRefused("Root required")
    if os.environ.get("UOPTI_BH_TEST_HOST") != "I_ACCEPT_REBUILD_TEST_HOST":
        raise TrialRefused("Trial host activation not explicitly enabled")
    with mutex():
        root = _root(role)
        if root.exists() or root.is_symlink():
            raise TrialRefused("Existing trial state; rollback/review first")
        resources = paired.reconcile(role, sidecar_dir, nginx_dir)
        issues = admission.admission(role, sidecar_dir, nginx_dir)
        if issues:
            raise TrialRefused("Preflight HOLD: " + "; ".join(issues))
        rows = _check_targets(resources, role)
        name = f"uopti-backhaul-sidecar-{role}"
        if _read_docker(name) is not None:
            raise TrialRefused("Sidecar container name already owned")
        run(["nginx", "-t"])
        run(["systemctl", "is-active", "nginx"])
        run(["docker", "pull", IMAGE])
        # Re-check host evidence just before creating the journal.
        if admission.admission(role, sidecar_dir, nginx_dir):
            raise TrialRefused("Host state changed during Docker image pull")
        _check_targets(resources, role)
        _create_dirs(resources)
        root = _root(role, create=True)
        trial_id = secrets.token_hex(12)
        doc = {"version": 1, "role": role, "trial_id": trial_id,
               "resources": rows, "phase": "prepared"}
        _journal_store(root, doc)  # Durable transaction identity FIRST.
        original = next(r["before"] for r in resources if r["operation"] == "edit")
        write_atomic(root / BACKUP, original, replace=False)
        try:
            for res, row in zip(resources, rows):
                target = Path(res["path"])
                write_atomic(target, res["after"],
                             mode=row["mode"], replace=(res["operation"] == "edit"))
            doc["phase"] = "files_installed"
            _journal_store(root, doc)
            run(["nginx", "-t"])
            run(["docker", "run", "-d", "--name", name,
                 "--label", "uopti.backhaul.trial=" + trial_id,
                 "--network", "host", "--restart", "unless-stopped",
                 "--read-only", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges",
                 "--mount", ("type=bind,src=/etc/u-opti/backhaul-sidecar/"
                             f"{role}.toml,dst=/run/backhaul/config.toml,readonly"),
                 "--entrypoint", "/usr/local/bin/backhaul", IMAGE,
                 "-c", "/run/backhaul/config.toml"])
            if not _docker_owned(doc):
                raise TrialRefused("Sidecar container did not start as expected")
            doc["phase"] = "container_started"
            _journal_store(root, doc)
            run(["systemctl", "reload", "nginx"])
            run(["nginx", "-t"])
            _verify_resource_states(doc)
            if not _docker_owned(doc):
                raise TrialRefused("Sidecar container disappeared")
            doc["phase"] = "trial_active"
            _journal_store(root, doc)
            return "TRIAL_INSTALL_LOCAL_CHECKS_PASSED"
        except Exception as exc:
            try:
                _recover_locked(root)
            except Exception:
                raise TrialRefused(
                    "Install stopped; automatic recovery on HOLD. "
                    "Journal retained for manual recovery") from exc
            raise TrialRefused(
                "Install failed; owned resources recovered to previous state") from exc


def rollback(role: str) -> str:
    if os.geteuid() != 0:
        raise TrialRefused("Root required")
    if os.environ.get("UOPTI_BH_TEST_HOST") != "I_ACCEPT_REBUILD_TEST_HOST":
        raise TrialRefused("Trial host rollback not explicitly enabled")
    with mutex():
        root = _root(role)
        if not root.is_dir():
            raise TrialRefused("No trial journal; nothing to rollback")
        _recover_locked(root)
        return "TRIAL_OWNED_RESOURCES_RECOVERED"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--role", required=True, choices=("ir", "kh"))
    task = p.add_mutually_exclusive_group(required=True)
    task.add_argument("--status", action="store_true")
    task.add_argument("--install-test", action="store_true")
    task.add_argument("--rollback-test", action="store_true")
    p.add_argument("--sidecar-dir", type=Path)
    p.add_argument("--nginx-dir", type=Path)
    p.add_argument("--confirm", default="")
    args = p.parse_args()
    try:
        if args.status:
            root = _root(args.role)
            if not root.is_dir():
                print("NO_TRIAL_JOURNAL")
            else:
                doc = _journal_read(root)
                print("TRIAL_JOURNAL_PRESENT role=" + doc["role"] +
                      " phase=" + doc["phase"])
            return 0
        expected = "INSTALL-" + args.role.upper() if args.install_test else (
            "ROLLBACK-" + args.role.upper())
        if args.confirm != expected:
            raise TrialRefused("Explicit --confirm " + expected + " required")
        if args.install_test:
            if args.sidecar_dir is None or args.nginx_dir is None:
                raise TrialRefused("Both private candidate directories required")
            print(install(args.role, args.sidecar_dir, args.nginx_dir))
        else:
            print(rollback(args.role))
    except (TrialRefused, OSError, ValueError) as exc:
        print("HOLD: " + str(exc))
        return 2
    print("Only local installation verified; authenticated IR/KH traffic")
    print("and separate reboot checks are still mandatory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
