#!/usr/bin/env python3
"""One-flow guided Backhaul install on an explicitly approved FRESH TEST VPS.

Reuses unchanged exact offline generators, admission and the transaction-journal
trial engine. Never selects arbitrary stale /tmp files or weakens approval gates.
Not a production installer. Existing Sidecars/FRP/Smite/Xray remain protected.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _load(alias: str, filename: str):
    spec = importlib.util.spec_from_file_location(alias, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("Required U-OPTI module is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guided = _load("oneflow_guided", "smite-backhaul-sidecar-guided-prep.py")
trial = _load("oneflow_trial", "smite-backhaul-sidecar-live-trial.py")
role_gate = _load("oneflow_role", "smite-backhaul-sidecar-ssh-pair.py")

SUCCESS = "GUIDED_TEST_HOST_INSTALL_LOCAL_CHECKS_PASSED"


class GuidedTrialHold(ValueError):
    pass


def authorized(role: str, approval: str, confirm: str) -> None:
    """Validate approval BEFORE staging private data or attempting install."""
    if role not in ("ir", "kh") or os.geteuid() != 0:
        raise GuidedTrialHold("Root and IR/KH role required")
    if approval != "REBUILT-TEST-VPS" or confirm != "INSTALL-" + role.upper():
        raise GuidedTrialHold("Explicit disposable-host and role consent required")
    if os.environ.get("UOPTI_BH_TEST_HOST") != "I_ACCEPT_REBUILD_TEST_HOST":
        raise GuidedTrialHold("Experimental host opt-in is missing")
    if not trial.disposable_host_approved():
        raise GuidedTrialHold("Independent disposable-host approval marker missing")
    # Do not confuse a KH and an IR terminal. No SSH command is executed.
    role_gate._trusted_role(role)


def install_fresh(role: str, ir_domain: str, kh_host: str,
                  approval: str, confirm: str) -> str:
    authorized(role, approval, confirm)
    # A previously installed/partially applied trial must be manually reviewed.
    # This check does not trust a directory name or regenerate an active token.
    if trial._root(role).exists() or trial._root(role).is_symlink():
        raise GuidedTrialHold("Trial journal exists; stop and inspect first")
    sidecar: Path | None = None
    nginx: Path | None = None
    try:
        sidecar, nginx = guided.prepare_fresh_pair(role, ir_domain, kh_host)
        # Underlying trial.install separately repeats all approvals, exact
        # reconciliation, admission, ownership checks, journaling and rollback.
        result = trial.install(role, sidecar, nginx)
        if result != "TRIAL_INSTALL_LOCAL_CHECKS_PASSED":
            raise GuidedTrialHold("Unexpected trial installer result")
    finally:
        # These two candidate directories are never recovery backups.
        # The unchanged installer saves its own durable journal and Nginx copy.
        guided._cleanup_private_stage(nginx, "uopti-bh-nginx-plan-")
        guided._cleanup_private_stage(sidecar, "uopti-backhaul-sidecar-")
    # A partial cleanup is not a clean success; stop for manual review
    # rather than asserting the private token-bearing proposals were deleted.
    if any(os.path.lexists(str(p)) for p in (sidecar, nginx)):
        raise GuidedTrialHold("Private staging cleanup unverified; inspect journal")
    return SUCCESS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("ir", "kh"))
    parser.add_argument("--ir-domain", required=True)
    parser.add_argument("--kh-host", required=True)
    parser.add_argument("--install-test", action="store_true")
    parser.add_argument("--test-host-approval", default="")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if not args.install_test:
        print("HOLD: Only a separately confirmed disposable TEST install is supported.")
        return 2
    try:
        result = install_fresh(args.role, args.ir_domain, args.kh_host,
                               args.test_host_approval, args.confirm)
    except Exception:
        # Never print lower-layer exceptions: candidate or vhost contents can
        # be sensitive. An error may occur AFTER trial activation; NEVER
        # recommend an automatic retry, duplicate install or unsafe cleanup.
        print("HOLD: Guided TEST installation incomplete or unverified.")
        print("Check the local trial journal/status READ-ONLY before retrying.")
        print("Do not overwrite an existing Sidecar or force recovery.")
        return 2
    print(result)
    print("No manual temporary paths required; private staging was cleaned.")
    print("This proves LOCAL installation only. Test authenticated VLESS/XHTTP,")
    print("existing FRP, KH public bridge guard, and sequential reboot separately.")
    print("TRIAL only: rollback/reinstall not yet field-validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
