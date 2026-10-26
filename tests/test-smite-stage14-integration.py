"""Cross-repository Stage14 source contract; never authorizes deployment."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release/smite-stage14-integration-review.json"
SMITE = Path(os.environ.get("SMITE_STAGE14_SOURCE", ROOT / ".stage14-smite-not-checked-out"))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stage14IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(MANIFEST.read_text())

    def test_review_is_unpublished_and_source_is_pinned(self):
        self.assertEqual(self.lock["schema"], 1)
        self.assertFalse(self.lock["release"]["published"])
        self.assertFalse(self.lock["release"]["production_ready"])
        self.assertFalse(self.lock["activation_allowed"])
        self.assertFalse(self.lock["automatic_deployment"])
        self.assertIsNone(self.lock["release"]["release_tag"])
        self.assertGreaterEqual(len(self.lock["unverified_requirements"]), 7)
        head = subprocess.run(["git", "-C", str(SMITE), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(head, self.lock["sources"]["smite"]["commit"])
        upstream = json.loads((SMITE / "release/stage14-review-contract.json").read_text())
        self.assertFalse(upstream["activation_allowed"])
        self.assertEqual(upstream["release"]["proposed_version"],
                         self.lock["release"]["proposed_version"])
        self.assertEqual((SMITE / "panel/app/node_auth.py").read_bytes(),
                         (SMITE / "node/app/node_auth.py").read_bytes())

    def test_admin_overlay_legacy_and_new_source_compatibility(self):
        helper = load(ROOT / "modules/smite-panel-auth-overlay.py", "stage14_admin")
        upgraded_main = (SMITE / "panel/main.py").read_text()
        unchanged, modified = helper.patch(upgraded_main)
        self.assertFalse(modified)
        self.assertEqual(unchanged, upgraded_main)
        self.assertIn("signed_nodes.router", unchanged)
        self.assertIn("node_pairing.router", unchanged)
        wrapper = (ROOT / "modules/smite.sh").read_text()
        anchor = 'docker cp smite-panel:/app/main.py "$SMITE_OVERLAY_DIR/panel/main.py"'
        invoke = '"$auth_helper_dir/smite-panel-auth-overlay.py"'
        self.assertEqual(wrapper.count(anchor), 1)
        self.assertEqual(wrapper.count(invoke), 1)
        self.assertLess(wrapper.index(anchor), wrapper.index(invoke))

    def test_real_uopti_hmac_passes_real_smite_node_verifier(self):
        gateway = load(ROOT / "modules/smite-foreign-gateway-signed-check.py",
                       "stage14_uopti_gateway")
        verifier = load(SMITE / "node/app/node_auth.py", "stage14_smite_hmac")
        uuid = "bbbbbbbb-1111-2222-3333-444444444444"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "identity"
            folder.mkdir(mode=0o700)
            file = folder / "node-identity.json"
            file.write_text(json.dumps({"node_id": uuid, "node_secret": "a" * 64}))
            file.chmod(0o600)
            now = int(time.time())
            req = gateway.build_signed_request(
                domain="panel.example.org",
                node_name="node-kh",
                control_url="https://kh.example.org/control/example/",
                identity=file, moment=now, nonce="b" * 32,
            )
            self.assertEqual(req.method, "POST")
            self.assertEqual(req.full_url,
                             "https://panel.example.org/api/node-control/gateway-check")
            headers = dict(req.header_items())
            args = dict(
                secret=b"a" * 64, node_id=uuid,
                method="POST", target="/api/node-control/gateway-check",
                headers=headers, now=now,
            )
            self.assertTrue(verifier.verify_request(
                **args, body=req.data, replay=verifier.NonceWindow()
            ))
            self.assertFalse(verifier.verify_request(
                **args, body=req.data + b" ", replay=verifier.NonceWindow()
            ))
            replay = verifier.NonceWindow()
            self.assertTrue(verifier.verify_request(**args, body=req.data, replay=replay))
            self.assertFalse(verifier.verify_request(**args, body=req.data, replay=replay))

    def test_activation_blocked_and_legacy_images_not_switched(self):
        installer = (ROOT / "modules/smite-install.sh").read_text()
        self.assertIn("SMITE_UPSTREAM_VERSION=", installer)
        self.assertIn(":-0.1.7", installer)
        self.assertFalse(self.lock["release"]["oci_images_published"])
        self.assertTrue((ROOT / "modules/smite-node-auth-candidate.py").exists())
        self.assertTrue((ROOT / "modules/smite-stage13-preflight.py").exists())
        self.assertIn("STAGE13_DEPLOYMENT_AUTHORIZED=NO",
                      (ROOT / "modules/smite-stage13-preflight.py").read_text())

    def test_installer_and_ci_include_sibling_pr27_guard(self):
        for path in ("install.sh", "u-opti"):
            self.assertIn("smite-panel-auth-overlay.py", (ROOT / path).read_text())
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("test-smite-panel-auth-overlay.py", ci)
        self.assertIn("test-smite-stage14-integration.py", ci)


if __name__ == "__main__":
    unittest.main()
