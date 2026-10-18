#!/usr/bin/env python3
"""Create an OFFLINE IR TLS/443 pairing gateway review bundle only.

NO live service, Docker, Nginx, firewall, certificate or port modification.
Generated secrets and Nginx directives are NEVER activated automatically.
"""
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import re
import secrets
import stat
import sys


class Stage19Hold(ValueError):
    pass


_DOMAIN = re.compile(
    r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]"
    r"(?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_SAFE_PATH = re.compile(r"^/[a-zA-Z0-9_./-]+$")
_FILE_NAMES = (
    "panel-pairing.env",
    "nginx-ingress-secret.conf",
    "nginx-pairing-location.conf",
    "REVIEW.txt",
)


def validate(*, domain: str, output: Path) -> str:
    if not isinstance(domain, str) or not _DOMAIN.fullmatch(domain.lower()):
        raise Stage19Hold("Valid trusted Panel DNS hostname required")
    if not output.is_absolute() or not _SAFE_PATH.fullmatch(str(output)) or ".." in output.parts:
        raise Stage19Hold("Absolute safe output path required")
    if output.exists() or output.is_symlink():
        raise Stage19Hold("Destination already exists; refusing secret overwrite")
    try:
        parent = output.parent.lstat()
    except OSError as exc:
        raise Stage19Hold("Private output parent missing") from exc
    if (not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700):
        raise Stage19Hold("Output parent must be owned mode 0700")
    return domain.lower()


def render(*, domain: str, output: Path, ingress: str, master: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{64}", ingress):
        raise Stage19Hold("Invalid private ingress token")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}=", master):
        raise Stage19Hold("Invalid private Fernet master")
    included = output / "nginx-ingress-secret.conf"
    if not output.is_absolute() or not _SAFE_PATH.fullmatch(str(included)):
        raise Stage19Hold("Nginx include path unsafe")
    return {
        "panel-pairing.env": (
            "# OFFLINE CANDIDATE; MUST NOT be added to live Compose automatically.\n"
            "SMITE_NODE_PAIRING_PREVIEW_ENABLED=false\n"
            f"SMITE_NODE_PAIRING_MASTER_KEY={master}\n"
            f"SMITE_NODE_PAIRING_INGRESS_TOKEN={ingress}\n"
        ),
        "nginx-ingress-secret.conf": (
            "# PRIVATE 0600 include; NEVER copy into public vhost or Git.\n"
            f'proxy_set_header X-Smite-Pairing-Ingress "{ingress}";\n'
        ),
        "nginx-pairing-location.conf": (
            "# INERT: add only after review to EXISTING IR 127.0.0.1:8443 SSL server.\n"
            "# Never replace the SNI stream or FRP, Backhaul, XHTTP locations.\n"
            "location = /api/node-pairing/redeem {\n"
            "    limit_except POST { deny all; }\n"
            "    client_max_body_size 16k;\n"
            "    proxy_http_version 1.1;\n"
            "    proxy_request_buffering on;\n"
            f"    include {included};\n"
            "    proxy_set_header Host $host;\n"
            "    proxy_set_header X-Forwarded-Proto https;\n"
            '    proxy_set_header Connection "";\n'
            "    proxy_pass http://127.0.0.1:8000;\n"
            "    proxy_connect_timeout 5s;\n"
            "    proxy_read_timeout 15s;\n"
            "    proxy_send_timeout 15s;\n"
            "    proxy_cache off;\n"
            '    add_header Cache-Control "no-store" always;\n'
            "    access_log off;\n"
            "}\n"
        ),
        "REVIEW.txt": (
            "STAGE19=INERT_ONLY\n"
            f"PANEL_DOMAIN={domain}\n"
            "ENTRY=EXISTING_TCP_443_SNI_TO_127.0.0.1_8443\n"
            "API=127.0.0.1_8000_ONLY\n"
            "REDEMPTION=EXACT_PATH_POST_ONLY\n"
            "PAIRING_PREVIEW=DISABLED\n"
            "SECRETS=PRIVATE_0600_NOT_LOGGED\n"
            "INTEGRATE_LOCATION=MANUAL_REVIEW_REQUIRED\n"
            "AUTH_MIGRATION=NOT_APPLIED\n"
            "ROLLBACK=DISCARD_CANDIDATE_ONLY\n"
            "NODES_DOCKER_NGINX_FIREWALL=UNCHANGED\n"
            "DO_NOT_UPLOAD_SECRET_FILES_TO_GITHUB\n"
        ),
    }


def prepare(*, domain: str, output: Path) -> str:
    host = validate(domain=domain, output=output)
    ingress = secrets.token_hex(32)
    master = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    content = render(domain=host, output=output, ingress=ingress, master=master)
    try:
        output.mkdir(mode=0o700)
    except OSError as exc:
        raise Stage19Hold("Could not create private directory") from exc
    created: list[Path] = []
    try:
        for name in _FILE_NAMES:
            path = output / name
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
            created.append(path)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content[name])
                stream.flush()
                os.fsync(stream.fileno())
        return "PRIVATE_OFFLINE_PAIRING_443_PLAN"
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        output.rmdir()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-domain", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print("STAGE19=" + prepare(domain=args.panel_domain, output=args.output_dir))
        print("PAIRING_PREVIEW=DISABLED")
        print("NGINX_RELOAD=NO")
        print("DOCKER_FIREWALL_VPS=UNCHANGED")
        print("ACTIVATION=HOLD")
        return 0
    except (Stage19Hold, OSError, ValueError) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
