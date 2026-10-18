#!/usr/bin/env python3
"""Smite Stage 13: READ-ONLY pre-activation inventory for IR and KH.

This tool cannot approve deployment. Even all locally provable checks PASS
cannot attest a Hetzner snapshot, running image digest, effective Nginx
config, certificate path, proxy semantics or actual tunnel traffic.
It never uses Docker, shell, Nginx reload, network, env secret dumps or writes.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

UUID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")
SECRET = re.compile(r"[a-f0-9]{64}\Z")
IMAGE_REF = re.compile(r"[A-Za-z0-9._/:@-]+@sha256:[0-9a-f]{64}\Z")
SNAPSHOT = re.compile(r"[A-Za-z0-9._:-]{4,120}\Z")

@dataclass(frozen=True)
class Paths:
    state: Path = Path("/etc/u-opti/smite/state.env")
    identity: Path = Path("/etc/u-opti/smite/identities/node-identity.json")
    node_compose: Path = Path("/opt/smite-node/docker-compose.yml")
    node_candidate: Path = Path("/opt/smite-node/docker-compose.security-candidate.yml")
    replay_dir: Path = Path("/var/lib/u-opti/smite-node-security/replay")
    image_lock: Path = Path("/etc/u-opti/smite/security-image-lock.json")
    snapshot_receipt: Path = Path("/etc/u-opti/smite/snapshot-receipt.json")
    panel_compose: Path = Path("/opt/smite/docker-compose.yml")
    approved_origins: Path = Path("/etc/smite-panel/trusted-nodes/approved-origins.json")
    nginx_vhost: Path = Path("/etc/nginx/sites-enabled/smite-secure-gateway")
    panel_app: Path = Path("/var/lib/u-opti/smite-stage13/panel-app")
    node_app: Path = Path("/var/lib/u-opti/smite-stage13/node-app")
    overlays: Path = Path("/opt/u-opti-smite")


class AuditHold(Exception):
    pass


def _read(path: Path, *, max_bytes: int = 128_000, private: bool = False) -> bytes:
    try:
        # No following symlinks, including last path element.
        entry = path.lstat()
        if (not stat.S_ISREG(entry.st_mode) or entry.st_size > max_bytes or
            (private and (entry.st_uid != os.geteuid() or
                          stat.S_IMODE(entry.st_mode) != 0o600))):
            raise AuditHold("unsafe_file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as fh:
            again = os.fstat(fh.fileno())
            if (not stat.S_ISREG(again.st_mode) or again.st_size > max_bytes or
                (private and (again.st_uid != os.geteuid() or
                              stat.S_IMODE(again.st_mode) != 0o600))):
                raise AuditHold("unsafe_file")
            body = fh.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise AuditHold("oversized_file")
            return body
    except (OSError, ValueError) as exc:
        raise AuditHold("missing_or_unsafe_file") from exc


def _private_dir(path: Path) -> None:
    try:
        entry = path.lstat()
        if (not stat.S_ISDIR(entry.st_mode) or
            entry.st_uid != os.geteuid() or
            stat.S_IMODE(entry.st_mode) != 0o700):
            raise AuditHold("unsafe_private_directory")
    except OSError as exc:
        raise AuditHold("missing_private_directory") from exc


def _json(path: Path, *, private: bool = True) -> dict:
    if private:
        _private_dir(path.parent)
    try:
        value = json.loads(_read(path, private=private))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise AuditHold("invalid_json") from exc
    if not isinstance(value, dict):
        raise AuditHold("invalid_json_object")
    return value


def _ok_state(role: str, p: Paths) -> None:
    txt = _read(p.state, max_bytes=16_384).decode("utf-8")
    entries = dict(line.split("=", 1) for line in txt.splitlines()
                   if line.startswith(("SMITE_ROLE=", "SMITE_CONNECTION_MODE=")))
    expected_role = "panel-iran" if role == "ir" else "foreign"
    if entries.get("SMITE_ROLE") != expected_role or entries.get("SMITE_CONNECTION_MODE") != "standard":
        raise AuditHold("role_or_mode_mismatch")


def _ok_identity(p: Paths) -> None:
    obj = _json(p.identity)
    if (not isinstance(obj.get("node_id"), str) or
        not UUID.fullmatch(obj["node_id"]) or
        not isinstance(obj.get("node_secret"), str) or
        not SECRET.fullmatch(obj["node_secret"])):
        raise AuditHold("unpaired_or_malformed_identity")


def _ok_compose(p: Paths) -> None:
    base = _read(p.node_compose).decode("utf-8")
    if (base.count("\n  smite-node:\n") != 1 or
        "network_mode: host" not in base or
        not re.search(r'command: \["uvicorn", "main:app", "--host", "127\.0\.0\.1", "--port", "8888"', base)):
        raise AuditHold("unapproved_node_compose")
    staged = _read(p.node_candidate, private=True).decode("utf-8")
    needed = (
        "STAGE9 CANDIDATE - INERT",
        "SMITE_AGENT_AUTH_MODE: strict",
        "SMITE_NODE_PANEL_AUTH_MODE: signed",
        ":/run/smite-node-identity:ro",
        ":/var/lib/smite-node/auth:rw",
        "http://127.0.0.1:8888/",
    )
    if any(x not in staged for x in needed) or "docker compose up" in staged:
        raise AuditHold("incomplete_or_unsafe_candidate")
    if "http://127.0.0.1:8888/api/agent/status" in staged:
        raise AuditHold("unsigned_healthcheck")


def _ok_replay(p: Paths) -> None:
    _private_dir(p.replay_dir)
    db = p.replay_dir / "agent-replay.sqlite3"
    if db.exists() or db.is_symlink():
        entry = db.lstat()
        if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.geteuid()
            or stat.S_IMODE(entry.st_mode) != 0o600):
            raise AuditHold("untrusted_replay_database")


def _ok_image_lock(p: Paths) -> None:
    doc = _json(p.image_lock)
    if doc.get("version") != 1 or not isinstance(doc.get("images"), dict):
        raise AuditHold("image_lock_schema")
    for name in ("panel", "node"):
        ref = doc["images"].get(name)
        if not isinstance(ref, str) or not IMAGE_REF.fullmatch(ref):
            raise AuditHold("untrusted_image_reference")
    if doc["images"]["panel"] == doc["images"]["node"]:
        raise AuditHold("image_pair_not_distinct")


def _ok_snapshot_receipt(p: Paths) -> None:
    doc = _json(p.snapshot_receipt)
    if doc.get("version") != 1 or not isinstance(doc.get("snapshots"), dict):
        raise AuditHold("snapshot_receipt_missing")
    for role in ("ir", "kh"):
        value = doc["snapshots"].get(role)
        if not isinstance(value, str) or not SNAPSHOT.fullmatch(value):
            raise AuditHold("missing_two_host_snapshot_reference")
    if not isinstance(doc.get("rollback_steps_reviewed"), bool) or not doc["rollback_steps_reviewed"]:
        raise AuditHold("rollback_steps_not_reviewed")


def _ok_nginx(role: str, p: Paths) -> None:
    # This is SOURCE text only, not nginx -T's effective merged vhosts.
    txt = _read(p.nginx_vhost).decode("utf-8")
    if not re.search(r"\blisten\s+(?:\S+:)?443\b[^;]*;", txt):
        raise AuditHold("no_tls_443_vhost")
    if role == "kh":
        if (txt.count("location ^~ /api/agent/ {") != 1 or
            txt.count("proxy_pass http://127.0.0.1:8888;") != 1 or
            "deny all;" not in txt or
            not re.search(r"\ballow\s+[0-9a-fA-F.:]+\s*;", txt) or
            "proxy_pass http://127.0.0.1:8888/;" in txt):
            raise AuditHold("signed_agent_target_or_acl_unverified")
    else:
        if (txt.count("location ^~ /api/node-control/ {") != 1 or
            "proxy_pass http://127.0.0.1:8000;" not in txt or
            "proxy_pass http://127.0.0.1:8000/;" in txt):
            raise AuditHold("signed_registration_target_unverified")


def _ok_approved_origins(role: str, p: Paths) -> None:
    if role != "ir":
        return
    doc = _json(p.approved_origins)
    nodes = doc.get("nodes")
    if doc.get("version") != 1 or not isinstance(nodes, dict) or not nodes:
        raise AuditHold("admin_origin_approvals_missing")
    approved_roles = set()
    for uid, pin in nodes.items():
        if not UUID.fullmatch(uid) or not isinstance(pin, dict):
            raise AuditHold("bad_approved_identity")
        if pin.get("role") not in ("iran", "foreign"):
            raise AuditHold("bad_approved_role")
        if not isinstance(pin.get("origin"), str) or not isinstance(pin.get("control_url"), str):
            raise AuditHold("bad_approved_origin")
        if pin["role"] == "foreign":
            if not re.fullmatch(r"https://[a-z0-9.-]+:443", pin["origin"]):
                raise AuditHold("unverified_foreign_tls_origin")
        approved_roles.add(pin["role"])
    if "foreign" not in approved_roles:
        raise AuditHold("no_approved_foreign_node")


def _ok_overlay_parity(p: Paths) -> None:
    """Reuse Stage10's real source-vs-host shadow auditor, fail closed.

    Requires independently extracted reviewed Panel+Node /app trees.
    Status is still only local byte parity, not a Docker image attestation.
    """
    path = Path(__file__).with_name("smite-auth-image-overlay-audit.py")
    spec = importlib.util.spec_from_file_location("smite_stage10_source_audit", path)
    if spec is None or spec.loader is None:
        raise AuditHold("source_auditor_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.assess(
        panel_root=p.panel_app, node_root=p.node_app,
        overlay_root=p.overlays, panel_compose=p.panel_compose,
        node_compose=p.node_compose,
    )
    result = dict(rows)
    if (
        any(value.startswith("HOLD_") for _, value in rows)
        or not all(
            result.get(f"IMAGE/{service}/{filename}") == "SOURCE_PRESENT"
            for service, filenames in module.REQUIRED_MODULES.items()
            for filename in filenames
        )
        or result.get("COMPOSE/panel") != "SOURCE_PRESENT"
        or result.get("COMPOSE/node") != "SOURCE_PRESENT"
        or any(
            result.get(f"OVERLAY/{role}/{name}") not in (
                "BYTE_IDENTICAL_SHADOW", "NO_HOST_SHADOW"
            )
            for role, name in module.SHADOWS
        )
    ):
        raise AuditHold("security_image_overlay_parity_missing")


def audit(role: str, p: Paths) -> list[tuple[str, str]]:
    if role not in ("ir", "kh"):
        raise ValueError("IR or KH role required")
    checks = [
        ("STANDARD_ROLE", lambda: _ok_state(role, p)),
        ("PAIRED_NODE_IDENTITY", lambda: _ok_identity(p)),
        ("NODE_COMPOSE_AND_INERT_CANDIDATE", lambda: _ok_compose(p)),
        ("PERSISTENT_REPLAY_PERMISSIONS", lambda: _ok_replay(p)),
        ("IMAGE_DIGEST_DECLARATION", lambda: _ok_image_lock(p)),
        ("SECURITY_IMAGE_OVERLAY_SOURCE_PARITY", lambda: _ok_overlay_parity(p)),
        ("TWO_HOST_SNAPSHOT_RECEIPT", lambda: _ok_snapshot_receipt(p)),
        ("SIGNED_443_NGINX_SOURCE", lambda: _ok_nginx(role, p)),
        ("APPROVED_NODE_ORIGINS", lambda: _ok_approved_origins(role, p)),
    ]
    rows = []
    for key, check in checks:
        try:
            check()
            rows.append((key, "PASS_LOCAL_EVIDENCE"))
        except (AuditHold, UnicodeError, ValueError, TypeError):
            rows.append((key, "HOLD"))
    # No subprocess/network means these cannot be proved by this tool.
    rows.extend((
        ("IMAGE_REGISTRY_ATTESTATION", "UNVERIFIED"),
        ("RUNNING_IMAGE_AND_DOCKER_MOUNTS", "UNVERIFIED"),
        ("EFFECTIVE_NGINX_TLS_CERT_HMAC_PATH", "UNVERIFIED"),
        ("CLOUD_SNAPSHOT_EXISTS_AND_RESTORE_WORKS", "UNVERIFIED"),
        ("FRP_BACKHAUL_XHTTP_REAL_TRAFFIC", "UNVERIFIED"),
        ("DUAL_HOST_REBOOT_AND_ROLLBACK_TEST", "UNVERIFIED"),
        ("AUTH_ACTIVATION", "BLOCKED"),
    ))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("ir", "kh"), required=True)
    for field in Paths.__dataclass_fields__:
        parser.add_argument("--" + field.replace("_", "-"),
                            type=Path, default=getattr(Paths(), field))
    args = parser.parse_args()
    p = Paths(**{name: getattr(args, name) for name in Paths.__dataclass_fields__})
    rows = audit(args.role, p)
    for name, result in rows:
        print(f"{name}={result}")
    hold = any(status == "HOLD" for _, status in rows)
    print("STAGE13_LOCAL_CHECKS=" + ("HOLD" if hold else "PASS_INCOMPLETE"))
    print("STAGE13_DEPLOYMENT_AUTHORIZED=NO")
    return 2 if hold else 0


if __name__ == "__main__":
    raise SystemExit(main())
