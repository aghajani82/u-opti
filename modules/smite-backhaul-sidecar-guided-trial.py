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


class ExistingTrialHold(GuidedTrialHold):
    """Existing or partial trial must be inspected instead of reinstalled."""


class PostInstallCleanupHold(GuidedTrialHold):
    """Trial may be active, but private temporary cleanup is not verified."""


TEST_HOST_MARKER = Path("/root/.uopti-backhaul-rebuilt-test-host")
TEST_HOST_APPROVAL = "I APPROVE DISPOSABLE BACKHAUL TEST HOST"


def register_test_host_approval(role: str, confirmation: str) -> str:
    """Explicitly enroll a disposable host before pairing or profile prompts.

    This deliberately does NOT bypass trial.authorized() or trial.install().
    No unattended enrollment, replacing a marker, or changes to live services.
    """
    if confirmation != TEST_HOST_APPROVAL:
        raise GuidedTrialHold("Exact disposable-host consent required")
    role_gate._trusted_role(role)
    if trial.disposable_host_approved():
        return "TEST_HOST_APPROVAL=READY"
    if TEST_HOST_MARKER.exists() or TEST_HOST_MARKER.is_symlink():
        raise GuidedTrialHold("Invalid existing test-host approval marker; inspect manually")
    # Prevent approving a host with existing/partial Sidecar installation.
    role_gate._fresh(role)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(TEST_HOST_MARKER, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fp:
        os.fchmod(fp.fileno(), 0o600)
        fp.write(TEST_HOST_APPROVAL + "\n")
        fp.flush()
        os.fsync(fp.fileno())
    if not trial.disposable_host_approved():
        raise GuidedTrialHold("Test-host approval could not be verified")
    return "TEST_HOST_APPROVAL=READY"


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
                  approval: str, confirm: str,
                  data_port: int = 56053, xhttp_path: str | None = None) -> str:
    authorized(role, approval, confirm)
    # A previously installed/partially applied trial must be manually reviewed.
    # This check does not trust a directory name or regenerate an active token.
    if trial._root(role).exists() or trial._root(role).is_symlink():
        raise ExistingTrialHold("Trial journal exists; stop and inspect first")
    sidecar: Path | None = None
    nginx: Path | None = None
    try:
        if data_port == 56053 and xhttp_path in (None, "/56053/www"):
            sidecar, nginx = guided.prepare_fresh_pair(role, ir_domain, kh_host)
        else:
            sidecar, nginx = guided.prepare_fresh_pair(
                role, ir_domain, kh_host, data_port, xhttp_path)
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
        raise PostInstallCleanupHold("Private staging cleanup unverified; inspect journal")
    return SUCCESS



def diagnose(role: str, data_port: int = 56053,
             xhttp_path: str | None = None, ir_domain: str | None = None,
             kh_host: str | None = None) -> int:
    """No mutation, no staging, no token or secret printing.

    A missing journal is explicitly NOT an installation; this catches the
    recurring operator confusion between Smite/FRP/Backhaul pairing and
    independently activating the Sidecar.
    """
    print("BACKHAUL GUIDED STATUS | READ-ONLY | role=" + role)
    print("Checks only THIS host. Does not contact the other VPS.")
    try:
        role_gate._trusted_role(role)
        print("SMITE_ROLE_AND_MODE=VERIFIED")
    except Exception:
        print("SMITE_ROLE_AND_MODE=HOLD (expected Standard Smite role)")
        print("NEXT=Correct the selected IR/KH server; do not install.")
        return 2

    try:
        port, path = guided.sidecar.validated_profile(data_port, xhttp_path)
        print(f"REQUESTED_XRAY_PROFILE={port} {path}")
    except Exception:
        print("XRAY_PROFILE=HOLD (unsafe/invalid port or XHTTP base Path)")
        return 2

    current = trial._root(role)
    if current.exists() or current.is_symlink():
        print("INSTALL_JOURNAL=PRESENT")
        print("NEXT=Read trial journal and existing Sidecar health; never reinstall over it.")
        return 2
    print("INSTALL_JOURNAL=MISSING")
    print("INSTALLATION=NOT VERIFIED; pairing is NOT Sidecar installation.")

    try:
        token_ok = guided.token_tool.inspect(guided.TOKEN_FILE)
    except Exception:
        token_ok = False
    print("PRIVATE_PAIRING=" + ("READY" if token_ok else "MISSING_OR_INVALID"))
    print("TEST_HOST_APPROVAL=" + ("READY" if trial.disposable_host_approved()
                                    else "MISSING_OR_INVALID"))
    try:
        vhost = (Path(guided.nginx_plan.IR_PATH) if role == "ir" else
                 Path(guided.nginx_plan.kh_vhost_path(kh_host)) if kh_host else None)
    except (TypeError, ValueError):
        vhost = None
    print("EXPECTED_NGINX_VHOST=" + ("FOUND" if vhost is not None and vhost.is_file() and not vhost.is_symlink()
                                       else "MISSING_OR_UNEXPECTED"))
    issues = guided.readiness.inspect_local(
        role, "new", data_port=port, xhttp_path=path)
    if issues:
        print("LOCAL_FRESH_READINESS=HOLD")
        # Fixed internal audit strings contain no token-bearing file content.
        for issue in issues:
            print("LOCAL_HOLD: " + issue)
    else:
        print("LOCAL_FRESH_READINESS=PASSED")

    layout_ok = True
    if ir_domain is not None or kh_host is not None:
        if not ir_domain or not kh_host:
            layout_ok = False
        else:
            try:
                source = guided.nginx_plan.original_bytes(vhost)
                guided.nginx_plan.compile_nginx(
                    role, source, ir_domain, kh_host, port, path)
            except Exception:
                layout_ok = False
        print("SELECTED_NGINX_LAYOUT=" + ("SUPPORTED" if layout_ok else "HOLD"))
        if not layout_ok:
            print("NEXT=Verify domain, exact Nginx host and supported proxy layout.")
    else:
        print("SELECTED_NGINX_LAYOUT=NOT_CHECKED (supply both hostnames)")

    if not token_ok:
        print("NEXT=Backhaul Step 1 Pair IR/KH on the fresh hosts.")
    elif not trial.disposable_host_approved():
        print("NEXT=After snapshot and console, register test-host approval.")
    elif issues or not layout_ok or vhost is None or not vhost.is_file():
        print("NEXT=Fix the local preflight condition; do not start installation.")
    else:
        print("NEXT=Backhaul Step 2 INSTALL Sidecar (separate on BOTH hosts).")
        print("Passing this check is NOT an install or proof of TLS/client traffic.")
    print("READ_ONLY_NO_FILES_CHANGED")
    return 0 if token_ok and trial.disposable_host_approved() and not issues and layout_ok and vhost is not None and vhost.is_file() else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("ir", "kh"))
    parser.add_argument("--ir-domain")
    parser.add_argument("--kh-host")
    parser.add_argument("--data-port", type=int, default=56053)
    parser.add_argument("--xhttp-path", default=None)
    actions = parser.add_mutually_exclusive_group(required=False)
    actions.add_argument("--install-test", action="store_true")
    actions.add_argument("--diagnose", action="store_true")
    actions.add_argument("--approval-status", action="store_true")
    actions.add_argument("--approve-test-host", action="store_true")
    parser.add_argument("--test-host-approval", default="")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.approval_status:
        try:
            role_gate._trusted_role(args.role)
        except Exception:
            print("TEST_HOST_APPROVAL=HOLD (trusted Standard role required)")
            return 2
        if trial.disposable_host_approved():
            print("TEST_HOST_APPROVAL=READY")
            return 0
        print("TEST_HOST_APPROVAL=MISSING_OR_INVALID")
        return 2
    if args.approve_test_host:
        try:
            print(register_test_host_approval(args.role, args.confirm))
        except Exception:
            print("HOLD: Test-host approval refused. No Sidecar installed or services changed.")
            return 2
        return 0
    if not args.diagnose and not args.install_test:
        print("HOLD: Select read-only --diagnose or explicit --install-test.")
        return 2
    if args.diagnose:
        return diagnose(args.role, args.data_port, args.xhttp_path,
                        args.ir_domain, args.kh_host)
    if not args.ir_domain or not args.kh_host:
        print("HOLD: Both IR and KH domains are required for installation.")
        return 2
    try:
        result = install_fresh(args.role, args.ir_domain, args.kh_host,
                               args.test_host_approval, args.confirm,
                               args.data_port, args.xhttp_path)
    except Exception as exc:
        # Fixed error categories only: never echo private token, vhost contents
        # or uncontrolled lower-layer exception strings.
        if isinstance(exc, ExistingTrialHold):
            stage = "EXISTING_OR_PARTIAL_TRIAL"
            hint = ("This call did NOT start an installation; an existing journal "
                    "must be checked before any action.")
        elif isinstance(exc, PostInstallCleanupHold):
            stage = "POST_INSTALL_PRIVATE_CLEANUP_UNVERIFIED"
            hint = ("Sidecar activation may already have succeeded, but temporary "
                    "cleanup is unverified. Do NOT reinstall or manually delete files.")
        elif isinstance(exc, GuidedTrialHold):
            stage = "HOST_APPROVAL_REFUSED"
            hint = "Host approval or explicit installation consent did not pass."
        elif isinstance(exc, guided.GuidedHold):
            stage = "PREPARATION_OR_NGINX_ADMISSION"
            hint = "Private preparation or Nginx admission did not pass."
        elif isinstance(exc, trial.TrialRefused):
            stage = "TRANSACTION_OR_POST_INSTALL_VERIFICATION"
            hint = "Trial transaction or post-install verification did not pass."
        else:
            stage = "UNEXPECTED_REVIEW_REQUIRED"
            hint = "Unexpected failure; do not guess or rerun."
        print("HOLD_STAGE=" + stage)
        print("HOLD: " + hint)
        print("NEXT=Inspect THIS host using the following READ-ONLY checks:")
        print("  smite-backhaul-sidecar-live-trial.py --role " + args.role + " --status")
        print("  smite-backhaul-sidecar-readiness.py --role " + args.role + " --mode existing")
        print("Never overwrite or retry a host with an existing/partial Sidecar.")
        return 2
    print(result)
    print("No manual temporary paths required; private staging was cleaned.")
    print("This proves LOCAL installation only. Test authenticated VLESS/XHTTP,")
    print("existing FRP, KH public bridge guard, and sequential reboot separately.")
    print("TRIAL only: rollback/reinstall not yet field-validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
