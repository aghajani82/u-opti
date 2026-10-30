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
    '      SMITE_SANAEI_DB_PATH: "/run/smite-sanaei-ro/x-ui.db"\n'
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

def baseline(before):
    need(before["image"] == EXPECTED_IMAGE
         and before["env"].get("SMITE_SANAEI_INVENTORY_ENABLED") == "false"
         and before["env"].get("SMITE_SANAEI_DB_PATH", TARGET + "/x-ui.db") == TARGET + "/x-ui.db",
         "INVENTORY_BASELINE_DRIFT")
    old_mount = [item for item in before["mounts"] if item["Destination"] == TARGET]
    need(len(old_mount) <= 1, "INVENTORY_MOUNT_DUPLICATED")
    if old_mount:
        need(old_mount[0]["Type"] == "bind" and old_mount[0]["RW"] is False
             and old_mount[0]["Source"] == "/opt/smite-node/.sanaei-empty",
             "INVENTORY_MOUNT_BASELINE_DRIFT")
    return old_mount[0] if old_mount else None


def admit_after(before, observed):
    """Prove *every* actual Docker field: only reviewed env/bind delta allowed.

    Docker Compose can represent new long bind syntax in HostConfig.Mounts
    rather than Binds. Never predict unknown Docker-generated host fields.
    Bind the verified observed signature only at successful COMMIT.
    """
    previous = baseline(before)
    need(set(observed) == set(before) and observed["image"] == EXPECTED_IMAGE
         and observed["command"] == before["command"],
         "INVENTORY_UNREVIEWED_NODE_CHANGE")
    normalized = copy.deepcopy(observed)
    env = normalized["env"]
    need(env.get("SMITE_SANAEI_INVENTORY_ENABLED") == "true"
         and env.get("SMITE_SANAEI_DB_PATH") == TARGET + "/x-ui.db",
         "INVENTORY_NEW_ENV_UNTRUSTED")
    env["SMITE_SANAEI_INVENTORY_ENABLED"] = "false"
    if "SMITE_SANAEI_DB_PATH" not in before["env"]:
        env.pop("SMITE_SANAEI_DB_PATH")
    need(env == before["env"], "INVENTORY_EXTRA_ENV_DELTA")
    new_mount = [item for item in normalized["mounts"]
                 if item["Destination"] == TARGET]
    need(len(new_mount) == 1 and new_mount[0]["Type"] == "bind"
         and new_mount[0]["Source"] == str(DB_DIR)
         and new_mount[0]["RW"] is False
         and new_mount[0].get("Propagation") in ("rprivate", ""),
         "INVENTORY_NEW_MOUNT_UNTRUSTED")
    if previous:
        replacement = copy.deepcopy(new_mount[0])
        replacement["Source"] = previous["Source"]
        need(replacement == previous, "INVENTORY_MOUNT_ATTRIBUTES_CHANGED")
        normalized["mounts"][normalized["mounts"].index(new_mount[0])] = replacement
    else:
        need(new_mount[0].get("Mode") in ("ro", ""),
             "INVENTORY_MOUNT_MODE_UNTRUSTED")
        normalized["mounts"].remove(new_mount[0])
    need(normalized["mounts"] == before["mounts"],
         "INVENTORY_EXISTING_MOUNTS_CHANGED")

    # Docker may move a short-syntax *old* bind to structured Mounts when
    # the new overlay uses long syntax. Normalize across BOTH collections.
    old_host = before["host"]
    new_host = normalized["host"]
    old_hits = []
    new_hits = []
    for key in ("Binds", "Mounts"):
        previous_values = old_host.get(key)
        current_values = new_host.get(key)
        need(previous_values is None or isinstance(previous_values, list),
             "INVENTORY_OLD_HOST_FORMAT")
        need(current_values is None or isinstance(current_values, list),
             "INVENTORY_NEW_HOST_FORMAT")
        for i, item in enumerate(previous_values or []):
            if key == "Binds":
                need(isinstance(item, str), "INVENTORY_OLD_BIND_INVALID")
                if ":" + TARGET + ":" in item:
                    need(item == "/opt/smite-node/.sanaei-empty:" + TARGET + ":ro",
                         "INVENTORY_OLD_BIND_UNTRUSTED")
                    old_hits.append((key, i, item))
            elif isinstance(item, dict):
                if item.get("Target", item.get("Destination")) == TARGET:
                    need(item.get("Type") == "bind"
                         and item.get("Source") == "/opt/smite-node/.sanaei-empty"
                         and item.get("ReadOnly") is True,
                         "INVENTORY_OLD_STRUCTURED_BIND_UNTRUSTED")
                    old_hits.append((key, i, item))
        for i, item in enumerate(current_values or []):
            if key == "Binds":
                need(isinstance(item, str), "INVENTORY_NEW_BIND_INVALID")
                if ":" + TARGET + ":" in item:
                    need(item == str(DB_DIR) + ":" + TARGET + ":ro",
                         "INVENTORY_UNSAFE_BIND_OPTIONS")
                    new_hits.append((key, i, item))
            elif isinstance(item, dict):
                if item.get("Target", item.get("Destination")) == TARGET:
                    need(item.get("Type") == "bind"
                         and item.get("Source") == str(DB_DIR)
                         and item.get("ReadOnly") is True
                         and not item.get("BindOptions", {}).get("CreateMountpoint", False),
                         "INVENTORY_HOST_BIND_UNTRUSTED")
                    new_hits.append((key, i, item))
    need(len(old_hits) == (1 if previous else 0) and len(new_hits) == 1,
         "INVENTORY_HOST_BIND_COUNT_DRIFT")
    key, i, _ = new_hits[0]
    new_host[key].pop(i)
    if old_hits:
        key, i, item = old_hits[0]
        if new_host.get(key) is None:
            new_host[key] = []
        new_host[key].insert(i, copy.deepcopy(item))
    for key in ("Binds", "Mounts"):
        if old_host.get(key) is None and new_host.get(key) == []:
            if key in old_host:
                new_host[key] = None
            else:
                new_host.pop(key, None)
    need(new_host == old_host, "INVENTORY_HOST_BIND_OTHER_CHANGE")
    need(normalized == before, "INVENTORY_UNRELATED_RUNTIME_DRIFT")
    return observed


def validate_compose():
    before = json.loads(h.run(w.compose("node", True, ["config", "--format", "json"])))
    after = json.loads(h.run(
        w.compose("node", True, ["-f", "-", "config", "--format", "json"]),
        input=OVERLAY_BYTES.decode()))
    old = before["services"]["smite-node"]
    a = copy.deepcopy(after)
    new = a["services"]["smite-node"]
    old_env = old["environment"]
    new_env = new["environment"]
    need(old_env.get("SMITE_SANAEI_INVENTORY_ENABLED") == "false"
         and old_env.get("SMITE_SANAEI_DB_PATH", TARGET + "/x-ui.db") == TARGET + "/x-ui.db"
         and new_env.get("SMITE_SANAEI_INVENTORY_ENABLED") == "true"
         and new_env.get("SMITE_SANAEI_DB_PATH") == TARGET + "/x-ui.db",
         "INVENTORY_COMPOSE_ENV_UNTRUSTED")
    new_env["SMITE_SANAEI_INVENTORY_ENABLED"] = "false"
    if "SMITE_SANAEI_DB_PATH" not in old_env:
        new_env.pop("SMITE_SANAEI_DB_PATH")
    old_vol = old["volumes"]
    new_vol = new["volumes"]
    need(isinstance(old_vol, list) and isinstance(new_vol, list),
         "INVENTORY_COMPOSE_MOUNTS_MISSING")
    old_target = [v for v in old_vol if v.get("target") == TARGET]
    new_target = [v for v in new_vol if v.get("target") == TARGET]
    need(len(old_target) <= 1 and len(new_target) == 1
         and new_target[0].get("source") == str(DB_DIR)
         and new_target[0].get("type") == "bind"
         and new_target[0].get("read_only") is True
         and new_target[0].get("bind", {}).get("create_host_path") is False,
         "INVENTORY_COMPOSE_BIND_UNTRUSTED")
    index = new_vol.index(new_target[0])
    if old_target:
        need(len(old_vol) == len(new_vol)
             and old_target[0].get("source") == "/opt/smite-node/.sanaei-empty"
             and old_target[0].get("read_only") is True,
             "INVENTORY_COMPOSE_OLD_MOUNT_DRIFT")
        new_vol[index] = copy.deepcopy(old_target[0])
    else:
        need(len(new_vol) == len(old_vol) + 1,
             "INVENTORY_UNEXPECTED_EXTRA_MOUNTS")
        new_vol.pop(index)
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
         and (doc["after"] is None or
              admit_after(doc["before"], doc["after"]) == doc["after"])
         and (doc["phase"] != "COMMITTED" or doc["after"] is not None),
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
    actual = w.signature(obj)
    if after:
        admit_after(doc["before"], actual)
        if doc["after"] is not None:
            need(actual == doc["after"], "KH_MIGRATED_RUNTIME_DRIFT")
    else:
        need(actual == doc["before"], "KH_NODE_RUNTIME_SIGNATURE_DRIFT")
    need(h.run(["docker", "image", "inspect", "smite-node:stage15-local",
                "--format", "{{.Id}}"]) == EXPECTED_IMAGE,
         "KH_IMAGE_TAG_DRIFT")
    return actual

def signed_inbounds():
    # Exercises the real loopback signed HTTP endpoint AND durable replay.
    response = h.run(["docker", "exec", "-w", "/app", "smite-node",
                      "python3", "-c", SIGNED_PROBE], timeout=35)
    need(response == "SIGNED_KH_INVENTORY=45121:/45121/www;REPLAY=DENIED",
         "SIGNED_KH_INVENTORY_UNAVAILABLE")

def plan():
    need(not exists(STATE) and not exists(STATE.with_name(STATE.name + ".stage")),
         "EXISTING_KH_INVENTORY_TRANSACTION")
    need(not exists(OVERLAY) and not exists(OVERLAY.with_name(OVERLAY.name + ".next")),
         "INVENTORY_OVERLAY_ALREADY_EXISTS")
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
                after=None, frpc=probe,
                overlay_sha=digest(OVERLAY_BYTES))

def begin(doc):
    # Atomic publication: a killed preparation never exposes half a receipt.
    stage = STATE.with_name(STATE.name + ".stage")
    h.new_dir(stage)
    h.new_file(stage / "record.json", canonical(doc), 0o600)
    os.replace(stage, STATE)
    h.flush(STATE.parent)

def publish_overlay():
    # fsync then rename; SIGKILL cannot expose a truncated active overlay.
    pending = OVERLAY.with_name(OVERLAY.name + ".next")
    need(not exists(pending) and not exists(OVERLAY),
         "UNEXPECTED_INVENTORY_OVERLAY")
    h.new_file(pending, OVERLAY_BYTES, 0o600)
    os.replace(pending, OVERLAY)
    h.flush(OVERLAY.parent)

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
    publish_overlay()
    doc["phase"] = "RECREATING"
    save(doc)
    recreate(True)  # only smite-node: one short FRPC interruption
    candidate = verify_runtime(doc, True)
    need(frpc() == doc["frpc"], "FRPC_COMMAND_OR_NAMESPACE_DRIFT")
    signed_inbounds()
    need(w.protected(["node"]) == doc["protected"], "SIGNED_STORAGE_DRIFT")
    doc["after"] = candidate
    doc["phase"] = "COMMITTED"
    save(doc)
    w.health(w.read_record(), True)

def rollback():
    doc = record()
    need(doc["phase"] in PHASES, "INVENTORY_UNKNOWN_STATE")
    pending = OVERLAY.with_name(OVERLAY.name + ".next")
    if exists(pending):
        need(doc["phase"] == "PREPARED", "UNRESOLVED_OVERLAY_WRITE")
        raw = h.file(pending, mode=0o600, limit=len(OVERLAY_BYTES))
        need(OVERLAY_BYTES.startswith(raw), "UNTRUSTED_OVERLAY_PARTIAL")
        pending.unlink()
        h.flush(pending.parent)
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
        if current != doc["before"]:
            admit_after(doc["before"], current)
            if doc["after"] is not None:
                need(current == doc["after"], "KH_RUNTIME_EXTERNAL_DRIFT")
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
