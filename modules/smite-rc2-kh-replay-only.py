#!/usr/bin/env python3
"""KH RC.2 Replay-only enrollment. Never activates Node or modifies Compose.

--plan is read-only; --apply is an explicitly gated ONE-TIME offline
provision; --verify independently checks durable enrollment. This module
does not offer rollback, key rotation, replay reset, or a rescue shortcut.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import os
from pathlib import Path
import socket
import stat
import sys

HERE = Path(__file__).resolve().parent
PAIRING = HERE / "smite-node-pairing.py"
ADMISSION = HERE / "smite-rc2-foreign-pairing-admission.py"
PAIRING_BLOB = "861e2735f76bb0b3947ab89e0b0bc28fde31c52c"
ADMISSION_BLOB = "67d4621b88c6f795573e60b5014c9d64bd6521bc"
EXPECTED_ADMISSION = [
    "KH_NODE_RC2_PAUSED=PASS",
    "KH_GATEWAY_TLS443=PASS",
    "KH_SANAEI_XHTTP=UNCHANGED",
    "KH_TO_IR_HTTPS=PASS",
    "KH_FOREIGN_SIGNED_RUNTIME=NOT_ACTIVATED",
]


class Hold(Exception):
    """Sanitized refusal: never place source file contents or secrets in text."""


def require(value, label):
    if not value:
        raise Hold(label)


def load_checked(path: Path, sha: str, name: str):
    """Validate root-private reviewed Git blob BEFORE executing source."""
    try:
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0
                and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_nlink == 1 and before.st_size <= 100000,
                "REVIEWED_SOURCE_PERMISSIONS")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            require((opened.st_dev, opened.st_ino) ==
                    (before.st_dev, before.st_ino), "SOURCE_CHANGED")
            blob = stream.read(100001)
        require(len(blob) <= 100000, "SOURCE_TOO_LARGE")
        envelope = b"blob " + str(len(blob)).encode("ascii") + b"\0" + blob
        require(hashlib.sha1(envelope).hexdigest() == sha, "SOURCE_HASH_DRIFT")
    except OSError as exc:
        raise Hold("SOURCE_UNAVAILABLE") from exc
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "SOURCE_IMPORT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def entry(path: Path):
    """Distinguish missing, including dangling symlinks, from unsafe entries."""
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def private_tree(replay_dir: Path, *, create: bool = False):
    """Inspect existing private parents; create only during approved --apply."""
    anchor = replay_dir.parents[2]
    require(anchor == Path("/var/lib"), "REPLAY_ROOT_DRIFT")
    base = entry(anchor)
    require(base is not None and stat.S_ISDIR(base.st_mode)
            and base.st_uid == 0
            and not (stat.S_IMODE(base.st_mode) & 0o022),
            "REPLAY_ANCHOR_UNSAFE")
    components = (replay_dir.parents[1], replay_dir.parent, replay_dir)
    missing = False
    for component in components:
        info = entry(component)
        if info is None:
            missing = True
            if create:
                component.mkdir(mode=0o700)
                info = entry(component)
            else:
                continue
        else:
            require(not missing, "REPLAY_PARENT_PARTIAL_DRIFT")
        require(info is not None and stat.S_ISDIR(info.st_mode)
                and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700,
                "REPLAY_DIRECTORY_UNSAFE")
    return entry(replay_dir) is not None


def replay_state(pairing) -> str:
    """No file creation; refuse *any* partial, symlink or quarantine state."""
    directory = pairing.IDENTITY_DIR
    d = entry(directory)
    require(d is not None and stat.S_ISDIR(d.st_mode)
            and d.st_uid == 0 and stat.S_IMODE(d.st_mode) == 0o700,
            "IDENTITY_DIRECTORY_DRIFT")
    identity = entry(pairing.IDENTITY_FILE)
    require(identity is not None and stat.S_ISREG(identity.st_mode)
            and identity.st_uid == 0 and stat.S_IMODE(identity.st_mode) == 0o600
            and identity.st_nlink == 1, "IDENTITY_FILE_UNSAFE")
    node_id, key = pairing._identity_record()
    require(bool(node_id and key), "IDENTITY_INVALID")
    require(entry(directory / "replay-restore-hold.json") is None,
            "REPLAY_RESTORE_QUARANTINED")
    marker = entry(directory / "replay-enrollment.json")
    db = entry(pairing.REPLAY_DB)
    ready_dir = private_tree(pairing.REPLAY_DIR)
    if (marker is None) != (db is None):
        raise Hold("REPLAY_PARTIAL_STATE")
    if marker is None:
        if ready_dir:
            # An unexplained leftover file might be a SQLite journal or
            # interrupted enrollment. Never overwrite or clean it automatically.
            require(not any(pairing.REPLAY_DIR.iterdir()),
                    "REPLAY_DIRECTORY_NONEMPTY")
        return "ABSENT"
    require(ready_dir, "REPLAY_DIRECTORY_MISSING")
    for item in (marker, db):
        require(stat.S_ISREG(item.st_mode) and item.st_uid == 0
                and stat.S_IMODE(item.st_mode) == 0o600
                and item.st_nlink == 1, "REPLAY_ARTIFACT_PERMISSIONS")
    require(pairing._replay_artifacts_valid(), "REPLAY_VALIDATION_FAILED")
    return "READY"


def admission(pairing, gate):
    require(gate.admit_kh() == EXPECTED_ADMISSION, "KH_ADMISSION_DRIFT")
    state = pairing.state_values()
    require(state.get("SMITE_ROLE") == "foreign"
            and state.get("SMITE_NODE_NAME") == "node-kh"
            and state.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.1"
            and state.get("SMITE_PANEL_DOMAIN") == "ir.kolbe1.ir",
            "KH_IDENTITY_SCOPE_DRIFT")


def fingerprint(pairing):
    """Retain only process-local evidence; never print signed values."""
    node_id, secret = pairing._identity_record()
    return hashlib.sha256((node_id + "\0" + secret).encode("ascii")).digest()


def runtime_snapshot(pairing):
    """Read-only evidence that running Node and exposed ports do not change."""
    image = pairing._run(
        ["docker", "inspect", "-f", "{{.Config.Image}}", "smite-node"],
        timeout=10, capture=True,
    )
    require(image == pairing._FOREIGN_NODE_IMAGE_RC2, "KH_IMAGE_PIN_DRIFT")
    image_id = pairing._run(
        ["docker", "inspect", "-f", "{{.Image}}", "smite-node"],
        timeout=10, capture=True,
    )
    available_id = pairing._run(
        ["docker", "image", "inspect", "-f", "{{.Id}}", image],
        timeout=10, capture=True,
    )
    require(image_id == available_id, "PINNED_IMAGE_NOT_LOCAL")
    started = pairing._run(
        ["docker", "inspect", "-f", "{{.State.StartedAt}}", "smite-node"],
        timeout=10, capture=True,
    )
    listeners = pairing._run(["ss", "-H", "-lnt"], timeout=10, capture=True)
    # Ignore changing kernel socket queue counters; compare exposed endpoints.
    endpoints = tuple(sorted(fields[3] for line in listeners.splitlines()
                             if len(fields := line.split()) >= 5
                             and fields[0] == "LISTEN"))
    return (image_id, started, endpoints)


def enrollment_command(pairing):
    """Ephemeral offline container only: explicitly forbid image pulling."""
    image = pairing._FOREIGN_NODE_IMAGE_RC2
    return [
        "docker", "run", "--rm", "--pull", "never", "--network", "none",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "128",
        "--user", "0:0",
        "--mount", "type=bind,source=" + str(pairing.IDENTITY_DIR)
                   + ",target=/run/smite-node-identity",
        "--mount", "type=bind,source=" + str(pairing.REPLAY_DIR)
                   + ",target=/var/lib/smite-node/auth",
        "--entrypoint", "python3", image, "-B",
        "-m", "app.replay_enrollment",
        "--identity", pairing.CONTAINER_IDENTITY,
        "--replay-db", pairing.CONTAINER_REPLAY,
        "--confirm-first-provision",
    ]


def lock_identity(pairing):
    """Serialize Replay-only attempts without creating a lock file."""
    path = pairing.IDENTITY_FILE
    prior = entry(path)
    require(prior is not None and stat.S_ISREG(prior.st_mode)
            and prior.st_uid == 0 and stat.S_IMODE(prior.st_mode) == 0o600
            and prior.st_nlink == 1, "LOCK_IDENTITY_UNSAFE")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        require((info.st_dev, info.st_ino) == (prior.st_dev, prior.st_ino),
                "IDENTITY_LOCK_RACE")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError as exc:
        if "fd" in locals():
            os.close(fd)
        raise Hold("REPLAY_LOCK_UNAVAILABLE") from exc
    except BaseException:
        if "fd" in locals():
            os.close(fd)
        raise


def apply_once(pairing, gate):
    """Exactly one approved offline enrollment; never perform Node activation."""
    require(os.environ.get("UOPTI_SMITE_PAIRING_FIELD_TRIAL") == "YES"
            and os.environ.get("UOPTI_SMITE_RC2_REPLAY_ONLY") == "YES",
            "REPLAY_DUAL_CONSENT_REQUIRED")
    require(sys.stdin.isatty(), "OPERATOR_TTY_REQUIRED")
    try:
        confirmation = input("Type ENROLL-REPLAY-ONCE to authorize: ").strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise Hold("OPERATOR_CANCELLED") from exc
    require(confirmation == "ENROLL-REPLAY-ONCE", "OPERATOR_CANCELLED")
    fd = lock_identity(pairing)
    try:
        admission(pairing, gate)
        status = replay_state(pairing)
        if status == "READY":
            print("KH_REPLAY_ALREADY_VALID=YES")
            print("LIVE_CHANGES=NONE")
            return
        require(status == "ABSENT", "REPLAY_NOT_FRESH")
        before_identity = fingerprint(pairing)
        before_runtime = runtime_snapshot(pairing)
        private_tree(pairing.REPLAY_DIR, create=True)
        # Recheck under the exclusive identity lock before the single write.
        require(replay_state(pairing) == "ABSENT", "REPLAY_CHANGED_BEFORE_WRITE")
        result = pairing._run(enrollment_command(pairing), timeout=90, capture=True)
        require(result.splitlines() == [
            "REPLAY_DB_FIRST_ENROLLMENT=PROVISIONED",
            "ENROLLMENT_MARKER=PERSISTENT_IN_IDENTITY_DIRECTORY",
            "SIGNED_TRAFFIC_ACTIVATION=NOT_AUTHORIZED",
        ], "REPLAY_ENROLLMENT_RESULT_UNEXPECTED")
        require(replay_state(pairing) == "READY", "REPLAY_POST_VERIFY_FAILED")
        require(fingerprint(pairing) == before_identity,
                "IDENTITY_CONTINUITY_FAILED")
        require(runtime_snapshot(pairing) == before_runtime,
                "KH_RUNTIME_OR_PORTS_CHANGED")
        admission(pairing, gate)
        print("KH_REPLAY_FIRST_ENROLLMENT=PASS")
        print("KH_SIGNED_RUNTIME=PAUSED")
        print("NODE_RESTARTS=NONE")
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    print("===== KH RC2 REPLAY ONLY =====")
    try:
        require(os.geteuid() == 0
                and socket.gethostname().split(".")[0].lower() == "kh",
                "KH_ROOT_REQUIRED")
        pairing = load_checked(PAIRING, PAIRING_BLOB, "rc2_replay_pairing")
        gate = load_checked(ADMISSION, ADMISSION_BLOB, "rc2_replay_admission")
        admission(pairing, gate)
        status = replay_state(pairing)
        if args.verify:
            require(status == "READY", "REPLAY_NOT_PROVISIONED")
            print("KH_REPLAY_INDEPENDENT_VERIFY=PASS_READ_ONLY")
        elif args.plan:
            print("KH_REPLAY_STATUS=" + status)
            print("KH_REPLAY_PLAN=PASS_READ_ONLY")
        else:
            apply_once(pairing, gate)
        print("SIGNED_ACTIVATION=NOT_PERFORMED")
        if not args.apply:
            print("LIVE_CHANGES=NONE")
        return 0
    except Hold as exc:
        print("KH_REPLAY=HOLD")
        print("REASON=" + str(exc))
    except Exception:
        # Neither raw traceback nor secret-bearing subprocess output is safe.
        print("KH_REPLAY=HOLD")
        print("REASON=UNEXPECTED_PRECONDITION_OR_RUNTIME_FAILURE")
    print("NODE_ACTIVATION=NOT_ATTEMPTED")
    print("DO_NOT_CLEAR_OR_RETRY_REPLAY_STATE=YES")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
