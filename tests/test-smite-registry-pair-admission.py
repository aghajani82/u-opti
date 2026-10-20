"""Offline negative and positive pre-admission cases using FAKE Cosign only."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules/smite-registry-pair-admission.py"
spec = importlib.util.spec_from_file_location("registry_pair_admission", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SOURCE = "a" * 40
PANEL = "sha256:" + "b" * 64
NODE = "sha256:" + "c" * 64
REF = "refs/tags/v2.0.0-rc.0"

class RegistryPairAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.path = self.folder / "pair.json"
        self.logs = self.folder / "calls"
        self.document = {
            "schema": 1,
            "kind": "smite_signed_registry_pair_candidate",
            "source_repo": "aghajani82/Smite",
            "source_commit": SOURCE,
            "publish_ref": REF,
            "version": "2.0.0-rc.0",
            "images": {
                "panel": "ghcr.io/aghajani82/smite-panel@" + PANEL,
                "node": "ghcr.io/aghajani82/smite-node@" + NODE,
            },
            "activation_allowed": False,
            "release_approved": False,
        }
        self.persist()
        fake = self.folder / "cosign"
        fake.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_COSIGN_LOG"], "a") as f:
    f.write(json.dumps(args) + "\\n")
ref = args[-1]
role = "panel" if "smite-panel@" in ref else "node"
if os.environ.get("FAKE_COSIGN_FAIL") == role:
    sys.exit(3)
digest = ref.split("@", 1)[1]
if os.environ.get("FAKE_COSIGN_LIE") == role:
    digest = "sha256:" + "f" * 64
source = next(x.split("=", 1)[1] for x in args if x.startswith("smite_source_sha="))
print(json.dumps([{"critical": {"type": "cosign container image signature",
                                  "image": {"docker-manifest-digest": digest}},
                   "optional": {"smite_source_sha": source, "smite_role": role}}]))
''')
        fake.chmod(0o700)
        self.fake_env = dict(os.environ,
            PATH=str(self.folder) + os.pathsep + os.environ["PATH"],
            FAKE_COSIGN_LOG=str(self.logs))

    def persist(self):
        self.path.write_text(json.dumps(self.document, sort_keys=True))
        self.hash = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def check(self, **extra):
        kwargs = dict(manifest=self.path, manifest_sha256=self.hash,
                      source_sha=SOURCE, publish_ref=REF)
        kwargs.update(extra)
        with patch.dict(os.environ, self.fake_env):
            return gate.verify_pair(**kwargs)

    def test_verified_independent_digest_source_role(self):
        self.check()
        calls = [json.loads(x) for x in self.logs.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        for role, call in zip(("panel", "node"), calls):
            self.assertEqual(call[0], "verify")
            self.assertIn("ghcr.io/aghajani82/smite-" + role + "@", call[-1])
            self.assertIn("smite_source_sha=" + SOURCE, call)
            self.assertIn("smite_role=" + role, call)
            self.assertIn("--certificate-identity=" + gate.WORKFLOW + REF, call)
            self.assertIn("--certificate-oidc-issuer=" + gate.ISSUER, call)
            self.assertIn("--certificate-github-workflow-sha=" + SOURCE, call)
            self.assertIn("--certificate-github-workflow-repository=" + gate.REPO, call)
            self.assertIn("--certificate-github-workflow-trigger=workflow_dispatch", call)
            self.assertFalse(any("insecure" in arg or "check-claims=false" in arg
                                 for arg in call))

    def test_signed_payload_only_accepts_real_cosign_signature_type(self):
        valid = [{"critical": {"type": "cosign container image signature",
                              "image": {"docker-manifest-digest": PANEL}},
                  "optional": {"smite_source_sha": SOURCE, "smite_role": "panel"}}]
        self.assertTrue(gate._signed_payload_match(
            valid, digest=PANEL, role="panel", source=SOURCE))
        for invalid in ("attestation", "", None):
            bad = json.loads(json.dumps(valid))
            bad[0]["critical"]["type"] = invalid
            self.assertFalse(gate._signed_payload_match(
                bad, digest=PANEL, role="panel", source=SOURCE))
        without_type = json.loads(json.dumps(valid))
        del without_type[0]["critical"]["type"]
        self.assertFalse(gate._signed_payload_match(
            without_type, digest=PANEL, role="panel", source=SOURCE))

    def test_untrusted_manifest_and_release_inputs_stop_before_cosign(self):
        cases = [
            ({"manifest_sha256": "0" * 64}, None),
            ({"source_sha": "0" * 40}, None),
            ({"publish_ref": "refs/tags/v2.0.1"}, None),
            ({}, ("activation_allowed", True)),
            ({}, ("release_approved", True)),
            ({}, ("source_repo", "other/Smite")),
            ({}, ("source_commit", "f" * 40)),
            ({}, ("publish_ref", "refs/heads/main")),
            ({}, ("images", {"panel": "ghcr.io/attacker/panel@" + PANEL,
                             "node": "ghcr.io/aghajani82/smite-node@" + NODE})),
            ({}, ("images", {"panel": "ghcr.io/aghajani82/smite-panel@" + PANEL,
                             "node": "ghcr.io/aghajani82/smite-node@" + PANEL})),
        ]
        for overrides, change in cases:
            with self.subTest(overrides=overrides, change=change):
                self.document = {
                    "schema": 1, "kind": "smite_signed_registry_pair_candidate",
                    "source_repo": "aghajani82/Smite", "source_commit": SOURCE,
                    "publish_ref": REF, "version": "2.0.0-rc.0",
                    "images": {"panel": "ghcr.io/aghajani82/smite-panel@" + PANEL,
                               "node": "ghcr.io/aghajani82/smite-node@" + NODE},
                    "activation_allowed": False, "release_approved": False,
                }
                if change:
                    self.document[change[0]] = change[1]
                self.persist()
                if self.logs.exists():
                    self.logs.unlink()
                with self.assertRaises(gate.AdmissionHold):
                    self.check(**overrides)
                self.assertFalse(self.logs.exists())

    def test_failed_signature_and_forged_claim_hold(self):
        for variable, role in [("FAKE_COSIGN_FAIL", "panel"),
                               ("FAKE_COSIGN_FAIL", "node"),
                               ("FAKE_COSIGN_LIE", "panel"),
                               ("FAKE_COSIGN_LIE", "node")]:
            with self.subTest(variable=variable, role=role):
                with patch.dict(os.environ, dict(self.fake_env, **{variable: role})):
                    with self.assertRaises(gate.AdmissionHold):
                        gate.verify_pair(manifest=self.path, manifest_sha256=self.hash,
                                         source_sha=SOURCE, publish_ref=REF)

    def test_cli_is_only_preflight_no_docker(self):
        p = subprocess.run([sys.executable, "-B", str(SCRIPT),
                            "--manifest", str(self.path), "--manifest-sha256", self.hash,
                            "--source-sha", SOURCE, "--publish-ref", REF],
                           capture_output=True, text=True, timeout=10, env=self.fake_env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("DEPLOYMENT_AUTHORIZED=NO", p.stdout)
        code = SCRIPT.read_text()
        for prohibited in ("docker load", "docker pull", "subprocess.Popen", "shell=True"):
            self.assertNotIn(prohibited, code)

    def test_symlink_is_rejected(self):
        alias = self.folder / "alias.json"
        alias.symlink_to(self.path)
        if self.logs.exists(): self.logs.unlink()
        with self.assertRaises(gate.AdmissionHold):
            self.check(manifest=alias)
        self.assertFalse(self.logs.exists())

if __name__ == "__main__":
    unittest.main(verbosity=2)
