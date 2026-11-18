#!/usr/bin/env python3
"""RC9 Backhaul ingress tests with disposable files and stubbed host commands."""

import importlib.util
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
