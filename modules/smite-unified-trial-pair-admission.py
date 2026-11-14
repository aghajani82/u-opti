#!/usr/bin/env python3
"""Read-only admission of the tagged RC9 pair for unified-install rehearsals."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

REF = "refs/tags/v2.0.0-rc.9"


class Hold(ValueError):
    pass


def verify(*, manifest, manifest_sha256, source_sha, trusted_root, runner=None):
    manifest = Path(manifest)
    trusted_root = Path(trusted_root)
    for path in (manifest, trusted_root):
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise Hold("Unified candidate input unavailable or unsafe")

    path = Path(__file__).with_name("smite-registry-pair-admission.py")
    if path.is_symlink() or not path.is_file():
        raise Hold("Tagged publisher verifier unavailable")
    spec = importlib.util.spec_from_file_location("uopti_registry_pair_admission", path)
    if spec is None or spec.loader is None:
        raise Hold("Tagged publisher verifier unavailable")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    try:
        result = verifier.verify_pair(
            manifest=manifest, manifest_sha256=manifest_sha256,
            source_sha=source_sha, publish_ref=REF, trusted_root=trusted_root,
            runner=runner,
        )
    except verifier.AdmissionHold as exc:
        raise Hold("Signed unified candidate pair admission HOLD") from exc

    return {
        "status": "verified_trial_pair",
        "source_sha": result["source_sha"],
        "panel": result["images"]["panel"],
        "node": result["images"]["node"],
        "host_activation_allowed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--trusted-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        verify(manifest=args.manifest, manifest_sha256=args.manifest_sha256,
               source_sha=args.source_sha, trusted_root=args.trusted_root)
    except (Hold, ValueError, TypeError, KeyError, OSError):
        print("TRIAL_PAIR_SIGNATURE_ADMISSION=HOLD")
        return 2
    print("TRIAL_PAIR_SIGNATURE_ADMISSION=VERIFIED_READ_ONLY")
    print("EXACT_SIGNED_PANEL_NODE_DIGESTS=YES")
    print("NO_MAIN_RELEASE_OR_HOST_ACTIVATION=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
