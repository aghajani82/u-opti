#!/usr/bin/env python3
"""Read-only installation admission gate for a *fresh* Backhaul test host.

Consumes two independently generated PRIVATE candidate bundles, checks exact
Sidecar/Nginx reconciliation, confirms the original host vhost bytes+owner+
mode and refuses target collisions. Consults the existing read-only listener,
Docker and Nginx baseline audit. NO INSTALL, Docker changes, nginx reload, or
network dial is performed here. A pass is NOT deployment authorization.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import stat
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


paired = _load("admission_pair", "smite-backhaul-sidecar-reconcile.py")
local = _load("admission_local", "smite-backhaul-sidecar-readiness.py")


class AdmissionRefused(ValueError):
    pass


def _existing_ancestors_safe(path: Path) -> bool:
    # Protect against a writable, symlinked ancestor. Do not resolve links.
    # Stop at /etc; shared system root paths are not modified by this tool.
    if not path.is_absolute() or not str(path).startswith("/etc/"):
        return False
    parent = path.parent
    while str(parent) not in ("/etc", "/"):
        try:
            st = parent.lstat()
        except FileNotFoundError:
            parent = parent.parent
            continue
        except OSError:
            return False
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0
                or stat.S_IMODE(st.st_mode) & 0o022):
            return False
        parent = parent.parent
    return True


def _original_source(path: Path, expected: bytes) -> str | None:
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != 0 or info.st_gid != 0
                or stat.S_IMODE(info.st_mode) not in (0o600, 0o640, 0o644)
                or not 32 <= info.st_size <= 128000):
            return "Original Nginx vhost not a safe root-owned regular file"
        # Do not read or echo token-bearing configuration text.
        with path.open("rb") as file:
            before = file.read(128001)
        second = path.lstat()
        if (before != expected or second.st_dev != info.st_dev
                or second.st_ino != info.st_ino or second.st_size != info.st_size
                or second.st_mtime_ns != info.st_mtime_ns
                or second.st_ctime_ns != info.st_ctime_ns):
            return "Nginx source drifted from the reviewed proposal"
    except (OSError, ValueError):
        return "Original Nginx vhost unreadable"
    return None


def admission(role: str, sidecar_dir: Path, nginx_dir: Path,
              *, observed_host: bool = True) -> list[str]:
    if role not in paired.LAYOUT:
        raise AdmissionRefused("Unknown role")
    # Verify all contents before querying the host. Staged secrets never
    # appear in errors, formatted output, or command arguments.
    try:
        rows = paired.reconcile(role, sidecar_dir, nginx_dir)
    except (paired.ReconcileRefused, OSError, ValueError) as exc:
        raise AdmissionRefused("Candidate identity, path or integrity mismatch") from exc

    issues = []
    for row in rows:
        path = Path(row["path"])
        if not _existing_ancestors_safe(path):
            issues.append("Non-root or writable/symlinked ancestor: " + path.name)
            continue
        if row["operation"] == "create":
            try:
                path.lstat()
            except FileNotFoundError:
                pass
            except OSError:
                issues.append("Cannot inspect proposed resource: " + path.name)
            else:
                issues.append("Resource already exists; NO OVERWRITE: " + path.name)
        else:
            failure = _original_source(path, row["before"])
            if failure:
                issues.append(failure)

    # The host baseline (process owner, reserved loopbacks, Docker and
    # nginx -t) is checked independently. This module never bypasses it.
    if observed_host:
        issues.extend(local.inspect_local(role, "new"))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("ir", "kh"))
    parser.add_argument("--sidecar-dir", required=True, type=Path)
    parser.add_argument("--nginx-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        issues = admission(args.role, args.sidecar_dir, args.nginx_dir)
    except AdmissionRefused:
        print("HOLD: Invalid or unsafe candidate bundles; no secrets disclosed.")
        return 2
    print("BACKHAUL INSTALL ADMISSION | READ-ONLY | role=" + args.role)
    if issues:
        for issue in issues:
            print("HOLD: " + issue)
        print("NO INSTALLATION. No files, containers or services changed.")
        return 2
    print("FRESH_HOST_FILES_AND_LOCAL_PREFLIGHT_PASSED")
    print("NOT DEPLOYMENT APPROVAL: verify snapshots, TLS/SNI, rollback and")
    print("full Nginx config on disposable hosts before enabling live writes.")
    print("NO INSTALLATION. No files, containers or services changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
