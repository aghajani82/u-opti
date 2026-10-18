#!/usr/bin/env python3
"""Stage12: prepare PRIVATE, INERT Nginx path-preserving HMAC Agent snippet.

NO Nginx reload, live vhost editing, cert generation, firewall change,
DNS change, Docker action or user tunnel mutation. The resulting snippet
MUST be manually reviewed against the active host-specific Nginx server
context, duplicate locations, TLS hostname, CDN and upstream port.

This applies ONLY to a direct/DNS-only Standard KH hostname; Cloudflare
proxied ingress or Private Network mode requires a separate access design.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import stat
import sys


class NginxPlanHold(Exception):
    pass


def allowed_panel_ip(value: str) -> str:
    if not isinstance(value, str):
        raise NginxPlanHold("Panel source address is invalid")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise NginxPlanHold("Only a confirmed literal Panel IP is allowed") from exc
    if (
        address.is_unspecified or address.is_multicast
        or address.is_loopback or address.is_link_local
    ):
        raise NginxPlanHold("Panel source IP must be a real routed address")
    return str(address)


def render(*, panel_ip: str) -> str:
    ip = allowed_panel_ip(panel_ip)
    # No URI component on proxy_pass: preserve exact client /api/agent
    # path and query bytes for node_auth HMAC verification.
    return (
        "# U-OPTI STAGE12 SIGNED AGENT CONTROL - CANDIDATE ONLY / NEVER ACTIVE\n"
        "# Review inside the EXISTING TLS/443 KH server {} block.\n"
        "# Direct/DNS-only KH ingress: ACL is the actual IR source IP.\n"
        "# Reject Cloudflare-proxied ingress until an authenticated edge policy is reviewed.\n"
        "# Do not use the legacy hidden gateway path with '/'-suffixed proxy_pass.\n"
        "location ^~ /api/agent/ {\n"
        "    allow 127.0.0.1;\n"
        "    allow ::1;\n"
        f"    allow {ip};\n"
        "    deny all;\n"
        "    limit_except GET POST { deny all; }\n"
        "    client_max_body_size 1m;\n"
        "    proxy_http_version 1.1;\n"
        "    proxy_request_buffering on;\n"
        "    proxy_pass http://127.0.0.1:8888;\n"
        "    proxy_set_header Host $host;\n"
        "    proxy_set_header X-Forwarded-Proto https;\n"
        "    proxy_set_header X-Real-IP $remote_addr;\n"
        "    proxy_connect_timeout 5s;\n"
        "    proxy_read_timeout 35s;\n"
        "    proxy_send_timeout 35s;\n"
        "}\n"
    )


def prepare(*, panel_ip: str, output: Path) -> str:
    if output.exists() or output.is_symlink():
        raise NginxPlanHold("Candidate already exists; refusing overwrite")
    if not output.is_absolute():
        raise NginxPlanHold("Use an absolute candidate file path")
    parent = output.parent
    try:
        info = parent.lstat()
    except OSError as exc:
        raise NginxPlanHold("Create a private candidate parent first") from exc
    if (
        not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.geteuid()
    ):
        raise NginxPlanHold("Candidate parent must be user-owned mode 0700")
    data = render(panel_ip=panel_ip)
    try:
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise NginxPlanHold("Could not create offline Nginx candidate") from exc
    return "INERT_NGINX_SNIPPET_PREPARED"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel-source-ip", required=True)
    p.add_argument("--output", type=Path, required=True)
    o = p.parse_args()
    try:
        value = prepare(panel_ip=o.panel_source_ip, output=o.output)
        print("STAGE12=" + value)
        print("NGINX_RELOAD=NO")
        print("SIGNED_PATH_PRESERVATION=UNVERIFIED_ON_REAL_SERVER")
        print("SIGNED_MODE_ACTIVATION=BLOCKED")
        return 0
    except (NginxPlanHold, OSError) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
