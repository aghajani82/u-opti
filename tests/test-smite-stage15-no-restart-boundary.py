"""Offline security boundary: do not silently relabel host facts as Node proof."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


verifier = load("stage15_no_restart_verifier", MODULES / "smite-stage15-approval-evidence.py")
collector = load("stage15_no_restart_collector", MODULES / "smite-stage15-live-evidence.py")


class NoRestartBoundaryTests(unittest.TestCase):
    def test_node_evidence_origin_is_still_exact_signed_agent_path(self):
        self.assertEqual(collector.TARGET, "/api/agent/approval/evidence")
        self.assertEqual(verifier.AUDIENCE, collector.AUDIENCE)
        source = (MODULES / "smite-stage15-live-evidence.py").read_text()
        self.assertIn('ir=_node_attestation(settings["ir"],"frps_owner",binding["port"])', source)
        self.assertIn('kh=_node_attestation(settings["kh"],"xhttp_inbound",binding["port"])', source)
        self.assertNotIn("fallback_host_attestation", source)

    def test_cannot_approve_on_host_facts_in_place_of_node_signatures(self):
        binding = {
            "ir_node": "node-ir-0001", "kh_node": "node-kh-0001",
            "owner": "owner-0001", "child": "child-0001",
            "lease": "child-0001", "port": 38658,
            "path": "/38658/shop",
            "owner_proof_sha256": "a" * 64,
            "kh_inventory_sha256": "b" * 64,
        }
        forged = {"schema": 1, "audience": verifier.AUDIENCE,
                  "kind": "frps_owner", "node": binding["ir_node"],
                  "issued_at": 123, "expires_at": 153, "nonce": "f" * 32,
                  "facts": {"tunnel_id": "owner-0001", "control_port": 7000,
                            "proxy_port": 38658},
                  # Only new explicitly reviewed protocol could include this.
                  "provenance": "host-root",
                  "signature": "a" * 86}
        bundle = {"ir_owner": forged, "kh_inbound": forged, "ir_lease": forged}
        with self.assertRaises(verifier.EvidenceHold):
            verifier.verify_bundle(bundle, binding, ir_public_key=b"x" * 32,
                                   kh_public_key=b"y" * 32,
                                   lease_public_key=b"z" * 32, now=130)

    def test_no_restart_is_a_blocker_not_claim_of_live_enablement(self):
        source = (ROOT / "docs/SMITE-STAGE15-NO-RESTART-EVIDENCE-BOUNDARY.md").read_text()
        for phrase in ("Status: BLOCKED for deployment",
                       "new", "provenance", "IR and KH",
                       "requires explicit operator approval",
                       "LIVE_MIGRATION_AUTHORIZED=NO"):
            # The doc must not be accidentally replaced by an enablement howto.
            self.assertIn(phrase, source)


if __name__ == "__main__":
    unittest.main()
