#!/usr/bin/env python3
"""Read-only FRP managed engine status / review; no live install path.

A local digest match is not signed Node evidence. "Install" stays HOLD until
the separately reviewed host lifecycle is integrated and accepted on two
disposable machines with snapshots. Does not inspect or alter Backhaul.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

MODULE_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("managed_frp_candidate", MODULE_DIR / "smite-managed-frp.py")
assert _spec and _spec.loader
frp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(frp)


class Hold(ValueError):
    pass


# RC7 can enroll frpc/frps already shipped in the signed smite-node image.
# That lane deliberately has NO host binary mounts. Never treat a missing
# mount as evidence of a broken live FRP tunnel or permission to recreate Node.
RC7_ENROLLMENT_RECORD = Path("/var/lib/u-opti/smite-rc7-frp-enrollment/record.json")


def _rc7_bundled_local_review(node: Path, role: str,
                              record: dict) -> dict[str, str] | None:
    """Read RC7's own root-owned committed journal; never probe live Docker.

    This is strictly LOCAL enrollment evidence. It does not attest image
    bytes, a running FRP owner/child, signed status, pairing, or replay.
    Return None if no RC7 journal exists so legacy mount errors remain clear.
    """
    if not RC7_ENROLLMENT_RECORD.exists() and not RC7_ENROLLMENT_RECORD.is_symlink():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "managed_frp_rc7_local_review",
            MODULE_DIR / "smite-rc7-frp-enrollment.py",
        )
        if spec is None or spec.loader is None:
            raise Hold("RC7_REVIEW_HELPER_MISSING")
        reviewed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reviewed)
        # state() checks the root-owned 0700 enrollment journal directory,
        # private 0600 record, schema, role and both binary digests.
        journal = reviewed.state()
        if journal.get("state") != "COMMITTED":
            return {"state": "UNAVAILABLE", "reason": "RC7_ENROLLMENT_NOT_COMMITTED"}
        if journal.get("role") != ("foreign" if role == "KH" else "ir"):
            return {"state": "UNAVAILABLE", "reason": "RC7_ENROLLMENT_ROLE_MISMATCH"}
        raw = reviewed.read_private(node / "config" / "engine-state" / "engines.json")
        if (reviewed.sha(raw) != journal["new"]
                or journal["binaries"] != {
                    "frpc": record["sha256"], "frps": record["server_sha256"],
                }):
            return {"state": "UNAVAILABLE", "reason": "RC7_ENROLLMENT_MANIFEST_DRIFT"}
        return {
            "state": "ENROLLED_UNVERIFIED",
            "reason": "RC7_BUNDLED_FRP_SIGNED_STATUS_REQUIRED",
        }
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, Hold,
            ImportError, AttributeError):
        # Never echo arbitrary paths, exceptions, identities or secret data.
        return {"state": "UNAVAILABLE", "reason": "RC7_ENROLLMENT_LOCAL_PROOF_INVALID"}


def inspect(node: Path, *, binaries: dict[str, Path] | None = None) -> dict[str, str]:
    if not node.is_absolute() or node.is_symlink() or not node.is_dir():
        raise Hold("UNSAFE_NODE_DIR")
    raw = frp.shared._file(node / ".env", max_size=16384).decode()
    settings = {}
    for line in raw.splitlines():
        if line.lstrip().startswith("#") or not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ("NODE_ROLE", "SMITE_ENGINE_INVENTORY_MODE",
                   "SMITE_AGENT_AUTH_MODE", "SMITE_NODE_PANEL_AUTH_MODE"):
            if key in settings:
                raise Hold("DUPLICATE_CORE_ENV")
            settings[key] = value
    if (settings.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            or settings.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or settings.get("SMITE_NODE_PANEL_AUTH_MODE") not in ("paused", "signed")
            or settings.get("NODE_ROLE") not in ("iran", "panel-iran", "foreign")):
        raise Hold("MANAGED_STRICT_CORE_REQUIRED")
    role = "KH" if settings["NODE_ROLE"] == "foreign" else "IR"
    compose = frp.shared._file(node / "docker-compose.yml", max_size=131072).decode()
    if (len(re.findall(r"(?m)^  smite-node:\s*$", compose)) != 1
            or not re.search(r"(?m)^    network_mode: host\s*$", compose)
            or re.search(r"(?m)^    ports:\s*$", compose)
            or "      - ./config:/etc/smite-node\n" not in compose):
        raise Hold("UNREVIEWED_NODE_COMPOSE")
    declared = frp.shared._existing_manifest(node / "config")
    if "frp" not in declared:
        if any(target in compose for target in frp.BINARY_PATHS.values()):
            return {"role": role, "state": "UNAVAILABLE", "reason": "PARTIAL_FRP_MOUNT"}
        return {"role": role, "state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}
    record = declared["frp"]
    binaries = binaries if binaries is not None else {
        name: frp.INSTALL_ROOT / name for name in frp.BINARY_PATHS
    }
    if set(binaries) != set(frp.BINARY_PATHS) or "server_sha256" not in record:
        return {"role": role, "state": "UNAVAILABLE", "reason": "DUAL_FRP_DIGEST_REQUIRED"}
    # The legacy independent-engine lane MUST keep its exact two external
    # read-only bind requirements. RC7's bundled lane has no such mounts and
    # may be classified only using its own committed, matching enrollment
    # journal. A partial external mount never falls back to RC7.
    if not any(target in compose for target in frp.BINARY_PATHS.values()):
        rc7 = _rc7_bundled_local_review(node, role, record)
        if rc7 is not None:
            return {"role": role, **rc7}
    for name, dest in frp.BINARY_PATHS.items():
        binpath = binaries[name]
        mount = f"      - {binpath}:{dest}:ro"
        if compose.splitlines().count(mount) != 1:
            return {"role": role, "state": "UNAVAILABLE", "reason": "MISSING_READONLY_MOUNT"}
        try:
            st = binpath.lstat()
            if (binpath.is_symlink() or not stat.S_ISREG(st.st_mode)
                    or st.st_uid != 0 or not st.st_mode & 0o111
                    or st.st_mode & 0o022 or st.st_nlink != 1):
                return {"role": role, "state": "UNAVAILABLE", "reason": "UNSAFE_FRP_BINARY"}
            expected = record["sha256"] if name == "frpc" else record["server_sha256"]
            if hashlib.sha256(frp.shared._file(binpath, max_size=frp.BINARY_MAX)).hexdigest() != expected:
                return {"role": role, "state": "UNAVAILABLE", "reason": "FRP_SHA256_MISMATCH"}
        except (OSError, frp.shared.Hold):
            return {"role": role, "state": "UNAVAILABLE", "reason": "FRP_BINARY_MISSING"}
    return {"role": role, "state": "ENROLLED_UNVERIFIED", "reason": "SIGNED_NODE_RECHECK_REQUIRED"}


# The two local Stage15 archives were independently checked for the KH
# signed-pairing field trial. This is a test-image ID, NOT an OCI digest or
# a production provenance attestation. RC.2 lanes keep their original pins.
STAGE15_NODE_ID = (
    "sha256:a417e8c28426da5eaf16d59925d5c89b52dbf7849ca560dfa9a765a1266b3991"
)


# PR39 final source and independently checked build 40830661751.
STAGE15_FRP071_NODE_ID = 'sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265'
STAGE15_NODE_VERSIONS = {STAGE15_NODE_ID: '0.65.0', STAGE15_FRP071_NODE_ID: '0.71.0'}

# Match the two reviewed loopback-only Standard installer argv variants.
# Do NOT admit arbitrary flags, publicly bound hosts, or non-8888 ports.
SAFE_NODE_COMMANDS = (
    ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"],
    ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888",
     "--log-level", "info", "--access-log"],
)

def _read_only(argv: list[str]) -> str:
    """Bounded argv-only reads. No shell, network, Docker recreation or writes."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20,
                           check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("STAGE15_READ_ONLY_COMMAND_FAILED") from exc
    if p.returncode or len(p.stdout) > 262144:
        raise Hold("STAGE15_READ_ONLY_COMMAND_FAILED")
    return p.stdout.strip()


def stage15_readiness(node: Path, *, run=None) -> dict[str, str]:
    """Read-only signed Stage15 Node readiness; never authorizes FRP apply.

    Enforces the specific running and tagged image ID, signed runtime,
    composed security overlay, loopback-only API, and source-declared bundled version.
    An image-ID match alone is NOT signed health, replay or live tunnel proof.
    """
    if run is None:
        run = _read_only
    previous = inspect(node)
    if previous["state"] != "NOT_INSTALLED":
        raise Hold("STAGE15_FRP_ENROLLMENT_REQUIRES_REVIEW")
    signed = node / "docker-compose.security-candidate.yml"
    frp.shared._file(signed, max_size=131072)
    try:
        entries = json.loads(run(["docker", "inspect", "smite-node"]))
        if not isinstance(entries, list) or len(entries) != 1:
            raise Hold("STAGE15_NODE_INSPECT_INVALID")
        runtime = entries[0]
        config = runtime["Config"]
        host = runtime["HostConfig"]
        env_raw = config["Env"]
        if not isinstance(env_raw, list):
            raise Hold("STAGE15_ENV_INVALID")
        values: dict[str, str] = {}
        for line in env_raw:
            if not isinstance(line, str) or "=" not in line:
                raise Hold("STAGE15_ENV_INVALID")
            key, value = line.split("=", 1)
            if key in values:
                raise Hold("STAGE15_DUPLICATE_ENV")
            values[key] = value
        if (config["Image"] != "smite-node:stage15-local"
                or runtime["Image"] not in STAGE15_NODE_VERSIONS
                or run(["docker", "image", "inspect", "-f", "{{.Id}}",
                        "smite-node:stage15-local"]) != runtime["Image"]):
            raise Hold("STAGE15_IMAGE_ID_MISMATCH")
        if (runtime["State"]["Running"] is not True
                or runtime["State"]["Health"]["Status"] != "healthy"):
            raise Hold("STAGE15_NODE_UNHEALTHY")
        if (host["NetworkMode"] != "host" or host.get("PortBindings")
                or host.get("Privileged") is True):
            raise Hold("STAGE15_NODE_NETWORK_DRIFT")
        if config.get("Cmd") not in SAFE_NODE_COMMANDS:
            raise Hold("STAGE15_NODE_LOOPBACK_DRIFT")
        for key, expected in {
            "SMITE_NODE_PANEL_AUTH_MODE": "signed",
            "SMITE_AGENT_AUTH_MODE": "strict",
            "SMITE_ENGINE_INVENTORY_MODE": "managed",
        }.items():
            if values.get(key) != expected:
                raise Hold("STAGE15_SIGNED_POLICY_DRIFT")
        if not re.fullmatch(r"[a-z0-9.-]+:443", values.get("PANEL_ADDRESS", "")):
            raise Hold("STAGE15_PANEL_TRANSPORT_DRIFT")
        if "SMITE_FRP_STANDARD_WSS" in values:
            raise Hold("STAGE15_WSS_FLAG_UNREVIEWED")
        active_files = {
            f.strip() for f in config.get("Labels", {}).get(
                "com.docker.compose.project.config_files", ""
            ).split(",") if f.strip()
        }
        if active_files != {str(node / "docker-compose.yml"), str(signed)}:
            raise Hold("STAGE15_SIGNED_COMPOSE_NOT_ACTIVE")
        mounts = {m["Destination"]: m for m in runtime["Mounts"]}
        for target, writable in {
            "/etc/smite-node": True,
            "/run/smite-node-identity": False,
            "/var/lib/smite-node/auth": True,
        }.items():
            if target not in mounts or mounts[target].get("RW") is not writable:
                raise Hold("STAGE15_SIGNED_MOUNT_DRIFT")
        for name in ("frpc", "frps"):
            version = run(["docker", "exec", "smite-node",
                           "/usr/local/bin/" + name, "--version"])
            if version.strip().lstrip("v") != STAGE15_NODE_VERSIONS[runtime["Image"]]:
                raise Hold("STAGE15_FRP_BINARY_VERSION_DRIFT")
    except (TypeError, KeyError, IndexError, AttributeError, ValueError,
            json.JSONDecodeError) as exc:
        if isinstance(exc, Hold):
            raise
        raise Hold("STAGE15_RUNTIME_EVIDENCE_INVALID") from exc
    return {
        "ROLE": previous["role"],
        "STAGE15_IMAGE": "PINNED_TEST_ID_MATCH",
        "SIGNED_NODE": "HEALTHY_LOCAL_RUNTIME_ONLY",
        "FRP_BINARIES": "STAGE15_BUNDLED_" + STAGE15_NODE_VERSIONS[runtime["Image"]].replace(".", "_"),
        "FRP_0_71_MANAGED_MATCH": "NO",
        "BUNDLED_FRP_PROVENANCE": "NOT_ATTESTED",
        "FRP_ENGINE_ENROLLED": "NO",
        "WSS_ACTIVATION": "NOT_ENABLED",
        "SIGNED_HMAC_REPLAY_PROOF": "NOT_QUERIED",
        "HOST_FRP_INSTALL": "HOLD_VERSION_AND_SIGNED_WSS_ADMISSION",
        "PUBLIC_PORTS_CHANGED": "NO",
        "LIVE_CHANGES": "NONE",
    }


# Exact RC9 trial baseline for the EXISTING FRP engine review. It is a
# local, non-mutating image/Compose/role/FRP-version witness, NOT signature
# admission, WSS enrollment, FRPS activation, or an install authorisation.
# RC7 and Stage15 paths deliberately keep their original independent pins.
RC9_UPSTREAM = "e7f76185e9a7da51d7069d5d0a829dc192cc1e06"
RC9_NODE_IMAGE = (
    "ghcr.io/aghajani82/smite-node@sha256:"
    "3df3c9d40c338ab87205bbe93e9ab9bd94eb4051558c4429fdd09f876b76b2c2"
)
RC9_STATE = Path("/etc/u-opti/smite/state.env")


def _unique_env(raw: str, *, invalid: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Hold(invalid)
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z0-9_]+", key) or key in values:
            raise Hold(invalid)
        values[key] = value
    return values


def rc9_readiness(node: Path, *, state_path: Path = RC9_STATE,
                  run=None) -> dict[str, str]:
    """Review only; never switch a running RC9 Node into an RC7/Stage15 path."""
    if run is None:
        run = _read_only
    previous = inspect(node)
    if previous["state"] != "NOT_INSTALLED":
        raise Hold("RC9_FRP_EXISTING_OR_PARTIAL_ENROLLMENT")
    state = _unique_env(
        frp.shared._file(state_path, max_size=16384).decode(),
        invalid="RC9_STATE_INVALID")
    role = "IR" if state.get("SMITE_ROLE") == "panel-iran" else "KH"
    if (state.get("SMITE_ROLE") not in ("panel-iran", "foreign")
            or state.get("SMITE_MANAGED_VERSION") != "2.0.0-rc.9"
            or state.get("SMITE_UPSTREAM_REF") != RC9_UPSTREAM
            or state.get("SMITE_CONNECTION_MODE") != "standard"
            or previous["role"] != role):
        raise Hold("RC9_SIGNED_SOURCE_OR_ROLE_MISMATCH")

    node_env = _unique_env(
        frp.shared._file(node / ".env", max_size=16384).decode(),
        invalid="RC9_NODE_ENV_INVALID")
    if (node_env.get("SMITE_NODE_PANEL_AUTH_MODE") != "signed"
            or node_env.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or node_env.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            or (role == "KH" and node_env.get("NODE_ROLE") != "foreign")
            or (role == "IR" and node_env.get("NODE_ROLE") not in ("iran", "panel-iran"))
            or not re.fullmatch(r"[a-z0-9.-]+:443",
                                node_env.get("PANEL_ADDRESS", ""))):
        raise Hold("RC9_NODE_SIGNED_POLICY_MISMATCH")

    base = node / "docker-compose.yml"
    signed = node / "docker-compose.security-candidate.yml"
    frp.shared._file(signed, max_size=131072)
    try:
        entries = json.loads(run(["docker", "inspect", "smite-node"]))
        if not isinstance(entries, list) or len(entries) != 1:
            raise Hold("RC9_NODE_INSPECT_INVALID")
        runtime = entries[0]
        config, host, active = (runtime["Config"], runtime["HostConfig"],
                                runtime["State"])
        if (config.get("Image") != RC9_NODE_IMAGE
                or not re.fullmatch(r"sha256:[a-f0-9]{64}",
                                    runtime.get("Image", ""))
                or run(["docker", "image", "inspect", "-f", "{{.Id}}",
                        RC9_NODE_IMAGE]) != runtime["Image"]):
            raise Hold("RC9_NODE_IMAGE_ID_MISMATCH")
        if (active.get("Running") is not True
                or active.get("Health", {}).get("Status") != "healthy"):
            raise Hold("RC9_NODE_NOT_HEALTHY")
        if (host.get("NetworkMode") != "host"
                or host.get("PortBindings")
                or host.get("Privileged") is True
                or config.get("Cmd") not in SAFE_NODE_COMMANDS):
            raise Hold("RC9_NODE_NETWORK_OR_LOOPBACK_DRIFT")
        env_raw = config["Env"]
        if not isinstance(env_raw, list):
            raise Hold("RC9_EFFECTIVE_ENV_INVALID")
        effective = _unique_env("\n".join(env_raw),
                                invalid="RC9_EFFECTIVE_ENV_INVALID")
        for key in ("SMITE_NODE_PANEL_AUTH_MODE", "SMITE_AGENT_AUTH_MODE",
                    "SMITE_ENGINE_INVENTORY_MODE", "NODE_ROLE",
                    "PANEL_ADDRESS"):
            if effective.get(key) != node_env.get(key):
                raise Hold("RC9_EFFECTIVE_SIGNED_POLICY_DRIFT")
        if "SMITE_FRP_STANDARD_WSS" in effective:
            raise Hold("RC9_WSS_ALREADY_CONFIGURED")
        labels = config.get("Labels") or {}
        project = labels.get("com.docker.compose.project", "")
        files = labels.get("com.docker.compose.project.config_files", "").split(",")
        if (not re.fullmatch(r"uopti_rc6_[a-f0-9]{32}", project)
                or labels.get("com.docker.compose.service") != "smite-node"
                or files != [str(base), str(signed)]):
            raise Hold("RC9_NODE_COMPOSE_OWNER_DRIFT")
        mounts = runtime["Mounts"]
        if not isinstance(mounts, list) or any(
                m.get("Destination") in (
                    "/usr/local/bin", "/usr/local/bin/frpc",
                    "/usr/local/bin/frps") or
                str(m.get("Destination", "")).startswith("/usr/local/bin/frp/")
                for m in mounts):
            raise Hold("RC9_FRP_BINARY_EXTERNAL_MOUNT")
        by_target = {}
        for mount in mounts:
            if mount.get("Destination") in by_target:
                raise Hold("RC9_DUPLICATE_NODE_MOUNTS")
            by_target[mount.get("Destination")] = mount
        for target, writable in (
                ("/etc/smite-node", True),
                ("/run/smite-node-identity", False),
                ("/var/lib/smite-node/auth", True)):
            if (target not in by_target
                    or by_target[target].get("Type") != "bind"
                    or by_target[target].get("RW") is not writable):
                raise Hold("RC9_SIGNED_IDENTITY_MOUNT_DRIFT")
        if by_target["/etc/smite-node"].get("Source") != str(node / "config"):
            raise Hold("RC9_NODE_CONFIG_MOUNT_DRIFT")
        if role == "KH":
            sanaei = by_target.get("/run/smite-sanaei-ro")
            if (not isinstance(sanaei, dict)
                    or sanaei.get("Type") != "bind"
                    or sanaei.get("Source") != "/opt/3x-ui/instances/01/db"
                    or sanaei.get("RW") is not False):
                raise Hold("RC9_SANAEI_READONLY_MOUNT_DRIFT")
        for binary in ("frpc", "frps"):
            version = run(["docker", "exec", "smite-node",
                           "/usr/local/bin/" + binary, "-v"])
            if version.strip().lstrip("v") != "0.71.0":
                raise Hold("RC9_BUNDLED_FRP_VERSION_DRIFT")
    except (OSError, TypeError, ValueError, KeyError, IndexError,
            AttributeError) as exc:
        if isinstance(exc, Hold):
            raise
        raise Hold("RC9_RUNTIME_EVIDENCE_INVALID") from exc
    return {
        "ROLE": role,
        "RC9_SIGNED_SOURCE": "EXACT_LOCAL_STATE",
        "RC9_IMAGE": "PINNED_REFERENCE_AND_LOCAL_IMAGE_ID",
        "RC9_NODE_RUNTIME": "HEALTHY_SIGNED_POLICY_LOCAL_ONLY",
        "FRP_BINARIES": "BUNDLED_0_71_0",
        "FRP_ENGINE_ENROLLED": "NO",
        "FRPS_OWNER": "NOT_VERIFIED",
        "WSS_ACTIVATION": "NOT_ENABLED",
        "SIGNED_HMAC_REPLAY": "NOT_QUERIED",
        "HOST_FRP_INSTALL": "HOLD_PENDING_RC9_SIGNED_WSS_AND_ROLLBACK_REVIEW",
        "PUBLIC_PORTS_CHANGED": "NO",
        "LIVE_CHANGES": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="FRP independent managed-engine read-only operator review")
    parser.add_argument("action", choices=("status", "review", "stage15", "verify-stage", "install", "rollback"))
    parser.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--rc9-baseline", action="store_true",
                        help="Existing RC9 pinned Node/FRP local review; never install")
    parser.add_argument("--state-path", type=Path, default=RC9_STATE)
    args = parser.parse_args()
    if args.action in ("install", "rollback"):
        print("HOLD: Real-host FRP engine activation is NOT enabled; no server changed", file=sys.stderr)
        return 2
    try:
        if args.rc9_baseline and args.action != "review":
            raise Hold("RC9_BASELINE_REVIEW_ONLY")
        if args.rc9_baseline:
            for key, val in rc9_readiness(
                    args.node_dir, state_path=args.state_path).items():
                print(f"{key}={val}")
            print("INSTALL_ALLOWED=NO")
            print("BACKHAUL_DEPENDENCY=NONE")
        elif args.action == "stage15":
            for key, value in stage15_readiness(args.node_dir).items():
                print(f"{key}={value}")
        elif args.action == "verify-stage":
            if args.stage is None or not frp.verify(args.stage):
                raise Hold("ONLY_OFFICIAL_FRP_CANDIDATE_ALLOWED")
            print("FRP_STAGE_VERIFIED=YES")
        else:
            for key, val in inspect(args.node_dir).items():
                print(f"{key.upper()}={val}")
            print("SIGNED_NODE_STATUS=NOT_QUERIED")
            if args.action == "review":
                print("INSTALL_ALLOWED=NO")
                print("BACKHAUL_DEPENDENCY=NONE")
                print("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED")
                print("HOST_DOCKER_ACTIONS=NONE")
        return 0
    except (Hold, frp.shared.Hold, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        value = str(exc)
        print("HOLD: " + (value if re.fullmatch(r"[A-Z0-9_]+", value) else "UNTRUSTED_LOCAL_STATE"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
