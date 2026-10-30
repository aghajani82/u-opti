#!/usr/bin/env python3
"""Offline fault-injection for cache-only Secure Web Approval image fetching."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "web_fetch", HERE / "modules/smite-stage15-web-approval-fetch.py"
)
web_fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web_fetch)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.images = {
            "panel": b"mock-panel-image" * 200,
            "node": b"mock-node-image" * 300,
        }
        self.manifest = {
            "schema": 1,
            "kind": "smite_offline_preview_images",
            "source_repo": "aghajani82/Smite",
            "source_commit": web_fetch.SOURCE_SHA,
            "proposed_version": "2.0.0-rc.0",
            "image_format": "docker-save-gzip",
            "signed": False,
            "registry_digest_verified": False,
            "runtime_security_verified": False,
            "activation_allowed": False,
            "images": {
                role: {
                    "file": f"smite-{role}-stage15.docker.tar.gz",
                    "archive_sha256": digest(data),
                    "bytes": len(data),
                    "local_image_id": "sha256:" + (("a" if role == "panel" else "b") * 64),
                }
                for role, data in self.images.items()
            },
        }

    def makezip(self, *, override=None, extra=None):
        if override:
            for key, value in override.items():
                self.manifest[key] = value
        raw = (json.dumps(self.manifest, sort_keys=True) + "\n").encode()
        path = self.root / "artifact.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
            z.writestr("stage15-images.json", raw)
            for role, payload in self.images.items():
                z.writestr(f"smite-{role}-stage15.docker.tar.gz", payload)
            if extra:
                z.writestr(extra, b"unexpected")
        return path, digest(path.read_bytes()), digest(raw)

    def verify(self, path, zip_sha, manifest_sha):
        return web_fetch.verify_zip(
            path, zip_sha=zip_sha,
            manifest_sha=manifest_sha, source=web_fetch.SOURCE_SHA
        )

    def test_valid_exact_pair_and_verified_extraction(self):
        path, zsha, msha = self.makezip()
        manifest = self.verify(path, zsha, msha)
        stage = self.root / "stage"
        stage.mkdir()
        (stage / web_fetch.ZIP_NAME).write_bytes(path.read_bytes())
        with patch.object(web_fetch, "MANIFEST_SHA256", msha):
            web_fetch.extract_to(stage, manifest)
        self.assertEqual((stage / web_fetch.FILES[1]).read_bytes(), self.images["panel"])
        self.assertEqual((stage / web_fetch.FILES[2]).read_bytes(), self.images["node"])

    def test_wrong_zip_digest_fails(self):
        path, _, msha = self.makezip()
        with self.assertRaisesRegex(web_fetch.Hold, "ZIP_SHA256_MISMATCH"):
            self.verify(path, "0" * 64, msha)

    def test_wrong_manifest_digest_fails_even_if_zip_is_trusted(self):
        path, zsha, _ = self.makezip()
        with self.assertRaisesRegex(web_fetch.Hold, "MANIFEST_SHA256_MISMATCH"):
            self.verify(path, zsha, "0" * 64)

    def test_disabled_deployment_flag_is_mandatory(self):
        path, zsha, msha = self.makezip(override={"activation_allowed": True})
        with self.assertRaisesRegex(web_fetch.Hold, "UNTRUSTED_PREVIEW_MANIFEST"):
            self.verify(path, zsha, msha)

    def test_wrong_source_fails(self):
        path, zsha, msha = self.makezip(override={"source_commit": "0" * 40})
        with self.assertRaisesRegex(web_fetch.Hold, "UNTRUSTED_PREVIEW_MANIFEST"):
            self.verify(path, zsha, msha)

    def test_image_content_tamper_fails(self):
        self.manifest["images"]["node"]["archive_sha256"] = "0" * 64
        path, zsha, msha = self.makezip()
        with self.assertRaisesRegex(web_fetch.Hold, "IMAGE_SHA256_MISMATCH"):
            self.verify(path, zsha, msha)

    def test_wrong_image_id_fails(self):
        self.manifest["images"]["node"]["local_image_id"] = "untrusted"
        path, zsha, msha = self.makezip()
        with self.assertRaisesRegex(web_fetch.Hold, "UNTRUSTED_IMAGE_METADATA"):
            self.verify(path, zsha, msha)

    def test_zip_extra_member_fails(self):
        path, zsha, msha = self.makezip(extra="../escape")
        with self.assertRaisesRegex(web_fetch.Hold, "UNEXPECTED_ZIP_MEMBERS"):
            self.verify(path, zsha, msha)

    def test_symlinked_zip_fails(self):
        path, zsha, msha = self.makezip()
        target = self.root / "link.zip"
        target.symlink_to(path)
        with self.assertRaisesRegex(web_fetch.Hold, "UNSAFE_FILE"):
            self.verify(target, zsha, msha)

    def test_cache_only_does_not_publish_runtime_changes(self):
        text = (HERE / "modules/smite-stage15-web-approval-fetch.py").read_text()
        self.assertNotIn("docker load", text.lower())
        self.assertNotIn("docker compose up", text.lower())
        self.assertIn("PREVIEW_ACTIVATION_ALLOWED=NO", text)
        self.assertIn("FRPS_FRPC_RESTART=NO", text)


if __name__ == "__main__":
    unittest.main()
