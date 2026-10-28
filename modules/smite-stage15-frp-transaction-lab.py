#!/usr/bin/env python3
"""Stage15 FRP dual-binary signed-Compose transaction DISPOSABLE CI LAB ONLY.

Exercises journal-before-write, exact rollback, crash recovery and simulated
signed/replay acceptance against a synthetic Stage15 filesystem. This MUST NOT
be used as a host installer: no Docker invocation, Nginx, network, ports, or
live Node recreation. The source Stage15 image still ships legacy FRP 0.65.
Only a separately audited real-host executor may adopt these invariants.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
MARKER = b"UOPTI-STAGE15-SIGNED-FRP-LAB-V1\n"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
NAMES = ("frpc", "frps")
MAX_FILE = 262144
MAX_BINARY = 48 * 1024 * 1024


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise Hold("REVIEWED_HELPER_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


frp = load("stage15_txn_official_candidate", "smite-managed-frp.py")
plan = load("stage15_txn_signed_compose", "smite-stage15-frp-compose-plan.py")


class Hold(RuntimeError):
    pass


class Interrupted(RuntimeError):
    pass


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require(ok: bool, reason: str):
    if not ok:
        raise Hold(reason)


def regular(path: Path, limit: int = MAX_FILE) -> bytes:
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid()
            and st.st_nlink == 1 and not stat.S_IMODE(st.st_mode) & 0o022
            and 0 <= st.st_size <= limit, "UNTRUSTED_LAB_FILE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as src:
        live = os.fstat(src.fileno())
        require((st.st_dev, st.st_ino) == (live.st_dev, live.st_ino),
                "LAB_FILE_READ_RACE")
        value = src.read(limit + 1)
    require(len(value) <= limit, "LAB_FILE_TOO_LARGE")
    return value


def private_dir(path: Path):
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid()
            and stat.S_IMODE(st.st_mode) == 0o700 and not path.is_symlink(),
            "LAB_PRIVATE_DIRECTORY_REQUIRED")


def gate(root: Path):
    """Never write outside a private, positively marked PR runner subtree."""
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
            and os.environ.get("GITHUB_REPOSITORY") == "aghajani82/u-opti",
            "PR_CI_ONLY")
    runner = os.environ.get("RUNNER_TEMP", "")
    require(bool(runner) and root.is_absolute() and not root.is_symlink()
            and root != Path(runner) and root.parent == Path(runner)
            and root.name.startswith("uopti-stage15-frp-"),
            "UNREVIEWED_LAB_ROOT")
    private_dir(root)
    require(regular(root / "EXPERIMENTAL-LAB", 128) == MARKER,
            "LAB_MARKER_REQUIRED")
    private_dir(root / "node")
    private_dir(root / "node" / "config")
    private_dir(root / "stages")
    private_dir(root / "protected")


def paths(root: Path) -> dict[str, Path]:
    return {
        "base": root / "node" / "docker-compose.yml",
        "signed": root / "node" / "docker-compose.security-candidate.yml",
        "overlay": root / "node" / "docker-compose.frp-stage15.yml",
        "env": root / "node" / ".env",
        "manifest": root / "node" / "config" / "engine-state" / "engines.json",
        "frpc": root / "installed" / "frp" / "frpc",
        "frps": root / "installed" / "frp" / "frps",
        "identity": root / "protected" / "identity.json",
        "replay": root / "protected" / "replay.db",
        "journal": root / "frp-signed-journal",
    }


def protected(f: dict[str, Path]) -> dict[str, str]:
    # Replay nonces may append; identity of the durable inode is what must
    # survive, not a stale copy of a live SQLite database.
    st = f["replay"].lstat()
    regular(f["replay"], MAX_FILE)
    return {"identity": sha(regular(f["identity"], 8192)),
            "replay_inode": f"{st.st_dev}:{st.st_ino}",
            "signed": sha(regular(f["signed"], 131072)),
            "env": sha(regular(f["env"], 8192))}


def verify_protected(f, prior):
    require(protected(f) == prior, "SIGNED_IDENTITY_REPLAY_DRIFT")


def write_new(path: Path, data: bytes, mode: int = 0o600):
    require(not path.exists() and not path.is_symlink(), "LAB_TARGET_EXISTS")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as dest:
        os.fchmod(dest.fileno(), mode)
        dest.write(data)
        dest.flush()
        os.fsync(dest.fileno())


def mkdir(path):
    require(not path.exists() and not path.is_symlink(), "LAB_TARGET_EXISTS")
    path.mkdir(mode=0o700)
    private_dir(path)


def fsync_dir(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def lock(root: Path):
    gate(root)
    lockfile = root / ".smite-engine-transaction.lock"
    fd = os.open(lockfile, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid()
                and stat.S_IMODE(st.st_mode) == 0o600 and st.st_nlink == 1,
                "LAB_LOCK_UNTRUSTED")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold("ENGINE_TXN_LOCK_BUSY") from exc
        yield
    finally:
        os.close(fd)


def candidate(root: Path, stage: Path, *, verify_official=frp.verify):
    gate(root)
    f = paths(root)
    require(stage.parent == root / "stages" and not stage.is_symlink(),
            "STAGE_OUTSIDE_CI_LAB")
    private_dir(stage)
    require(verify_official(stage), "OFFICIAL_FRP_PAIR_NOT_VERIFIED")
    require(not f["journal"].exists() and not f["journal"].is_symlink()
            and not f["overlay"].exists() and not f["overlay"].is_symlink()
            and all(not f[n].exists() and not f[n].is_symlink() for n in NAMES),
            "STAGE15_PREVIOUS_FRP_TRANSACTION")
    env = regular(f["env"], 8192).decode()
    require(all(env.count(t) == 1 for t in (
        "SMITE_NODE_PANEL_AUTH_MODE=signed",
        "SMITE_AGENT_AUTH_MODE=strict",
        "SMITE_ENGINE_INVENTORY_MODE=managed",
    )), "NOT_A_SIGNED_STAGE15_NODE")
    require("SMITE_FRP_STANDARD_WSS=1" not in env,
            "WSS_NOT_SEPARATELY_AUTHORIZED")
    base = regular(f["base"], 131072)
    signed = regular(f["signed"], 131072)
    require(b"smite-node:stage15-local" in base
            and b"127.0.0.1" in base and b"8888" in base
            and b"SMITE_AGENT_AUTH_MODE" in signed,
            "UNRECOGNIZED_STAGE15_COMPOSE")
    old = (regular(f["manifest"], 8192)
           if f["manifest"].exists() or f["manifest"].is_symlink() else None)
    current = json.loads(old) if old is not None else {
        "schema": 1, "engines": {}
    }
    require(isinstance(current, dict) and set(current) == {"schema", "engines"}
            and current["schema"] == 1
            and isinstance(current["engines"], dict)
            and "frp" not in current["engines"], "ENGINE_INVENTORY_DRIFT")
    staged = {name: regular(stage / f"{name}.bin", MAX_BINARY) for name in NAMES}
    new = json.loads(regular(stage / "engines.candidate.json", 8192))
    expected = {"sha256": sha(staged["frpc"]),
                "server_sha256": sha(staged["frps"])}
    require(new == {"schema": 1, "engines": {**current["engines"],
                                             "frp": expected}},
            "OFFICIAL_FRP_MANIFEST_NOT_ADDITIVE")
    require(regular(stage / "compose.override.candidate.yml", 8192)
            == plan.STAGED_OVERLAY.encode(), "OFFICIAL_FRP_OVERLAY_DRIFT")
    for value in (b"7000", b"8888:8888", b"SMITE_FRP_STANDARD_WSS=1"):
        require(value not in plan.OVERLAY.encode(), "PROPOSED_OVERLAY_NOT_INERT")
    return f, old, staged, regular(stage / "engines.candidate.json", 8192)


def journal(root: Path, f, old: bytes | None, staged: dict, manifest: bytes):
    mkdir(f["journal"])
    write_new(f["journal"] / "base.before", regular(f["base"], 131072))
    write_new(f["journal"] / "signed.before", regular(f["signed"], 131072))
    if old is not None:
        write_new(f["journal"] / "manifest.before", old)
    data = {
        "schema": 1,
        "base_sha256": sha(regular(f["base"], 131072)),
        "old_manifest_sha256": sha(old) if old is not None else None,
        "new_manifest_sha256": sha(manifest),
        "overlay_sha256": sha(plan.OVERLAY.encode()),
        "frpc_sha256": sha(staged["frpc"]), "frps_sha256": sha(staged["frps"]),
        "protected": protected(f),
    }
    write_new(f["journal"] / "record.json",
              (json.dumps(data, sort_keys=True) + "\n").encode())
    fsync_dir(f["journal"])
    return data


def record(f):
    private_dir(f["journal"])
    doc = json.loads(regular(f["journal"] / "record.json", 8192))
    required = {"schema", "base_sha256", "old_manifest_sha256",
                "new_manifest_sha256", "overlay_sha256", "frpc_sha256",
                "frps_sha256", "protected"}
    require(isinstance(doc, dict) and set(doc) == required
            and doc["schema"] == 1
            and all(isinstance(doc[k], str) and HEX64.fullmatch(doc[k])
                    for k in ("base_sha256", "new_manifest_sha256",
                              "overlay_sha256", "frpc_sha256", "frps_sha256"))
            and (doc["old_manifest_sha256"] is None
                 or HEX64.fullmatch(str(doc["old_manifest_sha256"])))
            and isinstance(doc["protected"], dict),
            "UNTRUSTED_SIGNED_FRP_JOURNAL")
    return doc


def signed_check(check, expected):
    # CI fixture callback, not evidence of live HMAC or replay.
    require(callable(check) and check(expected) == "PASS",
            "SIGNED_RUNTIME_REPLAY_NOT_PROVEN")


def activate(root: Path, stage: Path, *, official_verify=frp.verify,
             signed_probe=None, interrupt: str = ""):
    f, old, bins, manifest = candidate(root, stage,
                                        verify_official=official_verify)
    signed_check(signed_probe, "not-installed")
    data = journal(root, f, old, bins, manifest)
    try:
        if interrupt == "journal":
            raise Interrupted("journal")
        mkdir(root / "installed")
        mkdir(root / "installed" / "frp")
        for name in NAMES:
            write_new(f[name], bins[name], 0o755)
            if interrupt == name:
                raise Interrupted(name)
        write_new(f["overlay"], plan.OVERLAY.encode())
        if interrupt == "overlay":
            raise Interrupted("overlay")
        state = f["manifest"].parent
        if not state.exists():
            mkdir(state)
        elif state.is_symlink():
            raise Hold("UNTRUSTED_MANIFEST_DIR")
        else:
            private_dir(state)
        # Lab refuses pre-existing other engines in this phase; another
        # engine needs a separately audited additive manifest transaction.
        require(old is None, "OTHER_ENGINE_REAL_HOST_TRANSACTION_HOLD")
        write_new(f["manifest"], manifest)
        if interrupt == "manifest":
            raise Interrupted("manifest")
        verify_protected(f, data["protected"])
        signed_check(signed_probe, "ready")
        verify_protected(f, data["protected"])
        require(sha(regular(f["overlay"])) == data["overlay_sha256"]
                and sha(regular(f["manifest"])) == data["new_manifest_sha256"]
                and all(sha(regular(f[n], MAX_BINARY)) ==
                        data[f"{n}_sha256"] for n in NAMES),
                "POST_ENROLLMENT_DRIFT")
        # Keep the journal for explicit rollback; no silent cleanup.
        return "CI_SIGNED_FRP_DUAL_PAIR_STAGED_NO_NODE_RESTART"
    except Interrupted:
        raise
    except Exception as exc:
        try:
            rollback(root, signed_probe=signed_probe)
        except Exception as recovery:
            raise Hold("CRITICAL_LAB_RECOVERY_REQUIRED") from recovery
        raise Hold("ENROLLMENT_FAILED_LAB_ROLLED_BACK") from exc


def rollback(root: Path, *, signed_probe=None):
    gate(root)
    f = paths(root)
    data = record(f)
    before_base = regular(f["journal"] / "base.before", 131072)
    before_signed = regular(f["journal"] / "signed.before", 131072)
    require(sha(before_base) == data["base_sha256"]
            and sha(before_signed) == data["protected"]["signed"],
            "JOURNAL_PREIMAGE_CHANGED")
    require(sha(regular(f["base"], 131072)) == data["base_sha256"],
            "BASE_COMPOSE_EXTERNAL_DRIFT")
    verify_protected(f, data["protected"])
    previous = (
        regular(f["journal"] / "manifest.before", 8192)
        if data["old_manifest_sha256"] is not None else None
    )
    if previous is not None:
        require(sha(previous) == data["old_manifest_sha256"],
                "JOURNAL_PRIOR_MANIFEST_CHANGED")
    for name, target in (("overlay_sha256", f["overlay"]),
                         ("new_manifest_sha256", f["manifest"]),
                         ("frpc_sha256", f["frpc"]),
                         ("frps_sha256", f["frps"])):
        if target.exists() or target.is_symlink():
            require(sha(regular(target, MAX_BINARY)) == data[name],
                    "STAGED_COMPONENT_EXTERNAL_DRIFT")
    if data["old_manifest_sha256"] is not None:
        require(f["manifest"].exists(), "ORIGINAL_MANIFEST_DISAPPEARED")
    # ALL mutation preconditions checked first. A different identity,
    # replay inode, signed compose or engine artifact must be left untouched.
    if f["manifest"].exists():
        f["manifest"].unlink()
    if previous is not None:
        write_new(f["manifest"], previous)
    if f["overlay"].exists():
        f["overlay"].unlink()
    for name in NAMES:
        if f[name].exists():
            f[name].unlink()
    for parent in (root / "installed" / "frp", root / "installed",
                   f["manifest"].parent):
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    signed_check(signed_probe, "not-installed")
    verify_protected(f, data["protected"])
    for item in f["journal"].iterdir():
        require(item.is_file() and not item.is_symlink(), "JOURNAL_UNTRUSTED_ENTRY")
        item.unlink()
    f["journal"].rmdir()
    return "CI_SIGNED_FRP_EXACT_ROLLBACK_AND_REPLAY_PRESERVED"


def main():
    # No real-host CLI action. Even with CI env this tool is only an
    # importable, marked private lab used by a reviewed offline unit suite.
    print("HOLD: STAGE15_SIGNED_FRP_HOST_EXECUTOR_NOT_RELEASED", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
