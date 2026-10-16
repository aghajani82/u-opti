#!/usr/bin/env python3
"""OFFLINE reconciliation of two private Backhaul candidate bundles.

This module reads private staged files only. It has no deployment action.
It proves that the Sidecar config and Nginx merge proposal describe the SAME
role, domains and exact bytes, including KH's public port-13080 denial.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tomllib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


sidecar = _load("reconcile_sidecar", "smite-backhaul-sidecar.py")
nginx = _load("reconcile_nginx", "smite-backhaul-sidecar-nginx-plan.py")

LAYOUT = {
    "ir": {
        "/etc/u-opti/backhaul-sidecar/ir.toml": ("create", "ir.toml", "sidecar"),
        "/etc/u-opti/backhaul-sidecar/compose-ir.yml": ("create", "compose.candidate.yaml", "sidecar"),
        nginx.IR_CONTROL: ("create", "ir-control.inc", "nginx"),
        nginx.IR_XHTTP: ("create", "ir-xhttp.inc", "nginx"),
        nginx.IR_PATH: ("edit", "patched.conf", "nginx"),
    },
    "kh": {
        "/etc/u-opti/backhaul-sidecar/kh.toml": ("create", "kh.toml", "sidecar"),
        "/etc/u-opti/backhaul-sidecar/compose-kh.yml": ("create", "compose.candidate.yaml", "sidecar"),
        nginx.KH_BRIDGE: ("create", "kh-bridge.conf", "nginx"),
        nginx.KH_PATH: ("edit", "patched.conf", "nginx"),
    },
}
SIDECAR_NAMES = {
    "ir": {"ir.toml", "compose.candidate.yaml", "ir-control.inc",
           "ir-xhttp.inc", "NOT-INSTALLED.txt"},
    "kh": {"kh.toml", "compose.candidate.yaml", "kh-bridge.conf",
           "NOT-INSTALLED.txt"},
}
NGINX_NAMES = {
    "ir": {"original.conf", "patched.conf", "ir-control.inc",
           "ir-xhttp.inc", "plan.json", "NOT-INSTALLED.txt"},
    "kh": {"original.conf", "patched.conf", "kh-bridge.conf",
           "plan.json", "NOT-INSTALLED.txt"},
}
HEX = re.compile(r"[a-f0-9]{64}\Z")


class ReconcileRefused(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_files(directory: Path, names: set[str], prefix: str) -> dict[str, bytes]:
    directory = Path(directory)
    info = directory.lstat()
    if (directory.parent != Path("/tmp") or not directory.name.startswith(prefix)
            or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ReconcileRefused("Expected private direct-child /tmp candidate directory")
    items = list(directory.iterdir())
    if {p.name for p in items} != names:
        raise ReconcileRefused("Candidate has unknown, missing or duplicate filenames")
    out = {}
    for p in items:
        fi = p.lstat()
        if (not stat.S_ISREG(fi.st_mode) or fi.st_uid != os.getuid()
                or stat.S_IMODE(fi.st_mode) & 0o077 or fi.st_size > 128_000):
            raise ReconcileRefused("Candidate file is linked, public or oversized")
        out[p.name] = p.read_bytes()
    return out


def _strict_plan(raw: bytes, role: str, ir_domain: str, kh_host: str,
                 original: bytes, patched: bytes, additions: dict[str, bytes],
                 data_port: int = 56053, xhttp_path: str = "/56053/www") -> None:
    try:
        meta = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ReconcileRefused("Nginx manifest cannot be decoded") from exc
    base_fields = {"version", "role", "status", "domain", "kh_host",
                   "nginx_edit", "new_files", "notes"}
    expected_fields = (base_fields if data_port == 56053 and
                       xhttp_path == "/56053/www" else base_fields | {"profile"})
    if not isinstance(meta, dict) or set(meta) != expected_fields:
        raise ReconcileRefused("Unexpected Nginx manifest schema")
    if "profile" in meta and meta["profile"] != {
        "data_port": data_port, "xhttp_path": xhttp_path
    }:
        raise ReconcileRefused("Custom XHTTP profile mismatch")
    if (meta["version"] != 1 or meta["role"] != role
            or meta["status"] != "REVIEW_ONLY_NO_DEPLOYMENT"
            or meta["domain"] != ir_domain or meta["kh_host"] != kh_host
            or not isinstance(meta["notes"], list)):
        raise ReconcileRefused("Nginx manifest identity or mode mismatch")
    vhost = nginx.IR_PATH if role == "ir" else nginx.kh_vhost_path(kh_host)
    edit = meta["nginx_edit"]
    if not isinstance(edit, dict) or edit != {
        "path": vhost, "original_sha256": sha(original),
        "patched_sha256": sha(patched),
        "backup": "original.conf", "candidate": "patched.conf",
        "action": "replace-only-if-original-sha-matches"
    }:
        raise ReconcileRefused("Nginx vhost hash or backup manifest mismatch")
    expected = {
        path: {"path": path, "candidate": (
            "ir-control.inc" if path == nginx.IR_CONTROL else
            "ir-xhttp.inc" if path == nginx.IR_XHTTP else "kh-bridge.conf"
        ), "action": "create-if-absent", "sha256": sha(value)}
        for path, value in additions.items()
    }
    rows = meta["new_files"]
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or any(not isinstance(r, dict) for r in rows)):
        raise ReconcileRefused("Nginx proposed resource set incomplete")
    found = {}
    for row in rows:
        path = row.get("path")
        if path not in expected or path in found or row != expected[path]:
            raise ReconcileRefused("Nginx proposed path or hash drift")
        found[path] = row
    if set(found) != set(expected):
        raise ReconcileRefused("Nginx bridge or IR include missing")


def reconcile(role: str, sidecar_dir: Path, nginx_dir: Path) -> list[dict]:
    """Return precise synthetic transaction resources; never write to the host.

    Each item has {"path", "operation", "before", "after"}. Secret-bearing
    before/after BYTES are only kept in-process; callers must not log them.
    """
    if role not in LAYOUT:
        raise ReconcileRefused("Unsupported Sidecar role")
    a = private_files(sidecar_dir, SIDECAR_NAMES[role], "uopti-backhaul-sidecar-")
    b = private_files(nginx_dir, NGINX_NAMES[role], "uopti-bh-nginx-plan-")
    try:
        config = tomllib.loads(a[f"{role}.toml"].decode("utf-8"))
        item = config["server"] if role == "ir" else config["client"]
        token = item["token"]
        if not isinstance(token, str) or not sidecar.TOKEN_PATTERN.fullmatch(token):
            raise ReconcileRefused("Private token schema invalid")
        meta = json.loads(b["plan.json"].decode("utf-8"))
        ir_domain = meta["domain"]
        kh_host = meta["kh_host"]
        selected = meta.get("profile", {"data_port": 56053, "xhttp_path": "/56053/www"})
        if not isinstance(selected, dict) or set(selected) != {"data_port", "xhttp_path"}:
            raise ReconcileRefused("Invalid XHTTP profile schema")
        data_port, xhttp_path = sidecar.validated_profile(
            selected["data_port"], selected["xhttp_path"])
        expected_sidecar = sidecar.candidate_files(
            role, token, ir_domain, kh_host, data_port, xhttp_path)
        compiled, additions, vhost = nginx.compile_nginx(
            role, b["original.conf"], ir_domain, kh_host, data_port, xhttp_path)
    except (UnicodeError, KeyError, TypeError, ValueError, IndexError) as exc:
        raise ReconcileRefused("Unable to verify paired candidate semantics") from exc
    if set(a) != set(expected_sidecar) or any(
        a[name] != expected.encode("utf-8")
        for name, expected in expected_sidecar.items()
    ):
        raise ReconcileRefused("Sidecar token, upstream or generated bytes mismatch")
    layout = (LAYOUT[role] if role == "ir" else {
        (nginx.kh_vhost_path(kh_host) if path == nginx.KH_PATH else path): spec
        for path, spec in LAYOUT["kh"].items()
    })
    if compiled != b["patched.conf"]:
        raise ReconcileRefused("Nginx patched file differs from exact compiler output")
    for path, contents in additions.items():
        name = next((n for p, (_, n, source) in layout.items()
                     if source == "nginx" and p == path), None)
        if name is None or b[name] != contents:
            raise ReconcileRefused("Sidecar route or KH public forwarding guard mismatched")
        if name in a and a[name] != b[name]:
            raise ReconcileRefused("Two candidate renderers produced different Nginx routes")
    if vhost != (nginx.IR_PATH if role == "ir" else nginx.kh_vhost_path(kh_host)):
        raise ReconcileRefused("Unexpected Nginx edit destination")
    _strict_plan(b["plan.json"], role, ir_domain, kh_host,
                 b["original.conf"], compiled, additions, data_port, xhttp_path)
    resources = []
    for path, (action, name, source) in layout.items():
        payload = (a if source == "sidecar" else b)[name]
        resources.append({
            "path": path, "operation": action,
            "before": b["original.conf"] if action == "edit" else None,
            "after": payload,
        })
    return resources


if __name__ == "__main__":
    raise SystemExit("This review-only helper is imported by offline tests; no live CLI.")
