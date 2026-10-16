#!/usr/bin/env python3
"""Offline-only, fail-closed Nginx integration compiler for the Backhaul Sidecar.

Takes ONE existing HTTPS server file, validates known IR/KH topology and writes
private ORIGINAL + PATCHED candidates to a new /tmp directory. This tool NEVER
writes /etc, installs software, reloads Nginx, touches Docker or opens sockets.
Its output is NOT approved for automated production activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
RENDERER = HERE / "smite-backhaul-standard.sh"
DOMAINS = re.compile(
    r"(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+\Z"
)
IR_PATH = "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
KH_PATH = "/etc/nginx/sites-available/3xui-kh.kolbe1.ir"  # Legacy default only
IR_CONTROL = "/etc/nginx/u-opti-backhaul-sidecar-control.inc"
IR_XHTTP = "/etc/nginx/u-opti-backhaul-sidecar-xhttp.inc"
KH_BRIDGE = "/etc/nginx/conf.d/u-opti-backhaul-sidecar-bridge.conf"
GUARD = ("    # U-OPTI independent Sidecar: refuse public numeric forwarding to KH Bridge.\n"
         "    location ~ ^/0*13080(/|$) {\n"
         "        return 403;\n"
         "    }\n\n")
KH_FWD_ANCHOR = "    location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {"
IR_ANCHOR = "    location / {"


class PlanRefused(ValueError):
    pass


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def domain_valid(raw: str) -> str:
    if not DOMAINS.fullmatch(raw):
        raise PlanRefused("Host must be a lowercase, fully qualified DNS name")
    return raw


def kh_vhost_path(kh_host: str) -> str:
    """Derive only the expected Sanaei-owned KH site from a validated hostname."""
    domain_valid(kh_host)
    return "/etc/nginx/sites-available/3xui-" + kh_host


def render(*args: str) -> bytes:
    result = subprocess.run(["bash", str(RENDERER), *args],
                            capture_output=True, check=True, timeout=8)
    if not result.stdout or len(result.stdout) > 40_000:
        raise PlanRefused("Unexpected renderer response")
    return result.stdout


def original_bytes(source: Path) -> bytes:
    if not source.is_absolute() or ".." in source.parts:
        raise PlanRefused("Source must be an absolute file path")
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or not 32 <= info.st_size <= 128_000:
        raise PlanRefused("Expected a non-symlink, regular, bounded Nginx file")
    # Never echo the original: it may contain URLs, secret paths or tokens.
    data = source.read_bytes()
    if len(data) != info.st_size or b"\x00" in data:
        raise PlanRefused("Source changed while reading or contains binary content")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanRefused("Nginx source must be valid UTF-8") from exc
    return data


def _base_checks(text: str, *, domain: str, xhttp_path: str = "/56053/www") -> None:
    # Require a single named server rather than accidentally inserting into
    # a shared/default server. This is intentionally restrictive, not a parser.
    if len(re.findall(r"(?m)^\s*server\s*\{", text)) != 1:
        raise PlanRefused("Nginx input must contain exactly ONE server block")
    if len(re.findall(r"(?m)^\s*server_name\s+" + re.escape(domain)
                      + r"\s*;\s*$", text)) != 1:
        raise PlanRefused("Expected exact server_name missing or duplicated")
    if text.count("{") != text.count("}"):
        raise PlanRefused("Unbalanced Nginx source; refusing layout inference")
    if "u-opti-backhaul-sidecar-" in text:
        raise PlanRefused("Existing Sidecar references found; never overwrite")
    # Existing locations for the same namespace are collision hazards, even
    # when declared in a different style or inside existing regex rules.
    if (re.search(r"(?m)^\s*location\b[^\n]*(?:/channel|/tunnel/|/56053/www)", text)
            or re.search(r"(?m)^\s*location\b[^\n]*"
                         + re.escape(xhttp_path) + r"(?=/|\s|\{|$)", text)):
        raise PlanRefused("Existing Sidecar path location; refuse duplicate")


def compile_nginx(role: str, original: bytes, ir_domain: str,
                  kh_host: str, data_port: int = 56053,
                  xhttp_path: str | None = None) -> tuple[bytes, dict[str, bytes], str]:
    if role not in ("ir", "kh"):
        raise PlanRefused("Role must be IR or KH")
    domain_valid(ir_domain)
    domain_valid(kh_host)
    # Import only the pure validator; never create a staged file here.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "nginx_plan_profile", HERE / "smite-backhaul-sidecar.py")
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    data_port, xhttp_path = validator.validated_profile(data_port, xhttp_path)
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanRefused("Invalid UTF-8") from exc
    _base_checks(text, domain=ir_domain if role == "ir" else kh_host,
                 xhttp_path=xhttp_path)
    if role == "ir":
        if (len(re.findall(r"(?m)^\s*listen\s+127\.0\.0\.1:8443\s+ssl;", text)) != 1
                or text.count(IR_ANCHOR) != 1
                or "proxy_pass http://127.0.0.1:8000;" not in text):
            raise PlanRefused("Unknown IR Smite TLS backend; require manual review")
        # The location / anchor is exact and must belong to a known single
        # Smite HTTPS server. New locations are separate include files.
        inserts = ("    # U-OPTI independent Backhaul Sidecar (offline proposal)\n"
                   f"    include {IR_CONTROL};\n"
                   f"    include {IR_XHTTP};\n\n")
        patched = text.replace(IR_ANCHOR, inserts + IR_ANCHOR, 1)
        additions = {
            IR_CONTROL: render("--render-ir-control", "3080"),
            IR_XHTTP: render("--render-ir-xhttp", str(data_port),
                             xhttp_path, kh_host),
        }
        return patched.encode("utf-8"), additions, IR_PATH
    # KH must have its existing wildcard numeric forwarding rule and its
    # own named HTTPS server. This does NOT certify other vhosts are safe.
    if not re.search(r"(?m)^\s*listen\s+443\s+ssl(?:\s+http2)?\s*;", text):
        raise PlanRefused("KH HTTPS:443 listener not found")
    if text.count(KH_FWD_ANCHOR) != 1 or "13080" in text:
        raise PlanRefused("Unknown KH forwarding layout or pre-existing guard")
    patched = text.replace(KH_FWD_ANCHOR, GUARD + KH_FWD_ANCHOR, 1)
    additions = {
        KH_BRIDGE: render("--render-kh-bridge", ir_domain, "13080")
    }
    return patched.encode("utf-8"), additions, kh_vhost_path(kh_host)


def private_write(directory: Path, name: str, contents: bytes) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", name):
        raise PlanRefused("Unsafe private stage filename")
    target = directory / name
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())


def prepare(role: str, source: Path, ir_domain: str, kh_host: str,
            data_port: int = 56053, xhttp_path: str | None = None) -> Path:
    contents = original_bytes(source)
    patched, additions, destination = compile_nginx(
        role, contents, ir_domain, kh_host, data_port, xhttp_path)
    # Use canonical slash-free form throughout the private proposal.
    xhttp_path = xhttp_path if xhttp_path is not None else f"/{data_port}/www"
    # File input must correspond to the role's actual vhost location to
    # ensure the manifest isn't accidentally used on a different file.
    if str(source) != destination:
        raise PlanRefused("Input path differs from role's expected Nginx vhost")
    if contents == patched:
        raise PlanRefused("No verified change in generated plan")
    stage = Path(tempfile.mkdtemp(prefix="uopti-bh-nginx-plan-", dir="/tmp"))
    try:
        os.chmod(stage, 0o700)
        private_write(stage, "original.conf", contents)
        private_write(stage, "patched.conf", patched)
        files = []
        for path, payload in additions.items():
            name = ("ir-control.inc" if path == IR_CONTROL else
                    "ir-xhttp.inc" if path == IR_XHTTP else "kh-bridge.conf")
            private_write(stage, name, payload)
            files.append({"path": path, "candidate": name,
                          "action": "create-if-absent",
                          "sha256": digest(payload)})
        manifest = {
            "version": 1, "role": role, "status": "REVIEW_ONLY_NO_DEPLOYMENT",
            "domain": ir_domain, "kh_host": kh_host,
            "nginx_edit": {
                "path": destination, "original_sha256": digest(contents),
                "patched_sha256": digest(patched),
                "backup": "original.conf", "candidate": "patched.conf",
                "action": "replace-only-if-original-sha-matches",
            },
            "new_files": files,
            "notes": [
                "Do not execute this plan: no live rollback or Nginx reload is implemented",
                "Before any activation, check all config includes, other Nginx vhosts, certificates and SNI",
                "Back up all of /etc/nginx and inspect owner of every reserved port",
                "Do not create a second Smite-managed Backhaul using the same local ports",
            ],
        }
        if data_port != 56053 or xhttp_path != "/56053/www":
            manifest["profile"] = {"data_port": data_port, "xhttp_path": xhttp_path}
        private_write(stage, "plan.json",
                      (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
        private_write(stage, "NOT-INSTALLED.txt", (
            "Offline Nginx candidate: NOT INSTALLED, NOT TESTED ON LIVE NGINX.\n"
            "Source and backup may contain secrets; this folder MUST stay private.\n"
            "Do not paste, upload or run these files without a separate review.\n"
        ).encode())
    except Exception:
        shutil.rmtree(stage)
        raise
    return stage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("ir", "kh"), required=True)
    parser.add_argument("--input", type=Path, required=True,
                        help="Read-only full path of current Nginx vhost")
    parser.add_argument("--ir-domain", required=True)
    parser.add_argument("--kh-host", required=True)
    parser.add_argument("--data-port", type=int, default=56053)
    parser.add_argument("--xhttp-path", default=None)
    args = parser.parse_args()
    try:
        stage = prepare(args.role, args.input, args.ir_domain, args.kh_host,
                        args.data_port, args.xhttp_path)
    except (PlanRefused, OSError, subprocess.SubprocessError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc if isinstance(exc, PlanRefused) else 'Read/renderer failed'}")
        return 2
    print(f"PRIVATE NGINX PLAN PREPARED: {stage}")
    print("REVIEW ONLY: zero live file changes; no reload, Docker, network, or installation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
