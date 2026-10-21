#!/usr/bin/env python3
"""Read-only pre-admission: verify BOTH immutable, independently signed Smite images.

This command requires independent operator-trusted manifest SHA256, exact source
commit and publisher tag. It reads a candidate created only AFTER both Smite
publisher jobs succeed, then invokes trusted installed cosign to verify EACH
digest and role/source signed claims. Never runs Docker, installs or deploys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

SHA = re.compile(r"[a-f0-9]{40}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9][a-zA-Z0-9.-]*)?\Z")
ROLES = {"panel", "node"}
REPO = "aghajani82/Smite"
ISSUER = "https://token.actions.githubusercontent.com"
WORKFLOW = "https://github.com/aghajani82/Smite/.github/workflows/publish-images.yml@"

class AdmissionHold(ValueError):
    pass

def _signed_payload_match(result: object, *, digest: str, role: str, source: str) -> bool:
    # Cosign JSON output may be either one Simple-Signing object or a list
    # of such objects. Normalize only those two shapes; everything else
    # remains fail-closed.
    if isinstance(result, dict):
        records = [result]
    elif isinstance(result, list):
        records = result
    else:
        return False
    if not records:
        return False
    for record in records:
        if not isinstance(record, dict):
            continue
        critical = record.get("critical", record.get("Critical"))
        optional = record.get("optional", record.get("Optional"))
        if not isinstance(critical, dict) or not isinstance(optional, dict):
            continue
        image = critical.get("image", critical.get("Image"))
        if not isinstance(image, dict):
            continue
        actual = image.get("docker-manifest-digest", image.get("Docker-manifest-digest"))
        signature_type = critical.get("type", critical.get("Type"))
        if (signature_type == "cosign container image signature"
                and actual == digest and optional.get("smite_source_sha") == source
                and optional.get("smite_role") == role):
            return True
    return False

def verify_pair(*, manifest: Path, manifest_sha256: str,
                source_sha: str, publish_ref: str) -> dict:
    if not isinstance(manifest_sha256, str) or not HASH.fullmatch(manifest_sha256):
        raise AdmissionHold("Independent manifest SHA256 required")
    if not isinstance(source_sha, str) or not SHA.fullmatch(source_sha):
        raise AdmissionHold("Independent immutable source commit required")
    if not isinstance(publish_ref, str) or not publish_ref.startswith("refs/tags/v"):
        raise AdmissionHold("Independent release tag required")
    version = publish_ref[len("refs/tags/v"):]
    if not VERSION.fullmatch(version):
        raise AdmissionHold("Invalid exact version tag")
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 32768:
        raise AdmissionHold("Invalid or oversized manifest")
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest_sha256:
        raise AdmissionHold("Manifest SHA256 does not match trusted checkpoint")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise AdmissionHold("Malformed JSON") from exc
    if (not isinstance(doc, dict)
            or set(doc) != {"schema", "kind", "source_repo", "source_commit",
                            "publish_ref", "version", "images", "activation_allowed",
                            "release_approved"}
            or type(doc.get("schema")) is not int or doc["schema"] != 1
            or doc.get("kind") != "smite_signed_registry_pair_candidate"
            or doc.get("source_repo") != REPO
            or doc.get("source_commit") != source_sha
            or doc.get("publish_ref") != publish_ref
            or doc.get("version") != version
            or doc.get("activation_allowed") is not False
            or doc.get("release_approved") is not False):
        raise AdmissionHold("Candidate contract or external pin mismatch")
    images = doc.get("images")
    if not isinstance(images, dict) or set(images) != ROLES:
        raise AdmissionHold("Exactly Panel and Node required")
    refs = {}
    digests = {}
    for role in ("panel", "node"):
        value = images[role]
        prefix = "ghcr.io/aghajani82/smite-" + role + "@"
        if not isinstance(value, str) or not value.startswith(prefix):
            raise AdmissionHold("Wrong image repository or role")
        digest = value[len(prefix):]
        if not DIGEST.fullmatch(digest):
            raise AdmissionHold("Invalid registry manifest digest")
        refs[role] = value
        digests[role] = digest
    if digests["panel"] == digests["node"]:
        raise AdmissionHold("Duplicate Panel and Node digests")

    identity = WORKFLOW + publish_ref
    # No ignore-tlog, no ignore-sct, no --check-claims=false or trust in tags.
    for role in ("panel", "node"):
        cmd = [
            "cosign", "verify",
            "--certificate-identity=" + identity,
            "--certificate-oidc-issuer=" + ISSUER,
            "--certificate-github-workflow-sha=" + source_sha,
            "--certificate-github-workflow-repository=" + REPO,
            "--certificate-github-workflow-trigger=workflow_dispatch",
            "-a", "smite_source_sha=" + source_sha,
            "-a", "smite_role=" + role,
            refs[role],
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                    check=False)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            raise AdmissionHold("Trusted cosign verification unavailable") from exc
        if result.returncode != 0 or len(result.stdout) > 512_000:
            raise AdmissionHold("Signature check failed for " + role)
        try:
            signed = json.loads(result.stdout)
        except (ValueError, UnicodeError) as exc:
            raise AdmissionHold("Invalid signature payload for " + role) from exc
        if not _signed_payload_match(signed, digest=digests[role],
                                     role=role, source=source_sha):
            raise AdmissionHold("Signed digest/source/role mismatch for " + role)
    return {"source_sha": source_sha, "publish_ref": publish_ref, "images": refs}

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--manifest-sha256", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--publish-ref", required=True)
    args = p.parse_args(argv)
    try:
        verify_pair(manifest=args.manifest, manifest_sha256=args.manifest_sha256,
                    source_sha=args.source_sha, publish_ref=args.publish_ref)
    except (AdmissionHold, OSError, TypeError) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 2
    print("PANEL_NODE_IMMUTABLE_DIGEST_SIGNATURES=VERIFIED")
    print("SAME_REVIEWED_SMITE_SOURCE_AND_TAG=VERIFIED")
    print("EXTERNAL_RELEASE_APPROVAL=NOT_PROVEN")
    print("REPLAY_RECOVERY_AND_HOST_EXECUTOR=NOT_PROVEN")
    print("DEPLOYMENT_AUTHORIZED=NO")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
