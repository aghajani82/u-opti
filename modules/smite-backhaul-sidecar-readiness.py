#!/usr/bin/env python3
"""Fail-closed, READ-ONLY Backhaul Sidecar host readiness check.

This is NOT a live installer, an end-to-end connectivity test, or proof
that Nginx can be safely changed. Never emits secrets or raw configs.
Synthetic tests mock every host operation; CI never contacts IR/KH.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import re
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
IMAGE = ("ghcr.io/zzedix/smite-node@sha256:"
         "967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e")
CONTAINERS = {"ir": "uopti-backhaul-sidecar-ir",
              "kh": "uopti-backhaul-sidecar-kh"}
IR_PANEL = Path("/etc/nginx/conf.d/u-opti-smite-panel-backend.conf")
IR_CONTROL = Path("/etc/nginx/u-opti-backhaul-sidecar-control.inc")
IR_XHTTP = Path("/etc/nginx/u-opti-backhaul-sidecar-xhttp.inc")
KH_BRIDGE = Path("/etc/nginx/conf.d/u-opti-backhaul-sidecar-bridge.conf")
KH_VHOST = Path("/etc/nginx/sites-available/3xui-kh.kolbe1.ir")
CONFIG_DIR = Path("/etc/u-opti/backhaul-sidecar")


def run_readonly(argv: tuple[str, ...]) -> str | None:
    if argv not in (
        ("ss", "-H", "-lntp"),
        ("nginx", "-t"),
    ) and not (
        len(argv) == 5
        and argv[:4] == ("docker", "inspect", "-f",
                        "{{.State.Running}}|{{.HostConfig.RestartPolicy.Name}}|"
                        "{{.HostConfig.NetworkMode}}|{{.Config.Image}}")
        and argv[4] in CONTAINERS.values()
    ):
        raise ValueError("Command not on read-only allowlist")
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                check=True, timeout=8)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    if len(result.stdout) > 200_000:
        return None
    return result.stdout.strip()


def parse_listeners(raw: str, requested_ports: set[int] | None = None
                    ) -> dict[int, list[tuple[str, str]]]:
    ports: dict[int, list[tuple[str, str]]] = {}
    wanted = {443, 7000, 8443, 3080, 13080}
    if requested_ports is None:
        wanted.add(56053)  # backward-compatible direct audit utility
    else:
        wanted.update(requested_ports)
    for line in raw.splitlines():
        parts = line.split(maxsplit=6)
        if len(parts) < 5 or parts[0] != "LISTEN":
            raise ValueError("Unexpected ss output")
        local = parts[3]
        host, sep, port = local.rpartition(":")
        if not sep or not port.isdecimal():
            raise ValueError("Unexpected listening address")
        n = int(port)
        if n not in wanted:
            continue
        names = set(re.findall(r'\("([a-zA-Z0-9_.-]{1,80})",pid=', line))
        if len(names) != 1:
            raise ValueError("Missing or ambiguous listener owner")
        owner = names.pop()
        ports.setdefault(n, []).append((host, owner))
    return ports


def is_expected(ports: dict, port: int, address: str, owner: str) -> bool:
    found = ports.get(port, ())
    if not found:
        return False
    if address == "public":
        check_addr = lambda addr: addr in ("0.0.0.0", "*", "[::]", "::")
    else:
        check_addr = lambda addr: addr == "127.0.0.1"
    if owner == "xray":
        check_owner = lambda x: x == "xray" or x.startswith("xray-")
    else:
        check_owner = lambda x: x == owner
    # One unexpected bind is a conflict, even when a good bind also exists.
    return all(check_addr(addr) and check_owner(who) for addr, who in found)


def read_small(path: Path) -> str | None:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 100_000:
            return None
        # Internal comparison only; never print or return file contents.
        return path.read_text("utf-8")
    except (OSError, UnicodeError):
        return None


def private_files(role: str) -> bool:
    path = CONFIG_DIR / f"{role}.toml"
    secret = CONFIG_DIR / "shared.token"
    try:
        directory = CONFIG_DIR.lstat()
        if not stat.S_ISDIR(directory.st_mode) or (
                stat.S_IMODE(directory.st_mode) & 0o077):
            return False
        for file in (path, secret):
            info = file.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or (
                    stat.S_IMODE(info.st_mode) & 0o077):
                return False
        return True
    except OSError:
        return False


def nginx_routes(role: str, data_port: int = 56053,
                 xhttp_path: str = "/56053/www") -> bool:
    if role == "ir":
        panel = read_small(IR_PANEL) or ""
        control = read_small(IR_CONTROL) or ""
        data = read_small(IR_XHTTP) or ""
        return (
            "include /etc/nginx/u-opti-backhaul-sidecar-control.inc;" in panel
            and "include /etc/nginx/u-opti-backhaul-sidecar-xhttp.inc;" in panel
            and "location = /channel {" in control
            and "location ^~ /tunnel/ {" in control
            and "proxy_pass http://127.0.0.1:3080;" in control
            and f"location ^~ {xhttp_path}/ {{" in data
            and f"proxy_pass http://127.0.0.1:{data_port};" in data
        )
    bridge = read_small(KH_BRIDGE) or ""
    vhost = read_small(KH_VHOST) or ""
    guard = "location ~ ^/0*13080(/|$)"
    forward = "location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$"
    return (
        "listen 127.0.0.1:13080;" in bridge
        and "location = /channel {" in bridge
        and "location ^~ /tunnel/ {" in bridge
        and "proxy_ssl_verify on;" in bridge
        and "proxy_ssl_server_name on;" in bridge
        and "proxy_pass https://" in bridge
        and guard in vhost and forward in vhost
        and vhost.index(guard) < vhost.index(forward)
    )


def profile_from_text(raw: str) -> tuple[int, str] | None:
    """Extract only non-secret validated profile metadata from a TOML proposal."""
    ports = re.findall(r"(?m)^# UOPTI_PROFILE_DATA_PORT=([^\n]+)$", raw)
    paths = re.findall(r"(?m)^# UOPTI_PROFILE_XHTTP_PATH=([^\n]+)$", raw)
    if not ports and not paths:
        return 56053, "/56053/www"
    if len(ports) != 1 or len(paths) != 1 or not ports[0].isdecimal():
        return None
    spec = importlib.util.spec_from_file_location(
        "readiness_profile", Path(__file__).with_name("smite-backhaul-sidecar.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod.validated_profile(int(ports[0]), paths[0])
    except (ValueError, TypeError):
        return None


def installed_profile(role: str) -> tuple[int, str] | None:
    """Discover installed port/path without revealing the TOML token."""
    raw = read_small(CONFIG_DIR / f"{role}.toml")
    return profile_from_text(raw) if raw is not None else None


def sidecar_files_present(role: str) -> bool:
    paths = ((CONFIG_DIR / "ir.toml", IR_CONTROL, IR_XHTTP)
             if role == "ir"
             else (CONFIG_DIR / "kh.toml", KH_BRIDGE))
    return any(p.exists() or p.is_symlink() for p in paths)


def docker_state(role: str) -> tuple[bool, bool]:
    name = CONTAINERS[role]
    out = run_readonly(("docker", "inspect", "-f",
                        "{{.State.Running}}|{{.HostConfig.RestartPolicy.Name}}|"
                        "{{.HostConfig.NetworkMode}}|{{.Config.Image}}", name))
    if out is None:
        return False, False
    fields = out.split("|")
    if len(fields) != 4:
        return True, False
    return True, fields == ["true", "unless-stopped", "host", IMAGE]


def evaluate(role: str, mode: str, *, ports: dict[int, list[tuple[str, str]]],
             nginx_ok: bool, container_exists: bool, container_ok: bool,
             private_ok: bool, routes_ok: bool, owned_files: bool,
             data_port: int = 56053, check_target: bool = True) -> list[str]:
    failures: list[str] = []
    if not nginx_ok:
        failures.append("Existing Nginx configuration does not validate")
    if role == "ir":
        baseline = [(443, "public", "nginx"), (8443, "127.0.0.1", "nginx"),
                    (7000, "127.0.0.1", "frps")]
    else:
        baseline = [(443, "public", "nginx")]
        if check_target:
            baseline.append((data_port, "127.0.0.1", "xray"))
    for port, addr, owner in baseline:
        if not is_expected(ports, port, addr, owner):
            failures.append(f"Expected {owner} listener on {addr}:{port} not verified")
    if mode == "existing":
        if not container_exists or not container_ok:
            failures.append("Pinned host-network Sidecar auto-start not verified")
        if not private_ok:
            failures.append("Private Sidecar files/ownership not verified")
        if not routes_ok:
            failures.append("Exact Nginx Sidecar routes/bridge guard not verified")
        if role == "ir":
            expected = [(3080, "backhaul"), (data_port, "backhaul")]
        else:
            expected = [(13080, "nginx")]
        for port, owner in expected:
            if not is_expected(ports, port, "127.0.0.1", owner):
                failures.append(f"Expected isolated {owner} listener on 127.0.0.1:{port} absent")
    elif mode == "new":
        if container_exists or owned_files:
            failures.append("Existing/partial Sidecar detected; fresh install REFUSED")
        if role == "ir":
            # Pairing (before choosing a data port) only checks the fixed WS
            # control listener. Install admission later checks the selected port.
            reserved = (3080, data_port) if check_target else (3080,)
        else:
            reserved = (13080,)
        for port in reserved:
            if port in ports:
                failures.append(f"Required Sidecar port {port} already occupied")
    else:
        raise ValueError("Unsupported mode")
    return failures


def inspect_local(role: str, mode: str, data_port: int = 56053,
                  xhttp_path: str | None = None,
                  *, check_target: bool = True) -> list[str]:
    if role not in CONTAINERS:
        raise ValueError("Unsupported role")
    if mode == "existing":
        profile = installed_profile(role)
        if profile is None:
            return ["Installed Sidecar profile missing or invalid"]
        data_port, xhttp_path = profile
    if xhttp_path is None:
        xhttp_path = f"/{data_port}/www"
    raw = run_readonly(("ss", "-H", "-lntp"))
    if raw is None:
        return ["Listener ownership unavailable; refuse inference"]
    try:
        ports = parse_listeners(raw, {data_port} if check_target else set())
    except ValueError:
        return ["Listener ownership ambiguous; refuse inference"]
    exists, correct = docker_state(role)
    return evaluate(
        role, mode, ports=ports,
        nginx_ok=run_readonly(("nginx", "-t")) is not None,
        container_exists=exists, container_ok=correct,
        private_ok=private_files(role),
        routes_ok=nginx_routes(role, data_port, xhttp_path),
        owned_files=sidecar_files_present(role),
        data_port=data_port, check_target=check_target,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("ir", "kh"))
    parser.add_argument("--mode", choices=("existing", "new"))
    parser.add_argument("--data-port", type=int, default=56053)
    parser.add_argument("--xhttp-path", default=None)
    parser.add_argument("--print-profile", action="store_true",
                        help="Print only non-secret installed Xray port and XHTTP path")
    args = parser.parse_args()
    if args.print_profile:
        if args.mode is not None or not private_files(args.role):
            print("HOLD: Private installed Sidecar profile not verified")
            return 2
        installed = installed_profile(args.role)
        if installed is None:
            print("HOLD: Installed Sidecar port/path missing or invalid")
            return 2
        print(f"{installed[0]} {installed[1]}")
        return 0
    if args.mode is None:
        parser.error("--mode new|existing is required for an audit")
    failures = inspect_local(args.role, args.mode, args.data_port, args.xhttp_path)
    print(f"BACKHAUL READ-ONLY AUDIT | role={args.role} | check={args.mode}")
    if failures:
        for reason in failures:
            print(f"HOLD: {reason}")
        print("NO INSTALLATION OR SERVICE CHANGE. Manual review required.")
        return 2
    if args.mode == "existing":
        print("EXISTING_SIDECAR_LOCAL_CHECKS_PASSED")
        print("Not proof of external reachability, authenticated WSS, VLESS or backup.")
    else:
        print("FRESH_HOST_LOCAL_PRECHECK_PASSED")
        print("NOT deployment approval: TLS, SNI, backups, public routing and rollback")
        print("must be checked separately before any future installation.")
    print("NO FILES WRITTEN; NO SERVICES MODIFIED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
