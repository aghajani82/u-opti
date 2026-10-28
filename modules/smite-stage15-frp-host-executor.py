#!/usr/bin/env python3
"""Stage15 signed FRP v0.71 engine enrollment on disposable IR/KH only.

A field-trial host transaction, NOT general FRP installation or WSS
activation. It pins a verified official dual-role archive, preserves the
existing signed security Compose overlay, and restarts ONLY smite-node.
The signed HMAC inventory probe consumes durable replay nonces before and
after recreation. Every mutation has a journaled rollback/recover path.

This must NOT be wired to the beginner menu before two-host acceptance.
No firewall, Nginx, FRP server, Xray, route or public port changes.
Production Grandoptical is explicitly excluded by host/role/image gates.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
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
import time
from contextlib import contextmanager

HERE = Path(__file__).resolve().parent
SHA = re.compile(r"^[a-f0-9]{64}$")
FLAG = "UOPTI_STAGE15_FRP_HOST_FIELD_TRIAL"
SNAPSHOT = "SNAPSHOTS-AND-CONSOLES-VERIFIED"
MAX_BIN = 48 * 1024 * 1024

def load(alias: str, name: str):
    spec = importlib.util.spec_from_file_location(alias, HERE / name)
    if spec is None or spec.loader is None:
        raise RuntimeError("REVIEWED_HELPER_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

package = load("stage15_frp_host_package", "smite-managed-frp.py")
proposal = load("stage15_frp_host_compose_plan", "smite-stage15-frp-compose-plan.py")
control = load("stage15_frp_host_control", "smite-managed-frp-control.py")
# Keep the bounded signed probe self-contained: the RC.2 executor is not
# installed by the Clean-RC installer and must not be a runtime dependency.
SIGNED_CHECK = r'''
import json, urllib.request, urllib.error
from app.config import settings
from app.agent_auth import read_identity
from app.node_auth import sign_request
expected=__import__("sys").argv[1]
node_id,secret=read_identity(settings.smite_agent_identity_path)
target="/api/agent/engines"
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
def check(ok):
    if not ok:
        raise RuntimeError("SIGNED_FRP_INVENTORY_REJECTED")
def request(headers=None):
    q=urllib.request.Request("http://127.0.0.1:8888"+target,
        method="GET",headers=headers or {})
    try:
        with opener.open(q,timeout=6) as r:
            return r.status,r.read()
    except urllib.error.HTTPError as e:
        return e.code,e.read()
check(request()[0]==401)
h=sign_request(secret=secret,node_id=node_id,method="GET",target=target,body=b"")
status,body=request(h)
check(status==200)
data=json.loads(body)
check(data["mode"]=="managed" and data["engines"]["frp"]==expected)
check(request(h)[0]==401)
print("SIGNED_FRP_INVENTORY=PASS")
'''


class Hold(RuntimeError):
    pass

class SimulatedCrash(RuntimeError):
    pass

@dataclass(frozen=True)
class Paths:
    node: Path = Path("/opt/smite-node")
    binaries: Path = package.INSTALL_ROOT
    state: Path = Path("/var/lib/u-opti/smite-stage15-frp-engine")
    identity: Path = Path("/etc/u-opti/smite/identities/node-identity.json")
    replay: Path = Path("/var/lib/u-opti/smite-node-security/replay/agent-replay.sqlite3")
    lock: Path = Path("/run/lock/u-opti-smite-engine.lock")

    @property
    def base(self): return self.node / "docker-compose.yml"
    @property
    def signed(self): return self.node / "docker-compose.security-candidate.yml"
    @property
    def overlay(self): return self.node / "docker-compose.frp-stage15.yml"
    @property
    def manifest_dir(self): return self.node / "config/engine-state"
    @property
    def manifest(self): return self.manifest_dir / "engines.json"
    @property
    def journal(self): return self.state / "journal"

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def require(ok: bool, code: str):
    if not ok:
        raise Hold(code)

def file(path: Path, *, limit: int = 131072, mode: int | None = None) -> bytes:
    try:
        trusted_parents(path)
        require(not path.is_symlink(), "UNTRUSTED_SYMLINK")
        old = path.lstat()
        require(stat.S_ISREG(old.st_mode) and old.st_nlink == 1
                and old.st_uid == os.geteuid()
                and 0 <= old.st_size <= limit, "UNTRUSTED_FILE")
        if mode is not None:
            require(stat.S_IMODE(old.st_mode) == mode, "UNSAFE_FILE_MODE")
        else:
            require(stat.S_IMODE(old.st_mode) & 0o022 == 0, "UNSAFE_FILE_MODE")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            require((old.st_dev, old.st_ino) == (info.st_dev, info.st_ino),
                    "FILE_REPLACED_DURING_READ")
            data = stream.read(limit + 1)
        require(len(data) <= limit, "FILE_EXCEEDS_LIMIT")
        return data
    except FileNotFoundError as exc:
        raise Hold("REQUIRED_FILE_MISSING") from exc

def trusted_parents(path: Path):
    # O_NOFOLLOW on the leaf alone does not protect an ancestor symlink.
    require(path.is_absolute() and ".." not in path.parts, "UNTRUSTED_DIRECTORY_TREE")
    for parent in path.parents:
        st = parent.lstat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid()
                and (stat.S_IMODE(st.st_mode) & 0o022 == 0
                     or (st.st_uid == 0 and st.st_mode & stat.S_ISVTX)),
                "UNTRUSTED_DIRECTORY_TREE")


def directory(path: Path, *, private: bool = False, shared_sticky: bool = False):
    trusted_parents(path)
    require(path.is_absolute() and not path.is_symlink(), "UNTRUSTED_DIRECTORY")
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid()
            and (stat.S_IMODE(st.st_mode) == 0o700 if private
                 else (stat.S_IMODE(st.st_mode) & 0o022 == 0
                       or (shared_sticky and st.st_uid == 0
                           and stat.S_IMODE(st.st_mode) == 0o1777))),
            "UNTRUSTED_DIRECTORY")

def new_dir(path: Path):
    require(not path.exists() and not path.is_symlink(), "DIRECTORY_ALREADY_EXISTS")
    path.mkdir(mode=0o700)
    directory(path, private=True)
    flush(path.parent)

def flush(path: Path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def new_file(path: Path, data: bytes, mode: int):
    trusted_parents(path)
    require(not path.exists() and not path.is_symlink(), "FILE_ALREADY_EXISTS")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                 | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        flush(path.parent)
    except BaseException:
        if path.exists() and not path.is_symlink():
            path.unlink()
        raise

@contextmanager
def exclusive(path: Path):
    directory(path.parent, shared_sticky=True)
    require(not path.is_symlink(), "UNSAFE_ENGINE_LOCK")
    fd = os.open(path, os.O_CREAT | os.O_RDWR
                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid()
                and st.st_nlink == 1 and stat.S_IMODE(st.st_mode) == 0o600,
                "UNSAFE_ENGINE_LOCK")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold("ENGINE_TRANSACTION_LOCKED") from exc
        yield
    finally:
        os.close(fd)

def run(argv: list[str], *, input: str | None = None, timeout: int = 35):
    """Argument-vector only; only exact reviewed commands are permitted."""
    require(not any(os.environ.get(key) for key in (
        "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH", "COMPOSE_FILE", "COMPOSE_PROFILES")),
        "REMOTE_OR_AMBIENT_DOCKER_CONFIGURATION")
    if argv and argv[0] == "docker":
        argv = ["docker", "--host", "unix:///var/run/docker.sock", *argv[1:]]
    try:
        res = subprocess.run(argv, input=input, capture_output=True, text=True,
                             check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("LOCAL_EXECUTION_UNAVAILABLE") from exc
    if res.returncode != 0 or len(res.stdout) > 262144:
        raise Hold("REVIEWED_COMMAND_FAILED")
    return res.stdout.strip()

def compose_cmd(p: Paths, *, enabled: bool, action: list[str]):
    cmd = ["docker", "compose", "-f", str(p.base), "-f", str(p.signed)]
    if enabled:
        cmd.extend(["-f", str(p.overlay)])
    return cmd + action

def protected(p: Paths):
    replay_st = p.replay.lstat()
    file(p.replay, limit=80 * 1024 * 1024, mode=0o600)
    ident_st = p.identity.lstat()
    return {
        "base": digest(file(p.base)),
        "signed": digest(file(p.signed, mode=0o600)),
        "env": digest(file(p.node / ".env", mode=0o600)),
        "identity": digest(file(p.identity, mode=0o600)),
        "identity_inode": f"{ident_st.st_dev}:{ident_st.st_ino}",
        "replay_inode": f"{replay_st.st_dev}:{replay_st.st_ino}",
    }

def ensure_protected(p: Paths, proof: dict):
    require(protected(p) == proof, "SIGNED_IDENTITY_REPLAY_OR_COMPOSE_DRIFT")

def artifacts(p: Paths):
    return {"frpc": p.binaries / "frpc", "frps": p.binaries / "frps",
            "overlay": p.overlay, "manifest": p.manifest}

def runtime(p: Paths, enabled: bool, *, runner=run, healthy: bool = True):
    try:
        raw = json.loads(runner(["docker", "inspect", "smite-node"]))
        require(isinstance(raw, list) and len(raw) == 1, "NODE_INSPECT_UNTRUSTED")
        obj = raw[0]
        require(obj["Image"] == control.STAGE15_NODE_ID
                and obj["Config"]["Image"] == "smite-node:stage15-local"
                and (not healthy or (obj["State"]["Running"] is True
                    and obj["State"]["Health"]["Status"] == "healthy")),
                "SIGNED_STAGE15_RUNTIME_UNHEALTHY")
        env = obj["Config"]["Env"]
        require(len(env) == len(set(x.split("=", 1)[0] for x in env)),
                "DUPLICATE_NODE_ENV")
        for value in ("SMITE_AGENT_AUTH_MODE=strict",
                      "SMITE_NODE_PANEL_AUTH_MODE=signed",
                      "SMITE_ENGINE_INVENTORY_MODE=managed"):
            require(value in env, "SIGNED_RUNTIME_POLICY_DRIFT")
        require(not any(x.startswith("SMITE_FRP_STANDARD_WSS=") for x in env),
                "UNREVIEWED_WSS_ENABLED")
        for value in (
            "SMITE_AGENT_IDENTITY_PATH=/run/smite-node-identity/node-identity.json",
            "SMITE_AGENT_REPLAY_DB=/var/lib/smite-node/auth/agent-replay.sqlite3",
        ):
            require(value in env, "SIGNED_STORAGE_PATH_DRIFT")
        require(obj["HostConfig"]["NetworkMode"] == "host"
                and not obj["HostConfig"].get("PortBindings")
                and obj["HostConfig"].get("Privileged") is False,
                "NODE_NETWORK_SECURITY_DRIFT")
        require(obj["Config"]["Cmd"] == [
            "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"
        ], "NODE_LOOPBACK_API_DRIFT")
        files = {x.strip() for x in obj["Config"]["Labels"].get(
            "com.docker.compose.project.config_files", "").split(",") if x.strip()}
        expected = {str(p.base), str(p.signed)}
        if enabled:
            expected.add(str(p.overlay))
        require(files == expected, "SIGNED_COMPOSE_FILE_SET_DRIFT")
        mounts = {m["Destination"]: m for m in obj["Mounts"]}
        require(len(mounts) == len(obj["Mounts"]), "DUPLICATE_RUNTIME_MOUNT")
        for key, (source, rw) in {
            "/etc/smite-node": (p.node / "config", True),
            "/run/smite-node-identity": (p.identity.parent, False),
            "/var/lib/smite-node/auth": (p.replay.parent, True),
        }.items():
            require(key in mounts and mounts[key].get("RW") is rw
                    and mounts[key].get("Type") == "bind"
                    and mounts[key].get("Source") == str(source),
                    "SIGNED_IDENTITY_MOUNT_DRIFT")
        if enabled:
            for name in ("frpc", "frps"):
                dest = "/usr/local/bin/" + name
                require(dest in mounts
                        and mounts[dest]["Source"] == str(p.binaries / name)
                        and mounts[dest]["RW"] is False,
                        "FRP_BINARY_MOUNT_DRIFT")
        else:
            require(not any(x in mounts for x in
                        ("/usr/local/bin/frpc", "/usr/local/bin/frps")),
                    "UNEXPECTED_FRP_BINARY_MOUNT")
    except (KeyError, ValueError, TypeError, AttributeError, IndexError) as exc:
        if isinstance(exc, Hold):
            raise
        raise Hold("NODE_INSPECT_MALFORMED") from exc

def signed_inventory(expected: str, *, runner=run):
    """A real HMAC nonce and durable Replay test (not a synthetic status)."""
    result = runner([
        "docker", "exec", "smite-node", "python3", "-B", "-c",
        SIGNED_CHECK, expected,
    ])
    require(result == "SIGNED_FRP_INVENTORY=PASS", "SIGNED_HMAC_REPLAY_FAILED")

def preflight(p: Paths, stage: Path, *, review=proposal.review,
              signed=signed_inventory, runner=run):
    require(p.node == Path("/opt/smite-node")
            and p.binaries == package.INSTALL_ROOT, "STAGE15_HOST_PATHS_UNREVIEWED")
    require(os.uname().nodename.split(".")[0].lower() in ("ir", "kh"),
            "ONLY_DISPOSABLE_IR_KH_HOSTS")
    directory(p.node)
    directory(p.node / "config")
    require(not p.overlay.exists() and not p.overlay.is_symlink(),
            "FRP_OVERLAY_ALREADY_PRESENT")
    require(not p.state.exists() and not p.state.is_symlink(),
            "PRIOR_FRP_TRANSACTION_REQUIRES_REVIEW")
    require(not p.manifest.exists() and not p.manifest.is_symlink()
            and not p.manifest_dir.exists() and not p.manifest_dir.is_symlink(),
            "PREEXISTING_ENGINE_STATE_REQUIRES_REVIEW")
    require(not (p.node / "config/tunnels.json").exists()
            and not (p.node / "config/tunnels.json").is_symlink(),
            "SAVED_TUNNELS_REQUIRE_REVIEW")
    for x in artifacts(p).values():
        require(not x.exists() and not x.is_symlink(),
                "FRP_HOST_ARTIFACT_ALREADY_PRESENT")
    require(not p.binaries.exists() and not p.binaries.is_symlink(),
            "PREEXISTING_FRP_HOST_BINARIES")
    result = review(p.node, stage)
    require(result.get("STAGE15_FRP_COMPOSE_PLAN") == "PASS_READ_ONLY"
            and result.get("FRP_MOUNTS") == "TWO_READ_ONLY_BINDS_ONLY"
            and result.get("APPLY_ALLOWED") == "NO",
            "STAGE15_SIGNED_PLAN_NOT_ADMITTED")
    runtime(p, False, runner=runner)
    proof = protected(p)
    signed("not-installed", runner=runner)
    return proof

def stage_bytes(stage: Path):
    require(stage.is_absolute() and not stage.is_symlink()
            and not stage.parent.is_symlink(), "UNTRUSTED_OFFICIAL_STAGE_PATH")
    directory(stage.parent, private=True)
    directory(stage, private=True)
    # All reviewed staged outputs must remain root-owned with their exact
    # original modes; do not admit an attacker-writable official stage.
    for name, mode in {
        "frp.official.tar.gz": 0o600,
        "summary.txt": 0o600,
        "SHA256SUMS": 0o600,
        "engines.candidate.json": 0o600,
        "compose.override.candidate.yml": 0o600,
        "frpc.bin": 0o755, "frps.bin": 0o755,
    }.items():
        file(stage / name, limit=MAX_BIN, mode=mode)
    require(package.verify(stage), "OFFICIAL_FRP_STAGE_NOT_VERIFIED")
    # A valid upstream ARM bundle must not be admitted on an amd64 host
    # (and vice versa); a signed inventory hash alone cannot detect ELF ABI.
    machine = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine)
    require(machine is not None, "HOST_FRP_ARCH_UNSUPPORTED")
    summary = file(stage / "summary.txt", limit=4096).decode()
    settings = dict(line.split("=", 1) for line in summary.splitlines())
    require(settings.get("FRP_ARCH") == machine,
            "OFFICIAL_FRP_STAGE_HOST_ARCH_MISMATCH")
    return {n: file(stage / (n + ".bin"), limit=MAX_BIN) for n in ("frpc", "frps")}

def create_parent(path: Path, anchor: Path):
    """Allow only a reviewed root-owned /opt or /var/lib hierarchy."""
    require(path.is_absolute() and anchor.is_absolute()
            and anchor in path.parents, "UNTRUSTED_DIRECTORY_TREE")
    directory(anchor)
    cur = anchor
    for part in path.relative_to(anchor).parts:
        cur = cur / part
        if not cur.exists() and not cur.is_symlink():
            new_dir(cur)
        else:
            directory(cur)

def journal_prepare(p: Paths, role: str, proof: dict, hashes: dict, manifest: bytes):
    create_parent(p.state, Path("/var/lib"))
    new_dir(p.journal)
    record = {"schema": 1, "role": role, "state": "PREPARED",
              "protected": proof,
              "binary_sha256": hashes,
              "overlay_sha256": digest(proposal.OVERLAY.encode()),
              "manifest_sha256": digest(manifest)}
    new_file(p.journal / "record.json",
             (json.dumps(record, sort_keys=True) + "\n").encode(), 0o600)
    return record

def update_record(p: Paths, data: dict, state: str):
    # Replace the bounded private journal atomically, retaining its earlier
    # canonical digest-protected preconditions in every state transition.
    data["state"] = state
    directory(p.state, private=True)
    directory(p.journal, private=True)
    out = p.journal / "record.new"
    if out.exists() or out.is_symlink():
        # A power loss before rename leaves an uncommitted scratch record.
        # Validate its file boundary; never trust its possibly partial contents.
        file(out, limit=16384, mode=0o600)
        out.unlink()
        flush(p.journal)
    new_file(out, (json.dumps(data, sort_keys=True) + "\n").encode(), 0o600)
    os.replace(out, p.journal / "record.json")
    flush(p.journal)

def receipt(p: Paths):
    directory(p.state, private=True)
    directory(p.journal, private=True)
    require({entry.name for entry in p.journal.iterdir()} <= {"record.json", "record.new"},
            "JOURNAL_UNSAFE_ENTRY")
    data = json.loads(file(p.journal / "record.json", limit=16384, mode=0o600))
    keys = {"schema", "role", "state", "protected",
            "binary_sha256", "overlay_sha256", "manifest_sha256"}
    require(isinstance(data, dict) and set(data) == keys
            and data["schema"] == 1
            and data["role"] in ("IR", "KH")
            and data["state"] in ("PREPARED", "BINARIES", "OVERLAY",
                                  "MANIFEST", "NODE_RECREATED", "COMMITTED",
                                  "RECOVERING")
            and set(data["binary_sha256"]) == {"frpc", "frps"}
            and all(isinstance(v, str) and SHA.fullmatch(v)
                    for v in [*data["binary_sha256"].values(),
                              data["overlay_sha256"], data["manifest_sha256"]])
            and isinstance(data["protected"], dict)
            and set(data["protected"]) == {
                "base", "signed", "env", "identity", "identity_inode",
                "replay_inode"}, "UNTRUSTED_FRP_HOST_JOURNAL")
    return data

def verify_artifacts(p: Paths, data: dict, *, complete: bool):
    for name, target in artifacts(p).items():
        if not target.exists() and not target.is_symlink():
            require(not complete, "FRP_HOST_ARTIFACT_MISSING")
            continue
        expected = (data["binary_sha256"][name] if name in ("frpc", "frps")
                    else data[name + "_sha256"])
        require(digest(file(target, limit=MAX_BIN if name in ("frpc", "frps")
                            else 131072, mode=0o755 if name in ("frpc", "frps") else 0o600)) == expected,
                "FRP_HOST_ARTIFACT_EXTERNAL_DRIFT")

def restart(p: Paths, *, enabled: bool, runner=run):
    runner(compose_cmd(p, enabled=enabled, action=[
        "up", "-d", "--no-build", "--no-deps", "--pull", "never",
        "--force-recreate", "smite-node"
    ]), timeout=125)

def await_signed(p: Paths, *, enabled: bool, expected: str, runner=run,
                 signed=signed_inventory):
    for _ in range(18):
        try:
            runtime(p, enabled, runner=runner)
            signed(expected, runner=runner)
            return
        except Hold:
            time.sleep(3)
    raise Hold("SIGNED_HMAC_REPLAY_OR_RUNTIME_NOT_RESTORED")

def _cleanup_empty(p: Paths):
    for path in [p.manifest_dir, p.binaries, p.state]:
        if path.exists() and not path.is_symlink() and not any(path.iterdir()):
            path.rmdir()
            flush(path.parent)

def restore(p: Paths, data: dict, *, runner=run, signed=signed_inventory):
    """Checked rollback. On uncertainty keep journal and HOLD, never erase."""
    ensure_protected(p, data["protected"])
    # An already committed install must retain all four exact artifacts;
    # missing files indicate out-of-band drift, not a recoverable interruption.
    verify_artifacts(p, data, complete=(data["state"] == "COMMITTED"))
    require(not (p.node / "config/tunnels.json").exists()
            and not (p.node / "config/tunnels.json").is_symlink(),
            "TUNNELS_CREATED_AFTER_FRP_STAGE")
    # Verify the current runtime before overwriting it. A changed mount,
    # listener/auth policy or extra Compose overlay is external drift.
    try:
        runtime(p, True, runner=runner, healthy=False)
    except Hold:
        runtime(p, False, runner=runner, healthy=False)
    # Commit rollback intent BEFORE removing the manifest. A crash here must
    # not leave COMMITTED claiming that all artifacts still exist.
    update_record(p, data, "RECOVERING")
    if p.manifest.exists():
        p.manifest.unlink()
        flush(p.manifest.parent)
    # Explicitly restore base + signed overlay. Never use the plain base
    # alone: that would silently drop strict/signed authentication.
    restart(p, enabled=False, runner=runner)
    await_signed(p, enabled=False, expected="not-installed",
                 runner=runner, signed=signed)
    ensure_protected(p, data["protected"])
    for name, target in artifacts(p).items():
        if name != "manifest" and target.exists():
            target.unlink()
            flush(target.parent)
    _cleanup_empty(p)
    # Keep a private audit trail if the signer/Node proof failed.
    for entry in p.journal.iterdir():
        require(entry.is_file() and not entry.is_symlink(), "JOURNAL_UNSAFE_ENTRY")
        entry.unlink()
    p.journal.rmdir()
    flush(p.journal.parent)
    _cleanup_empty(p)

def install(p: Paths, stage: Path, *, snapshot_confirm: str,
            role_confirm: str, runner=run, signed=signed_inventory,
            review=proposal.review, inject: str = ""):
    require(snapshot_confirm == SNAPSHOT, "SNAPSHOT_CONSOLE_CONFIRMATION_REQUIRED")
    require(os.geteuid() == 0 and os.environ.get(FLAG) == "YES",
            "EXPLICIT_ROOT_FIELD_TRIAL_REQUIRED")
    role = os.uname().nodename.split(".")[0].upper()
    require(role in ("IR", "KH")
            and role_confirm == "INSTALL-STAGE15-FRP-" + role,
            "ROLE_CONFIRMATION_REQUIRED")
    with exclusive(p.lock):
        proof = preflight(p, stage, review=review, signed=signed, runner=runner)
        binaries = stage_bytes(stage)
        hashes = {k: digest(v) for k, v in binaries.items()}
        raw_manifest = file(stage / "engines.candidate.json", limit=8192)
        doc = json.loads(raw_manifest)
        require(doc == {"schema": 1, "engines": {"frp": {
            "sha256": hashes["frpc"], "server_sha256": hashes["frps"],
        }}}, "MANAGED_FRP_MANIFEST_UNREVIEWED")
        data = journal_prepare(p, role, proof, hashes, raw_manifest)
        try:
            if inject == "journal":
                raise SimulatedCrash("journal")
            create_parent(p.binaries, Path("/opt"))
            for name, binary in binaries.items():
                new_file(p.binaries / name, binary, 0o755)
                if inject == name:
                    raise SimulatedCrash(name)
            update_record(p, data, "BINARIES")
            new_file(p.overlay, proposal.OVERLAY.encode(), 0o600)
            update_record(p, data, "OVERLAY")
            if inject == "overlay":
                raise SimulatedCrash("overlay")
            new_dir(p.manifest_dir)
            new_file(p.manifest, raw_manifest, 0o600)
            update_record(p, data, "MANIFEST")
            if inject == "manifest":
                raise SimulatedCrash("manifest")
            ensure_protected(p, proof)
            restart(p, enabled=True, runner=runner)
            update_record(p, data, "NODE_RECREATED")
            if inject == "restart":
                raise SimulatedCrash("restart")
            await_signed(p, enabled=True, expected="ready",
                         runner=runner, signed=signed)
            ensure_protected(p, proof)
            verify_artifacts(p, data, complete=True)
            update_record(p, data, "COMMITTED")
            return {"STAGE15_FRP_HOST_ENROLLMENT": "PASS_SIGNED_FIELD_TRIAL",
                    "FRP_ENGINE": "READY", "WSS": "NOT_ENABLED",
                    "TUNNEL_CREATED": "NO", "PRODUCTION_RELEASE": "NO"}
        except SimulatedCrash:
            raise
        except Exception as exc:
            try:
                restore(p, data, runner=runner, signed=signed)
            except Exception as recovery_exc:
                raise Hold("CRITICAL_SIGNED_FRP_RECOVERY_REQUIRED") from recovery_exc
            raise Hold("FRP_ENROLLMENT_ROLLED_BACK") from exc

def rollback(p: Paths, *, role_confirm: str, runner=run,
             signed=signed_inventory, allow_incomplete: bool = False):
    require(os.geteuid() == 0 and os.environ.get(FLAG) == "YES",
            "EXPLICIT_ROOT_FIELD_TRIAL_REQUIRED")
    with exclusive(p.lock):
        data = receipt(p)
        require(os.uname().nodename.split(".")[0].upper() == data["role"],
                "JOURNAL_HOST_ROLE_MISMATCH")
        expected = "RECOVER" if allow_incomplete else "ROLLBACK"
        require(role_confirm == expected + "-STAGE15-FRP-" + data["role"],
                "ROLE_CONFIRMATION_REQUIRED")
        if allow_incomplete:
            require(data["state"] != "COMMITTED", "COMMITTED_USE_ROLLBACK")
        else:
            require(data["state"] == "COMMITTED", "INCOMPLETE_USE_RECOVER")
        restore(p, data, runner=runner, signed=signed)
        return {"STAGE15_FRP_HOST_" + expected: "PASS_SIGNED_PRIOR_RUNTIME",
                "FRP_ENGINE": "NOT_INSTALLED", "PRODUCTION_RELEASE": "NO"}

def verify(p: Paths, *, runner=run, signed=signed_inventory):
    with exclusive(p.lock):
        data = receipt(p)
        require(os.uname().nodename.split(".")[0].upper() == data["role"],
                "JOURNAL_HOST_ROLE_MISMATCH")
        require(data["state"] == "COMMITTED", "FRP_HOST_TRANSACTION_INCOMPLETE")
        ensure_protected(p, data["protected"])
        verify_artifacts(p, data, complete=True)
        runtime(p, True, runner=runner)
        signed("ready", runner=runner)
        return {"STAGE15_FRP_HOST_VERIFY": "PASS_SIGNED_REPLAY",
                "WSS": "NOT_ENABLED", "TUNNEL_CREATED": "NO"}

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("install", "verify", "rollback", "recover"))
    ap.add_argument("--stage", type=Path)
    ap.add_argument("--snapshot-confirm")
    ap.add_argument("--role-confirm")
    args = ap.parse_args()
    p = Paths()
    try:
        require(os.geteuid() == 0 and os.environ.get(FLAG) == "YES",
                "FIELD_TRIAL_ONLY_NOT_A_GENERAL_INSTALLER")
        require(os.uname().nodename.split(".")[0].lower() in ("ir", "kh"),
                "ONLY_DISPOSABLE_IR_KH_HOSTS")
        if args.action == "install":
            require(args.stage is not None, "OFFICIAL_STAGE_REQUIRED")
            result = install(p, args.stage,
                             snapshot_confirm=args.snapshot_confirm or "",
                             role_confirm=args.role_confirm or "")
        elif args.action == "verify":
            result = verify(p)
        else:
            result = rollback(p, role_confirm=args.role_confirm or "",
                              allow_incomplete=(args.action == "recover"))
        for key, value in result.items():
            print(f"{key}={value}")
        return 0
    except SimulatedCrash:
        print("HOLD: INTERRUPTED_TRANSACTION_USE_RECOVER", file=sys.stderr)
        return 91
    except (Hold, OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError, package.Hold) as exc:
        reason = str(exc)
        print("HOLD: " + (reason if re.fullmatch(r"[A-Z0-9_]{1,100}", reason)
                           else "UNTRUSTED_STAGE15_FRP_STATE"), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
