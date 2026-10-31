#!/usr/bin/env python3
"""IR-only read-only FRPS owner observer (OFFLINE REVIEW PROTOTYPE).

No signing, no HTTP, no grants, no FRP/Node/Panel mutations. This is not
a production attestation source. Its strict registry schema is hypothetical
until independently verified against the actual IR host. Incompatible state
HOLDs; never attempt repair/reapply or infer a missing owner from sockets.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import time

NODE_IMAGE = "sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265"
OWNER_ID = "FRP-IR-KH-45121"
REGISTRY = Path("/var/lib/docker/volumes/smite-node-data/_data/tunnels.json")
PORTS = (7000, 28897, 38658, 45121)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
OWNER_PATTERN = re.compile(r'"frps",pid=(\d+)\b')


class ObserverHold(RuntimeError):
    pass


def need(ok, reason):
    if not ok:
        raise ObserverHold(reason)


def command(*args):
    """Commands are a fixed inventory with no shell, no user-supplied args."""
    try:
        return subprocess.run(args, check=True, capture_output=True,
                              text=True, timeout=15).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ObserverHold("READ_ONLY_RUNTIME_UNAVAILABLE") from exc


def inspect_node(runner=command):
    try:
        objects = json.loads(runner("docker", "inspect", "smite-node"))
    except (ValueError, TypeError) as exc:
        raise ObserverHold("DOCKER_INSPECT_UNTRUSTED") from exc
    need(type(objects) is list and len(objects) == 1
         and type(objects[0]) is dict, "DOCKER_INSPECT_UNTRUSTED")
    item = objects[0]
    state = item.get("State") or {}
    need(item.get("Image") == NODE_IMAGE and state.get("Running") is True
         and (state.get("Health") or {}).get("Status") == "healthy"
         and item.get("RestartCount") == 0, "IR_NODE_RUNTIME_DRIFT")
    cid = item.get("Id")
    need(type(cid) is str and bool(HEX64.fullmatch(cid)),
         "IR_NODE_CONTAINER_ID_UNTRUSTED")
    mounts = item.get("Mounts") or []
    matching = [m for m in mounts if type(m) is dict
                and m.get("Type") == "volume"
                and m.get("Name") == "smite-node-data"
                and m.get("Source") == str(REGISTRY.parent)]
    need(len(matching) == 1 and matching[0].get("RW") is True,
         "IR_REGISTRY_LIVE_VOLUME_UNVERIFIED")
    return cid


def processes(raw):
    lines = raw.strip().splitlines()
    need(len(lines) >= 2 and lines[0].split()[:2] == ["PID","COMMAND"],
         "NODE_PROCESS_INVENTORY_UNTRUSTED")
    entries = []
    for row in lines[1:]:
        fields = row.split()
        need(len(fields) == 2 and fields[0].isdigit(),
             "NODE_PROCESS_INVENTORY_UNTRUSTED")
        entries.append((int(fields[0]),fields[1].rsplit("/",1)[-1]))
    return entries


def listeners(raw):
    """Exact FRPS 4-socket loopback and singleton-PID ownership."""
    observed = {}
    for line in raw.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 6:
            continue
        pids = {int(m) for m in OWNER_PATTERN.findall(fields[5])}
        if not pids:
            continue
        try:
            port = int(fields[3].rsplit(":", 1)[1])
        except ValueError as exc:
            raise ObserverHold("FRPS_LISTENER_UNPARSEABLE") from exc
        need(port in PORTS and fields[3] == f"127.0.0.1:{port}",
             "UNEXPECTED_OR_PUBLIC_FRPS_LISTENER")
        need(len(pids) == 1 and port not in observed,
             "FRPS_LISTENER_AMBIGUOUS")
        observed[port] = next(iter(pids))
    need(set(observed) == set(PORTS) and len(set(observed.values())) == 1,
         "FRPS_SINGLETON_OR_SOCKET_DRIFT")
    return next(iter(observed.values()))


def start_ticks(pid, proc_root=Path("/proc")):
    need(type(pid) is int and 0 < pid < 2**31, "FRPS_PROCESS_ID_INVALID")
    try:
        raw = (proc_root / str(pid) / "stat").read_text(encoding="ascii")
        ending = raw.rfind(") ")
        need(ending > 0, "FRPS_PROCESS_STAT_INVALID")
        parts = raw[ending+2:].split()
        tick = int(parts[19])
        need(tick > 0, "FRPS_PROCESS_GENERATION_INVALID")
        return tick
    except (OSError, IndexError, ValueError) as exc:
        raise ObserverHold("FRPS_PROCESS_GENERATION_UNAVAILABLE") from exc


def registry_owner(raw, expected_owner=OWNER_ID):
    """Contract for test fixtures only; unknown live schemas HOLD closed.

    Do not support guessy fallbacks or accept a remote assertion as registry.
    Full Panel owner/child lease reconciliation is NOT implemented here.
    """
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise ObserverHold("IR_REGISTRY_MALFORMED") from exc
    need(type(document) is dict and set(document) == {"tunnels"}
         and type(document["tunnels"]) is dict,
         "IR_REGISTRY_SCHEMA_NOT_REVIEWED")
    matches = [value for name,value in document["tunnels"].items()
               if name == expected_owner]
    need(len(matches) == 1 and type(matches[0]) is dict,
         "IR_OWNER_REGISTRY_MISSING")
    owner = matches[0]
    spec = owner.get("spec")
    need(owner.get("core") == "frp" and type(spec) is dict
         and spec.get("mode") == "server"
         and type(spec.get("bind_port")) is int
         and spec["bind_port"] == 7000,
         "IR_OWNER_REGISTRY_DRIFT")
    # Strict schema identifies a candidate only; no owner->child lease proof.
    need(not any(name == expected_owner and value is not owner
                 for name,value in document["tunnels"].items()),
         "IR_OWNER_DUPLICATE")
    return expected_owner


def read_registry(path=REGISTRY):
    need(path == REGISTRY, "IR_UNAPPROVED_REGISTRY_PATH")
    try:
        info = path.lstat()
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
             and info.st_nlink == 1 and not info.st_mode & 0o022
             and 0 < info.st_size < 1024*1024, "IR_REGISTRY_UNTRUSTED")
        with path.open("rb") as f:
            before = os.fstat(f.fileno())
            need((before.st_dev,before.st_ino) == (info.st_dev,info.st_ino),
                 "IR_REGISTRY_REPLACED")
            blob = f.read(1024*1024)
            need(len(blob) == info.st_size, "IR_REGISTRY_CHANGED")
        return blob, info
    except OSError as exc:
        raise ObserverHold("IR_REGISTRY_UNAVAILABLE") from exc


def collect_ir(*, node_id, port, runner=command, proc_root=Path("/proc"),
               registry_path=REGISTRY, require_host=True):
    """Return non-secret unsignable facts after fixed-source observations.

    The caller-provided node_id is NOT independently enrolled or pinned yet.
    Future reviewed implementation must pin the signed live Node identity
    before any privileged signer or grant can consume these observations.
    """
    if require_host:
        need(os.geteuid() == 0 and socket.gethostname().split(".")[0] == "ir",
             "IR_ROOT_ONLY")
    need(type(node_id) is str and bool(IDENT.fullmatch(node_id)),
         "IR_UNPINNED_NODE_ID")
    need(type(port) is int and port in PORTS and port != 7000,
         "IR_UNAPPROVED_PROXY_PORT")
    need(not require_host or registry_path == REGISTRY,
         "IR_REGISTRY_PATH_UNTRUSTED")
    start = time.monotonic()
    node_container = inspect_node(runner)
    proc = processes(runner("docker","top","smite-node","-eo","pid,comm"))
    frps = [p for p,exe in proc if exe == "frps"]
    need(len(frps) == 1, "FRPS_PROCESS_NOT_SINGLETON")
    pid = frps[0]
    tick = start_ticks(pid,proc_root=proc_root)
    need(listeners(runner("ss","-Hlntp")) == pid, "FRPS_PROCESS_NOT_SOCKET_OWNER")
    blob, info = read_registry(registry_path)
    owner = registry_owner(blob)
    current = registry_path.lstat()
    need((current.st_dev,current.st_ino) == (info.st_dev,info.st_ino)
         and start_ticks(pid,proc_root=proc_root) == tick,
         "FRPS_REGISTRY_OR_GENERATION_CHANGED")
    need(inspect_node(runner) == node_container,
         "IR_NODE_CONTAINER_REPLACED")
    need(time.monotonic()-start <= 5, "IR_OBSERVATION_STALE")
    return {"node":node_id, "tunnel_id":owner,
            "control_port":7000, "proxy_port":port,
            "owner_pid":pid, "owner_start_ticks":tick,
            "node_container_id":node_container,
            "registry_sha256":hashlib.sha256(blob).hexdigest(),
            "listener_ports":list(PORTS)}


if __name__ == "__main__":
    raise SystemExit("OFFLINE_LIBRARY_ONLY_NO_IR_HOST_ACTIVATION")
