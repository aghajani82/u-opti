#!/usr/bin/env python3
"""Read-only pre-admission: verify BOTH immutable, independently signed Smite images.

This command requires independent operator-trusted manifest SHA256, exact source
commit and publisher tag. It reads a candidate created only AFTER both Smite
publisher jobs succeed, then invokes trusted installed cosign to verify EACH
digest and role/source signed claims. Never runs Docker, installs or deploys.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import platform
import shutil
import tempfile
from pathlib import Path
import re
import subprocess
import sys

SHA = re.compile(r"[a-f0-9]{40}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9][a-zA-Z0-9.-]*)?\Z")
ROLES = {"panel", "node"}
COSIGN_SIGNATURE_TYPES = {
    "cosign container image signature",
    "https://sigstore.dev/cosign/sign/v1",
}
REPO = "aghajani82/Smite"
ISSUER = "https://token.actions.githubusercontent.com"
WORKFLOW = "https://github.com/aghajani82/Smite/.github/workflows/publish-images.yml@"
# Explicitly reviewed Sigstore root-signing snapshot: c9aa2600c1492365922f1b3f351a208aa17d0e64
# Source: targets/trusted_root.json. TUF refresh is not claimed for this mode.
TRUSTED_ROOT_SHA256 = "6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66"

# Same official Cosign v3.0.6 linux/amd64 asset SHA pinned by the existing
# RC7 fresh installer. Retained-node *review* must not assume a prior install.
COSIGN_RC7_SOURCE_SHA = "9a1270b31e8d44f13d09b71ab6b9798410b09c12"
COSIGN_RC7_PUBLISH_REF = "refs/tags/v2.0.0-rc.7"
COSIGN_RC7_AMD64_URL = (
    "https://github.com/sigstore/cosign/releases/download/"
    "v3.0.6/cosign-linux-amd64"
)
COSIGN_RC7_AMD64_SHA256 = "c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74"
COSIGN_RC7_MAX_BYTES = 200_000_000

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
        if (signature_type in COSIGN_SIGNATURE_TYPES
                and actual == digest and optional.get("smite_source_sha") == source
                and optional.get("smite_role") == role):
            return True
    return False

def _validated_trusted_root(path: Path | None) -> str | None:
    if path is None:
        return None
    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise AdmissionHold("Invalid selected trusted-root path")
    if path.stat().st_size > 32768:
        raise AdmissionHold("Selected trusted-root file is oversized")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != TRUSTED_ROOT_SHA256:
        raise AdmissionHold("Selected Sigstore trusted-root SHA256 mismatch")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise AdmissionHold("Malformed selected Sigstore trusted-root JSON") from exc
    if (not isinstance(data, dict)
            or data.get("mediaType") != "application/vnd.dev.sigstore.trustedroot+json;version=0.1"
            or not all(isinstance(data.get(k), list) and data[k]
                       for k in ("tlogs", "certificateAuthorities", "ctlogs"))):
        raise AdmissionHold("Selected Sigstore trusted-root shape mismatch")
    return str(path)


@contextmanager
def _review_cosign(*, source_sha: str, publish_ref: str,
                   trusted_root: str | None):
    """Reuse installed Cosign; only RC7 may temporarily stage a pinned asset.

    The fallback is strictly review-only: no package manager, persistent
    executable, Docker, Node/FRP service, or configuration mutation. Every
    temporary byte is removed after both independent image verifications.
    """
    if shutil.which("cosign") is not None or trusted_root is None:
        # Preserve the original fail-closed behavior for historic releases
        # without the separately pinned Sigstore trust root.
        yield "cosign"
        return
    if (source_sha != COSIGN_RC7_SOURCE_SHA
            or publish_ref != COSIGN_RC7_PUBLISH_REF
            or platform.machine() != "x86_64"):
        raise AdmissionHold("Pinned Cosign unavailable for selected release or architecture")
    with tempfile.TemporaryDirectory(prefix="smite-rc7-review-cosign-") as directory:
        binary = Path(directory) / "cosign"
        cmd = [
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--proto", "=https", "--proto-redir", "=https",
            "--connect-timeout", "10", "--max-time", "90",
            "--max-filesize", str(COSIGN_RC7_MAX_BYTES),
            COSIGN_RC7_AMD64_URL, "--output", str(binary),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=95, check=False,
            )
            if result.returncode != 0:
                raise AdmissionHold("Pinned Cosign download unavailable")
            stat = binary.lstat()
            if (not binary.is_file() or binary.is_symlink()
                    or stat.st_nlink != 1
                    or not 0 < stat.st_size <= COSIGN_RC7_MAX_BYTES):
                raise AdmissionHold("Pinned Cosign download untrusted")
            digest = hashlib.sha256()
            with binary.open("rb") as stream:
                for part in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(part)
            if digest.hexdigest() != COSIGN_RC7_AMD64_SHA256:
                raise AdmissionHold("Pinned Cosign SHA256 mismatch")
            binary.chmod(0o700)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdmissionHold("Pinned Cosign download unavailable") from exc
        yield str(binary)


def _unique_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise AdmissionHold("Duplicate JSON field")
        fields[key] = value
    return fields


def verify_pair(*, manifest: Path, manifest_sha256: str,
                source_sha: str, publish_ref: str,
                trusted_root: Path | None = None, runner=None) -> dict:
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
        doc = json.loads(raw, object_pairs_hook=_unique_fields)
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

    trust_root_path = _validated_trusted_root(trusted_root)
    identity = WORKFLOW + publish_ref
    run = subprocess.run if runner is None else runner
    # No ignore-tlog, no ignore-sct, no --check-claims=false or trust in tags.
    with _review_cosign(source_sha=source_sha, publish_ref=publish_ref,
                        trusted_root=trust_root_path) as cosign:
        for role in ("panel", "node"):
            cmd = [
                cosign, "verify",
                *([ "--trusted-root", trust_root_path ] if trust_root_path else []),
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
                result = run(cmd, capture_output=True, text=True, timeout=60,
                                        check=False)
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
                raise AdmissionHold("Trusted cosign verification unavailable") from exc
            if result.returncode != 0 or len(result.stdout) > 512_000:
                raise AdmissionHold("Signature check failed for " + role)
            try:
                signed = json.loads(result.stdout, object_pairs_hook=_unique_fields)
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
    p.add_argument("--trusted-root", type=Path, help="Reviewed, SHA-pinned Sigstore trusted root")
    args = p.parse_args(argv)
    try:
        verify_pair(manifest=args.manifest, manifest_sha256=args.manifest_sha256,
                    source_sha=args.source_sha, publish_ref=args.publish_ref,
                    trusted_root=args.trusted_root)
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
