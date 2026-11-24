#!/usr/bin/env python3
"""Restore a 3x-ui SQLite export behind its existing U-OPTI HTTPS site."""

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlsplit


HOST_KEYS = (
    "webListen", "webDomain", "webPort", "webCertFile", "webKeyFile",
    "subListen", "subDomain", "subPort", "subCertFile", "subKeyFile",
    "secret", "panelGuid", "nodeMtlsCaCertPem", "nodeMtlsCaKeyPem",
    "nodeMtlsClientCertPem", "nodeMtlsClientKeyPem", "nodeMtlsClientCertSha256",
    "nodeMtlsClientCAPem",
)
SAFE_PATH = re.compile(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/")


class RestoreError(Exception):
    pass


def checked_file(path):
    if path.is_symlink() or not path.is_file():
        raise RestoreError(f"Expected a regular file: {path.name}")
    return path


def read_db(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def settings(db):
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    return dict(rows)


def route_path(value):
    if not SAFE_PATH.fullmatch(value or "") or value.startswith("/smite-node/"):
        raise RestoreError("Backup contains a URI path that this restore cannot publish.")
    return value


def public_path(config, key, fallback, domain):
    value = config.get(key) or ""
    if not value:
        return route_path(fallback)
    url = urlsplit(value)
    if url.scheme != "https" or url.netloc.lower() not in {domain, f"{domain}:443"} or url.query or url.fragment:
        raise RestoreError("Backup subscription URLs must use HTTPS on the destination domain and port 443.")
    return route_path(url.path)


def formats(config, domain):
    raw = route_path(config.get("subPath") or "/sub/")
    result = []
    if config.get("subEnable") != "false":
        result.append(("subURI", public_path(config, "subURI", raw, domain), "/sub/"))
    for kind in ("Clash", "Json"):
        prefix = "sub" + kind
        if config.get(prefix + "Enable") == "true":
            backend = route_path(config.get(prefix + "Path") or "/" + kind.lower() + "/")
            result.append((prefix + "URI", public_path(config, prefix + "URI", backend, domain), backend))
    return result


def snapshot_sqlite(source, destination):
    with contextlib.closing(read_db(source)) as original, contextlib.closing(sqlite3.connect(destination)) as copy:
        original.backup(copy)
        if copy.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RestoreError("The SQLite database failed its integrity check.")


def stage_database(source, destination, host, routes, domain):
    snapshot_sqlite(source, destination)
    with contextlib.closing(sqlite3.connect(destination)) as db, db:
        values = {key: host[key] for key in HOST_KEYS if key in host}
        values["subPath"] = "/sub/"
        for key, public, _ in routes:
            values[key] = f"https://{domain}{public}"
        keys = (*HOST_KEYS, "subPath", *(route[0] for route in routes))
        db.executemany("DELETE FROM settings WHERE key = ?", ((key,) for key in keys))
        db.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", values.items())


def subscription_ids(source):
    with contextlib.closing(read_db(source)) as db:
        ids = []
        for (raw,) in db.execute("SELECT settings FROM inbounds WHERE enable = 1"):
            for client in json.loads(raw).get("clients") or []:
                if client.get("enable", True):
                    ids.append(client.get("subId") or "")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "clients" in tables:
            ids.extend(row[0] or "" for row in db.execute("SELECT sub_id FROM clients WHERE enable = 1"))
    return list(dict.fromkeys(value for value in ids if re.fullmatch(r"[A-Za-z0-9_-]+", value)))


def render_site(site, old, new, include):
    if "# U-OPTI-MANAGED-3XUI-NGINX" not in site.splitlines():
        raise RestoreError("The destination needs a U-OPTI-managed HTTPS site.")
    for before, after in (
        (f"    location = {old.rstrip('/')} {{", f"    location = {new.rstrip('/')} {{"),
        (f"        return 301 {old};", f"        return 301 {new};"),
        (f"    location ^~ {old} {{", f"    location ^~ {new} {{"),
    ):
        if site.splitlines().count(before) != 1:
            raise RestoreError("The current panel path does not match its managed Nginx configuration.")
        site = site.replace(before + "\n", after + "\n", 1)
    site = site.replace(f"# Web Base Path: {old}\n", f"# Web Base Path: {new}\n", 1)
    if include not in site.splitlines():
        marker = "    # Sanaei Subscription\n"
        if site.count(marker) != 1:
            raise RestoreError("The managed subscription include could not be added.")
        site = site.replace(marker, include + "\n" + marker)
    return site


def render_subscriptions(routes, panel, port):
    paths = [public for _, public, _ in routes]
    backends = [backend for _, _, backend in routes]
    if len(set(paths)) != len(paths) or len(set(backends)) != len(backends):
        raise RestoreError("Subscription formats have overlapping paths.")
    raw_alias, dedicated = "", []
    for key, public, backend in routes:
        # Numeric paths belong to the guarded XHTTP router, except the
        # established legacy subscription form.
        if public.split("/")[1].isdigit() and not re.fullmatch(r"/[0-9]+/sub/", public):
            raise RestoreError("A subscription URL overlaps the reserved XHTTP path space.")
        if public == "/sub/" and backend != "/sub/":
            raise RestoreError("A subscription format overlaps the managed /sub/ route.")
        if public.startswith(panel) or panel.startswith(public):
            raise RestoreError("A subscription path overlaps the panel path.")
        if key == "subURI":
            if public != "/sub/":
                raw_alias = f"    location ^~ {public} {{\n        rewrite ^{public}(.*)$ /sub/$1 last;\n    }}\n"
            continue
        dedicated.append(f"""    location ^~ {public} {{
        proxy_pass http://127.0.0.1:{port}{backend};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }}
""")
    return raw_alias, "\n".join(dedicated)


def remove_sidecars(db):
    for suffix in ("-wal", "-shm", "-journal"):
        Path(str(db) + suffix).unlink(missing_ok=True)


def run(*command, timeout=30):
    return subprocess.run(command, check=True, timeout=timeout, text=True, stdout=subprocess.PIPE).stdout


def probe(domain, path, destination):
    # Response bodies can contain credentials. Retain them only for verification.
    return subprocess.run(
        ["curl", "--noproxy", "*", "--resolve", f"{domain}:443:127.0.0.1",
         "--max-time", "5", "-s", "-o", str(destination), "-w", "%{http_code}",
         f"https://{domain}{path}"], check=False, capture_output=True, text=True,
    ).stdout


def verify_routes(domain, panel, routes, ids, directory):
    body = directory / "probe"
    try:
        for _ in range(25):
            if probe(domain, panel, body) in {"200", "301", "302", "303", "307", "308"}:
                break
            time.sleep(1)
        else:
            raise RestoreError("The restored panel URL did not respond.")
        if routes and not ids:
            print("No enabled subscription ID was available for an HTTPS subscription check.", flush=True)
        if not ids:
            return
        for key, public, _ in routes:
            for client in ids[:8]:
                if probe(domain, public + client, body) != "200":
                    continue
                content = body.read_bytes().lstrip()
                if not content or content.startswith(b"<"):
                    continue
                if key == "subClashURI" and b"proxies:" not in content:
                    continue
                if key == "subJsonURI" and not content.startswith((b"[", b"{")):
                    continue
                break
            else:
                raise RestoreError(f"The restored {key} URL did not return its subscription format.")
    finally:
        body.unlink(missing_ok=True)


def atomic_file(path, content, mode, uid=None, gid=None):
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            info = os.fstat(handle.fileno())
            if uid is not None and (info.st_uid, info.st_gid) != (uid, gid):
                os.fchown(handle.fileno(), uid, gid)
            handle.write(content)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def config_snapshot(path):
    if not path.exists() and not path.is_symlink():
        return None
    info = checked_file(path).stat()
    return path.read_bytes(), stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid


def put_snapshot(path, backup):
    if backup is None:
        path.unlink(missing_ok=True)
    else:
        atomic_file(path, *backup)


def read_env(path):
    return dict(line.split("=", 1) for line in checked_file(path).read_text().splitlines() if "=" in line)


def restore(instance, source):
    if not re.fullmatch(r"[0-9]{2}", instance):
        raise RestoreError("Invalid instance ID.")
    base = Path("/opt/3x-ui/instances") / instance
    with (base / ".sqlite-restore.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        restore_locked(instance, base, source)


def restore_locked(instance, base, source, nginx=Path("/etc/nginx")):
    source = checked_file(source)
    live_db = checked_file(base / "db/x-ui.db")
    if source.samefile(live_db):
        raise RestoreError("Select an exported backup, not the live database.")
    state = read_env(base / "state.env")
    compat = base / "compat.env"
    old_panel = route_path(read_env(compat).get("WEB_BASE_PATH"))
    domain = state["DOMAIN"].lower()
    container = state["CONTAINER_NAME"]
    port = int(state["SUBSCRIPTION_PORT"])
    if not re.fullmatch(r"[a-z0-9.-]+", domain) or container != f"3xui-{instance}" or not 1 <= port <= 65535:
        raise RestoreError("Invalid destination instance settings.")
    site = checked_file(nginx / "sites-available" / f"3xui-{domain}")
    enabled = nginx / "sites-enabled" / site.name
    if not enabled.is_symlink() or enabled.resolve() != site:
        raise RestoreError("The managed HTTPS site is not enabled.")
    subdir = nginx / f"u-opti-3xui-subscription-{domain}"
    guarddir = nginx / f"u-opti-3xui-xhttp-{domain}"
    if subdir.is_symlink() or guarddir.is_symlink():
        raise RestoreError("Unexpected Nginx routing directory.")
    subs = subdir / "public-url.conf"
    format_file = subdir / "restored-formats.conf"
    guard = guarddir / "routes.conf"
    helper = checked_file(Path(__file__).with_name("docker-3xui-xhttp-guard.py"))
    with contextlib.closing(read_db(source)) as db:
        imported = settings(db)
    with contextlib.closing(read_db(live_db)) as db:
        host = settings(db)
    panel = route_path(imported.get("webBasePath"))
    if panel.split("/")[1].isdigit():
        raise RestoreError("The panel path overlaps the reserved XHTTP path space.")
    routes = formats(imported, domain)
    ids = subscription_ids(source)
    site_text = render_site(site.read_text(), old_panel, panel, f"    include {subdir}/*.conf;")
    raw_alias, format_text = render_subscriptions(routes, panel, port)
    compat_snapshot = compat.read_text().splitlines()
    if compat_snapshot.count(f"WEB_BASE_PATH={old_panel}") != 1:
        raise RestoreError("The saved panel path is ambiguous.")
    compat_text = "\n".join(
        f"WEB_BASE_PATH={panel}" if line == f"WEB_BASE_PATH={old_panel}" else line
        for line in compat_snapshot
    ) + "\n"
    if host.get("subListen") != "127.0.0.1" or host.get("subCertFile") or host.get("subKeyFile"):
        raise RestoreError("The managed site requires a loopback HTTP subscription listener.")
    if host.get("subPort") != str(port) or host.get("webBasePath") != old_panel:
        raise RestoreError("The live panel settings do not match the saved U-OPTI settings.")
    if run("docker", "inspect", "-f", "{{.State.Running}}", container).strip() != "true":
        raise RestoreError("Start the destination instance before restoring.")
    run("nginx", "-t")
    with tempfile.TemporaryDirectory(dir=base, prefix=".restore-stage-") as work:
        staged = Path(work) / "import.db"
        stage_database(source, staged, host, routes, domain)
        if input("Replace the destination database and restore its old HTTPS URLs? [y/N]: ").lower() != "y":
            return
        backup_dir = Path(tempfile.mkdtemp(dir=base, prefix="pre-db-restore-"))
        config_files = (site, compat, subs, format_file, guard)
        backups = {path: config_snapshot(path) for path in config_files}
        for path, saved in backups.items():
            if saved is not None:
                atomic_file(backup_dir / path.name, saved[0], 0o600)
        print(f"Restore recovery files: {backup_dir}", flush=True)
        old_db = backup_dir / "x-ui.db"
        db_info = live_db.stat()
        mode = stat.S_IMODE(db_info.st_mode)
        db_owner = (mode, db_info.st_uid, db_info.st_gid)
        stop_requested = swapped = start_requested = False
        try:
            stop_requested = True
            run("docker", "stop", container, timeout=60)
            snapshot_sqlite(live_db, old_db)
            remove_sidecars(live_db)
            atomic_file(live_db, staged.read_bytes(), *db_owner)
            swapped = True
            subdir.mkdir(mode=0o700, exist_ok=True)
            atomic_file(site, site_text.encode(), *backups[site][1:])
            atomic_file(compat, compat_text.encode(), *backups[compat][1:])
            atomic_file(subs, raw_alias.encode(), 0o600)
            atomic_file(format_file, format_text.encode(), 0o600)
            run("nginx", "-t")
            start_requested = True
            run("docker", "start", container, timeout=60)
            # Xray needs its local listeners before the guarded inventory can sync.
            for _ in range(20):
                review = subprocess.run(["python3", "-B", str(helper), "--instance", instance, "--check"],
                                        capture_output=True, text=True, timeout=30)
                if review.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RestoreError("XHTTP review failed: " + (review.stdout or review.stderr).strip())
            print(run("python3", "-B", str(helper), "--instance", instance, "--apply", timeout=60).strip())
            run("systemctl", "reload", "nginx")
            verify_routes(domain, panel, routes, ids, Path(work))
        except (OSError, ValueError, RestoreError, sqlite3.Error, subprocess.SubprocessError, KeyboardInterrupt):
            try:
                if start_requested:
                    run("docker", "stop", container, timeout=60)
                if swapped:
                    remove_sidecars(live_db)
                    atomic_file(live_db, old_db.read_bytes(), *db_owner)
                for path, backup in backups.items():
                    put_snapshot(path, backup)
                run("nginx", "-t")
                run("systemctl", "reload", "nginx")
                if stop_requested:
                    run("docker", "start", container, timeout=60)
                print("Previous database and Nginx configuration restored.", flush=True)
            except (OSError, subprocess.SubprocessError):
                print(f"ERROR: Automatic rollback incomplete. Use the recovery files in {backup_dir}.", flush=True)
            raise
        print("Database restore and HTTPS route verification complete.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise RestoreError("Run this restore as root.")
        os.umask(0o077)
        restore(args.instance, args.backup)
    except (OSError, KeyError, ValueError, RestoreError, sqlite3.Error, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        parser.exit(1, f"Restore failed: {exc}\n")


if __name__ == "__main__":
    main()
