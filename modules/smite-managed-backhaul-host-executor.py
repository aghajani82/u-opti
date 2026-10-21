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

class Hold(RuntimeError):
    pass

class SimulatedCrash(RuntimeError):
    pass

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

def _mkdir_chain(path: Path, anchor: Path) -> None:
    if not anchor.is_absolute() or not path.is_absolute() or anchor not in path.parents:
        raise Hold("UNSAFE_MANAGED_DIRECTORY")
    _dir(anchor)
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
    if path.is_symlink() or not path.parent.is_dir():
        raise Hold("UNSAFE_LOCK_PATH")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid():
            raise Hold("UNSAFE_LOCK_FILE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold("ANOTHER_ENGINE_TRANSACTION_ACTIVE") from exc
        yield
    finally:
        os.close(fd)

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

def _run_restart(paths: Paths, runner=subprocess.run) -> None:
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
    p.add_argument("action", choices=("install", "rollback", "recover"))
    p.add_argument("--stage", type=Path)
    p.add_argument("--expected-node-image", required=True)
    p.add_argument("--expected-plan-sha256")
    p.add_argument("--confirm-snapshot-and-console")
    p.add_argument("--confirm-role", required=True)
    args = p.parse_args()
    try:
        if os.geteuid() != 0:
            raise Hold("ROOT_REQUIRED")
        if args.action == "install":
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
        return 0
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
