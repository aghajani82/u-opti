#!/usr/bin/env python3
"""Restore 3x-ui SQLite exports and publish subscription formats behind U-OPTI HTTPS."""

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


def write_clash_settings(database, values):
    with contextlib.closing(sqlite3.connect(database)) as db, db:
        for key in ("subClashPath", "subClashURI"):
            db.execute("DELETE FROM settings WHERE key = ?", (key,))
            if key in values:
                db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, values[key]))


def sync_subscription_formats(base, nginx=Path("/etc/nginx"), *, clash_path=None):
    state = read_env(base / "state.env")
    domain = state["DOMAIN"].lower()
    port = int(state["SUBSCRIPTION_PORT"])
    if not re.fullmatch(r"[a-z0-9.-]+", domain) or not 1 <= port <= 65535:
        raise RestoreError("Invalid managed subscription host or port.")
    site = nginx / "sites-available" / f"3xui-{domain}"
    enabled = nginx / "sites-enabled" / site.name
    if not (enabled.exists() or enabled.is_symlink()):
        if clash_path is not None:
            raise RestoreError("Set up the managed HTTPS site first.")
        return
    if not enabled.is_symlink() or enabled.resolve() != checked_file(site):
        raise RestoreError("The HTTPS site is not managed by U-OPTI.")

    database = checked_file(base / "db/x-ui.db")
    with contextlib.closing(read_db(database)) as db:
        original = settings(db)
    config = original
    if clash_path is not None:
        clash_path = "/" + clash_path.strip().removeprefix("/").removesuffix("/") + "/"
        if not SAFE_PATH.fullmatch(clash_path) or clash_path.startswith("/smite-node/"):
            raise RestoreError("Enter a Clash path such as mihomo or /mihomo/. Use letters, digits, hyphens, or underscores in each segment.")
        if original.get("subEnable") == "false" or original.get("subClashEnable") != "true":
            raise RestoreError("Enable the Clash / Mihomo subscription in the panel first.")
        config = {**original, "subClashPath": clash_path, "subClashURI": f"https://{domain}{clash_path}"}
    subdir = nginx / f"u-opti-3xui-subscription-{domain}"
    if subdir.is_symlink():
        raise RestoreError("Unexpected Nginx routing directory.")
    snippet = subdir / "restored-formats.conf"
    saved_snippet = config_snapshot(snippet)
    if not saved_snippet and not (
        config.get("subEnable") != "false"
        and any(config.get(key) == "true" for key in ("subClashEnable", "subJsonEnable"))
    ):
        return

    if (config.get("subListen") != "127.0.0.1" or config.get("subPort") != str(port)
            or config.get("subCertFile") or config.get("subKeyFile")):
        raise RestoreError("The subscription listener must use the managed loopback HTTP port.")
    panel = route_path(config.get("webBasePath"))
    routes = formats(config, domain) if config.get("subEnable") != "false" else []
    for key, public, backend in routes:
        if key == "subURI":
            continue
        if any(path.startswith("/sub/") or "/sub/".startswith(path) for path in (public, backend)):
            raise RestoreError("Use a separate URI path for each subscription format. Keep /sub/ for the standard subscription.")
        if public.split("/")[1].isdigit():
            raise RestoreError("A subscription format overlaps the reserved XHTTP path space.")
        if any(other_key != key and (public.startswith(other) or other.startswith(public))
               for other_key, other, _ in routes):
            raise RestoreError("Subscription formats have overlapping public paths.")
    _, dedicated = render_subscriptions(routes, panel, port)
    include = f"    include {subdir}/*.conf;"
    saved_site = config_snapshot(site)
    current_site = saved_site[0].decode()
    updated_site = render_site(current_site, panel, panel, include)
    content = dedicated.encode()
    if (clash_path is None or config == original) and current_site == updated_site and (
        (saved_snippet is None and not content) or (saved_snippet and saved_snippet[0] == content)
    ):
        return

    container = state["CONTAINER_NAME"]
    changing = config != original
    if changing and (container != f"3xui-{base.name}"
                     or run("docker", "inspect", "-f", "{{.State.Running}}", container).strip() != "true"):
        raise RestoreError("Start the selected managed 3x-UI container first.")
    run("nginx", "-t")
    subdir.mkdir(mode=0o700, exist_ok=True)
    stopped = settings_changed = start_requested = False
    try:
        if changing:
            stopped = True
            run("docker", "stop", container, timeout=60)
            with contextlib.closing(read_db(database)) as db:
                if settings(db) != original:
                    raise RestoreError("Panel settings changed during preparation. Run the command again.")
            backup = Path(tempfile.mkdtemp(dir=base, prefix="pre-clash-path-"))
            snapshot_sqlite(database, backup / "x-ui.db")
            for path, saved in ((site, saved_site), (snippet, saved_snippet)):
                if saved is not None:
                    atomic_file(backup / path.name, saved[0], 0o600)
            print(f"Clash path recovery files: {backup}", flush=True)
            write_clash_settings(database, config)
            settings_changed = True
        if current_site != updated_site:
            atomic_file(site, updated_site.encode(), *saved_site[1:])
        if content:
            atomic_file(snippet, content, 0o600)
        else:
            snippet.unlink(missing_ok=True)
        run("nginx", "-t")
        run("systemctl", "reload", "nginx")
        if changing:
            start_requested = True
            run("docker", "start", container, timeout=60)
            with tempfile.TemporaryDirectory(dir=backup) as work:
                clash_routes = [route for route in routes if route[0] == "subClashURI"]
                verify_routes(domain, panel, clash_routes, subscription_ids(database), Path(work))
    except (OSError, ValueError, RestoreError, sqlite3.Error, subprocess.SubprocessError, KeyboardInterrupt):
        try:
            if start_requested:
                run("docker", "stop", container, timeout=60)
            if settings_changed:
                write_clash_settings(database, original)
            put_snapshot(snippet, saved_snippet)
            if current_site != updated_site:
                put_snapshot(site, saved_site)
            if stopped:
                run("docker", "start", container, timeout=60)
            run("nginx", "-t")
            run("systemctl", "reload", "nginx")
        except (OSError, sqlite3.Error, subprocess.SubprocessError) as rollback_error:
            raise RestoreError(f"Automatic rollback incomplete: {rollback_error}") from rollback_error
        raise
    if clash_path is not None:
        print(f"Clash subscription base URL: https://{domain}{clash_path}", flush=True)
    else:
        print("3x-UI HTTPS subscription formats synchronized.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--sync-subscription-formats", action="store_true")
    modes.add_argument("--change-clash-path", metavar="PATH")
    modes.add_argument("backup", type=Path, nargs="?")
    args = parser.parse_args()
    action = "Restore"
    if args.change_clash_path is not None:
        action = "Clash path change"
    elif args.sync_subscription_formats:
        action = "Subscription route sync"
    try:
        if os.geteuid() != 0:
            raise RestoreError("Run this command as root.")
        os.umask(0o077)
        if args.backup is None:
            if not re.fullmatch(r"[0-9]{2}", args.instance):
                raise RestoreError("Invalid instance ID.")
            base = Path("/opt/3x-ui/instances") / args.instance
            with (base / ".sqlite-restore.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                sync_subscription_formats(base, clash_path=args.change_clash_path)
        else:
            restore(args.instance, args.backup)
    except (OSError, KeyError, ValueError, RestoreError, sqlite3.Error, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        parser.exit(1, f"{action} failed: {exc}\n")


if __name__ == "__main__":
    main()
