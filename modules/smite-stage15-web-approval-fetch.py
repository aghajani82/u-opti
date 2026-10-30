#!/usr/bin/env python3
"""Download and verify the exact Stage15 Secure Web Approval PREVIEW image pair.

This is a CACHE-ONLY operation.  It MUST NOT load Docker images, update
Compose, change live services, or interpret the preview manifest as permission
to deploy.  Publication to the pinned prerelease is separately reviewed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

SOURCE_SHA = "1f28222d80c29a9423da445c7e977cbc1867aead"
ZIP_SHA256 = "d7a5ab438b45bd05a46b42e97c9d925c3379adc6a06057e542b38091829bf63a"
MANIFEST_SHA256 = "8c1e86220090ad960344d938c1d1d4c30ab656b07c54aff22a16e5d61482b4eb"
TAG = "stage15-web-approval-images-1f28222d"
ZIP_NAME = "smite-stage15-offline-images-1f28222d.zip"
ROOT = Path("/var/lib/u-opti/smite-stage15-web-approval-images")
CACHE = ROOT / SOURCE_SHA
RELEASE_URL = ("https://github.com/aghajani82/Smite/releases/download/"
               + TAG + "/" + ZIP_NAME)
FILES = ("stage15-images.json",
         "smite-panel-stage15.docker.tar.gz",
         "smite-node-stage15.docker.tar.gz")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
MAX_ZIP_BYTES = 1_000_000_000
MAX_EXTRACTED_BYTES = 1_500_000_000


class Hold(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_file(path: Path) -> os.stat_result:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise Hold("UNSAFE_FILE")
    return st


def validate_manifest(raw: bytes, source: str) -> dict:
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Hold("INVALID_MANIFEST") from exc
    if not isinstance(data, dict):
        raise Hold("INVALID_MANIFEST")
    fixed = {
        "schema": 1,
        "kind": "smite_offline_preview_images",
        "source_repo": "aghajani82/Smite",
        "source_commit": source,
        "proposed_version": "2.0.0-rc.0",
        "image_format": "docker-save-gzip",
        "signed": False,
        "registry_digest_verified": False,
        "runtime_security_verified": False,
        "activation_allowed": False,
    }
    if any(data.get(k) != v or type(data.get(k)) is not type(v)
           for k, v in fixed.items()):
        raise Hold("UNTRUSTED_PREVIEW_MANIFEST")
    images = data.get("images")
    if not isinstance(images, dict) or set(images) != {"panel", "node"}:
        raise Hold("INVALID_IMAGE_PAIR")
    ids = set()
    for role, name in zip(("panel", "node"), FILES[1:]):
        item = images[role]
        if not isinstance(item, dict) or item.get("file") != name:
            raise Hold("WRONG_IMAGE_FILENAME")
        if (not isinstance(item.get("archive_sha256"), str)
            or not SHA64.fullmatch(item["archive_sha256"])
            or type(item.get("bytes")) is not int
            or not 0 < item["bytes"] <= MAX_EXTRACTED_BYTES
            or not isinstance(item.get("local_image_id"), str)
            or not IMAGE_ID.fullmatch(item["local_image_id"])):
            raise Hold("UNTRUSTED_IMAGE_METADATA")
        ids.add(item["local_image_id"])
    if len(ids) != 2:
        raise Hold("DUPLICATE_IMAGE_IDENTITIES")
    return data


def verify_zip(path: Path, *, zip_sha: str = ZIP_SHA256,
               manifest_sha: str = MANIFEST_SHA256,
               source: str = SOURCE_SHA) -> dict:
    st = safe_file(path)
    if not 0 < st.st_size <= MAX_ZIP_BYTES:
        raise Hold("UNEXPECTED_ZIP_SIZE")
    if sha256_file(path) != zip_sha:
        raise Hold("ZIP_SHA256_MISMATCH")
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) != len(FILES) or set(i.filename for i in infos) != set(FILES):
                raise Hold("UNEXPECTED_ZIP_MEMBERS")
            if (sum(i.file_size for i in infos) > MAX_EXTRACTED_BYTES
                or any(i.is_dir() or i.file_size <= 0 for i in infos)):
                raise Hold("UNSAFE_ZIP_LAYOUT")
            for info in infos:
                mode = (info.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG):
                    raise Hold("NON_REGULAR_ZIP_MEMBER")
            manifest_info = z.getinfo(FILES[0])
            if manifest_info.file_size > 131072:
                raise Hold("OVERSIZED_MANIFEST")
            raw = z.read(FILES[0])
            if hashlib.sha256(raw).hexdigest() != manifest_sha:
                raise Hold("MANIFEST_SHA256_MISMATCH")
            manifest = validate_manifest(raw, source)
            for role in ("panel", "node"):
                item = manifest["images"][role]
                info = z.getinfo(item["file"])
                if info.file_size != item["bytes"]:
                    raise Hold("IMAGE_SIZE_MISMATCH")
                digest = hashlib.sha256()
                size = 0
                with z.open(info) as src:
                    for block in iter(lambda: src.read(1024 * 1024), b""):
                        size += len(block)
                        if size > item["bytes"]:
                            raise Hold("IMAGE_SIZE_OVERFLOW")
                        digest.update(block)
                if size != item["bytes"] or digest.hexdigest() != item["archive_sha256"]:
                    raise Hold("IMAGE_SHA256_MISMATCH")
            return manifest
    except (zipfile.BadZipFile, RuntimeError, EOFError, OSError) as exc:
        raise Hold("INVALID_ZIP_ARCHIVE") from exc


def extract_to(stage: Path, manifest: dict) -> None:
    with zipfile.ZipFile(stage / ZIP_NAME) as z:
        for name in FILES:
            dest = stage / name
            with z.open(name) as src, dest.open("xb") as out:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    out.write(chunk)
            dest.chmod(0o600)
    if sha256_file(stage / FILES[0]) != MANIFEST_SHA256:
        raise Hold("EXTRACTED_MANIFEST_MISMATCH")
    for role in ("panel", "node"):
        info = manifest["images"][role]
        dest = stage / info["file"]
        if dest.stat().st_size != info["bytes"] or sha256_file(dest) != info["archive_sha256"]:
            raise Hold("EXTRACTED_ARCHIVE_MISMATCH")


def trusted_cache_root() -> None:
    for path in (Path("/var"), Path("/var/lib"), Path("/var/lib/u-opti")):
        if path.exists() or path.is_symlink():
            st = path.lstat()
            if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0
                or st.st_mode & 0o022):
                raise Hold("UNTRUSTED_CACHE_PARENT")
        else:
            path.mkdir(mode=0o700)
    if ROOT.exists() or ROOT.is_symlink():
        st = ROOT.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0
            or stat.S_IMODE(st.st_mode) != 0o700):
            raise Hold("UNTRUSTED_CACHE_DIRECTORY")
    else:
        ROOT.mkdir(mode=0o700)


def verify_cache() -> None:
    st = CACHE.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
        raise Hold("UNTRUSTED_EXISTING_CACHE")
    manifest = verify_zip(CACHE / ZIP_NAME)
    for name in FILES:
        st_file = safe_file(CACHE / name)
        if st_file.st_uid != 0 or st_file.st_mode & 0o077:
            raise Hold("UNTRUSTED_CACHE_FILE")
    if sha256_file(CACHE / FILES[0]) != MANIFEST_SHA256:
        raise Hold("CACHE_MANIFEST_MISMATCH")
    for role in ("panel", "node"):
        item = manifest["images"][role]
        dest = CACHE / item["file"]
        if dest.stat().st_size != item["bytes"] or sha256_file(dest) != item["archive_sha256"]:
            raise Hold("CACHE_ARCHIVE_MISMATCH")


def fetch() -> None:
    if os.geteuid() != 0 or os.uname().nodename.split(".")[0].lower() not in ("ir", "kh"):
        raise Hold("DISPOSABLE_IR_KH_ROOT_ONLY")
    if os.uname().machine != "x86_64":
        raise Hold("REVIEWED_IMAGES_AMD64_ONLY")
    trusted_cache_root()
    lock_fd = os.open(ROOT / ".download.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise Hold("INVALID_CACHE_LOCK")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if CACHE.exists() or CACHE.is_symlink():
            verify_cache()
        else:
            stage = Path(tempfile.mkdtemp(prefix=".incoming-", dir=ROOT))
            try:
                cmd = ["curl", "--fail", "--silent", "--show-error", "--location",
                       "--proto", "=https", "--proto-redir", "=https",
                       "--connect-timeout", "20", "--max-time", "1200",
                       "--retry", "3", "--max-filesize", str(MAX_ZIP_BYTES),
                       "--output", str(stage / ZIP_NAME), RELEASE_URL]
                subprocess.run(cmd, check=True, timeout=1230)
                (stage / ZIP_NAME).chmod(0o600)
                manifest = verify_zip(stage / ZIP_NAME)
                extract_to(stage, manifest)
                stage.rename(CACHE)  # Publish only a fully verified directory.
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        print("STAGE15_WEB_APPROVAL_CACHE=VERIFIED")
        print("CACHE_PATH=" + str(CACHE))
        print("SOURCE_SHA=" + SOURCE_SHA)
        print("PREVIEW_ACTIVATION_ALLOWED=NO")
        print("DOCKER_LOAD=NO")
        print("COMPOSE_UP=NO")
        print("FRPS_FRPC_RESTART=NO")
        print("RUNTIME_CHANGES=NONE")
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    try:
        fetch()
    except (Hold, OSError, subprocess.SubprocessError, ValueError) as exc:
        if isinstance(exc, Hold):
            msg = str(exc)
        else:
            msg = "DOWNLOAD_OR_CACHE_FAILURE"
        print("HOLD: " + msg, file=sys.stderr)
        raise SystemExit(2)
