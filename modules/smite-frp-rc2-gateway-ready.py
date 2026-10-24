#!/usr/bin/env python3
"""Fail-closed RC2 signed IR Smite FRP/WSS gateway readiness (read-only).

This replaces the *obsolete* /opt/u-opti-smite/node/frp_gateway_config.py
existence check ONLY for the explicitly activated RC2 signed Node WSS trial.
It never creates compatibility stubs, mutates Nginx, tests the live tunnel,
consumes replay nonces, or prints protected configuration values.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

NODE_IMAGE = ("ghcr.io/aghajani82/smite-node@sha256:"
              "9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec")
NODE_FILES = {
    "/opt/smite-node/docker-compose.yml",
    "/opt/smite-node/docker-compose.security-candidate.yml",
    "/opt/smite-node/docker-compose.frp-wss-rc2.yml",
}
WSS_OVERLAY = (b"services:\n  smite-node:\n    environment:\n"
               b"      - SMITE_FRP_STANDARD_WSS=1\n")
ORIGIN = "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
DEDICATED = "/etc/nginx/conf.d/u-opti-smite-panel-kh-wss.conf"
SNIPPET = "/etc/nginx/u-opti-smite-frp-xhttp.conf"
STATE = "/etc/u-opti/smite/state.env"
JOURNAL = "/var/lib/u-opti/smite-rc2-frp-wss-node/ir/record.json"
OVERLAY = "/opt/smite-node/docker-compose.frp-wss-rc2.yml"


class GateHold(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise GateHold(code)


def read_root_file(path: Path, *, max_bytes: int, mode: int | None = None) -> bytes:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and info.st_nlink == 1 and not (info.st_mode & 0o022)
            and info.st_size <= max_bytes, "UNTRUSTED_FILE")
    if mode is not None:
        require(stat.S_IMODE(info.st_mode) == mode, "UNTRUSTED_FILE_MODE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        meta = os.fstat(fd)
        require((meta.st_dev, meta.st_ino) == (info.st_dev, info.st_ino),
                "FILE_CHANGED")
        with os.fdopen(fd, "rb") as fp:
            data = fp.read(max_bytes + 1)
            fd = -1
    finally:
        if fd != -1:
            os.close(fd)
    require(len(data) <= max_bytes, "FILE_TOO_LARGE")
    return data


def read_root_dir(path: Path, *, private: bool = False) -> None:
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
            and not (info.st_mode & 0o022), "UNTRUSTED_DIRECTORY")
    if private:
        require(stat.S_IMODE(info.st_mode) == 0o700, "UNTRUSTED_PRIVATE_DIRECTORY")


def get_node() -> dict:
    try:
        p = subprocess.run(
            ["docker", "inspect", "smite-node"],
            capture_output=True, text=True, timeout=15,
            check=True
        )
        value = json.loads(p.stdout)
        require(isinstance(value, list) and len(value) == 1,
                "NODE_INSPECT_INVALID")
        return value[0]
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise GateHold("NODE_INSPECT_UNAVAILABLE") from exc


def panel_root_proxy_targets(backend: str) -> list[str]:
    """Return proxy_pass targets only from the managed Panel location /.

    Additional custom locations may legitimately proxy to the same Panel.
    Those are not evidence of drift in the Panel root upstream.
    """
    anchor = "    location / {\n"
    require(backend.count(anchor) == 1, "IR_PANEL_ROOT_LOCATION_DRIFT")
    tail = backend.split(anchor, 1)[1]
    end = re.search(r"(?m)^    }[ \t]*(?:\n|$)", tail)
    require(end is not None, "IR_PANEL_ROOT_LOCATION_UNCLOSED")
    root = tail[:end.start()]
    require("{" not in root and "}" not in root,
            "IR_PANEL_ROOT_UNEXPECTED_NESTED_LAYOUT")
    return re.findall(r"(?m)^[ \t]*proxy_pass[ \t]+([^;\n]+);[ \t]*$", root)


def audit(paths: dict[str, Path] | None = None, runtime: dict | None = None,
          *, enforce_host: bool = True, allow_missing_snippet: bool = False,
          nginx_config: str | None = None) -> None:
    if enforce_host:
        require(os.geteuid() == 0
                and os.uname().nodename.split(".")[0].lower() == "ir",
                "IR_ROOT_ONLY")
    p = paths or {
        "state": Path(STATE), "backend": Path(ORIGIN),
        "dedicated": Path(DEDICATED), "snippet": Path(SNIPPET),
        "journal": Path(JOURNAL),
        "overlay": Path(OVERLAY),
        "state_root": Path(JOURNAL).parent.parent,
        "journal_dir": Path(JOURNAL).parent,
    }

    mode = read_root_file(p["state"], max_bytes=16384).decode("utf-8").splitlines()
    require(mode.count("SMITE_CONNECTION_MODE=standard") == 1,
            "STANDARD_FRP_STATE_MISSING")

    read_root_dir(p["state_root"], private=True)
    read_root_dir(p["journal_dir"], private=True)
    raw = read_root_file(p["journal"], max_bytes=16384, mode=0o600)
    journal = json.loads(raw)
    require(isinstance(journal, dict)
            and journal.get("host") == "ir"
            and journal.get("schema") == 1
            and journal.get("state") == "COMMITTED"
            and journal.get("image") == NODE_IMAGE
            and journal.get("overlay_sha") == hashlib.sha256(WSS_OVERLAY).hexdigest(),
            "RC2_WSS_NOT_COMMITTED")
    require(read_root_file(p["overlay"], max_bytes=8192, mode=0o600)
            == WSS_OVERLAY, "RC2_WSS_OVERLAY_MISMATCH")

    node = runtime if runtime is not None else get_node()
    require(node.get("Config", {}).get("Image") == NODE_IMAGE,
            "NODE_IMAGE_DRIFT")
    require(node.get("State", {}).get("Running") is True
            and node["State"].get("Health", {}).get("Status") == "healthy",
            "NODE_NOT_HEALTHY")
    env_raw = node["Config"].get("Env", [])
    require(isinstance(env_raw, list), "NODE_ENV_INVALID")
    env = dict(x.split("=", 1) for x in env_raw if isinstance(x, str) and "=" in x)
    require(all(env.get(key) == value for key, value in {
        "SMITE_FRP_STANDARD_WSS": "1",
        "SMITE_NODE_PANEL_AUTH_MODE": "signed",
        "SMITE_AGENT_AUTH_MODE": "strict",
        "SMITE_ENGINE_INVENTORY_MODE": "managed",
        "PANEL_ADDRESS": "ir.kolbe1.ir:443",
    }.items()), "SIGNED_WSS_NODE_DRIFT")
    labels = node["Config"].get("Labels") or {}
    named = labels.get("com.docker.compose.project.config_files", "")
    require(set(x.strip() for x in named.split(",") if x.strip()) == NODE_FILES,
            "NODE_SIGNED_COMPOSE_DRIFT")
    require(labels.get("com.docker.compose.service") == "smite-node",
            "NODE_COMPOSE_SERVICE_DRIFT")
    mounts = {m.get("Destination"): m for m in node.get("Mounts", [])}
    require({
        "/etc/smite-node", "/run/smite-node-identity",
        "/var/lib/smite-node/auth",
    }.issubset(mounts), "NODE_SIGNED_MOUNTS_MISSING")
    require(mounts["/etc/smite-node"].get("Source") == "/opt/smite-node/config"
            and mounts["/etc/smite-node"].get("RW") is True
            and mounts["/run/smite-node-identity"].get("RW") is False
            and mounts["/var/lib/smite-node/auth"].get("RW") is True,
            "NODE_SIGNED_MOUNTS_DRIFT")

    backend = read_root_file(p["backend"], max_bytes=131072).decode("utf-8")
    dedicated = read_root_file(p["dedicated"], max_bytes=131072).decode("utf-8")
    # In RC2 these are TWO distinct TLS servers. The signed KH-WSS vhost
    # is isolated on 8444; the 8443 panel server must not duplicate /~!frp.
    require(backend.startswith("# Managed by U-OPTI - Smite Panel TLS backend\n")
            and backend.count("server_name ir.kolbe1.ir;") == 1
            and len(re.findall(r"(?m)^\s*listen\s+127\.0\.0\.1:8443\s+ssl\s*;",
                               backend)) == 1
            and not re.search(r"(?m)^\s*location\s+(?:=\s*)?/~!frp\s*\{",
                               backend),
            "IR_PANEL_8443_BACKEND_DRIFT")
    require(panel_root_proxy_targets(backend) == ["http://127.0.0.1:8000"],
            "IR_PANEL_ROOT_PROXY_DRIFT")

    xhttp_include = "    include /etc/nginx/u-opti-smite-frp-xhttp.conf;\n"
    if allow_missing_snippet:
        require(backend.count(xhttp_include) == 0
                and "u-opti-smite-frp-xhttp.conf;" not in backend,
                "XHTTP_BACKEND_NOT_PRISTINE")
    else:
        require(backend.count(xhttp_include) == 1,
                "IR_XHTTP_INCLUDE_MISSING_OR_DUPLICATED")

    # Dedicated KH-WSS is already carrying the IR hostname for allowlisted
    # KH-source clients; never attempt to insert this route into 8443.
    require(len(re.findall(r"(?m)^\s*server\s*\{", dedicated)) == 1
            and len(re.findall(r"(?m)^\s*listen\s+127\.0\.0\.1:8444\s+ssl\s*;",
                               dedicated)) == 1
            and len(re.findall(r"(?m)^\s*server_name\s+ir\.kolbe1\.ir\s*;",
                               dedicated)) == 1
            and len(re.findall(r"(?m)^\s*location\s+=\s+/~!frp\s*\{",
                               dedicated)) == 1
            and len(re.findall(r"(?m)^\s*proxy_pass\s+http://127\.0\.0\.1:7000\s*;",
                               dedicated)) == 1
            and re.search(r"(?m)^\s*proxy_http_version\s+1\.1\s*;",
                          dedicated)
            and re.search(r"(?mi)^\s*proxy_set_header\s+Upgrade\s+\$http_upgrade\s*;",
                          dedicated)
            and re.search(r'(?mi)^\s*proxy_set_header\s+Connection\s+(?:"upgrade"|\$connection_upgrade)\s*;',
                          dedicated),
            "IR_KH_WSS_8444_DRIFT")

    # Verify Nginx's LIVE loaded topology without printing addresses,
    # certificates, or environment values. A 502 WS probe alone does not
    # establish the exact SNI/source allowlist route.
    if nginx_config is None:
        result = subprocess.run(["nginx", "-T"], capture_output=True,
                                text=True, timeout=30, check=True)
        nginx_config = result.stdout
    require(len(nginx_config) < 4 * 1024 * 1024,
            "NGINX_TOPOLOGY_TOO_LARGE")
    wss_matches = re.findall(
        r"(?m)^\s*location\s+=\s+/~!frp\s*\{", nginx_config)
    require(len(wss_matches) == 1
            and "127.0.0.1:8443;" in nginx_config
            and 'map "$ssl_preread_server_name|$remote_addr" $uopti_frp_canary_backend {'
            in nginx_config
            and re.search(r"(?m)^\s*default\s+\$uopti_smite_backend\s*;",
                          nginx_config)
            and re.search(r"(?m)^\s*proxy_pass\s+\$uopti_frp_canary_backend\s*;",
                          nginx_config),
            "IR_NGINX_STREAM_LAYOUT_DRIFT")
    rows = re.findall(
        r'(?m)^\s*"ir\.kolbe1\.ir\|((?:\d{1,3}\.){3}\d{1,3})"\s+127\.0\.0\.1:8444\s*;',
        nginx_config)
    require(len(rows) == 1, "KH_SOURCE_ALLOWLIST_MAPPING_DRIFT")
    import ipaddress
    require(isinstance(ipaddress.IPv4Address(rows[0]), ipaddress.IPv4Address),
            "INVALID_KH_SOURCE_IP")

    # An absent managed snippet is supported ONLY by the explicit, no-write
    # bootstrap lane. Regular runtime and route sync must refuse absence.
    snippet_path = p["snippet"]
    if (allow_missing_snippet and not snippet_path.exists()
            and not snippet_path.is_symlink()):
        read_root_dir(snippet_path.parent)
    else:
        snippet = read_root_file(snippet_path, max_bytes=131072).decode("utf-8")
        require(snippet.startswith("# Managed by U-OPTI - Standard FRP XHTTP\n"),
                "IR_XHTTP_SNIPPET_UNTRUSTED")


def main() -> int:
    try:
        import argparse
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--bootstrap-preflight", action="store_true",
                            help="Check trusted RC2 state before creation of the missing Nginx snippet")
        args = parser.parse_args()
        audit(allow_missing_snippet=args.bootstrap_preflight)
        if args.bootstrap_preflight:
            print("RC2_IR_FRP_XHTTP_BOOTSTRAP=PASS_READ_ONLY")
        else:
            print("RC2_IR_FRP_XHTTP_GATE=PASS_READ_ONLY")
        print("SIGNED_WSS_NODE=VERIFIED")
        print("STANDARD_FRP_GATEWAY=VERIFIED")
        print("NGINX_FRP_INCLUDE=VERIFIED")
        print("LIVE_CHANGES=NONE")
        return 0
    except (GateHold, OSError, KeyError, TypeError,
            UnicodeError, json.JSONDecodeError) as exc:
        reason = str(exc)
        if not reason.isupper() or not reason.replace("_", "").isalnum():
            reason = "UNTRUSTED_RC2_GATE_STATE"
        print("HOLD: " + reason, file=sys.stderr)
        print("RC2_IR_FRP_XHTTP_GATE=HOLD")
        print("LIVE_CHANGES=NONE")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
