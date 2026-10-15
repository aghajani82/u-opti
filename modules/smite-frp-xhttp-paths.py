#!/usr/bin/env python3
"""Safe, per-port XHTTP path mapping for Smite Standard FRP (IR gateway).

Smite persists TCP forwarded ports, not KH Xray's HTTP path. Paths live in
a private root-owned side file, defaulting to /PORT/web for legacy tunnels.
No secrets, Xray UUIDs, or FRP tokens are read or rendered here.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

DEFAULT_MAP = Path(os.environ.get(
    "SMITE_FRP_XHTTP_PATHS", "/etc/u-opti/smite/frp-xhttp-paths.json"))
SIDECAR_INCLUDE = Path(os.environ.get(
    "SMITE_FRP_XHTTP_SIDECAR_INC",
    "/etc/nginx/u-opti-backhaul-sidecar-xhttp.inc"))
PORT_DENY = {443, 7000, 8000, 8443, 8888}
PATH_RE = re.compile(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z")
RESERVED = {"api", "assets", "auth", "channel", "docs", "login",
            "static", "sub", "tunnel", "openapi.json"}

class RouteError(ValueError):
    pass

def valid_port(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise RouteError("Invalid forwarded TCP port")
    raw = str(value)
    if not raw.isascii() or not raw.isdecimal():
        raise RouteError("Invalid forwarded TCP port")
    port = int(raw)
    if not 1024 <= port <= 65535 or port in PORT_DENY:
        raise RouteError("Unsafe forwarded TCP port")
    return port

def valid_path(path, port):
    if (not isinstance(path, str) or len(path) > 128
            or not PATH_RE.fullmatch(path)):
        raise RouteError("Invalid XHTTP path: use /segment[/segment], no trailing slash")
    first = path.split("/")[1]
    if first in RESERVED:
        raise RouteError("Reserved HTTP gateway namespace")
    if first.isdecimal() and int(first) != port:
        raise RouteError("Numeric XHTTP path prefix must match its forwarded port")
    return path

def overlaps(a, b):
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")

def default_path(port):
    return f"/{port}/web"

def registry_read(path):
    try:
        st = path.lstat()
    except FileNotFoundError:
        return {}
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) & 0o077 or st.st_size > 65536):
        raise RouteError("Unsafe FRP path registry ownership/mode/size")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise RouteError("Invalid FRP path registry") from exc
    if not isinstance(data, dict) or len(data) > 128:
        raise RouteError("Invalid FRP path registry")
    output = {}
    for key, value in data.items():
        port = valid_port(key)
        if key != str(port):
            raise RouteError("Non-canonical FRP port in registry")
        output[port] = valid_path(value, port)
    return output

def registry_write(path, mapping):
    parent = path.parent
    try:
        parent_stat = parent.lstat()
    except OSError as exc:
        raise RouteError("FRP path registry parent missing") from exc
    if (not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_stat.st_mode) & 0o022):
        raise RouteError("Unsafe FRP path registry parent")
    fd, stage = tempfile.mkstemp(prefix=".frp-path-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            os.fchmod(fp.fileno(), 0o600)
            fp.write(json.dumps({str(p): mapping[p] for p in sorted(mapping)},
                                separators=(",", ":")) + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(stage, path)
    finally:
        if os.path.lexists(stage):
            os.unlink(stage)

def server_ports(state):
    if state.stat().st_size > 1048576:
        raise RouteError("Tunnel state too large")
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise RouteError("Invalid Smite tunnel state") from exc
    if not isinstance(data, dict):
        raise RouteError("Invalid Smite tunnel state")
    ports = set()
    for value in data.values():
        if not isinstance(value, dict) or value.get("core") != "frp":
            continue
        spec = value.get("spec")
        if (not isinstance(spec, dict) or spec.get("mode") != "server"
                or spec.get("type", "tcp") != "tcp"):
            continue
        mapping = spec.get("ports") or [spec.get("remote_port")
                                         or spec.get("listen_port")]
        if not isinstance(mapping, list) or len(mapping) > 128:
            raise RouteError("Invalid FRP server port mappings")
        for item in mapping:
            port = valid_port(item.get("remote") if isinstance(item, dict) else item)
            if port == int(spec.get("bind_port", 7000)):
                raise RouteError("FRP bind port cannot be forwarded")
            ports.add(port)
    if len(ports) > 128:
        raise RouteError("Too many FRP routes")
    return ports

def sidecar_locations():
    try:
        st = SIDECAR_INCLUDE.lstat()
    except FileNotFoundError:
        return []
    if not stat.S_ISREG(st.st_mode) or st.st_size > 65536:
        raise RouteError("Unsafe Sidecar include; refuse overlapping route")
    content = SIDECAR_INCLUDE.read_text(encoding="utf-8")
    return re.findall(r"(?m)^\s*location\s+(?:=|\^~)\s+(/[A-Za-z0-9_/-]+)\s*\{",
                      content)

def render(snapshot, destination, path_file):
    ports = server_ports(snapshot)
    registry = registry_read(path_file)
    paths = {port: registry.get(port, default_path(port)) for port in ports}
    for port, path in paths.items():
        valid_path(path, port)
    occupied = []
    for port, path in sorted(paths.items()):
        if any(overlaps(path, other) for other in occupied):
            raise RouteError("Overlapping FRP XHTTP paths")
        occupied.append(path)
    for external in sidecar_locations():
        for path in paths.values():
            if overlaps(path, external.rstrip("/")):
                raise RouteError("FRP XHTTP route overlaps an installed Backhaul Sidecar")
    shared = (
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "        proxy_buffering off;\n"
        "        proxy_request_buffering off;\n"
        "        proxy_connect_timeout 10s;\n"
        "        proxy_read_timeout 3600s;\n"
        "        proxy_send_timeout 3600s;\n"
    )
    lines = ["# Managed by U-OPTI - Standard FRP XHTTP\n"]
    for port, path in sorted(paths.items()):
        lines.append(f"\n    location = {path} {{\n"
                     f"        proxy_pass http://127.0.0.1:{port};\n"
                     + shared + "    }\n")
        lines.append(f"\n    location ^~ {path}/ {{\n"
                     f"        proxy_pass http://127.0.0.1:{port};\n"
                     + shared + "    }\n")
    destination.write_text("".join(lines), encoding="utf-8")
    print("Valid Standard FRP XHTTP routes:", len(ports))

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    cmd = ap.add_subparsers(dest="cmd", required=True)
    c = cmd.add_parser("render")
    c.add_argument("snapshot", type=Path)
    c.add_argument("output", type=Path)
    c = cmd.add_parser("contains")
    c.add_argument("snapshot", type=Path)
    c.add_argument("port")
    c = cmd.add_parser("check")
    c.add_argument("port")
    c.add_argument("path")
    c = cmd.add_parser("get")
    c.add_argument("port")
    c = cmd.add_parser("set")
    c.add_argument("port")
    c.add_argument("path")
    args = ap.parse_args()
    try:
        if args.cmd == "render":
            render(args.snapshot, args.output, DEFAULT_MAP)
        elif args.cmd == "contains":
            if valid_port(args.port) not in server_ports(args.snapshot):
                raise RouteError("No applied IR FRP server tunnel for that port")
        elif args.cmd == "check":
            valid_path(args.path, valid_port(args.port))
        elif args.cmd == "get":
            port = valid_port(args.port)
            print(registry_read(DEFAULT_MAP).get(port, default_path(port)))
        else:
            if os.geteuid() != 0 and not os.environ.get("UOPTI_FRP_TEST_MODE"):
                raise RouteError("Root required to save FRP XHTTP path")
            port = valid_port(args.port)
            path = valid_path(args.path, port)
            mapping = registry_read(DEFAULT_MAP)
            if path == default_path(port):
                mapping.pop(port, None)
            else:
                mapping[port] = path
            if len(mapping) > 128:
                raise RouteError("Too many stored FRP paths")
            registry_write(DEFAULT_MAP, mapping)
            print("FRP_XHTTP_PATH_REGISTRY_SAVED")
    except (RouteError, OSError, OverflowError, TypeError) as exc:
        print("HOLD:", str(exc), file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
