#!/usr/bin/env python3
"""Read-only RC.2 Signed Smite FRP WSS/443 candidate and preservation admission.

NEVER installs an override or modifies Nginx, Compose, Node, ports or Replay.
Uses Docker Compose config --format json with -f - for in-memory preview,
explicitly requiring signed Identity/Replay mounts and exact strict auth.
The current Nginx stream-to-TLS-backend path does NOT preserve peer source
by default; this checker does not claim KH-IP ACL enforcement.

A separate independently reviewed change/rollback transaction is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

NODE = Path("/opt/smite-node")
BASE = NODE / "docker-compose.yml"
SIGNED = NODE / "docker-compose.security-candidate.yml"
BACKEND = Path("/etc/nginx/conf.d/u-opti-smite-panel-backend.conf")
DOMAIN = "ir.kolbe1.ir"
FRP_PATH = "/~!frp"
OVERLAY = (
    "services:\n"
    "  smite-node:\n"
    "    environment:\n"
    "      - SMITE_FRP_STANDARD_WSS=1\n"
)
ENGINES = ("backhaul", "frp", "gost", "rathole", "chisel")
MANDATORY = {
    "SMITE_AGENT_AUTH_MODE": "strict",
    "SMITE_NODE_PANEL_AUTH_MODE": "signed",
    "SMITE_ENGINE_INVENTORY_MODE": "managed",
}


class Hold(Exception):
    pass


def require(condition: bool, why: str) -> None:
    if not condition:
        raise Hold(why)


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def read_file(path: Path, *, limit: int = 131072) -> bytes:
    import stat
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and
            st.st_nlink == 1 and not st.st_mode & 0o022 and
            st.st_size <= limit, "UNTRUSTED_FILE")
    return path.read_bytes()


def render_backend(original: str, *, domain: str = DOMAIN) -> str:
    require(domain == DOMAIN, "UNREVIEWED_PANEL_DOMAIN")
    require(original.startswith("# Managed by U-OPTI - Smite Panel TLS backend\n"),
            "UNMANAGED_TLS_BACKEND")
    require(original.count("server_name " + domain + ";") == 1 and
            original.count("    listen 127.0.0.1:8443 ssl;") == 1,
            "UNEXPECTED_TLS_BACKEND")
    require(original.count("    location / {\n") == 1 and
            original.count("proxy_pass http://127.0.0.1:8000;") >= 1,
            "UNEXPECTED_PANEL_LOCATION")
    require("BEGIN U-OPTI STANDARD FRP WSS" not in original and
            not re.search(r"(?m)^\s*location\s+[^;\n]*\/~!frp", original),
            "EXISTING_FRP_LOCATION_REQUIRES_REVIEW")
    # HTTP-level 'allow KH_IP' would see 127.0.0.1 from the upstream
    # stream->loopback TLS proxy, NOT the original KH source address.
    # Do not silently promise an effective source-IP ACL. The reviewed
    # rollout must decide between proxy_protocol with trusted real-IP,
    # or a different network-edge ACL after validating all Panel routes.
    snippet = (
        "    # BEGIN U-OPTI RC2 FRP WSS CANDIDATE\n"
        "    # No KH source allowlist claimed: stream upstream obscures peer IP.\n"
        "    # Do NOT activate without separate edge ACL and FRP token review.\n"
        "    location = /~!frp {\n"
        "        proxy_pass http://127.0.0.1:7000;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header Upgrade $http_upgrade;\n"
        "        proxy_set_header Connection \"upgrade\";\n"
        "        proxy_connect_timeout 10s;\n"
        "        proxy_read_timeout 3600s;\n"
        "        proxy_send_timeout 3600s;\n"
        "        proxy_buffering off;\n"
        "    }\n"
        "    # END U-OPTI RC2 FRP WSS CANDIDATE\n\n"
    )
    return original.replace("    location / {\n",
                            snippet + "    location / {\n", 1)


def environ(value) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, list):
        result: dict[str, str] = {}
        for line in value:
            require(isinstance(line, str) and "=" in line, "BAD_COMPOSE_ENV")
            k, v = line.split("=", 1)
            require(k not in result, "DUPLICATE_COMPOSE_ENV")
            result[k] = v
        return result
    raise Hold("BAD_COMPOSE_ENV")


def mount_targets(service: dict) -> set[str]:
    targets = set()
    for item in service.get("volumes", []):
        if isinstance(item, dict):
            targets.add(item.get("target", ""))
        elif isinstance(item, str):
            parts = item.split(":")
            if len(parts) >= 2:
                targets.add(parts[1])
    return targets


def validate_preview(current: dict, effective: dict, image: str) -> None:
    require(current.get("Config", {}).get("Image") == image, "REVIEWED_IMAGE_REQUIRED")
    require(current.get("State", {}).get("Running") is True, "NODE_NOT_RUNNING")
    service = effective.get("services", {}).get("smite-node", {})
    require(service.get("image") == image, "COMPOSE_IMAGE_DRIFT")
    actual = environ(current["Config"]["Env"])
    trial = environ(service.get("environment", {}))
    require(actual.get("SMITE_FRP_STANDARD_WSS") not in ("1",) and
            trial.get("SMITE_FRP_STANDARD_WSS") == "1", "WSS_NOT_EXPLICITLY_ENABLED")
    for k, value in MANDATORY.items():
        require(actual.get(k) == value and trial.get(k) == value,
                "SIGNED_AUTH_NOT_PRESERVED")
    require(actual.get("PANEL_ADDRESS", "").endswith(":443")
            and trial.get("PANEL_ADDRESS", "").endswith(":443"),
            "443_PANEL_ADDRESS_REQUIRED")
    expected_mounts = {"/etc/smite-node",
                       "/run/smite-node-identity",
                       "/var/lib/smite-node/auth"}
    present = {m.get("Destination") for m in current.get("Mounts", [])}
    require(expected_mounts <= present
            and expected_mounts <= mount_targets(service),
            "SIGNED_MOUNTS_NOT_PRESERVED")
    require(service.get("network_mode") == "host", "NETWORK_MODE_CHANGED")
    # The local Agent's public bind must not be expanded through Compose.
    command = service.get("command") or []
    if isinstance(command, list):
        joined = " ".join(str(x) for x in command)
    else:
        joined = str(command)
    require("127.0.0.1" in joined and "8888" in joined,
            "SIGNED_AGENT_LOCAL_BIND_LOST")


def local_inventory() -> None:
    program = (
        "from app.engine_inventory import engine_inventory; "
        "x=engine_inventory(); print(x['mode']+':'+x['engines']['frp'])"
    )
    r = subprocess.run(
        ["docker", "exec", "smite-node", "python3", "-B", "-c", program],
        capture_output=True, text=True, timeout=15, check=False)
    require(r.returncode == 0 and r.stdout.strip() == "managed:ready",
            "MANAGED_FRP_NOT_READY")


def run_plan(host: str) -> None:
    require(os.geteuid() == 0 and
            os.uname().nodename.split(".")[0].lower() == host and
            host in ("ir", "kh"), "WRONG_HOST_OR_USER")
    read_file(BASE)
    read_file(SIGNED)
    r = subprocess.run(
        ["docker", "inspect", "smite-node"],
        capture_output=True, text=True, timeout=15)
    require(r.returncode == 0, "NODE_INSPECT_FAILED")
    obj = json.loads(r.stdout)[0]
    labels = obj.get("Config", {}).get("Labels") or {}
    require("docker-compose.security-candidate.yml" in
            labels.get("com.docker.compose.project.config_files", ""),
            "SIGNED_OVERLAY_NOT_ACTIVE")
    cmd = ["docker", "compose",
           "-f", str(BASE), "-f", str(SIGNED), "-f", "-",
           "config", "--format", "json"]
    compiled = subprocess.run(
        cmd, input=OVERLAY, capture_output=True, text=True,
        timeout=30, cwd=NODE)
    require(compiled.returncode == 0, "COMPOSE_PREVIEW_FAILED")
    data = json.loads(compiled.stdout)
    validate_preview(obj, data, obj["Config"]["Image"])
    local_inventory()
    print("HOST=" + host.upper())
    print("SIGNED_COMPOSE_PREVIEW=PASS_READ_ONLY")
    print("FRP_WSS_OVERLAY_SHA256=" + digest(OVERLAY.encode()))
    if host == "ir":
        orig = read_file(BACKEND).decode("utf-8")
        output = render_backend(orig)
        require(output != orig, "NGINX_CANDIDATE_IDENTICAL")
        ng = subprocess.run(["nginx", "-t"],
                            capture_output=True, text=True, timeout=15)
        require(ng.returncode == 0, "CURRENT_NGINX_INVALID")
        print("IR_NGINX_WSS_CANDIDATE=PASS_IN_MEMORY")
        print("IR_NGINX_WSS_CANDIDATE_SHA256=" + digest(output.encode()))
        print("REAL_KH_SOURCE_ACL=NOT_ESTABLISHED")
    print("SIGNED_NODE_RECREATION=NOT_AUTHORIZED")
    print("WSS_ACTIVATION=NOT_PERFORMED")
    print("LIVE_CHANGES=NONE")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("plan",))
    args = p.parse_args()
    try:
        run_plan(os.uname().nodename.split(".")[0].lower())
        return 0
    except (Hold, OSError, KeyError, ValueError, TypeError,
            subprocess.SubprocessError, UnicodeError) as error:
        code = str(error)
        if not re.fullmatch(r"[A-Z0-9_]{1,90}", code):
            code = "UNTRUSTED_RC2_WSS_STATE"
        print("WSS_GATE=HOLD_" + code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
