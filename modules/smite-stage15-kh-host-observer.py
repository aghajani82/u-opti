#!/usr/bin/env python3
"""KH-only read-only host observer prototype; NOT a signer, service or grant.

Extract only minimal XHTTP facts from authoritative-mounted Sanaei SQLite
plus live Docker, socket and process observations. All observations fail
closed on drift; no live deployment authorisation and no export of secrets.
No integration with Root approval or current Node attestation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import subprocess
import time

NODE_IMAGE = "sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265"
KNOWN_CHILD_PORTS = (45121, 38658, 28897)
PATH_RE = re.compile(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z")
IDENT_RE = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
RESERVED = {"api", "auth", "admin", "assets", "docs", "health",
            "login", "metrics", "openapi", "redoc", "static", "sub", "ws"}


class ObserverHold(RuntimeError):
    pass


def need(value, reason):
    if not value:
        raise ObserverHold(reason)


def command(*argv):
    try:
        return subprocess.run(argv, check=True, capture_output=True, text=True,
                              timeout=12).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise ObserverHold("READ_ONLY_RUNTIME_COMMAND_UNAVAILABLE") from exc


def decode_one(raw):
    try:
        doc = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ObserverHold("DOCKER_INSPECT_INVALID") from exc
    need(type(doc) is list and len(doc) == 1 and type(doc[0]) is dict,
         "DOCKER_INSPECT_INVALID")
    return doc[0]


def inspect(container, *, runner=command):
    return decode_one(runner("docker", "inspect", container))


def process_list(output):
    lines = output.strip().splitlines()
    need(len(lines) >= 2 and lines[0].split()[:2] == ["PID", "COMMAND"],
         "DOCKER_TOP_INCOMPLETE")
    result = []
    for line in lines[1:]:
        fields = line.split()
        need(len(fields) == 2 and fields[0].isdigit(),
             "DOCKER_TOP_MALFORMED")
        result.append((int(fields[0]), fields[1].rsplit("/", 1)[-1]))
    return result


def pid_start_ticks(pid, *, proc_root=Path("/proc")):
    need(type(pid) is int and 1 <= pid < 2**31, "PROCESS_ID_INVALID")
    path = proc_root / str(pid) / "stat"
    try:
        line = path.read_text(encoding="ascii")
        offset = line.rfind(") ")
        need(offset > 0, "PROCESS_STAT_MALFORMED")
        fields = line[offset+2:].split()
        # /proc/PID/stat field 22 is index 19 starting at field 3.
        tick = int(fields[19])
        need(tick > 0, "PROCESS_GENERATION_INVALID")
        return tick
    except (OSError, ValueError, IndexError) as exc:
        raise ObserverHold("PROCESS_GENERATION_UNAVAILABLE") from exc


def listener_pids(raw, port):
    matched = []
    for line in raw.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 6:
            continue
        try:
            local = fields[3]
            row_port = int(local.rsplit(":", 1)[-1])
        except ValueError:
            continue
        if row_port == port:
            # Do not infer safety from a second process at the same port.
            need(local == f"127.0.0.1:{port}", "PUBLIC_OR_NON_LOOPBACK_XRAY")
            processes = re.findall(r'"([^"]+)",pid=(\d+)', fields[5])
            need(len(processes) == 1 and processes[0][0] == "xray",
                 "XRAY_SOCKET_UNATTRIBUTED")
            matched.append(int(processes[0][1]))
    need(len(matched) == 1, "KH_XHTTP_SOCKET_AMBIGUOUS")
    return matched[0]


def safe_db_path(db_path, ui):
    db = Path(db_path)
    need(db.is_absolute() and ".." not in db.parts and db.name == "x-ui.db",
         "SANAEI_PATH_UNAPPROVED")
    try:
        meta = db.lstat()
    except OSError as exc:
        raise ObserverHold("SANAEI_DB_UNAVAILABLE") from exc
    need(stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1
         and meta.st_uid == 0 and not meta.st_mode & 0o022
         and 0 < meta.st_size < 128 * 1024 * 1024,
         "SANAEI_DB_UNTRUSTED")
    # Do not mistake a copied, stale x-ui.db for the mounted live source.
    # This proves a trusted Docker volume mount, but not freshness by itself;
    # the next step checks SQLite's live read view and exact running container.
    mounts = ui.get("Mounts") or []
    trusted = []
    for m in mounts:
        src = m.get("Source")
        if not isinstance(src, str):
            continue
        root = Path(src)
        if m.get("Type") in ("bind", "volume") and root.is_absolute():
            try:
                rel = db.relative_to(root)
            except ValueError:
                continue
            if rel.parts and not any(x in (".", "..") for x in rel.parts):
                trusted.append(root)
    need(len(trusted) == 1, "SANAEI_AUTHORITATIVE_MOUNT_UNVERIFIED")
    for suffix, max_size in (("-wal", 128 * 1024 * 1024),
                             ("-shm", 4 * 1024 * 1024)):
        side = Path(str(db) + suffix)
        try:
            state = side.lstat()
        except FileNotFoundError:
            state = None
        except OSError as exc:
            raise ObserverHold("SANAEI_WAL_UNAVAILABLE") from exc
        if state:
            need(stat.S_ISREG(state.st_mode) and state.st_nlink == 1
                 and state.st_uid == meta.st_uid and not state.st_mode & 0o022
                 and 0 <= state.st_size <= max_size, "SANAEI_WAL_UNTRUSTED")
        yield_value = state is not None
        if suffix == "-wal":
            wal = yield_value
        else:
            need(wal == yield_value, "SANAEI_WAL_INCOMPLETE")
    return db, meta


def sanitized_inbounds(db, port, path):
    """One read-only SQLite transaction (including authoritative WAL view)."""
    need(type(port) is int and 1024 <= port <= 65535 and port != 7000,
         "UNAPPROVED_XHTTP_PORT")
    need(type(path) is str and len(path) <= 128 and PATH_RE.fullmatch(path)
         and path.split("/")[1].lower() not in RESERVED,
         "UNAPPROVED_XHTTP_PATH")
    try:
        with sqlite3.connect(db.absolute().as_uri() + "?mode=ro", uri=True,
                             isolation_level=None, timeout=1) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            registered = conn.execute("PRAGMA database_list").fetchall()
            need(len(registered) == 1 and Path(registered[0][2]) == db.absolute(),
                 "SANAEI_DB_ORIGIN_DRIFT")
            need(conn.execute("PRAGMA quick_check(1)").fetchone() == ("ok",),
                 "SANAEI_DB_INTEGRITY_HOLD")
            schema = {row[1] for row in conn.execute("PRAGMA table_info(inbounds)")}
            need({"port", "listen", "protocol", "stream_settings",
                  "enable"}.issubset(schema), "SANAEI_SCHEMA_UNSUPPORTED")
            rows = conn.execute(
                "SELECT port,listen,protocol,stream_settings,enable "
                "FROM inbounds LIMIT 129").fetchall()
            need(len(rows) <= 128, "SANAEI_INVENTORY_TOO_LARGE")
            observed = []
            for p, listen, protocol, stream_json, enabled in rows:
                if protocol != "vless" or enabled not in (1, True):
                    continue
                try:
                    settings = json.loads(stream_json)
                except (ValueError, TypeError) as exc:
                    raise ObserverHold("SANAEI_STREAM_INVALID") from exc
                need(type(settings) is dict, "SANAEI_STREAM_INVALID")
                if settings.get("network") != "xhttp":
                    continue
                conf = settings.get("xhttpSettings")
                inbound_path = conf.get("path") if type(conf) is dict else None
                need(type(p) is int and 1024 <= p <= 65535
                     and listen == "127.0.0.1"
                     and type(inbound_path) is str and len(inbound_path) <= 128
                     and bool(PATH_RE.fullmatch(inbound_path))
                     and inbound_path.split("/")[1].lower() not in RESERVED,
                     "SANAEI_XHTTP_ENTRY_INVALID")
                observed.append({"port": p, "path": inbound_path})
            need(len({row["port"] for row in observed}) == len(observed)
                 and len({row["path"] for row in observed}) == len(observed),
                 "SANAEI_XHTTP_DUPLICATE")
            selected = [row for row in observed if row == {"port": port, "path": path}]
            need(len(selected) == 1, "SANAEI_XHTTP_INBOUND_NOT_UNIQUE")
            canonical = json.dumps(sorted(observed, key=lambda r:(r["port"],r["path"])),
                                   sort_keys=True, separators=(",",":")).encode()
            digest = hashlib.sha256(canonical).hexdigest()
            conn.execute("ROLLBACK")
            return digest
    except sqlite3.Error as exc:
        raise ObserverHold("SANAEI_DB_READ_FAILED") from exc


def collect_kh(*, node_id, port, path, db_path, runner=command,
               proc_root=Path("/proc"), require_host=True):
    """Read local KH data only. Caller must separately pin identity/mounts.

    Returns sanitized facts, NOT a proof. Never sign arbitrary remote facts.
    This library deliberately has no CLI, web endpoint or grant wiring.
    """
    if require_host:
        need(os.geteuid() == 0 and socket.gethostname().split(".")[0] == "kh",
             "KH_ROOT_ONLY")
    need(type(node_id) is str and IDENT_RE.fullmatch(node_id),
         "KH_NODE_UNAPPROVED")
    start = time.monotonic()
    node = inspect("smite-node",runner=runner)
    ui = inspect("3xui-01",runner=runner)
    need(node.get("Image") == NODE_IMAGE
         and node.get("State",{}).get("Running") is True
         and node.get("State",{}).get("Health",{}).get("Status") == "healthy"
         and node.get("RestartCount") == 0, "KH_NODE_RUNTIME_DRIFT")
    need(ui.get("State",{}).get("Running") is True
         and ui.get("RestartCount") == 0, "SANAEI_RUNTIME_DRIFT")
    container_id = ui.get("Id")
    need(type(container_id) is str and bool(HEX64.fullmatch(container_id)),
         "SANAEI_CONTAINER_ID_INVALID")
    db, before = safe_db_path(db_path, ui)
    node_processes = process_list(runner("docker","top","smite-node","-eo","pid,comm"))
    need(sum(comm == "frpc" for _,comm in node_processes) == 3,
         "KH_FRPC_PROCESS_DRIFT")
    ui_processes = process_list(runner("docker","top","3xui-01","-eo","pid,comm"))
    xray_pids = [pid for pid,comm in ui_processes if comm == "xray"]
    need(len(xray_pids) == 1, "KH_XRAY_PROCESS_DRIFT")
    pid = xray_pids[0]
    tick = pid_start_ticks(pid,proc_root=proc_root)
    ss = runner("ss","-Hlntp")
    need(listener_pids(ss,port) == pid, "KH_XRAY_SOCKET_OWNER_DRIFT")
    digest = sanitized_inbounds(db,port,path)
    after = db.lstat()
    need((before.st_dev,before.st_ino) == (after.st_dev,after.st_ino)
         and tick == pid_start_ticks(pid,proc_root=proc_root),
         "KH_RUNTIME_GENERATION_CHANGED")
    need(time.monotonic() - start <= 5, "KH_OBSERVATION_EXPIRED")
    again = inspect("3xui-01",runner=runner)
    need(again.get("Id") == container_id
         and again.get("State",{}).get("Running") is True,
         "SANAEI_CONTAINER_REPLACED")
    return {
        "node": node_id, "port": port, "listen": "127.0.0.1",
        "protocol": "vless", "network": "xhttp", "path": path, "enabled": True,
        "xray_pid": pid, "xray_start_ticks": tick,
        "sanaei_container_id": container_id,
        "db_view_sha256": digest, "frpc_count": 3,
    }


if __name__ == "__main__":
    raise SystemExit("OFFLINE_REVIEW_LIBRARY_ONLY_NO_LIVE_APPROVAL")
