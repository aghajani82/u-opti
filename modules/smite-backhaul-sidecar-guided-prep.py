#!/usr/bin/env python3
"""Role-aware single-step PRIVATE OFFLINE Backhaul preparation for fresh TEST hosts.

Combines the existing exact Sidecar generator, Nginx merge-plan compiler and
fresh-host admission check. Does NOT deploy, alter /etc, run containers,
reload Nginx, modify Smite/FRP/Xray, or print credentials. The old individual
tools and the independently gated experimental trial installer remain intact.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TOKEN_FILE = Path("/etc/u-opti/backhaul-sidecar/shared.token")


def _load(alias: str, name: str):
    spec = importlib.util.spec_from_file_location(alias, HERE / name)
    if spec is None or spec.loader is None:
        raise RuntimeError("Required offline module missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


token_tool = _load("guided_token", "smite-backhaul-sidecar-token.py")
sidecar = _load("guided_sidecar", "smite-backhaul-sidecar.py")
nginx_plan = _load("guided_nginx", "smite-backhaul-sidecar-nginx-plan.py")
admission_gate = _load("guided_admission", "smite-backhaul-sidecar-admission.py")
readiness = _load("guided_readiness", "smite-backhaul-sidecar-readiness.py")


class GuidedHold(ValueError):
    pass


def _cleanup_private_stage(path: Path | None, prefix: str) -> None:
    """Clean up only our own private direct-child /tmp folders on HOLD."""
    if path is None or path.parent != Path("/tmp") or not path.name.startswith(prefix):
        return
    try:
        info = path.lstat()
        if (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o700):
            shutil.rmtree(path)
    except OSError:
        # Fail closed: never remove an unexpected replacement or follow a link.
        pass


def prepare_fresh_pair(role: str, ir_domain: str, kh_host: str
                       ) -> tuple[Path, Path]:
    """Prepare and verify; success means staged only, NOT installed."""
    if os.geteuid() != 0:
        raise GuidedHold("Root is required")
    if role not in ("ir", "kh"):
        raise GuidedHold("Choose a verified IR or KH role")
    # Domain validation before any staging. Exact Nginx topology checks remain
    # inside the unchanged compiler and admission gate.
    sidecar.validated_domain(ir_domain)
    sidecar.validated_domain(kh_host)
    if not token_tool.inspect(TOKEN_FILE):
        raise GuidedHold("Private pairing token missing or unsafe; verify it first")
    existing = readiness.inspect_local(role, "new")
    if existing:
        raise GuidedHold("Fresh-host checks not passed: " + "; ".join(existing))
    vhost = Path(nginx_plan.IR_PATH if role == "ir" else nginx_plan.KH_PATH)
    sc_stage: Path | None = None
    ng_stage: Path | None = None
    success = False
    try:
        sc_stage = sidecar.prepare(role, TOKEN_FILE, ir_domain, kh_host)
        ng_stage = nginx_plan.prepare(role, vhost, ir_domain, kh_host)
        issues = admission_gate.admission(role, sc_stage, ng_stage)
        if issues:
            raise GuidedHold("Paired candidate admission HOLD: " + "; ".join(issues))
        success = True
        return sc_stage, ng_stage
    finally:
        if not success:
            _cleanup_private_stage(ng_stage, "uopti-bh-nginx-plan-")
            _cleanup_private_stage(sc_stage, "uopti-backhaul-sidecar-")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("ir", "kh"), required=True)
    parser.add_argument("--ir-domain", required=True)
    parser.add_argument("--kh-host", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--confirm", default="")
    opts = parser.parse_args()
    if not opts.prepare_only or opts.confirm != "PREPARE-PRIVATE-OFFLINE":
        print("HOLD: Explicit private OFFLINE preparation confirmation required.")
        return 2
    try:
        sc, ng = prepare_fresh_pair(opts.role, opts.ir_domain, opts.kh_host)
    except Exception:
        # Never include caught exception text: lower layers may contain
        # token-bearing paths or private Nginx source details.
        print("HOLD: Offline pair not verified; check fresh-host readiness, "
              "token, Nginx topology, and bundle admission. No activation.")
        return 2
    print("PAIRED_PRIVATE_OFFLINE_CANDIDATES_AND_LOCAL_PREFLIGHT_PASSED")
    print("Role:", opts.role)
    print("Sidecar private proposal:", sc)
    print("Nginx private proposal:", ng)
    print("OFFLINE ONLY: No /etc writes, Docker changes, Nginx reload or install.")
    print("NOT production approval. Keep private proposals and the token secret.")
    print("Review TLS/SNI, backup and guarded rollback before any later activation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
