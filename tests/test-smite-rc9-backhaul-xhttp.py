#!/usr/bin/env python3
"""Backhaul route admission and recovery without live hosts or Docker."""

from pathlib import Path
from runpy import run_path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))
workflow = run_path(str(ROOT / "modules/smite-rc9-backhaul-xhttp.py"))
configure = workflow["configure"]
TUNNEL_ID = "28592460-d10a-4e40-b54a-1ae9642e0189"
INBOUND = {"port": 56053, "path": "/56053/web", "enabled": True,
           "listen": "127.0.0.1", "network": "xhttp", "protocol": "vless"}


class BackhaulXhttpTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.target = self.directory / "56053.conf"
        self.journal = self.directory / ".56053.transaction.json"
        self.rt = SimpleNamespace(load=Mock(return_value=SimpleNamespace(verify=Mock())),
                                  fsync_dir=Mock())
        self.edge = SimpleNamespace(rt=self.rt)
        self.ingress = SimpleNamespace(
            runtime_context=Mock(return_value=("panel.example.test", None, None, None)),
            run_operation=Mock(), render_fragment=Mock(return_value=b"tested snippet"),
            read_trusted=lambda rt, path, mode: path.read_bytes(), reload_nginx=Mock(),
            replace_bytes=lambda rt, path, data, mode, **kwargs: path.write_bytes(data))
        self.route = SimpleNamespace(
            ROUTE_DIR=self.directory, BIN="nginx", _safe_directory=Mock(),
            _run=Mock(return_value=""),
            _frps_socket_inventory=Mock(return_value=(1234, {7000, 32868})),
            check_locations=Mock())
        self.panel = Mock(side_effect=lambda rt, phase, port: {
            "active": phase == "activate", "id": TUNNEL_ID if phase == "activate" else None,
            "inbound": INBOUND})
        self.listener = Mock()
        self.probe = Mock(return_value=True)
        fixture = patch.dict(configure.__globals__, {
            "panel": self.panel, "listener": self.listener, "probe": self.probe})
        fixture.start()
        self.addCleanup(fixture.stop)

    def invoke(self, action):
        return configure(self.edge, self.ingress, self.route, 56053, action)

    def test_preview_has_no_listener_or_file_mutations(self):
        self.assertEqual(self.invoke("plan"), ("PLAN_READ_ONLY", INBOUND["path"]))
        self.assertEqual(self.panel.call_count, 1)
        self.ingress.reload_nginx.assert_not_called()
        self.assertFalse(self.target.exists())

    def test_create_verify_and_rollback_publication(self):
        compile(workflow["PANEL_JOB"], "pinned-panel-job", "exec")
        self.assertEqual(self.invoke("apply")[0], "APPLIED")
        self.assertEqual(self.target.read_bytes(), b"tested snippet")
        self.panel.side_effect = None
        self.panel.return_value = {"active": True, "id": TUNNEL_ID, "inbound": INBOUND}
        self.assertEqual(self.invoke("apply")[0], "VERIFIED")
        self.panel.side_effect = AssertionError("rollback must be local")
        self.assertEqual(self.invoke("rollback")[0], "ROLLED_BACK")
        self.assertFalse(self.target.exists())
        self.assertIn('"ROLLED_BACK"', self.journal.read_text())

    def test_failed_https_probe_rolls_back_route(self):
        self.probe.side_effect = [True, False]
        with self.assertRaisesRegex(RuntimeError, "PUBLIC_XHTTP_HANDLER_UNVERIFIED"):
            self.invoke("apply")
        self.assertFalse(self.target.exists())
        self.assertEqual(self.ingress.reload_nginx.call_count, 2)
        self.assertIn('"ROLLED_BACK"', self.journal.read_text())

    def test_frp_port_collision_never_activates_pair(self):
        self.route._frps_socket_inventory.return_value = (1234, {7000, 56053})
        with self.assertRaisesRegex(RuntimeError, "FRP_DATA_PORT_IN_USE"):
            self.invoke("apply")
        self.assertEqual(self.panel.call_count, 1)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
