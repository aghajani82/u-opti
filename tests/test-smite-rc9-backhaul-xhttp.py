#!/usr/bin/env python3
"""Backhaul route admission and recovery without live hosts or Docker."""

from pathlib import Path
from contextlib import nullcontext
import re
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


class ProbeTests(unittest.TestCase):
    def test_probe_uses_real_cors_and_matches_nginx_upstream_host(self):
        def run(cmd, **kwargs):
            have_cors = ("Access-Control-Request-Method: POST" in cmd
                         and "Origin: https://panel.example.test" in cmd)
            if not have_cors:
                return "HTTP/1.1 400 Bad Request\r\nX-Padding: abc"
            if "Host: panel.example.test" not in cmd:
                return "HTTP/1.1 404 Not Found"
            return "HTTP/1.1 200 OK\r\nX-Padding: abc"

        rt = SimpleNamespace(run=Mock(side_effect=run), Hold=RuntimeError)
        for public in (False, True):
            self.assertTrue(workflow["probe"](rt, "panel.example.test", 56053, "/56053/web", public))
        self.assertIn("http://127.0.0.1:56053/56053/web/", rt.run.call_args_list[0].args[0])
        self.assertIn("panel.example.test:443:127.0.0.1", rt.run.call_args_list[1].args[0])
        self.assertTrue(workflow["probe"](rt, "panel.example.test", 56053, "/56053/web",
                                         public=True, backend=True))
        self.assertIn("panel.example.test:443:127.0.0.1:8443", rt.run.call_args.args[0])

    def test_http_200_without_padding_is_still_rejected(self):
        rt = SimpleNamespace(run=Mock(return_value="HTTP/1.1 200 OK"), Hold=RuntimeError)
        self.assertFalse(workflow["probe"](rt, "panel.example.test", 56053, "/56053/web"))


class WorkerTests(unittest.TestCase):
    def test_idle_publisher_keeps_the_engine_and_route_locks_available(self):
        sync = workflow["sync_panel"]
        edge = SimpleNamespace(rt=SimpleNamespace(locked=Mock(side_effect=nullcontext)))
        ingress = SimpleNamespace(runtime_context=Mock())
        route = Mock()
        poll = Mock(side_effect=[False, True])
        lock = Mock(side_effect=lambda _: nullcontext())
        consume = Mock()
        with patch.dict(sync.__globals__, {"queue": poll, "route_lock": lock, "run_queue": consume}):
            sync(edge, ingress, route)
            edge.rt.locked.assert_not_called()
            lock.assert_not_called()
            consume.assert_not_called()
            sync(edge, ingress, route)
        edge.rt.locked.assert_called_once_with()
        lock.assert_called_once_with(route)
        consume.assert_called_once_with(edge, ingress, route)
        poll.assert_called_with(edge.rt, "poll")

    def test_worker_binds_the_selected_pair_and_reports_only_confirmed_publication(self):
        run_queue = workflow["run_queue"]
        edge = SimpleNamespace(rt=Mock())
        ingress = SimpleNamespace(runtime_context=Mock(), CONTROL_RESERVED_PORTS={3080})
        route = Mock()
        job = dict(id=TUNNEL_ID, port=56053, iran_node_id="ir", foreign_node_id="kh", name="Mobile")
        queue = Mock(side_effect=[job, None])
        apply = Mock(return_value=("APPLIED", INBOUND["path"]))
        compile(workflow["QUEUE_JOB"], "panel-queue-job", "exec")
        with patch.dict(run_queue.__globals__, {"queue": queue, "configure": apply}):
            run_queue(edge, ingress, route)
        apply.assert_called_once_with(edge, ingress, route, 56053, "apply", pair=("ir", "kh"), name="Mobile")
        queue.assert_called_with(edge.rt, "finish", TUNNEL_ID, "applied", INBOUND["path"], "")

    def test_worker_does_not_mark_a_failed_or_unverified_tunnel_as_applied(self):
        run_queue = workflow["run_queue"]
        edge = SimpleNamespace(rt=Mock())
        ingress = SimpleNamespace(runtime_context=Mock(), CONTROL_RESERVED_PORTS={3080})
        job = dict(id=TUNNEL_ID, port=56053, iran_node_id="ir", foreign_node_id="kh", name="Mobile")
        queue = Mock(side_effect=[job, None])
        apply = Mock(side_effect=RuntimeError("PUBLIC_XHTTP_HANDLER_UNVERIFIED"))
        with patch.dict(run_queue.__globals__, {"queue": queue, "configure": apply}):
            run_queue(edge, ingress, Mock())
        queue.assert_called_with(edge.rt, "finish", TUNNEL_ID, "hold", "", "PUBLIC_XHTTP_HANDLER_UNVERIFIED")


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
            recover_control_slot=Mock(), validate_record=Mock(return_value={}),
            ensure_control_slot=Mock(), CONTROL_RESERVED_PORTS={3080, 13080},
            read_trusted=lambda rt, path, mode: path.read_bytes(), reload_nginx=Mock(),
            replace_bytes=lambda rt, path, data, mode, **kwargs: path.write_bytes(data))
        self.route = SimpleNamespace(
            ROUTE_DIR=self.directory, BIN="nginx", _safe_directory=Mock(),
            _run=Mock(return_value=""),
            _frps_socket_inventory=Mock(return_value=(1234, {7000, 32868})),
            check_locations=Mock())
        self.panel = Mock(side_effect=lambda rt, phase, port, control=0, **kwargs: {
            "active": phase == "activate", "id": TUNNEL_ID if phase == "activate" else None,
            "inbound": INBOUND, "slot": None, "control_port": 3080, "reserved_ports": []})
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

    def test_reload_waits_for_real_public_xhttp_response(self):
        self.probe.side_effect = [True, False, False, True]
        with patch.object(configure.__globals__["time"], "sleep") as sleep:
            self.assertEqual(self.invoke("apply")[0], "APPLIED")
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(self.ingress.reload_nginx.call_count, 1)
        self.assertTrue(self.target.is_file())
        self.assertIn('"COMMITTED"', self.journal.read_text())

    def test_second_port_uses_reserved_independent_control(self):
        slot = "b" * 32
        self.ingress.validate_record.return_value = {"slots": {slot: 41001}}
        self.panel.side_effect = lambda rt, phase, port, control=0, **kwargs: {
            "active": phase == "activate", "id": TUNNEL_ID if phase == "activate" else None,
            "inbound": INBOUND, "slot": slot, "control_port": control or None,
            "reserved_ports": [3080, 38463],
        }
        self.assertEqual(self.invoke("apply")[0], "APPLIED")
        self.ingress.ensure_control_slot.assert_called_once_with(self.edge, slot, 41001)
        self.panel.assert_called_with(self.rt, "activate", 56053, 41001, pair=("", ""), name="")
        self.listener.assert_any_call(self.rt, 41001, TUNNEL_ID)

    def test_failed_https_probe_rolls_back_route(self):
        # The direct TLS backend responds, but the public socket never does.
        self.probe.side_effect = [True] + [False] * 5 + [True]
        with patch.object(configure.__globals__["time"], "sleep"):
            with self.assertRaisesRegex(RuntimeError, "PUBLIC_XHTTP_HANDLER_UNVERIFIED"):
                self.invoke("apply")
        self.assertTrue(self.probe.call_args.kwargs["backend"])
        self.assertFalse(self.target.exists())
        self.assertEqual(self.ingress.reload_nginx.call_count, 2)
        self.assertIn('"ROLLED_BACK"', self.journal.read_text())

    def test_frp_port_collision_never_activates_pair(self):
        self.route._frps_socket_inventory.return_value = (1234, {7000, 56053})
        with self.assertRaisesRegex(RuntimeError, "FRP_DATA_PORT_IN_USE"):
            self.invoke("apply")
        self.assertEqual(self.panel.call_count, 1)
        self.assertFalse(self.target.exists())

    def test_first_backhaul_publication_without_frps(self):
        self.route._frps_socket_inventory.return_value = (None, frozenset())
        self.assertEqual(self.invoke("apply"), ("APPLIED", INBOUND["path"]))
        self.assertIn('"COMMITTED"', self.journal.read_text())
        self.panel.assert_called_with(self.rt, "activate", 56053, 3080, pair=("", ""), name="")
        self.route._frps_socket_inventory.assert_called_with()

    def test_unexpected_frps_listener_is_not_treated_as_absent(self):
        self.route.RouteTransactionHold = ValueError
        self.route.BIND = re.compile(r'"frps",pid=([0-9]+)')
        self.route._frps_socket_inventory.side_effect = ValueError("FRPS_OWNER_7000_MISSING")
        self.assertEqual(workflow["frps_snapshot"](self.route), (None, frozenset()))
        self.route._run.return_value = 'LISTEN 0 0 127.0.0.1:7001 0.0.0.0:* users:(("frps",pid=100))'
        with self.assertRaisesRegex(ValueError, "FRPS_OWNER_7000_MISSING"):
            workflow["frps_snapshot"](self.route)


if __name__ == "__main__":
    unittest.main()
