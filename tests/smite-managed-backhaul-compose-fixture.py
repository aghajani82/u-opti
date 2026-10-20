#!/usr/bin/env python3
"""Create strictly isolated Compose from the *actual* Node Compose config.

PR-only Docker test fixture, NEVER a real host Compose updater. Receives
Docker Compose normalized config through stdin; verifies original managed
service/bind mounts, then emits one service, no host networking/privileges.
No engine install or Docker operation occurs in this module.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import stat
import sys


class Hold(ValueError):
    pass


IMAGE = "ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
ENGINETARGET = "/usr/local/bin/backhaul"
HEALTH_CMD = (
    "import urllib.request; "
    "urllib.request.urlopen('http://127.0.0.1:8888/healthz')"
)
HEALTH_TEST = ["CMD", "python", "-c", HEALTH_CMD]


def checked(root: Path, phase: str, run_id: str, config: dict, smite: Path, engine: str = "backhaul") -> dict:
    if (os.environ.get("GITHUB_ACTIONS") != "true" or
            os.environ.get("GITHUB_EVENT_NAME") != "pull_request" or
            os.environ.get("GITHUB_REPOSITORY") != "aghajani82/u-opti"):
        raise Hold("NOT_GITHUB_PR")
    runner = Path(os.environ.get("RUNNER_TEMP", "/"))
    if (engine not in ("backhaul", "frp")
            or not root.is_absolute() or not runner.is_absolute()
            or root.parent != runner
            or not root.name.startswith(
                "backhaul-txn-" if engine == "backhaul" else "uopti-official-frp-"
            )
            or root.is_symlink() or not root.is_dir()):
        raise Hold("NOT_PRIVATE_RUNNER_LAB")
    if root.stat().st_mode & 0o077:
        raise Hold("UNSAFE_RUNNER_LAB")
    if (root / "EXPERIMENTAL-LAB").read_text() != "U-OPTI-BACKHAUL-ISOLATED-LAB-V1\n":
        raise Hold("LAB_MARKER_MISSING")
    if phase not in ("absent", "ready") or not re.fullmatch(r"[0-9]{1,20}", run_id):
        raise Hold("INVALID_PHASE_OR_RUN_ID")
    source = config.get("services")
    if not isinstance(source, dict) or set(source) != {"smite-node"}:
        raise Hold("UNEXPECTED_COMPOSE_SERVICES")
    node = source["smite-node"]
    if not isinstance(node, dict):
        raise Hold("MALFORMED_NODE_SERVICE")
    if (node.get("network_mode") != "host" or node.get("ports") or
            node.get("privileged") is True):
        raise Hold("UNEXPECTED_PRODUCTION_NETWORK")
    if not isinstance(node.get("healthcheck"), dict) or (
            node["healthcheck"].get("test") != HEALTH_TEST):
        raise Hold("UNREVIEWED_NODE_HEALTHCHECK")
    mounts = node.get("volumes")
    if not isinstance(mounts, list):
        raise Hold("MISSING_SOURCE_MOUNTS")
    mountmap = {}
    for mount in mounts:
        if not isinstance(mount, dict) or "target" not in mount:
            raise Hold("UNKNOWN_MOUNT")
        target = mount["target"]
        if target in mountmap:
            raise Hold("DUPLICATE_MOUNT_TARGET")
        mountmap[target] = mount
    expected_config = root / "node" / "config"
    core_mount = mountmap.get("/etc/smite-node")
    if (not isinstance(core_mount, dict)
            or core_mount.get("type") != "bind"
            or core_mount.get("source") != str(expected_config)):
        raise Hold("WRONG_CORE_CONFIG_SOURCE")
    # A Backhaul trial may preserve already verified FRP on the same Node.
    # This is explicit PR-only opt-in, not permission for arbitrary engines.
    existing_frp = os.environ.get("SMITE_CI_EXISTING_FRP", "0")
    if existing_frp not in ("0", "1") or (existing_frp == "1" and engine != "backhaul"):
        raise Hold("UNREVIEWED_DUAL_ENGINE_MODE")
    dual = existing_frp == "1"
    frp_targets = ("/usr/local/bin/frpc", "/usr/local/bin/frps")
    targets = ((ENGINETARGET,) + frp_targets if dual else
               (ENGINETARGET,) if engine == "backhaul" else frp_targets)
    other = () if dual else (
        frp_targets if engine == "backhaul" else (ENGINETARGET,))
    if any(name in mountmap for name in other):
        raise Hold("UNEXPECTED_OTHER_ENGINE_MOUNT")
    for binary_target in targets:
        mount = mountmap.get(binary_target)
        if phase == "ready" or (dual and binary_target in frp_targets):
            binary_name = ("backhaul" if binary_target == ENGINETARGET
                           else binary_target.rsplit("/", 1)[-1])
            expected_binary = (
                root / "installed" / "backhaul" if binary_target == ENGINETARGET
                else root / "installed" / "frp" / binary_name)
            if (mount is None or mount.get("type") != "bind"
                    or mount.get("source") != str(expected_binary)
                    or mount.get("read_only") is not True):
                raise Hold("UNVERIFIED_ENGINE_BIND")
        elif mount is not None:
            raise Hold("UNEXPECTED_ENGINE_MOUNT_BEFORE_INSTALL")
    if (not smite.is_dir() or not (smite / "node" / "app" / "agent_auth.py").is_file()
            or not (smite / "node" / "main.py").is_file()):
        raise Hold("MISSING_REVIEWED_SMITE_SOURCE")
    if any((root / part).is_symlink() for part in ("node", "node/config", "node-data")):
        raise Hold("UNSAFE_HOST_BIND")
    if not (root / "node-data").is_dir():
        raise Hold("PERSISTENT_DATA_MISSING")
    name = f"uopti-managed-api-{run_id}-{phase}"
    volumes = [
        {"type": "bind", "source": str(expected_config),
         "target": "/etc/smite-node"},
        {"type": "bind", "source": str(root / "node-data"),
         "target": "/var/lib/smite-node"},
        {"type": "bind", "source": str(smite / "node" / "app"),
         "target": "/app/app", "read_only": True},
        {"type": "bind", "source": str(smite / "node" / "main.py"),
         "target": "/app/main.py", "read_only": True},
    ]
    if phase == "ready" and engine == "backhaul":
        volumes.append({"type": "bind", "source": str(root / "installed/backhaul"),
                        "target": ENGINETARGET, "read_only": True})
    if engine == "frp" and phase == "ready" or dual:
        for frp_binary_name in ("frpc", "frps"):
            volumes.append({
                "type": "bind", "source": str(root / "installed" / "frp" / frp_binary_name),
                "target": "/usr/local/bin/" + frp_binary_name, "read_only": True,
            })
    service = {
        "image": IMAGE,
        "container_name": name,
        "network_mode": "none",
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 96,
        "mem_limit": "384m",
        "user": "0:0",
        "tmpfs": ["/tmp:rw,nosuid,nodev,noexec,size=16m"],
        "environment": {
            "PYTHONDONTWRITEBYTECODE": "1",
            "SMITE_AGENT_AUTH_MODE": "strict",
            "SMITE_NODE_PANEL_AUTH_MODE": "paused",
            "SMITE_ENGINE_INVENTORY_MODE": "managed",
            "SMITE_AGENT_IDENTITY_PATH": "/etc/smite-node/identity/node-identity.json",
            "SMITE_AGENT_REPLAY_DB": "/var/lib/smite-node/auth/agent-replay.sqlite3",
            "SMITE_ENGINE_MANIFEST_PATH": "/etc/smite-node/engine-state/engines.json",
            "NODE_API_PORT": "8888",
        },
        "entrypoint": ["python"],
        "command": ["-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                    "--port", "8888", "--no-access-log"],
        "volumes": volumes,
        # Same reviewed localhost-only probe, accelerated for disposable CI.
        "healthcheck": {
            "test": HEALTH_TEST,
            "interval": "2s",
            "timeout": "2s",
            "retries": 8,
            "start_period": "4s",
        },
        "restart": "no",
    }
    return {"services": {"smite-node": service}}


def main() -> int:
    if len(sys.argv) not in (6, 7):
        print("HOLD: EXPECT_ROOT_PHASE_RUNID_SMITE_OUTPUT_ENGINE", file=sys.stderr)
        return 2
    root, phase, run_id, smite, output = (Path(sys.argv[1]), sys.argv[2],
                                          sys.argv[3], Path(sys.argv[4]),
                                          Path(sys.argv[5]))
    engine = sys.argv[6] if len(sys.argv) == 7 else "backhaul"
    try:
        parsed = json.load(sys.stdin)
        document = checked(root, phase, run_id, parsed, smite, engine)
        if output != root / f"smite-node-isolated-{phase}.json" or output.is_symlink():
            raise Hold("UNSAFE_OUTPUT_PATH")
        raw = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        print("PR_ONLY_ISOLATED_COMPOSE_PREPARED=YES")
        return 0
    except Hold as exc:
        # Only static codes; never echo untrusted paths or Docker metadata.
        message = str(exc)
        safe = message if re.fullmatch("[A-Z0-9_]+", message) else "INVALID_INPUT"
        print("HOLD: " + safe, file=sys.stderr)
        return 2
    except FileExistsError:
        print("HOLD: ISOLATED_COMPOSE_OUTPUT_ALREADY_EXISTS", file=sys.stderr)
        return 2
    except PermissionError:
        print("HOLD: PRIVATE_RUNNER_OUTPUT_PERMISSION_DENIED", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError):
        print("HOLD: ISOLATED_COMPOSE_MALFORMED_INPUT_OR_IO", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
