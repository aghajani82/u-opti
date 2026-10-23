#!/usr/bin/env python3
"""Opt-in, bounded, IR-only Smite RC.2 Panel image trial, with RC.1 rollback.

Default --plan cannot mutate the host. --apply is a separate operator action,
requiring BOTH a literal confirmation argument and environment opt-in.
It is experimental source on a DRAFT U-OPTI branch, NOT production approval.
It never restarts the local signed IR Node, KH, Sanaei, Nginx, FRP or Backhaul.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
import time

HERE = Path(__file__).resolve().parent
PANEL_COMPOSE = Path("/opt/smite/docker-compose.yml")
OVERLAY = Path("/opt/smite/docker-compose.signed-control.yml")
STATE = Path("/etc/u-opti/smite/state.env")
IDENTITY = Path("/etc/u-opti/smite/identities/node-identity.json")
BACKUP_DIR = Path("/root/ir-smite-pre-rc2-20261023T151016Z")
BACKUP_HASHES = {
    "smite.db": "8b7fb3a5681811f850df0f61b5477928b1940eb19d0ffb94632402c9f2489420",
    "agent-replay.sqlite3": "17a5845061e31144115cc171230643a7a249edd9b87435a1f39d6e70c579a8fc",
    "ir-private-config.tar.gz": "90849b1be778b5ae12f3347ecc87e51c415e83d02ffabb61b30102f324851e67",
}
MANIFEST_SHA = "63e3efbdec955e92deaf0a84c86cc5c8a950f48b4e0d6d301bc7f7c8354eb80b"
SOURCE_SHA = "e6c3ecce81010130ae28e7d1e37ea99b31d70c28"
PUBLISH_REF = "refs/tags/v2.0.0-rc.2"
COSIGN_BIN_SHA = "c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74"
LOCK = Path("/run/lock/uopti-ir-panel-rc2.lock")
PANEL_HOST = "ir.kolbe1.ir"


class Hold(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Hold(message)


def load_helper(filename: str, module_name: str):
    path = HERE / filename
    require(path.is_file() and not path.is_symlink(), "Reviewed helper missing")
    spec = importlib.util.spec_from_file_location(module_name, path)
    require(spec is not None and spec.loader is not None, "Cannot inspect helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(args: list[str], *, timeout: int = 60) -> str:
    try:
        completed = subprocess.run(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=timeout,
            check=False, env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("Required operation unavailable") from exc
    # Do not leak Docker Compose env interpolation or credentials via stderr.
    require(completed.returncode == 0, "Required operation returned non-zero")
    require(len(completed.stdout) <= 2_000_000, "Unexpected large output")
    return completed.stdout.strip()


def safe_file(path: Path, *, size: int = 262144) -> bytes:
    try:
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o022,
                "Unsafe file type or mode")
        require(info.st_size <= size, "File exceeds safe limit")
        return path.read_bytes()
    except OSError as exc:
        raise Hold("Required file missing") from exc


def baseline_state() -> None:
    values = {}
    for line in safe_file(STATE, size=8192).decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        require(bool(sep) and key not in values, "Invalid managed state")
        values[key] = value
    require(
        values.get("SMITE_ROLE") == "panel-iran"
        and values.get("SMITE_CONNECTION_MODE") == "standard"
        and values.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.1"
        and values.get("SMITE_PANEL_DOMAIN") == PANEL_HOST,
        "This operator action is for the exact IR RC.1 Standard role only",
    )


def check_backups() -> None:
    try:
        info = BACKUP_DIR.lstat()
    except OSError as exc:
        raise Hold("IR backup directory unavailable") from exc
    require(
        stat.S_ISDIR(info.st_mode) and info.st_uid == 0
        and stat.S_IMODE(info.st_mode) == 0o700,
        "IR backup directory ownership/mode unsafe",
    )
    for name, digest in BACKUP_HASHES.items():
        path = BACKUP_DIR / name
        contents = safe_file(path, size=128 * 1024 * 1024)
        require(hashlib.sha256(contents).hexdigest() == digest,
                "One reviewed IR backup checksum changed")
    require(
        run(["tar", "-tzf", str(BACKUP_DIR / "ir-private-config.tar.gz")],
            timeout=15) is not None,
        "IR private archive unreadable",
    )


def reviewed_manifest(registry) -> None:
    result = registry.verify_pair(
        manifest=HERE / "smite-rc2-signed-registry-candidate.json",
        manifest_sha256=MANIFEST_SHA, source_sha=SOURCE_SHA,
        publish_ref=PUBLISH_REF,
    )
    require(
        result["images"]["panel"] == load_helper(
            "smite-rc2-panel-compose-review.py", "uopti_panel_dryrun_verify"
        ).RC2_PANEL,
        "Signature-admitted candidate Panel mismatch",
    )


def checked_cosign(registry) -> None:
    binary = Path("/usr/local/bin/cosign")
    require(
        binary.is_file() and not binary.is_symlink()
        and hashlib.sha256(binary.read_bytes()).hexdigest() == COSIGN_BIN_SHA,
        "On-host pinned Cosign verifier missing or changed",
    )
    reviewed_manifest(registry)


def read_only_config() -> dict:
    raw = run([
        "docker", "compose", "-f", str(PANEL_COMPOSE),
        "-f", str(OVERLAY), "config", "--format", "json",
    ])
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise Hold("Combined Compose JSON invalid") from exc
    require(isinstance(doc, dict), "Combined Compose unavailable")
    return doc


def signed_node_id() -> str:
    try:
        data = json.loads(safe_file(IDENTITY, size=4096))
    except (UnicodeError, ValueError) as exc:
        raise Hold("Signed IR Node identity unreadable") from exc
    node_id = data.get("node_id")
    require(isinstance(node_id, str)
            and bool(re.fullmatch(r"[A-Za-z0-9_-]{8,80}", node_id)),
            "Signed IR Node identity invalid")
    return node_id


SIGNED_PROBE_SCRIPT = (
    "import asyncio,sys; "
    "from app.node_client import NodeClient; "
    "result=asyncio.run(NodeClient().get_tunnel_status(sys.argv[1])); "
    "assert isinstance(result,dict) and result.get('status')=='ok'; "
    "print('SIGNED_PANEL_TO_IR_NODE=PASS')"
)
FOREIGN_PREFIX_SCRIPT = (
    "from app.signed_agent_transport import validate_foreign_gateway_prefix;"
    "result=validate_foreign_gateway_prefix("
    "origin='https://kh.example.net:443',"
    "control_url='https://kh.example.net/smite-node/0123456789abcdef');"
    "assert result=='https://kh.example.net:443/smite-node/0123456789abcdef';"
    "print('RC2_FOREIGN_PREFIX_ROUTER=PASS')"
)


def runtime_probe(*, node_id: str, target_image: str,
                  check_foreign_prefix: bool) -> None:
    require(
        run(["docker", "inspect", "-f", "{{.Config.Image}}", "smite-panel"])
        == target_image, "Panel runtime image digest unexpected",
    )
    require(
        run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "smite-panel"])
        == "healthy", "Panel did not become healthy",
    )
    run(["docker", "exec", "smite-panel", "python3", "-c",
         SIGNED_PROBE_SCRIPT, node_id], timeout=35)
    if check_foreign_prefix:
        require(
            run(["docker", "exec", "smite-panel", "python3", "-c",
                 FOREIGN_PREFIX_SCRIPT], timeout=20)
            == "RC2_FOREIGN_PREFIX_ROUTER=PASS",
            "RC.2 approved KH prefix router not available",
        )
    run(["curl", "--noproxy", "*", "-4", "--fail", "--silent",
         "--show-error", "--max-time", "15",
         "https://" + PANEL_HOST + "/api/status"], timeout=20)


def verify_node_unchanged(planner) -> None:
    require(
        run(["docker", "inspect", "-f", "{{.Config.Image}}", "smite-node"])
        == planner.RC1_NODE,
        "Local signed Node image changed unexpectedly",
    )
    require(
        run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "smite-node"])
        == "healthy",
        "Local signed IR Node is no longer healthy",
    )


def preflight(planner) -> tuple[bytes, bytes, dict, str]:
    baseline_state()
    check_backups()
    info = planner.review(compose=PANEL_COMPOSE, overlay=OVERLAY,
                          execute=run)
    require("IR_SIGNED_COMPOSE_EFFECTIVE=VERIFIED" in info,
            "IR signed Compose review failed")
    original = safe_file(PANEL_COMPOSE)
    proposed = planner.plan_exact_panel_image_replacement(original)
    require(
        hashlib.sha256(proposed).hexdigest()
        == "adc4dfb3031d5f2b5c007241589ed96fe9679ac2df29da62853192c7d716ca5a",
        "Proposed single-line IR Panel image patch differs from operator dry-run",
    )
    before = read_only_config()
    planner.validate_combined_compose(before)
    node_id = signed_node_id()
    verify_node_unchanged(planner)
    return original, proposed, before, node_id


def change_atomically(path: Path, new_bytes: bytes) -> None:
    require(path.is_file() and not path.is_symlink(),
            "Destination Compose file unsafe")
    info = path.stat()
    require(info.st_uid == 0 and stat.S_ISREG(info.st_mode),
            "Destination Compose owner unsafe")
    fd, tmp = tempfile.mkstemp(prefix=".uopti-ir-rc2-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode))
            output.write(new_bytes)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
        dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def save_rollback_copy(contents: bytes) -> Path:
    path = BACKUP_DIR / "panel-compose.before-rc2.yml"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise Hold("Existing rollback copy or unsafe target; manual reconciliation needed") from exc
    with os.fdopen(fd, "wb") as dest:
        dest.write(contents)
        dest.flush()
        os.fsync(dest.fileno())
    return path


def wait_panel_health(*, target_image: str, timeout: int = 110) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            image = run(["docker", "inspect", "-f", "{{.Config.Image}}", "smite-panel"])
            healthy = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "smite-panel"])
            if image == target_image and healthy == "healthy":
                return
        except Hold:
            pass
        time.sleep(3)
    raise Hold("Panel did not report expected healthy immutable image")


def recreate_panel_only() -> None:
    run([
        "docker", "compose", "-f", str(PANEL_COMPOSE), "-f", str(OVERLAY),
        "up", "-d", "--no-build", "--no-deps", "--pull", "never",
        "--force-recreate", "smite-panel",
    ], timeout=150)


def apply(planner, registry) -> None:
    require(
        os.environ.get("UOPTI_SMITE_IR_RC2_PANEL_FIELD_TRIAL") == "YES",
        "Explicit IR Panel-only disposable Field Trial authorization missing",
    )
    require(os.geteuid() == 0, "Root required for reviewed cutover")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(LOCK, flags, 0o600)
    except OSError as exc:
        raise Hold("IR cutover lock unavailable") from exc
    with os.fdopen(descriptor, "w") as locked:
        try:
            fcntl.flock(locked.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise Hold("Another migration is already operating") from exc

        original, proposed, before, node_id = preflight(planner)
        runtime_probe(node_id=node_id, target_image=planner.RC1_PANEL,
                      check_foreign_prefix=False)
        checked_cosign(registry)
        # Image pull is allowed only within the explicit --apply transaction.
        run(["docker", "pull", planner.RC2_PANEL], timeout=180)
        run(["docker", "image", "inspect", planner.RC2_PANEL], timeout=10)
        require(
            safe_file(PANEL_COMPOSE) == original,
            "Panel Compose changed between preflight and commit",
        )
        save_rollback_copy(original)
        attempted_recreate = False
        changed_compose = False
        try:
            change_atomically(PANEL_COMPOSE, proposed)
            changed_compose = True
            after = read_only_config()
            planner.validate_combined_compose(after, expected_image=planner.RC2_PANEL)
            expected = json.loads(json.dumps(before))
            expected["services"]["smite-panel"]["image"] = planner.RC2_PANEL
            require(after == expected, "Effective Compose changed beyond Panel image")
            attempted_recreate = True
            recreate_panel_only()
            wait_panel_health(target_image=planner.RC2_PANEL)
            runtime_probe(node_id=node_id, target_image=planner.RC2_PANEL,
                          check_foreign_prefix=True)
            verify_node_unchanged(planner)
        except Exception as exc:
            if changed_compose:
                rollback_ok = False
                try:
                    change_atomically(PANEL_COMPOSE, original)
                    require(
                        hashlib.sha256(safe_file(PANEL_COMPOSE)).hexdigest()
                        == planner.KNOWN_HASHES["panel"],
                        "Restored Compose digest incorrect",
                    )
                    if attempted_recreate:
                        recreate_panel_only()
                        wait_panel_health(target_image=planner.RC1_PANEL)
                        runtime_probe(node_id=node_id, target_image=planner.RC1_PANEL,
                                      check_foreign_prefix=False)
                    verify_node_unchanged(planner)
                    rollback_ok = True
                except Exception:
                    pass
                if not rollback_ok:
                    raise Hold(
                        "CRITICAL: IR Panel cutover failed and rollback NOT verified; "
                        "halt trial and use saved Compose/provider snapshot"
                    ) from exc
                raise Hold(
                    "IR Panel RC.2 cutover failed; exact RC.1 Compose restored, "
                    "runtime rollback verified where recreation was attempted"
                ) from exc
            raise Hold("IR Panel RC.2 cutover held before Compose mutation") from exc

        print("IR_PANEL_RC2_TRIAL=PASS")
        print("IR_SIGNED_NODE_RC1=UNCHANGED")
        print("IR_PANEL_TO_NODE_SIGNED_HMAC=PASS")
        print("IR_FOREIGN_PREFIX_ROUTER=READY")
        print("IR_PANEL_BASE_COMPOSE_SHA256="
              + hashlib.sha256(safe_file(PANEL_COMPOSE)).hexdigest())
        print("MANAGED_VERSION=RC1_RETAINED_DURING_MIXED_TRIAL")
        print("NO_SQLITE_RESTORATION_OR_REPLAY_RESET=YES")
        print("KH_AND_SANAEI=UNTOUCHED")
        print("PRODUCTION_RELEASE_APPROVED=NO")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", action="store_true", help="Read-only default")
    p.add_argument("--apply", action="store_true", help="Explicit IR-only trial")
    p.add_argument("--confirm-ir-host", default="", help="Exact managed IR Panel hostname")
    args = p.parse_args(argv)
    print("===== RC2 IR PANEL-ONLY FIELD TRIAL =====")
    try:
        require(not (args.plan and args.apply), "Choose plan OR apply")
        planner = load_helper(
            "smite-rc2-panel-compose-review.py", "uopti_rc2_panel_review"
        )
        require(os.geteuid() == 0, "Root required for safe admission")
        if args.apply:
            require(
                args.confirm_ir_host == PANEL_HOST,
                "Exact IR hostname confirmation required",
            )
            registry = load_helper(
                "smite-registry-pair-admission.py", "uopti_rc2_signed_registry"
            )
            apply(planner, registry)
        else:
            original, proposed, _before, _node_id = preflight(planner)
            print("IR_CURRENT_COMPOSE_SHA256=" + hashlib.sha256(original).hexdigest())
            print("IR_PROPOSED_COMPOSE_SHA256=" + hashlib.sha256(proposed).hexdigest())
            print("IR_ONLY_PANEL_IMAGE_LINE_CHANGE=PASS")
            print("IR_PANEL_BASELINE_SIGNED=PASS")
            print("RC2_DEPLOYMENT_AUTHORIZED=NO")
            print("LIVE_CHANGES=NONE")
        return 0
    except (Hold, ValueError, TypeError, OSError) as exc:
        # Errors are internal constants only; never include secrets, JWTs,
        # Compose YAML, raw subprocess stderr or signed payloads.
        print("IR_RC2_PANEL_TRIAL=HOLD")
        print("REASON=" + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
