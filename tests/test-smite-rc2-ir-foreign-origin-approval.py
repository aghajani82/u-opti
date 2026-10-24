#!/usr/bin/env python3
"""Mocked, offline safety tests for foreign origin approval read-only plan."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "modules/smite-rc2-ir-foreign-origin-approval.py"
spec = importlib.util.spec_from_file_location("rc2_origin_field_trial", HELPER)
origin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(origin)


class FakeAdmission:
    def admit_ir(self):
        return [
            "IR_PANEL_RC2_SIGNED=PASS",
            "IR_LOCAL_NODE_RC1=UNCHANGED",
            "IR_TRUST_MOUNT=READ_ONLY",
            "IR_FOREIGN_PATH_HMAC_POLICY=PASS",
            "IR_HTTPS_STATUS=PASS",
        ]


class OriginTests(unittest.TestCase):
    def test_explicit_role_gate_only_ir(self):
        with patch.object(origin.os, "geteuid", return_value=0), \
             patch.object(origin.socket, "gethostname", return_value="kh"), \
             patch("sys.stdout", io.StringIO()):
            self.assertEqual(origin.main(["--plan"]), 2)

    def test_exact_kh_https_path_must_match_no_query(self):
        good = "https://kh.kolbe1.ir/smite-node/0123456789abcdef"
        self.assertTrue(origin.URL_RULE.fullmatch(good))
        for bad in (
            "https://kh.kolbe1.ir/smite-node/x",
            "http://kh.kolbe1.ir/smite-node/0123456789abcdef",
            "https://evil.kolbe1.ir/smite-node/0123456789abcdef",
            good + "?secret=1",
            "https://kh.kolbe1.ir:444/smite-node/0123456789abcdef",
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(origin.URL_RULE.fullmatch(bad))

    def test_readonly_plan_cannot_commit_trust(self):
        pairing = Mock()
        pairing._require_panel_signed_registration_schema = Mock()
        pairing._require_panel_foreign_transport = Mock()
        url = "https://kh.kolbe1.ir/smite-node/0123456789abcdef"
        with patch.object(origin.os, "geteuid", return_value=0), \
             patch.object(origin.socket, "gethostname", return_value="ir"), \
             patch.object(origin.sys.stdin, "isatty", return_value=True), \
             patch.object(origin, "checked_module", side_effect=[pairing, FakeAdmission()]), \
             patch.object(origin, "reserved_node", return_value=({"SMITE_ROLE":"panel-iran"}, "node-abcdefgh")), \
             patch.object(origin, "hidden_url", return_value=url), \
             patch.object(origin, "verify_gateway") as gateway, \
             patch("sys.stdout", io.StringIO()) as output:
            self.assertEqual(origin.main(["--plan"]), 0)
            self.assertIn("IR_FOREIGN_ORIGIN_PLAN=PASS_READ_ONLY", output.getvalue())
        gateway.assert_called_once_with(pairing, url)
        pairing.approve_foreign_origin_field_trial.assert_not_called()

    def test_apply_requires_dual_consent_before_write(self):
        pairing = Mock()
        with patch.object(origin.os, "geteuid", return_value=0), \
             patch.object(origin.socket, "gethostname", return_value="ir"), \
             patch.object(origin.sys.stdin, "isatty", return_value=True), \
             patch.object(origin, "checked_module", side_effect=[pairing, FakeAdmission()]), \
             patch.object(origin, "reserved_node", return_value=({"SMITE_ROLE":"panel-iran"}, "node-abcdefgh")), \
             patch.object(origin, "hidden_url", return_value="https://kh.kolbe1.ir/smite-node/0123456789abcdef"), \
             patch.object(origin, "verify_gateway"), \
             patch.dict(origin.os.environ, {"UOPTI_SMITE_PAIRING_FIELD_TRIAL":"NO",
                     "UOPTI_SMITE_IR_RC2_ORIGIN_APPROVAL":"NO"}), \
             patch("sys.stdout", io.StringIO()):
            self.assertEqual(origin.main(["--apply"]), 2)
        pairing.approve_foreign_origin_field_trial.assert_not_called()

    def test_apply_requires_operator_specific_confirmation(self):
        pairing = Mock()
        with patch.object(origin.os, "geteuid", return_value=0), \
             patch.object(origin.socket, "gethostname", return_value="ir"), \
             patch.object(origin.sys.stdin, "isatty", return_value=True), \
             patch.object(origin, "checked_module", side_effect=[pairing, FakeAdmission()]), \
             patch.object(origin, "reserved_node", return_value=({"SMITE_ROLE":"panel-iran"}, "node-abcdefgh")), \
             patch.object(origin, "hidden_url", return_value="https://kh.kolbe1.ir/smite-node/0123456789abcdef"), \
             patch.object(origin, "verify_gateway"), \
             patch.dict(origin.os.environ, {"UOPTI_SMITE_PAIRING_FIELD_TRIAL":"YES",
                     "UOPTI_SMITE_IR_RC2_ORIGIN_APPROVAL":"YES"}), \
             patch("builtins.input", return_value="CANCEL"), \
             patch("sys.stdout", io.StringIO()):
            self.assertEqual(origin.main(["--apply"]), 2)
        pairing.approve_foreign_origin_field_trial.assert_not_called()

    def test_reserved_node_requires_exact_pending_record_and_existing_ir_trust(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            db=root/"smite.db"
            import sqlite3
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE nodes (id TEXT,name TEXT,status TEXT,metadata TEXT)")
                conn.execute("INSERT INTO nodes VALUES (?,?,?,?)",
                             ("node-abcdefgh","node-kh","pending",json.dumps({
                                "role":"foreign","node_name":"node-kh",
                                "provisioning":"reserved_for_pairing",
                             })))
            pairing=Mock()
            pairing.PANEL_DB=db
            pairing.APPROVED_ORIGINS=root/"origins.json"
            pairing.state_values.return_value={
                "SMITE_ROLE":"panel-iran", "SMITE_CONNECTION_MODE":"standard",
                "SMITE_PANEL_DOMAIN":"ir.kolbe1.ir", "SMITE_MANAGED_VERSION":"2.0.0-rc.1",
            }
            pairing._regular.return_value=json.dumps({
                "version":1,"nodes":{"local":{"role":"iran","node_name":"node-ir"}}
            }).encode()
            self.assertEqual(origin.reserved_node(pairing)[1],"node-abcdefgh")
            pairing._regular.return_value=json.dumps({
                "version":1,"nodes":{"local":{"role":"iran"},
                  "foreign":{"role":"foreign","node_name":"node-kh"}}
            }).encode()
            with self.assertRaisesRegex(origin.Hold, "TRUST_BASELINE_DRIFT"):
                origin.reserved_node(pairing)


if __name__=="__main__":
    unittest.main()
