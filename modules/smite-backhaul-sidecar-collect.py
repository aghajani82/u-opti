#!/usr/bin/env python3
"""READ-ONLY Sidecar IR/KH evidence collector. Emits SANITIZED JSON on stdout.

Never reads TOML/config contents, emits secrets, runs docker exec, starts
containers, changes network settings, runs nginx -t/reload, or writes files.
Only ss, narrowly scoped Docker metadata, and file existence/count are read.

It deliberately leaves any unverified preflight assertions as null. A snapshot
produced by this program is NOT deployment readiness or installation approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PREFLIGHT = Path(__file__).resolve().with_name("smite-backhaul-sidecar-preflight.py")
_spec = importlib.util.spec_from_file_location("uopti_sidecar_gate", PREFLIGHT)
_gate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_gate)

PORTS = {"ir": frozenset((443, 8443, 7000, 3080, 56053)),
         "kh": frozenset((56053, 13080))}
KNOWN = {"nginx", "frps", "xray"}
CONTAINERS = {"ir": "uopti-backhaul-sidecar-ir",
              "kh": "uopti-backhaul-sidecar-kh"}
FILES = {
    "ir": (
        "/etc/u-opti/backhaul-sidecar/ir.toml",
        "/etc/u-opti/backhaul-sidecar/compose-ir.yml",
        "/etc/nginx/u-opti-sidecar/ir-control.inc",
        "/etc/nginx/u-opti-sidecar/ir-xhttp.inc",
    ),
    "kh": (
        "/etc/u-opti/backhaul-sidecar/kh.toml",
        "/etc/u-opti/backhaul-sidecar/compose-kh.yml",
        "/etc/nginx/conf.d/u-opti-backhaul-kh-bridge.conf",
    ),
}


class CollectionError(ValueError):
    pass


def run_readonly(*argv: str) -> str:
    """Fixed allowlist: no shell, mutations, or arbitrary command arguments."""
    if argv == ("ss", "-H", "-l", "-n", "-t", "-p"):
        pass
    elif argv == ("docker", "container", "ls", "--all", "--format", "{{.Names}}"):
        pass
    elif (len(argv) == 7 and argv[:5] ==
          ("docker", "inspect", "--type", "container", "--format") and
          argv[5] in ("{{.HostConfig.NetworkMode}}", "{{.State.Running}}",
                      "{{json .Mounts}}") and
          argv[6] in ("smite-node", "smite-panel")):
        pass
    else:
        raise CollectionError("Command not on strict read-only allowlist")
    try:
        result = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=True, text=True, timeout=7,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise CollectionError("Read-only inspection unavailable") from exc
    if len(result.stdout) > 256_000:
        raise CollectionError("Unexpectedly large inspection response")
    return result.stdout.strip()


def masked_ip(value: str) -> str:
    """Keep only bind category/family, never the server's public IP."""
    if value in ("*", "0.0.0.0"):
        return "0.0.0.0"
    if value in ("::", "[::]"):
        return "::"
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise CollectionError("Cannot classify listening address") from exc
    if address.is_loopback:
        if address.version == 4:
            return "127.0.0.1" if str(address) == "127.0.0.1" else "127.0.0.2"
        return "::1"
    # Fixed documentation prefixes are REDACTIONS, NOT actual IPs.
    return "192.0.2.1" if address.version == 4 else "2001:db8::1"


def parse_ss(raw: str, role: str) -> list[dict]:
    if role not in PORTS:
        raise CollectionError("Invalid role")
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        fields = line.split(maxsplit=6)
        if len(fields) < 5 or fields[0] != "LISTEN":
            raise CollectionError("Unrecognized TCP LISTEN record; refuse inference")
        local = fields[3]
        if ":" not in local:
            raise CollectionError("Unrecognized TCP listen address")
        host, separator, port_raw = local.rpartition(":")
        if not separator or not port_raw.isdigit():
            raise CollectionError("Non-numeric TCP listen port")
        port = int(port_raw)
        if not 1 <= port <= 65535:
            raise CollectionError("Invalid listening port")
        if port not in PORTS[role]:
            continue
        addr = masked_ip(host)
        owners = set(re.findall(r'\("([^"]{1,100})",pid=\d+', line))
        if len(owners) == 1 and next(iter(owners)) in KNOWN:
            owner = next(iter(owners))
        else:
            owner = "other"  # no PID, executable path, or unknown process leaked
        item = {"address": addr, "port": port, "owner": owner}
        if item in out:
            continue  # ss may show repeated worker processes on one socket
        out.append(item)
    return sorted(out, key=lambda x: (x["port"], x["address"], x["owner"]))


def legacy_config_count(mounts_json: str) -> int | None:
    """Count *.toml filenames ONLY from exact Smite Node config bind mount."""
    try:
        mounts = json.loads(mounts_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(mounts, list):
        return None
    candidates = [
        x for x in mounts
        if isinstance(x, dict)
        and x.get("Destination") == "/etc/smite-node"
        and x.get("Type") == "bind"
        and isinstance(x.get("Source"), str)
    ]
    if len(candidates) != 1:
        return None
    try:
        parent = Path(candidates[0]["Source"])
        if parent.is_symlink():
            return None
        directory = parent / "backhaul"
        if directory.is_symlink():
            return None
        if not directory.is_dir():
            return 0  # directory absent: no Smite-managed Backhaul TOMLs
        with os.scandir(directory) as scan:
            return sum(
                e.name.endswith(".toml") and e.is_file(follow_symlinks=False)
                for e in scan
            )
    except (OSError, ValueError):
        return None


def snapshot_from_observations(
    role: str, raw_ss: str, network_mode: str | None,
    container_names: list[str] | None, node_running: bool | None,
    panel_running: bool | None, legacy_count: int | None,
    existing_files: dict[str, bool | None],
    now: datetime | None = None,
) -> dict:
    """Pure constructor for simulated test fixtures; no host interaction."""
    if role not in PORTS:
        raise CollectionError("Invalid role")
    if not isinstance(existing_files, dict) or set(existing_files) != set(FILES[role]):
        raise CollectionError("Missing file-ownership observations")
    if container_names is not None and (
        not isinstance(container_names, list) or
        not all(isinstance(n, str) for n in container_names)
    ):
        raise CollectionError("Invalid container inventory")
    if legacy_count is not None and (type(legacy_count) is not int or legacy_count < 0):
        raise CollectionError("Invalid legacy count")
    checks: dict[str, bool | None] = {name: None for name in _gate.EXPECTED[role]}
    checks["smite_node_running"] = node_running
    if role == "ir":
        checks["smite_panel_running"] = panel_running
    if container_names is not None:
        checks["sidecar_names_unallocated"] = CONTAINERS[role] not in container_names
    if all(value is not None for value in existing_files.values()):
        checks["sidecar_files_absent"] = not any(existing_files.values())
    listeners = parse_ss(raw_ss, role)
    if role == "ir":
        checks["stream_443_nginx_owned"] = any(
            p["port"] == 443 and p["owner"] == "nginx" for p in listeners
        )
    # Everything else requires separate verification/manual review: do NOT
    # "green" TLS, stream rules, FRP continuity, Nginx syntax or Xray routing.
    timestamp = now if now is not None else datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise CollectionError("Timestamp must have timezone")
    return {
        "role": role,
        "observed_at": timestamp.isoformat(),
        "ports": {
            "role": role,
            "network_mode": network_mode if network_mode in ("host", "bridge") else "unknown",
            "listeners": listeners,
        },
        "checks": checks,
        # Image labels/tags cannot prove the actual binary version or Smite version.
        "versions": {"backhaul": None, "smite": None},
        "baseline": {"legacy_clients": legacy_count},
    }


def collect(role: str) -> dict:
    if role not in PORTS:
        raise CollectionError("Unknown role")
    raw_ss = run_readonly("ss", "-H", "-l", "-n", "-t", "-p")
    try:
        mode = run_readonly(
            "docker", "inspect", "--type", "container", "--format",
            "{{.HostConfig.NetworkMode}}", "smite-node"
        )
        node_status = run_readonly(
            "docker", "inspect", "--type", "container", "--format",
            "{{.State.Running}}", "smite-node"
        )
        mounts = run_readonly(
            "docker", "inspect", "--type", "container", "--format",
            "{{json .Mounts}}", "smite-node"
        )
        names = run_readonly(
            "docker", "container", "ls", "--all", "--format", "{{.Names}}"
        ).splitlines()
        if role == "ir":
            panel_status = run_readonly(
                "docker", "inspect", "--type", "container", "--format",
                "{{.State.Running}}", "smite-panel"
            )
        else:
            panel_status = None
    except CollectionError:
        # No ambiguous Docker output can ever be considered a clear port or
        # container ownership picture. Do not output a partial success report.
        raise
    if node_status not in ("true", "false") or (
        panel_status is not None and panel_status not in ("true", "false")
    ):
        raise CollectionError("Invalid container status")
    count = legacy_config_count(mounts)
    existing_files = {}
    for file in FILES[role]:
        try:
            existing_files[file] = os.path.lexists(file)
        except OSError:
            existing_files[file] = None
    return snapshot_from_observations(
        role, raw_ss, mode, names, node_status == "true",
        None if panel_status is None else panel_status == "true",
        count, existing_files,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("ir", "kh"), required=True)
    args = parser.parse_args()
    try:
        output = collect(args.role)
    except (CollectionError, OSError, ValueError) as exc:
        parser.error("READ-ONLY COLLECTION INCOMPLETE: " + type(exc).__name__)
    print(json.dumps(output, ensure_ascii=True, indent=2, sort_keys=True))
    print("UNVERIFIED: this is sanitized evidence, NOT install approval", file=sys.stderr)


if __name__ == "__main__":
    main()
