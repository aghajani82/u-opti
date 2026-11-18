#!/usr/bin/env python3
"""Configure a signed RC9 Backhaul pair and publish its verified XHTTP inbound."""

from contextlib import contextmanager
import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import time

from smite_xhttp_nginx_plan import PATH as XHTTP_PATH

HERE = Path(__file__).resolve().parent

# Run inside the already pinned Panel image. Reuse its database, admissions,
# signed NodeClient and compensated pair Apply. Return only public route facts.
PANEL_JOB = r'''
import asyncio
import json
import re
import secrets
import sys
import uuid
from types import SimpleNamespace

from sqlalchemy import select
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Node, Tunnel
from app.node_client import NodeClient
from app.routers.tunnels import TunnelCreate, apply_tunnel, create_tunnel
from app.uopti_backhaul_standard import compile_standard_specs

async def run(phase, port, requested_control, expected_ir, expected_kh, name):
    if (settings.smite_panel_agent_auth_mode != "signed"
            or settings.smite_engine_management_mode != "managed"):
        raise RuntimeError("SIGNED_MANAGED_PANEL_REQUIRED")
    client = NodeClient()
    async with AsyncSessionLocal() as db:
        nodes = (await db.execute(select(Node))).scalars().all()
        pair = {role: [node.id for node in nodes
                       if (node.node_metadata or {}).get("role") == role]
                for role in ("iran", "foreign")}
        if any(len(ids) != 1 for ids in pair.values()):
            raise RuntimeError("ONE_IR_AND_ONE_FOREIGN_NODE_REQUIRED")
        ir, kh = pair["iran"][0], pair["foreign"][0]
        if (expected_ir or expected_kh) and (ir, kh) != (expected_ir, expected_kh):
            raise RuntimeError("BACKHAUL_PUBLISH_PAIR_MISMATCH")
        inv = await client.get_signed_sanaei_xhttp_inbounds(kh)
        if inv.get("status") != "success" or inv.get("schema_version") != 1:
            raise RuntimeError("SIGNED_FOREIGN_XHTTP_INVENTORY_UNAVAILABLE")
        matches = [entry for entry in inv["inbounds"] if entry.get("port") == port]
        if len(matches) != 1:
            raise RuntimeError("INBOUND_PORT_NOT_IN_SIGNED_FOREIGN_INVENTORY")
        inbound = matches[0]
        if (inbound.get("enabled") is not True or inbound.get("protocol") != "vless"
                or inbound.get("network") != "xhttp" or inbound.get("listen") != "127.0.0.1"):
            raise RuntimeError("SIGNED_FOREIGN_INBOUND_NOT_ELIGIBLE")
        rows = (await db.execute(select(Tunnel).where(Tunnel.core == "backhaul"))).scalars().all()
        def slot_id(data_port):
            return uuid.uuid5(uuid.NAMESPACE_URL,
                              f"uopti-backhaul:{ir}:{kh}:{data_port}").hex

        data_ports, controls = set(), set()
        tunnel = None
        for row in rows:
            spec = row.spec
            if (row.iran_node_id != ir or row.foreign_node_id != kh
                    or not isinstance(spec, dict) or spec.get("uopti_standard_backhaul") is not True
                    or spec.get("bridge_port", 13080) != 13080):
                raise RuntimeError("BACKHAUL_TUNNEL_ALREADY_RESERVED")
            data, control = spec.get("data_port"), spec.get("control_port", 3080)
            compile_standard_specs(spec, data_port=data, control_port=control)
            if control != 3080 and not re.fullmatch(f"uopti-bh-{slot_id(data)}[.][0-9a-f]{{64}}", spec["token"]):
                raise RuntimeError("BACKHAUL_CONTROL_SLOT_TOKEN_INVALID")
            if data in data_ports or control in controls:
                raise RuntimeError("BACKHAUL_TUNNEL_PORT_COLLISION")
            data_ports.add(data)
            controls.add(control)
            if data == port:
                tunnel = row
        if data_ports & controls or port in controls:
            raise RuntimeError("BACKHAUL_TUNNEL_PORT_COLLISION")
        if tunnel and tunnel.status not in ("pending", "active"):
            raise RuntimeError("BACKHAUL_TUNNEL_ALREADY_RESERVED")
        control = tunnel.spec.get("control_port", 3080) if tunnel else (None if rows else 3080)
        slot = slot_id(port) if control != 3080 else None
        if phase == "activate" and control is None:
            if (not 1024 <= requested_control <= 65535 or requested_control in
                    data_ports | controls | {port, 3080, 7000, 8000, 8443, 8444, 8888, 13080, 18476}):
                raise RuntimeError("BACKHAUL_CONTROL_SLOT_PORT_INVALID")
            control = requested_control
        if phase == "activate" and requested_control != control:
            raise RuntimeError("BACKHAUL_CONTROL_SLOT_PORT_CHANGED")
        if phase == "activate" and (tunnel is None or tunnel.status == "pending"):
            request = SimpleNamespace()
            if tunnel is None:
                token = secrets.token_hex(32)
                if slot is not None:
                    token = f"uopti-bh-{slot}.{token}"
                spec = {"uopti_standard_backhaul": True, "transport": "ws",
                        "token": token, "data_port": port, "control_port": control,
                        "bridge_port": 13080, "ports": [f"127.0.0.1:{port}=127.0.0.1:{port}"]}
                tunnel = await create_tunnel(TunnelCreate(
                    name=name or f"Backhaul XHTTP {port}", core="backhaul", type="ws",
                    node_id=ir, iran_node_id=ir, foreign_node_id=kh, spec=spec,
                ), request, db)
                if tunnel.status != "pending":
                    raise RuntimeError("MANAGED_BACKHAUL_DRAFT_REQUIRED")
            result = await apply_tunnel(tunnel.id, request, db)
            if result.get("status") != "applied":
                raise RuntimeError("SIGNED_BACKHAUL_PAIR_APPLY_UNCONFIRMED")
            await db.refresh(tunnel)
        if tunnel and tunnel.status == "active":
            from urllib.parse import quote
            for node in (ir, kh):
                response = await client._signed_agent_request(
                    node, method="GET",
                    target="/api/agent/tunnels/status?tunnel_id=" + quote(tunnel.id, safe=""),
                    timeout=4.0)
                data = response.get("data", {})
                if (response.get("status") != "success" or data.get("active") is not True
                        or data.get("record_present") is not True or data.get("record_core") != "backhaul"
                        or data.get("type") != "backhaul"):
                    raise RuntimeError("SIGNED_BACKHAUL_PAIR_NOT_ACTIVE")
        return {"inbound": inbound, "id": tunnel.id if tunnel else None,
                "active": tunnel is not None and tunnel.status == "active",
                "slot": slot, "control_port": control,
                "reserved_ports": sorted(data_ports | controls)}

try:
    print("ROUTE_RESULT " + json.dumps(asyncio.run(run(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), *sys.argv[4:7]))))
except Exception as exc:
    import re
    reason = getattr(exc, "detail", None) or str(exc)
    print("ROUTE_HOLD " + (reason if isinstance(reason, str)
          and re.fullmatch(r"[A-Z0-9_]{1,100}", reason) else "SIGNED_PANEL_OPERATION_FAILED"))
'''


QUEUE_JOB = r'''
import asyncio
import json
import sys
from time import time

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import BackhaulPublishRequest as Job, Settings
from app.uopti_backhaul_publish import HEARTBEAT_KEY

async def run(args):
    if (settings.smite_panel_agent_auth_mode != "signed"
            or settings.smite_engine_management_mode != "managed"):
        raise RuntimeError("SIGNED_MANAGED_PANEL_REQUIRED")
    async with AsyncSessionLocal() as db:
        if args == ["check"]:
            await db.scalar(select(Job.id).limit(1))
            return None
        if args == ["claim"]:
            beat = int(time())
            stmt = insert(Settings).values(key=HEARTBEAT_KEY, value=beat)
            await db.execute(stmt.on_conflict_do_update(
                index_elements=["key"], set_={"value": beat}))
            # Host locks span claim, apply and finish. Any applying request
            # visible at the next claim belongs to an interrupted worker.
            await db.execute(update(Job).where(Job.status == "applying").values(
                status="hold", detail="BACKHAUL_PUBLISH_INTERRUPTED"))
            row = await db.scalar(select(Job).where(Job.status == "queued")
                                  .order_by(Job.created_at, Job.id).limit(1))
            if row is None:
                await db.commit()
                return None
            claim = await db.execute(update(Job).where(Job.id == row.id, Job.status == "queued")
                                     .values(status="applying"))
            if claim.rowcount != 1:
                await db.rollback()
                return None
            result = {"id": row.id, "port": row.port, "iran_node_id": row.iran_node_id,
                      "foreign_node_id": row.foreign_node_id, "name": row.name}
            await db.commit()
            return result
        action, job_id, status, path, detail = args
        if action != "finish" or status not in ("applied", "hold"):
            raise RuntimeError("INVALID_BACKHAUL_WORKER_RESULT")
        updated = await db.execute(update(Job).where(Job.id == job_id, Job.status == "applying")
                                   .values(status=status, path=path or None, detail=detail or None))
        if updated.rowcount != 1:
            await db.rollback()
            raise RuntimeError("BACKHAUL_WORKER_RESULT_UNCERTAIN")
        await db.commit()
        return None

print("QUEUE_RESULT " + json.dumps(asyncio.run(run(sys.argv[1:]))))
'''


def load(name, filename, *, executable=False):
    path = str(HERE / filename)
    loader = importlib.machinery.SourceFileLoader(name, path) if executable else None
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def need(condition, reason):
    if not condition:
        raise RuntimeError(reason)


@contextmanager
def route_lock(route):
    fd = os.open(route.LOCK_FILE, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        meta = os.fstat(fd)
        need(meta.st_uid == 0 and meta.st_nlink == 1 and stat.S_ISREG(meta.st_mode)
             and stat.S_IMODE(meta.st_mode) == 0o600, "UNTRUSTED_ROUTE_LOCK")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def panel(rt, phase, port, control=0, *, pair=("", ""), name=""):
    response = rt.run(["docker", "exec", "-i", "smite-panel", "python3", "-B", "-",
                       phase, str(port), str(control), *pair, name], input=PANEL_JOB, timeout=75)
    matches = [line for line in response.splitlines()
               if line.startswith(("ROUTE_RESULT ", "ROUTE_HOLD "))]
    need(len(matches) == 1, "SIGNED_PANEL_OPERATION_UNVERIFIED")
    status, _, payload = matches[0].partition(" ")
    need(status == "ROUTE_RESULT", payload)
    result = json.loads(payload)
    need(result["inbound"].get("port") == port and type(result["active"]) is bool
         and (result["id"] is None or re.fullmatch(r"[0-9a-f-]{36}", result["id"]))
         and (result["slot"] is None or re.fullmatch(r"[0-9a-f]{32}", result["slot"]))
         and (result["control_port"] is None or type(result["control_port"]) is int)
         and type(result["reserved_ports"]) is list
         and all(type(value) is int for value in result["reserved_ports"]),
         "SIGNED_PANEL_EVIDENCE_INVALID")
    return result


def listener(rt, port, tunnel_id):
    rows = rt.run(["ss", "-H", "-lntp", f"( sport = :{port} )"], timeout=10).splitlines()
    if tunnel_id is None:
        need(not rows, "BACKHAUL_DATA_PORT_IN_USE")
        return
    need(len(rows) == 1, "BACKHAUL_DATA_LISTENER_UNVERIFIED")
    row = rows[0].split(maxsplit=5)
    need(len(row) == 6 and row[3] == f"127.0.0.1:{port}",
         "BACKHAUL_DATA_LISTENER_UNVERIFIED")
    matches = re.findall(r'"backhaul",pid=(\d+),', row[5])
    need(len(matches) == 1, "BACKHAUL_DATA_LISTENER_UNVERIFIED")
    cmdline = (Path("/proc") / matches[0] / "cmdline").read_bytes().split(b"\0")
    need(cmdline == [b"/usr/local/bin/backhaul", b"-c",
                    f"/etc/smite-node/backhaul/{tunnel_id}.toml".encode(), b""],
         "BACKHAUL_DATA_LISTENER_UNVERIFIED")


def probe(rt, domain, port, path, public=False, *, report=False, backend=False):
    url = f"http://127.0.0.1:{port}{path}/"
    pin = []
    if public:
        url = f"https://{domain}{path}/"
        pin = (["--connect-to", f"{domain}:443:127.0.0.1:8443"] if backend
               else ["--resolve", f"{domain}:443:127.0.0.1"])
    try:
        # Go's XHTTP handler distinguishes real CORS preflight from an
        # OPTIONS uplink. Use the same upstream Host as the Nginx renderer.
        output = rt.run(["curl", "-q", "--noproxy", "*", "--http1.1",
                         "--connect-timeout", "3", "--max-time", "5",
                         "-X", "OPTIONS", "-H", f"Host: {domain}",
                         "-H", f"Origin: https://{domain}",
                         "-H", "Access-Control-Request-Method: POST",
                         "-D", "-", "-o", "/dev/null", *pin, url], timeout=7)
    except rt.Hold:
        output = ""
    lines = output.splitlines()
    status = re.match(r"HTTP/1\.[01] ([1-5][0-9]{2})(?: |$)", lines[0]) if lines else None
    code = status[1] if status else "000"
    padding = any(line.lower().startswith("x-padding:") for line in lines[1:])
    passed = code == "200" and padding
    if report and (not passed or backend):
        stage = "HTTPS_BACKEND" if backend else "HTTPS" if public else "DATA"
        print(f"BACKHAUL_{stage}_PROBE_HTTP={code}")
        print(f"BACKHAUL_{stage}_PROBE_X_PADDING={'YES' if padding else 'NO'}")
        if not backend:
            print(f"XHTTP_PATH={path}")
    return passed


def configure(edge, ingress, route, port, action, *, pair=("", ""), name=""):
    rt = edge.rt
    domain, _, _, _ = ingress.runtime_context(edge, "ir")
    if action == "apply":
        ingress.recover_control_slot(edge)
    if action != "rollback":
        ingress.run_operation(edge, "ir", "verify")
    bridge = rt.load("smite-stage15-xhttp-bridge.py")
    bridge.verify()
    route._safe_directory(route.ROUTE_DIR)
    target = route.ROUTE_DIR / f"{port}.conf"
    journal = route.ROUTE_DIR / f".{port}.transaction.json"
    saved = json.loads(ingress.read_trusted(rt, journal, 0o600)) if os.path.lexists(journal) else None
    if action == "rollback":
        need(isinstance(saved, dict) and saved.get("kind") == "backhaul", "BACKHAUL_ROUTE_JOURNAL_MISSING")
        inbound = {"path": saved.get("path")}
    else:
        result = panel(rt, "inspect", port, pair=pair)
        slots = ingress.validate_record(rt).get("slots", {})
        need(port not in slots.values(), "BACKHAUL_TUNNEL_PORT_COLLISION")
        inbound = result["inbound"]
    # The signed inventory has already validated the transport and its
    # reserved application namespaces. Recheck path syntax locally before
    # rendering; rollback only accepts its previously recorded exact bytes.
    path = inbound.get("path")
    need(isinstance(path, str) and len(path) <= 128 and XHTTP_PATH.fullmatch(path)
         and path.split("/")[1].lower() not in {"channel", "tunnel"},
         "BACKHAUL_ROUTE_RESERVED")
    snippet = ingress.render_fragment("--render-ir-xhttp", str(port), path, domain)
    record = {"state": "PREPARED", "kind": "backhaul", "port": port,
              "path": path, "snippet": snippet.decode()}
    before = route._frps_socket_inventory(allow_absent=True)
    need(port not in before[1], "FRP_DATA_PORT_IN_USE")

    if saved is not None:
        need(saved == {**record, "state": "COMMITTED"} or saved == record
             or saved == {**record, "state": "ROLLED_BACK"}, "BACKHAUL_ROUTE_JOURNAL_MISMATCH")
        if os.path.lexists(target):
            need(ingress.read_trusted(rt, target, 0o644) == snippet,
                 "BACKHAUL_ROUTE_CONFIGURATION_DRIFT")
        if saved["state"] == "COMMITTED" and action != "rollback":
            need(result["active"] and target.is_file(), "BACKHAUL_ROUTE_UNVERIFIED")
            listener(rt, port, result["id"])
            need(probe(rt, domain, port, path, public=True, report=True), "PUBLIC_XHTTP_HANDLER_UNVERIFIED")
            return "VERIFIED", path
        if action == "rollback":
            if target.exists():
                target.unlink()
                rt.fsync_dir(target.parent)
            ingress.reload_nginx(rt)
            need(route._frps_socket_inventory(allow_absent=True) == before, "FRPS_RUNTIME_CHANGED")
            ingress.replace_bytes(rt, journal, (json.dumps({**record, "state": "ROLLED_BACK"}) + "\n").encode(), 0o600)
            return "ROLLED_BACK", path
        need(saved["state"] == "ROLLED_BACK", "BACKHAUL_XHTTP_ROLLBACK_REQUIRED")
    need(action != "rollback" and not os.path.lexists(target), "BACKHAUL_ROUTE_FILE_ALREADY_EXISTS")
    active = route._run([route.BIN, "-T"])
    route.check_locations(active, path)
    need(not re.search(r"127\.0\.0\.1:" + str(port) + r"\b", active), "NGINX_DATA_PORT_IN_USE")
    listener(rt, port, result["id"] if result["active"] else None)
    if action == "plan":
        return "PLAN_READ_ONLY", path
    control = result["control_port"]
    slot = result["slot"]
    if slot is not None:
        if control is None:
            control = slots.get(slot)
        if control is None:
            reserved = (set(result["reserved_ports"]) | set(slots.values())
                        | ingress.CONTROL_RESERVED_PORTS | {port})
            for _ in range(8):
                with socket.socket() as candidate:
                    candidate.bind(("127.0.0.1", 0))
                    selected = candidate.getsockname()[1]
                if selected not in reserved:
                    control = selected
                    break
        need(type(control) is int and control != port, "BACKHAUL_CONTROL_SLOT_PORT_INVALID")
        ingress.ensure_control_slot(edge, slot, control)
        listener(rt, control, result["id"] if result["active"] else None)
    applied = panel(rt, "activate", port, control, pair=pair, name=name)
    need(applied["active"] and applied["inbound"] == result["inbound"]
         and applied["slot"] == slot and applied["control_port"] == control,
         "SIGNED_BACKHAUL_APPLY_UNVERIFIED")
    listener(rt, port, applied["id"])
    if slot is not None:
        listener(rt, control, applied["id"])
    for attempt in range(4):
        if probe(rt, domain, port, path, report=(attempt == 3)):
            break
        if attempt < 3:
            time.sleep(2)
    else:
        raise RuntimeError("BACKHAUL_END_TO_END_HANDLER_UNVERIFIED")
    need(route._frps_socket_inventory(allow_absent=True) == before, "FRPS_RUNTIME_CHANGED")
    def save(phase):
        ingress.replace_bytes(
            rt, journal, (json.dumps({**record, "state": phase}) + "\n").encode(), 0o600)
    save("PREPARED")
    ingress.replace_bytes(rt, target, snippet, 0o644, create=True)
    try:
        ingress.reload_nginx(rt)
        # Reload signals the master before new workers accept connections.
        # The old Panel may answer CORS with 200 during the handover. Only
        # commit after the public socket returns the real XHTTP marker.
        for attempt in range(5):
            if probe(rt, domain, port, path, public=True, report=(attempt == 4)):
                break
            if attempt < 4:
                time.sleep(1)
        else:
            probe(rt, domain, port, path, public=True, backend=True, report=True)
            raise RuntimeError("PUBLIC_XHTTP_HANDLER_UNVERIFIED")
        need(route._frps_socket_inventory(allow_absent=True) == before, "FRPS_RUNTIME_CHANGED")
        save("COMMITTED")
    except Exception:
        need(ingress.read_trusted(rt, target, 0o644) == snippet,
             "BACKHAUL_ROUTE_CONFIGURATION_DRIFT")
        target.unlink()
        rt.fsync_dir(target.parent)
        ingress.reload_nginx(rt)
        save("ROLLED_BACK")
        raise
    return "APPLIED", path


def queue(rt, *args):
    response = rt.run(["docker", "exec", "-i", "smite-panel", "python3", "-B", "-", *args],
                      input=QUEUE_JOB, timeout=20)
    matches = [line for line in response.splitlines() if line.startswith("QUEUE_RESULT ")]
    need(len(matches) == 1, "BACKHAUL_PANEL_QUEUE_UNAVAILABLE")
    return json.loads(matches[0].removeprefix("QUEUE_RESULT "))


def run_queue(edge, ingress, route):
    """Consume at most one web request under the same locks as the console."""
    rt = edge.rt
    # Prove the pinned owning Panel and local IR identity before trusting
    # any fields returned by the queue in that container.
    ingress.runtime_context(edge, "ir")
    job = queue(rt, "claim")
    if job is None:
        return
    need(type(job) is dict and job.keys() == {"id", "port", "iran_node_id", "foreign_node_id", "name"}
         and type(job["id"]) is str and re.fullmatch(r"[0-9a-f-]{36}", job["id"])
         and all(type(job[key]) is str and 0 < len(job[key]) <= 128
                 for key in ("iran_node_id", "foreign_node_id"))
         and type(job["name"]) is str and 1 <= len(job["name"]) <= 100 and job["name"].isprintable(),
         "BACKHAUL_PANEL_QUEUE_REQUEST_INVALID")
    try:
        validate_port(job["port"], ingress.CONTROL_RESERVED_PORTS)
        _, path = configure(edge, ingress, route, job["port"], "apply",
                            pair=(job["iran_node_id"], job["foreign_node_id"]), name=job["name"])
    except Exception as exc:
        reason = str(exc)
        reason = reason if re.fullmatch(r"[A-Z0-9_]{1,100}", reason) else "BACKHAUL_XHTTP_UNVERIFIED"
        queue(rt, "finish", job["id"], "hold", "", reason)
        print("BACKHAUL_PANEL_PUBLISH=HOLD")
    else:
        queue(rt, "finish", job["id"], "applied", path, "")
        print("BACKHAUL_PANEL_PUBLISH=APPLIED")


def panel_queue_units(ingress, rt):
    service = "u-opti-smite-backhaul-panel.service"
    timer = "u-opti-smite-backhaul-panel.timer"
    installed = Path("/usr/local/lib/u-opti/modules") / Path(__file__).name
    need(Path(__file__).resolve() == installed, "INSTALLED_BACKHAUL_WORKER_REQUIRED")
    units = {
        service: ("[Unit]\nDescription=U-OPTI Smite Backhaul publication\nAfter=docker.service nginx.service\n"
                  "[Service]\nType=oneshot\nTimeoutStartSec=240\n"
                  f"ExecStart=/usr/bin/python3 -B {installed} sync-panel\n").encode(),
        timer: ("[Unit]\nDescription=Process Smite Backhaul publication requests\n"
                "[Timer]\nOnActiveSec=2s\nOnUnitInactiveSec=10s\nAccuracySec=2s\n"
                f"Unit={service}\n[Install]\nWantedBy=timers.target\n").encode(),
    }
    directory = Path("/etc/systemd/system")
    paths = {directory / unit: contents for unit, contents in units.items()}
    for target, contents in paths.items():
        if os.path.lexists(target):
            need(ingress.read_trusted(rt, target, 0o644) == contents,
                 "BACKHAUL_PANEL_WORKER_UNIT_DRIFT")
    return timer, paths


def enable_panel_queue(edge, ingress):
    rt = edge.rt
    ingress.run_operation(edge, "ir", "verify")
    queue(rt, "check")
    timer, paths = panel_queue_units(ingress, rt)
    for target, contents in paths.items():
        if not os.path.lexists(target):
            ingress.replace_bytes(rt, target, contents, 0o644, create=True)
    rt.run(["systemctl", "daemon-reload"], timeout=15)
    rt.run(["systemctl", "enable", "--now", timer], timeout=20)
    print("BACKHAUL_PANEL_PUBLISHER=ENABLED")


def disable_panel_queue(ingress, rt):
    timer, paths = panel_queue_units(ingress, rt)
    if any(path.name == timer and path.is_file() for path in paths):
        rt.run(["systemctl", "disable", "--now", timer], timeout=20)


def validate_port(port, reserved):
    need(type(port) is int and 1024 <= port <= 65535 and port not in reserved,
         "DEDICATED_XHTTP_PORT_REQUIRED")


def main():
    import argparse

    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("action", choices=("plan", "apply", "rollback", "sync-panel", "enable-panel"))
    arg.add_argument("--port", type=int)
    args = arg.parse_args()
    try:
        need(os.geteuid() == 0, "ROOT_REQUIRED")
        if args.action in ("sync-panel", "enable-panel"):
            need(args.port is None, "BACKHAUL_PANEL_SYNC_HAS_NO_PORT_ARGUMENT")
        else:
            validate_port(args.port, {3080, 7000, 8000, 8443, 8444, 8888, 13080, 18476})
        if args.action in ("apply", "rollback", "enable-panel"):
            challenge = args.action.upper() + "-RC9-BACKHAUL-XHTTP"
            need(sys.stdin.isatty() and input(f"Type {challenge}: ").strip() == challenge,
                 "OPERATOR_CANCELLED")
        edge = load("backhaul_xhttp_edge", "smite-rc7-wss-edge.py")
        ingress = load("backhaul_xhttp_ingress", "smite-rc9-backhaul-ingress.py")
        route = load("backhaul_xhttp_route", "smite-xhttp-nginx-route", executable=True)
        edge.select_rc9()
        with edge.rt.locked(), route_lock(route):
            if args.action == "sync-panel":
                run_queue(edge, ingress, route)
                return 0
            if args.action == "enable-panel":
                enable_panel_queue(edge, ingress)
                return 0
            result, path = configure(edge, ingress, route, args.port, args.action)
        print("RC9_BACKHAUL_XHTTP=" + result)
        print("XHTTP_PATH=" + path)
        return 0
    except Exception as exc:
        reason = str(exc)
        print("HOLD: " + (reason if re.fullmatch(r"[A-Z0-9_]{1,100}", reason)
                          else "BACKHAUL_XHTTP_UNVERIFIED"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
