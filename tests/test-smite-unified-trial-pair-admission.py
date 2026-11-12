"""No-network trial pair verification tests; NEVER deploy."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "smite_unified_trial_pair", ROOT/"modules"/"smite-unified-trial-pair-admission.py")
v = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v
spec.loader.exec_module(v)
SOURCE = "a"*40
PANEL = "sha256:"+"b"*64
NODE = "sha256:"+"c"*64
ROOT_FILE = ROOT/"modules"/"smite-rc7-sigstore-trusted-root.json"


class TrialPair(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manifest = Path(self.tmp.name)/"pair.json"
        self.values = {
            "schema":1, "kind":"smite_unified_install_signed_trial_candidate",
            "source_repo":"aghajani82/Smite", "source_commit":SOURCE,
            "publish_ref":v.REF, "version":"2.0.0-unified-install-trial",
            "images":{
                "panel":"ghcr.io/aghajani82/smite-panel@"+PANEL,
                "node":"ghcr.io/aghajani82/smite-node@"+NODE},
            "activation_allowed":False, "release_approved":False}
        self.issued=[]
        self.write()

    def write(self):
        self.manifest.write_text(json.dumps(self.values,sort_keys=True)+"\n")
        self.sha=hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def fake_signer(self, argv, **kwargs):
        self.issued.append(argv)
        role="panel" if "smite_role=panel" in argv else "node"
        digest=PANEL if role=="panel" else NODE
        record={"critical":{"type":"cosign container image signature",
                            "image":{"docker-manifest-digest":digest}},
                "optional":{"smite_source_sha":SOURCE,"smite_role":role,
                            "smite_trial":"unified-install"}}
        return subprocess.CompletedProcess(argv,0,json.dumps([record]),"")

    def check_admission(self, **kw):
        args={"manifest":self.manifest,"manifest_sha256":self.sha,
              "source_sha":SOURCE,"trusted_root":ROOT_FILE,"runner":self.fake_signer}
        args.update(kw)
        return v.verify(**args)

    def test_exact_success_and_immutable_workflow_identity(self):
        out=self.check_admission()
        self.assertEqual(out["status"],"verified_trial_pair")
        self.assertFalse(out["host_activation_allowed"])
        self.assertEqual(len(self.issued),2)
        for role,command in zip(("panel","node"),self.issued):
            self.assertIn("--trusted-root",command)
            self.assertIn("--certificate-identity="+v.WORKFLOW,command)
            self.assertIn("--certificate-oidc-issuer="+v.ISSUER,command)
            self.assertIn("--certificate-github-workflow-sha="+SOURCE,command)
            self.assertIn("--certificate-github-workflow-trigger=push",command)
            self.assertIn("smite_role="+role,command)
            self.assertIn("smite_trial=unified-install",command)
            self.assertIn(self.values["images"][role],command)

    def test_modified_manifest_or_outside_pin_refused_before_cosign(self):
        with self.assertRaises(v.Hold):self.check_admission(manifest_sha256="0"*64)
        self.assertEqual(self.issued,[])
        self.values["release_approved"]=True
        self.write()
        with self.assertRaises(v.Hold):self.check_admission()
        self.assertEqual(self.issued,[])

    def test_wrong_role_branch_version_and_legacy_claims_hold(self):
        bad=[
          ("publish_ref","refs/tags/v2.0.0-rc.7"),
          ("publish_ref","refs/heads/main"),
          ("kind","smite_signed_registry_pair_candidate"),
          ("version","2.0.0-rc.7"),
          ("source_commit","0"*40),
          ("activation_allowed",True),
          ("schema",True),
        ]
        for key,wrong in bad:
            old=self.values[key]
            self.values[key]=wrong
            self.write()
            with self.subTest(key=key, wrong=wrong),self.assertRaises(v.Hold):
                self.check_admission()
            self.values[key]=old
        self.assertEqual(self.issued,[])

    def test_duplicate_image_and_wrong_repository_denied(self):
        self.values["images"]["node"]=self.values["images"]["panel"]
        self.write()
        with self.assertRaises(v.Hold):self.check_admission()
        self.values["images"]["node"]="ghcr.io/other/smite-node@"+NODE
        self.write()
        with self.assertRaises(v.Hold):self.check_admission()
        self.assertEqual(self.issued,[])

    def test_duplicate_json_keys_rejected(self):
        self.manifest.write_text(self.manifest.read_text().rstrip()[:-1]+',"schema":1}')
        self.sha=hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        with self.assertRaises(v.Hold):self.check_admission()
        self.assertEqual(self.issued,[])

    def test_tampered_or_missing_trusted_root_denied(self):
        bad=Path(self.tmp.name)/"root.json"
        bad.write_bytes(ROOT_FILE.read_bytes()+b"x")
        with self.assertRaises(v.Hold):self.check_admission(trusted_root=bad)
        bad.unlink()
        with self.assertRaises(v.Hold):self.check_admission(trusted_root=bad)
        self.assertEqual(self.issued,[])

    def test_nonzero_cosign_and_wrong_digest_or_claim_refused(self):
        def fail(argv,**kw):return subprocess.CompletedProcess(argv,5,"","")
        with self.assertRaises(v.Hold):self.check_admission(runner=fail)
        def forged(argv,**kw):
            record={"critical":{"type":"cosign container image signature",
                                "image":{"docker-manifest-digest":"sha256:"+"e"*64}},
                    "optional":{"smite_source_sha":SOURCE,"smite_role":"panel",
                                "smite_trial":"unified-install"}}
            return subprocess.CompletedProcess(argv,0,json.dumps([record]),"")
        with self.assertRaises(v.Hold):self.check_admission(runner=forged)

    def test_existing_official_release_verifier_does_not_accept_trial(self):
        official=(ROOT/"modules"/"smite-registry-pair-admission.py").read_text()
        self.assertIn("WORKFLOW = \"https://github.com/aghajani82/Smite/.github/workflows/publish-images.yml@\"",official)
        self.assertIn("Independent release tag required",official)
        self.assertNotIn("smite_trial=unified-install",official)


if __name__=="__main__":
    unittest.main(verbosity=2)
