#!/usr/bin/env python3
"""EXPERIMENTAL BACKHAUL ACTIVATION ENGINE - NOT YET RELEASED TO WIZARD.

Designed only for an explicitly rebuilt/reprovisioned disposable test host.
This is intentionally NOT in U-OPTI installer/updater manifests, and its CLI
only supports --check (READ-ONLY) for now; activation entry points are a
Python interface for isolated tests. There is no operational authorization to
execute against production IR/KH. Never copy private stage folders into CI.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from contextlib import contextmanager
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def module(alias, file):
    spec = importlib.util.spec_from_file_location(alias, HERE / file)
    obj = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(obj)
    return obj


pair = module("live_pair_reconcile", "smite-backhaul-sidecar-reconcile.py")
admission = module("live_candidate_admission", "smite-backhaul-sidecar-admission.py")

IMAGE = pair.sidecar.IMAGE
CONTAINER = {"ir": "uopti-backhaul-sidecar-ir",
             "kh": "uopti-backhaul-sidecar-kh"}


class ActivationRefused(ValueError):
    pass


class SubprocessDriver:
    """Strict *argument-level* allowlist for the unreleased trial engine.

    The historical executable-name-only check was insufficient: arbitrary
    arguments to docker/systemctl would have passed. Stage-provided data
    cannot add flags, change mounts, choose images, or pick container names.
    """

    LABEL_FMT = '{{index .Config.Labels "uopti.tx"}}|{{.Config.Image}}'
    PS_FMT = "{{.Names}}"

    @classmethod
    def allowed(cls, argv: list[str]) -> bool:
        if argv in (["nginx", "-t"], ["systemctl", "reload", "nginx"]):
            return True
        if not argv or argv[0] != "docker":
            return False
        for role, name in CONTAINER.items():
            if argv in (
                ["docker", "inspect", "-f", cls.LABEL_FMT, name],
                ["docker", "ps", "-a", "--filter", "name=^/" + name + "$",
                 "--format", cls.PS_FMT],
                ["docker", "update", "--restart", "unless-stopped", name],
                ["docker", "rm", "-f", name],
            ):
                return True
            if len(argv) == 23 and argv[:6] == [
                "docker", "run", "-d", "--name", name, "--label"
            ]:
                label = argv[6]
                if not label.startswith("uopti.tx="):
                    return False
                txn_id = label[len("uopti.tx="):]
                if len(txn_id) != 32 or any(ch not in "0123456789abcdef" for ch in txn_id):
                    return False
                expected = [
                    "docker", "run", "-d", "--name", name,
                    "--label", label, "--network", "host",
                    "--restart", "no", "--read-only",
                    "--cap-drop", "ALL", "--security-opt",
                    "no-new-privileges", "--mount",
                    "type=bind,src=/etc/u-opti/backhaul-sidecar/"
                    + role + ".toml,dst=/run/backhaul/config.toml,readonly",
                    "--entrypoint", "/usr/local/bin/backhaul",
                    IMAGE, "-c", "/run/backhaul/config.toml",
                ]
                return argv == expected
        return False

    def call(self, argv: list[str], timeout: int = 45) -> str:
        if not self.allowed(argv) or type(timeout) is not int or not 1 <= timeout <= 90:
            raise ActivationRefused("Command/arguments not on strict trial allowlist")
        try:
            output = subprocess.run(
                argv, check=True, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ActivationRefused("Required local command failed") from exc
        if len(output.stdout) > 65536:
            raise ActivationRefused("Unexpected command output size")
        return output.stdout.strip()


def shasum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_directory(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ActivationRefused("Unsafe private transaction directory")


def state_write(path: Path, data: dict) -> None:
    private_directory(path.parent)
    raw = (json.dumps(data, sort_keys=True) + "\n").encode()
    fd, temp = tempfile.mkstemp(prefix=".txn-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fsync_directory(path.parent)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_exact(path: Path, contents: bytes, *, owner: int, group: int,
                mode: int, create: bool) -> None:
    """Atomic owner/mode-aware write; never overwrite a newly created target."""
    if mode not in (0o600, 0o640, 0o644):
        raise ActivationRefused("Unsupported file permissions")
    fd, temp = tempfile.mkstemp(prefix=".bh-txn-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), owner, group)
            elif owner != os.geteuid() or group != os.getegid():
                raise ActivationRefused("Cannot preserve file ownership")
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        if create:
            # Link only if destination absent (unlike os.replace).
            os.link(temp, path, follow_symlinks=False)
            os.unlink(temp)
        else:
            os.replace(temp, path)
        fsync_directory(path.parent)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def verified_file(path: Path, expected_hash: str, mode: int, uid: int, gid: int) -> bool:
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode):
            return False
        if (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) != (uid, gid, mode):
            return False
        if st.st_size > 150_000:
            return False
        data = path.read_bytes()
        st2 = path.lstat()
        if (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns) != (
                st2.st_dev, st2.st_ino, st2.st_mtime_ns, st2.st_ctime_ns):
            return False
        return shasum(data) == expected_hash
    except OSError:
        return False


def absent(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    return False


def safe_target(path: Path, role: str, root: Path) -> Path:
    """Only the exact approved resource paths; never arbitrary paths from JSON."""
    if str(path) not in pair.LAYOUT[role]:
        raise ActivationRefused("Unowned destination path")
    return root / path.relative_to("/")


def safe_parents(target: Path, root: Path) -> None:
    # Never traverse symlinked or writable existing ancestors under root.
    segment = target.parent
    while segment != root:
        if segment.exists() or segment.is_symlink():
            st = segment.lstat()
            if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o022:
                raise ActivationRefused("Unsafe destination parent directory")
        segment = segment.parent


def ensure_private_parent(target: Path, root: Path) -> None:
    safe_parents(target, root)
    if target.parent.exists():
        return
    # Only the Sidecar config directory may be created during activation.
    allowed = root / "etc/u-opti/backhaul-sidecar"
    if target.parent != allowed:
        raise ActivationRefused("Unexpected missing parent")
    if not (root / "etc/u-opti").is_dir():
        raise ActivationRefused("U-OPTI config parent missing")
    target.parent.mkdir(mode=0o700)
    fsync_directory(target.parent.parent)


def metadata_for(row: dict, target: Path) -> dict:
    if row["operation"] == "create":
        if not absent(target):
            raise ActivationRefused("Candidate destination already exists")
        suffix = target.suffix
        mode = 0o600 if suffix in (".toml", ".yml") else 0o644
        return {"uid": os.geteuid(), "gid": os.getegid(), "mode": mode}
    if not verified_file(target, shasum(row["before"]),
                         stat.S_IMODE(target.lstat().st_mode),
                         target.lstat().st_uid, target.lstat().st_gid):
        raise ActivationRefused("Original file identity changed during review")
    st = target.lstat()
    if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) not in (
            0o600, 0o640, 0o644):
        raise ActivationRefused("Unsupported original Nginx metadata")
    return {"uid": st.st_uid, "gid": st.st_gid, "mode": stat.S_IMODE(st.st_mode)}


def new_journal(role: str, resources: list[dict], root: Path, txn_id: str) -> dict:
    if role not in CONTAINER:
        raise ActivationRefused("Unknown host role")
    rows = []
    for resource in resources:
        target = safe_target(Path(resource["path"]), role, root)
        safe_parents(target, root)
        if resource["operation"] == "create" and not absent(target):
            raise ActivationRefused("Created file already present")
        if resource["operation"] == "edit" and (
                absent(target) or target.read_bytes() != resource["before"]):
            raise ActivationRefused("Original Nginx changed since proposal")
        attrs = metadata_for(resource, target)
        rows.append({
            "path": resource["path"], "operation": resource["operation"],
            "before_sha256": (shasum(resource["before"])
                              if resource["before"] is not None else None),
            "after_sha256": shasum(resource["after"]),
            **attrs,
        })
    return {
        "version": 1, "id": txn_id, "role": role, "status": "prepared",
        "container": CONTAINER[role], "image": IMAGE,
        "resources": rows,
    }


def record_matches(role: str, doc: dict, txn_id: str) -> bool:
    if (doc.get("version") != 1 or doc.get("id") != txn_id
            or doc.get("role") != role or doc.get("image") != IMAGE
            or doc.get("container") != CONTAINER[role]):
        return False
    return (
        isinstance(doc.get("resources"), list)
        and [r.get("path") for r in doc["resources"]] == list(pair.LAYOUT[role])
        and all(r.get("operation") == pair.LAYOUT[role][r["path"]][0]
                for r in doc["resources"])
    )


@contextmanager
def exclusive(root: Path):
    # Driver/test adapter acquires one OS-level lock per host root.
    # This does not protect against unrelated direct admin edits: hash checks do.
    lock_dir = root / "var/lib/u-opti/backhaul-sidecar"
    if not lock_dir.is_dir():
        raise ActivationRefused("Transaction root must be explicitly provisioned")
    private_directory(lock_dir)
    fd = os.open(lock_dir / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield lock_dir
    finally:
        os.close(fd)


class LiveEngine:
    def __init__(self, *, root: Path, driver: SubprocessDriver):
        self.root = Path(root)
        self.driver = driver
        # A fake-root fixture must NEVER be paired with an actual host driver:
        # that combination would run host-network Docker against the real host.
        if self.root != Path("/") and isinstance(driver, SubprocessDriver):
            raise ActivationRefused("Real host driver forbidden in synthetic fixture")
        self._approved = None

    def _root_allowed(self) -> bool:
        if self.root == Path("/"):
            # This marker must be provided on a deliberately rebuilt,
            # manually approved test VPS; it is NOT created by this module.
            marker = self.root / "root/.uopti-backhaul-rebuilt-test-host"
            try:
                st = marker.lstat()
                return (os.geteuid() == 0 and stat.S_ISREG(st.st_mode)
                        and st.st_uid == 0
                        and stat.S_IMODE(st.st_mode) == 0o600
                        and marker.read_text().strip() ==
                        "I APPROVE DISPOSABLE BACKHAUL TEST HOST")
            except OSError:
                return False
        # Hermetic unit-test trees must be private direct /tmp children.
        try:
            st = self.root.lstat()
            marker = self.root / ".uopti-live-engine-fixture"
            m = marker.lstat()
            return (self.root.parent == Path("/tmp")
                    and self.root.name.startswith("uopti-bh-live-fixture-")
                    and stat.S_ISDIR(st.st_mode)
                    and stat.S_IMODE(st.st_mode) == 0o700
                    and st.st_uid == os.geteuid()
                    and stat.S_ISREG(m.st_mode)
                    and m.st_uid == os.geteuid()
                    and stat.S_IMODE(m.st_mode) == 0o600)
        except OSError:
            return False

    def _txn_dir(self, txn_id: str) -> Path:
        if not (len(txn_id) == 32 and all(ch in "0123456789abcdef" for ch in txn_id)):
            raise ActivationRefused("Invalid transaction reference")
        return self.root / "var/lib/u-opti/backhaul-sidecar" / txn_id

    def docker_owned(self, role: str, txn_id: str) -> bool:
        try:
            line = self.driver.call([
                "docker", "inspect", "-f",
                "{{index .Config.Labels \"uopti.tx\"}}|{{.Config.Image}}",
                CONTAINER[role]], timeout=10)
        except ActivationRefused:
            return False
        return line == txn_id + "|" + IMAGE

    def prepare(self, role: str, sidecar_stage: Path, nginx_stage: Path):
        # No activation without an explicit test-host marker and admission.
        if not self._root_allowed():
            raise ActivationRefused("Test root marker missing; no host changes allowed")
        if role not in CONTAINER:
            raise ActivationRefused("Unknown host role")
        issues = admission.admission(role, sidecar_stage, nginx_stage)
        if issues:
            raise ActivationRefused("Read-only admission HOLD")
        resources = pair.reconcile(role, sidecar_stage, nginx_stage)
        self._approved = (role, tuple((r["path"], shasum(r["after"]))
                                       for r in resources))
        return resources

    def apply(self, role: str, resources: list[dict], *, txn_id: str) -> str:
        """Only call following explicit operator approval and full preflight.

        Transaction directory must already have been provisioned safely.
        """
        if not self._root_allowed():
            raise ActivationRefused("Activation root no longer authorized")
        evidence = (role, tuple((r["path"], shasum(r["after"]))
                                for r in resources))
        if self._approved != evidence or role not in CONTAINER:
            raise ActivationRefused("Fresh admission approval missing or outdated")
        self._approved = None  # One-time scoped admission, no replay.
        with exclusive(self.root):
            target_dir = self._txn_dir(txn_id)
            target_dir.mkdir(mode=0o700, exist_ok=False)
            private_directory(target_dir)
            journal = new_journal(role, resources, self.root, txn_id)
            original = next(r["before"] for r in resources if r["operation"] == "edit")
            backup = target_dir / "vhost-original"
            write_exact(backup, original, owner=os.geteuid(),
                        group=os.getegid(), mode=0o600, create=True)
            # Journal is fsynced before any installed target changes.
            state_write(target_dir / "journal.json", journal)
            try:
                for resource, entry in zip(resources, journal["resources"]):
                    target = safe_target(Path(resource["path"]), role, self.root)
                    ensure_private_parent(target, self.root)
                    if resource["operation"] == "edit":
                        if not verified_file(
                                target, entry["before_sha256"],
                                entry["mode"], entry["uid"], entry["gid"]):
                            raise ActivationRefused("Vhost drift before atomic apply")
                    elif not absent(target):
                        raise ActivationRefused("Resource collision before create")
                    write_exact(target, resource["after"],
                                owner=entry["uid"], group=entry["gid"],
                                mode=entry["mode"],
                                create=resource["operation"] == "create")
                self.driver.call(["nginx", "-t"], timeout=15)
                self.driver.call(["systemctl", "reload", "nginx"], timeout=25)
                # A transaction label survives a power loss between Docker
                # creation and journal update, enabling ownership verification.
                self.driver.call([
                    "docker", "run", "-d", "--name", CONTAINER[role],
                    "--label", "uopti.tx=" + txn_id,
                    "--network", "host", "--restart", "no", "--read-only",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--mount", "type=bind,src=/etc/u-opti/backhaul-sidecar/"
                    + role + ".toml,dst=/run/backhaul/config.toml,readonly",
                    "--entrypoint", "/usr/local/bin/backhaul", IMAGE,
                    "-c", "/run/backhaul/config.toml",
                ], timeout=60)
                if not self.docker_owned(role, txn_id):
                    raise ActivationRefused("Sidecar ownership could not be verified")
                self.driver.call(["docker", "update", "--restart", "unless-stopped",
                                  CONTAINER[role]], timeout=20)
                # Checks remain local only; authenticated VLESS requires a
                # separate real-client verification after BOTH servers installed.
                failures = admission.local.inspect_local(role, "existing")
                if failures:
                    raise ActivationRefused("Post-install local health gate HOLD")
                journal["status"] = "local-validated-only"
                state_write(target_dir / "journal.json", journal)
                return txn_id
            except Exception:
                # Do NOT silently swallow rollback failure: preserve journal.
                self._rollback_locked(role, txn_id)
                raise

    def _read_journal(self, role: str, txn_id: str) -> tuple[Path, dict]:
        target_dir = self._txn_dir(txn_id)
        private_directory(target_dir)
        path = target_dir / "journal.json"
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > 32768):
            raise ActivationRefused("Unsafe journal metadata")
        doc = json.loads(path.read_text())
        if not record_matches(role, doc, txn_id):
            raise ActivationRefused("Journal ownership mismatch; manual recovery only")
        return target_dir, doc

    def _rollback_locked(self, role: str, txn_id: str) -> None:
        target_dir, doc = self._read_journal(role, txn_id)
        backup = target_dir / "vhost-original"
        backup_st = backup.lstat()
        if (not stat.S_ISREG(backup_st.st_mode)
                or stat.S_IMODE(backup_st.st_mode) != 0o600):
            raise ActivationRefused("Unverifiable original backup")
        old = backup.read_bytes()
        # Validate ENTIRE resource set before touching Docker or any file.
        states = []
        for entry in doc["resources"]:
            target = safe_target(Path(entry["path"]), role, self.root)
            if absent(target):
                if entry["operation"] != "create":
                    raise ActivationRefused("Original vhost unexpectedly missing")
                states.append("original")
            elif verified_file(target, entry["after_sha256"],
                               entry["mode"], entry["uid"], entry["gid"]):
                states.append("applied")
            elif (entry["operation"] == "edit" and verified_file(
                    target, entry["before_sha256"],
                    entry["mode"], entry["uid"], entry["gid"])):
                states.append("original")
            else:
                raise ActivationRefused("Foreign file drift; refuse rollback")
        edit = [x for x in doc["resources"] if x["operation"] == "edit"]
        if len(edit) != 1 or shasum(old) != edit[0]["before_sha256"]:
            raise ActivationRefused("Original vhost backup hash mismatch")
        if self.docker_owned(role, txn_id):
            self.driver.call(["docker", "rm", "-f", CONTAINER[role]], timeout=30)
        else:
            # A failed docker inspect can mean daemon downtime, NOT absence.
            # docker ps returning successfully is required before any file edit.
            listed = self.driver.call([
                "docker", "ps", "-a", "--filter",
                "name=^/" + CONTAINER[role] + "$", "--format", "{{.Names}}"
            ], timeout=10)
            if listed != "":
                raise ActivationRefused("Foreign or unverified Sidecar container; HOLD")
        for entry, condition in reversed(list(zip(doc["resources"], states))):
            if condition != "applied":
                continue
            target = safe_target(Path(entry["path"]), role, self.root)
            if entry["operation"] == "create":
                target.unlink()
                fsync_directory(target.parent)
            else:
                write_exact(target, old, owner=entry["uid"], group=entry["gid"],
                            mode=entry["mode"], create=False)
        self.driver.call(["nginx", "-t"], timeout=15)
        self.driver.call(["systemctl", "reload", "nginx"], timeout=25)
        doc["status"] = "rolled-back"
        state_write(target_dir / "journal.json", doc)

    def rollback(self, role: str, txn_id: str) -> None:
        if not self._root_allowed() or role not in CONTAINER:
            raise ActivationRefused("Rollback requires approved test-host identity")
        with exclusive(self.root):
            self._rollback_locked(role, txn_id)


def main() -> int:
    print("EXPERIMENTAL: operational apply/rollback CLI is NOT enabled.")
    print("The engine is not distributed by U-OPTI and must first pass lab tests.")
    print("NO FILES OR SERVICES MODIFIED.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
