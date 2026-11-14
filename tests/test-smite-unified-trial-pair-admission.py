"""No-network trial pair verification tests; NEVER deploy."""
import ast
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


class SealedRepositoryPinContract(unittest.TestCase):
    """No-network consistency check across existing signed trial consumers.

    A new signed Panel/Node pair must update EVERY consuming path together.
    A green isolated component suite does not prove source/digest alignment.
    This checks source literals WITHOUT importing or executing host helpers.
    """

    @staticmethod
    def constants(path):
        values = {}
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"),
                         filename=str(path))
        for statement in tree.body:
            if (isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)):
                try:
                    values[statement.targets[0].id] = ast.literal_eval(statement.value)
                except (ValueError, TypeError, SyntaxError, MemoryError,
                        RecursionError):
                    pass
        return values

    def repository_contract(self, *, overrides=None):
        modules = ROOT / "modules"
        path = modules / "smite-unified-trial-registry-pair.json"
        raw = path.read_bytes()
        manifest = json.loads(raw)
        source = manifest["source_commit"]
        expected_sha = hashlib.sha256(raw).hexdigest()
        panel = manifest["images"]["panel"]
        node = manifest["images"]["node"]
        self.assertEqual(manifest["publish_ref"], v.REF)
        self.assertIs(manifest["release_approved"], False)
        self.assertIs(manifest["activation_allowed"], False)

        contracts = {
            "modules/smite-unified-panel-stage.py": {
                "SOURCE": source, "MANIFEST_HASH": expected_sha,
                "NEW_PANEL": panel, "NEW_NODE": node,
            },
            "modules/smite-unified-panel-transaction.py": {
                "SOURCE_SHA": source,
            },
            "modules/smite-unified-foreign-activation-review.py": {
                "SOURCE": source, "MANIFEST_SHA": expected_sha,
                "PANEL": panel, "NODE": node,
            },
            "modules/smite-unified-foreign-existing-witnesses.py": {
                "SOURCE": source, "MANIFEST_SHA": expected_sha,
                "TRIAL_PANEL": panel, "TRIAL_NODE": node,
            },
            "modules/smite-node-pairing.py": {
                "_FOREIGN_NODE_IMAGE_UNIFIED_TRIAL": node,
            },
        }
        if overrides is not None:
            target, key, value = overrides
            contracts[target][key] = value
        for filename, expected in contracts.items():
            actual = self.constants(filename)
            for key, correct_value in expected.items():
                # Propagate errors normally so the negative-control tests
                # can prove mismatches really fail the entire release gate.
                self.assertIn(key, actual, f"Missing {key} in {filename}")
                self.assertEqual(actual[key], correct_value,
                                 f"Drifted {key} in {filename}")

        pairing = (modules / "smite-node-pairing.py").read_text()
        release_gate = pairing.split(
            "def _require_unified_foreign_release()", 1)[1].split(
            "\ndef activate_foreign_node_field_trial(", 1)[0]
        for value in (source, expected_sha, panel):
            self.assertIn(value, release_gate)
        self.assertIn("host_activation_allowed", release_gate)
        self.assertIn("is not True", release_gate)

        installer = (modules / "smite-install.sh").read_text()
        for value in (source, expected_sha, node):
            self.assertIn(value, installer)
        self.assertIn("FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES", installer)
        # The original RC7 Panel and Node remain independent of this new
        # trial pair. Updating only the trial manifest cannot overwrite them.
        official = json.loads(
            (modules / "smite-rc7-registry-pair.json").read_bytes())
        self.assertNotEqual(official["images"]["panel"], panel)
        self.assertNotEqual(official["images"]["node"], node)

        client = (ROOT / ".github/workflows/foreign-install-client-trial.yml").read_text()
        signed = (ROOT / ".github/workflows/smite-unified-trial-signed-pair-review.yml").read_text()
        panel_ci = client.split("\n  panel-compose-upgrade:", 1)[1]
        for workflow in (client, signed):
            self.assertIn("--manifest-sha256 " + expected_sha, workflow)
            self.assertIn("--source-sha " + source, workflow)
        self.assertIn("ref: " + source, client)
        self.assertIn("--manifest-sha256 " + expected_sha, panel_ci)
        self.assertIn("--source-sha " + source, panel_ci)
        self.assertIn("HOST_INSTALL_ALLOWED=NO", signed)
        return True

    def test_actual_trial_source_images_and_all_consumers_are_one_pair(self):
        self.assertTrue(self.repository_contract())

    def test_mismatched_manifest_consumer_is_detected(self):
        with self.assertRaises(AssertionError):
            self.repository_contract(overrides=(
                "modules/smite-unified-panel-stage.py", "NEW_PANEL",
                "ghcr.io/aghajani82/smite-panel@sha256:" + "0" * 64))
        with self.assertRaises(AssertionError):
            self.repository_contract(overrides=(
                "modules/smite-node-pairing.py",
                "_FOREIGN_NODE_IMAGE_UNIFIED_TRIAL",
                "ghcr.io/aghajani82/smite-node@sha256:" + "0" * 64))


if __name__=="__main__":
    unittest.main(verbosity=2)
