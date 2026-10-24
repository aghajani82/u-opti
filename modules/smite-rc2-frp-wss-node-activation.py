#!/usr/bin/env python3
"""RC.2 signed Smite Node opt-in for FRP WSS/443; IR and KH field trial only.

A narrow separate transaction from the already enrolled FRP binaries and
IR-only Nginx edge. Keep BOTH original Compose + signed security candidate
in *every* recreation. No panel, Nginx, firewall, engine manifest, Xray,
FRP tunnel, identity or replay file writes. Not for a generic U-OPTI release.

Explicit snapshot/console confirmation and TTY grant required to mutate.
The new Compose overlay is persistent and journaled for future recovery.
Operator must keep its -f argument in future manual Node recreations.
"""
from __future__ import annotations

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

NODE = Path("/opt/smite-node")
BASE = NODE / "docker-compose.yml"
SIGNED = NODE / "docker-compose.security-candidate.yml"
OVERLAY_PATH = NODE / "docker-compose.frp-wss-rc2.yml"
STATE_ROOT = Path("/var/lib/u-opti/smite-rc2-frp-wss-node")
LOCK = Path("/run/lock/u-opti-smite-engine.lock")
IDENTITY = Path("/etc/u-opti/smite/identities/node-identity.json")
REPLAY = Path("/var/lib/u-opti/smite-node-security/replay/agent-replay.sqlite3")
MANIFEST = NODE / "config/engine-state/engines.json"
TUNNELS = NODE / "config/tunnels.json"
IMAGES = {
    "ir": "ghcr.io/aghajani82/smite-node@sha256:9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec",
    "kh": "ghcr.io/aghajani82/smite-node@sha256:2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78",
}
WSS_OVERLAY = ("services:\n  smite-node:\n    environment:\n"
               "      - SMITE_FRP_STANDARD_WSS=1\n").encode()
FLAG = "UOPTI_SMITE_RC2_WSS_NODE_TRIAL"
SNAPSHOT = "SNAPSHOTS-AND-CONSOLES-VERIFIED"
CONFIRM = {
    "apply": {"ir": "ACTIVATE-IR-SIGNED-WSS", "kh": "ACTIVATE-KH-SIGNED-WSS"},
    "rollback": {"ir": "ROLLBACK-IR-SIGNED-WSS", "kh": "ROLLBACK-KH-SIGNED-WSS"},
    "recover": {"ir": "RECOVER-IR-SIGNED-WSS", "kh": "RECOVER-KH-SIGNED-WSS"},
}
HERE = Path(__file__).resolve().parent


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, HERE / path)
    if spec is None or spec.loader is None:
        raise Hold("REVIEWED_HELPER_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Hold(Exception):
    pass


def need(ok: bool, reason: str) -> None:
    if not ok:
        raise Hold(reason)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def host() -> str:
    value = os.uname().nodename.split(".")[0].lower()
    need(os.geteuid() == 0 and value in IMAGES, "IR_KH_ROOT_ONLY")
    return value


def trusted(path: Path, limit: int = 1024 * 1024, mode: int | None = None) -> bytes:
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == 0
         and info.st_nlink == 1 and not info.st_mode & 0o022
         and 0 <= info.st_size <= limit, "UNTRUSTED_FILE")
    if mode is not None:
        need(stat.S_IMODE(info.st_mode) == mode, "WRONG_FILE_MODE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        opened = os.fstat(f.fileno())
        need((info.st_ino, info.st_dev) == (opened.st_ino, opened.st_dev),
             "FILE_CHANGED")
        raw = f.read(limit + 1)
    need(len(raw) <= limit, "FILE_TOO_LARGE")
    return raw


def directory(path: Path, private: bool = False) -> None:
    info = path.lstat()
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == 0, "UNTRUSTED_DIRECTORY")
    actual = stat.S_IMODE(info.st_mode)
    need(actual == 0o700 if private else not actual & 0o022,
         "WRONG_DIRECTORY_MODE")


def absent(path: Path) -> bool:
    return not path.exists() and not path.is_symlink()


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def new_file(path: Path, raw: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                 mode)
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), mode)
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    fsync_dir(path.parent)


def mkdir(path: Path) -> None:
    need(absent(path), "STATE_ALREADY_EXISTS")
    directory(path.parent)
    path.mkdir(mode=0o700)
    directory(path, private=True)
    fsync_dir(path.parent)


def lock() -> int:
    need(not LOCK.is_symlink(), "ENGINE_LOCK_SYMLINK")
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    s = os.fstat(fd)
    need(stat.S_ISREG(s.st_mode) and s.st_uid == 0
         and stat.S_IMODE(s.st_mode) == 0o600, "UNTRUSTED_ENGINE_LOCK")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise Hold("ENGINE_OPERATION_LOCKED") from exc
    return fd


def run(argv: list[str], *, input_text: str | None = None,
        timeout: int = 35) -> str:
    try:
        result = subprocess.run(argv, input=input_text, capture_output=True,
                                text=True, timeout=timeout, check=False,
                                cwd=NODE)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("LOCAL_OPERATION_UNAVAILABLE") from exc
    need(result.returncode == 0, "LOCAL_OPERATION_FAILED")
    return result.stdout.strip()


def inspect() -> dict:
    objects = json.loads(run(["docker", "inspect", "smite-node"], timeout=15))
    need(isinstance(objects, list) and len(objects) == 1,
         "UNEXPECTED_NODE_INSPECT")
    return objects[0]


def env(runtime: dict) -> dict[str, str]:
    raw = runtime["Config"]["Env"]
    result = {}
    for line in raw:
        name, value = line.split("=", 1)
        need(name not in result, "DUPLICATE_RUNTIME_ENV")
        result[name] = value
    return result


def signed_health(runtime: dict, role: str, *, enabled: bool) -> None:
    need(runtime.get("Config", {}).get("Image") == IMAGES[role], "NODE_IMAGE_DRIFT")
    need(runtime.get("State", {}).get("Running") is True and
         runtime.get("State", {}).get("Health", {}).get("Status") == "healthy",
         "NODE_NOT_HEALTHY")
    settings = env(runtime)
    for key, expected in {
        "SMITE_NODE_PANEL_AUTH_MODE": "signed",
        "SMITE_AGENT_AUTH_MODE": "strict",
        "SMITE_ENGINE_INVENTORY_MODE": "managed",
    }.items():
        need(settings.get(key) == expected, "SIGNED_POLICY_DRIFT")
    need(settings.get("SMITE_FRP_STANDARD_WSS") == "1" if enabled else
         settings.get("SMITE_FRP_STANDARD_WSS") != "1", "WSS_RUNTIME_DRIFT")
    need(settings.get("PANEL_ADDRESS", "").endswith(":443"), "PANEL_ADDRESS_DRIFT")
    mounts = {m.get("Destination"): m for m in runtime.get("Mounts", [])}
    need(set(mounts) >= {"/etc/smite-node",
                         "/run/smite-node-identity",
                         "/var/lib/smite-node/auth"}, "SIGNED_MOUNT_MISSING")
    need(mounts["/etc/smite-node"].get("Source") == str(NODE / "config") and
         mounts["/etc/smite-node"].get("RW") is True,
         "ENGINE_MANIFEST_MOUNT_DRIFT")
    need(mounts["/run/smite-node-identity"].get("RW") is False and
         mounts["/var/lib/smite-node/auth"].get("RW") is True,
         "IDENTITY_REPLAY_MOUNT_DRIFT")


def compose_names(runtime: dict) -> set[str]:
    labels = runtime.get("Config", {}).get("Labels") or {}
    files = labels.get("com.docker.compose.project.config_files", "")
    return set(x.strip() for x in files.split(",") if x.strip())


def state_file(role: str) -> Path:
    return STATE_ROOT / role / "record.json"


def state_dir(role: str) -> Path:
    return STATE_ROOT / role


def anchor() -> None:
    directory(NODE)
    directory(NODE / "config")
    directory(STATE_ROOT.parent)
    directory(IDENTITY.parent, private=True)
    directory(REPLAY.parent, private=True)


def file_identity(path: Path, mode: int = 0o600,
                  limit: int = 256 * 1024 * 1024) -> tuple[str, str]:
    raw = trusted(path, limit, mode)
    s = path.lstat()
    return sha(raw), f"{s.st_dev}:{s.st_ino}"


def protected() -> dict[str, str]:
    return {
        "base": sha(trusted(BASE, 131072)),
        "signed": sha(trusted(SIGNED, 131072, 0o600)),
        "identity": file_identity(IDENTITY)[0],
        "identity_inode": file_identity(IDENTITY)[1],
        "replay_inode": file_identity(REPLAY)[1],
        "manifest": sha(trusted(MANIFEST, 8192, 0o600)),
    }


def verify_protected(doc: dict) -> None:
    p = protected()
    need(all(p[k] == doc[k] for k in p), "PROTECTED_STATE_DRIFT")
    need(absent(TUNNELS), "SAVED_TUNNELS_PRESENT")


def journal(role: str) -> dict:
    directory(STATE_ROOT, private=True)
    directory(state_dir(role), private=True)
    obj = json.loads(trusted(state_file(role), 16384, 0o600))
    keys = {"schema", "host", "state", "overlay_sha", "image",
            "container_before", *protected().keys()}
    need(isinstance(obj, dict) and set(obj) == keys
         and obj["schema"] == 1 and obj["host"] == role
         and obj["image"] == IMAGES[role]
         and obj["state"] in ("PREPARED", "COMMITTED")
         and obj["overlay_sha"] == sha(WSS_OVERLAY)
         and all(isinstance(obj[k], str) and bool(obj[k])
                 for k in keys - {"schema"}),
         "INVALID_WSS_JOURNAL")
    return obj


def record(role: str, proof: dict[str, str], prior: str) -> None:
    if absent(STATE_ROOT):
        mkdir(STATE_ROOT)
    directory(STATE_ROOT, private=True)
    mkdir(state_dir(role))
    data = {
        "schema": 1, "host": role, "state": "PREPARED",
        "overlay_sha": sha(WSS_OVERLAY), "image": IMAGES[role],
        "container_before": prior, **proof,
    }
    new_file(state_file(role), (json.dumps(data, sort_keys=True) + "\n").encode())


def commit(role: str) -> None:
    obj = journal(role)
    need(obj["state"] == "PREPARED", "ALREADY_COMMITTED")
    doc = dict(obj, state="COMMITTED")
    temp = state_dir(role) / ".commit.next"
    need(absent(temp), "UNRESOLVED_JOURNAL_WRITE")
    new_file(temp, (json.dumps(doc, sort_keys=True) + "\n").encode())
    os.replace(temp, state_file(role))
    fsync_dir(state_dir(role))


def cleanup(role: str) -> None:
    state_file(role).unlink()
    fsync_dir(state_dir(role))
    state_dir(role).rmdir()
    fsync_dir(STATE_ROOT)
    if not list(STATE_ROOT.iterdir()):
        STATE_ROOT.rmdir()
        fsync_dir(STATE_ROOT.parent)


def compose_command(*, enable: bool, args: list[str]) -> list[str]:
    argv = ["docker", "compose", "-f", str(BASE), "-f", str(SIGNED)]
    if enable:
        argv.extend(["-f", str(OVERLAY_PATH)])
    return argv + args


def wait_health(role: str, *, enabled: bool) -> dict:
    import time
    for _ in range(18):
        try:
            obj = inspect()
            signed_health(obj, role, enabled=enabled)
            return obj
        except Hold:
            time.sleep(3)
    raise Hold("SIGNED_NODE_HEALTH_TIMEOUT")


def signed_probe(role: str, *, enabled: bool) -> None:
    enrolled = load("rc2_wss_existing_enrollment", "smite-rc2-frp-bundled-enrollment.py")
    enrolled.signed_probe("ready")
    target = "ir.kolbe1.ir" if enabled else ""
    code = (
        "from app.frp_gateway_config import frp_standard_wss_host; "
        "print(frp_standard_wss_host() or 'OFF')"
    )
    value = run(["docker", "exec", "smite-node", "python3", "-B",
                 "-c", code], timeout=15)
    need(value == (target or "OFF"), "FRP_WSS_RUNTIME_HELPER_DRIFT")


def prerequisite(role: str) -> tuple[dict, dict]:
    anchor()
    need(absent(OVERLAY_PATH), "WSS_OVERLAY_ALREADY_PRESENT")
    need(absent(STATE_ROOT) or absent(state_dir(role)),
         "UNRESOLVED_WSS_NODE_TRANSACTION")
    need(absent(TUNNELS), "SAVED_TUNNELS_PRESENT")
    current = inspect()
    signed_health(current, role, enabled=False)
    files = compose_names(current)
    need(str(BASE) in files and str(SIGNED) in files and
         files == {str(BASE), str(SIGNED)}, "UNREVIEWED_ACTIVE_COMPOSE_SET")
    source = protected()
    plan = load("rc2_wss_existing_plan", "smite-rc2-frp-wss-plan.py")
    original = run(compose_command(enable=False, args=["config", "--format", "json"]))
    proposed = run(["docker", "compose", "-f", str(BASE), "-f", str(SIGNED),
                    "-f", "-", "config", "--format", "json"],
                   input_text=WSS_OVERLAY.decode())
    before = json.loads(original)
    after = json.loads(proposed)
    # Control-plane drift is limited to one opt-in environment value.
    baseline = before["services"]["smite-node"]
    future = after["services"]["smite-node"]
    def without_wss(doc: dict) -> dict:
        result = json.loads(json.dumps(doc))
        en = plan.environ(result.get("environment", {}))
        en.pop("SMITE_FRP_STANDARD_WSS", None)
        result["environment"] = en
        return result
    need(without_wss(baseline) == without_wss(future),
         "COMPOSE_UNEXPECTED_SERVICE_DRIFT")
    plan.validate_preview(current, after, IMAGES[role])
    signed_probe(role, enabled=False)
    return current, source


def recreate(enable: bool) -> None:
    run(compose_command(enable=enable, args=[
        "up", "-d", "--no-build", "--no-deps", "--pull", "never",
        "--force-recreate", "smite-node"
    ]), timeout=120)


def check_runtime(role: str, enable: bool) -> None:
    current = wait_health(role, enabled=enable)
    labels = compose_names(current)
    want = {str(BASE), str(SIGNED)}
    if enable:
        want.add(str(OVERLAY_PATH))
    need(labels == want, "NODE_COMPOSE_SET_DRIFT")
    signed_probe(role, enabled=enable)


def revert(role: str, doc: dict, *, permitted_prepared: bool) -> None:
    need(doc["state"] == ("PREPARED" if permitted_prepared else "COMMITTED"),
         "WRONG_RECOVERY_LANE")
    verify_protected(doc)
    if not absent(OVERLAY_PATH):
        need(sha(trusted(OVERLAY_PATH, 8192, 0o600)) == doc["overlay_sha"],
             "OVERLAY_TAMPERED")
    else:
        need(permitted_prepared, "COMMITTED_OVERLAY_MISSING")
    runtime = inspect()
    signed_health(runtime, role, enabled=env(runtime).get("SMITE_FRP_STANDARD_WSS") == "1")
    # If Node was never recreated, no need to restart a healthy signed Node.
    if env(runtime).get("SMITE_FRP_STANDARD_WSS") == "1":
        recreate(False)
        check_runtime(role, False)
    else:
        signed_probe(role, enabled=False)
    if not absent(OVERLAY_PATH):
        OVERLAY_PATH.unlink()
        fsync_dir(NODE)
    cleanup(role)
    print("WSS_NODE_ROLLBACK_OR_RECOVERY=PASS")
    print("SIGNED_NODE_PRESERVED=YES")
    print("FRP_ENGINE=READY")


def apply(role: str) -> None:
    fd = lock()
    try:
        current, proof = prerequisite(role)
        record(role, proof, current["Id"])
        try:
            new_file(OVERLAY_PATH, WSS_OVERLAY)
            recreate(True)
            check_runtime(role, True)
            verify_protected(journal(role))
            commit(role)
        except Exception as problem:
            try:
                revert(role, journal(role), permitted_prepared=True)
            except Exception as recovery:
                raise Hold("CRITICAL_WSS_NODE_RECOVERY_REQUIRED") from recovery
            raise Hold("WSS_NODE_ACTIVATION_ROLLED_BACK") from problem
        print("RC2_WSS_NODE=COMMITTED")
        print("HOST=" + role.upper())
        print("SIGNED_HMAC_REPLAY=PASS")
        print("FRP_ENGINE=READY")
        print("WSS_HELPER=ENABLED")
        print("PUBLIC_PORTS_UNCHANGED=EXPECTED")
        print("TUNNEL=NOT_CREATED")
    finally:
        os.close(fd)


def verify(role: str) -> None:
    doc = journal(role)
    need(doc["state"] == "COMMITTED", "WSS_NODE_NOT_COMMITTED")
    verify_protected(doc)
    need(sha(trusted(OVERLAY_PATH, 8192, 0o600)) == doc["overlay_sha"],
         "WSS_OVERLAY_DRIFT")
    check_runtime(role, True)
    print("RC2_WSS_NODE_VERIFY=PASS_SIGNED")
    print("HOST=" + role.upper())
    print("FRP_ENGINE=READY")
    print("CONFIG_CHANGES=NONE")
    print("SIGNED_PROBE_REPLAY_NONCE=RECORDED")


def rollback(role: str) -> None:
    fd = lock()
    try:
        doc = journal(role)
        revert(role, doc, permitted_prepared=False)
    finally:
        os.close(fd)


def recover(role: str) -> None:
    fd = lock()
    try:
        doc = journal(role)
        revert(role, doc, permitted_prepared=True)
    finally:
        os.close(fd)


def main() -> int:
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("action", choices=("plan", "apply", "verify",
                                        "rollback", "recover"))
    arg.add_argument("--confirm-snapshot", default="")
    args = arg.parse_args()
    try:
        role = host()
        if args.action in ("apply", "rollback", "recover"):
            need(os.environ.get(FLAG) == "YES", "EXPLICIT_RC2_TRIAL_FLAG_REQUIRED")
            need(args.confirm_snapshot == SNAPSHOT,
                 "SNAPSHOT_CONSOLE_ACK_REQUIRED")
            need(sys.stdin.isatty(), "INTERACTIVE_TERMINAL_REQUIRED")
            need(input("Type " + CONFIRM[args.action][role] + " to authorize: ").strip()
                 == CONFIRM[args.action][role], "OPERATOR_CANCELLED")
        if args.action == "plan":
            prerequisite(role)
            print("RC2_WSS_NODE_PLAN=PASS_READ_ONLY")
            print("HOST=" + role.upper())
            print("SIGNED_SECURITY_OVERLAY=PRESERVED")
            print("LIVE_CHANGES=NONE")
        elif args.action == "apply":
            apply(role)
        elif args.action == "verify":
            verify(role)
        elif args.action == "rollback":
            rollback(role)
        else:
            recover(role)
        return 0
    except (Hold, OSError, ValueError, KeyError, TypeError, IndexError,
            UnicodeError, subprocess.SubprocessError, json.JSONDecodeError) as err:
        value = str(err)
        if not re.fullmatch(r"[A-Z0-9_]{1,96}", value):
            value = "UNTRUSTED_RC2_SIGNED_WSS_STATE"
        print("HOLD: " + value, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
