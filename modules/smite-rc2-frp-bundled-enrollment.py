#!/usr/bin/env python3
"""RC.2-only enrollment of the reviewed, already bundled FRP pair.

This is a disposable IR/KH field-trial bridge, NOT a general FRP installer.
The two immutable reviewed Node images already ship matching frpc/frps.
An explicit, crash-auditable manifest enrollment enables managed inventory.
It never downloads binaries, edits Compose, recreates containers, creates
tunnels, configures ingress/443, or enables legacy unsigned authentication.

Only a separately approved host operator may enroll or rollback; plan and
verify are read-only. Reboot/recreation persistence and TLS/443 traffic
remain separate acceptance gates. Main/stable releases are not authorized.
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

NODE = Path("/opt/smite-node")
CONFIG = NODE / "config"
MANIFEST_DIR = CONFIG / "engine-state"
MANIFEST = MANIFEST_DIR / "engines.json"
JOURNAL_DIR = NODE / "frp-rc2-enrollment-journal"
JOURNAL = JOURNAL_DIR / "record.json"
LOCK = Path("/run/lock/u-opti-smite-engine.lock")
IDENTITY = Path("/etc/u-opti/smite/identities/node-identity.json")
REPLAY = Path("/var/lib/u-opti/smite-node-security/replay/agent-replay.sqlite3")
CANDIDATE = NODE / "docker-compose.security-candidate.yml"
HOST_IMAGES = {
    "ir": "ghcr.io/aghajani82/smite-node@sha256:9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec",
    "kh": "ghcr.io/aghajani82/smite-node@sha256:2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78",
}
BINARIES = {
    "frpc": "a89129b922f91f1327853a46da65136c52ad421c85315299d333ec06da3f3bbb",
    "frps": "02b50823f330d0486f334d6aa9e448c4d0a26f553a691d167aae8358baab89ee",
}
TRIAL_FLAG = "UOPTI_SMITE_RC2_FRP_ENROLLMENT"
CONFIRM = {"enroll": "ENROLL-RC2-FRP", "rollback": "ROLLBACK-RC2-FRP"}


class Hold(Exception):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Hold(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def regular(path: Path, *, mode: int | None = None, limit: int = 65536) -> bytes:
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and st.st_nlink == 1,
            "UNSAFE_FILE")
    require(not (stat.S_IMODE(st.st_mode) & 0o022), "UNSAFE_FILE_MODE")
    if mode is not None:
        require(stat.S_IMODE(st.st_mode) == mode, "UNEXPECTED_FILE_MODE")
    require(0 <= st.st_size <= limit, "UNSAFE_FILE_LENGTH")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        opened = os.fstat(source.fileno())
        require((st.st_dev, st.st_ino) == (opened.st_dev, opened.st_ino),
                "FILE_CHANGED")
        return source.read(limit + 1)


def directory(path: Path, *, private: bool = False) -> None:
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == 0, "UNSAFE_DIRECTORY")
    mode = stat.S_IMODE(st.st_mode)
    require(mode == 0o700 if private else not mode & 0o022, "UNSAFE_DIRECTORY_MODE")


def absent(path: Path) -> bool:
    return not path.exists() and not path.is_symlink()


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_private(path: Path) -> None:
    require(absent(path), "TARGET_ALREADY_EXISTS")
    path.mkdir(mode=0o700)
    directory(path, private=True)
    fsync_dir(path.parent)


def create_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as target:
        os.fchmod(target.fileno(), 0o600)
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    fsync_dir(path.parent)


def run(args: list[str], *, stdin: str | None = None) -> str:
    try:
        result = subprocess.run(
            args, input=stdin, capture_output=True, text=True, timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("LOCAL_PROBE_FAILED") from exc
    require(result.returncode == 0, "LOCAL_PROBE_FAILED")
    return result.stdout.strip()


def immutable_runtime(host: str) -> None:
    record = json.loads(run(["docker", "inspect", "smite-node"]))[0]
    require(record["Config"]["Image"] == HOST_IMAGES[host], "NODE_IMAGE_DRIFT")
    require(record["State"].get("Running") is True and
            record["State"].get("Health", {}).get("Status") == "healthy",
            "NODE_NOT_HEALTHY")
    env = set(record["Config"]["Env"])
    for setting in (
        "SMITE_NODE_PANEL_AUTH_MODE=signed",
        "SMITE_AGENT_AUTH_MODE=strict",
        "SMITE_ENGINE_INVENTORY_MODE=managed",
    ):
        require(setting in env, "SIGNED_NODE_POLICY_DRIFT")
    mounts = record.get("Mounts", [])
    config_mount = [m for m in mounts if m.get("Destination") == "/etc/smite-node"]
    require(len(config_mount) == 1 and config_mount[0].get("Type") == "bind"
            and config_mount[0].get("Source") == str(CONFIG)
            and config_mount[0].get("RW") is True, "CONFIG_MOUNT_DRIFT")
    for destination in ("/run/smite-node-identity", "/var/lib/smite-node/auth"):
        require(any(m.get("Destination") == destination for m in mounts),
                "SIGNED_STATE_MOUNT_MISSING")


BINARY_CHECK = r'''
import hashlib, json, os, stat
from pathlib import Path
result={}
for name in ("frpc","frps"):
    path=Path("/usr/local/bin")/name
    s=path.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1
    assert s.st_mode & 0o111 and not s.st_mode & 0o022
    result[name]=hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(result,sort_keys=True,separators=(",",":")))
'''

SIGNED_CHECK = r'''
import json, urllib.request, urllib.error
from app.config import settings
from app.agent_auth import read_identity
from app.node_auth import sign_request
expected=__import__("sys").argv[1]
node_id,secret=read_identity(settings.smite_agent_identity_path)
target="/api/agent/engines"
def request(headers=None):
    q=urllib.request.Request("http://127.0.0.1:8888"+target,
        method="GET",headers=headers or {})
    try:
        with urllib.request.urlopen(q,timeout=6) as r:
            return r.status,r.read()
    except urllib.error.HTTPError as e:
        return e.code,e.read()
assert request()[0]==401
h=sign_request(secret=secret,node_id=node_id,method="GET",target=target,body=b"")
status,body=request(h)
assert status==200
data=json.loads(body)
assert data["mode"]=="managed" and data["engines"]["frp"]==expected
assert request(h)[0]==401
print("SIGNED_FRP_INVENTORY=PASS")
'''



def local_probe(expected: str) -> None:
    source = (
        "from app.engine_inventory import engine_inventory; "
        "doc=engine_inventory(); "
        "print(doc['mode'] + ':' + doc['engines']['frp'])"
    )
    response = run(["docker", "exec", "smite-node", "python3",
                    "-B", "-c", source])
    require(response == "managed:" + expected, "LOCAL_INVENTORY_FAILED")

def binary_attestation() -> None:
    result = json.loads(run(["docker", "exec", "smite-node",
                             "python3", "-B", "-c", BINARY_CHECK]))
    require(result == BINARIES, "FRP_BUNDLE_DIGEST_DRIFT")


def signed_probe(expected: str) -> None:
    value = run(["docker", "exec", "smite-node", "python3", "-B",
                 "-c", SIGNED_CHECK, expected])
    require(value == "SIGNED_FRP_INVENTORY=PASS", "SIGNED_INVENTORY_FAILED")


def host_preflight(host: str) -> dict[str, str]:
    require(os.geteuid() == 0 and host in HOST_IMAGES and
            os.uname().nodename.split(".")[0].lower() == host,
            "WRONG_HOST_OR_USER")
    directory(NODE)
    directory(CONFIG)
    regular(CANDIDATE, mode=0o600, limit=131072)
    identity = regular(IDENTITY, mode=0o600)
    regular(REPLAY, mode=0o600, limit=80 * 1024 * 1024)
    replay_inode = REPLAY.lstat()
    directory(IDENTITY.parent, private=True)
    directory(REPLAY.parent, private=True)
    immutable_runtime(host)
    binary_attestation()
    tunnels = CONFIG / "tunnels.json"
    require(absent(tunnels), "SAVED_TUNNELS_REQUIRE_REVIEW")
    return {"identity_sha256": sha(identity),
            "replay_identity": str(replay_inode.st_dev) + ":" + str(replay_inode.st_ino)}


def unchanged(expected: dict[str, str]) -> None:
    require(sha(regular(IDENTITY, mode=0o600)) == expected["identity_sha256"],
            "IDENTITY_CHANGED")
    # Signed reads legitimately append nonces to the persistent replay DB.
    # Require identity of the same durable inode, not byte-for-byte contents.
    regular(REPLAY, mode=0o600, limit=80 * 1024 * 1024)
    st = REPLAY.lstat()
    require(str(st.st_dev) + ":" + str(st.st_ino)
            == expected["replay_identity"], "REPLAY_STORAGE_REPLACED")
    require(absent(CONFIG / "tunnels.json"), "TUNNELS_CHANGED")


def expected_manifest() -> bytes:
    data = {"schema": 1, "engines": {"frp": {
        "sha256": BINARIES["frpc"], "server_sha256": BINARIES["frps"],
    }}}
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def lock():
    require(not LOCK.is_symlink(), "UNSAFE_SHARED_LOCK")
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    st = os.fstat(fd)
    require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and
            stat.S_IMODE(st.st_mode) == 0o600, "UNSAFE_SHARED_LOCK")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise Hold("ENGINE_TRANSACTION_LOCKED") from exc
    return fd


def write_journal(host: str, proof: dict[str, str]) -> None:
    create_private(JOURNAL_DIR)
    doc = {"schema": 1, "host": host, "state": "PREPARED",
           **proof, "manifest_sha256": sha(expected_manifest())}
    create_file(JOURNAL, (json.dumps(doc, sort_keys=True) + "\n").encode())


def journal(host: str) -> dict:
    directory(JOURNAL_DIR, private=True)
    doc = json.loads(regular(JOURNAL, mode=0o600))
    require(set(doc) == {"schema", "host", "state", "identity_sha256",
                         "replay_identity", "manifest_sha256"}
            and doc["schema"] == 1 and doc["host"] == host
            and doc["state"] == "PREPARED"
            and doc["manifest_sha256"] == sha(expected_manifest())
            and all(re.fullmatch(r"[a-f0-9]{64}", doc[k]) for k in
                    ("identity_sha256",)), "UNTRUSTED_JOURNAL")
    require(re.fullmatch(r"[0-9]+:[0-9]+", doc["replay_identity"]),
            "UNTRUSTED_JOURNAL")
    return doc


def remove_manifest(doc: dict) -> None:
    unchanged(doc)
    if MANIFEST.exists() or MANIFEST.is_symlink():
        require(sha(regular(MANIFEST, mode=0o600)) == doc["manifest_sha256"],
                "MANIFEST_EXTERNAL_DRIFT")
        MANIFEST.unlink()
        fsync_dir(MANIFEST_DIR)
    if MANIFEST_DIR.is_dir() and not any(MANIFEST_DIR.iterdir()):
        MANIFEST_DIR.rmdir()
        fsync_dir(CONFIG)


def clear_journal() -> None:
    JOURNAL.unlink()
    fsync_dir(JOURNAL_DIR)
    JOURNAL_DIR.rmdir()
    fsync_dir(NODE)


def enroll(host: str) -> None:
    fd = lock()
    try:
        proof = host_preflight(host)
        require(absent(JOURNAL_DIR) and absent(MANIFEST), "PREVIOUS_ENROLLMENT_PRESENT")
        require(absent(MANIFEST_DIR), "ENGINE_DIRECTORY_REQUIRES_REVIEW")
        signed_probe("not-installed")
        write_journal(host, proof)
        try:
            create_private(MANIFEST_DIR)
            create_file(MANIFEST, expected_manifest())
            signed_probe("ready")
            unchanged(proof)
        except Exception as exc:
            try:
                remove_manifest(journal(host))
                signed_probe("not-installed")
                clear_journal()
            except Exception as bad:
                raise Hold("CRITICAL_MANUAL_RECOVERY_REQUIRED") from bad
            raise Hold("ENROLLMENT_FAILED_ROLLED_BACK") from exc
        print("RC2_FRP_ENROLLMENT=PASS")
        print("SIGNED_INVENTORY=READY")
        print("NODE_RESTART=NO")
        print("PUBLIC_PORT_CHANGE=NONE")
        print("GENERAL_INSTALLER=NOT_RELEASED")
    finally:
        os.close(fd)


def verify(host: str) -> None:
    host_preflight(host)
    doc = journal(host)
    unchanged(doc)
    require(MANIFEST.is_file() and not MANIFEST.is_symlink(),
            "MANIFEST_CHANGED")
    require(sha(regular(MANIFEST, mode=0o600)) == doc["manifest_sha256"],
            "MANIFEST_CHANGED")
    directory(MANIFEST_DIR, private=True)
    signed_probe("ready")
    print("RC2_FRP_VERIFY=PASS_SIGNED")
    print("NODE_RESTART=NO")
    print("CONFIG_CHANGES=NONE")
    print("SIGNED_PROBE=REPLAY_NONCE_RECORDED")


def rollback(host: str) -> None:
    fd = lock()
    try:
        host_preflight(host)
        doc = journal(host)
        unchanged(doc)
        signed_probe("ready")
        remove_manifest(doc)
        signed_probe("not-installed")
        clear_journal()
        print("RC2_FRP_ROLLBACK=PASS")
        print("NODE_RESTART=NO")
    finally:
        os.close(fd)


def plan(host: str) -> None:
    host_preflight(host)
    require(absent(JOURNAL_DIR) and absent(MANIFEST_DIR) and
            absent(MANIFEST), "EXISTING_ENGINE_STATE")
    # A signed inventory request consumes a durable replay nonce; keep
    # the operator's --plan strictly read-only and defer signed proof to
    # the separately authorized enrollment action.
    local_probe("not-installed")
    print("RC2_FRP_PLAN=PASS_LOCAL_READ_ONLY")
    print("SIGNED_PROBE=PENDING_ENROLLMENT")
    print("NODE_RESTART=NO")
    print("LIVE_CHANGES=NONE")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "enroll", "verify", "rollback"))
    args = parser.parse_args()
    try:
        host = os.uname().nodename.split(".")[0].lower()
        if args.action in ("enroll", "rollback"):
            require(os.environ.get(TRIAL_FLAG) == "YES", "EXPLICIT_TRIAL_FLAG_REQUIRED")
            require(sys.stdin.isatty(), "INTERACTIVE_TERMINAL_REQUIRED")
            require(input("Type " + CONFIRM[args.action] + " to authorize: ").strip()
                    == CONFIRM[args.action], "OPERATOR_CANCELLED")
        {"plan": plan, "enroll": enroll,
         "verify": verify, "rollback": rollback}[args.action](host)
        return 0
    except (Hold, OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError, json.JSONDecodeError) as exc:
        reason = str(exc)
        safe = reason if re.fullmatch(r"[A-Z0-9_]{1,96}", reason) else "UNTRUSTED_HOST_STATE"
        print("HOLD: " + safe, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
