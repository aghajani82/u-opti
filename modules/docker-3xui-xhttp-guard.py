#!/usr/bin/env python3
"""Guard KH HTTPS XHTTP forwarding: accept only active loopback Sanaei VLESS inbounds.

Ports are discovered from the local 3x-ui database, never hardcoded.
No tunnel engine or IR service is modified. Use --check before --apply.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile

OLD = "    location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {"
SAFE = re.compile(r"/([0-9]{4,5})/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z")
DOMAIN = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\Z")


class Hold(ValueError):
    pass


def require_file(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != os.geteuid() or s.st_mode & 0o022:
        raise Hold("Unsafe source file permissions")
    return path


def validate_inbounds(db, reserved, ss_output):
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=10) as cx:
        rows = cx.execute(
            "SELECT enable, port, listen, protocol, stream_settings FROM inbounds"
        ).fetchall()
    if len(rows) > 128:
        raise Hold("Too many inbounds")
    routes = {}
    for active, port, listen, protocol, raw in rows:
        if not active or protocol != "vless":
            continue
        stream = json.loads(raw)
        if stream.get("network") != "xhttp":
            continue
        if type(port) is not int or port < 1024 or port > 65535 or port in reserved:
            raise Hold("Unsafe XHTTP port")
        if listen != "127.0.0.1" or stream.get("security", "none") != "none":
            raise Hold("XHTTP must be plain HTTP on 127.0.0.1")
        settings = stream.get("xhttpSettings", {})
        raw_path = settings.get("path")
        if not isinstance(raw_path, str):
            raise Hold("Invalid XHTTP path")
        path = raw_path.rstrip("/")
        m = SAFE.fullmatch(path)
        if not m or int(m.group(1)) != port or len(path) > 128:
            raise Hold("XHTTP path must be /CHOSEN_PORT/path")
        listens = [line for line in ss_output.splitlines()
                   if len(line.split()) > 3 and
                   line.split()[3].rsplit(":", 1)[-1] == str(port)]
        if not listens or any(
            not row.split()[3].startswith("127.0.0.1:") or "xray" not in row.lower()
            for row in listens
        ):
            raise Hold("XHTTP port is not an exclusive loopback Xray listener")
        if path in routes or any(
            path.startswith(other + "/") or other.startswith(path + "/")
            for other in routes
        ):
            raise Hold("Overlapping XHTTP routes")
        routes[path] = port
    return routes


def render(routes):
    common = (
        "        client_max_body_size 0;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_buffering off;\n"
        "        proxy_request_buffering off;\n"
        "        proxy_read_timeout 1d;\n"
        "        proxy_send_timeout 1d;\n"
    )
    output = "# U-OPTI KH dynamic allowlisted XHTTP routes\n"
    for path, port in sorted(routes.items()):
        for suffix, match in (("", "="), ("/", "^~")):
            output += (f"    location {match} {path}{suffix} {{\n"
                       f"        proxy_pass http://127.0.0.1:{port};\n"
                       + common + "    }\n")
    return output


def harden(source, domain):
    include = f"    include /etc/nginx/u-opti-3xui-xhttp-{domain}/*.conf;\n"
    deny = "    location ~ ^/[0-9]+/ { return 404; }\n"
    if not source.startswith("# U-OPTI-MANAGED-3XUI-NGINX"):
        raise Hold("Not an owned U-OPTI vhost")
    if f"server_name {domain};" not in source:
        raise Hold("Vhost domain mismatch")
    if include in source and deny in source and "$fwdport" not in source:
        return source
    lines = source.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip() == OLD]
    if len(starts) != 1:
        raise Hold("Unknown numeric forwarding block")
    start = starts[0]
    ends = [i for i in range(start + 1, len(lines)) if lines[i].rstrip() == "    }"]
    if not ends:
        raise Hold("Unclosed numeric forwarding block")
    end = ends[0]
    old = "".join(lines[start:end + 1])
    if ("proxy_pass http://127.0.0.1:$fwdport$is_args$args;" not in old or
            "grpc_pass grpc://127.0.0.1:$fwdport;" not in old):
        raise Hold("Modified legacy forwarding block")
    return "".join(lines[:start] + [include, deny] + lines[end + 1:])


def atomic(path, content):
    fd, stage = tempfile.mkstemp(dir=path.parent, prefix=".uopti-xhttp-")
    try:
        with os.fdopen(fd, "w") as out:
            os.fchmod(out.fileno(), 0o644)
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(stage, path)
    finally:
        if os.path.lexists(stage):
            os.unlink(stage)


def apply(instance, check):
    if not re.fullmatch(r"[0-9]{2}", instance):
        raise Hold("Invalid instance ID")
    root = Path("/opt/3x-ui/instances") / instance
    state = require_file(root / "state.env")
    values = dict(line.split("=", 1) for line in state.read_text().splitlines() if "=" in line)
    domain = values.get("DOMAIN", "")
    if not DOMAIN.fullmatch(domain):
        raise Hold("Invalid instance domain")
    db = require_file(root / "db/x-ui.db")
    site = require_file(Path("/etc/nginx/sites-available") / ("3xui-" + domain))
    enabled = Path("/etc/nginx/sites-enabled") / site.name
    if not enabled.is_symlink() or enabled.resolve() != site:
        raise Hold("Expected Sanaei site not enabled")
    reserved = {22, 80, 443, 7000, 8000, 8443, 8888}
    for key in ("PANEL_PORT", "API_PORT", "SUBSCRIPTION_PORT", "METRICS_PORT"):
        reserved.add(int(values[key]))
    sockets = subprocess.run(["ss", "-H", "-lntp"], check=True,
                             text=True, capture_output=True, timeout=10).stdout
    routes = validate_inbounds(db, reserved, sockets)
    original = site.read_text()
    hardened = harden(original, domain)
    content = render(routes)
    print(f"XHTTP_REVIEW=PASS ROUTES={len(routes)} LEGACY_ROUTE={'YES' if hardened != original else 'NO'}")
    if check:
        return
    if os.geteuid() != 0:
        raise Hold("Root required")
    folder = Path("/etc/nginx") / ("u-opti-3xui-xhttp-" + domain)
    if folder.is_symlink():
        raise Hold("Unsafe Nginx allowlist directory")
    folder.mkdir(mode=0o700, exist_ok=True)
    fs = folder.lstat()
    if not stat.S_ISDIR(fs.st_mode) or fs.st_uid != 0 or fs.st_mode & 0o077:
        raise Hold("Unsafe allowlist directory permissions")
    snippet = folder / "routes.conf"
    old_snippet = None
    if snippet.exists() or snippet.is_symlink():
        require_file(snippet)
        old_snippet = snippet.read_text()
    if hardened == original and old_snippet == content:
        print("XHTTP_SYNC=UNCHANGED")
        return
    # Private recovery snapshot is retained, including for a successful field trial.
    backup_dir = Path("/var/lib/u-opti/3xui-xhttp-backups")
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    bs = backup_dir.lstat()
    if backup_dir.is_symlink() or not stat.S_ISDIR(bs.st_mode) or bs.st_mode & 0o077:
        raise Hold("Unsafe recovery snapshot directory")
    fd, snapshot = tempfile.mkstemp(dir=backup_dir, prefix="pre-xhttp-", suffix=".conf")
    with os.fdopen(fd, "w") as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(original)
    try:
        atomic(snippet, content)
        if hardened != original:
            atomic(site, hardened)
        subprocess.run(["nginx", "-t"], check=True, timeout=20)
        subprocess.run(["systemctl", "reload", "nginx"], check=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        try:
            atomic(site, original)
            if old_snippet is None:
                snippet.unlink(missing_ok=True)
            else:
                atomic(snippet, old_snippet)
            subprocess.run(["nginx", "-t"], check=True, timeout=20)
            subprocess.run(["systemctl", "reload", "nginx"], check=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            raise Hold("CRITICAL: manual Nginx recovery required") from None
        raise Hold("Nginx rejected change; previous configuration restored") from None
    print(f"XHTTP_SYNC=PASS ROUTES={len(routes)} UNKNOWN_NUMERIC_PORTS=DENIED")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--instance", default="01")
    actions = p.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--apply", action="store_true")
    a = p.parse_args()
    try:
        apply(a.instance, a.check)
    except (Hold, OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as e:
        print("HOLD: " + str(e))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
