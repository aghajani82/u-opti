#!/usr/bin/env python3
"""U-OPTI Stage 9: prepare an INERT Smite Node signed-auth Compose candidate.

NEVER invokes Docker, changes the base Compose/.env, reboots/reloads, or
activates authentication. Candidate carries STRICT future settings and MUST
NOT be passed to 'docker compose up' before the full coordinated rollout.
Only Standard mode; Private Network is not changed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

STATE = Path("/etc/u-opti/smite/state.env")
IDENTITY = Path("/etc/u-opti/smite/identities/node-identity.json")
NODE_COMPOSE = Path("/opt/smite-node/docker-compose.yml")
CANDIDATE = Path("/opt/smite-node/docker-compose.security-candidate.yml")
REPLAY_DIR = Path("/var/lib/u-opti/smite-node-security/replay")
TAG = "# U-OPTI SMITE NODE SECURITY STAGE9 CANDIDATE - INERT\n"
NODE_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
NODE_SECRET = re.compile(r"^[0-9a-f]{64}$")


class StageHold(ValueError):
    pass


def _checked_file(path: Path, *, mode: int | None = None, max_bytes: int = 100_000) -> bytes:
    try:
        record = path.lstat()
        if (
            not stat.S_ISREG(record.st_mode)
            or record.st_size > max_bytes
            or (mode is not None and stat.S_IMODE(record.st_mode) != mode)
            or (mode is not None and record.st_uid != os.geteuid())
        ):
            raise StageHold("Required regular file is unsafe or unexpectedly large")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode) or opened.st_size > max_bytes
                or (mode is not None and (
                    stat.S_IMODE(opened.st_mode) != mode
                    or opened.st_uid != os.geteuid()
                ))
            ):
                raise StageHold("Required file changed during inspection")
            return stream.read(max_bytes + 1)
    except OSError as exc:
        raise StageHold("Required file not present or unreadable") from exc


def _private_directory(path: Path) -> None:
    try:
        record = path.lstat()
        if (
            not stat.S_ISDIR(record.st_mode)
            or record.st_uid != os.geteuid()
            or stat.S_IMODE(record.st_mode) != 0o700
        ):
            raise StageHold("Private directory must be owned and mode 0700")
    except OSError as exc:
        raise StageHold("Private directory does not exist") from exc


def _create_private_directory(path: Path) -> None:
    """Only create missing directories beneath an already-known host path."""
    if path.is_symlink():
        raise StageHold("Refusing symlinked private directory")
    if not path.exists():
        if not path.parent.is_dir() or path.parent.is_symlink():
            raise StageHold("Private storage parent is missing or unsafe")
        path.mkdir(mode=0o700)
    _private_directory(path)


def state(path: Path = STATE) -> dict[str, str]:
    raw = _checked_file(path, max_bytes=16384).decode("utf-8")
    result = {}
    for line in raw.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in ("SMITE_ROLE", "SMITE_CONNECTION_MODE"):
            result[key] = value.strip()
    if result.get("SMITE_CONNECTION_MODE") != "standard":
        raise StageHold("Private/unknown mode is HOLD; Standard only")
    if result.get("SMITE_ROLE") not in ("panel-iran", "iran", "foreign"):
        raise StageHold("Unknown Smite Node role")
    return result


def paired_identity(path: Path = IDENTITY) -> str:
    _private_directory(path.parent)
    try:
        blob = json.loads(_checked_file(path, mode=0o600, max_bytes=4096))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise StageHold("Paired identity is invalid") from exc
    if not isinstance(blob, dict):
        raise StageHold("Paired identity is invalid")
    node_id, secret = blob.get("node_id"), blob.get("node_secret")
    if (
        not isinstance(node_id, str) or not NODE_ID.fullmatch(node_id)
        or not isinstance(secret, str) or not NODE_SECRET.fullmatch(secret)
    ):
        raise StageHold("Paired identity invalid or missing")
    # The key MUST NEVER be echoed or included in generated Compose.
    return node_id


def base_compose_ok(path: Path = NODE_COMPOSE) -> None:
    contents = _checked_file(path).decode("utf-8")
    if len(re.findall(r"^  smite-node:\s*$", contents, re.M)) != 1:
        raise StageHold("Unexpected Smite Node Compose service")
    if "    network_mode: host\n" not in contents:
        raise StageHold("Unrecognized Node network mode")
    # Existing U-OPTI Stage 8888 control path must remain localhost-only.
    # This is a static check; active process and image still need live proof.
    pattern = r'^    command: \["uvicorn", "main:app", "--host", "127\.0\.0\.1", "--port", "8888"'
    if not re.search(pattern, contents, re.M):
        raise StageHold("Node Compose lacks U-OPTI's validated localhost:8888 command")
    if "    volumes:\n" not in contents:
        raise StageHold("Node Compose volume layout not verified")


def compose_candidate(*, identity: Path = IDENTITY, replay_dir: Path = REPLAY_DIR) -> str:
    # No secrets are ever interpolated into YAML.
    return (
        TAG
        + "# DO NOT APPLY - requires coordinated Panel/Node image, 443 gateway, HMAC\n"
        + "# mutual registration and both-direction preflight before activation.\n"
        + "services:\n"
        + "  smite-node:\n"
        + "    volumes:\n"
        + f"      - {identity.parent}:/run/smite-node-identity:ro\n"
        + f"      - {replay_dir}:/var/lib/smite-node/auth:rw\n"
        + "    environment:\n"
        + "      SMITE_AGENT_AUTH_MODE: strict\n"
        + "      SMITE_NODE_PANEL_AUTH_MODE: signed\n"
        + "      SMITE_AGENT_IDENTITY_PATH: /run/smite-node-identity/node-identity.json\n"
        + "      SMITE_AGENT_REPLAY_DB: /var/lib/smite-node/auth/agent-replay.sqlite3\n"
        + "    healthcheck:\n"
        + '      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen(\'http://127.0.0.1:8888/\', timeout=5)"]\n'
        + "      interval: 30s\n"
        + "      timeout: 10s\n"
        + "      retries: 3\n"
        + "      start_period: 40s\n"
    )


def prepare(
    *, state_path: Path = STATE, identity: Path = IDENTITY,
    base_compose: Path = NODE_COMPOSE, candidate: Path = CANDIDATE,
    replay_dir: Path = REPLAY_DIR,
) -> str:
    state(state_path)
    paired_identity(identity)
    base_compose_ok(base_compose)
    if candidate.parent != base_compose.parent:
        raise StageHold("Candidate must be beside the existing Node Compose")
    if replay_dir == identity.parent or replay_dir.is_symlink():
        raise StageHold("Replay directory may not alias identity")
    _create_private_directory(replay_dir.parent)
    _create_private_directory(replay_dir)
    yaml = compose_candidate(identity=identity, replay_dir=replay_dir)
    if candidate.exists() or candidate.is_symlink():
        if _checked_file(candidate, mode=0o600).decode("utf-8") == yaml:
            return "UNCHANGED"
        raise StageHold("Different security candidate exists; refusing overwrite")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(yaml)
            out.flush()
            os.fsync(out.fileno())
    except OSError as exc:
        raise StageHold("Cannot stage offline Compose candidate") from exc
    return "PREPARED"


def discard(
    *, candidate: Path = CANDIDATE, identity: Path = IDENTITY,
    replay_dir: Path = REPLAY_DIR,
) -> str:
    if not candidate.exists() and not candidate.is_symlink():
        return "NOT_PRESENT"
    expected = compose_candidate(identity=identity, replay_dir=replay_dir)
    if _checked_file(candidate, mode=0o600).decode("utf-8") != expected:
        raise StageHold("Candidate modified; cannot automatically discard")
    candidate.unlink()
    # Never delete identity, replay data or any running resource.
    return "DISCARDED_CANDIDATE_ONLY"


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__)
    mode = args.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--discard", action="store_true")
    opts = args.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise StageHold("Must run with root privileges")
        if opts.discard:
            print("STAGE9=" + discard())
            return 0
        state()
        paired_identity()
        base_compose_ok()
        if opts.preflight:
            print("STAGE9=LOCAL_PREFLIGHT_PASS")
            print("ACTIVE_DOCKER_IMAGE=UNVERIFIED")
            print("PANEL_HMAC_AND_443_GATEWAY=UNVERIFIED")
            print("AUTH_SWITCH=BLOCKED")
            return 0
        result = prepare()
        print("STAGE9=" + result)
        print("COMPOSE_CANDIDATE=INERT_NOT_APPLIED")
        print("NODE_RUNTIME=UNCHANGED")
        print("AUTH_SWITCH=BLOCKED_UNTIL_DUAL_SIDE_LIVE_ADMISSION")
        return 0
    except (StageHold, UnicodeError, OSError) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
