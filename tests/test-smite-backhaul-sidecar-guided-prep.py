#!/usr/bin/env python3
"""Hermetic tests: guided fresh-host PRIVATE/OFFLINE pairing must fail closed."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "guided_under_test", HERE / "modules/smite-backhaul-sidecar-guided-prep.py"
)
guided = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(guided)


class GuidedPreparationTests(unittest.TestCase):
    def good(self, role="ir", **more):
        options = dict(
            token=True, baseline=[], issues=[],
            sc=Path("/tmp/uopti-backhaul-sidecar-testfixture"),
            ng=Path("/tmp/uopti-bh-nginx-plan-testfixture"),
        )
        options.update(more)
        with patch.object(guided.os, "geteuid", return_value=0), \
             patch.object(guided.token_tool, "inspect", return_value=options["token"]) as token, \
             patch.object(guided.readiness, "inspect_local", return_value=options["baseline"]) as local, \
             patch.object(guided.sidecar, "prepare", return_value=options["sc"]) as side, \
             patch.object(guided.nginx_plan, "prepare", return_value=options["ng"]) as nginx, \
             patch.object(guided.admission_gate, "admission", return_value=options["issues"]) as admission, \
             patch.object(guided, "_cleanup_private_stage") as clean:
            if options["issues"] or options["baseline"] or not options["token"]:
                with self.assertRaises(guided.GuidedHold):
                    guided.prepare_fresh_pair(role, "ir.kolbe1.ir", "kh.kolbe1.ir")
            else:
                self.assertEqual(
                    (options["sc"], options["ng"]),
                    guided.prepare_fresh_pair(role, "ir.kolbe1.ir", "kh.kolbe1.ir"))
            return token, local, side, nginx, admission, clean

    def test_both_role_bundles_and_admission_verified(self):
        for role in ("ir", "kh"):
            token, local, side, nginx, admission, clean = self.good(role)
            token.assert_called_once_with(guided.TOKEN_FILE)
            local.assert_called_once_with(role, "new")
            side.assert_called_once_with(
                role, guided.TOKEN_FILE, "ir.kolbe1.ir", "kh.kolbe1.ir")
            path = guided.nginx_plan.IR_PATH if role == "ir" else guided.nginx_plan.KH_PATH
            nginx.assert_called_once_with(
                role, Path(path), "ir.kolbe1.ir", "kh.kolbe1.ir")
            admission.assert_called_once()
            clean.assert_not_called()

    def test_custom_xray_port_path_are_checked_before_pairing(self):
        role = "kh"
        with patch.object(guided.os, "geteuid", return_value=0), \
             patch.object(guided.token_tool, "inspect", return_value=True), \
             patch.object(guided.readiness, "inspect_local", return_value=[]) as readiness, \
             patch.object(guided.sidecar, "prepare", return_value=Path("/tmp/uopti-backhaul-sidecar-testfixture")) as side, \
             patch.object(guided.nginx_plan, "prepare", return_value=Path("/tmp/uopti-bh-nginx-plan-testfixture")) as nginx, \
             patch.object(guided.admission_gate, "admission", return_value=[]), \
             patch.object(guided, "_cleanup_private_stage"):
            guided.prepare_fresh_pair(role, "ir.kolbe1.ir", "kh.kolbe1.ir",
                                      45123, "/assets/v1/connect")
            readiness.assert_called_once_with(
                role, "new", data_port=45123, xhttp_path="/assets/v1/connect")
            side.assert_called_once_with(
                role, guided.TOKEN_FILE, "ir.kolbe1.ir", "kh.kolbe1.ir",
                data_port=45123, xhttp_path="/assets/v1/connect")
            nginx.assert_called_once_with(
                role, Path(guided.nginx_plan.KH_PATH),
                "ir.kolbe1.ir", "kh.kolbe1.ir",
                data_port=45123, xhttp_path="/assets/v1/connect")

    def test_existing_sidecar_is_a_hard_stop_before_staging(self):
        _, local, side, nginx, admission, _ = self.good(
            baseline=["Existing/partial Sidecar detected; fresh install REFUSED"])
        local.assert_called_once()
        side.assert_not_called()
        nginx.assert_not_called()
        admission.assert_not_called()

    def test_missing_or_unsafe_pairing_token_refuses(self):
        _, local, side, nginx, admission, _ = self.good(token=False)
        local.assert_not_called()
        side.assert_not_called()
        nginx.assert_not_called()
        admission.assert_not_called()

    def test_admission_hold_cleans_up_both_private_stages(self):
        _, _, side, nginx, admission, clean = self.good(
            issues=["Nginx source drifted from the reviewed proposal"])
        side.assert_called_once()
        nginx.assert_called_once()
        admission.assert_called_once()
        self.assertEqual(clean.call_count, 2)

    def test_generator_error_must_not_print_secrets(self):
        with patch.object(guided.os, "geteuid", return_value=0), \
             patch.object(guided.token_tool, "inspect", return_value=True), \
             patch.object(guided.readiness, "inspect_local", return_value=[]), \
             patch.object(guided.sidecar, "prepare",
                          side_effect=ValueError("TOP_SECRET_VALUE")), \
             patch.object(guided, "_cleanup_private_stage"):
            buffer = io.StringIO()
            with patch.object(sys, "argv", [
                "guided", "--role", "ir", "--ir-domain", "ir.kolbe1.ir",
                "--kh-host", "kh.kolbe1.ir", "--prepare-only",
                "--confirm", "PREPARE-PRIVATE-OFFLINE"
            ]), redirect_stdout(buffer):
                self.assertEqual(2, guided.main())
            self.assertIn("HOLD:", buffer.getvalue())
            self.assertNotIn("TOP_SECRET_VALUE", buffer.getvalue())

    def test_explicit_confirmation_required(self):
        with patch.object(sys, "argv", [
            "guided", "--role", "kh", "--ir-domain", "ir.kolbe1.ir",
            "--kh-host", "kh.kolbe1.ir"
        ]), redirect_stdout(io.StringIO()) as output, \
             patch.object(guided, "prepare_fresh_pair") as prep:
            self.assertEqual(2, guided.main())
            self.assertIn("confirmation", output.getvalue())
            prep.assert_not_called()

    def test_root_and_input_validation_before_any_write(self):
        with patch.object(guided.os, "geteuid", return_value=1000):
            with self.assertRaises(guided.GuidedHold):
                guided.prepare_fresh_pair("ir", "ir.kolbe1.ir", "kh.kolbe1.ir")
        with patch.object(guided.os, "geteuid", return_value=0), \
             patch.object(guided.sidecar, "prepare") as side:
            with self.assertRaises(ValueError):
                guided.prepare_fresh_pair("ir", "invalid;command", "kh.kolbe1.ir")
            side.assert_not_called()


if __name__ == "__main__":
    unittest.main()
