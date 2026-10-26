#!/usr/bin/env python3
"""RC.2-only FRP WSS peer-scoped Nginx dual-backend offline gate.

Existing Nginx Stream SNI + *actual* remote_addr map routes only vetted
KH public IPv4 to a new 127.0.0.1:8444 TLS clone of the already-managed
IR Panel backend. All others remain on current 127.0.0.1:8443 (no FRP
location), so an HTTP-level loopback "allow KH" fiction is unnecessary.

This helper ONLY READS files, Nginx config and socket table. It does
NOT install, reload, open a listener, touch TLS/identity/replay/Compose,
or permit FRP tunnel Apply. The stage is for signed RC.2 test hosts ONLY.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import socket
import stat
import subprocess

TLS_SOURCE = Path("/etc/nginx/conf.d/u-opti-smite-panel-backend.conf")
STREAM_SOURCE = Path("/etc/nginx/modules-enabled/99-u-opti-smite-stream.conf")
FRP_MAP = Path("/etc/nginx/u-opti-smite-frp-sni-map.conf")
DOMAIN = "ir.kolbe1.ir"
ALT_PORT = 8444
ALT_LISTEN = "127.0.0.1:8444"
ALT_CANDIDATE = Path("/etc/nginx/conf.d/u-opti-smite-panel-kh-wss.conf")
OLD_LISTEN = "    listen 127.0.0.1:8443 ssl;"
BACKEND_HEADER = "# Managed by U-OPTI - Smite Panel TLS backend\n"
MAP_HEADER = "# U-OPTI FRP TLS/SNI allowlist (SNI + source IPv4 required)\n"

class Hold(Exception):
    pass

def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Hold(reason)

def read_safe(path: Path, limit: int = 262144) -> str:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode)
            and info.st_uid == 0 and info.st_nlink == 1
            and not stat.S_IMODE(info.st_mode) & 0o022
            and 0 <= info.st_size <= limit, "UNSAFE_NGINX_INPUT")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        require((st.st_dev, st.st_ino) == (info.st_dev, info.st_ino),
                "NGINX_INPUT_CHANGED")
        data = f.read(limit + 1)
    require(len(data) <= limit, "NGINX_INPUT_OVERSIZED")
    return data.decode("utf-8")

def sha(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()

def kh_ip(value: str) -> str:
    try:
        ip = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, ValueError) as e:
        raise Hold("VALID_KH_PUBLIC_IPV4_REQUIRED") from e
    require(ip.is_global and not ip.is_multicast, "VALID_KH_PUBLIC_IPV4_REQUIRED")
    return str(ip)

def render_alt(source: str) -> str:
    require(source.startswith(BACKEND_HEADER), "UNMANAGED_TLS_BACKEND")
    require(source.count(OLD_LISTEN) == 1
            and source.count("server_name " + DOMAIN + ";") == 1,
            "NONCANONICAL_IR_TLS_BACKEND")
    require(source.count("    location / {\n") == 1
            and source.count("proxy_pass http://127.0.0.1:8000;") >= 1,
            "PANEL_HTTP_BACKEND_CHANGED")
    require("location = /~!frp" not in source
            and "BEGIN U-OPTI RC2 FRP WSS" not in source,
            "FRP_WSS_ALREADY_EXISTS")
    # Must not accidentally clone an arbitrary extra top-level server
    # or another listen socket beyond the reviewed one.
    require(len(re.findall(r"(?m)^\s*server\s*\{\s*$", source)) == 1
            and len(re.findall(r"(?m)^\s*listen\s+", source)) == 1,
            "UNEXPECTED_TLS_BACKEND_LAYOUT")
    from_panel = source.replace(OLD_LISTEN,
                  "    listen " + ALT_LISTEN + " ssl;", 1)
    block = (
        "    # BEGIN U-OPTI RC2 FRP WSS KH-ONLY\n"
        "    # Restricted by outer Nginx stream SNI+source-IP map.\n"
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
        "    # END U-OPTI RC2 FRP WSS KH-ONLY\n\n"
    )
    return from_panel.replace("    location / {\n", block+"    location / {\n", 1)

def render_map(source: str, peer_ip: str) -> str:
    require(source.startswith(MAP_HEADER), "UNMANAGED_STREAM_SNI_MAP")
    line = f'    "{DOMAIN}|{peer_ip}" {ALT_LISTEN};'
    require(line not in source, "KH_STREAM_RULE_ALREADY_REGISTERED")
    require(not re.search(r"(?m)^\s*\""+re.escape(DOMAIN)
                          +r"\|"+re.escape(peer_ip)+r"\"\s+", source),
            "KH_STREAM_RULE_CONFLICT")
    # Only append an exact match; preserve every original rule byte-for-byte.
    require(source.endswith("\n"), "NONCANONICAL_STREAM_MAP")
    return source + line + "\n"

def stream_gate(stream: str) -> None:
    require(stream.startswith("# Managed by U-OPTI - Smite TCP/443 SNI gateway\n"),
            "UNMANAGED_STREAM_GATEWAY")
    require(stream.count("map \"$ssl_preread_server_name|$remote_addr\" $uopti_frp_canary_backend {") == 1
            and stream.count("include "+str(FRP_MAP)+";") == 1
            and stream.count("default $uopti_smite_backend;") == 1,
            "STREAM_SOURCE_ALLOWLIST_NOT_ACTIVE")
    require(stream.count("proxy_pass $uopti_frp_canary_backend;") == 1,
            "STREAM_PROXY_NOT_USING_IP_MAP")
    require("listen 443;" in stream and "ssl_preread on;" in stream,
            "PUBLIC_TLS_GATEWAY_CHANGED")
    require("proxy_protocol on;" not in stream,
            "UNREVIEWED_STREAM_PROTOCOL")

def loopback_port_free(port: int) -> None:
    result = subprocess.run(
        ["ss", "-H", "-lnt", f"( sport = :{port} )"],
        capture_output=True, text=True, timeout=12)
    require(result.returncode == 0 and not result.stdout.strip(),
            "ALT_TLS_LOOPBACK_PORT_BUSY")

def plan(peer_ip: str) -> None:
    require(os.geteuid() == 0 and
            socket.gethostname().split(".")[0].lower() == "ir",
            "IR_ROOT_ONLY")
    ip = kh_ip(peer_ip)
    require(not ALT_CANDIDATE.exists() and not ALT_CANDIDATE.is_symlink(),
            "ALT_BACKEND_ALREADY_EXISTS")
    current = read_safe(TLS_SOURCE)
    stream = read_safe(STREAM_SOURCE)
    mapping = read_safe(FRP_MAP)
    stream_gate(stream)
    new_backend = render_alt(current)
    new_map = render_map(mapping, ip)
    loopback_port_free(ALT_PORT)
    test = subprocess.run(["nginx", "-t"], capture_output=True,
                          text=True, timeout=20)
    require(test.returncode == 0, "CURRENT_NGINX_INVALID")
    print("IR_FRP_WSS_EDGE_PLAN=PASS_IN_MEMORY")
    print("KH_PEER_IPV4_INPUT_VALID=YES")
    print("KH_PEER_IP_OWNERSHIP=OPERATOR_VERIFICATION_REQUIRED")
    print("SOURCE_BACKEND_SHA256=" + sha(current))
    print("ALTERNATE_BACKEND_SHA256=" + sha(new_backend))
    print("SOURCE_STREAM_MAP_SHA256=" + sha(mapping))
    print("PROPOSED_STREAM_MAP_SHA256=" + sha(new_map))
    print("ALT_TLS_LISTEN=127.0.0.1:8444")
    print("KH_IP_MATCHED_BY_STREAM_MAP=YES")
    print("ORDINARY_PANEL_BACKEND=UNMODIFIED")
    print("DURABLE_RECONCILIATION=NOT_IMPLEMENTED")
    print("WSS_ACTIVATION=NOT_PERFORMED")
    print("NODE_RESTART=NO")
    print("NGINX_RELOAD=NO")
    print("LIVE_CHANGES=NONE")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan",))
    parser.add_argument("--kh-ip", required=True,
                        help="Operator-verified KH public egress IPv4")
    args = parser.parse_args()
    try:
        plan(args.kh_ip)
        return 0
    except (Hold, OSError, UnicodeError, KeyError, TypeError, ValueError,
            subprocess.SubprocessError) as e:
        reason = str(e)
        if not re.fullmatch(r"[A-Z0-9_]{1,100}", reason):
            reason = "UNTRUSTED_IR_WSS_EDGE_STATE"
        print("IR_FRP_WSS_EDGE_PLAN=HOLD_" + reason)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
