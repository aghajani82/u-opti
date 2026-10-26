#!/usr/bin/env python3
"""Verify only the paired Foreign Node's own gateway over signed HTTPS/443.

Never enumerates Panel Nodes. Uses U-OPTI's staged, root-owned 0600 identity,
not administrator JWT or a reusable credential embedded in URLs/logs.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import stat
import sys
import time
from urllib import request, error, parse

IDENTITY = Path("/etc/u-opti/smite/identities/node-identity.json")
UUID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
SECRET = re.compile(r"^[a-f0-9]{64}$")
HOST = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
TARGET = "/api/node-control/gateway-check"
VERSION = "smite-node-hmac-v1"


class GatewayHold(Exception):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _private_identity(path: Path) -> tuple[str, bytes]:
    try:
        parent = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise GatewayHold("Private Node identity directory is unsafe")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            item = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(item.st_mode)
                or item.st_uid != os.geteuid()
                or stat.S_IMODE(item.st_mode) != 0o600
                or item.st_size > 4096
            ):
                raise GatewayHold("Node identity file permissions are unsafe")
            info = json.loads(handle.read(4097))
        node_id, secret = info["node_id"], info["node_secret"]
        if (
            not isinstance(node_id, str) or not UUID.fullmatch(node_id)
            or not isinstance(secret, str) or not SECRET.fullmatch(secret)
        ):
            raise GatewayHold("Invalid paired Node identity")
        return node_id, secret.encode("ascii")
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise GatewayHold("Paired Node identity unavailable") from exc


def _panel_url(domain: str) -> str:
    if not isinstance(domain, str) or not HOST.fullmatch(domain.lower()):
        raise GatewayHold("Invalid Panel HTTPS domain")
    return "https://" + domain.lower() + TARGET


def _control_url(value: str) -> str:
    try:
        parsed = parse.urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
    except (ValueError, TypeError) as exc:
        raise GatewayHold("Invalid Foreign HTTPS control URL") from exc
    if (
        parsed.scheme != "https" or not hostname or not HOST.fullmatch(hostname.lower())
        or port not in (None, 443)
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or not parsed.path.startswith("/") or parsed.path == "/"
    ):
        raise GatewayHold("Foreign control must use HTTPS/443 with a path")
    return value.rstrip("/")


def build_signed_request(
    *, domain: str, node_name: str, control_url: str, identity: Path = IDENTITY,
    moment: int | None = None, nonce: str | None = None,
) -> request.Request:
    """Construct the byte-exact HMAC envelope used by Smite Node v1."""
    url = _panel_url(domain)
    if not isinstance(node_name, str) or not 1 <= len(node_name) <= 128:
        raise GatewayHold("Invalid Foreign node name")
    expected = _control_url(control_url)
    node_id, secret = _private_identity(identity)
    body = json.dumps(
        {"node_id": node_id, "node_name": node_name, "control_url": expected},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(body) > 8192:
        raise GatewayHold("Node gateway check too large")
    stamp = str(int(time.time()) if moment is None else int(moment))
    unique = secrets.token_hex(16) if nonce is None else nonce
    if not re.fullmatch(r"[a-f0-9]{32}", unique):
        raise GatewayHold("Invalid request nonce")
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((VERSION, node_id, "POST", TARGET, stamp, unique, payload_hash)).encode()
    signature = hmac.new(secret, canonical, "sha256").hexdigest()
    return request.Request(
        url, method="POST", data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "X-Smite-Node-ID": node_id,
            "X-Smite-Timestamp": stamp,
            "X-Smite-Nonce": unique,
            "X-Smite-Signature": signature,
        },
    )


def verify_gateway(
    *, domain: str, node_name: str, control_url: str,
    identity: Path = IDENTITY,
) -> bool:
    req = build_signed_request(
        domain=domain, node_name=node_name,
        control_url=control_url, identity=identity,
    )
    # Verify public-CA TLS and DNS hostname. Never follow redirects or
    # use an environment-configured proxy for this credential-bearing call.
    opener = request.build_opener(
        request.ProxyHandler({}),
        request.HTTPSHandler(context=ssl.create_default_context()),
        NoRedirect(),
    )
    try:
        with opener.open(req, timeout=15) as response:
            if response.status != 200:
                return False
            raw = response.read(4097)
            if len(raw) > 4096:
                return False
            parsed = json.loads(raw)
            return (
                isinstance(parsed, dict)
                and parsed.get("status") == "ok"
                and parsed.get("gateway_ready") is True
            )
    except (error.HTTPError, error.URLError, OSError, ValueError, ssl.SSLError):
        # Never log a signed request, its URL, key, or HTTP error body.
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel-domain", required=True)
    parser.add_argument("--node-name", required=True)
    parser.add_argument("--control-url", required=True)
    args = parser.parse_args()
    try:
        return 0 if verify_gateway(
            domain=args.panel_domain,
            node_name=args.node_name,
            control_url=args.control_url,
        ) else 2
    except GatewayHold:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
