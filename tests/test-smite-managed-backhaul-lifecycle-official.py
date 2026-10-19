#!/usr/bin/env python3
"""Official Backhaul v0.7.2 end-to-end CI lifecycle (never on VPS).

The official artifact, private lab, signed Node API test and pinned Smite
source must already have been prepared by the parent PR shell script.
Only these checked-in scripts can be launched as health callbacks.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-managed-backhaul-lifecycle.py"
HEALTH = ROOT / "tests/test-smite-managed-backhaul-signed-api.sh"
spec = importlib.util.spec_from_file_location("reviewed_backhaul_lifecycle", SOURCE)
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)


def main() -> int:
    if len(sys.argv) != 3:
        print("HOLD: exact root and stage required", file=sys.stderr)
        return 2
    lab, stage = map(Path, sys.argv[1:])
    # Required before any probe or file mutation. No environment spoofed here:
    # only the parent GitHub PR job can provide the private runner lab marker.
    lifecycle.tx.admission(lab)

    def signed_probe(root: Path, phase: str) -> bool:
        if phase not in ("ready", "absent"):
            return False
        try:
            process = subprocess.run(
                ["bash", str(HEALTH), str(root), phase],
                check=False, capture_output=True, text=True, timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        stdout = process.stdout
        required = (
            "SIGNED_NODE_NETWORK_NONE_NO_HOST_PORTS=PASS",
            f"SIGNED_NODE_API_{phase.upper()}_RESTART=PASS",
            f"SIGNED_API_BACKHAUL_{phase.upper()}_AFTER-RESTART=PASS",
        )
        # Never print raw stdout or stderr: they may contain HMAC test data.
        return process.returncode == 0 and all(token in stdout for token in required)

    try:
        result = lifecycle.run_lab_rehearsal(
            lab, stage,
            check_ready=lambda root: signed_probe(root, "ready"),
            check_absent=lambda root: signed_probe(root, "absent"),
        )
        assert result["PRODUCTION_ACTIVATION"] == "HOLD"
        assert result["TRIAL_PREVIOUS_RUNTIME"] == "SIGNED_ABSENT_AFTER_RESTART_VERIFIED"
        print("OFFICIAL_BACKHAUL_LIFECYCLE_SIGNED_READY_AND_AUTO_ROLLBACK=PASS")

        def injected_failure(root: Path) -> bool:
            if not signed_probe(root, "ready"):
                return False
            # Inject a fault AFTER the real Node has started and restarted.
            return False

        try:
            lifecycle.run_lab_rehearsal(
                lab, stage, check_ready=injected_failure,
                check_absent=lambda root: signed_probe(root, "absent"))
        except lifecycle.Hold as err:
            if str(err) != "ACTIVATION_FAILED_EXACT_ROLLBACK_PROVED":
                raise
            print("OFFICIAL_BACKHAUL_POST_RESTART_FAILURE_COMPENSATED=PASS")
        else:
            raise lifecycle.Hold("FAILED_HEALTH_PROOF_WAS_ACCEPTED")
        # State remains absent, while previous signed identity persists.
        node = lab / "node"
        state = lifecycle.ctl.inspect(node, lab_binary=lab / "installed/backhaul")
        assert state["state"] == "NOT_INSTALLED"
        assert not (lab / "recovery-journal").exists()
        print("OFFICIAL_BACKHAUL_PREVIOUS_NODE_AND_IDENTITY_RECOVERED=PASS")
        return 0
    except lifecycle.Hold as error:
        # Lifecycle Hold reasons are fixed internal codes, never credentials.
        message = str(error)
        allowed = {
            "UNFINISHED_TRANSACTION_MUST_RECOVER_FIRST", "ENGINE_MUST_START_ABSENT",
            "CORRUPT_SAVED_TUNNEL_REGISTRY", "UNKNOWN_SAVED_TUNNEL_REGISTRY",
            "EXISTING_TUNNELS_DO_NOT_RECREATE",
            "ROLLBACK_FAILED_MANUAL_REVIEW_REQUIRED",
            "ROLLBACK_BYTES_OR_PROTECTED_STATE_MISMATCH",
            "PREVIOUS_SIGNED_NODE_RUNTIME_NOT_RESTORED",
            "ACTIVATION_FAILED_EXACT_ROLLBACK_PROVED",
            "FAILED_HEALTH_PROOF_WAS_ACCEPTED",
        }
        print("HOLD: " + (message if message in allowed else "LIFECYCLE_ADMISSION_OR_ARTIFACT_FAILED"),
              file=sys.stderr)
        return 2
    except (OSError, AssertionError):
        print("HOLD: LIFECYCLE_SYSTEM_CHECK_FAILED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
