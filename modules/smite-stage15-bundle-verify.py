#!/usr/bin/env python3
"""Read-only U-OPTI Stage15 admission for paired Smite offline Docker archives.

Require TWO externally trusted values from the successful GitHub Actions run:
(1) exact Smite Git commit and (2) stage15-images.json SHA256. Verify all
local archive checksums/size without loading or running any container.

This is NOT a signature or registry attestation and NEVER authorizes deploy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
FILES = {
    "panel": "smite-panel-stage15.docker.tar.gz",
    "node": "smite-node-stage15.docker.tar.gz",
}


class BundleHold(ValueError):
    pass


def _hash(path: Path, *, max_bytes: int = 5_000_000_000) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise BundleHold("Missing or symlinked artifact")
    sha = hashlib.sha256()
    count = 0
    with path.open("rb") as file:
        while block := file.read(1024 * 1024):
            count += len(block)
            if count > max_bytes:
                raise BundleHold("Unexpectedly large artifact")
            sha.update(block)
    if count == 0:
        raise BundleHold("Empty artifact")
    return sha.hexdigest(), count


def verify(*, folder: Path, source_sha: str, manifest_sha: str) -> dict:
    if not HEX40.fullmatch(source_sha) or not HEX64.fullmatch(manifest_sha):
        raise BundleHold("Requires exact trusted source and manifest SHA256")
    if folder.is_symlink() or not folder.is_dir():
        raise BundleHold("Invalid extracted bundle folder")
    path = folder / "stage15-images.json"
    sha, size = _hash(path, max_bytes=100_000)
    if sha != manifest_sha:
        raise BundleHold("Manifest does not match expected GitHub Actions hash")
    try:
        doc = json.loads(path.read_bytes())
    except (OSError, ValueError, UnicodeError) as exc:
        raise BundleHold("Invalid preview manifest") from exc
    if (
        not isinstance(doc, dict)
        or doc.get("schema") != 1
        or doc.get("kind") != "smite_offline_preview_images"
        or doc.get("source_repo") != "aghajani82/Smite"
        or doc.get("source_commit") != source_sha
        or doc.get("proposed_version") != "2.0.0-rc.0"
        or doc.get("image_format") != "docker-save-gzip"
        or doc.get("signed") is not False
        or doc.get("registry_digest_verified") is not False
        or doc.get("runtime_security_verified") is not False
        or doc.get("activation_allowed") is not False
    ):
        raise BundleHold("Unexpected or activation-marked preview contract")
    images = doc.get("images")
    if not isinstance(images, dict) or set(images) != set(FILES):
        raise BundleHold("Both Panel and Node archives required")
    seen = set()
    for role, filename in FILES.items():
        item = images[role]
        if not isinstance(item, dict) or item.get("file") != filename:
            raise BundleHold("Unexpected image filename")
        if not IMAGE_ID.fullmatch(str(item.get("local_image_id"))):
            raise BundleHold("Invalid source image ID")
        if not HEX64.fullmatch(str(item.get("archive_sha256"))):
            raise BundleHold("Missing archive SHA256")
        if type(item.get("bytes")) is not int or item["bytes"] < 1:
            raise BundleHold("Invalid archive size")
        digest, count = _hash(folder / filename)
        if digest != item["archive_sha256"] or count != item["bytes"]:
            raise BundleHold("Archive corrupted or replaced")
        seen.add(item["local_image_id"])
    if len(seen) != 2:
        raise BundleHold("Duplicate Panel/Node image ID")
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", type=Path, required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--manifest-sha256", required=True)
    args = p.parse_args(argv)
    try:
        verify(folder=args.folder, source_sha=args.source_sha,
               manifest_sha=args.manifest_sha256)
    except (BundleHold, OSError, TypeError) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 2
    print("STAGE15_TWO_IMAGES=SHA256_VERIFIED")
    print("STAGE15_GIT_SOURCE=EXPECTED_COMMIT_MATCHED")
    print("STAGE15_REGISTRY_OR_IMAGE_ATTESTATION=UNVERIFIED")
    print("STAGE15_RUNTIME_MOUNTS_AND_TLS443=UNVERIFIED")
    print("STAGE15_DEPLOYMENT_AUTHORIZED=NO")
    # Never exit zero: a source + archive hash is insufficient for cutover.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
