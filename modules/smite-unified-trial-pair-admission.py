#!/usr/bin/env python3
"""Read-only verifier for TWO branch-scoped Smite unified-install trial digests.

This is NOT a production release verifier. Both registry signatures must match
the exact trial workflow identity, commit, role and OIDC issuer. The independent
manifest hash must be supplied by the operator, not read from the manifest.
No Docker, secrets, Node runtime, FRP, Nginx, Sanaei or installer mutations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

SOURCE = re.compile(r"[a-f0-9]{40}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")
REF = "refs/heads/trial/unified-smite-install"
WORKFLOW = ("https://github.com/aghajani82/Smite/.github/workflows/"
            "unified-install-signed-trial.yml@" + REF)
ISSUER = "https://token.actions.githubusercontent.com"
ROOT_SHA256 = "6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66"


class Hold(ValueError):
    pass


def deny():
    raise Hold("Signed unified trial pair admission HOLD")


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            deny()
        result[key] = value
    return result


def safe_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=no_duplicates)
    except (ValueError, TypeError, UnicodeError):
        deny()


def read_regular(path, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        deny()
    info = path.stat()
    if info.st_nlink != 1 or not 0 < info.st_size <= limit:
        deny()
    return path.read_bytes()


def _signed_payload_match(doc, *, digest, role, source):
    if isinstance(doc, dict):
        records = [doc]
    elif isinstance(doc, list):
        records = doc
    else:
        return False
    if not records:
        return False
    for entry in records:
        if not isinstance(entry, dict):
            continue
        critical = entry.get("critical", entry.get("Critical"))
        optional = entry.get("optional", entry.get("Optional"))
        if not isinstance(critical, dict) or not isinstance(optional, dict):
            continue
        image = critical.get("image", critical.get("Image"))
        if not isinstance(image, dict):
            continue
        actual = image.get("docker-manifest-digest",
                           image.get("Docker-manifest-digest"))
        if (critical.get("type", critical.get("Type")) in
                {"cosign container image signature", "https://sigstore.dev/cosign/sign/v1"}
                and actual == digest
                and optional.get("smite_source_sha") == source
                and optional.get("smite_role") == role
                and optional.get("smite_trial") == "unified-install"):
            return True
    return False


def verify(*, manifest, manifest_sha256, source_sha, trusted_root,
           cosign="cosign", runner=subprocess.run):
    if (not isinstance(manifest_sha256, str) or not SHA256.fullmatch(manifest_sha256)
            or not isinstance(source_sha, str) or not SOURCE.fullmatch(source_sha)):
        deny()
    data = read_regular(manifest, 32_768)
    if hashlib.sha256(data).hexdigest() != manifest_sha256:
        deny()
    doc = safe_json(data)
    if (not isinstance(doc, dict)
            or set(doc) != {"schema", "kind", "source_repo", "source_commit",
                            "publish_ref", "version", "images",
                            "activation_allowed", "release_approved"}
            or type(doc["schema"]) is not int or doc["schema"] != 1
            or doc["kind"] != "smite_unified_install_signed_trial_candidate"
            or doc["source_repo"] != "aghajani82/Smite"
            or doc["source_commit"] != source_sha
            or doc["publish_ref"] != REF
            or doc["version"] != "2.0.0-unified-install-trial"
            or doc["activation_allowed"] is not False
            or doc["release_approved"] is not False):
        deny()
    images = doc["images"]
    if not isinstance(images, dict) or set(images) != {"panel", "node"}:
        deny()
    refs, digests = {}, {}
    for role in ("panel", "node"):
        value = images[role]
        prefix = "ghcr.io/aghajani82/smite-" + role + "@"
        if not isinstance(value, str) or not value.startswith(prefix):
            deny()
        digest = value[len(prefix):]
        if not DIGEST.fullmatch(digest):
            deny()
        refs[role], digests[role] = value, digest
    if digests["panel"] == digests["node"]:
        deny()
    root = read_regular(trusted_root, 32_768)
    if hashlib.sha256(root).hexdigest() != ROOT_SHA256:
        deny()
    trusted = safe_json(root)
    if (not isinstance(trusted, dict)
            or trusted.get("mediaType") !=
                "application/vnd.dev.sigstore.trustedroot+json;version=0.1"
            or not all(isinstance(trusted.get(k), list) and trusted[k]
                       for k in ("tlogs", "certificateAuthorities", "ctlogs"))):
        deny()
    for role in ("panel", "node"):
        command = [
            cosign, "verify", "--trusted-root", str(trusted_root),
            "--certificate-identity=" + WORKFLOW,
            "--certificate-oidc-issuer=" + ISSUER,
            "--certificate-github-workflow-repository=aghajani82/Smite",
            "--certificate-github-workflow-trigger=push",
            "--certificate-github-workflow-sha=" + source_sha,
            "-a", "smite_source_sha=" + source_sha,
            "-a", "smite_role=" + role,
            "-a", "smite_trial=unified-install",
            refs[role],
        ]
        try:
            outcome = runner(command, capture_output=True, text=True,
                             check=False, timeout=80)
        except (OSError, subprocess.TimeoutExpired):
            deny()
        if outcome.returncode != 0 or len(outcome.stdout) > 512_000:
            deny()
        signed = safe_json(outcome.stdout)
        if not _signed_payload_match(signed, digest=digests[role],
                                     role=role, source=source_sha):
            deny()
    return {"status": "verified_trial_pair", "source_sha": source_sha,
            "panel": refs["panel"], "node": refs["node"],
            "host_activation_allowed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--trusted-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(manifest=args.manifest,
                        manifest_sha256=args.manifest_sha256,
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
