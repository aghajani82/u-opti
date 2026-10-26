"""Clean first-install profile accepts only independently pinned paired images."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "modules/smite-clean-image-pair.py"
spec = importlib.util.spec_from_file_location("smite_fresh_image_pair", PATH)
pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pair)

SHA = "e" * 40
PANEL_ID = "sha256:" + "a" * 64
NODE_ID = "sha256:" + "b" * 64


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CleanImagePairTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        archives = {}
        for role, name, img_id in [
            ("panel", "smite-panel-stage15.docker.tar.gz", PANEL_ID),
            ("node", "smite-node-stage15.docker.tar.gz", NODE_ID),
        ]:
            content = (role + "-unit-test-no-live-image").encode()
            (self.folder / name).write_bytes(content)
            archives[role] = {
                "file": name, "archive_sha256": digest(content),
                "bytes": len(content), "local_image_id": img_id,
            }
        self.manifest = {
            "schema": 1, "kind": "smite_offline_preview_images",
            "source_repo": "aghajani82/Smite",
            "source_commit": SHA,
            "proposed_version": "2.0.0-rc.0",
            "image_format": "docker-save-gzip",
            "images": archives,
            "signed": False,
            "registry_digest_verified": False,
            "runtime_security_verified": False,
            "activation_allowed": False,
        }
        self.path = self.folder / "stage15-images.json"
        self.persist()

    def persist(self):
        self.path.write_text(json.dumps(self.manifest))
        self.manifest_hash = digest(self.path.read_bytes())

    def check(self, **overrides):
        params = dict(folder=self.folder, source_sha=SHA,
                      manifest_sha256=self.manifest_hash)
        params.update(overrides)
        return pair.inspected_pair(**params)

    def test_both_paired_images_and_independent_manifest_sha(self):
        output = self.check()
        self.assertEqual(output["panel_image_id"], PANEL_ID)
        self.assertEqual(output["node_image_id"], NODE_ID)
        self.assertEqual(output["source_commit"], SHA)
        self.assertEqual(output["panel_archive"].parent, self.folder)
        self.assertEqual(output["node_archive"].parent, self.folder)

    def test_wrong_sha_and_damaged_archive_fail(self):
        with self.assertRaises(pair.FreshInstallHold):
            self.check(source_sha="0" * 40)
        with self.assertRaises(pair.FreshInstallHold):
            self.check(manifest_sha256="1" * 64)
        (self.folder / "smite-node-stage15.docker.tar.gz").write_bytes(b"corrupted")
        with self.assertRaises(pair.FreshInstallHold):
            self.check()

    def test_no_unsigned_live_install_or_legacy_fallback(self):
        self.manifest["activation_allowed"] = True
        self.persist()
        with self.assertRaises(pair.FreshInstallHold):
            self.check()
        self.manifest["activation_allowed"] = False
        self.persist()
        self.assertEqual(
            pair.main([
                "--folder", str(self.folder), "--source-sha", SHA,
                "--manifest-sha256", self.manifest_hash,
            ]), 0,
        )
        for filename in ("install.sh", "u-opti"):
            self.assertIn("smite-clean-image-pair.py", (ROOT / filename).read_text())
        source = PATH.read_text()
        for unsafe in ("subprocess.run(", "docker pull", "docker load", "os.system("):
            self.assertNotIn(unsafe, source)


if __name__ == "__main__":
    unittest.main()
