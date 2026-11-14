#!/usr/bin/env python3
"""Read-only new trial digest admission. No Docker/network/host access."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "trial_foreign_activation_review",
    ROOT / "modules" / "smite-unified-foreign-activation-review.py")
reviewer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reviewer
spec.loader.exec_module(reviewer)

pairing_spec = importlib.util.spec_from_file_location(
    "unified_readonly_existing_pairing",
    ROOT / "modules" / "smite-node-pairing.py")
pairing_core = importlib.util.module_from_spec(pairing_spec)
sys.modules[pairing_spec.name] = pairing_core
pairing_spec.loader.exec_module(pairing_core)


class ForeignActivationReview(unittest.TestCase):
    def setUp(self):
        cosign = patch("shutil.which", return_value="/usr/bin/cosign")
        cosign.start()
        self.addCleanup(cosign.stop)
        self.calls = []
        self.pairing_calls = []
        self.state = {
            "SMITE_ROLE": "foreign",
            "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            "SMITE_CONNECTION_MODE": "standard",
            "SMITE_NODE_NAME": "node-kh",
            "SMITE_PANEL_DOMAIN": "iran.example.org",
            "SMITE_FOREIGN_DOMAIN": "kh.example.org",
        }
        self.id = "sha256:" + "d" * 64
        self.env = "\n".join([
            "SMITE_NODE_PANEL_AUTH_MODE=paused",
            "SMITE_AGENT_AUTH_MODE=strict",
            "SMITE_ENGINE_INVENTORY_MODE=managed",
        ]) + "\n"
        self.replay = True
        self.identity = ("foreign-node-1234", "b" * 64)
        self.signature_failure = None
        self.mode = "ok"
        self.fake = SimpleNamespace(
            _FOREIGN_NODE_IMAGE_UNIFIED_TRIAL=reviewer.NODE,
            WizardHold=pairing_core.WizardHold,
            state_values=self.state_values,
            _require_no_active_engine_overlays=self.overlays,
            _foreign_gateway_preflight=self.gateway,
            _identity_record=self.identity_record,
            _replay_artifacts_valid=self.replay_ready,
            _rc7_foreign_paused_rollback_verified=(
                pairing_core._rc7_foreign_paused_rollback_verified),
        )

    def signer(self, command, **kw):
        self.calls.append(command)
        self.assertIn("--trusted-root", command)
        self.assertIn(
            "--certificate-github-workflow-sha=" + reviewer.SOURCE, command)
        self.assertIn("--certificate-github-workflow-trigger=workflow_dispatch", command)
        role = "panel" if "smite_role=panel" in command else "node"
        ref = reviewer.PANEL if role == "panel" else reviewer.NODE
        digest = ref.rsplit("@",1)[1]
        if self.signature_failure == "exit":
            return subprocess.CompletedProcess(command, 1, "", "bad")
        if self.signature_failure == "digest":
            digest = "sha256:" + "e"*64
        if self.signature_failure == "claim":
            signed_role = "node" if role == "panel" else "panel"
        else:
            signed_role = role
        doc = {
            "critical": {"type":"cosign container image signature",
                         "image":{"docker-manifest-digest":digest}},
            "optional": {"smite_source_sha":reviewer.SOURCE,
                         "smite_role":signed_role},
        }
        return subprocess.CompletedProcess(command,0,json.dumps([doc]),"")

    def state_values(self):
        self.pairing_calls.append("state")
        return self.state

    def overlays(self):
        self.pairing_calls.append("overlays")
        if self.mode == "overlay":
            raise pairing_core.WizardHold("active other engine")

    def gateway(self, state, **kwargs):
        self.pairing_calls.append("gateway")
        self.assertEqual(kwargs, {"review_unified_trial":True})
        if self.mode == "gateway":
            raise pairing_core.WizardHold("wrong 443 gateway")
        return "iran.example.org","kh.example.org","https://kh.example.org:443/smite-node/"+"a"*32

    def identity_record(self):
        self.pairing_calls.append("identity")
        return self.identity

    def replay_ready(self):
        self.pairing_calls.append("replay")
        return self.replay

    def mock_run(self, args, **kwargs):
        self.pairing_calls.append("inspect")
        self.assertEqual(kwargs["capture"],True)
        self.assertEqual(kwargs["timeout"],10)
        self.assertNotIn("up",args)
        self.assertNotIn("run",args)
        self.assertNotIn("restart",args)
        if args[-1] == "smite-node" and "{{.Config.Image}}" in args:
            return (pairing_core._FOREIGN_NODE_IMAGE_RC7
                    if self.mode == "wrong-ref" else reviewer.NODE)
        if args[-1] == "smite-node" and "{{.Image}}" in args:
            if self.mode == "running-id":
                return "sha256:"+"e"*64
            return self.id
        if args[:3] == ["docker","image","inspect"]:
            self.assertEqual(args[-1],reviewer.NODE)
            return self.id
        if any("{{range .Config.Env}}" in part for part in args):
            return self.env
        raise AssertionError("unexpected command "+str(args))

    def review(self):
        # Run the real shared verifier with an offline read-only Docker probe.
        with patch.object(pairing_core, "_run", side_effect=self.mock_run), \
             patch.object(pairing_core, "_identity_record",
                          side_effect=self.identity_record), \
             patch.object(pairing_core, "_replay_artifacts_valid",
                          side_effect=self.replay_ready):
            return reviewer.review(
                signature_runner=self.signer, pairing=self.fake)

    def test_trusted_signed_pair_and_paused_runtime_admitted_read_only(self):
        report=self.review()
        self.assertEqual(report["admission"],"READY_READ_ONLY")
        self.assertEqual(report["signed_pair"],"VERIFIED_TRIAL_ONLY")
        self.assertEqual(report["runtime"],"PAUSED_STRICT")
        self.assertEqual(report["node_image"],"EXACT_RUNNING_DIGEST")
        self.assertEqual(report["replay"],"IDENTITY_BOUND")
        self.assertEqual(report["control_path"],"/smite-node/"+"a"*32)
        self.assertEqual(report["panel_runtime"],"NOT_PROVEN_ON_REMOTE_HOST")
        self.assertFalse(report["activation_allowed"])
        self.assertFalse(report["bidirectional_connected"])
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.pairing_calls,
                         ["state","overlays","gateway","identity","replay",
                          "inspect","inspect","inspect","inspect",
                          "identity","replay"])

    def test_invalid_signature_never_reaches_host_runtime(self):
        for reason in ("exit","digest","claim"):
            self.signature_failure=reason
            with self.subTest(reason=reason),self.assertRaises(reviewer.Hold):
                self.review()
            self.assertEqual(self.pairing_calls,[])
            self.calls.clear()
        self.signature_failure=None

    def test_wrong_role_version_and_transport_fail_before_host_access(self):
        for key,invalid in (
                ("SMITE_ROLE","iran"),
                ("SMITE_MANAGED_VERSION","2.0.0-rc.6"),
                ("SMITE_CONNECTION_MODE","private")):
            old=self.state[key]
            self.state[key]=invalid
            try:
                self.pairing_calls.clear()
                with self.subTest(key=key),self.assertRaises(reviewer.Hold):
                    self.review()
                self.assertEqual(self.pairing_calls,["state"])
            finally:
                self.state[key]=old

    def test_corrupt_gateway_active_engine_or_missing_replay_blocks(self):
        for mode in ("overlay","gateway"):
            self.mode=mode
            with self.subTest(mode=mode),self.assertRaises(reviewer.Hold):
                self.review()
        self.mode="ok"
        self.replay=False
        with self.assertRaises(reviewer.Hold):
            self.review()

    def test_identity_missing_and_empty_name_denied(self):
        self.identity=("", "b"*64)
        with self.assertRaises(reviewer.Hold):self.review()
        self.identity=("foreign-node-1234","b"*64)
        self.state.pop("SMITE_NODE_NAME")
        with self.assertRaises(reviewer.Hold):self.review()

    def test_wrong_actual_image_id_refused(self):
        self.mode="wrong-ref"
        with self.assertRaises(reviewer.Hold):
            self.review()
        self.mode="running-id"
        with self.assertRaises(reviewer.Hold):
            self.review()
        self.mode="ok"
        self.id="not-an-image"
        with self.assertRaises(reviewer.Hold):
            self.review()

    def test_effective_runtime_auth_flags_are_strict_and_unique(self):
        valid=self.env
        for invalid in (
            valid.replace("MODE=paused","MODE=signed"),
            valid.replace("SMITE_AGENT_AUTH_MODE=strict","SMITE_AGENT_AUTH_MODE=legacy"),
            valid.replace("SMITE_ENGINE_INVENTORY_MODE=managed",
                          "SMITE_ENGINE_INVENTORY_MODE=off"),
            valid + "SMITE_NODE_PANEL_AUTH_MODE=paused\n",
            valid + "SMITE_NODE_PANEL_AUTH_MODE=signed\n",
            "\n".join(valid.splitlines()[:2])+"\n",
        ):
            self.env=invalid
            with self.subTest(invalid=invalid),self.assertRaises(reviewer.Hold):
                self.review()
        self.env=valid
        self.assertEqual(self.review()["admission"],"READY_READ_ONLY")

    def test_trial_pairing_pin_missing_fails_closed(self):
        self.fake._FOREIGN_NODE_IMAGE_UNIFIED_TRIAL=reviewer.PANEL
        with self.assertRaises(reviewer.Hold):self.review()
        self.assertFalse(self.pairing_calls)

    def test_no_public_activation_entry_or_connected_claim(self):
        path=ROOT/"modules"/"smite-unified-foreign-activation-review.py"
        data=path.read_text()
        self.assertNotIn('add_argument("--activate"',data)
        self.assertNotIn('add_argument("--apply"',data)
        self.assertNotIn('--force-recreate',data)
        self.assertNotIn('docker compose up',data)
        proc=subprocess.run(
            [sys.executable,"-B",str(path),"--activate"],
            capture_output=True,text=True,check=False)
        self.assertNotEqual(proc.returncode,0)


if __name__=="__main__":
    unittest.main(verbosity=2)
