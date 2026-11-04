#!/usr/bin/env python3
"""Read-only gate before ANY future real-host Backhaul-only installation.

No installation authority can be produced by this tool. It never updates
Smite, Docker, Nginx, firewall, engine state, tunnels or credentials, and it
does NOT query the cloud snapshot provider or signed Panel API. Even a fully
passing local inventory returns HOLD with explicit unresolved prerequisites.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

MAX_INSPECT_BYTES = 1024 * 1024
MAX_TUNNELS_BYTES = 256 * 1024
MIN_FREE_BYTES = 256 * 1024 * 1024
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
LOCAL_TEST_IMAGE = "smite-node:stage15-local"
REVIEWED_NODE_DIGEST = re.compile(
    r"^ghcr\.io/aghajani82/smite-node@sha256:[a-f0-9]{64}$"
)
PRIVATE_PROFILES = {"managed", "strict"}
NO_PROOF = "UNVERIFIED_MANUAL_OR_SEPARATE_SIGNED_TEST"
# An RC6/RC7 fresh install may retain its transaction-owned named volume.
# It is admitted for read-only inventory only with the exact COMMITTED journal.
# Fixed, reviewed local evidence locations; never taken from untrusted env.
# None of these observations is a live FRP owner/child or signed WSS proof.
FRP_PROC_ROOT = Path("/proc")
BROKER_SOCKET = Path("/run/u-opti/smite/xhttp-broker.sock")
WSS_EDGE_JOURNAL = Path("/var/lib/u-opti/smite-rc7-wss-edge/record.json")
RC6_JOURNAL = Path("/var/lib/u-opti/rc6-install-journal/current.json")
RC6_ID = re.compile(r"^uopti_rc6_[0-9a-f]{32}$")
RC6_SOURCES = frozenset({
    "9a1270b31e8d44f13d09b71ab6b9798410b09c12",
    "25ff25585be3f7ff1c8b73b39a23d0509f9a2312",
})


class GateHold(ValueError):
    pass


def _local_file(path: Path, *, max_bytes: int, require_root: bool = False) -> bytes:
    if path.is_symlink():
        raise GateHold("LOCAL_SYMLINK")
    try:
        st = path.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_size > max_bytes or st.st_size < 0):
            raise GateHold("UNTRUSTED_LOCAL_FILE")
        if require_root and st.st_uid != 0:
            raise GateHold("UNTRUSTED_OWNERSHIP")
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise GateHold("MISSING_LOCAL_FILE") from exc
    except OSError as exc:
        raise GateHold("LOCAL_IO_FAILURE") from exc


def _node_profile(env_data: bytes) -> str:
    try:
        lines = env_data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise GateHold("INVALID_CORE_ENV") from exc
    protected = {"NODE_ROLE", "SMITE_ENGINE_INVENTORY_MODE",
                 "SMITE_AGENT_AUTH_MODE", "SMITE_NODE_PANEL_AUTH_MODE"}
    found = {}
    for line in lines:
        if not line or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if key in protected and sep:
            if key in found:
                raise GateHold("DUPLICATE_CORE_ENV")
            found[key] = value
    if (found.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            or found.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or found.get("SMITE_NODE_PANEL_AUTH_MODE") not in ("paused", "signed")):
        raise GateHold("NOT_MANAGED_STRICT_CORE")
    if found.get("NODE_ROLE") in ("iran", "panel-iran"):
        return "IR"
    if found.get("NODE_ROLE") == "foreign":
        return "KH"
    raise GateHold("UNRECOGNIZED_CORE_ROLE")


def _declared_node_volume_name(compose: str) -> str:
    """Extract exactly one top-level node-data volume name (not any nested name)."""
    in_volumes = in_node_data = False
    sections = definitions = 0
    names: list[str] = []
    for line in compose.splitlines():
        if line == "volumes:":
            sections += 1
            in_volumes, in_node_data = True, False
            continue
        if in_volumes and line and not line[0].isspace() and not line.startswith("#"):
            in_volumes = in_node_data = False
        if not in_volumes:
            continue
        if line == "  node-data:":
            definitions += 1
            in_node_data = True
            continue
        if (line.startswith("  ") and not line.startswith("    ")
                and not line.lstrip().startswith("#")):
            in_node_data = False
        if in_node_data:
            m = re.fullmatch(r"    name:\s*([a-zA-Z0-9_-]+)\s*", line)
            if m:
                names.append(m.group(1))
            elif re.match(r"    name\s*:", line):
                raise GateHold("UNTRUSTED_NODE_COMPOSE")
    if sections != 1 or definitions != 1 or len(names) != 1:
        raise GateHold("UNTRUSTED_NODE_COMPOSE")
    return names[0]


def _read_rc6_journal_bytes(path: Path = RC6_JOURNAL) -> bytes:
    """Read only a root-owned, non-symlink, private transaction journal."""
    try:
        for parent in (path.parent.parent.parent, path.parent.parent, path.parent):
            st = parent.lstat()
            if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0
                    or st.st_mode & 0o022):
                raise GateHold("UNTRUSTED_RC6_JOURNAL")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0
                    or st.st_gid != 0 or stat.S_IMODE(st.st_mode) != 0o600
                    or st.st_nlink != 1 or not 0 < st.st_size <= 16384):
                raise GateHold("UNTRUSTED_RC6_JOURNAL")
            with os.fdopen(fd, "rb", closefd=False) as file:
                raw = file.read(16385)
            if len(raw) > 16384:
                raise GateHold("UNTRUSTED_RC6_JOURNAL")
            return raw
        finally:
            os.close(fd)
    except OSError as exc:
        raise GateHold("UNTRUSTED_RC6_JOURNAL") from exc


def _committed_rc6_volume(raw: bytes, role: str) -> str:
    """Bind a volume to the exact trusted install journal, never by name alone."""
    def unique_pairs(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise GateHold("UNTRUSTED_RC6_JOURNAL")
            out[key] = value
        return out
    try:
        journal = json.loads(raw, object_pairs_hook=unique_pairs)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise GateHold("UNTRUSTED_RC6_JOURNAL") from exc
    if (not isinstance(journal, dict)
            or type(journal.get("schema")) is not int
            or journal.get("schema") != 1
            or journal.get("state") != "COMMITTED"
            or journal.get("source") not in RC6_SOURCES
            or journal.get("role") != {"IR": "panel-iran", "KH": "foreign"}.get(role)
            or not isinstance(journal.get("id"), str)
            or RC6_ID.fullmatch(journal["id"]) is None):
        raise GateHold("UNTRUSTED_RC6_JOURNAL")
    return journal["id"] + "_node-data"


def _approved_data_volume_name(compose: str, role: str) -> str:
    name = _declared_node_volume_name(compose)
    if name == "smite-node-data":
        return name  # Existing reviewed static-volume installations.
    if not re.fullmatch(r"uopti_rc6_[0-9a-f]{32}_node-data", name):
        raise GateHold("UNTRUSTED_NODE_COMPOSE")
    # An apparently valid RC6 prefix alone never grants admission.
    if name != _committed_rc6_volume(_read_rc6_journal_bytes(), role):
        raise GateHold("UNTRUSTED_RC6_JOURNAL")
    return name


def read_only_docker_inspect(*, name: str = "smite-node", runner=subprocess.run) -> dict:
    """The single subprocess permitted in this module: 'docker inspect'."""
    if not NAME.fullmatch(name):
        raise GateHold("UNSAFE_CONTAINER_NAME")
    try:
        result = runner(
            ["docker", "inspect", "--type=container", name],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateHold("DOCKER_INSPECT_UNAVAILABLE") from exc
    if result.returncode != 0 or len(result.stdout) > MAX_INSPECT_BYTES:
        raise GateHold("DOCKER_INSPECT_UNAVAILABLE")
    try:
        parsed = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise GateHold("DOCKER_INSPECT_MALFORMED") from exc
    if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
        raise GateHold("DOCKER_INSPECT_MALFORMED")
    return parsed[0]


def check_runtime(report: dict, *, node_dir: Path,
                  expected_node_image: str | None = None,
                  expected_data_volume: str = "smite-node-data") -> tuple[str, Path, str]:
    """Inspect exact container identity and an externally pinned Node digest.

    Production-like registry images are never trusted from Docker metadata
    alone. The caller must supply the exact independently reviewed immutable
    ghcr.io/aghajani82/smite-node@sha256:... reference. This local equality
    check is NOT cryptographic registry verification and never authorizes use.
    """
    if (report.get("Name") != "/smite-node" or
            not isinstance(report.get("State"), dict)
            or report["State"].get("Running") is not True):
        raise GateHold("NODE_NOT_RUNNING")
    config = report.get("Config")
    host = report.get("HostConfig")
    if not isinstance(config, dict) or not isinstance(host, dict):
        raise GateHold("DOCKER_METADATA_INCOMPLETE")
    image = config.get("Image")
    if not isinstance(image, str):
        raise GateHold("UNREVIEWED_NODE_IMAGE")
    if image == LOCAL_TEST_IMAGE:
        if expected_node_image is not None:
            raise GateHold("LOCAL_TEST_IMAGE_CANNOT_SATISFY_PIN")
        image_class = "LOCAL_TAG_UNATTESTED"
    else:
        if REVIEWED_NODE_DIGEST.fullmatch(image) is None:
            raise GateHold("UNREVIEWED_NODE_IMAGE")
        if expected_node_image is None:
            raise GateHold("EXPECTED_NODE_DIGEST_REQUIRED")
        if REVIEWED_NODE_DIGEST.fullmatch(expected_node_image) is None:
            raise GateHold("INVALID_EXPECTED_NODE_DIGEST")
        if image != expected_node_image:
            raise GateHold("NODE_IMAGE_DIGEST_MISMATCH")
        image_class = "OPERATOR_PINNED_DIGEST_UNATTESTED"
    if host.get("NetworkMode") != "host":
        raise GateHold("UNEXPECTED_NODE_NETWORK")
    if host.get("PortBindings"):
        raise GateHold("PUBLISHED_DOCKER_PORTS")
    mounts = report.get("Mounts")
    if not isinstance(mounts, list):
        raise GateHold("DOCKER_MOUNT_INVENTORY_MISSING")
    mapping = {}
    for mount in mounts:
        if not isinstance(mount, dict):
            raise GateHold("UNTRUSTED_NODE_MOUNT")
        dest = mount.get("Destination")
        if dest in ("/etc/smite-node", "/var/lib/smite-node"):
            if dest in mapping:
                raise GateHold("DUPLICATE_PERSISTENT_MOUNT")
            source = mount.get("Source")
            if not isinstance(source, str) or not source.startswith("/"):
                raise GateHold("UNTRUSTED_NODE_MOUNT")
            mapping[dest] = mount

    config_mount = mapping.get("/etc/smite-node")
    data_mount = mapping.get("/var/lib/smite-node")
    if (config_mount is None or config_mount.get("Type") != "bind"
            or config_mount.get("Source") != str(node_dir / "config")):
        raise GateHold("WRONG_NODE_CONFIG_VOLUME")
    # The reviewed original Smite/node/docker-compose.yml uses:
    # node-data:/var/lib/smite-node, name: smite-node-data, driver: local.
    # This is NOT a bind mount. Silently demanding a bind would reject
    # legitimate fresh Smite Core installations.
    if (data_mount is None or data_mount.get("Type") != "volume"
            or data_mount.get("Name") != expected_data_volume
            or data_mount.get("Driver") != "local"):
        raise GateHold("WRONG_NODE_NAMED_VOLUME")
    data_path = Path(data_mount["Source"])
    if (node_dir.joinpath("config").is_symlink() or
            data_path.is_symlink() or
            not node_dir.joinpath("config").is_dir() or
            not data_path.is_dir()):
        raise GateHold("INVALID_PERSISTENT_VOLUMES")
    return image, data_path, image_class


def tunnel_inventory(data_dir: Path) -> tuple[int, str]:
    """Exact persisted registry bytes digest; no raw tunnel specs or tokens.

    ABSENT is intentionally different from SHA256('{}'): missing files must
    not be mistaken for a validated empty registry. This is NOT a signed
    tunnel-health proof or a host installation authorization.
    """
    saved = data_dir / "tunnels.json"
    if not saved.exists() and not saved.is_symlink():
        return 0, "ABSENT"
    blob = _local_file(saved, max_bytes=MAX_TUNNELS_BYTES, require_root=True)
    try:
        tunnels = json.loads(blob)
    except (ValueError, UnicodeError) as exc:
        raise GateHold("TUNNEL_REGISTRY_CORRUPT") from exc
    if not isinstance(tunnels, dict) or len(tunnels) > 5000:
        raise GateHold("UNTRUSTED_TUNNEL_REGISTRY")
    for value in tunnels.values():
        if (not isinstance(value, dict) or
                not isinstance(value.get("core"), str) or
                not isinstance(value.get("spec"), dict)):
            raise GateHold("UNTRUSTED_TUNNEL_REGISTRY")
    return len(tunnels), hashlib.sha256(blob).hexdigest()


def tunnel_count(data_dir: Path) -> int:
    # Preserve the existing count-only caller contract.
    return tunnel_inventory(data_dir)[0]


def _read_proc_file(path: Path, limit: int) -> bytes:
    """Bounded read with O_NOFOLLOW; no argv, environ, fd or secrets."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("OVERSIZED_PROCESS_METADATA")
        return data


def frp_process_footprint(proc_root: Path = FRP_PROC_ROOT) -> dict[str, str]:
    """Best-effort /proc *names and start ticks*, never arguments or secrets.

    A process named frps is NOT proof that it owns the reviewed FRPS service;
    this only offers a local before/after restart-change hint.
    """
    result = {
        "FRPC_PROCESS_LOCAL": "UNVERIFIED",
        "FRPS_PROCESS_LOCAL": "UNVERIFIED",
        "FRPC_INSTANCE_SHA256": "UNVERIFIED",
        "FRPS_INSTANCE_SHA256": "UNVERIFIED",
    }
    observed: dict[str, list[str]] = {"frpc": [], "frps": []}
    try:
        if proc_root.is_symlink() or not proc_root.is_dir():
            return result
        count = 0
        for pid_dir in proc_root.iterdir():
            if not pid_dir.name.isdecimal() or not pid_dir.is_dir():
                continue
            count += 1
            if count > 65536:
                return result
            try:
                comm = _read_proc_file(pid_dir / "comm", 64)
                if comm not in (b"frpc\n", b"frps\n"):
                    continue
                name = comm.strip().decode("ascii")
                # /proc/PID/stat: after the final ') ', field 3 is process state,
                # so field 22 (starttime) is at index 19 in this suffix.
                raw = _read_proc_file(pid_dir / "stat", 4096)
                marker = raw.rfind(b") ")
                if marker < 0:
                    return result
                fields = raw[marker + 2:].split()
                if len(fields) < 20 or not fields[19].isdigit():
                    return result
                observed[name].append(pid_dir.name + ":" + fields[19].decode("ascii"))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                # A process disappeared during inspection: cannot claim a
                # stable snapshot, so fail closed instead of ignoring it.
                return result
        for name, entries in observed.items():
            key = name.upper()
            result[key + "_PROCESS_LOCAL"] = (
                "OBSERVED_UNATTESTED" if entries else "NOT_OBSERVED"
            )
            if entries:
                payload = "\n".join(sorted(entries)).encode("ascii")
                result[key + "_INSTANCE_SHA256"] = hashlib.sha256(payload).hexdigest()
            else:
                result[key + "_INSTANCE_SHA256"] = "ABSENT"
    except (OSError, ValueError, UnicodeError):
        return {
            "FRPC_PROCESS_LOCAL": "UNVERIFIED",
            "FRPS_PROCESS_LOCAL": "UNVERIFIED",
            "FRPC_INSTANCE_SHA256": "UNVERIFIED",
            "FRPS_INSTANCE_SHA256": "UNVERIFIED",
        }
    return result


def broker_socket_footprint(socket_path: Path = BROKER_SOCKET,
                            *, stat_fn=os.lstat) -> dict[str, str]:
    """Check socket type, strict root/GID/mode and inode; do not connect."""
    result = {"BROKER_SOCKET_LOCAL": "UNVERIFIED",
              "BROKER_SOCKET_ID_SHA256": "UNVERIFIED"}
    try:
        parent = stat_fn(socket_path.parent)
        entry = stat_fn(socket_path)
    except FileNotFoundError:
        result["BROKER_SOCKET_LOCAL"] = "ABSENT"
        result["BROKER_SOCKET_ID_SHA256"] = "ABSENT"
        return result
    except OSError:
        return result
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
            or stat.S_IMODE(parent.st_mode) != 0o750
            or not stat.S_ISSOCK(entry.st_mode) or entry.st_uid != 0
            or entry.st_gid <= 0 or entry.st_gid != parent.st_gid
            or entry.st_nlink != 1
            or stat.S_IMODE(entry.st_mode) != 0o660):
        result["BROKER_SOCKET_LOCAL"] = "UNTRUSTED"
        return result
    raw = f"{entry.st_dev}:{entry.st_ino}".encode("ascii")
    return {"BROKER_SOCKET_LOCAL": "PRESENT_UNATTESTED",
            "BROKER_SOCKET_ID_SHA256": hashlib.sha256(raw).hexdigest()}


def wss_edge_footprint(journal: Path = WSS_EDGE_JOURNAL) -> dict[str, str]:
    """Read only the exact root-owned RC7 edge journal; never log peer IP."""
    result = {"WSS_EDGE_JOURNAL_LOCAL": "UNVERIFIED",
              "WSS_EDGE_JOURNAL_SHA256": "UNVERIFIED"}
    if not journal.exists() and not journal.is_symlink():
        result["WSS_EDGE_JOURNAL_LOCAL"] = "ABSENT"
        result["WSS_EDGE_JOURNAL_SHA256"] = "ABSENT"
        return result
    try:
        st = journal.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0
                or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600
                or not 0 < st.st_size <= 16384):
            return result
        blob = _local_file(journal, max_bytes=16384, require_root=True)
        def reject_duplicate(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError("DUPLICATE_EDGE_JOURNAL_FIELD")
                out[key] = value
            return out
        doc = json.loads(blob, object_pairs_hook=reject_duplicate)
        if (not isinstance(doc, dict) or type(doc.get("schema")) is not int
                or doc.get("schema") != 1 or doc.get("state") != "COMMITTED"):
            return result
    except (OSError, ValueError, TypeError, UnicodeError):
        return result
    return {"WSS_EDGE_JOURNAL_LOCAL": "COMMITTED_LOCAL_UNATTESTED",
            "WSS_EDGE_JOURNAL_SHA256": hashlib.sha256(blob).hexdigest()}


def audit(node: Path, *, runtime: dict | None = None, runner=subprocess.run,
          min_bytes: int = MIN_FREE_BYTES,
          expected_node_image: str | None = None) -> dict[str, str]:
    """No mutable actions and no secret-bearing result strings."""
    result = {
        "NODE_ROLE": "HOLD",
        "LOCAL_CORE": "HOLD",
        "DOCKER_NODE": "HOLD",
        "PERSISTENT_DATA": "UNVERIFIED",
        "PERSISTED_TUNNELS": "UNKNOWN",
        "PERSISTED_TUNNEL_REGISTRY_SHA256": "UNVERIFIED",
        "NODE_CONTAINER_ID_SHA256": "UNVERIFIED",
        "FRPC_PROCESS_LOCAL": "UNVERIFIED",
        "FRPS_PROCESS_LOCAL": "UNVERIFIED",
        "FRPC_INSTANCE_SHA256": "UNVERIFIED",
        "FRPS_INSTANCE_SHA256": "UNVERIFIED",
        "BROKER_SOCKET_LOCAL": "UNVERIFIED",
        "BROKER_SOCKET_ID_SHA256": "UNVERIFIED",
        "WSS_EDGE_JOURNAL_LOCAL": "UNVERIFIED",
        "WSS_EDGE_JOURNAL_SHA256": "UNVERIFIED",
        "DISK_SPACE": "HOLD",
        "ENGINE": "BACKHAUL_ONLY",
        "FRP_INSTALL_REQUIRED": "NO",
        "NEW_PUBLIC_PORTS": "NONE_PLANNED",
        "SNAPSHOT_AND_CONSOLE": NO_PROOF,
        "SIGNED_NODE_POST_RESTART": NO_PROOF,
        "PAIRING_AND_REPLAY_PRESERVATION": NO_PROOF,
        "NGINX_443_AND_FIREWALL_EXPOSURE": NO_PROOF,
        "TUNNEL_RECOVERY_AFTER_RESTART": NO_PROOF,
        "HOST_INSTALL_AUTHORIZED": "NO",
    }
    try:
        if not node.is_absolute() or node.is_symlink() or not node.is_dir():
            raise GateHold("UNSAFE_NODE_ROOT")
        role = _node_profile(_local_file(node / ".env", max_bytes=16384, require_root=True))
        result["NODE_ROLE"] = role
        result["LOCAL_CORE"] = "MANAGED_STRICT"
        compose = _local_file(node / "docker-compose.yml", max_bytes=131072,
                              require_root=True).decode("utf-8")
        if (len(re.findall(r"(?m)^  smite-node:\s*$", compose)) != 1
                or not re.search(r"(?m)^\s+network_mode: host\s*$", compose)
                or re.search(r"(?m)^\s+ports:\s*$", compose)
                or not re.search(r"(?m)^\s+- ./config:/etc/smite-node\s*$", compose)
                or not re.search(r"(?m)^\s+- node-data:/var/lib/smite-node\s*$", compose)):
            raise GateHold("UNTRUSTED_NODE_COMPOSE")
        data_volume_name = _approved_data_volume_name(compose, role)
        result["COMPOSE_SHA256"] = hashlib.sha256(compose.encode("utf-8")).hexdigest()
        node_report = runtime if runtime is not None else read_only_docker_inspect(runner=runner)
        _image, data_dir, image_class = check_runtime(
            node_report, node_dir=node, expected_node_image=expected_node_image,
            expected_data_volume=data_volume_name
        )
        result["DOCKER_NODE"] = "RUNNING_REVIEWED_IMAGE"
        result["PERSISTENT_DATA"] = "LOCAL_NAMED_VOLUME_CONFIRMED"
        result["VOLUME_PROOF"] = ("COMMITTED_RC6_JOURNAL" if data_volume_name != "smite-node-data"
                                  else "REVIEWED_STATIC_VOLUME")
        result["IMAGE_REFERENCE_CLASS"] = image_class
        # Docker's raw container ID is not itself a signed runtime proof.
        # Export only its SHA256, and never invent an ID for a missing field.
        container_id = node_report.get("Id")
        if isinstance(container_id, str) and re.fullmatch(r"[a-f0-9]{64}", container_id):
            result["NODE_CONTAINER_ID_SHA256"] = hashlib.sha256(
                container_id.encode("ascii")).hexdigest()
        count, saved_sha256 = tunnel_inventory(data_dir)
        result["PERSISTED_TUNNEL_REGISTRY_SHA256"] = saved_sha256
        result["PERSISTED_TUNNELS"] = "ZERO" if count == 0 else "EXISTING_DO_NOT_RESTART"
        # Local process/socket/journal evidence is independent of saved tunnels.
        # A positive hint cannot override the hard saved-tunnel or snapshot HOLD.
        result.update(frp_process_footprint())
        if role == "IR":
            result.update(broker_socket_footprint())
            result.update(wss_edge_footprint())
        try:
            free = os.statvfs(node).f_bavail * os.statvfs(node).f_frsize
        except OSError as exc:
            raise GateHold("DISK_SPACE_UNREADABLE") from exc
        if free < min_bytes:
            raise GateHold("INSUFFICIENT_FREE_DISK")
        result["DISK_SPACE"] = "MINIMUM_AVAILABLE"
        result["HOST_PREFLIGHT"] = (
            "HOLD_EXISTING_TUNNELS" if count else "PASS_LOCAL_ONLY_INCOMPLETE"
        )
    except (GateHold, UnicodeError, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, GateHold) else "UNTRUSTED_LOCAL_DATA"
        result["HOST_PREFLIGHT"] = "HOLD"
        # Never print exception arguments from external processes or secrets.
        result["HOLD_REASON"] = reason if re.fullmatch(r"[A-Z0-9_]+", reason) else "UNVERIFIED"
    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Backhaul host preflight READ ONLY; never authorizes installation")
    p.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    p.add_argument(
        "--expected-node-image",
        help="Exact independently reviewed ghcr.io/aghajani82/smite-node@sha256:... ref",
    )
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args()
    report = audit(args.node_dir, expected_node_image=args.expected_node_image)
    report["BACKHAUL_ACTIVATION_GATE"] = "HOLD"
    if args.format == "json":
        # Explicit, bounded, secret-free report. No raw Docker inspect,
        # .env, tunnel specifications, credentials or filesystem paths.
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        for key, value in report.items():
            print(f"{key}={value}")
    # Never make this look like an install-capable PASS.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
