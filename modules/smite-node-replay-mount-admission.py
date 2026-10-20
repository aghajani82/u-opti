#!/usr/bin/env python3
"""Read-only admission for the *inert* Smite KH strict-auth Compose candidate.

Review the existing paired identity, separately stored one-time enrollment
marker, durable SQLite replay DB and exact candidate mount layout. Never
call Docker, create any file, auto-provision a DB or enable strict auth.
Successful inspection is NOT proof of persistence across reboot or safe
same-Node snapshot rollback; deployment is always HOLD.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

SOURCE = Path(__file__).with_name("smite-node-auth-candidate.py")
spec = importlib.util.spec_from_file_location("uopti_smite_inert_compose", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("Signed Node Compose candidate validator unavailable")
candidate_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate_helper)

HOST_IDENTITY = candidate_helper.IDENTITY
HOST_REPLAY_DIR = candidate_helper.REPLAY_DIR
HOST_COMPOSE = candidate_helper.NODE_COMPOSE
HOST_CANDIDATE = candidate_helper.CANDIDATE
STATE = candidate_helper.STATE
CONTAINER_IDENTITY = "/run/smite-node-identity/node-identity.json"
CONTAINER_REPLAY = "/var/lib/smite-node/auth/agent-replay.sqlite3"
MARKER_NAME = "replay-enrollment.json"
DB_NAME = "agent-replay.sqlite3"
MAX_JSON = 4096


class AdmissionHold(ValueError):
    pass


def _private_dir(path: Path) -> None:
    try:
        item = path.lstat()
    except OSError as exc:
        raise AdmissionHold("Required private directory unavailable") from exc
    if (not stat.S_ISDIR(item.st_mode)
            or item.st_uid != os.geteuid()
            or stat.S_IMODE(item.st_mode) != 0o700):
        raise AdmissionHold("Untrusted private directory (must be 0700 and owned)")


def _secure_file(path: Path, *, max_bytes: int = MAX_JSON,
                 metadata_only: bool = False) -> bytes:
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1
                or before.st_size > max_bytes):
            raise AdmissionHold("Untrusted private file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if ((info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
                    or not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_nlink != 1
                    or info.st_size > max_bytes):
                raise AdmissionHold("Private file changed during read")
            if metadata_only:
                # Small fixed header from the already validated nofollow fd.
                return stream.read(100)
            data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise AdmissionHold("Oversized private file")
            return data
    except OSError as exc:
        raise AdmissionHold("Private file missing or unreadable") from exc


def _json(path: Path) -> dict:
    raw = _secure_file(path)
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise AdmissionHold("Private JSON document invalid") from exc
    if not isinstance(record, dict):
        raise AdmissionHold("Private JSON root invalid")
    return record


def _database(db: Path, node_id: str) -> None:
    header = _secure_file(db, max_bytes=256 * 1024 * 1024, metadata_only=True)
    # Exact offline inspection: don't recover a hot journal or read an
    # inconsistent WAL snapshot. In immutable mode SQLite cannot create a
    # -shm sidecar. An active/wal-mode database requires independent shutdown
    # and checkpoint review, not a sneaky read of partial nonce history.
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(db) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise AdmissionHold("Replay DB not offline/quiescent; journal sidecar present")
    if (len(header) < 100 or header[:16] != b"SQLite format 3\x00"
            or header[18:20] != b"\x01\x01"):
        raise AdmissionHold("Replay DB is not checkpointed in rollback-journal mode")
    try:
        with closing(sqlite3.connect(
            db.absolute().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=2
        )) as conn:
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("PRAGMA user_version").fetchone() != (1,):
                raise AdmissionHold("Unsupported replay SQLite schema")
            if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise AdmissionHold("Replay SQLite integrity failed")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_nonces)")}
            if not {"node_id", "nonce", "expires_at"} <= columns:
                raise AdmissionHold("Replay nonce table untrusted")
            nodes = conn.execute("SELECT node_id FROM replay_store_identity").fetchall()
            if nodes != [(node_id,)]:
                raise AdmissionHold("Replay DB paired identity mismatch")
    except sqlite3.Error as exc:
        raise AdmissionHold("Replay SQLite missing, corrupt or unavailable") from exc


def preflight(
    *, state: Path = STATE, identity: Path = HOST_IDENTITY,
    replay_dir: Path = HOST_REPLAY_DIR,
    base_compose: Path = HOST_COMPOSE,
    candidate: Path = HOST_CANDIDATE,
) -> str:
    """Only inspects already prepared files. Does not repair/create anything."""
    details = candidate_helper.state(state)
    if details.get("SMITE_ROLE") != "foreign":
        raise AdmissionHold("Strict replay mount admission is KH (foreign) only")
    candidate_helper.base_compose_ok(base_compose)
    if (not identity.is_absolute() or not replay_dir.is_absolute()
            or not candidate.is_absolute()
            or identity.name != "node-identity.json"):
        raise AdmissionHold("Unrecognized absolute host storage paths")
    if (identity.parent == replay_dir
            or identity.parent == replay_dir.parent
            or replay_dir.is_relative_to(identity.parent)
            or identity.parent.is_relative_to(replay_dir)):
        raise AdmissionHold("Identity and replay storage must be separate")
    if (replay_dir.parent.is_symlink() or identity.parent.is_symlink()
            or replay_dir.is_symlink()):
        raise AdmissionHold("Symlinked private storage is forbidden")
    _private_dir(identity.parent)
    _private_dir(replay_dir.parent)
    _private_dir(replay_dir)
    _secure_file(identity)
    node_id = candidate_helper.paired_identity(identity)
    marker = _json(identity.parent / MARKER_NAME)
    replay = replay_dir / DB_NAME
    if (set(marker) != {"schema", "node_id", "replay_database", "status"}
            or type(marker["schema"]) is not int or marker["schema"] != 1
            or marker["status"] != "ENROLLMENT_STARTED"
            or marker["node_id"] != node_id
            or marker["replay_database"] != str(replay)):
        raise AdmissionHold("Replay enrollment marker and paired identity mismatch")
    _database(replay, node_id)
    # Require exact candidate bytes, including trusted source mount,
    # read-only identity and read/write replay under their known endpoints.
    expected = candidate_helper.compose_candidate(identity=identity, replay_dir=replay_dir)
    try:
        found = candidate_helper._checked_file(candidate, mode=0o600).decode("utf-8")
    except (candidate_helper.StageHold, UnicodeError) as exc:
        raise AdmissionHold("Security Compose candidate unavailable") from exc
    if found != expected:
        raise AdmissionHold("Unreviewed Compose bind-mount/environment drift")
    if (f"{identity.parent}:/run/smite-node-identity:ro" not in found
            or f"{replay_dir}:/var/lib/smite-node/auth:rw" not in found
            or f"SMITE_AGENT_IDENTITY_PATH={CONTAINER_IDENTITY}" not in found
            or f"SMITE_AGENT_REPLAY_DB={CONTAINER_REPLAY}" not in found):
        raise AdmissionHold("Node runtime identity/replay path mismatch")
    return "KH_PRIVATE_BIND_MOUNTS_OFFLINE_PREFLIGHT_PASS"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        # Preview admission must never mutate a running Node or enable auth.
        if os.geteuid() != 0:
            raise AdmissionHold("KH private admission requires local root owner")
        print(preflight())
        print("DOCKER_COMPOSE_APPLY=NO")
        print("REPLAY_DB_BOOTSTRAP=NO")
        print("INSTALL_ALLOWED=NO")
        print("ACTIVATION_GATE=HOLD")
        print("PERSISTENCE_REBOOT_TEST=NOT_DONE")
        print("SAME_IDENTITY_SNAPSHOT_ROLLBACK=NOT_PROVEN_SAFE")
        return 0
    except (AdmissionHold, candidate_helper.StageHold, OSError) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
