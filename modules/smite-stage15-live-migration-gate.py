#!/usr/bin/env python3
"""Read-only Stage15 IR/KH live migration boundary audit.

No image load, Docker mutation, signed request, network request, or rollback.
A PASS proves only the observed process/Compose isolation at that instant,
not image eligibility, no-downtime, rollback readiness, or authorization.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys

IR_PANEL = "sha256:4abfd55d5c18d95119f8bae4c790cb2b687c54355836ea5529c8aff8a53dcd09"
NODE = "sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265"
TUNNEL_PORTS = (45121, 38658, 28897)
OWNER_PORTS = (7000,) + TUNNEL_PORTS


class Hold(RuntimeError):
    pass


def need(value: bool, reason: str) -> None:
    if not value:
        raise Hold(reason)


def command(*args: str) -> str:
    # Commands are a fixed read-only inventory, never shell-interpreted.
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=30, check=True)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise Hold("READ_ONLY_COMMAND_UNAVAILABLE") from exc
    return result.stdout


def inspect(name: str) -> dict:
    try:
        result = json.loads(command("docker", "inspect", name))
        need(isinstance(result, list) and len(result) == 1, "DOCKER_INSPECT_UNTRUSTED")
        return result[0]
    except (ValueError, TypeError, KeyError) as exc:
        raise Hold("DOCKER_INSPECT_UNTRUSTED") from exc


def process_ids(name: str, executable: str | None = None) -> set[int]:
    rows = command("docker", "top", name, "-eo", "pid,comm").splitlines()
    need(len(rows) >= 2 and rows[0].split()[:2] == ["PID", "COMMAND"],
         "DOCKER_TOP_UNTRUSTED")
    matched = set()
    for row in rows[1:]:
        fields = row.split()
        need(len(fields) >= 2 and fields[0].isdigit(), "DOCKER_TOP_UNTRUSTED")
        if executable is None or fields[1].rsplit("/", 1)[-1] == executable:
            matched.add(int(fields[0]))
    need(bool(matched), "PROCESS_INVENTORY_EMPTY")
    return matched


def listener_pids(output: str, ports: tuple[int, ...], executable: str) -> dict[int, set[int]]:
    observed = {port: set() for port in ports}
    all_matching = set()
    for row in output.splitlines():
        fields = row.split(maxsplit=5)
        if len(fields) < 6:
            continue
        try:
            port = int(fields[3].rsplit(":", 1)[-1])
        except ValueError:
            continue
        matches = re.findall(r'"' + re.escape(executable) + r'",pid=(\d+)', fields[5])
        if matches:
            all_matching.add(port)
        if port in observed:
            observed[port].update(int(value) for value in matches)
    need(all_matching.issubset(set(ports)), "UNEXPECTED_OWNER_LISTENER")
    need(all(len(observed[port]) == 1 for port in ports), "OWNER_SOCKET_DRIFT")
    return observed


def require_runtime(obj: dict, image: str) -> None:
    state = obj.get("State") or {}
    need(obj.get("Image") == image, "IMAGE_BASELINE_DRIFT")
    need(state.get("Running") is True, "CONTAINER_NOT_RUNNING")
    need((state.get("Health") or {}).get("Status") == "healthy", "CONTAINER_NOT_HEALTHY")
    need(obj.get("RestartCount") == 0, "CONTAINER_RESTART_DRIFT")


def panel_compose_only(panel: dict) -> None:
    labels = (panel.get("Config") or {}).get("Labels") or {}
    raw = labels.get("com.docker.compose.project.config_files", "")
    files = [item.strip() for item in raw.split(",") if item.strip()]
    need(len(files) == 3 and all(item.startswith("/opt/smite/") for item in files),
         "PANEL_COMPOSE_FILES_DRIFT")
    args = ["docker", "compose"]
    for file in files:
        args += ["-f", file]
    args += ["config", "--format", "json"]
    try:
        config = json.loads(command(*args))
    except ValueError as exc:
        raise Hold("PANEL_COMPOSE_UNTRUSTED") from exc
    services = config.get("services")
    need(isinstance(services, dict) and set(services) == {"smite-panel"},
         "PANEL_COMPOSE_HAS_OTHER_SERVICES")
    panel_spec = services["smite-panel"]
    need(panel_spec.get("network_mode") == "host", "PANEL_NETWORK_MODE_DRIFT")
    need(not panel_spec.get("depends_on"), "PANEL_HAS_DEPENDENCIES")


def audit(host: str) -> None:
    need(os.geteuid() == 0 and socket.gethostname().split(".")[0].lower() == host,
         "WRONG_HOST_OR_USER")
    node = inspect("smite-node")
    require_runtime(node, NODE)
    print("NODE_BASELINE=PASS")

    if host == "ir":
        panel = inspect("smite-panel")
        require_runtime(panel, IR_PANEL)
        panel_compose_only(panel)
        print("PANEL_COMPOSE_ISOLATION=PASS")
        node_pids = process_ids("smite-node")
        panel_pids = process_ids("smite-panel")
        owners = listener_pids(command("ss", "-Hlntp"), OWNER_PORTS, "frps")
        unique = {next(iter(pids)) for pids in owners.values()}
        need(len(unique) == 1, "MULTIPLE_FRPS_OWNERS")
        owner = next(iter(unique))
        need(owner in node_pids and owner not in panel_pids,
             "FRPS_NOT_ISOLATED_FROM_PANEL")
        print("FRPS_INSIDE_NODE_OUTSIDE_PANEL=PASS")
        print("IR_PANEL_ONLY_PLANNING=ELIGIBLE_FOR_REVIEW")
    else:
        # KH has three expected FRPC child processes and an independent 3x-ui.
        ui = inspect("3xui-01")
        need((ui.get("State") or {}).get("Running") is True
             and ui.get("RestartCount") == 0, "SANAEI_RUNTIME_DRIFT")
        frpc = process_ids("smite-node", "frpc")
        need(len(frpc) == 3, "KH_FRPC_COUNT_DRIFT")
        output = command("ss", "-Hlnt")
        listening = set()
        for row in output.splitlines():
            fields = row.split()
            if len(fields) >= 4:
                try:
                    listening.add(int(fields[3].rsplit(":", 1)[-1]))
                except ValueError:
                    pass
        need({443, *TUNNEL_PORTS}.issubset(listening), "KH_LISTENER_DRIFT")
        print("KH_FRPC_THREE=PASS")
        print("KH_LISTENERS=PASS")

    # These are policy blocks, not missing implementation steps.
    print("NODE_RECREATE_WITHOUT_MAINTENANCE=BLOCKED")
    print("UNSIGNED_PREVIEW_ACTIVATION=DENIED")
    print("LIVE_MIGRATION_AUTHORIZED=NO")
    print("DOCKER_MUTATIONS=NONE")
    print("FRP_MUTATIONS=NONE")


def main() -> int:
    if sys.argv[1:] not in (["audit"],):
        print("Usage: smite-stage15-live-migration-gate.py audit", file=sys.stderr)
        return 2
    try:
        host = socket.gethostname().split(".")[0].lower()
        need(host in ("ir", "kh"), "FIELD_TRIAL_IR_KH_ONLY")
        print("===== STAGE15 LIVE MIGRATION READ-ONLY GATE =====")
        audit(host)
        print("MIGRATION_GATE_AUDIT=PASS_READ_ONLY")
        return 0
    except (Hold, KeyError, TypeError) as exc:
        print("MIGRATION_GATE_AUDIT=HOLD")
        print("HOLD_REASON=" + (str(exc) if isinstance(exc, Hold) else "UNTRUSTED_RUNTIME"))
        print("LIVE_MIGRATION_AUTHORIZED=NO")
        print("DOCKER_MUTATIONS=NONE")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
