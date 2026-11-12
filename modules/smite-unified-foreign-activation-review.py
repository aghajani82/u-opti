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
import re
import subprocess
import sys

MODULES = Path(__file__).resolve().parent
SOURCE = "b865be93e22153c60769f6329e6e55e781494ded"
MANIFEST_SHA = "e13f0708b1de5eef112b955f4b6efe4e1efa5520d404458646bb6e1e76c96608"
NODE = ("ghcr.io/aghajani82/smite-node@sha256:"
        "587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483")
PANEL = ("ghcr.io/aghajani82/smite-panel@sha256:"
         "1b03d0d865ba4abd6fe45899d2ccd6d34f300b4804acd2c6690a52b68fb26289")
ID = re.compile(r"sha256:[a-f0-9]{64}\Z")


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

        # The original preflight validated the Compose service image string.
        # Also bind the ACTUAL runtime image ID to the locally pinned digest,
        # and verify effective runtime auth values, not just on-disk env.
        runtime = pairing._run(
            ["docker", "inspect", "-f", "{{.Image}}", "smite-node"],
            capture=True, timeout=10)
        local = pairing._run(
            ["docker", "image", "inspect", "-f", "{{.Id}}", NODE],
            capture=True, timeout=10)
        if (not isinstance(runtime, str) or not ID.fullmatch(runtime)
                or runtime != local):
            deny()
        effective = pairing._run(
            ["docker", "inspect", "-f",
             "{{range .Config.Env}}{{println .}}{{end}}", "smite-node"],
            capture=True, timeout=10)
        if not isinstance(effective, str):
            deny()
        rows = effective.splitlines()
        for label in (
            "SMITE_NODE_PANEL_AUTH_MODE=paused",
            "SMITE_AGENT_AUTH_MODE=strict",
            "SMITE_ENGINE_INVENTORY_MODE=managed",
        ):
            key = label.split("=")[0] + "="
            if len([r for r in rows if r.startswith(key)]) != 1 or label not in rows:
                deny()
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
