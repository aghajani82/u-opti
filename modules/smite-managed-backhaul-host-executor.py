#!/usr/bin/env python3
"""Explicit Backhaul disposable-host transaction executor.

This is NOT a production release switch and is intentionally not wired to
the beginner menu. It can mutate only the existing managed Smite Node's
Backhaul binary/Compose/engine manifest after a separately reviewed image
digest, package/plan SHA, snapshot+console acknowledgement and exact
role-specific confirmation are supplied.

It never changes Nginx, firewall, Xray/Sanaei, Panel, public ports, FRP
binaries or tunnel routes. A signed HMAC/replay probe of the real Node runs
before and after the single Node recreation. Failure compensates by restoring
journaled bytes and proving the prior signed inventory again.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
SHA = re.compile(r"^[a-f0-9]{64}$")
IMAGE = re.compile(r"^ghcr\.io/aghajani82/smite-node@sha256:[a-f0-9]{64}$")
SNAPSHOT_CONFIRM = "SNAPSHOT-RESTORE-AND-CONSOLE-VERIFIED"
ENGINE_NAMES = ("backhaul", "frp", "gost", "rathole", "chisel")
MAX_FILE = 1024 * 1024
MAX_BINARY = 48 * 1024 * 1024

def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("MISSING_REVIEWED_MODULE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

admission = _load("uopti_bh_host_exec_admission", "smite-managed-engine-host-admission.py")
plan = _load("uopti_bh_host_exec_plan", "smite-managed-engine-host-plan.py")
package = plan.backhaul

@dataclass(frozen=True)
class Paths:
    node: Path = Path("/opt/smite-node")
    staging: Path = Path("/var/lib/u-opti/smite-engine-staging")
    state: Path = Path("/var/lib/u-opti/smite-engine-host/backhaul")
    lock: Path = Path("/run/lock/u-opti-smite-engine.lock")
    binary: Path = package.INSTALL_BINARY
    frp_state: Path = Path("/var/lib/u-opti/smite-rc7-frp-enrollment")

class Hold(RuntimeError):
    pass

class SimulatedCrash(RuntimeError):
    pass


def _deny_live_recreating_trial_paths(paths: Paths) -> None:
    """Refuse production paths for the legacy Node-recreating trial executor.

    The legacy transaction uses --force-recreate. A textual acknowledgement
    is not independent snapshot/restore or console proof. Never acquire even
    the production engine lock, probe Docker or write a journal via its
    install/rollback/recover path. Separately approved in-place enrollment
    is deliberately NOT implemented by this guard.
    """
    if not isinstance(paths, Paths):
        raise Hold("LEGACY_TRIAL_PATHS_UNTRUSTED")
    live = Paths()
    protected = []
    for name in ("node", "staging", "state", "lock", "binary", "frp_state"):
        fixed = getattr(live, name)
        protected.extend((fixed, fixed.resolve()))
    for name in ("node", "staging", "state", "lock", "binary"):
        path = getattr(paths, name)
        if not isinstance(path, Path) or not path.is_absolute():
            raise Hold("LEGACY_TRIAL_PATHS_UNTRUSTED")
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise Hold("LEGACY_TRIAL_PATHS_UNTRUSTED") from exc
        for candidate in (path, resolved):
            if any(candidate == fixed or candidate in fixed.parents
                   or fixed in candidate.parents for fixed in protected):
                raise Hold("LIVE_NODE_RECREATING_TRIAL_FORBIDDEN")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _read(path: Path, limit: int = MAX_FILE) -> bytes:
    try:
        if path.is_symlink():
            raise Hold("UNSAFE_SYMLINK")
        st = path.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_uid != os.geteuid() or st.st_size < 0
                or st.st_size > limit):
            raise Hold("UNSAFE_FILE")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as source:
            opened = os.fstat(source.fileno())
            if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
                raise Hold("FILE_CHANGED_DURING_REVIEW")
            return source.read(limit + 1)
    except FileNotFoundError as exc:
        raise Hold("MISSING_FILE") from exc
    except OSError as exc:
        raise Hold("FILE_IO_FAILURE") from exc

def _dir(path: Path, *, create: bool = False) -> None:
    if path.is_symlink():
        raise Hold("UNSAFE_DIRECTORY")
    if not path.exists():
        if not create:
            raise Hold("MISSING_DIRECTORY")
        parent = path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise Hold("UNSAFE_DIRECTORY_PARENT")
        path.mkdir(mode=0o700)
        fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    st = path.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) & 0o077):
        raise Hold("PRIVATE_DIRECTORY_REQUIRED")

def _trusted_anchor(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise Hold("UNSAFE_MANAGED_DIRECTORY")
    st = path.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) & 0o022):
        raise Hold("UNSAFE_MANAGED_DIRECTORY")

def _mkdir_chain(path: Path, anchor: Path) -> None:
    if not anchor.is_absolute() or not path.is_absolute() or anchor not in path.parents:
        raise Hold("UNSAFE_MANAGED_DIRECTORY")
    _trusted_anchor(anchor)
    current = anchor
    for part in path.relative_to(anchor).parts:
        current = current / part
        _dir(current, create=True)

def _atomic(path: Path, data: bytes, mode: int) -> None:
    if path.is_symlink():
        raise Hold("TARGET_SYMLINK")
    _dir(path.parent)
    fd, temp = tempfile.mkstemp(prefix=".uopti-host-new-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), mode)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def _new(path: Path, data: bytes, mode: int) -> None:
    _dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), mode)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise

@contextmanager
def _lock(path: Path):
    if (not path.is_absolute() or path.is_symlink()
            or path.parent.is_symlink() or not path.parent.is_dir()):
        raise Hold("UNSAFE_LOCK_PATH")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600):
            raise Hold("UNSAFE_LOCK_FILE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold("ANOTHER_ENGINE_TRANSACTION_ACTIVE") from exc
        # A file replaced between open() and flock() is a detached lock
        # inode. No second writer would be serialized by that old inode.
        # Fail before the first transactional journal or engine write.
        try:
            current = path.lstat()
        except OSError as exc:
            raise Hold("ENGINE_LOCK_CHANGED") from exc
        if (not stat.S_ISREG(current.st_mode) or
                (current.st_dev, current.st_ino) != (st.st_dev, st.st_ino)):
            raise Hold("ENGINE_LOCK_CHANGED")
        yield
    finally:
        os.close(fd)

@contextmanager
def _read_only_engine_lock(path: Path):
    """Hold the existing RC7 engine lock across the full read-only review.

    Never create a lock file: missing, replaced or busy lock means HOLD.
    An exclusive FRP or retained-Backhaul transaction must not race the
    journal, Docker identity, signed pair and manifest observations.
    """
    if (not path.is_absolute() or path.is_symlink()
            or path.parent.is_symlink() or not path.parent.is_dir()):
        raise Hold("RETAINED_ENGINE_LOCK_UNTRUSTED")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise Hold("RETAINED_ENGINE_LOCK_MISSING") from exc
    except OSError as exc:
        raise Hold("RETAINED_ENGINE_LOCK_UNTRUSTED") from exc
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600):
            raise Hold("RETAINED_ENGINE_LOCK_UNTRUSTED")
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold("RETAINED_ENGINE_LOCK_BUSY") from exc
        # Holding a lock on a detached inode does not serialize writers.
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (st.st_dev, st.st_ino):
            raise Hold("RETAINED_ENGINE_LOCK_CHANGED")
        yield
    except OSError as exc:
        raise Hold("RETAINED_ENGINE_LOCK_UNTRUSTED") from exc
    finally:
        os.close(fd)

# The operator CLI only reviews retained nodes. The write entry below is
# exercised on isolated nodes until independent deployment admission exists.
pair = _load("retained_pair", "smite-managed-backhaul-transaction.py")


def _retained_files(paths):
    manifest = paths.node / "config/engine-state/engines.json"
    receipt = paths.frp_state / "record.json"
    for directory in (manifest.parent, receipt.parent, paths.state):
        if not directory.is_absolute() or directory.resolve(strict=True) != directory:
            raise Hold("RETAINED_DIRECTORY_UNTRUSTED")
        _dir(directory)
    return manifest, receipt, paths.state / "retained-rc7.json"


def _retained_finish_cleanup(*, seal, journal, role, binary, fingerprint,
                             witness, current):
    """Resume terminal RESTORED cleanup, including after journal unlink.

    This helper is private to the isolated retained-node transaction. A
    durable seal protects the crash interval between deleting the restored
    journal and syncing its directory. Neither path admits live hosts.
    """
    try:
        envelope = pair._pair_load_json(pair._pair_read_private(seal, limit=4096))
    except (pair.Hold, OSError, ValueError, TypeError) as exc:
        raise Hold("RETAINED_CLEANUP_SEAL_UNTRUSTED") from exc
    record = envelope.get("record")
    keys = {"schema", "role", "binary", "witness",
            "manifest_sha256", "receipt_sha256", "journal_sha256"}
    if (set(envelope) != {"record", "sha256"} or not isinstance(record, dict)
            or set(record) != keys or type(record["schema"]) is not int
            or record["schema"] != 1 or record["role"] != role
            or record["binary"] != binary or record["witness"] != fingerprint
            or any(type(record[key]) is not str or SHA.fullmatch(record[key]) is None
                   for key in ("manifest_sha256", "receipt_sha256", "journal_sha256"))
            or _sha(json.dumps(record, sort_keys=True).encode()) != envelope["sha256"]):
        raise Hold("RETAINED_CLEANUP_SEAL_UNTRUSTED")

    before = current()
    if (_sha(before[0]) != record["manifest_sha256"]
            or _sha(before[1]) != record["receipt_sha256"]
            or witness() != fingerprint):
        raise Hold("RETAINED_CLEANUP_BASELINE_DRIFT")
    # Hash equality alone is not the retained FRP receipt's semantic proof.
    try:
        pair._pair_expected_transition(*before, binary, role=role)
    except pair.Hold as exc:
        raise Hold("RETAINED_CLEANUP_SEMANTIC_DRIFT") from exc
    if os.path.lexists(journal):
        try:
            journal_digest = _sha(pair._pair_read_private(journal, limit=40000))
        except (pair.Hold, OSError, ValueError, TypeError) as exc:
            raise Hold("RETAINED_CLEANUP_JOURNAL_DRIFT") from exc
        if journal_digest != record["journal_sha256"]:
            raise Hold("RETAINED_CLEANUP_JOURNAL_DRIFT")
        journal.unlink()
        pair._pair_fsync_dir(journal.parent)
    if (current() != before or witness() != fingerprint):
        raise Hold("RETAINED_CLEANUP_POSTCHECK_FAILED")
    seal.unlink()
    pair._pair_fsync_dir(seal.parent)
    return "CLEANED"


def _retained_step(paths, *, action, role, arch, witness, expected_before=None,
                   expected_witness=None):
    """Apply or compensate under the same lock used by RC7 FRP enrollment.

    witness() re-authenticates this retained node and returns the stable
    protected-state fingerprint. No mutable host caller is admitted yet.
    """
    if action not in ("install", "rollback", "recover", "cleanup") or role not in ("ir", "foreign"):
        raise Hold("RETAINED_OPERATION_INVALID")
    if arch not in package.OFFICIAL_BINARY_SHA256:
        raise Hold("OFFICIAL_BACKHAUL_ARCH_REQUIRED")
    # The two-role coordinator binds install to the EXACT preflight bytes.
    # A cooperating writer may alter an otherwise valid FRP receipt between
    # the first host preflight and this lock; never silently adopt new bytes.
    if expected_before is not None:
        if (action != "install" or not isinstance(expected_before, tuple)
                or len(expected_before) != 2
                or any(type(raw) is not bytes or not 0 < len(raw) <= 8192
                       for raw in expected_before)):
            raise Hold("RETAINED_EXPECTED_BASELINE_INVALID")
        # The coordinator's separately collected protected-runtime witness
        # belongs to the exact preflight pair. Never adopt a fresh process
        # identity in the handoff interval after the two-host admission.
        if (type(expected_witness) is not str
                or SHA.fullmatch(expected_witness) is None):
            raise Hold("RETAINED_EXPECTED_WITNESS_REQUIRED")
    elif expected_witness is not None:
        raise Hold("RETAINED_EXPECTED_WITNESS_UNEXPECTED")
    # Never lock or write a protected live resource through an alternate
    # field, a parent/child alias or a symlink. An earlier boundary checked
    # only node/frp_state/state, overlooking the real shared FRP lock path.
    # Keep the entire retained mutation executor CI-only pending independent
    # signed two-host admission and explicitly authorized production rollout.
    if not isinstance(paths, Paths):
        raise Hold("RETAINED_OPERATION_PATH_UNTRUSTED")
    live = Paths()
    fields = ("node", "staging", "state", "lock", "binary", "frp_state")
    def resolve_checked(path: Path) -> Path:
        try:
            return path.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise Hold("RETAINED_OPERATION_PATH_UNTRUSTED") from exc

    protected = []
    for name in fields:
        fixed = getattr(live, name)
        protected.extend((fixed, resolve_checked(fixed)))
    for name in fields:
        resource = getattr(paths, name)
        if not isinstance(resource, Path) or not resource.is_absolute():
            raise Hold("RETAINED_OPERATION_PATH_UNTRUSTED")
        for candidate in (resource, resolve_checked(resource)):
            if any(candidate == fixed or fixed in candidate.parents
                   or candidate in fixed.parents for fixed in protected):
                raise Hold("INDEPENDENT_DEPLOYMENT_APPROVAL_REQUIRED")
    # This writer is private but directly callable by imported Python code.
    # The two-host coordinator already requires a marked GitHub PR sandbox;
    # require the SAME admission at this lower mutation boundary so no
    # caller can bypass it by invoking _retained_step on alternate host paths.
    # This check must precede opening the shared engine lock or any journal.
    root = paths.node.parent
    if (not root.is_absolute() or paths.node != root / "node"):
        raise Hold("RETAINED_CI_LAB_ONLY")
    try:
        pair.admission(root)
        for name in ("staging", "state", "lock", "binary", "frp_state"):
            pair.ensure_in_lab(root, getattr(paths, name))
    except (pair.Hold, OSError, ValueError, TypeError) as exc:
        raise Hold("RETAINED_CI_LAB_ONLY") from exc
    binary = package.OFFICIAL_BINARY_SHA256[arch]

    with _lock(paths.lock):
        manifest, receipt, journal = _retained_files(paths)
        for conflict in (_journal(paths), receipt.with_name("record.next"),
                         manifest.with_name("engines.json.rc7-next"),
                         manifest.with_name("engines.json.rc7-rollback-next")):
            if os.path.lexists(conflict):
                raise Hold("COMPETING_RECOVERY_REQUIRED")

        def current():
            return pair._pair_read_private(manifest), pair._pair_read_private(receipt)

        def record_phase(phase):
            record["phase"] = phase
            payload = json.dumps(record, sort_keys=True).encode()
            envelope = {"record": record, "sha256": _sha(payload)}
            _atomic(journal, (json.dumps(envelope, sort_keys=True) + "\n").encode(), 0o600)

        fingerprint = witness()
        if not isinstance(fingerprint, str) or not SHA.fullmatch(fingerprint):
            raise Hold("RETAINED_RUNTIME_PROOF_REQUIRED")
        if (expected_witness is not None
                and fingerprint != expected_witness):
            raise Hold("RETAINED_PREFLIGHT_WITNESS_CHANGED")
        seal = paths.state / "retained-rc7-cleanup.json"
        # A coordinator's fresh install must start with an empty journal.
        # An independently appearing COMMITTED receipt/journal between the
        # two-host preflight and this locked writer is NOT our transaction;
        # never adopt it as an idempotent success or as rollback evidence.
        if expected_before is not None and (os.path.lexists(journal)
                                            or os.path.lexists(seal)):
            raise Hold("RETAINED_PREFLIGHT_JOURNAL_APPEARED")
        if os.path.lexists(seal):
            if action != "cleanup":
                raise Hold("RETAINED_CLEANUP_RECOVERY_REQUIRED")
            return _retained_finish_cleanup(
                seal=seal, journal=journal, role=role, binary=binary,
                fingerprint=fingerprint, witness=witness, current=current)

        if os.path.lexists(journal):
            envelope = pair._pair_load_json(pair._pair_read_private(journal, limit=40000))
            record = envelope.get("record")
            if (set(envelope) != {"record", "sha256"} or not isinstance(record, dict)
                    or _sha(json.dumps(record, sort_keys=True).encode()) != envelope["sha256"]):
                raise Hold("RETAINED_JOURNAL_CHECKSUM_INVALID")
            if (set(record) != {"schema", "role", "binary", "witness", "manifest",
                                "receipt", "phase"} or type(record["schema"]) is not int
                    or record["schema"] != 1 or record["role"] != role
                    or record["binary"] != binary or record["witness"] != fingerprint
                    or record["phase"] not in ("PREPARED", "COMMITTED", "RESTORING", "RESTORED")):
                raise Hold("RETAINED_JOURNAL_UNTRUSTED")
            # A checksummed journal is not inherently trusted input. Reject
            # malformed/noncanonical hex snapshots *before* decoding them:
            # bytes.fromhex would otherwise raise uncaught TypeError/ValueError
            # and accepts whitespace that is not part of the reviewed format.
            for key in ("manifest", "receipt"):
                raw_hex = record[key]
                if (type(raw_hex) is not str or not 0 < len(raw_hex) <= 16384
                        or len(raw_hex) % 2
                        or re.fullmatch(r"(?:[0-9a-f]{2})+", raw_hex) is None):
                    raise Hold("RETAINED_JOURNAL_UNTRUSTED")
            try:
                before = tuple(bytes.fromhex(record[key])
                               for key in ("manifest", "receipt"))
            except (TypeError, ValueError) as exc:
                raise Hold("RETAINED_JOURNAL_UNTRUSTED") from exc
        else:
            if action != "install":
                raise Hold("RETAINED_JOURNAL_MISSING")
            before = current()
            # Re-check under the SAME exclusive lock as the first fsynced
            # PREPARED journal write. Never create a journal on stale proof.
            if expected_before is not None and before != expected_before:
                raise Hold("RETAINED_PREFLIGHT_PAIR_CHANGED")
            record = {"schema": 1, "role": role, "binary": binary, "witness": fingerprint,
                      "manifest": before[0].hex(), "receipt": before[1].hex(), "phase": "NEW"}

        after = pair._pair_expected_transition(*before, binary, role=role)
        observed = current()
        mixed = (after[0], before[1])
        allowed = {"NEW": (before,), "PREPARED": (before, mixed, after),
                   "COMMITTED": (after,), "RESTORING": (before, mixed, after),
                   "RESTORED": (before,)}
        phase = record["phase"]
        if observed not in allowed[phase]:
            raise Hold("RETAINED_PAIR_DRIFT")
        if action == "cleanup":
            if phase != "RESTORED":
                raise Hold("RETAINED_CLEANUP_REQUIRES_RESTORED")
            raw_journal = pair._pair_read_private(journal, limit=40000)
            cleanup = {"schema": 1, "role": role, "binary": binary,
                       "witness": fingerprint,
                       "manifest_sha256": _sha(before[0]),
                       "receipt_sha256": _sha(before[1]),
                       "journal_sha256": _sha(raw_journal)}
            envelope = {"record": cleanup,
                        "sha256": _sha(json.dumps(cleanup, sort_keys=True).encode())}
            # Refuse a stale protected Node/FRP identity or changed pair
            # before writing even the terminal cleanup seal. The later
            # cleanup verification remains necessary for subsequent races.
            if current() != observed or witness() != fingerprint:
                raise Hold("RETAINED_RUNTIME_OR_PAIR_DRIFT")
            # Persist terminal proof before deleting any recovery evidence.
            _atomic(seal, (json.dumps(envelope, sort_keys=True) + "\n").encode(), 0o600)
            return _retained_finish_cleanup(
                seal=seal, journal=journal, role=role, binary=binary,
                fingerprint=fingerprint, witness=witness, current=current)
        if action == "install":
            if phase == "COMMITTED":
                return phase
            # A restored transaction still owns its durable recovery journal.
            # Re-enrollment must not reuse that journal and overwrite the
            # terminal RESTORED evidence before its sealed cleanup completes.
            if phase == "RESTORED":
                raise Hold("RETAINED_TERMINAL_CLEANUP_REQUIRED")
            if phase != "NEW":
                raise Hold("RETAINED_RECOVERY_REQUIRED")
            # Do not even create the durable PREPARED journal if a concurrent
            # FRP/Node change happened after our first witness observation.
            if (expected_witness is not None
                    and witness() != expected_witness):
                raise Hold("RETAINED_PREFLIGHT_WITNESS_CHANGED")
            record_phase("PREPARED")
            destination = after
            order = (0, 1)
            final = "COMMITTED"
        else:
            if phase == "RESTORED" or (action == "recover" and phase == "COMMITTED"):
                return phase
            # Mirror install's pre-PREPARED identity check: a protected
            # process or paired receipt may rotate while rollback is planned.
            # Do not replace a valid recovery journal with RESTORING until
            # the original witness and exact observed pair still hold.
            if current() != observed or witness() != fingerprint:
                raise Hold("RETAINED_RUNTIME_OR_PAIR_DRIFT")
            record_phase("RESTORING")
            destination = before
            order = (1, 0)
            final = "RESTORED"
        for index in order:
            if current() != observed or witness() != fingerprint:
                raise Hold("RETAINED_RUNTIME_OR_PAIR_DRIFT")
            if observed[index] != destination[index]:
                pair._pair_atomic((manifest, receipt)[index], destination[index])
                updated = list(observed)
                updated[index] = destination[index]
                observed = tuple(updated)
        if current() != destination or witness() != fingerprint:
            raise Hold("RETAINED_FINAL_PROOF_FAILED")
        record_phase(final)
        return final



def _retained_two_host_rehearsal_lab(ir: Paths, foreign: Paths, *,
                                     arch: str, observe, inject: str = "") -> dict[str, str]:
    """Exercise the actual retained host transaction on TWO disposable nodes.

    Unlike the older paired-file lab, this uses _retained_step (the existing
    Host Executor's fsynced phase journal and terminal cleanup) on each role.
    It ALWAYS compensates both nodes, even after success. It cannot be
    invoked by the menu or CLI and requires the GitHub PR disposable marker
    for each root. Fixture hashes are NOT signed runtime/forwarding proof.
    """
    if (arch not in package.OFFICIAL_BINARY_SHA256
            or inject not in ("", "after-ir", "after-both")
            or not callable(observe)
            or not isinstance(ir, Paths) or not isinstance(foreign, Paths)):
        raise Hold("RETAINED_TWO_HOST_REHEARSAL_INVALID")
    hosts = (("ir", ir), ("foreign", foreign))
    roots = []
    for role, paths in hosts:
        root = paths.node.parent
        expected = {
            "node": root / "node",
            "staging": root / "stages",
            "frp_state": root / pair.PAIR_RECEIPT_DIR,
            "state": root / "state/engine/backhaul",
            "lock": root / "engine.lock",
            "binary": root / "installed/backhaul",
        }
        if (not root.is_absolute()
                or any(getattr(paths, key) != value or value.resolve() != value
                       for key, value in expected.items())):
            raise Hold("RETAINED_TWO_HOST_LAB_PATH_UNTRUSTED")
        # Strict GitHub PR-only marker, private root and directory admission.
        # Never remove/bypass this check in order to touch production hosts.
        try:
            pair.admission(root)
            pair._pair_paths(root)
            pair._rc7_two_host_guards(root, role=role)
        except (pair.Hold, OSError, ValueError) as exc:
            raise Hold("RETAINED_TWO_HOST_LAB_ADMISSION_REQUIRED") from exc
        roots.append(root)
    if (roots[0] == roots[1] or roots[0] in roots[1].parents
            or roots[1] in roots[0].parents):
        raise Hold("RETAINED_TWO_HOST_DISTINCT_LABS_REQUIRED")

    # The witness is tied to existing FRP Owner/Child and broker/replay
    # fixtures, not caller-provided fake hex. Nothing here claims real signed
    # two-host health, TLS/443 continuity, or permission to deploy.
    def witness(role, root):
        digests = pair._rc7_two_host_guards(root, role=role)
        return _sha(json.dumps(digests, separators=(",", ":")).encode())

    snapshots = {}
    baselines = {}
    for role, paths in hosts:
        # Both preflights MUST pass before either manifest is touched.
        try:
            with _lock(paths.lock):
                manifest, receipt, journal = _retained_files(paths)
                if (os.path.lexists(journal)
                        or os.path.lexists(paths.state / "retained-rc7-cleanup.json")
                        or _retained_review_pending_recovery(paths)):
                    raise Hold("RETAINED_TWO_HOST_PENDING_RECOVERY")
                old = (pair._pair_read_private(manifest),
                       pair._pair_read_private(receipt))
                pair._pair_expected_transition(
                    *old, package.OFFICIAL_BINARY_SHA256[arch], role=role)
                snapshots[role] = old
                baselines[role] = witness(role, paths.node.parent)
        except (pair.Hold, OSError, ValueError, TypeError) as exc:
            # A corrupt Foreign receipt must never escape as an unhandled
            # exception or allow us to begin writing the IR manifest.
            raise Hold("RETAINED_TWO_HOST_PREFLIGHT_UNVERIFIED") from exc

    def unchanged():
        return all(witness(role, paths.node.parent) == baselines[role]
                   for role, paths in hosts)

    def observed(phase):
        try:
            ok = observe(phase, roots[0], roots[1]) is True
        except Exception:
            ok = False
        return ok and unchanged()

    if not observed("before"):
        raise Hold("RETAINED_TWO_HOST_PRIOR_SYNTHETIC_PROOF_FAILED")
    # The observer can be slow or untrusted. Both roles' EXACT original
    # pairs must still match the preflight before any role is modified.
    # Checking Foreign first prevents modifying IR if Foreign already drifted.
    for role, paths in reversed(hosts):
        with _lock(paths.lock):
            manifest, receipt, journal = _retained_files(paths)
            if (_retained_review_pending_recovery(paths) is not None
                    or (pair._pair_read_private(manifest),
                        pair._pair_read_private(receipt)) != snapshots[role]):
                raise Hold("RETAINED_TWO_HOST_PREFLIGHT_PAIR_CHANGED")
            # A peer's FRP/Node identity can drift after the initial
            # two-host observer but before IR's first manifest write.
            # Catch this under the final role-specific engine lock so an
            # IR journal is not begun on stale Foreign protected state.
            if witness(role, paths.node.parent) != baselines[role]:
                raise Hold("RETAINED_TWO_HOST_PREFLIGHT_WITNESS_CHANGED")
    failed = False
    try:
        if _retained_step(ir, action="install", role="ir", arch=arch,
                          witness=lambda: witness("ir", roots[0]),
                          expected_before=snapshots["ir"],
                          expected_witness=baselines["ir"]) != "COMMITTED":
            raise Hold("RETAINED_TWO_HOST_IR_APPLY_NOT_COMMITTED")
        if not observed("after-ir") or inject == "after-ir":
            raise Hold("RETAINED_TWO_HOST_AFTER_IR_PROOF_FAILED")
        if _retained_step(foreign, action="install", role="foreign", arch=arch,
                          witness=lambda: witness("foreign", roots[1]),
                          expected_before=snapshots["foreign"],
                          expected_witness=baselines["foreign"]) != "COMMITTED":
            raise Hold("RETAINED_TWO_HOST_FOREIGN_APPLY_NOT_COMMITTED")
        if not observed("after-both") or inject == "after-both":
            raise Hold("RETAINED_TWO_HOST_AFTER_BOTH_PROOF_FAILED")
    except Exception:
        failed = True

    # Reverse-order compensation uses the SAME real host journal implementation.
    # On drift or interrupted recovery, preserve the journal for manual review.
    try:
        if not unchanged():
            raise Hold("RETAINED_TWO_HOST_PROTECTED_FIXTURE_DRIFT")
        for role, paths in reversed(hosts):
            journal = paths.state / "retained-rc7.json"
            if os.path.lexists(journal):
                outcome = _retained_step(
                    paths, action="rollback", role=role, arch=arch,
                    witness=lambda role=role, root=paths.node.parent:
                        witness(role, root))
                if outcome != "RESTORED":
                    raise Hold("RETAINED_TWO_HOST_EXACT_ROLLBACK_NOT_PROVEN")
        # Both original pairs must be restored and the final external
        # observer must accept them BEFORE removing either host's durable
        # rollback journal. A failed after-rollback observation previously
        # left neither journal available for independent manual review.
        for role, paths in hosts:
            manifest, receipt, journal = _retained_files(paths)
            if ((pair._pair_read_private(manifest),
                 pair._pair_read_private(receipt)) != snapshots[role]
                    or not unchanged()):
                raise Hold("RETAINED_TWO_HOST_RESTORE_MISMATCH")
        if not observed("after-rollback"):
            raise Hold("RETAINED_TWO_HOST_FINAL_SYNTHETIC_PROOF_FAILED")
        # Only now can the existing fsynced terminal cleanup finish. Never
        # mistake a missing journal after a written transaction for proof of
        # completed cleanup. On interruption keep the other journal intact.
        for role, paths in hosts:
            manifest, receipt, journal = _retained_files(paths)
            if os.path.lexists(journal):
                if _retained_step(
                    paths, action="cleanup", role=role, arch=arch,
                    witness=lambda role=role, root=paths.node.parent:
                        witness(role, root)) != "CLEANED":
                    raise Hold("RETAINED_TWO_HOST_CLEANUP_NOT_PROVEN")
            if ((pair._pair_read_private(manifest),
                 pair._pair_read_private(receipt)) != snapshots[role]
                    or not unchanged()
                    or os.path.lexists(journal)
                    or os.path.lexists(paths.state / "retained-rc7-cleanup.json")):
                raise Hold("RETAINED_TWO_HOST_CLEANUP_POSTCHECK_FAILED")
    except Exception:
        raise Hold("RETAINED_TWO_HOST_MANUAL_RECOVERY_REQUIRED") from None

    if failed:
        raise Hold("RETAINED_TWO_HOST_ABORTED_EXACT_ROLLBACK_PROVED")
    return {
        "RETAINED_TWO_HOST": "DISPOSABLE_HOST_EXECUTOR_EXACT_ROLLBACK",
        "RETAINED_RECOVERY_JOURNALS": "SEALED_AND_CLEANED",
        "SIGNED_OWNER_CHILD_CONTINUITY": "NOT_PROVEN",
        "NODE_RECREATED": "NO_DOCKER_EXECUTED_IN_LAB",
        "INSTALL_ALLOWED": "NO",
        "ACTIVATION_GATE": "HOLD",
    }


def _journal(paths: Paths) -> Path:
    return paths.state / "journal"

def _record(paths: Paths) -> dict:
    try:
        raw = _read(_journal(paths) / "record.json", 16384)
        record = json.loads(raw)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise Hold("CORRUPT_HOST_JOURNAL") from exc
    required = {
        "schema", "id", "role", "state", "expected_node_image",
        "plan_sha256", "compose_old", "compose_new", "compose_mode",
        "manifest_old", "manifest_new", "manifest_mode", "binary_new",
        "env_sha256", "tunnels_sha256",
    }
    if (not isinstance(record, dict) or set(record) != required
            or record.get("schema") != 1
            or record.get("role") not in ("IR", "KH")
            or record.get("state") not in (
                "PREPARED", "WROTE_BINARY", "WROTE_COMPOSE", "WROTE_MANIFEST",
                "NODE_RESTARTED", "COMMITTED", "RECOVERING")
            or IMAGE.fullmatch(record.get("expected_node_image", "")) is None
            or SHA.fullmatch(record.get("plan_sha256", "")) is None
            or any(SHA.fullmatch(record.get(k, "") or "") is None
                   for k in ("compose_old", "compose_new", "manifest_new", "binary_new",
                             "env_sha256"))
            or (record.get("manifest_old") is not None
                and SHA.fullmatch(record["manifest_old"]) is None)
            or (record.get("tunnels_sha256") is not None
                and SHA.fullmatch(record["tunnels_sha256"]) is None)
            or type(record.get("compose_mode")) is not int
            or record["compose_mode"] not in (0o600, 0o640, 0o644)
            or (record.get("manifest_mode") is not None
                and record["manifest_mode"] != 0o600)):
        raise Hold("CORRUPT_HOST_JOURNAL")
    return record

def _write_record(paths: Paths, record: dict) -> None:
    _atomic(_journal(paths) / "record.json",
            (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            0o600)

def _file_hash_or_none(path: Path, limit: int = MAX_FILE) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    return _sha(_read(path, limit))

def _protected(paths: Paths) -> tuple[str, str | None]:
    env_hash = _sha(_read(paths.node / ".env", 16384))
    tunnels = paths.node / "config" / "tunnels.json"
    return env_hash, _file_hash_or_none(tunnels, 262144)

def _check_protected(paths: Paths, record: dict) -> None:
    env_hash, tunnels = _protected(paths)
    if env_hash != record["env_sha256"] or tunnels != record["tunnels_sha256"]:
        raise Hold("PROTECTED_NODE_STATE_CHANGED")

def _expected_states(manifest_bytes: bytes | None) -> dict[str, str]:
    engines = {}
    if manifest_bytes is not None:
        try:
            doc = json.loads(manifest_bytes)
        except (ValueError, UnicodeError, TypeError) as exc:
            raise Hold("UNTRUSTED_ENGINE_MANIFEST") from exc
        if (not isinstance(doc, dict) or set(doc) != {"schema", "engines"}
                or doc.get("schema") != 1 or not isinstance(doc.get("engines"), dict)
                or not set(doc["engines"]).issubset({"backhaul", "frp"})):
            raise Hold("UNTRUSTED_ENGINE_MANIFEST")
        engines = doc["engines"]
    return {name: ("ready" if name in engines else "not-installed")
            for name in ENGINE_NAMES}


# A retained, signed RC7 Node may ALREADY bundle the exact official Backhaul
# executable at the path consumed by Smite's managed engine inventory. If so,
# a future manifest-only transaction may avoid recreating smite-node entirely.
# This review DOES NOT enroll it, write a manifest or declare live readiness.
IN_PLACE_BINARY_PROBE = r'''
import hashlib,os,stat,sys
expected=os.environ.get("UOPTI_EXPECTED_BACKHAUL_SHA256","")
path="/usr/local/bin/backhaul"
try:
    original=os.lstat(path)
    if (not stat.S_ISREG(original.st_mode) or original.st_uid!=0
            or original.st_nlink!=1 or not original.st_mode&0o111
            or original.st_mode&0o022 or not 100000<original.st_size<48*1024*1024):
        raise RuntimeError("not trusted")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        actual=os.fstat(fd)
        if (actual.st_dev,actual.st_ino,actual.st_size)!=(
                original.st_dev,original.st_ino,original.st_size):
            raise RuntimeError("raced binary")
        digest=hashlib.sha256()
        while True:
            chunk=os.read(fd,65536)
            if not chunk: break
            digest.update(chunk)
    finally:
        os.close(fd)
    if digest.hexdigest()!=expected:
        raise RuntimeError("not official")
except (OSError,RuntimeError):
    sys.exit(2)
print("OFFICIAL_BUNDLED_BACKHAUL_BYTES=PASS")
'''


def _retained_container_fingerprint(doc: dict) -> tuple:
    """Pin actual running container identity, image and immutable mounts.

    Docker metadata is NOT an externally authenticated image signature. It
    only lets us ensure a read-only probe did not observe a recreated Node.
    """
    try:
        ident = doc["Id"]
        image = doc["Image"]
        started = doc["State"]["StartedAt"]
        mounts = doc["Mounts"]
        if (not isinstance(ident,str) or not re.fullmatch("[a-f0-9]{64}",ident)
                or not isinstance(image,str) or not re.fullmatch("sha256:[a-f0-9]{64}",image)
                or not isinstance(started,str) or not started
                or doc["State"]["Running"] is not True
                or not isinstance(mounts,list)):
            raise Hold("RETAINED_NODE_RUNTIME_IDENTITY_UNVERIFIED")
        # No credentials, mount contents or paths leave the process.
        return (ident,image,started,
                _sha(json.dumps(mounts,sort_keys=True).encode()))
    except (KeyError,TypeError,ValueError) as exc:
        raise Hold("RETAINED_NODE_RUNTIME_IDENTITY_UNVERIFIED") from exc


def _retained_review_pending_recovery(paths: Paths) -> str | None:
    """Read only: deny an active FRP/Backhaul writer's durable intent.

    The shared engine lock is advisory; all linked RC7 recovery markers must
    be absent both before Docker inspection and after the pure paired plan.
    lexists also refuses dangling symlinks and never follows their target.
    """
    if os.path.lexists(paths.state / "retained-rc7-cleanup.json"):
        return "RETAINED_CLEANUP_RECOVERY_REQUIRED"
    if os.path.lexists(paths.state / "retained-rc7.json"):
        return "RETAINED_JOURNAL_REQUIRES_LOCKED_REVIEW"
    manifest = paths.node / "config/engine-state/engines.json"
    for pending in (
        _journal(paths),
        paths.frp_state / "record.next",
        manifest.with_name("engines.json.rc7-next"),
        manifest.with_name("engines.json.rc7-rollback-next"),
    ):
        if os.path.lexists(pending):
            return "COMPETING_RECOVERY_REQUIRED"
    return None


def _retained_live_signed_witness(*, role: str, expected_node_image: str,
                                  paths: Paths = Paths()) -> str:
    """Stable, role-scoped LIVE Node/FRP witness for future retained writer.

    This is a read-only building block, NOT a live writer admission token.
    It does not contact the peer, attest provider backups, sign a release
    or authorize any real transaction. Signed local Agent GETs consume replay
    nonces; no Node, FRP, broker, routing or engine bytes are written here.
    """
    if (paths != Paths() or os.geteuid() != 0
            or role not in ("ir", "foreign")
            or IMAGE.fullmatch(expected_node_image) is None):
        raise Hold("RETAINED_LIVE_WITNESS_SCOPE_UNTRUSTED")
    try:
        frp = _load("uopti_retained_live_frp", "smite-rc7-frp-enrollment.py")
        control = _load("uopti_retained_live_bh", "smite-managed-backhaul-control.py")
        doc = frp.node_details()
        if doc.get("role") != role or doc.get("state") != "COMMITTED":
            raise Hold("RETAINED_LIVE_ROLE_UNVERIFIED")
        node = frp.rt.inspect_container("smite-node")
        if (node.get("Name") != "/smite-node"
                or node.get("Config", {}).get("Image") != expected_node_image):
            raise Hold("RETAINED_LIVE_IMAGE_PIN_CHANGED")
        identity = _retained_container_fingerprint(node)
        mounts = node.get("Mounts")
        if not isinstance(mounts, list):
            raise Hold("RETAINED_LIVE_MOUNTS_UNTRUSTED")
        matched = [mount for mount in mounts if
                   isinstance(mount, dict)
                   and mount.get("Destination") == "/var/lib/smite-node"]
        if (len(matched) != 1 or matched[0].get("Type") != "volume"
                or matched[0].get("Driver") != "local"
                or not isinstance(matched[0].get("Source"), str)):
            raise Hold("RETAINED_LIVE_NODE_VOLUME_UNTRUSTED")
        data = Path(matched[0]["Source"])
        if (not data.is_absolute() or data.is_symlink()
                or not data.is_dir()):
            raise Hold("RETAINED_LIVE_NODE_VOLUME_UNTRUSTED")
        # Exact bytes of the persisted FRP registry are read locally,
        # without printing any tunnel IDs, tokens, proxy ports or hosts.
        # A corrupt or concurrently written registry must fail closed.
        registry = data / "tunnels.json"
        saved = pair._pair_read_private(registry, limit=262144)
        frp.rt.signed_probe()
        footprint = admission.host.frp_process_footprint()
        if role == "ir":
            if (footprint.get("FRPS_PROCESS_LOCAL") != "OBSERVED_UNATTESTED"
                    or SHA.fullmatch(
                        footprint.get("FRPS_INSTANCE_SHA256", "")) is None):
                raise Hold("RETAINED_LIVE_FRPS_PROCESS_UNVERIFIED")
            owner = frp.signed_owner_inventory()
            if not isinstance(owner, str) or SHA.fullmatch(owner) is None:
                raise Hold("RETAINED_LIVE_SIGNED_OWNER_UNVERIFIED")
            broker = admission.host.broker_socket_footprint()
            if (broker.get("BROKER_SOCKET_LOCAL") != "PRESENT_UNATTESTED"
                    or SHA.fullmatch(
                        broker.get("BROKER_SOCKET_ID_SHA256", "")) is None):
                raise Hold("RETAINED_LIVE_BROKER_UNVERIFIED")
            role_proof = (owner, footprint["FRPS_INSTANCE_SHA256"],
                          broker["BROKER_SOCKET_ID_SHA256"])
        else:
            if (footprint.get("FRPC_PROCESS_LOCAL") != "OBSERVED_UNATTESTED"
                    or SHA.fullmatch(
                        footprint.get("FRPC_INSTANCE_SHA256", "")) is None):
                raise Hold("RETAINED_LIVE_FRPC_PROCESS_UNVERIFIED")
            children = control._rc7_foreign_saved_child_ids(frp)
            if not children:
                raise Hold("RETAINED_LIVE_FOREIGN_CHILDREN_MISSING")
            signed_children = control._rc7_foreign_signed_instances(frp, children)
            if (len(signed_children) != len(children)
                    or not all(type(s) is str and SHA.fullmatch(s)
                               for s in signed_children)):
                raise Hold("RETAINED_LIVE_SIGNED_CHILDREN_UNVERIFIED")
            role_proof = (footprint["FRPC_INSTANCE_SHA256"],
                          tuple(signed_children),
                          _sha(json.dumps(children, sort_keys=True).encode()))
        # A signed read can itself span a Node restart or FRP process
        # change. Repeat the local immutable/process evidence afterward.
        after = frp.rt.inspect_container("smite-node")
        if (_retained_container_fingerprint(after) != identity
                or after.get("Config", {}).get("Image") != expected_node_image
                or admission.host.frp_process_footprint() != footprint
                or pair._pair_read_private(registry, limit=262144) != saved):
            raise Hold("RETAINED_LIVE_NODE_OR_FRP_DRIFT")
        if role == "ir" and admission.host.broker_socket_footprint() != broker:
            raise Hold("RETAINED_LIVE_BROKER_DRIFT")
        payload = [role, expected_node_image, identity, _sha(saved), role_proof]
        return _sha(json.dumps(payload, sort_keys=True).encode())
    except Hold:
        raise
    except Exception as exc:
        # Local exceptions and Docker output might include secrets.
        raise Hold("RETAINED_LIVE_SIGNED_WITNESS_UNVERIFIED") from exc


def review_in_place_binary(*, expected_node_image: str, arch: str,
                           paths: Paths = Paths(), runner=subprocess.run,
                           signed_pair_manifest: Path | None = None,
                           signed_pair_manifest_sha256: str | None = None,
                           signed_pair_source_sha: str | None = None,
                           signed_pair_publish_ref: str | None = None,
                           signed_pair_trusted_root: Path | None = None) -> dict[str,str]:
    """Read-only feasibility of future Backhaul enrollment on an active FRP Node.

    It deliberately does NOT use _candidate/install/rollback: all of those
    demand empty tunnels and may recreate Node. No filesystem or Docker change,
    signed API request, restart, tunnel, service, or container copy is made.
    """
    report = {
        "RETAINED_NODE_BACKHAUL_BINARY": "UNVERIFIED",
        "IN_PLACE_MANIFEST_TRANSACTION": "NOT_IMPLEMENTED",
        "SIGNED_RUNTIME_PRESERVATION": "NOT_PROVEN",
        "NODE_RECREATE": "FORBIDDEN",
        "HOST_TRANSACTION_AND_ROLLBACK": "NOT_IMPLEMENTED",
        "INSTALL_ALLOWED": "NO",
        "ACTIVATION_GATE": "HOLD",
    }
    def hold(reason: str):
        report["REASON"] = reason
        return report
    if IMAGE.fullmatch(expected_node_image) is None:
        return hold("EXTERNAL_NODE_IMAGE_PIN_REQUIRED")
    if arch not in package.OFFICIAL_BINARY_SHA256:
        return hold("OFFICIAL_BACKHAUL_ARCH_REQUIRED")
    try:
        with _read_only_engine_lock(paths.lock):
            # A crash after terminal unlink can leave only the durable cleanup
            # seal. Never present the paired manifest as a clean install candidate
            # until its independent locked recovery has completed.
            pending = _retained_review_pending_recovery(paths)
            if pending is not None:
                return hold(pending)
            before = admission.host.read_only_docker_inspect(runner=runner)
            identity = _retained_container_fingerprint(before)
            review = admission.report(
                "backhaul", paths.node, runtime=before,
                expected_node_image=expected_node_image,
                signed_pair_manifest=signed_pair_manifest,
                signed_pair_manifest_sha256=signed_pair_manifest_sha256,
                signed_pair_source_sha=signed_pair_source_sha,
                signed_pair_publish_ref=signed_pair_publish_ref,
                signed_pair_trusted_root=signed_pair_trusted_root,
            )
            report["SIGNED_REGISTRY_PAIR_PROOF"] = review.get(
                "SIGNED_REGISTRY_PAIR_PROOF","UNVERIFIED")
            # An *existing* protected FRP registry is the reason we explore
            # in-place access. Keep original admission's no-recreate HOLD intact.
            if (review.get("NODE_CONTAINER")!="RUNNING_REVIEWED_IMAGE"
                    or review.get("CORE_PROFILE")!="MANAGED_STRICT"
                    or review.get("SAVED_TUNNELS")!="EXISTING_DO_NOT_RESTART"
                    or review.get("TARGET_ENGINE")!="NOT_INSTALLED"
                    or review.get("OTHER_ENGINE")!="ENROLLED_UNVERIFIED"
                    or review.get("INSTALL_ALLOWED")!="NO"
                    or review.get("ACTIVATION_GATE")!="HOLD"
                    or review.get("OTHER_ENGINE_ACTION")!="NEVER_MODIFY"):
                return hold("RETAINED_FRP_HOST_ADMISSION_HOLD")
            # Don't equate a Docker digest with an immutable signed artifact.
            # This may still classify candidate binary bytes for a later audit.
            env_before = _sha(_read(paths.node/".env",16384))
            compose_before = _sha(_read(paths.node/"docker-compose.yml",131072))
            manifest_before = _sha(_read(
                paths.node/"config/engine-state/engines.json",8192))
            # The shared lock serializes trusted writers, but is advisory.
            # Also pin the exact FRP receipt bytes against out-of-band drift
            # during the Docker and signed-pair observations. Keep unsigned
            # feasibility reviews compatible with a missing receipt.
            receipt_path = paths.frp_state / "record.json"
            receipt_before = (
                _sha(pair._pair_read_private(receipt_path))
                if report["SIGNED_REGISTRY_PAIR_PROOF"] == "COSIGN_VERIFIED"
                else None
            )
            digest = package.OFFICIAL_BINARY_SHA256[arch]
            argv = ["docker","exec","-i","--env",
                    "UOPTI_EXPECTED_BACKHAUL_SHA256="+digest,
                    "smite-node","python","-B","-"]
            try:
                result = runner(argv,input=IN_PLACE_BINARY_PROBE,
                                capture_output=True,text=True,timeout=25,check=False)
            except (OSError,subprocess.TimeoutExpired):
                return hold("RETAINED_NODE_BINARY_READ_UNAVAILABLE")
            if (result.returncode!=0
                    or result.stdout.strip()!="OFFICIAL_BUNDLED_BACKHAUL_BYTES=PASS"):
                return hold("RETAINED_NODE_BINARY_ABSENT_OR_HASH_DRIFT")
            after = admission.host.read_only_docker_inspect(runner=runner)
            if _retained_container_fingerprint(after)!=identity:
                return hold("RETAINED_NODE_RECREATED_DURING_REVIEW")
            verify = admission.report(
                "backhaul", paths.node, runtime=after,
                expected_node_image=expected_node_image,
                signed_pair_manifest=signed_pair_manifest,
                signed_pair_manifest_sha256=signed_pair_manifest_sha256,
                signed_pair_source_sha=signed_pair_source_sha,
                signed_pair_publish_ref=signed_pair_publish_ref,
                signed_pair_trusted_root=signed_pair_trusted_root,
            )
            if review != verify:
                return hold("RETAINED_ADMISSION_CHANGED_DURING_REVIEW")
            if (_sha(_read(paths.node/".env",16384))!=env_before
                    or _sha(_read(paths.node/"docker-compose.yml",131072))!=compose_before
                    or _sha(_read(paths.node/"config/engine-state/engines.json",8192))
                        !=manifest_before):
                return hold("NODE_CONFIGURATION_CHANGED_DURING_REVIEW")
            # A non-cooperating writer can bypass flock. Never return a
            # positive paired preview if a journal or cleanup seal appeared
            # while signed inventory / binary proof was being checked.
            pending = _retained_review_pending_recovery(paths)
            if pending is not None:
                return hold(pending)
            report["RETAINED_NODE_BACKHAUL_BINARY"] = "OFFICIAL_EXECUTABLE_SHA256_MATCH"
            if report["SIGNED_REGISTRY_PAIR_PROOF"] != "COSIGN_VERIFIED":
                return hold("SIGNED_IMAGE_AND_IN_PLACE_ROLLBACK_STILL_REQUIRED")
            manifest = paths.node / "config/engine-state/engines.json"
            for directory in (manifest.parent, paths.frp_state):
                if directory.resolve(strict=True) != directory:
                    return hold("RETAINED_DIRECTORY_UNTRUSTED")
                _dir(directory)
            baseline = pair._pair_read_private(manifest)
            if _sha(baseline) != manifest_before:
                return hold("NODE_CONFIGURATION_CHANGED_DURING_REVIEW")
            # A receipt edit that remains syntactically valid and binds the
            # same manifest is still unauthorized drift for this observation.
            receipt_now = pair._pair_read_private(receipt_path)
            if _sha(receipt_now) != receipt_before:
                return hold("RETAINED_FRP_RECEIPT_CHANGED_DURING_REVIEW")
            role = {"IR": "ir", "KH": "foreign"}.get(review.get("NODE_ROLE"))
            pair._pair_expected_transition(baseline, receipt_now,
                digest, role=role)
            if (_sha(pair._pair_read_private(receipt_path)) != receipt_before
                    or _sha(pair._pair_read_private(manifest)) != manifest_before):
                return hold("RETAINED_PAIR_CHANGED_DURING_REVIEW")
            pending = _retained_review_pending_recovery(paths)
            if pending is not None:
                return hold(pending)
            report["IN_PLACE_MANIFEST_TRANSACTION"] = "PAIR_PLAN_VERIFIED_READ_ONLY"
            return hold("INDEPENDENT_DEPLOYMENT_APPROVAL_AND_RUNTIME_PROOF_REQUIRED")
    except (Hold,admission.host.GateHold,OSError,UnicodeError,ValueError,
            RuntimeError,TypeError):
        return hold("RETAINED_NODE_PREVIEW_UNVERIFIED")


PROBE = r'''
import json, os, secrets, urllib.error, urllib.request
from app.agent_auth import read_identity
from app.node_auth import sign_request

expected=json.loads(os.environ["UOPTI_EXPECTED_ENGINES"])
assert set(expected)=={"backhaul","frp","gost","rathole","chisel"}
node_id, secret=read_identity("/etc/smite-node/identity/node-identity.json")

def call(target, headers=None):
    req=urllib.request.Request("http://127.0.0.1:8888"+target, method="GET",
                               headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()

target="/api/agent/engines"
assert call(target)[0]==401
headers=sign_request(secret=secret,node_id=node_id,method="GET",target=target,body=b"")
status, body=call(target,headers); assert status==200
assert call(target,headers)[0]==401
again=sign_request(secret=secret,node_id=node_id,method="GET",target=target,body=b"")
status, body2=call(target,again); assert status==200
assert json.loads(body2)==json.loads(body)
wrong=bytearray(secret); wrong[0]^=255
bad=sign_request(secret=bytes(wrong),node_id=node_id,method="GET",target=target,body=b"")
assert call(target,bad)[0]==401
inventory=json.loads(body)
assert inventory=={"mode":"managed","engines":expected}
status_target="/api/agent/status"
signed=sign_request(secret=secret,node_id=node_id,method="GET",target=status_target,body=b"")
status, payload=call(status_target,signed); assert status==200
status_doc=json.loads(payload)
assert status_doc=={"status":"ok","active_tunnels":0,"tunnels":[]}
print("UOPTI_SIGNED_RUNTIME=PASS")
'''


def _no_frp_in_manifest(raw: bytes | None) -> None:
    """Refuse to recreate a Node where FRP is/was explicitly enrolled.

    Must be checked against both the journaled prior manifest and the current
    manifest *before* modifying any Node-managed bytes. This function is
    intentionally stricter than the disposable-host candidate preparer.
    """
    if raw is None:
        return
    def reject_duplicate_keys(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise Hold("FRP_RECREATE_MANIFEST_UNTRUSTED")
            values[key] = value
        return values
    try:
        record = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise Hold("FRP_RECREATE_MANIFEST_UNTRUSTED") from exc
    if (not isinstance(record, dict)
            or set(record) != {"schema", "engines"}
            or type(record["schema"]) is not int or record["schema"] != 1
            or not isinstance(record["engines"], dict)
            or not set(record["engines"]).issubset(set(ENGINE_NAMES))):
        raise Hold("FRP_RECREATE_MANIFEST_UNTRUSTED")
    if "frp" in record["engines"]:
        raise Hold("ENROLLED_FRP_NODE_RECREATE_FORBIDDEN")


def _assert_no_frp_before_recreate(paths: Paths, *,
                                   previous_manifest: bytes | None = None) -> None:
    """Defense-in-depth guard across install, recovery and rollback.

    A missing manifest never proves that a currently running FRPC/FRPS is
    harmless. Refuse unknown /proc evidence; never terminate a process.
    This check is not an attestation and cannot defeat external races.
    """
    _no_frp_in_manifest(previous_manifest)
    manifest = paths.node / "config" / "engine-state" / "engines.json"
    current = _read(manifest, 8192) if manifest.exists() or manifest.is_symlink() else None
    _no_frp_in_manifest(current)
    try:
        evidence = admission.host.frp_process_footprint()
    except (OSError, ValueError, RuntimeError, AttributeError) as exc:
        raise Hold("FRP_PROCESS_PRESENCE_OR_UNVERIFIED") from exc
    if (not isinstance(evidence, dict)
            or evidence.get("FRPC_PROCESS_LOCAL") != "NOT_OBSERVED"
            or evidence.get("FRPS_PROCESS_LOCAL") != "NOT_OBSERVED"
            or evidence.get("FRPC_INSTANCE_SHA256") != "ABSENT"
            or evidence.get("FRPS_INSTANCE_SHA256") != "ABSENT"):
        raise Hold("FRP_PROCESS_PRESENCE_OR_UNVERIFIED")


def _run_restart(paths: Paths, runner=subprocess.run) -> None:
    # Recheck directly before the only container recreation.
    _assert_no_frp_before_recreate(paths)
    argv = ["docker", "compose", "-f", str(paths.node / "docker-compose.yml"),
            "up", "-d", "--no-build", "--force-recreate", "--no-deps", "smite-node"]
    try:
        result = runner(argv, capture_output=True, text=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("NODE_RECREATE_UNAVAILABLE") from exc
    if result.returncode != 0:
        raise Hold("NODE_RECREATE_FAILED")

def _signed_probe(expected: dict[str, str], runner=subprocess.run) -> None:
    value = json.dumps(expected, sort_keys=True, separators=(",", ":"))
    argv = ["docker", "exec", "-i", "--env", "UOPTI_EXPECTED_ENGINES=" + value,
            "smite-node", "python", "-B", "-"]
    try:
        result = runner(argv, input=PROBE, capture_output=True, text=True,
                        timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("SIGNED_RUNTIME_PROBE_UNAVAILABLE") from exc
    if result.returncode != 0 or result.stdout.strip() != "UOPTI_SIGNED_RUNTIME=PASS":
        raise Hold("SIGNED_RUNTIME_PROBE_FAILED")

def _candidate(paths: Paths, stage: Path, expected_image: str,
               expected_plan: str, runtime: dict | None) -> tuple[dict, bytes, bytes, bytes, bytes | None]:
    if IMAGE.fullmatch(expected_image) is None or SHA.fullmatch(expected_plan) is None:
        raise Hold("INVALID_EXTERNAL_IMAGE_OR_PLAN_PIN")
    status = admission.report(
        "backhaul", paths.node, runtime=runtime,
        expected_node_image=expected_image,
    )
    if (status.get("LOCAL_PREFLIGHT") != "PASS_LOCAL_ONLY_INCOMPLETE"
            or status.get("TARGET_ENGINE") != "NOT_INSTALLED"
            or status.get("SAVED_TUNNELS") != "ZERO"
            or status.get("INSTALL_ALLOWED") != "NO"
            or status.get("ACTIVATION_GATE") != "HOLD"):
        raise Hold("HOST_ADMISSION_INCOMPLETE")
    reviewed = plan.review(
        "backhaul", paths.node, stage, staging_root=paths.staging,
        host_status=status,
    )
    if (reviewed.get("STAGE_ADMISSION") != "VERIFIED_PREVIEW_ONLY"
            or reviewed.get("PLAN_SHA256_NOT_AUTHORIZATION") != expected_plan
            or reviewed.get("ARTIFACT_PROVENANCE") != "OFFICIAL_BACKHAUL_ARCHIVE_VERIFIED"):
        raise Hold("REVIEWED_HOST_PLAN_MISMATCH")
    raw_compose = _read(paths.node / "docker-compose.yml", 131072)
    raw_binary = _read(stage / "backhaul.bin", MAX_BINARY)
    raw_manifest = _read(stage / "engines.candidate.json", 8192)
    manifest_path = paths.node / "config" / "engine-state" / "engines.json"
    old_manifest = (_read(manifest_path, 8192)
                    if manifest_path.exists() or manifest_path.is_symlink() else None)
    # Separate pre-journal safety check. An enrolled FRP means this executor
    # is the wrong architecture even when the saved-tunnels list is empty.
    _assert_no_frp_before_recreate(paths, previous_manifest=old_manifest)
    if _sha(raw_binary) != reviewed["BINARIES_SHA256"][0]:
        raise Hold("CANDIDATE_BINARY_DRIFT")
    if _sha(raw_manifest) != reviewed["CANDIDATE_MANIFEST_SHA256"]:
        raise Hold("CANDIDATE_MANIFEST_DRIFT")
    marker = b"      - ./config:/etc/smite-node\n"
    if raw_compose.count(marker) != 1 or b"/usr/local/bin/backhaul" in raw_compose:
        raise Hold("UNSAFE_COMPOSE_FOR_BACKHAUL")
    mount = ("      - " + str(paths.binary) + ":/usr/local/bin/backhaul:ro\n").encode()
    new_compose = raw_compose.replace(marker, marker + mount, 1)
    return status, raw_compose, new_compose, raw_binary, old_manifest

def _prepare_journal(paths: Paths, role: str, expected_image: str,
                     expected_plan: str, old_compose: bytes, new_compose: bytes,
                     old_manifest: bytes | None, new_manifest: bytes,
                     binary: bytes) -> dict:
    if _journal(paths).exists() or _journal(paths).is_symlink():
        raise Hold("UNRESOLVED_HOST_JOURNAL")
    _mkdir_chain(paths.state, paths.state.parents[1])
    _dir(_journal(paths), create=True)
    compose_path = paths.node / "docker-compose.yml"
    manifest_path = paths.node / "config" / "engine-state" / "engines.json"
    env_hash, tunnels_hash = _protected(paths)
    _new(_journal(paths) / "compose.before", old_compose, 0o600)
    if old_manifest is not None:
        _new(_journal(paths) / "manifest.before", old_manifest, 0o600)
    record = {
        "schema": 1, "id": uuid.uuid4().hex, "role": role, "state": "PREPARED",
        "expected_node_image": expected_image, "plan_sha256": expected_plan,
        "compose_old": _sha(old_compose), "compose_new": _sha(new_compose),
        "compose_mode": stat.S_IMODE(compose_path.lstat().st_mode),
        "manifest_old": _sha(old_manifest) if old_manifest is not None else None,
        "manifest_new": _sha(new_manifest),
        "manifest_mode": (stat.S_IMODE(manifest_path.lstat().st_mode)
                          if old_manifest is not None else None),
        "binary_new": _sha(binary), "env_sha256": env_hash,
        "tunnels_sha256": tunnels_hash,
    }
    _new(_journal(paths) / "record.json",
         (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(),
         0o600)
    return record

def _archive(paths: Paths, record: dict, suffix: str) -> None:
    journal = _journal(paths)
    destination = paths.state / ("audit-" + record["id"] + "-" + suffix)
    if destination.exists() or destination.is_symlink():
        raise Hold("AUDIT_ARCHIVE_CONFLICT")
    os.replace(journal, destination)
    fd = os.open(paths.state, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def _rollback_locked(paths: Paths, record: dict, runner=subprocess.run,
                     *, archive: bool = True) -> None:
    # Fail BEFORE updating the journal or restoring/deleting any Node files.
    prior = (_read(_journal(paths) / "manifest.before", 8192)
             if record["manifest_old"] is not None else None)
    _assert_no_frp_before_recreate(paths, previous_manifest=prior)
    record["state"] = "RECOVERING"
    _write_record(paths, record)
    compose = paths.node / "docker-compose.yml"
    manifest = paths.node / "config" / "engine-state" / "engines.json"
    old_compose = _read(_journal(paths) / "compose.before", 131072)
    old_manifest = (_read(_journal(paths) / "manifest.before", 8192)
                    if record["manifest_old"] is not None else None)
    if _sha(old_compose) != record["compose_old"]:
        raise Hold("JOURNAL_COMPOSE_BACKUP_DRIFT")
    if old_manifest is not None and _sha(old_manifest) != record["manifest_old"]:
        raise Hold("JOURNAL_MANIFEST_BACKUP_DRIFT")
    current_compose = _read(compose, 131072)
    if _sha(current_compose) not in (record["compose_old"], record["compose_new"]):
        raise Hold("COMPOSE_EXTERNAL_DRIFT")
    if paths.binary.exists() or paths.binary.is_symlink():
        if _file_hash_or_none(paths.binary, MAX_BINARY) != record["binary_new"]:
            raise Hold("BACKHAUL_BINARY_EXTERNAL_DRIFT")
    if manifest.exists() or manifest.is_symlink():
        current_manifest = _file_hash_or_none(manifest, 8192)
        allowed = {record["manifest_new"]}
        if record["manifest_old"] is not None:
            allowed.add(record["manifest_old"])
        if current_manifest not in allowed:
            raise Hold("ENGINE_MANIFEST_EXTERNAL_DRIFT")
    if _sha(current_compose) != record["compose_old"]:
        _atomic(compose, old_compose, record["compose_mode"])
    if record["manifest_old"] is None:
        if manifest.exists():
            manifest.unlink()
    elif _file_hash_or_none(manifest, 8192) != record["manifest_old"]:
        _atomic(manifest, old_manifest, record["manifest_mode"])
    if paths.binary.exists():
        paths.binary.unlink()
    _check_protected(paths, record)
    _run_restart(paths, runner)
    _signed_probe(_expected_states(old_manifest), runner)
    _check_protected(paths, record)
    if archive:
        _archive(paths, record, "rolled-back")

def install(*, stage: Path, expected_node_image: str, expected_plan_sha256: str,
            snapshot_confirm: str, role_confirm: str, paths: Paths = Paths(),
            runtime: dict | None = None, runner=subprocess.run,
            inject: str = "") -> dict[str, str]:
    _deny_live_recreating_trial_paths(paths)
    if snapshot_confirm != SNAPSHOT_CONFIRM:
        raise Hold("SNAPSHOT_AND_CONSOLE_CONFIRMATION_REQUIRED")
    if os.geteuid() != 0 and paths == Paths():
        raise Hold("ROOT_REQUIRED")
    with _lock(paths.lock):
        status, old_compose, new_compose, binary, old_manifest = _candidate(
            paths, stage, expected_node_image, expected_plan_sha256, runtime
        )
        role = status.get("NODE_ROLE")
        if role not in ("IR", "KH") or role_confirm != "APPLY-BACKHAUL-" + role + "-TRIAL":
            raise Hold("ROLE_SPECIFIC_CONFIRMATION_REQUIRED")
        new_manifest = _read(stage / "engines.candidate.json", 8192)
        _signed_probe(_expected_states(old_manifest), runner)
        record = _prepare_journal(
            paths, role, expected_node_image, expected_plan_sha256,
            old_compose, new_compose, old_manifest, new_manifest, binary,
        )
        try:
            if inject == "after-journal":
                raise SimulatedCrash("after-journal")
            _mkdir_chain(paths.binary.parent, paths.binary.parents[3])
            _new(paths.binary, binary, 0o755)
            record["state"] = "WROTE_BINARY"; _write_record(paths, record)
            if inject == "after-binary":
                raise SimulatedCrash("after-binary")
            _atomic(paths.node / "docker-compose.yml", new_compose, record["compose_mode"])
            record["state"] = "WROTE_COMPOSE"; _write_record(paths, record)
            if inject == "after-compose":
                raise SimulatedCrash("after-compose")
            state_dir = paths.node / "config" / "engine-state"
            if not state_dir.exists():
                _dir(state_dir, create=True)
            manifest = state_dir / "engines.json"
            if old_manifest is None:
                _new(manifest, new_manifest, 0o600)
            else:
                _atomic(manifest, new_manifest, 0o600)
            record["state"] = "WROTE_MANIFEST"; _write_record(paths, record)
            if inject == "after-manifest":
                raise SimulatedCrash("after-manifest")
            _check_protected(paths, record)
            _run_restart(paths, runner)
            record["state"] = "NODE_RESTARTED"; _write_record(paths, record)
            if inject == "after-restart":
                raise SimulatedCrash("after-restart")
            _signed_probe(_expected_states(new_manifest), runner)
            _check_protected(paths, record)
            if (_sha(_read(paths.node / "docker-compose.yml", 131072)) != record["compose_new"]
                    or _file_hash_or_none(paths.binary, MAX_BINARY) != record["binary_new"]
                    or _file_hash_or_none(manifest, 8192) != record["manifest_new"]):
                raise Hold("POST_RESTART_ENGINE_DRIFT")
            record["state"] = "COMMITTED"; _write_record(paths, record)
            return {
                "TRIAL_INSTALL": "COMMITTED_SIGNED_RUNTIME_VERIFIED",
                "TUNNEL_APPLY": "NOT_PERFORMED",
                "PUBLIC_PORT_CHANGE": "NONE",
                "PRODUCTION_RELEASE": "HOLD",
            }
        except SimulatedCrash:
            raise
        except Exception as exc:
            try:
                _rollback_locked(paths, record, runner)
            except Exception as rollback_exc:
                raise Hold("INSTALL_FAILED_ROLLBACK_NEEDS_MANUAL_REVIEW") from rollback_exc
            raise Hold("INSTALL_FAILED_EXACT_ROLLBACK_PROVED") from exc

def rollback(*, expected_node_image: str, role_confirm: str,
             paths: Paths = Paths(), runner=subprocess.run) -> dict[str, str]:
    _deny_live_recreating_trial_paths(paths)
    if os.geteuid() != 0 and paths == Paths():
        raise Hold("ROOT_REQUIRED")
    with _lock(paths.lock):
        record = _record(paths)
        if expected_node_image != record["expected_node_image"]:
            raise Hold("EXPECTED_IMAGE_DOES_NOT_MATCH_JOURNAL")
        if role_confirm != "ROLLBACK-BACKHAUL-" + record["role"] + "-TRIAL":
            raise Hold("ROLE_SPECIFIC_CONFIRMATION_REQUIRED")
        _rollback_locked(paths, record, runner)
        return {
            "TRIAL_ROLLBACK": "EXACT_BYTES_AND_SIGNED_PRIOR_RUNTIME_VERIFIED",
            "PRODUCTION_RELEASE": "HOLD",
        }

def recover(*, expected_node_image: str, role_confirm: str,
            paths: Paths = Paths(), runner=subprocess.run) -> dict[str, str]:
    _deny_live_recreating_trial_paths(paths)
    if os.geteuid() != 0 and paths == Paths():
        raise Hold("ROOT_REQUIRED")
    with _lock(paths.lock):
        record = _record(paths)
        if record["state"] == "COMMITTED":
            raise Hold("COMMITTED_INSTALL_USE_EXPLICIT_ROLLBACK")
        if expected_node_image != record["expected_node_image"]:
            raise Hold("EXPECTED_IMAGE_DOES_NOT_MATCH_JOURNAL")
        if role_confirm != "RECOVER-BACKHAUL-" + record["role"] + "-TRIAL":
            raise Hold("ROLE_SPECIFIC_CONFIRMATION_REQUIRED")
        _rollback_locked(paths, record, runner)
        return {
            "INTERRUPTED_TRIAL_RECOVERY": "ROLLED_BACK_AND_SIGNED_PRIOR_RUNTIME_VERIFIED",
            "PRODUCTION_RELEASE": "HOLD",
        }

def main() -> int:
    p = argparse.ArgumentParser(
        description="Backhaul disposable-host executor; explicit trial only, no tunnel Apply")
    p.add_argument("action", choices=("install", "rollback", "recover", "review-in-place"))
    p.add_argument("--stage", type=Path)
    p.add_argument("--arch", choices=tuple(package.OFFICIAL_BINARY_SHA256))
    p.add_argument("--signed-pair-manifest", type=Path)
    p.add_argument("--signed-pair-manifest-sha256")
    p.add_argument("--signed-pair-source-sha")
    p.add_argument("--signed-pair-publish-ref")
    p.add_argument("--signed-pair-trusted-root", type=Path)
    p.add_argument("--expected-node-image", required=True)
    p.add_argument("--expected-plan-sha256")
    p.add_argument("--confirm-snapshot-and-console")
    p.add_argument("--confirm-role", required=True)
    args = p.parse_args()
    try:
        if os.geteuid() != 0:
            raise Hold("ROOT_REQUIRED")
        if args.action == "review-in-place":
            if args.arch is None or args.confirm_role != "REVIEW-BACKHAUL-IN-PLACE":
                raise Hold("IN_PLACE_REVIEW_ARCH_AND_CONFIRMATION_REQUIRED")
            result = review_in_place_binary(
                expected_node_image=args.expected_node_image,arch=args.arch,
                signed_pair_manifest=args.signed_pair_manifest,
                signed_pair_manifest_sha256=args.signed_pair_manifest_sha256,
                signed_pair_source_sha=args.signed_pair_source_sha,
                signed_pair_publish_ref=args.signed_pair_publish_ref,
                signed_pair_trusted_root=args.signed_pair_trusted_root,
            )
        elif args.action == "install":
            if args.stage is None or args.expected_plan_sha256 is None:
                raise Hold("STAGE_AND_PLAN_REQUIRED")
            result = install(
                stage=args.stage,
                expected_node_image=args.expected_node_image,
                expected_plan_sha256=args.expected_plan_sha256,
                snapshot_confirm=args.confirm_snapshot_and_console or "",
                role_confirm=args.confirm_role,
            )
        elif args.action == "rollback":
            result = rollback(
                expected_node_image=args.expected_node_image,
                role_confirm=args.confirm_role,
            )
        else:
            result = recover(
                expected_node_image=args.expected_node_image,
                role_confirm=args.confirm_role,
            )
        for key, value in result.items():
            print(f"{key}={value}")
        return 2 if args.action == "review-in-place" else 0
    except SimulatedCrash:
        print("HOLD: INTERRUPTED_TRIAL_JOURNAL_REQUIRES_RECOVER", file=sys.stderr)
        return 91
    except (Hold, OSError, ValueError, RuntimeError, UnicodeError) as exc:
        reason = str(exc)
        if re.fullmatch(r"[A-Z0-9_]{1,96}", reason) is None:
            reason = "HOST_TRIAL_FAILED"
        print("HOLD: " + reason, file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
