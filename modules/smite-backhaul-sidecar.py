#!/usr/bin/env python3
"""Offline-only independent Backhaul v0.7.2 sidecar candidate generator.

Creates private files under a fresh directory in /tmp. Never installs, starts,
stops, reloads, replaces or updates a running Smite/FRP/Nginx/Xray service.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

IMAGE = (
    "ghcr.io/zzedix/smite-node@sha256:"
    "967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
)
RENDERER = Path(__file__).with_name("smite-backhaul-standard.sh")
DOMAINS = re.compile(
    r"(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{24,128}\Z")


class UnsafeCandidate(ValueError):
    pass


def read_private_token(filename: Path) -> str:
    """Read an existing 0600 token file; never accept secrets on the CLI."""
    info = filename.lstat()
    if not stat.S_ISREG(info.st_mode) or (stat.S_IMODE(info.st_mode) & 0o077):
        raise UnsafeCandidate("Token must be a regular, private file (mode 0600)")
    token = filename.read_text(encoding="ascii")
    if token.endswith("\n"):
        token = token[:-1]
    if not TOKEN_PATTERN.fullmatch(token):
        raise UnsafeCandidate("Token must have 24-128 ASCII characters [A-Za-z0-9_-]")
    return token


def validated_domain(domain: str) -> str:
    if not DOMAINS.fullmatch(domain):
        raise UnsafeCandidate("Invalid DNS name")
    return domain


def validated_profile(data_port: int, xhttp_path: str | None) -> tuple[int, str]:
    if (not isinstance(data_port, int) or isinstance(data_port, bool)
            or not 1024 <= data_port <= 65535
            or data_port in (443, 3080, 7000, 8000, 8443, 8888, 13080, 18476)):
        raise UnsafeCandidate("Invalid or reserved Backhaul data port")
    path = xhttp_path if xhttp_path is not None else f"/{data_port}/www"
    if (not isinstance(path, str) or not 2 <= len(path) <= 128
            or not re.fullmatch(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", path)
            or path == "/channel" or path.startswith("/channel/")
            or path == "/tunnel" or path.startswith("/tunnel/")
            or path == "/~!frp" or path.startswith("/~!frp/")
            or re.match(r"/0*[0-9]+/web(?:/|$)", path)):
        raise UnsafeCandidate("Invalid or reserved XHTTP path")
    return data_port, path


def backhaul_toml(role: str, token: str, data_port: int = 56053,
                  xhttp_path: str | None = None) -> str:
    data_port, xhttp_path = validated_profile(data_port, xhttp_path)
    # Both IR and KH retain the selected profile privately for local audit.
    # Legacy defaults preserve previous exact TOML bytes for compatibility.
    annotation = ("" if data_port == 56053 and xhttp_path == "/56053/www" else
                  f"# UOPTI_PROFILE_DATA_PORT={data_port}\n"
                  f"# UOPTI_PROFILE_XHTTP_PATH={xhttp_path}\n")
    if role == "ir":
        return (
            annotation
            + '[server]\n'
            'bind_addr = "127.0.0.1:3080"\n'
            'transport = "ws"\n'
            f'token = "{token}"\n'
            f'ports = ["127.0.0.1:{data_port}=127.0.0.1:{data_port}"]\n'
            'channel_size = 2048\n'
            'keepalive_period = 75\n'
            'heartbeat = 40\n'
            'nodelay = true\n'
            'sniffer = false\n'
            'skip_optz = true\n'
            'web_port = 0\n'
            'log_level = "info"\n'
        )
    if role == "kh":
        return (
            annotation
            + '[client]\n'
            'remote_addr = "127.0.0.1:13080"\n'
            'transport = "ws"\n'
            f'token = "{token}"\n'
            'connection_pool = 4\n'
            'retry_interval = 3\n'
            'dial_timeout = 10\n'
            'keepalive_period = 75\n'
            'nodelay = true\n'
            'sniffer = false\n'
            'skip_optz = true\n'
            'web_port = 0\n'
            'log_level = "info"\n'
        )
    raise UnsafeCandidate("Unsupported Sidecar role")


def compose_candidate(role: str) -> str:
    if role not in ("ir", "kh"):
        raise UnsafeCandidate("Unsupported Sidecar role")
    # Host networking is intentionally shared with the host, so ownership of
    # every local port MUST be checked before any separately approved activation.
    return (
        "# CANDIDATE ONLY. Do not run this Compose file on a production host.\n"
        "# The external token-bearing config mount is not installed by this generator.\n"
        "services:\n"
        f"  backhaul-{role}:\n"
        f"    image: {IMAGE}\n"
        f"    container_name: uopti-backhaul-sidecar-{role}\n"
        "    network_mode: host\n"
        '    restart: "no"\n'
        "    entrypoint: [/usr/local/bin/backhaul, -c, /run/backhaul/config.toml]\n"
        "    read_only: true\n"
        "    cap_drop: [ALL]\n"
        "    security_opt: [no-new-privileges:true]\n"
        "    volumes:\n"
        "      - type: bind\n"
        f"        source: /etc/u-opti/backhaul-sidecar/{role}.toml\n"
        "        target: /run/backhaul/config.toml\n"
        "        read_only: true\n"
        "        bind:\n"
        "          create_host_path: false\n"
    )


def nginx_candidate(*args: str) -> str:
    result = subprocess.run(
        ["bash", str(RENDERER), *args],
        text=True, capture_output=True, check=True,
    )
    return result.stdout


def candidate_files(role: str, token: str, domain: str, kh_host: str,
                    data_port: int = 56053,
                    xhttp_path: str | None = None) -> dict[str, str]:
    validated_domain(domain)
    validated_domain(kh_host)
    data_port, xhttp_path = validated_profile(data_port, xhttp_path)
    files = {
        f"{role}.toml": backhaul_toml(role, token, data_port, xhttp_path),
        "compose.candidate.yaml": compose_candidate(role),
    }
    if role == "ir":
        files["ir-control.inc"] = nginx_candidate("--render-ir-control", "3080")
        files["ir-xhttp.inc"] = nginx_candidate(
            "--render-ir-xhttp", str(data_port), xhttp_path, kh_host
        )
    elif role == "kh":
        files["kh-bridge.conf"] = nginx_candidate(
            "--render-kh-bridge", domain, "13080"
        )
    else:
        raise UnsafeCandidate("Unsupported Sidecar role")
    files["NOT-INSTALLED.txt"] = (
        "OFFLINE CANDIDATE ONLY. NOT INSTALLED OR STARTED.\n"
        "Never run compose directly from this staging folder.\n"
        "Before an explicitly authorized deployment: check all listener owners,\n"
        "pin/verify the Backhaul binary v0.7.2, review Nginx 443/8443 routing,\n"
        "provision the private config, test nginx -t and prepare live rollback.\n"
        "Existing Smite-managed Backhaul clients and production FRP stay untouched.\n"
    )
    return files


def prepare(role: str, token_file: Path, domain: str, kh_host: str,
            data_port: int = 56053, xhttp_path: str | None = None) -> Path:
    token = read_private_token(token_file)
    files = candidate_files(role, token, domain, kh_host,
                            data_port=data_port, xhttp_path=xhttp_path)
    stage = Path(tempfile.mkdtemp(prefix="uopti-backhaul-sidecar-"))
    try:
        os.chmod(stage, 0o700)
        for filename, contents in files.items():
            destination = stage / filename
            # Exclusive creation; no symlink or existing file can be overwritten.
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(contents)
            os.chmod(destination, 0o600)
    except Exception:
        shutil.rmtree(stage)
        raise
    return stage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("ir", "kh"))
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--ir-domain", default="ir.kolbe1.ir")
    parser.add_argument("--kh-host", default="kh.kolbe1.ir")
    parser.add_argument("--data-port", type=int, default=56053)
    parser.add_argument("--xhttp-path", default=None,
                        help="Optional URI e.g. /assets/v1/connect (without trailing slash)")
    args = parser.parse_args()
    try:
        stage = prepare(
            args.role, args.token_file, args.ir_domain, args.kh_host,
            data_port=args.data_port, xhttp_path=args.xhttp_path
        )
    except (UnsafeCandidate, OSError, subprocess.CalledProcessError) as exc:
        parser.error(f"Offline preparation refused: {type(exc).__name__}")
    print(f"PREPARED PRIVATE OFFLINE CANDIDATE: {stage} ({args.role})")
    print("NOT INSTALLED; no Docker, Smite, FRP, Xray or Nginx action performed.")


if __name__ == "__main__":
    main()
