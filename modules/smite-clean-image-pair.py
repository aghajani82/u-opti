#!/usr/bin/env python3
"""Verified OFFLINE inputs for explicitly requested CLEAN Smite test install.

Does NOT install images, invoke Docker, start services, write secrets, or
authorize production use. It only checks that the supplied Panel/Node
archives have the exact trusted Git source and manifest SHA256.

The source commit and manifest SHA256 MUST be independently copied from
the trusted GitHub Actions run. Do not derive them from the artifact itself.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys

VERIFY_MODULE = Path(__file__).with_name("smite-stage15-bundle-verify.py")


class FreshInstallHold(Exception):
    pass


def inspected_pair(*, folder: Path, source_sha: str, manifest_sha256: str) -> dict:
    if not VERIFY_MODULE.is_file() or VERIFY_MODULE.is_symlink():
        raise FreshInstallHold("Stage15 checksum verifier unavailable")
    module_spec = importlib.util.spec_from_file_location("smite_clean_archive_check", VERIFY_MODULE)
    if not module_spec or not module_spec.loader:
        raise FreshInstallHold("Cannot load checksum verifier")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    try:
        manifest = module.verify(
            folder=folder, source_sha=source_sha, manifest_sha=manifest_sha256,
        )
    except (module.BundleHold, OSError, UnicodeError, TypeError) as exc:
        raise FreshInstallHold("Untrusted or mismatched offline image pair") from exc

    # These are local Docker image IDs; never confuse with registry digests.
    panel = manifest["images"]["panel"]["local_image_id"]
    node = manifest["images"]["node"]["local_image_id"]
    return {
        "source_commit": source_sha,
        "panel_image_id": panel,
        "node_image_id": node,
        "panel_archive": folder / "smite-panel-stage15.docker.tar.gz",
        "node_archive": folder / "smite-node-stage15.docker.tar.gz",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", required=True, type=Path)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--manifest-sha256", required=True)
    args = p.parse_args(argv)
    try:
        result = inspected_pair(
            folder=args.folder,
            source_sha=args.source_sha,
            manifest_sha256=args.manifest_sha256,
        )
    except FreshInstallHold as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 2

    print("CLEAN_RC_PAIR=ARCHIVES_VERIFIED")
    print(f"SMITE_RC_SOURCE_COMMIT={result['source_commit']}")
    print(f"SMITE_RC_PANEL_ID={result['panel_image_id']}")
    print(f"SMITE_RC_NODE_ID={result['node_image_id']}")
    print("SIGNED_PRODUCTION_RELEASE=NO")
    print("CLEAN_RC_PRECHECK_ONLY=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
