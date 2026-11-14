#!/usr/bin/env python3
"""Read-only admission for the *new* signed trial Foreign runtime.

Reuses the existing RC7 paused/strict security gates and independently
verified Smite Panel/Node signature pair. No image is changed, no secret is
issued, no replay database is provisioned, and no Node/Panel/FRP/Nginx
service is started or restarted. This is NOT activation.

The trial manifest explicitly has activation_allowed=false. Official RC7
runtime activation remains pinned to its *old* digest. Only a separately
reviewed and operator-approved activation implementation can change this.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys

MODULES = Path(__file__).resolve().parent
SOURCE = "de0677d015a00160970ed57bba565adc4fafe8eb"
MANIFEST_SHA = "61149003bbf966445bb25d0f94a4e666bb57b4544a5565703af55b30afa41c84"
NODE = ("ghcr.io/aghajani82/smite-node@sha256:"
        "2f63b5e1b3d262bf29bd2feaeec11b30b910c14e4d4b31ce4bb17e4fb24e2f4b")
PANEL = ("ghcr.io/aghajani82/smite-panel@sha256:"
         "a4142110b058b02a5325e8f2130f2faa5daa5fc0aa3faad82bb4389948d4385f")


class Hold(ValueError):
    pass


def deny():
    raise Hold("Signed unified Foreign activation admission HOLD")


def load(name, filename):
    path = MODULES / filename
    if path.is_symlink() or not path.is_file():
        deny()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        deny()
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def review(*, signature_runner=subprocess.run, pairing=None):
    """No writes, independent evidence. Injection is for offline tests only."""
    signed = load("uopti_trial_activation_pair", "smite-unified-trial-pair-admission.py")
    if pairing is None:
        pairing = load("uopti_trial_activation_pairing", "smite-node-pairing.py")

    try:
        result = signed.verify(
            manifest=MODULES / "smite-unified-trial-registry-pair.json",
            manifest_sha256=MANIFEST_SHA, source_sha=SOURCE,
            trusted_root=MODULES / "smite-rc7-sigstore-trusted-root.json",
            runner=signature_runner)
        if (result.get("status") != "verified_trial_pair"
                or result.get("host_activation_allowed") is not False
                or result.get("source_sha") != SOURCE
                or result.get("node") != NODE or result.get("panel") != PANEL
                or getattr(pairing, "_FOREIGN_NODE_IMAGE_UNIFIED_TRIAL", None) != NODE):
            deny()

        current = pairing.state_values()
        if (current.get("SMITE_ROLE") != "foreign"
                or current.get("SMITE_MANAGED_VERSION") != "2.0.0-rc.7"
                or current.get("SMITE_CONNECTION_MODE") != "standard"):
            deny()
        # Existing read-only RC7 security contract checks the exact reviewed
        # 443 path, managed Nginx metadata, paused Node env, healthy Docker,
        # immutable trial image, owned Compose, and the RO Sanaei mount.
        pairing._require_no_active_engine_overlays()
        panel, domain, control = pairing._foreign_gateway_preflight(
            current, review_unified_trial=True)

        node_id, secret = pairing._identity_record()
        if (not node_id or not secret or not pairing._replay_artifacts_valid()):
            deny()

        # Reuse the existing RC7 immutable-image and paused rollback
        # witness. Only this read-only reviewer selects the trial image,
        # after the independent two-image signature/source admission.
        pairing._rc7_foreign_paused_rollback_verified(
            expected_identity=(node_id, secret),
            require_replay=True,
            review_unified_trial=True,
        )
        if current.get("SMITE_NODE_NAME") is None or not current["SMITE_NODE_NAME"]:
            deny()

        return {
            "admission": "READY_READ_ONLY",
            "signed_pair": "VERIFIED_TRIAL_ONLY",
            "node_image": "EXACT_RUNNING_DIGEST",
            "runtime": "PAUSED_STRICT",
            "replay": "IDENTITY_BOUND",
            "gateway": "LOCAL_HTTPS_READ_ONLY_VERIFIED",
            "panel_runtime": "NOT_PROVEN_ON_REMOTE_HOST",
            "bidirectional_connected": False,
            "activation_allowed": False,
            "node_id": node_id,
            "panel_domain": panel,
            "foreign_domain": domain,
            "control_path": __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(control).path,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            signed.Hold, pairing.WizardHold):
        deny()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        if __import__("os").geteuid() != 0:
            deny()
        outcome = review()
    except Hold:
        print("UNIFIED_FOREIGN_ACTIVATION_REVIEW=HOLD")
        return 2
    print("UNIFIED_FOREIGN_ACTIVATION_REVIEW=" + outcome["admission"])
    print("SIGNED_TRIAL_RUNTIME=" + outcome["runtime"])
    print("TRIAL_HOST_ACTIVATION_ALLOWED=NO")
    print("PANEL_TO_FOREIGN_CONNECTED=NOT_PROVEN")
    print("NODE_RECREATED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
