#!/usr/bin/env python3
"""READ-ONLY Backhaul Sidecar activation blueprint. NEVER deploys anything.

Inputs: two independent audited snapshots, two private candidate directories,
and two private hash-only backup attestations. No shell, Docker, Nginx, service
actions, file writes or network. The output is for manual design review only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
DIR = Path(__file__).resolve().parent

def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod

gate = load("bh_plan_gate", "smite-backhaul-sidecar-preflight.py")
builder = load("bh_plan_gen", "smite-backhaul-sidecar.py")
rollback = load("bh_plan_rollback", "smite-backhaul-sidecar-rollback.py")

SOURCE = {
    "ir": {"ir.toml", "compose.candidate.yaml", "ir-control.inc",
           "ir-xhttp.inc", "NOT-INSTALLED.txt"},
    "kh": {"kh.toml", "compose.candidate.yaml", "kh-bridge.conf",
           "NOT-INSTALLED.txt"},
}
ASSIGN = {
    "ir": {
        "/etc/u-opti/backhaul-sidecar/ir.toml": "ir.toml",
        "/etc/u-opti/backhaul-sidecar/compose-ir.yml": "compose.candidate.yaml",
        "/etc/nginx/u-opti-sidecar/ir-control.inc": "ir-control.inc",
        "/etc/nginx/u-opti-sidecar/ir-xhttp.inc": "ir-xhttp.inc",
    },
    "kh": {
        "/etc/u-opti/backhaul-sidecar/kh.toml": "kh.toml",
        "/etc/u-opti/backhaul-sidecar/compose-kh.yml": "compose.candidate.yaml",
        "/etc/nginx/conf.d/u-opti-backhaul-kh-bridge.conf": "kh-bridge.conf",
    },
}
BACKUPS = {
    "ir": {
        "https_backend": "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf",
        "stream_router": "/etc/nginx/modules-enabled/99-u-opti-smite-stream.conf",
    },
    "kh": {"nginx_main": "/etc/nginx/nginx.conf"},
}
HEX = re.compile(r"[a-f0-9]{64}\Z")

class PlanBlocked(ValueError):
    pass

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def private_stage(path: Path, role: str) -> dict[str, bytes]:
    if role not in SOURCE:
        raise PlanBlocked("Unknown role")
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise PlanBlocked("Stage not a private owned real directory")
    contents = list(path.iterdir())
    if {p.name for p in contents} != SOURCE[role]:
        raise PlanBlocked("Unexpected stage file names")
    result = {}
    for item in contents:
        info = item.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_size > 64000):
            raise PlanBlocked("Unsafe candidate file")
        result[item.name] = item.read_bytes()
    return result

def validate_candidates(ir: dict[str, bytes], kh: dict[str, bytes]) -> dict:
    if set(ir) != SOURCE["ir"] or set(kh) != SOURCE["kh"]:
        raise PlanBlocked("Incomplete candidate files")
    try:
        a = tomllib.loads(ir["ir.toml"].decode("utf-8"))["server"]
        b = tomllib.loads(kh["kh.toml"].decode("utf-8"))["client"]
        x, y = ir["ir-control.inc"].decode(), ir["ir-xhttp.inc"].decode()
        z = kh["kh-bridge.conf"].decode()
        compositions = [ir["compose.candidate.yaml"].decode(),
                        kh["compose.candidate.yaml"].decode()]
    except (UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise PlanBlocked("Invalid Sidecar candidate format") from exc
    for c in (a,b):
        if (c.get("transport") != "ws" or c.get("skip_optz") is not True
                or c.get("web_port") != 0):
            raise PlanBlocked("Sidecar transport or TCP tuning not safe")
    if (a.get("bind_addr") != "127.0.0.1:3080"
            or a.get("ports") != ["127.0.0.1:56053=127.0.0.1:56053"]
            or b.get("remote_addr") != "127.0.0.1:13080"):
        raise PlanBlocked("Unexpected listener ownership")
    token = a.get("token")
    if (not isinstance(token, str) or not builder.TOKEN_PATTERN.fullmatch(token)
            or b.get("token") != token):
        raise PlanBlocked("Sidecar token mismatch")
    expected = {
        "ir_ws": (x, {"location = /channel {":1, "location ^~ /tunnel/ {":1,
                       "proxy_pass http://127.0.0.1:3080;":2}),
        "ir_xhttp": (y, {"location = /56053/www {":1,
                          "location ^~ /56053/www/ {":1,
                          "proxy_set_header Host kh.kolbe1.ir;":2}),
        "kh_bridge": (z, {"location = /channel {":1,
                          "location ^~ /tunnel/ {":1,
                          "proxy_ssl_verify on;":2,
                          "proxy_ssl_server_name on;":2,
                          "proxy_ssl_name ir.kolbe1.ir;":2,
                          "proxy_pass https://ir.kolbe1.ir:443;":2}),
    }
    for label,(raw,needles) in expected.items():
        if any(raw.count(k) != v for k,v in needles.items()):
            raise PlanBlocked("Altered Nginx candidate route: "+label)
    for role,comp in zip(("ir","kh"),compositions):
        if any(needle not in comp for needle in (
                builder.IMAGE, "network_mode: host", 'restart: "no"',
                "cap_drop: [ALL]", "create_host_path: false",
                "no-new-privileges:true", f"uopti-backhaul-sidecar-{role}")):
            raise PlanBlocked("Unsafe Compose candidate")
    return {
        role:{target:digest(source[name])
              for target,name in ASSIGN[role].items()}
        for role,source in (("ir",ir),("kh",kh))
    }

def attest(backups: object, role: str) -> list[dict]:
    """Hash-only evidence; does not constitute a real persisted backup."""
    if (not isinstance(backups,dict) or set(backups)!={"role","copies"}
            or backups["role"]!=role or not isinstance(backups["copies"],list)):
        raise PlanBlocked("Malformed role-specific backup record")
    if len(backups["copies"]) != len(BACKUPS[role]):
        raise PlanBlocked("Incomplete backup attestation")
    found={}
    for row in backups["copies"]:
        if not isinstance(row,dict) or set(row)!={
                "label","path","observed_sha256","backup_sha256",
                "verified_independently"}:
            raise PlanBlocked("Invalid backup attestation structure")
        label=row["label"]
        if (label not in BACKUPS[role] or label in found
                or row["path"] != BACKUPS[role][label]):
            raise PlanBlocked("Unexpected/duplicate backup path")
        observed, backed=row["observed_sha256"],row["backup_sha256"]
        if (not isinstance(observed,str) or not HEX.fullmatch(observed)
                or not isinstance(backed,str) or not HEX.fullmatch(backed)
                or observed!=backed or row["verified_independently"] is not True):
            raise PlanBlocked("Original/backup SHA256 mismatch or unverified backup")
        found[label]={"path":row["path"],"before_sha256":observed}
    if set(found)!=set(BACKUPS[role]):
        raise PlanBlocked("Incomplete backup path coverage")
    return [found[k] for k in BACKUPS[role]]

def plan(ir_evidence:dict,kh_evidence:dict,ir:dict[str,bytes],kh:dict[str,bytes],
         ir_backups:dict,kh_backups:dict,now:datetime|None=None)->dict:
    try:
        gate.review(ir_evidence,"ir",now=now)
        gate.review(kh_evidence,"kh",now=now)
    except (gate.PreflightRefused,gate._port.AuditError) as exc:
        raise PlanBlocked("Preflight missing, stale or conflicting") from exc
    files=validate_candidates(ir,kh)
    backups={"ir":attest(ir_backups,"ir"),"kh":attest(kh_backups,"kh")}
    for role in ("ir","kh"):
        created={p for p,t in rollback.ALLOW[role].items() if t=="create"}
        if set(files[role])!=created:
            raise PlanBlocked("Owned-file allowlist mismatch")
    return {
        "schema":1,
        "state":"REVIEW_ONLY_NO_DEPLOYMENT_AUTHORIZATION",
        "file_hashes":files,
        "original_backup_hashes":backups,
        "sidecar_container_names":rollback.CONTAINER,
        "manual_sequence":[
            "Recheck each host's live ownership and exact Nginx SNI/Canary rules immediately before any approved change",
            "Independently preserve and verify actual prior Nginx files; keep recoverable off-host backups",
            "Stage ONLY new Sidecar-owned files; never modify Smite, FRP or Xray configs",
            "Test isolated and proposed Nginx configs before any separately approved reload",
            "With separate approval, start only IR-owned Sidecar and verify loopback ownership",
            "With separate approval, add only reviewed IR HTTP routes; verify old traffic before any reload",
            "With separate approval, stage KH local TLS bridge and independent KH Sidecar",
            "Verify /channel, /tunnel/<id>, XHTTP and continued FRP/Smite/Xray service health",
            "On failure: stop only exactly owned Sidecar, verify file hashes, restore original bytes, validate Nginx and recheck existing services",
            "Keep backups and recovery journal until independent signoff",
        ],
        "unresolved_blockers":[
            "No production installer or executable host recovery exists",
            "Not tested with live IR/KH Nginx routing, ownership or certificate state",
            "Backups in this model are hash-only attestations, NOT a safe backup operation",
            "Human approval required separately before ANY host mutation/merge",
        ],
        "has_execution_actions":False,
        "authorized_for_production":False,
    }

def read_json(path:Path)->dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:
        raise PlanBlocked("Unsafe JSON evidence input")
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError,ValueError) as exc:
        raise PlanBlocked("Bad JSON evidence") from exc
    if not isinstance(value,dict):
        raise PlanBlocked("JSON object required")
    return value

def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ("ir_evidence","kh_evidence","ir_stage","kh_stage",
                  "ir_backups","kh_backups"):
        parser.add_argument("--"+field.replace("_","-"),type=Path,required=True)
    args=parser.parse_args()
    try:
        result=plan(
            read_json(args.ir_evidence),read_json(args.kh_evidence),
            private_stage(args.ir_stage,"ir"),private_stage(args.kh_stage,"kh"),
            read_json(args.ir_backups),read_json(args.kh_backups),
        )
    except (PlanBlocked,OSError,ValueError) as exc:
        parser.error("NO GO: "+type(exc).__name__)
    print(json.dumps(result,sort_keys=True,indent=2))
    print("NO HOST ACTION PERFORMED OR APPROVED",file=sys.stderr)

if __name__=="__main__":
    main()
