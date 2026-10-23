#!/usr/bin/env python3
"""KH-only, fail-closed RC.1 -> RC.2 paused Smite Node Field Trial.

Default --plan is read-only. --apply requires a separate explicit host
confirmation and environment opt-in and is NOT enabled by any existing menu.
Never changes KH foreign pairing, its Node registration mode, Sanaei/XHTTP,
Nginx, local tunnel config, managed version or IR Panel.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
COMPOSE = Path("/opt/smite-node/docker-compose.yml")
BACKUP_DIR = Path("/root/kh-sanaei-pre-rc2-20261023T150429Z")
LOCK = Path("/run/lock/uopti-kh-node-rc2.lock")
ORIGINAL_SHA = "ab0f360f288c4659a52ec5e4f5b67afd22ec21dcc29a328d72cd8829b91eae6f"
CANDIDATE_SHA = "8339ee07dcc3fe68da65dd8cb993b11d8da20b69b0470c032f8d504b0ea9de4e"
MANIFEST_SHA = "63e3efbdec955e92deaf0a84c86cc5c8a950f48b4e0d6d301bc7f7c8354eb80b"
SOURCE_SHA = "e6c3ecce81010130ae28e7d1e37ea99b31d70c28"
PUBLISH_REF = "refs/tags/v2.0.0-rc.2"
COSIGN_SHA = "c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74"
KH_GATEWAY_DOMAIN = "kh.kolbe1.ir"
IR_PANEL_DOMAIN = "ir.kolbe1.ir"
OLD_COPY = BACKUP_DIR / "kh-node-compose.before-rc2.yml"
SECURITY = {
    "SMITE_AGENT_AUTH_MODE": "strict",
    "SMITE_NODE_PANEL_AUTH_MODE": "paused",
    "SMITE_ENGINE_INVENTORY_MODE": "managed",
}


class Hold(Exception):
    pass


def require(ok: bool, why: str) -> None:
    if not ok:
        raise Hold(why)


def helper(filename: str, module: str):
    target = HERE / filename
    require(target.is_file() and not target.is_symlink(), "Reviewed helper missing")
    spec = importlib.util.spec_from_file_location(module, target)
    require(spec is not None and spec.loader is not None, "Invalid reviewed helper")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run(command: list[str], *, timeout: int = 40) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("Host command failed or timed out") from exc
    # Never expose stderr, stdout or interpolated Compose environment in errors.
    require(result.returncode == 0, "Host command rejected")
    require(len(result.stdout) < 1_000_000, "Host command returned excess data")
    return result.stdout.strip()


def read_regular(path: Path, *, limit: int = 262144) -> bytes:
    try:
        before = path.lstat()
        require(
            stat.S_ISREG(before.st_mode) and before.st_uid == 0
            and before.st_nlink == 1 and not (before.st_mode & 0o022)
            and before.st_size <= limit,
            "Reviewed file metadata unsafe",
        )
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            require(
                (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)
                and opened.st_uid == 0 and opened.st_nlink == 1
                and opened.st_size <= limit,
                "Reviewed file changed",
            )
            content = stream.read(limit + 1)
        require(len(content) <= limit, "Reviewed file exceeded size limit")
        return content
    except OSError as exc:
        raise Hold("Reviewed file unavailable") from exc


def compose_effective() -> dict:
    raw = run(["docker", "compose", "-f", str(COMPOSE), "config", "--format", "json"])
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Hold("Effective KH Compose invalid") from exc
    require(isinstance(doc, dict) and isinstance(doc.get("services"), dict),
            "Expected KH Compose services missing")
    return doc


def only_image_changed(before: dict, after: dict, *, source: str, target: str) -> None:
    require(before["services"]["smite-node"]["image"] == source,
            "Original Node image not approved")
    require(after["services"]["smite-node"]["image"] == target,
            "Proposed Node image not approved")
    expected = json.loads(json.dumps(before))
    expected["services"]["smite-node"]["image"] = target
    require(after == expected, "Effective KH Compose changed outside Node image")
    env = after["services"]["smite-node"].get("environment")
    require(isinstance(env, dict), "Node environment unavailable")
    for key, value in SECURITY.items():
        require(env.get(key) == value, "Node paused/strict/managed security changed")


def signatures(registry, planner) -> None:
    verifier = Path("/usr/local/bin/cosign")
    require(
        verifier.is_file() and not verifier.is_symlink()
        and hashlib.sha256(read_regular(verifier, limit=40_000_000)).hexdigest() == COSIGN_SHA,
        "Pinned Cosign executable invalid",
    )
    result = registry.verify_pair(
        manifest=HERE / "smite-rc2-signed-registry-candidate.json",
        manifest_sha256=MANIFEST_SHA,
        source_sha=SOURCE_SHA,
        publish_ref=PUBLISH_REF,
    )
    require(result["images"]["node"] == planner.RC2_NODE,
            "Verified RC.2 Node digest does not match rollout")


def runtime_node(expected_image: str, planner) -> None:
    require(run(["docker", "inspect", "-f", "{{.Config.Image}}", "smite-node"])
            == expected_image, "Node image unexpectedly changed")
    require(run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "smite-node"])
            == "healthy", "Node is not healthy")
    flags = run(["docker", "inspect", "-f",
                 "{{range .Config.Env}}{{println .}}{{end}}", "smite-node"])
    for key, value in SECURITY.items():
        require((key + "=" + value) in flags.splitlines(),
                "Node security mode mismatch")
    run(["curl", "--noproxy", "*", "--fail", "--silent", "--show-error",
         "--max-time", "8", "-o", "/dev/null", "http://127.0.0.1:8888/healthz"],
        timeout=12)
    listeners = run(["ss", "-H", "-lnt"])
    found = [line.split()[3] for line in listeners.splitlines()
             if len(line.split()) >= 4 and line.split()[3].endswith(":8888")]
    require(found and all(v in ("127.0.0.1:8888", "[::1]:8888") for v in found),
            "Node 8888 unexpectedly public")
    require(run(["docker", "inspect", "-f", "{{.Image}}", "3xui-01"])
            == planner.SANAEI_IMAGE, "Sanaei original image changed")
    require(run(["docker", "inspect", "-f", "{{.State.Status}}", "3xui-01"])
            == "running", "Sanaei no longer running")
    run(["nginx", "-t"])
    output = run(["python3", "-B",
                  "/usr/local/lib/u-opti/modules/docker-3xui-xhttp-guard.py",
                  "--instance", "01", "--check"])
    require("XHTTP_REVIEW=PASS" in output and "ROUTES=1" in output
            and "LEGACY_ROUTE=NO" in output, "KH XHTTP route drift")
    run(["curl", "--noproxy", "*", "--fail", "--silent", "--show-error",
         "--max-time", "15", "-o", "/dev/null",
         "https://" + IR_PANEL_DOMAIN + "/api/status"], timeout=19)


def preflight(planner) -> tuple[bytes, bytes, dict]:
    planner.audit()
    original = read_regular(COMPOSE)
    require(hashlib.sha256(original).hexdigest() == ORIGINAL_SHA,
            "Original KH Compose digest mismatch")
    candidate = planner.exact_node_image_plan(original)
    require(hashlib.sha256(candidate).hexdigest() == CANDIDATE_SHA,
            "Planned KH RC.2 Compose differs from reviewed operator output")
    before = compose_effective()
    require(before["services"]["smite-node"]["image"] == planner.RC1_NODE,
            "Live KH Compose no longer RC.1")
    runtime_node(planner.RC1_NODE, planner)
    return original, candidate, before


def atomic_write(path: Path, data: bytes) -> None:
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and
            before.st_nlink == 1, "Cannot replace unsafe KH Compose")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".uopti-kh-rc2-")
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(before.st_mode))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def save_original(original: bytes) -> None:
    before = BACKUP_DIR.lstat()
    require(
        stat.S_ISDIR(before.st_mode) and before.st_uid == 0
        and stat.S_IMODE(before.st_mode) == 0o700,
        "KH root-private backup directory unsafe",
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(OLD_COPY, flags, 0o600)
    except OSError as exc:
        raise Hold("Original KH Compose already saved or backup unsafe") from exc
    with os.fdopen(fd, "wb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())


def recreate_node() -> None:
    run([
        "docker", "compose", "-f", str(COMPOSE),
        "up", "-d", "--no-deps", "--no-build",
        "--pull", "never", "--force-recreate", "smite-node",
    ], timeout=165)


def wait_node(image: str, *, timeout: int = 110) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            current = run(["docker", "inspect", "-f", "{{.Config.Image}}", "smite-node"])
            health = run(["docker", "inspect", "-f",
                          "{{.State.Health.Status}}", "smite-node"])
            if current == image and health == "healthy":
                return
        except Hold:
            pass
        time.sleep(3)
    raise Hold("KH Node did not become healthy with expected signed image")


def apply(planner, registry) -> None:
    require(
        os.environ.get("UOPTI_SMITE_KH_RC2_NODE_FIELD_TRIAL") == "YES",
        "Explicit KH-only Field Trial opt-in missing",
    )
    require(os.geteuid() == 0, "Root required")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lockfd = os.open(
        LOCK, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(lockfd, "w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise Hold("Another KH Node upgrade is running") from exc

        old, new, before = preflight(planner)
        signatures(registry, planner)
        run(["docker", "pull", planner.RC2_NODE], timeout=180)
        run(["docker", "image", "inspect", planner.RC2_NODE], timeout=20)
        require(read_regular(COMPOSE) == old, "KH Compose changed before cutover")
        runtime_node(planner.RC1_NODE, planner)
        save_original(old)

        attempted_recreate = False
        # os.replace can commit before a subsequent directory fsync failure.
        try:
            atomic_write(COMPOSE, new)
            after = compose_effective()
            only_image_changed(before, after, source=planner.RC1_NODE, target=planner.RC2_NODE)
            attempted_recreate = True
            recreate_node()
            wait_node(planner.RC2_NODE)
            runtime_node(planner.RC2_NODE, planner)
        except Exception as exc:
            try:
                atomic_write(COMPOSE, old)
                require(hashlib.sha256(read_regular(COMPOSE)).hexdigest()
                        == ORIGINAL_SHA, "Original KH Compose rollback digest wrong")
                if attempted_recreate:
                    recreate_node()
                    wait_node(planner.RC1_NODE)
                runtime_node(planner.RC1_NODE, planner)
            except Exception as rollback_error:
                raise Hold(
                    "CRITICAL: KH Node image trial failed and RC.1 recovery NOT proven; "
                    "halt and use preserved backup/snapshot"
                ) from rollback_error
            raise Hold(
                "KH Node RC.2 trial failed; original RC.1 Node and Compose "
                "restored and independently verified"
            ) from exc

        print("KH_NODE_RC2_TRIAL=PASS")
        print("KH_NODE_SECURITY=PAUSED_STRICT_MANAGED")
        print("KH_NODE_8888=LOOPBACK_ONLY")
        print("KH_SANAEI_XHTTP=UNCHANGED")
        print("KH_TO_IR_PANEL_HTTPS=PASS")
        print("KH_NODE_COMPOSE_SHA256=" + hashlib.sha256(read_regular(COMPOSE)).hexdigest())
        print("KH_FOREIGN_PAIRING=NOT_ACTIVATED")
        print("MANAGED_VERSION=RC1_RETAINED_DURING_MIXED_TRIAL")
        print("NO_SQLITE_OR_REPLAY_RESTORE=YES")
        print("PRODUCTION_RELEASE_APPROVED=NO")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm-kh-host", default="")
    a = p.parse_args(argv)
    print("===== KH RC2 NODE-ONLY FIELD TRIAL =====")
    try:
        require(not (a.plan and a.apply), "Choose plan OR apply")
        require(os.geteuid() == 0, "Root required")
        planner = helper("smite-rc2-kh-node-plan.py", "kh_rc2_plan")
        if a.apply:
            require(a.confirm_kh_host == KH_GATEWAY_DOMAIN,
                    "Explicit exact KH domain confirmation required")
            registry = helper("smite-registry-pair-admission.py", "kh_rc2_registry")
            apply(planner, registry)
        else:
            old, new, _before = preflight(planner)
            print("KH_ORIGINAL_COMPOSE_SHA256=" + hashlib.sha256(old).hexdigest())
            print("KH_PROPOSED_COMPOSE_SHA256=" + hashlib.sha256(new).hexdigest())
            print("KH_NODE_SECURITY=PAUSED_STRICT_MANAGED")
            print("KH_FOREIGN_PAIRING=NOT_ACTIVATED")
            print("KH_RC2_UPGRADE_AUTHORIZED=NO")
            print("LIVE_CHANGES=NONE")
        return 0
    except (Hold, OSError, ValueError, TypeError, KeyError) as exc:
        # Summaries only: never expose Panel secrets, paired identities or Docker env.
        print("KH_RC2_NODE_TRIAL=HOLD")
        print("REASON=" + str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
