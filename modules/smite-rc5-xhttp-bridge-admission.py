#!/usr/bin/env python3
"""U-OPTI / Smite RC5: read-only host TLS/443 XHTTP bridge admission.

This module ONLY prepares a proposed one-line include insertion in the
existing U-OPTI-owned IR HTTPS backend. There is NO file writer, new port,
service reload, systemd change, Node RPC, or network POST in this module.
A later separately reviewed host transaction must implement the apply gate.
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

BACKEND = Path("/etc/nginx/conf.d/u-opti-smite-panel-backend.conf")
STREAM = Path("/etc/nginx/modules-enabled/99-u-opti-smite-stream.conf")
SNI_MAP = Path("/etc/nginx/u-opti-smite-stream-map.conf")
LEGACY = Path("/etc/nginx/u-opti-smite-frp-xhttp.conf")
STATE = Path("/etc/u-opti/smite/state.env")
BRIDGE = Path("/etc/nginx/smite-xhttp-bridge.conf")
ROUTE_DIR = Path("/etc/nginx/smite-xhttp-routes")
NGINX = "/usr/sbin/nginx"
DOMAIN = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}\Z")
INCLUDE = b"    include /etc/nginx/smite-xhttp-bridge.conf;\n"
OLD_INCLUDE = b"    include /etc/nginx/u-opti-smite-frp-xhttp.conf;\n"
ROOT_LOCATION = b"    location / {\n"
MAX_BYTES = 131072


class BridgeHold(ValueError):
    """A precondition failed. Never change host configuration."""


@dataclasses.dataclass(frozen=True)
class BridgePlan:
    original: bytes
    candidate: bytes
    domain: str
    destination: str
    change_count: int


def _one(data: bytes, value: bytes, hold: str) -> None:
    if data.count(value) != 1:
        raise BridgeHold(hold)


def propose_bridge(
    *, backend: bytes, stream: bytes, sni_map: bytes,
    legacy: bytes, domain: str, timer_enabled: bool,
    bridge_exists: bool, directory_exists: bool,
) -> BridgePlan:
    """Validate a known U-OPTI stream/TLS backend pair, then plan one diff.

    This pure function is also the offline, adversarial test entrypoint.
    It is not proof the candidate has been installed or activated.
    """
    if not DOMAIN.fullmatch(domain):
        raise BridgeHold("INVALID_PANEL_DOMAIN")
    if timer_enabled:
        raise BridgeHold("LEGACY_XHTTP_TIMER_UNSAFE")
    if bridge_exists or directory_exists:
        raise BridgeHold("EXISTING_BRIDGE_REQUIRES_MIGRATION_REVIEW")
    for data in (backend, stream, sni_map, legacy):
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
            raise BridgeHold("INVALID_SOURCE_CONTENT")
    if not backend.startswith(b"# Managed by U-OPTI - Smite Panel TLS backend\n"):
        raise BridgeHold("UNAPPROVED_PANEL_BACKEND")
    _one(backend, b"server {", "BACKEND_SERVER_COUNT")
    _one(backend, b"listen 127.0.0.1:8443 ssl;", "BACKEND_8443_MISSING")
    _one(backend, f"server_name {domain};".encode(), "DOMAIN_MISMATCH")
    _one(backend, f"/etc/letsencrypt/live/{domain}/fullchain.pem;".encode(),
         "CERTIFICATE_MISMATCH")
    _one(backend, f"/etc/letsencrypt/live/{domain}/privkey.pem;".encode(),
         "CERTIFICATE_MISMATCH")
    _one(backend, OLD_INCLUDE, "UOPTI_XHTTP_INCLUDE_MISSING_OR_DUPLICATE")
    _one(backend, ROOT_LOCATION, "PANEL_ROOT_ROUTE_MISSING_OR_DUPLICATE")
    if (INCLUDE.strip() in backend or b"smite-xhttp-routes/" in backend
            or b"smite-xhttp-bridge.conf" in backend):
        raise BridgeHold("MANAGED_BRIDGE_ALREADY_REFERENCED")
    if not legacy.startswith(b"# Managed by U-OPTI - Standard FRP XHTTP\n"):
        raise BridgeHold("UNAPPROVED_LEGACY_XHTTP_FILE")

    if not stream.startswith(b"# Managed by U-OPTI - Smite TCP/443 SNI gateway\n"):
        raise BridgeHold("UNAPPROVED_STREAM_GATEWAY")
    _one(stream, b"listen 443;", "PUBLIC_443_STREAM_MISSING_OR_DUPLICATE")
    _one(stream, b"ssl_preread on;", "STREAM_TLS_SNI_MISSING_OR_DUPLICATE")
    _one(stream, b"proxy_pass $uopti_frp_canary_backend;",
         "STREAM_BACKEND_MISSING_OR_DUPLICATE")
    _one(stream, b"include /etc/nginx/u-opti-smite-stream-map.conf;",
         "STREAM_MAP_INCLUDE_UNAPPROVED")

    map_lines = [ln.strip() for ln in sni_map.splitlines()
                 if ln.strip() and not ln.lstrip().startswith(b"#")]
    exact = f"{domain}    127.0.0.1:8443;".encode()
    if map_lines.count(exact) != 1:
        raise BridgeHold("SNI_DOMAIN_TO_LOOPBACK_8443_NOT_UNIQUE")
    # Do not let the same domain appear anywhere else in SNI routes.
    if sum(1 for line in map_lines if line.split()[:1] == [domain.encode()]) != 1:
        raise BridgeHold("SNI_MAP_DOMAIN_CONFLICT")

    # Place only in the sole vetted HTTP backend, never inside Stream.
    # Original U-OPTI legacy include and every active location are unmodified.
    candidate = backend.replace(ROOT_LOCATION, INCLUDE + b"\n" + ROOT_LOCATION, 1)
    if candidate.count(INCLUDE) != 1:
        raise BridgeHold("CANDIDATE_NOT_UNIQUE")
    if candidate.replace(INCLUDE + b"\n", b"", 1) != backend:
        raise BridgeHold("UNRELATED_BACKEND_MUTATION")
    return BridgePlan(backend, candidate, domain, str(BACKEND), 1)


def _read_root_file(path: Path) -> bytes:
    try:
        meta = path.lstat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0
                or meta.st_nlink != 1 or bool(meta.st_mode & 0o022)
                or not 0 < meta.st_size <= MAX_BYTES):
            raise BridgeHold("UNTRUSTED_UOPTI_FILE")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            open_meta = os.fstat(fd)
            if (open_meta.st_ino, open_meta.st_dev) != (meta.st_ino, meta.st_dev):
                raise BridgeHold("UOPTI_FILE_CHANGED")
            data = os.read(fd, MAX_BYTES + 1)
        finally:
            os.close(fd)
        if len(data) > MAX_BYTES:
            raise BridgeHold("UOPTI_FILE_TOO_LARGE")
        return data
    except OSError as exc:
        raise BridgeHold("UOPTI_FILE_UNAVAILABLE") from exc


def _state_domain(state: bytes) -> str:
    found = []
    for line in state.decode("utf-8").splitlines():
        if line.startswith("SMITE_PANEL_DOMAIN="):
            found.append(line.partition("=")[2].strip())
    if len(found) != 1:
        raise BridgeHold("STATE_DOMAIN_UNAVAILABLE")
    return found[0]


def _run(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BridgeHold("READ_ONLY_CHECK_UNAVAILABLE") from exc
    return p.returncode, p.stdout


def _timer_is_unsafe() -> bool:
    # Either running or enabled is a competing whole-file publisher.
    for cmd in ("is-active", "is-enabled"):
        code, value = _run(["/usr/bin/systemctl", cmd,
                            "u-opti-smite-frp-xhttp.timer"])
        if code == 0 or value.strip() in ("active", "enabled", "enabled-runtime",
                                           "activating"):
            return True
        if value.strip() not in ("inactive", "disabled", "masked", "static",
                                  "unknown", "not-found", "failed", ""):
            raise BridgeHold("TIMER_STATE_UNKNOWN")
    return False


def audit_read_only() -> BridgePlan:
    if os.geteuid() != 0 or os.uname().nodename.split(".")[0].lower() != "ir":
        raise BridgeHold("IR_ROOT_ONLY")
    for p in (BRIDGE, ROUTE_DIR):
        # Never inherit an existing unmanaged bridge or route directory.
        if p.exists() or p.is_symlink():
            raise BridgeHold("BRIDGE_ALREADY_PRESENT")
    source = {p: _read_root_file(p) for p in (BACKEND, STREAM, SNI_MAP, LEGACY, STATE)}
    domain = _state_domain(source[STATE])
    if _run([NGINX, "-t"])[0] != 0:
        raise BridgeHold("NGINX_SYNTAX_INVALID")
    code, config = _run([NGINX, "-T"])
    if code != 0:
        raise BridgeHold("NGINX_EFFECTIVE_CONFIG_UNAVAILABLE")
    for path in (BACKEND, STREAM, SNI_MAP, LEGACY):
        if config.count(f"# configuration file {path}:") != 1:
            raise BridgeHold("NGINX_SOURCE_NOT_ACTIVE")
    return propose_bridge(
        backend=source[BACKEND], stream=source[STREAM],
        sni_map=source[SNI_MAP], legacy=source[LEGACY], domain=domain,
        timer_enabled=_timer_is_unsafe(), bridge_exists=False,
        directory_exists=False,
    )


def main() -> int:
    try:
        if sys.argv[1:] != ["--check"]:
            raise BridgeHold("CHECK_ONLY_NO_APPLY")
        result = audit_read_only()
        print("IR_443_STREAM_TO_8443=VERIFIED")
        print("UOPTI_OLD_XHTTP_INCLUDE=UNCHANGED")
        print("CANDIDATE_BACKEND_ADDITIONS=" + str(result.change_count))
        print("SMITE_BRIDGE=NOT_CREATED")
        print("NGINX_RELOAD=NO")
        print("LIVE_CHANGES=NONE")
        print("RESULT=PASS_READ_ONLY")
        return 0
    except (BridgeHold, UnicodeError, ValueError):
        print("RESULT=HOLD_READ_ONLY")
        print("LIVE_CHANGES=NONE")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
