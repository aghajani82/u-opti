#!/usr/bin/env python3
"""Offline-only Sidecar rollback manifest validator and reverse-action planner.

Reads JSON simulation input; returns only descriptive actions. Does NOT
read/write installed files, remove containers, or reload any service.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

HEX = re.compile(r"[0-9a-f]{64}\Z")
ALLOW = {
    "ir": {
        "/etc/u-opti/backhaul-sidecar/ir.toml": "create",
        "/etc/u-opti/backhaul-sidecar/compose-ir.yml": "create",
        "/etc/nginx/u-opti-sidecar/ir-control.inc": "create",
        "/etc/nginx/u-opti-sidecar/ir-xhttp.inc": "create",
        "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf": "edit",
    },
    "kh": {
        "/etc/u-opti/backhaul-sidecar/kh.toml": "create",
        "/etc/u-opti/backhaul-sidecar/compose-kh.yml": "create",
        "/etc/nginx/conf.d/u-opti-backhaul-kh-bridge.conf": "create",
    },
}
CONTAINER = {"ir": "uopti-backhaul-sidecar-ir", "kh": "uopti-backhaul-sidecar-kh"}


class RollbackUnsafe(ValueError):
    pass


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise RollbackUnsafe(f"Invalid SHA256 for {label}")
    return value


def plan_reversal(manifest: object, observed: object) -> list[str]:
    """Fail closed on ANY drift, unknown target or incomplete sidecar manifest.

    manifest: {"role":"ir"|"kh", "container_name":..., "resources":[{
      "path": ..., "operation": "create"|"edit",
      "before_sha256": null|sha, "applied_sha256": sha,
      "backup_sha256": null|sha}]}
    observed: {"container_name": ..., "resources": {path: live_sha256}}
    No executable rollback actions are returned.
    """
    if not isinstance(manifest, dict) or not isinstance(observed, dict):
        raise RollbackUnsafe("Manifest/observation must be objects")
    role = manifest.get("role")
    if role not in ALLOW or manifest.get("container_name") != CONTAINER[role]:
        raise RollbackUnsafe("Unexpected sidecar role or container name")
    if observed.get("container_name") != CONTAINER[role]:
        raise RollbackUnsafe("Observed container does not match owned sidecar")
    rows = manifest.get("resources")
    live = observed.get("resources")
    if not isinstance(rows, list) or not isinstance(live, dict):
        raise RollbackUnsafe("Missing resource manifest/observation")
    if set(live) != set(ALLOW[role]):
        raise RollbackUnsafe("Observed paths differ from exact resource allowlist")
    found = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "path", "operation", "before_sha256", "applied_sha256", "backup_sha256"
        }:
            raise RollbackUnsafe("Unexpected resource shape")
        path = row["path"]
        if path not in ALLOW[role] or path in found:
            raise RollbackUnsafe("Unknown/duplicate resource path")
        if row["operation"] != ALLOW[role][path]:
            raise RollbackUnsafe("Illegal resource operation")
        applied = _sha(row["applied_sha256"], "applied")
        current = _sha(live.get(path), "observed")
        if current != applied:
            raise RollbackUnsafe("Observed resource drifted; refuse rollback")
        if row["operation"] == "create":
            if row["before_sha256"] is not None or row["backup_sha256"] is not None:
                raise RollbackUnsafe("Created file must have absent baseline/backup")
        else:
            before = _sha(row["before_sha256"], "baseline")
            backed = _sha(row["backup_sha256"], "backup")
            if before != backed or before == applied:
                raise RollbackUnsafe("Unverified original backup")
        found[path] = row
    if set(found) != set(ALLOW[role]):
        raise RollbackUnsafe("Incomplete rollback scope")
    # Reports only: actual container stop must be separately designed and
    # authorized, and only after confirming its exact ownership.
    steps = ["PLAN ONLY: stop the specifically named independent Sidecar container"]
    for path in reversed(list(ALLOW[role])):
        action = "restore verified original backup" if found[path]["operation"] == "edit" else "remove solely owned created file"
        steps.append(f"PLAN ONLY: {action}: {path}")
    steps.append("PLAN ONLY: validate Nginx with nginx -t before a separately approved reload")
    steps.append("NOT EXECUTED. No Smite, FRP, Xray, Nginx or Docker changes.")
    return steps


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--observed", type=Path, required=True)
    args = ap.parse_args()
    try:
        if args.manifest.stat().st_size > 32768 or args.observed.stat().st_size > 32768:
            raise RollbackUnsafe("Oversized input")
        rows = json.loads(args.manifest.read_text())
        observed = json.loads(args.observed.read_text())
        steps = plan_reversal(rows, observed)
    except (OSError, ValueError) as exc:
        ap.error("FAIL CLOSED: " + type(exc).__name__)
    print("OFFLINE ROLLBACK SIMULATION — NO COMMANDS EXECUTED")
    print("\n".join(steps))


if __name__ == "__main__":
    main()
