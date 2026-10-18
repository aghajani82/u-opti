"""Offline Stage15 two-image bundle verification: no Docker, no network."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "modules/smite-stage15-bundle-verify.py"
spec = importlib.util.spec_from_file_location("smite_stage15_verify", FILE)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

SHA = "a" * 40
ID_PANEL = "sha256:" + "b" * 64
ID_NODE = "sha256:" + "c" * 64


def h(data):
    return hashlib.sha256(data).hexdigest()


class Stage15BundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        images = {}
        for role, name, identity, body in (
            ("panel", tool.FILES["panel"], ID_PANEL, b"preview-panel"),
            ("node", tool.FILES["node"], ID_NODE, b"preview-node"),
        ):
            (self.folder / name).write_bytes(body)
            images[role] = {
                "file": name,
                "archive_sha256": h(body),
                "bytes": len(body),
                "local_image_id": identity,
            }
        self.manifest = {
            "schema": 1, "kind": "smite_offline_preview_images",
            "source_repo": "aghajani82/Smite",
            "source_commit": SHA, "proposed_version": "2.0.0-rc.0",
            "image_format": "docker-save-gzip", "images": images,
            "signed": False, "registry_digest_verified": False,
            "runtime_security_verified": False, "activation_allowed": False,
        }
        self.save()

    def save(self):
        (self.folder / "stage15-images.json").write_text(json.dumps(self.manifest))
        self.digest = h((self.folder / "stage15-images.json").read_bytes())

    def check(self, **override):
        args = dict(folder=self.folder, source_sha=SHA, manifest_sha=self.digest)
        args.update(override)
        return tool.verify(**args)

    def test_pair_checksums_and_exact_trusted_source(self):
        result = self.check()
        self.assertEqual(set(result["images"]), {"panel", "node"})
        self.assertFalse(result["activation_allowed"])

    def test_manifest_tamper_rejected_even_if_rechecksums_archives(self):
        self.manifest["activation_allowed"] = True
        self.save()
        with self.assertRaises(tool.BundleHold):
            self.check()
        self.manifest["activation_allowed"] = False
        self.save()
        with self.assertRaises(tool.BundleHold):
            self.check(manifest_sha="f" * 64)

    def test_source_mismatch_and_corrupted_archive_hold(self):
        with self.assertRaises(tool.BundleHold):
            self.check(source_sha="0" * 40)
        (self.folder / tool.FILES["node"]).write_bytes(b"tampered-node")
        with self.assertRaises(tool.BundleHold):
            self.check()

    def test_extra_roles_duplicate_id_or_path_traversal_rejected(self):
        self.manifest["images"]["malicious"] = self.manifest["images"]["panel"]
        self.save()
        with self.assertRaises(tool.BundleHold):
            self.check()
        self.manifest["images"].pop("malicious")
        self.manifest["images"]["node"]["local_image_id"] = ID_PANEL
        self.save()
        with self.assertRaises(tool.BundleHold):
            self.check()
        self.manifest["images"]["node"]["local_image_id"] = ID_NODE
        self.manifest["images"]["panel"]["file"] = "../other.tar.gz"
        self.save()
        with self.assertRaises(tool.BundleHold):
            self.check()

    def test_symlink_archive_or_manifest_rejected(self):
        file = self.folder / tool.FILES["node"]
        file.unlink()
        file.symlink_to(self.folder / tool.FILES["panel"])
        with self.assertRaises(tool.BundleHold):
            self.check()

    def test_cli_all_pass_still_nonzero_and_no_deploy(self):
        with patch("builtins.print") as printer:
            rc = tool.main([
                "--folder", str(self.folder),
                "--source-sha", SHA,
                "--manifest-sha256", self.digest,
            ])
        self.assertEqual(rc, 2)
        report = [str(x.args[0]) for x in printer.call_args_list]
        self.assertIn("STAGE15_DEPLOYMENT_AUTHORIZED=NO", report)
        self.assertIn("STAGE15_TWO_IMAGES=SHA256_VERIFIED", report)

    def test_no_host_network_or_docker_mutation_and_packaging(self):
        source = FILE.read_text()
        for forbidden in ("docker load", "subprocess.run(", "os.system(",
                          "docker compose", "systemctl restart"):
            self.assertNotIn(forbidden, source)
        for name in ("install.sh", "u-opti"):
            self.assertIn("smite-stage15-bundle-verify.py", (ROOT / name).read_text())


if __name__ == "__main__":
    unittest.main()
