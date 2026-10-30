#!/usr/bin/env python3
"""KH-only, journaled Sanaei Inventory overlay for the EXISTING Stage15 Node.

No database writes, FRP apply, owner creation, image load, Nginx change or
identity/replay restoration. Recreate of smite-node interrupts its sole FRPC;
apply/recover/rollback require independent, interactive root authorization.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

HERE = Path(__file__).resolve().parent

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

w = load("kh_inventory_wss", "smite-stage15-wss.py")
h = w.host
need = h.require
Hold = h.Hold
STATE = Path("/var/lib/u-opti/smite-stage15-kh-inventory")
OVERLAY = w.NODE / "docker-compose.sanaei-inventory.yml"
DB_DIR = Path("/opt/3x-ui/instances/01/db")
DB_FILE = DB_DIR / "x-ui.db"
TARGET = "/run/smite-sanaei-ro"
EXPECTED_IMAGE = w.REVIEWED_IMAGES["node"]
PHASES = ("PREPARED", "RECREATING", "COMMITTED", "RECOVERING", "ROLLED_BACK")
OVERLAY_BYTES = (
    "services:\n"
    "  smite-node:\n"
    "    environment:\n"
    '      SMITE_SANAEI_INVENTORY_ENABLED: "true"\n'
    "    volumes:\n"
    "      - type: bind\n"
    "        source: /opt/3x-ui/instances/01/db\n"
    "        target: /run/smite-sanaei-ro\n"
    "        read_only: true\n"
    "        bind:\n"
    "          create_host_path: false\n"
).encode()
SIGNED_PROBE = r'''
import json, urllib.request, urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
from app.config import settings
node_id, secret = read_identity(settings.smite_agent_identity_path)
target = "/api/agent/inbounds/xhttp"
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
def request(headers=None):
    req = urllib.request.Request("http://127.0.0.1:8888" + target,
                                 method="GET", headers=headers or {})
    try:
        with opener.open(req, timeout=6) as response:
            return response.status, response.read(65536)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1024)
if request()[0] != 401:
    raise RuntimeError("INVENTORY_ANONYMOUS_AUTH_BYPASS")
headers = sign_request(secret=secret, node_id=node_id,
                       method="GET", target=target, body=b"")
status, body = request(headers)
if status != 200:
    raise RuntimeError("SIGNED_KH_INVENTORY_UNAVAILABLE")
data = json.loads(body)
items = data.get("inbounds")
if (data.get("schema_version") != 1 or not isinstance(items, list)
        or not any(isinstance(item, dict)
                   and item.get("port") == 45121
                   and item.get("path") == "/45121/www"
                   and item.get("listen") == "127.0.0.1"
                   and item.get("network") == "xhttp"
                   and item.get("protocol") == "vless"
                   and item.get("enabled") is True for item in items)):
    raise RuntimeError("KH_EXPECTED_XHTTP_INBOUND_MISSING")
if request(headers)[0] != 401:
    raise RuntimeError("SIGNED_INVENTORY_REPLAY_ACCEPTED")
print("SIGNED_KH_INVENTORY=45121:/45121/www;REPLAY=DENIED")
'''

def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()

def digest(value):
    return hashlib.sha256(value).hexdigest()

def exists(path):
    return path.exists() or path.is_symlink()

def database():
    # Only operator-approved instance 01; never accept path from GUI or request.
    for parent in [Path("/opt/3x-ui"), Path("/opt/3x-ui/instances"),
                   DB_DIR.parent, DB_DIR]:
        st = parent.lstat()
        need(stat.S_ISDIR(st.st_mode) and st.st_uid == 0
             and not st.st_mode & 0o022, "SANAEI_DIRECTORY_UNTRUSTED")
    st = DB_FILE.lstat()
    need(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and st.st_nlink == 1
         and not st.st_mode & 0o022 and 0 < st.st_size <= 128 * 1024 * 1024,
         "SANAEI_DATABASE_UNTRUSTED")
    # No SQLite checkpoint/copy: mode=ro opens the live directory with WAL/SHM.
    for suffix in ("-wal", "-shm"):
        side = DB_DIR / ("x-ui.db" + suffix)
        if exists(side):
            info = side.lstat()
            need(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                 and info.st_nlink == 1 and not info.st_mode & 0o022,
                 "SANAEI_WAL_UNTRUSTED")
    need(exists(DB_DIR / "x-ui.db-wal") == exists(DB_DIR / "x-ui.db-shm"),
         "SANAEI_WAL_INCOMPLETE")
    try:
        with sqlite3.connect(DB_FILE.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("SELECT port, listen, protocol, stream_settings, enable FROM inbounds LIMIT 129").fetchall()
    except sqlite3.Error as exc:
        raise Hold("SANAEI_WAL_READ_UNAVAILABLE") from exc
    return [st.st_dev, DB_DIR.stat().st_ino, st.st_ino]

def expected_signature(before):
    need(before["image"] == EXPECTED_IMAGE, "NODE_IMAGE_DRIFT")
    after = copy.deepcopy(before)
    need(after["env"].get("SMITE_SANAEI_INVENTORY_ENABLED") == "false"
         and after["env"].get("SMITE_SANAEI_DB_PATH") == TARGET + "/x-ui.db",
         "INVENTORY_BASELINE_DRIFT")
    after["env"]["SMITE_SANAEI_INVENTORY_ENABLED"] = "true"
    mounts = [m for m in after["mounts"] if m["Destination"] == TARGET]
    need(len(mounts) == 1 and mounts[0]["Type"] == "bind"
         and mounts[0]["RW"] is False, "INVENTORY_MOUNT_BASELINE_DRIFT")
    previous = mounts[0]["Source"]
    need(previous == "/opt/smite-node/.sanaei-empty", "INVENTORY_SOURCE_DRIFT")
    mounts[0]["Source"] = str(DB_DIR)
    binds = after["host"].get("Binds")
    need(isinstance(binds, list), "INVENTORY_BINDS_MISSING")
    old = previous + ":" + TARGET + ":ro"
    new = str(DB_DIR) + ":" + TARGET + ":ro"
    need(binds.count(old) == 1 and new not in binds, "INVENTORY_BIND_DRIFT")
    binds[binds.index(old)] = new
    after["host"]["Binds"] = sorted(binds)
    return after

def validate_compose():
    command = w.compose("node", True, ["config", "--format", "json"])
    before = json.loads(h.run(command))
    after = json.loads(h.run(
        w.compose("node", True, ["-f", "-", "config", "--format", "json"]),
        input=OVERLAY_BYTES.decode()))
    old = before["services"]["smite-node"]
    new = after["services"]["smite-node"]
    a = copy.deepcopy(after)
    a_service = a["services"]["smite-node"]
    need(old.get("environment", {}).get("SMITE_SANAEI_INVENTORY_ENABLED") == "false"
         and new.get("environment", {}).get("SMITE_SANAEI_INVENTORY_ENABLED") == "true",
         "INVENTORY_ENV_DELTA_INVALID")
    a_service["environment"]["SMITE_SANAEI_INVENTORY_ENABLED"] = "false"
    old_vol = old["volumes"]
    new_vol = a_service["volumes"]
    need(isinstance(old_vol, list) and isinstance(new_vol, list)
         and len(old_vol) == len(new_vol), "INVENTORY_UNEXPECTED_MOUNT_COUNT")
    old_mount = [m for m in old_vol if m.get("target") == TARGET]
    new_mount = [m for m in new_vol if m.get("target") == TARGET]
    need(len(old_mount) == len(new_mount) == 1
         and old_mount[0].get("source") == "/opt/smite-node/.sanaei-empty"
         and old_mount[0].get("read_only") is True
         and new_mount[0].get("source") == str(DB_DIR)
         and new_mount[0].get("read_only") is True
         and new_mount[0].get("bind", {}).get("create_host_path") is False,
         "INVENTORY_COMPOSE_BIND_UNTRUSTED")
    idx = new_vol.index(new_mount[0])
    original = copy.deepcopy(new_mount[0])
    original["source"] = old_mount[0]["source"]
    original["bind"] = old_mount[0].get("bind", {})
    new_vol[idx] = original
    need(a == before, "INVENTORY_COMPOSE_UNRELATED_DRIFT")

def frpc():
    node = w.inspect("node")
    pid = node["State"].get("Pid")
    need(type(pid) is int and pid > 1, "NODE_HOST_PID_UNAVAILABLE")
    node_ns = [os.readlink(f"/proc/{pid}/ns/{name}") for name in ("mnt", "pid")]
    matches = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            if (Path("/proc") / entry / "comm").read_text().strip() != "frpc":
                continue
            name_spaces = [os.readlink(f"/proc/{entry}/ns/{name}")
                           for name in ("mnt", "pid")]
            cmdline = (Path("/proc") / entry / "cmdline").read_bytes()
            matches.append((name_spaces, cmdline))
        except (OSError, PermissionError):
            continue
    need(len(matches) == 1 and matches[0][0] == node_ns
         and b"frpc" in matches[0][1] and len(matches[0][1]) < 16384,
         "FRPC_SINGLETON_NAMESPACE_DRIFT")
    return digest(matches[0][1])

def bound(doc):
    need(doc["schema"] == 1 and doc["phase"] in PHASES
         and set(doc) == {"schema", "phase", "wss_sha", "protected",
                          "db", "before", "after", "frpc", "overlay_sha"},
         "INVENTORY_RECEIPT_INVALID")
    need(doc["overlay_sha"] == digest(OVERLAY_BYTES), "INVENTORY_OVERLAY_HASH_DRIFT")
    receipt = w.read_record()
    need(receipt["state"] == "COMMITTED" and receipt["roles"] == ["node"],
         "KH_WSS_NOT_COMMITTED")
    need(doc["wss_sha"] == digest(h.file(w.STATE / "record.json", mode=0o600))
         and receipt["runtime"]["node"] == doc["before"]
         and expected_signature(doc["before"]) == doc["after"],
         "INVENTORY_WSS_BINDING_DRIFT")
    need(w.protected(["node"]) == doc["protected"], "SIGNED_STORAGE_DRIFT")
    need(database() == doc["db"], "SANAEI_DATABASE_INODE_DRIFT")
    if doc["phase"] in ("RECREATING", "COMMITTED", "RECOVERING"):
        need(h.file(OVERLAY, mode=0o600) == OVERLAY_BYTES,
             "INVENTORY_OVERLAY_DRIFT")
    elif exists(OVERLAY):
        need(h.file(OVERLAY, mode=0o600) == OVERLAY_BYTES,
             "INVENTORY_OVERLAY_DRIFT")
    return doc

def record():
    h.directory(STATE, private=True)
    return bound(json.loads(h.file(STATE / "record.json", mode=0o600, limit=1048576)))

def save(doc):
    bound(doc)
    w.write_atomic(STATE / "record.json", canonical(doc))

def expectation(wss_doc, image):
    """WSS admission extension: never trust an incomplete inventory cutover."""
    doc = record()
    need(wss_doc["runtime"]["node"] == doc["before"]
         and image == EXPECTED_IMAGE, "INVENTORY_NODE_IMAGE_DRIFT")
    need(doc["phase"] in ("COMMITTED", "ROLLED_BACK"),
         "KH_INVENTORY_RECOVERY_REQUIRED")
    return doc["after"] if doc["phase"] == "COMMITTED" else doc["before"]

def verify_runtime(doc, after):
    obj = w.inspect("node")
    w.runtime("node", obj, True, inventory=after)
    need(w.signature(obj) == doc["after" if after else "before"],
         "KH_NODE_RUNTIME_SIGNATURE_DRIFT")
    need(h.run(["docker", "image", "inspect", "smite-node:stage15-local",
                "--format", "{{.Id}}"]) == EXPECTED_IMAGE,
         "KH_IMAGE_TAG_DRIFT")
    return obj

def signed_inbounds():
    # Exercises the real loopback signed HTTP endpoint AND durable replay.
    response = h.run(["docker", "exec", "-w", "/app", "smite-node",
                      "python3", "-c", SIGNED_PROBE], timeout=35)
    need(response == "SIGNED_KH_INVENTORY=45121:/45121/www;REPLAY=DENIED",
         "SIGNED_KH_INVENTORY_UNAVAILABLE")

def plan():
    need(not exists(STATE) and not exists(STATE.with_name(STATE.name + ".stage")),
         "EXISTING_KH_INVENTORY_TRANSACTION")
    need(not exists(OVERLAY), "INVENTORY_OVERLAY_ALREADY_EXISTS")
    need(os.geteuid() == 0 and os.uname().nodename.split(".")[0].lower() == "kh",
         "KH_ROOT_ONLY")
    wdoc = w.read_record()
    need(wdoc["roles"] == ["node"] and wdoc["state"] == "COMMITTED",
         "KH_WSS_NOT_COMMITTED")
    obj = w.inspect("node")
    w.runtime("node", obj, True)
    before = w.signature(obj)
    need(before == wdoc["runtime"]["node"], "KH_EXISTING_WSS_SIGNATURE_DRIFT")
    h.require(obj["State"]["Health"]["Status"] == "healthy", "KH_NODE_UNHEALTHY")
    need(h.run(["docker", "image", "inspect", "smite-node:stage15-local",
                "--format", "{{.Id}}"]) == EXPECTED_IMAGE, "KH_IMAGE_TAG_DRIFT")
    validate_compose()
    db = database()
    probe = frpc()
    w.health(wdoc, True)
    return dict(schema=1, phase="PREPARED",
                wss_sha=digest(h.file(w.STATE / "record.json", mode=0o600)),
                protected=w.protected(["node"]), db=db, before=before,
                after=expected_signature(before), frpc=probe,
                overlay_sha=digest(OVERLAY_BYTES))

def begin(doc):
    # Atomic publication: a killed preparation never exposes half a receipt.
    stage = STATE.with_name(STATE.name + ".stage")
    h.new_dir(stage)
    h.new_file(stage / "record.json", canonical(doc), 0o600)
    os.replace(stage, STATE)
    h.flush(STATE.parent)

def recreate(enabled):
    files = w.service_files("node") + [w.overlay("node")]
    if enabled:
        files.append(OVERLAY)
    cmd = ["docker", "compose"]
    for file in files:
        cmd += ["-f", str(file)]
    return h.run(cmd + ["up", "-d", "--no-build", "--no-deps", "--pull",
                        "never", "--force-recreate", "smite-node"], timeout=160)

def apply():
    doc = plan()
    begin(doc)
    h.new_file(OVERLAY, OVERLAY_BYTES, 0o600)
    doc["phase"] = "RECREATING"
    save(doc)
    recreate(True)  # only smite-node: one short FRPC interruption
    verify_runtime(doc, True)
    need(frpc() == doc["frpc"], "FRPC_COMMAND_OR_NAMESPACE_DRIFT")
    signed_inbounds()
    need(w.protected(["node"]) == doc["protected"], "SIGNED_STORAGE_DRIFT")
    doc["phase"] = "COMMITTED"
    save(doc)
    w.health(w.read_record(), True)

def rollback():
    doc = record()
    need(doc["phase"] in PHASES, "INVENTORY_UNKNOWN_STATE")
    if doc["phase"] == "ROLLED_BACK":
        verify_runtime(doc, False)
        w.health(w.read_record(), True)
        return
    current = None
    try:
        obj = w.inspect("node")
    except Hold:
        # Docker can remove the old container before power fails. Recovery
        # may repair ONLY that incomplete state, with no competing FRPC.
        need(doc["phase"] in ("RECREATING", "RECOVERING"),
             "KH_NODE_MISSING_AFTER_COMMIT")
        need(h.run(["docker", "ps", "-aq", "--filter",
                    "name=^/smite-node$"]) == "",
             "KH_CONTAINER_UNKNOWN_DURING_RECOVERY")
        processes = h.run(["ps", "-e", "-o", "comm="]).splitlines()
        need("frpc" not in processes, "FRPC_RUNNING_WITHOUT_NODE")
    else:
        current = w.signature(obj)
        need(current in (doc["before"], doc["after"]),
             "KH_RUNTIME_EXTERNAL_DRIFT")
    if current == doc["before"]:
        # Already restored (or cutover never started): no second interruption.
        verify_runtime(doc, False)
    else:
        doc["phase"] = "RECOVERING"
        save(doc)
        recreate(False)
        verify_runtime(doc, False)
    need(frpc() == doc["frpc"], "FRPC_ROLLBACK_DRIFT")
    need(w.protected(["node"]) == doc["protected"], "SIGNED_STORAGE_DRIFT")
    doc["phase"] = "ROLLED_BACK"
    save(doc)
    w.health(w.read_record(), True)

def verify():
    doc = record()
    need(doc["phase"] == "COMMITTED", "KH_INVENTORY_NOT_COMMITTED")
    verify_runtime(doc, True)
    need(frpc() == doc["frpc"], "FRPC_POST_RECREATE_DRIFT")
    signed_inbounds()
    w.health(w.read_record(), True)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("plan", "apply", "verify", "recover", "rollback"))
    a = p.parse_args()
    try:
        need(os.geteuid() == 0 and os.uname().nodename.split(".")[0].lower() == "kh",
             "KH_ROOT_ONLY")
        if a.action in ("apply", "recover", "rollback"):
            need(sys.stdin.isatty(), "ROOT_TTY_APPROVAL_REQUIRED")
            challenge = a.action.upper() + "-KH-INVENTORY-SNAPSHOT-CONSOLE-FRPC-INTERRUPTION"
            need(input("Type " + challenge + ": ").strip() == challenge,
                 "ROOT_OPERATOR_CANCELLED")
        with h.exclusive(w.LOCK):
            if a.action == "plan":
                plan()
            elif a.action == "apply":
                apply()
            elif a.action == "verify":
                verify()
            else:
                rollback()
        print("KH_INVENTORY_" + a.action.upper() + "=PASS")
        print("FRPS_OWNER_REAPPLIED=NO; SANAEI_DB_WRITES=NONE")
        return 0
    except (Hold, OSError, ValueError, KeyError, TypeError,
            sqlite3.Error, json.JSONDecodeError) as exc:
        code = str(exc)
        if not re.fullmatch("[A-Z0-9_]{1,100}", code):
            code = "KH_INVENTORY_UNTRUSTED_STATE"
        print("HOLD: " + code, file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
