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
import zlib
import tarfile

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


def inspect_archive(path: Path, *, role: str, source_sha: str, image_id: str) -> dict:
    """Bind Docker config to OCI index without extracting or executing archives.

    Docker classic stores a config ID; containerd may report an OCI index ID.
    Return both explicitly. Neither is a registry signature or deployment grant.
    """
    if role not in FILES or not HEX40.fullmatch(source_sha) or not IMAGE_ID.fullmatch(image_id):
        raise BundleHold("Invalid archive identity request")
    if path.is_symlink() or not path.is_file():
        raise BundleHold("Missing or symlinked archive")
    small, digests, sizes, unpacked = {}, {}, {}, {}
    total = retained = expanded = 0
    try:
        with tarfile.open(path, "r|gz") as archive:
            seen = set()
            for member in archive:
                name = member.name
                if (name in seen or name.startswith("/") or ".." in name.split("/")
                        or "\\" in name or len(seen) >= 4096):
                    raise BundleHold("Duplicate or unsafe archive member")
                seen.add(name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise BundleHold("Archive links and special files forbidden")
                total += member.size
                if total > 5_000_000_000:
                    raise BundleHold("Expanded archive too large")
                stream = archive.extractfile(member)
                digest = hashlib.sha256()
                data = bytearray() if member.size <= 1_000_000 else None
                uncompressed = hashlib.sha256()
                decoder = None
                first = True
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    if first:
                        decoder = zlib.decompressobj(31) if block.startswith(b"\x1f\x8b") else None
                        first = False
                    if decoder is None:
                        uncompressed.update(block)
                    else:
                        pending = block
                        while pending:
                            output = decoder.decompress(pending, 1024 * 1024)
                            expanded += len(output)
                            if expanded > 5_000_000_000:
                                raise BundleHold("Expanded layer limit exceeded")
                            uncompressed.update(output)
                            pending = decoder.unconsumed_tail
                        if decoder.unused_data:
                            raise BundleHold("Trailing compressed layer data")
                    digest.update(block)
                    if data is not None:
                        data.extend(block)
                if decoder is not None and not decoder.eof:
                    raise BundleHold("Truncated compressed layer")
                unpacked[name] = uncompressed.hexdigest()
                digests[name], sizes[name] = digest.hexdigest(), member.size
                if name.startswith("blobs/sha256/") and name != "blobs/sha256/" + digest.hexdigest():
                    raise BundleHold("OCI blob content digest mismatch")
                if data is not None:
                    retained += len(data)
                    if retained > 32_000_000:
                        raise BundleHold("Archive metadata too large")
                    small[name] = bytes(data)
        def document(name):
            return json.loads(small[name])
        def descriptor(item):
            value = item["digest"]
            if not IMAGE_ID.fullmatch(value):
                raise BundleHold("Unsupported OCI digest")
            name = "blobs/sha256/" + value[7:]
            if digests[name] != value[7:] or sizes[name] != item["size"]:
                raise BundleHold("OCI descriptor mismatch")
            return name
        manifests = document("manifest.json")
        if len(manifests) != 1 or manifests[0]["RepoTags"] != ["smite-" + role + ":stage15-local"]:
            raise BundleHold("Unexpected Docker archive tag or image count")
        docker = manifests[0]
        config_name = docker["Config"]
        config_id = "sha256:" + digests[config_name]
        config = document(config_name)
        if (config["architecture"] != "amd64" or config["os"] != "linux"
                or config["config"]["Labels"]["org.opencontainers.image.revision"] != source_sha):
            raise BundleHold("Image platform or source revision mismatch")
        layers = docker["Layers"]
        if not layers or len(set(layers)) != len(layers) or any(x not in digests for x in layers):
            raise BundleHold("Missing or duplicate image layers")
        if config["rootfs"]["diff_ids"] != ["sha256:" + unpacked[x] for x in layers]:
            raise BundleHold("Docker layer content mismatch")
        index_id = None
        if "index.json" in small:
            top = document("index.json")["manifests"]
            if len(top) != 1:
                raise BundleHold("Ambiguous OCI image index")
            root_name = descriptor(top[0])
            index_id = top[0]["digest"]
            root = document(root_name)
            if "manifests" in root:
                selected = [x for x in root["manifests"] if x.get("platform") == {"architecture":"amd64", "os":"linux"}]
                if len(selected) != 1:
                    raise BundleHold("Ambiguous OCI runtime platform")
                for item in root["manifests"]:
                    descriptor(item)
                root = document(descriptor(selected[0]))
            if descriptor(root["config"]) != config_name:
                raise BundleHold("OCI config differs from Docker config")
            if [descriptor(x) for x in root["layers"]] != layers:
                raise BundleHold("OCI layers differ from Docker layers")
        if image_id not in (config_id, index_id):
            raise BundleHold("Build image ID is not bound to archive")
        return dict(role=role, source_commit=source_sha, config_id=config_id,
                    index_id=index_id, build_image_id=image_id, activation_allowed=False)
    except (KeyError, TypeError, ValueError, tarfile.TarError, zlib.error, EOFError) as exc:
        if isinstance(exc, BundleHold):
            raise
        raise BundleHold("Invalid Docker/OCI archive") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", type=Path, required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--manifest-sha256", required=True)
    p.add_argument("--inspect-archives", action="store_true")
    args = p.parse_args(argv)
    try:
        doc = verify(folder=args.folder, source_sha=args.source_sha,
               manifest_sha=args.manifest_sha256)
        if args.inspect_archives:
            for role, item in doc["images"].items():
                print(json.dumps(inspect_archive(args.folder / item["file"], role=role,
                    source_sha=args.source_sha, image_id=item["local_image_id"]), sort_keys=True))
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
