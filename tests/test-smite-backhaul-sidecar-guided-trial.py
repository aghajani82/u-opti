#!/usr/bin/env python3
"""Hermetic tests for one-flow test-VPS setup; never touch real hosts."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "modules/smite-backhaul-sidecar-guided-trial.py"
spec = importlib.util.spec_from_file_location("oneflow_test", SOURCE)
flow = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(flow)

IR = "ir.kolbe1.ir"
KH = "kh.kolbe1.ir"
SC = Path("/tmp/uopti-backhaul-sidecar-fixture-test")
NG = Path("/tmp/uopti-bh-nginx-plan-fixture-test")


class GuidedTrialTest(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(flow.os, "geteuid", return_value=0),
            patch.dict(flow.os.environ, {"UOPTI_BH_TEST_HOST": "I_ACCEPT_REBUILD_TEST_HOST"}),
            patch.object(flow.trial, "disposable_host_approved", return_value=True),
            patch.object(flow.role_gate, "_trusted_role"),
            patch.object(flow.trial, "_root", return_value=Mock(exists=lambda: False,
                                                               is_symlink=lambda: False)),
            patch.object(flow.guided, "prepare_fresh_pair", return_value=(SC, NG)),
            patch.object(flow.trial, "install",
                         return_value="TRIAL_INSTALL_LOCAL_CHECKS_PASSED"),
            patch.object(flow.guided, "_cleanup_private_stage"),
        ]
        self.values = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def call(self, role="ir", approval="REBUILT-TEST-VPS", confirm=None):
        return flow.install_fresh(role, IR, KH, approval,
                                  confirm if confirm is not None else ("INSTALL-" + role.upper()))

    def test_ir_and_kh_use_private_pair_without_manual_directory_prompts(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                self.assertEqual(self.call(role), flow.SUCCESS)
                self.values[3].assert_called_with(role)
                self.values[5].assert_called_with(role, IR, KH)
                self.values[6].assert_called_with(role, SC, NG)
                self.assertEqual(self.values[7].call_count % 2, 0)

    def test_custom_xray_port_and_path_reach_the_real_install_gate(self):
        self.assertEqual(
            flow.install_fresh("kh", IR, KH, "REBUILT-TEST-VPS",
                               "INSTALL-KH", 45123, "/assets/v1/connect"),
            flow.SUCCESS)
        self.values[5].assert_called_once_with(
            "kh", IR, KH, 45123, "/assets/v1/connect")
        self.values[6].assert_called_once_with("kh", SC, NG)

    def test_missing_second_confirmation_never_prepares(self):
        self.values[5].reset_mock()
        for bad in ("wrong", ""):
            with self.assertRaises(flow.GuidedTrialHold):
                self.call(confirm=bad)
        self.values[5].assert_not_called()

    def test_rejects_wrong_role_before_prepare(self):
        self.values[5].reset_mock()
        with self.assertRaises(flow.GuidedTrialHold):
            self.call("foreign", confirm="INSTALL-FOREIGN")
        self.values[5].assert_not_called()

    def test_missing_test_host_marker_never_prepares(self):
        self.values[2].return_value = False
        with self.assertRaises(flow.GuidedTrialHold):
            self.call()
        self.values[5].assert_not_called()

    def test_existing_trial_journal_refused_before_prepare(self):
        self.values[4].return_value.exists = lambda: True
        with self.assertRaises(flow.GuidedTrialHold):
            self.call()
        self.values[5].assert_not_called()

    def test_live_trial_failure_cleans_private_stages_and_retains_rollback_owner(self):
        self.values[6].side_effect = flow.trial.TrialRefused("simulated failure")
        with self.assertRaises(flow.trial.TrialRefused):
            self.call("kh")
        self.assertEqual(self.values[7].call_count, 2)
        self.values[7].assert_any_call(NG, "uopti-bh-nginx-plan-")
        self.values[7].assert_any_call(SC, "uopti-backhaul-sidecar-")

    def test_incomplete_offline_prepare_does_not_call_installer(self):
        self.values[5].side_effect = flow.guided.GuidedHold("offline check failed")
        with self.assertRaises(flow.guided.GuidedHold):
            self.call()
        self.values[6].assert_not_called()
        self.values[7].assert_called()

    def test_cleanup_must_be_verified_before_success(self):
        with patch.object(flow.os.path, "lexists", return_value=True):
            with self.assertRaisesRegex(flow.GuidedTrialHold, "cleanup unverified"):
                self.call()
        self.values[6].assert_called_once()
        self.assertEqual(self.values[7].call_count, 2)

    def test_role_identity_mismatch_stops_before_preparation(self):
        self.values[3].side_effect = ValueError("wrong Smite role")
        with self.assertRaisesRegex(ValueError, "wrong Smite role"):
            self.call()
        self.values[5].assert_not_called()

    def test_cli_failure_sanitizes_sensitive_lower_layer_error(self):
        with patch.object(sys, "argv", ["oneflow", "--role", "ir",
                                         "--ir-domain", IR, "--kh-host", KH,
                                         "--install-test",
                                         "--test-host-approval", "REBUILT-TEST-VPS",
                                         "--confirm", "INSTALL-IR"]), \
             patch.object(flow, "install_fresh",
                          side_effect=ValueError("confidential-data-fixture")), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(flow.main(), 2)
            self.assertNotIn("confidential-data-fixture", output.getvalue())
            self.assertIn("READ-ONLY", output.getvalue())

    def test_readonly_diagnostic_explicitly_distinguishes_pairing_from_install(self):
        # A matched pairing token is NOT an installed Sidecar.
        with tempfile.TemporaryDirectory() as root:
            vhost = Path(root) / "ir.conf"
            vhost.write_text("# harmless nginx fixture\n", encoding="utf-8")
            with patch.object(flow.guided.nginx_plan, "IR_PATH", str(vhost)), \
                 patch.object(flow.guided.token_tool, "inspect", return_value=True), \
                 patch.object(flow.guided.readiness, "inspect_local", return_value=[]), \
                 patch.object(flow.guided.nginx_plan, "original_bytes",
                              return_value=b"fake nginx fixture"), \
                 patch.object(flow.guided.nginx_plan, "compile_nginx") as compile_only, \
                 patch.object(flow.guided, "prepare_fresh_pair") as prepare, \
                 patch.object(flow.trial, "install") as activate, \
                 redirect_stdout(io.StringIO()) as output:
                self.assertEqual(flow.diagnose("ir", 17991, "/17991/shop", IR, KH), 0)
                screen = output.getvalue()
                self.assertIn("INSTALL_JOURNAL=MISSING", screen)
                self.assertIn("INSTALLATION=NOT VERIFIED", screen)
                self.assertIn("NEXT=Backhaul Step 2 INSTALL", screen)
                self.assertIn("REQUESTED_XRAY_PROFILE=17991 /17991/shop", screen)
                compile_only.assert_called_once()
                prepare.assert_not_called()
                activate.assert_not_called()

    def test_readonly_diagnostic_blocks_existing_trial_journal(self):
        self.values[4].return_value.exists = lambda: True
        with patch.object(flow.guided.token_tool, "inspect") as token_reader, \
             patch.object(flow.trial, "install") as activate, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(flow.diagnose("kh", 17991, "/17991/shop", IR, KH), 2)
            self.assertIn("INSTALL_JOURNAL=PRESENT", output.getvalue())
            token_reader.assert_not_called()
            activate.assert_not_called()

    def test_readonly_diagnostic_reports_role_mismatch_without_secret(self):
        self.values[3].side_effect = ValueError("confidential-role-data")
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(flow.diagnose("ir"), 2)
            self.assertIn("SMITE_ROLE_AND_MODE=HOLD", output.getvalue())
            self.assertNotIn("confidential-role-data", output.getvalue())

    def test_missing_install_flag_does_not_prepare(self):
        with patch.object(sys, "argv", ["oneflow", "--role", "ir",
                                         "--ir-domain", IR, "--kh-host", KH]), \
             patch.object(flow, "install_fresh") as install, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(flow.main(), 2)
            install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
