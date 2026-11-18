#!/usr/bin/env python3
"""Journaled RC9 Backhaul control routing over the existing HTTPS/443 edge."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
STATE = Path("/var/lib/u-opti/smite-rc9-backhaul-ingress.json")
KH_CONFIG = Path("/etc/nginx/conf.d/u-opti-smite-rc9-backhaul-bridge.conf")
HEADER = b"X-U-OPTI-RC9-Backhaul-Control"
MARKER = HEADER + b": peer-edge"
LOCATION = re.compile(rb"(?m)^\s*location\b[^\n{]*(?:/channel\b|/tunnel\b)")
ANCHOR = b"    location / {\n"
CONTROL_PATHS = ("/channel", "/tunnel/")


class Hold(Exception):
    pass


def need(condition, reason):
    if not condition:
        raise Hold(reason)


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def valid_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError) as exc:
        raise Hold("PUBLIC_PANEL_IPV4_REQUIRED") from exc
    need(address.is_global and not address.is_multicast, "PUBLIC_PANEL_IPV4_REQUIRED")
    return str(address)


def render_fragment(*args):
    result = subprocess.run(
        ["bash", str(HERE / "smite-backhaul-standard.sh"), *args],
        capture_output=True, check=True, timeout=8,
    )
    need(0 < len(result.stdout) < 16384, "BACKHAUL_RENDER_FAILED")
    return result.stdout


def render_ir(before):
    need(before.count(ANCHOR) == 1 and LOCATION.search(before) is None
         and HEADER.lower() not in before.lower(), "BACKHAUL_CONTROL_LOCATION_CONFLICT")
    control = render_fragment("--render-ir-control", "3080")
    upstream = b"        proxy_pass http://127.0.0.1:3080;\n"
    need(control.count(upstream) == 2, "BACKHAUL_CONTROL_RENDER_DRIFT")
    control = control.replace(
        upstream, upstream
        + b"        proxy_hide_header " + HEADER + b";\n"
        + b"        add_header " + HEADER + b" peer-edge always;\n",
    )
    return before.replace(ANCHOR, control + b"\n" + ANCHOR, 1)


def render_foreign(domain, upstream):
    ip = valid_ipv4(upstream)
    bridge = render_fragment("--render-kh-bridge", domain, "13080")
    # Use IPv4 for the peer-IP stream rule. Preserve hostname/SNI and validation.
    named = f"proxy_pass https://{domain}:443;".encode()
    need(bridge.count(named) == 2, "BACKHAUL_BRIDGE_RENDER_DRIFT")
    return bridge.replace(named, f"proxy_pass https://{ip}:443;".encode())


def resolve_panel(rt, domain):
    result = rt.run(["getent", "ahostsv4", domain], timeout=10)
    addresses = {valid_ipv4(line.split()[0]) for line in result.splitlines() if line.strip()}
    need(len(addresses) == 1, "ONE_PUBLIC_PANEL_IPV4_REQUIRED")
    return addresses.pop()


def read_trusted(rt, path, mode):
    info = rt.trusted_path(path)
    need(stat.S_IMODE(info.st_mode) == mode and info.st_size <= 262144,
         "BACKHAUL_INGRESS_FILE_UNTRUSTED")
    return path.read_bytes()


def validate_record(rt):
    try:
        doc = json.loads(read_trusted(rt, STATE, 0o600))
        need(isinstance(doc, dict) and doc.keys() == {
            "schema", "phase", "role", "domain", "binding", "before", "after", "upstream",
        }, "BACKHAUL_INGRESS_JOURNAL_INVALID")
        need(type(doc["schema"]) is int and doc["schema"] == 1
             and doc["phase"] in ("PREPARED", "COMMITTED")
             and doc["role"] in ("ir", "foreign")
             and all(isinstance(doc[key], str) and re.fullmatch(r"[0-9a-f]{64}", doc[key])
                     for key in ("binding", "after"))
             and isinstance(doc["domain"], str)
             and rt.p.DOMAIN.fullmatch(doc["domain"]) is not None,
             "BACKHAUL_INGRESS_JOURNAL_INVALID")
        return doc
    except (OSError, ValueError, TypeError) as exc:
        raise Hold("BACKHAUL_INGRESS_JOURNAL_INVALID") from exc


def check_ir_overlay(rt, target, edge_doc, before):
    """Called by the FRP/Stage15 verifier. Bind the exact alternate and journal."""
    journal = validate_record(rt)
    after = render_ir(before)
    require_record(journal, "ir", edge_doc["domain"], edge_doc["alternate"], before, after)
    need(journal["phase"] == "COMMITTED", "BACKHAUL_INGRESS_RECOVERY_REQUIRED")
    need(read_trusted(rt, target, 0o644) == after,
         "BACKHAUL_INGRESS_CONFIGURATION_DRIFT")


def replace_bytes(rt, path, contents, mode, *, create=False):
    rt.trusted_path(path.parent, directory=True)
    fd, name = tempfile.mkstemp(prefix=".uopti-backhaul-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        if create:
            need(not os.path.lexists(path), "BACKHAUL_INGRESS_TARGET_EXISTS")
        os.replace(temporary, path)
        rt.fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def save(rt, doc, *, create=False):
    payload = (json.dumps(doc, sort_keys=True) + "\n").encode()
    replace_bytes(rt, STATE, payload, 0o600, create=create)


def require_record(doc, role, domain, binding, before, after):
    need(doc["role"] == role and doc["domain"] == domain and doc["binding"] == binding
         and doc["before"] == (None if before is None else digest(before))
         and doc["after"] == digest(after)
         and (role != "ir" or doc["upstream"] is None),
         "BACKHAUL_INGRESS_JOURNAL_DRIFT")


def runtime_context(edge, role):
    rt = edge.rt
    values = rt.rc9_state(role)
    runtime = rt.record()
    domain = values.get("SMITE_PANEL_DOMAIN", "")
    need(rt.p.DOMAIN.fullmatch(domain) and runtime["role"] == role
         and runtime["state"] == "COMMITTED" and runtime["domain"] == domain,
         "RC9_WSS_RUNTIME_NOT_COMMITTED")
    if role == "ir":
        edge_doc = edge.journal()
        before = edge.committed_config(edge_doc)
        return domain, edge_doc["alternate"], edge.q.ALT_CANDIDATE, before
    rt.check_protected(runtime)
    rt.ensure_service("smite-node", runtime, enabled=True)
    binding = digest(read_trusted(rt, rt.STATE / "record.json", 0o600))
    return domain, binding, KH_CONFIG, None


def current_content(rt, target):
    if os.path.lexists(target):
        return read_trusted(rt, target, 0o644)
    return None


def headers(rt, path, port, *, domain=None):
    cmd = ["curl", "--noproxy", "*", "-4", "--http1.1", "-sS",
           "--connect-timeout", "3", "--max-time", "10",
           "-o", "/dev/null", "-D", "-"]
    if domain is not None:
        cmd += ["--resolve", f"{domain}:{port}:127.0.0.1",
                f"https://{domain}:{port}{path}"]
    else:
        cmd += [f"http://127.0.0.1:{port}{path}"]
    text = rt.run(cmd, timeout=12)
    lines = text.encode().splitlines()
    response = re.fullmatch(rb"HTTP/1\.[01] ([1-5][0-9]{2})(?: .*)?", lines[0]) if lines else None
    need(response is not None, "BACKHAUL_CONTROL_PROBE_INVALID")
    if port != 8443:
        need(not response[1].startswith(b"3"), "BACKHAUL_CONTROL_REDIRECT")
    return [line.lower() for line in lines if line.lower().startswith(HEADER.lower() + b":")]


def verify_live(edge, role, domain):
    rt = edge.rt
    if role == "ir":
        rt.panel_probe(domain)
        edge.alternate_probe(domain)
    for path in CONTROL_PATHS:
        answers = (headers(rt, path, 8444, domain=domain) if role == "ir"
                   else headers(rt, path, 13080))
        need(answers == [MARKER.lower()], "BACKHAUL_CONTROL_ROUTE_NOT_PROVEN")
        if role == "ir":
            need(not headers(rt, path, 8443, domain=domain),
                 "BACKHAUL_CONTROL_LEAKED_TO_DEFAULT_BACKEND")


def reload_nginx(rt):
    rt.run(["nginx", "-t"], timeout=15)
    rt.run(["systemctl", "reload", "nginx"], timeout=25)


def restore(edge, role, domain, target, before, after, journal):
    rt = edge.rt
    current = current_content(rt, target)
    need(current in (before, after), "BACKHAUL_INGRESS_CONFIGURATION_DRIFT")
    journal["phase"] = "PREPARED"
    save(rt, journal)
    if current != before:
        if before is None:
            target.unlink()
            rt.fsync_dir(target.parent)
        else:
            replace_bytes(rt, target, before, 0o644)
    reload_nginx(rt)
    if role == "ir":
        rt.panel_probe(domain)
        edge.alternate_probe(domain)
    need(current_content(rt, target) == before, "BACKHAUL_INGRESS_RESTORE_FAILED")
    STATE.unlink()
    rt.fsync_dir(STATE.parent)


def run_operation(edge, role, action):
    rt = edge.rt
    domain, binding, target, before = runtime_context(edge, role)
    journal = validate_record(rt) if os.path.lexists(STATE) else None
    if role == "ir":
        after = render_ir(before)
        upstream = None
    else:
        upstream = valid_ipv4(journal["upstream"]) if journal else resolve_panel(rt, domain)
        after = render_foreign(domain, upstream)

    current = current_content(rt, target)
    if journal:
        require_record(journal, role, domain, binding, before, after)
        if action == "rollback":
            restore(edge, role, domain, target, before, after, journal)
            return "RESTORED"
        need(journal["phase"] == "COMMITTED", "BACKHAUL_INGRESS_RECOVERY_REQUIRED")
        need(current == after, "BACKHAUL_INGRESS_CONFIGURATION_DRIFT")
        verify_live(edge, role, domain)
        return "VERIFIED"

    need(action in ("plan", "apply"), "BACKHAUL_INGRESS_NOT_INSTALLED")
    need(current == before, "BACKHAUL_INGRESS_CONFIGURATION_DRIFT")
    rt.trusted_path(target.parent, directory=True)
    if role == "foreign":
        need(not rt.run(["ss", "-H", "-lnt", "( sport = :13080 )"], timeout=10),
             "BACKHAUL_BRIDGE_PORT_IN_USE")
    rt.run(["nginx", "-t"], timeout=15)
    if action == "plan":
        return "PLAN_READ_ONLY"

    journal = {
        "schema": 1, "phase": "PREPARED", "role": role, "domain": domain,
        "binding": binding, "before": None if before is None else digest(before),
        "after": digest(after), "upstream": upstream,
    }
    save(rt, journal, create=True)
    try:
        need(current_content(rt, target) == before, "BACKHAUL_INGRESS_CONFIGURATION_DRIFT")
        replace_bytes(rt, target, after, 0o644, create=(before is None))
        reload_nginx(rt)
        verify_live(edge, role, domain)
        need(current_content(rt, target) == after, "BACKHAUL_INGRESS_CONFIGURATION_DRIFT")
        journal["phase"] = "COMMITTED"
        save(rt, journal)
    except Exception as exc:
        try:
            restore(edge, role, domain, target, before, after, journal)
        except Exception as recovery:
            raise Hold("BACKHAUL_INGRESS_RECOVERY_REQUIRED") from recovery
        raise Hold("BACKHAUL_INGRESS_APPLY_FAILED_RESTORED") from exc
    return "APPLIED"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "verify", "rollback"))
    parser.add_argument("--role", required=True, choices=("ir", "foreign"))
    args = parser.parse_args()
    try:
        need(os.geteuid() == 0, "ROOT_REQUIRED")
        if args.action in ("apply", "rollback"):
            challenge = f"{args.action.upper()}-RC9-BACKHAUL-INGRESS-{args.role.upper()}"
            need(sys.stdin.isatty() and input("Type " + challenge + ": ").strip() == challenge,
                 "OPERATOR_CANCELLED")
        # Lazy imports so an edge verifier can load the renderer without
        # recursively loading the edge/Backhaul runtime validators.
        path = HERE / "smite-rc7-wss-edge.py"
        spec = importlib.util.spec_from_file_location("rc9_backhaul_edge", path)
        edge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(edge)
        edge.select_rc9()
        if args.action == "apply":
            control = edge.rt.load("smite-managed-backhaul-control.py")
            control._verify_bundled_backhaul(args.role, rc9=True, expected_backhaul_state="ready")
        with edge.rt.locked():
            result = run_operation(edge, args.role, args.action)
        print("RC9_BACKHAUL_CONTROL_" + args.role.upper() + "=" + result)
        print("BACKHAUL_XHTTP_PUBLISHED=NO")
        return 0
    except Exception as exc:
        reason = str(exc)
        print("HOLD: " + (reason if re.fullmatch(r"[A-Z0-9_]{1,100}", reason)
                          else "BACKHAUL_INGRESS_UNVERIFIED"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
