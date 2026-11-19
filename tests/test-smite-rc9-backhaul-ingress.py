#!/usr/bin/env python3
"""RC9 Backhaul ingress tests with disposable files and stubbed host commands."""

import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

MODULE = Path(__file__).resolve().parents[1] / "modules/smite-rc9-backhaul-ingress.py"
spec = importlib.util.spec_from_file_location("ingress", MODULE)
ingress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingress)


class IngressTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        path = Path(workspace.name)
        self.state = path / "record.json"
        self.alt = path / "alternate.conf"
        self.kh = path / "bridge.conf"
        self.before = (b"server {\n    location = /~!frp {\n"
                       b"        proxy_pass http://127.0.0.1:7000;\n    }\n"
                       b"    location / {\n        return 404;\n    }\n}\n")
        self.alt.write_bytes(self.before)
        self.alt.chmod(0o644)
        self.domain = "ir.example.net"
        self.binding = ingress.digest(self.before)
        self.rt = SimpleNamespace(
            trusted_path=lambda file, **opts: file.lstat(),
            fsync_dir=Mock(),
            p=SimpleNamespace(DOMAIN=re.compile(r"[a-z.]+")),
            run=Mock(),
            panel_probe=Mock(),
        )
        self.edge = SimpleNamespace(rt=self.rt, alternate_probe=Mock())
        self.context = Mock(return_value=(self.domain, self.binding, self.alt, self.before))
        self.live = Mock()
        for key, value in (("STATE", self.state), ("runtime_context", self.context),
                           ("verify_live", self.live)):
            patcher = patch.object(ingress, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_apply_command_uses_shared_readiness_to_admit_either_role(self):
        control = SimpleNamespace(verify_rc9_backhaul_ready=Mock())
        self.rt.load = Mock(return_value=control)
        self.rt.locked = nullcontext
        self.edge.select_rc9 = Mock()
        for role in ("ir", "foreign"):
            with self.subTest(role=role), \
                    patch.object(ingress.sys, "argv", ["ingress", "apply", "--role", role]), \
                    patch.object(ingress.sys.stdin, "isatty", return_value=True), \
                    patch("builtins.input", return_value=f"APPLY-RC9-BACKHAUL-INGRESS-{role.upper()}"), \
                    patch.object(ingress.os, "geteuid", return_value=0), \
                    patch.object(ingress.importlib.util, "spec_from_file_location",
                                 return_value=SimpleNamespace(loader=Mock())), \
                    patch.object(ingress.importlib.util, "module_from_spec", return_value=self.edge), \
                    patch.object(ingress, "run_operation", return_value="APPLIED") as operation:
                self.assertEqual(ingress.main(), 0)
                control.verify_rc9_backhaul_ready.assert_called_with(role)
                operation.assert_called_once_with(self.edge, role, "apply")

    def test_uninstall_preflight_blocks_only_the_selected_managed_route(self):
        directory = self.state.parent / "routes"
        directory.mkdir()
        record = {"state": "COMMITTED", "port": 56053, "path": "/56053/web",
                  "snippet": "managed route", "kind": "backhaul"}
        journal = directory / ".56053.transaction.json"
        route = directory / "56053.conf"
        journal.write_text(json.dumps(record))
        journal.chmod(0o600)
        route.write_text(record["snippet"])
        self.rt.saved_tunnels_only = Mock()
        self.rt.run.return_value = "PID COMMAND\n123 backhaul"
        with patch.object(ingress, "XHTTP_ROUTES", directory):
            with self.assertRaisesRegex(ingress.Hold, "ENGINE_REMOVAL_ROUTE_ROLLBACK_REQUIRED"):
                ingress.review_engine_removal(self.rt, "ir", "backhaul")
            ingress.review_engine_removal(self.rt, "ir", "frp")
            self.rt.saved_tunnels_only.assert_called_once_with("backhaul")
            self.assertTrue(route.is_file())
            self.rt.run.return_value = "PID COMMAND\n123 frpc"
            with self.assertRaisesRegex(ingress.Hold, "ENGINE_REMOVAL_TUNNEL_STILL_RUNNING"):
                ingress.review_engine_removal(self.rt, "foreign", "frp")

    def test_ir_apply_replay_and_rollback(self):
        self.assertEqual(ingress.run_operation(self.edge, "ir", "plan"), "PLAN_READ_ONLY")
        self.assertFalse(self.state.exists())
        self.assertEqual(self.alt.read_bytes(), self.before)
        self.assertEqual(ingress.run_operation(self.edge, "ir", "apply"), "APPLIED")
        after = self.alt.read_bytes()
        self.assertIn(b"location = /~!frp", after)
        self.assertIn(b"location ^~ /tunnel/", after)
        ingress.check_ir_overlay(self.rt, self.alt,
                                 {"domain": self.domain, "alternate": self.binding}, self.before)
        self.assertEqual(ingress.run_operation(self.edge, "ir", "apply"), "VERIFIED")
        self.assertEqual(ingress.run_operation(self.edge, "ir", "rollback"), "RESTORED")
        self.assertFalse(self.state.exists())
        self.assertEqual(self.alt.read_bytes(), self.before)

    def test_ir_verifies_only_exact_committed_slot_map(self):
        self.assertEqual(ingress.run_operation(self.edge, "ir", "apply"), "APPLIED")
        legacy = self.alt.read_bytes()
        journal = ingress.validate_record(self.rt)
        slots = {"a" * 32: 3081, "b" * 32: 3082}
        after = ingress.render_ir(self.before, slots)
        self.assertIn(b"default 3080;", after)
        self.assertIn(b"proxy_pass http://127.0.0.1:7000;", legacy)
        self.assertIn(b"proxy_pass http://127.0.0.1:7000;", after)
        self.assertIn(b"uopti-bh-" + b"a" * 32, after)
        with self.assertRaisesRegex(ingress.Hold, "SLOTS_INVALID"):
            ingress.render_ir(self.before, {"a" * 32: 3080})
        with self.assertRaisesRegex(ingress.Hold, "SLOTS_INVALID"):
            ingress.render_ir(self.before, {"a" * 32: 3081, "b" * 32: 3081})

        self.alt.write_bytes(after)
        journal.update(slots=slots, after=ingress.digest(after))
        ingress.save(self.rt, journal)
        edge_doc = {"domain": self.domain, "alternate": self.binding}
        ingress.check_ir_overlay(self.rt, self.alt, edge_doc, self.before)
        self.assertEqual(ingress.run_operation(self.edge, "ir", "verify"), "VERIFIED")
        with self.assertRaisesRegex(ingress.Hold, "SHARED_CONTROL_SLOTS_ACTIVE"):
            ingress.run_operation(self.edge, "ir", "rollback")
        self.alt.write_bytes(after.replace(b" 3081;", b" 3083;"))
        with self.assertRaisesRegex(ingress.Hold, "CONFIGURATION_DRIFT"):
            ingress.check_ir_overlay(self.rt, self.alt, edge_doc, self.before)

    def test_add_slot_replays_without_rewriting_and_recovers_interrupted_add(self):
        self.assertEqual(ingress.run_operation(self.edge, "ir", "apply"), "APPLIED")
        self.rt.run.return_value = ""
        ingress.ensure_control_slot(self.edge, "a" * 32, 3081)
        existing = self.alt.read_bytes()
        self.live.reset_mock()
        ingress.ensure_control_slot(self.edge, "a" * 32, 3081)
        self.live.assert_not_called()

        class Interrupted(BaseException):
            pass

        self.live.side_effect = Interrupted()
        with self.assertRaises(Interrupted):
            ingress.ensure_control_slot(self.edge, "b" * 32, 3082)
        self.assertNotEqual(self.alt.read_bytes(), existing)
        self.live.side_effect = None
        ingress.recover_control_slot(self.edge)
        self.assertEqual(self.alt.read_bytes(), existing)
        self.assertEqual(ingress.validate_record(self.rt)["slots"], {"a" * 32: 3081})
        self.assertFalse(self.state.with_name(self.state.name + ".slot-pending").exists())
        ingress.ensure_control_slot(self.edge, "b" * 32, 3082)
        self.assertEqual(ingress.validate_record(self.rt)["slots"], {"a" * 32: 3081, "b" * 32: 3082})

    def test_apply_failure_compensates_without_leaving_journal(self):
        self.live.side_effect = ingress.Hold("BACKHAUL_CONTROL_ROUTE_NOT_PROVEN")
        with self.assertRaisesRegex(ingress.Hold, "APPLY_FAILED_RESTORED"):
            ingress.run_operation(self.edge, "ir", "apply")
        self.assertEqual(self.alt.read_bytes(), self.before)
        self.assertFalse(self.state.exists())

    def test_pending_apply_requires_recovery_and_preserves_external_drift(self):
        class Interrupted(BaseException):
            pass

        self.live.side_effect = Interrupted()
        with self.assertRaises(Interrupted):
            ingress.run_operation(self.edge, "ir", "apply")
        with self.assertRaisesRegex(ingress.Hold, "RECOVERY_REQUIRED"):
            ingress.run_operation(self.edge, "ir", "verify")
        after = self.alt.read_bytes()
        self.alt.write_bytes(b"external write")
        with self.assertRaisesRegex(ingress.Hold, "CONFIGURATION_DRIFT"):
            ingress.run_operation(self.edge, "ir", "rollback")
        self.assertEqual(self.alt.read_bytes(), b"external write")
        self.alt.write_bytes(after)
        self.assertEqual(ingress.run_operation(self.edge, "ir", "rollback"), "RESTORED")
        self.assertEqual(self.alt.read_bytes(), self.before)

    def test_foreign_refuses_an_occupied_bridge_and_uses_pinned_ipv4_tls(self):
        self.context.return_value = self.domain, self.binding, self.kh, None
        self.rt.run.side_effect = ["8.8.4.4 STREAM x\n8.8.4.4 DGRAM x", "busy"]
        with self.assertRaisesRegex(ingress.Hold, "PORT_IN_USE"):
            ingress.run_operation(self.edge, "foreign", "apply")
        self.assertFalse(self.kh.exists())
        self.rt.run.side_effect = None
        self.rt.run.return_value = ""
        with patch.object(ingress, "resolve_panel", return_value="8.8.4.4"):
            self.assertEqual(ingress.run_operation(self.edge, "foreign", "apply"), "APPLIED")
        config = self.kh.read_bytes()
        self.assertIn(b"listen 127.0.0.1:13080;", config)
        self.assertIn(b"proxy_pass https://8.8.4.4:443;", config)
        self.assertIn(b"proxy_ssl_name ir.example.net;", config)
        self.assertIn(b"proxy_ssl_verify on;", config)
        self.assertEqual(ingress.run_operation(self.edge, "foreign", "rollback"), "RESTORED")
        self.assertFalse(self.kh.exists())


if __name__ == "__main__":
    unittest.main()
