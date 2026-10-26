#!/usr/bin/env python3
"""Offline RC.2 digest handoff: no installer/runtime activation."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "modules/smite-rc2-signed-registry-candidate.json"
RC1 = ROOT / "modules/smite-field-trial-candidate.json"
INSTALLER = ROOT / "modules/smite-install.sh"
PAIRING = ROOT / "modules/smite-node-pairing.py"
EXPECTED_MANIFEST_HASH = (
    "63e3efbdec955e92deaf0a84c86cc5c8a950f48b4e0d6d301bc7f7c8354eb80b"
)
SOURCE = "e6c3ecce81010130ae28e7d1e37ea99b31d70c28"
PANEL = (
    "ghcr.io/aghajani82/smite-panel@sha256:"
    "9101898e19631d334b754ba8e956b63ab7dfaee304a8f9b954cf30a185125e8e"
)
NODE = (
    "ghcr.io/aghajani82/smite-node@sha256:"
    "2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78"
)


class RC2HandoffTests(unittest.TestCase):
    def test_exact_runner_manifest_sha256_and_source(self):
        raw = CANDIDATE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), EXPECTED_MANIFEST_HASH)
        doc = json.loads(raw)
        self.assertEqual(doc, {
            "activation_allowed": False,
            "images": {"node": NODE, "panel": PANEL},
            "kind": "smite_signed_registry_pair_candidate",
            "publish_ref": "refs/tags/v2.0.0-rc.2",
            "release_approved": False,
            "schema": 1,
            "source_commit": SOURCE,
            "source_repo": "aghajani82/Smite",
            "version": "2.0.0-rc.2",
        })
        self.assertNotEqual(doc["images"]["node"], doc["images"]["panel"])
        for role in ("node", "panel"):
            self.assertRegex(
                doc["images"][role],
                r"^ghcr\.io/aghajani82/smite-" + role + r"@sha256:[0-9a-f]{64}$"
            )
        self.assertFalse(doc["activation_allowed"])
        self.assertFalse(doc["release_approved"])

    def test_do_not_implicitly_promote_rc2_to_live_install_profile(self):
        historical = json.loads(RC1.read_bytes())
        self.assertEqual(historical["version"], "2.0.0-rc.1")
        self.assertNotEqual(historical["images"]["node"], NODE)
        self.assertNotEqual(historical["images"]["panel"], PANEL)
        installer = INSTALLER.read_text()
        self.assertIn("SMITE_INSTALL_PROFILE=", installer)
        self.assertIn('SMITE_FIELD_TRIAL_VERSION="2.0.0-rc.1"', installer)
        self.assertNotIn("smite-rc2-signed-registry-candidate.json", installer)
        foreign = PAIRING.read_text()
        self.assertNotIn(NODE.split("@", 1)[1], foreign)
        self.assertIn("_FOREIGN_NODE_IMAGE", foreign)

    def test_rc2_preview_is_not_a_release_authorization(self):
        doc = json.loads(CANDIDATE.read_bytes())
        self.assertTrue(doc["publish_ref"].startswith("refs/tags/v"))
        self.assertNotIn("latest", str(doc))
        self.assertFalse(doc["activation_allowed"] or doc["release_approved"])
        self.assertTrue(re.fullmatch("[a-f0-9]{40}", doc["source_commit"]))


if __name__ == "__main__":
    unittest.main()
