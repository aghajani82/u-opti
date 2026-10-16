#!/usr/bin/env python3
"""Hermetic readiness tests. NO access to production IR/KH hosts."""
import importlib.util
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules/smite-backhaul-sidecar-readiness.py"
spec = importlib.util.spec_from_file_location("sidecar_readiness", MODULE)
audit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit)


def ports_ir():
    return {443: [("0.0.0.0", "nginx"), ("[::]", "nginx")],
            8443: [("127.0.0.1", "nginx")],
            7000: [("127.0.0.1", "frps")],
            3080: [("127.0.0.1", "backhaul")],
            56053: [("127.0.0.1", "backhaul")]}


def ports_kh():
    return {443: [("0.0.0.0", "nginx")],
            13080: [("127.0.0.1", "nginx")],
            56053: [("127.0.0.1", "xray-linux-amd6")]}


def evaluate(role, mode, ports=None, **kwargs):
    return audit.evaluate(
        role, mode,
        ports=ports if ports is not None else (ports_ir() if role == "ir" else ports_kh()),
        nginx_ok=kwargs.get("nginx_ok", True),
        container_exists=kwargs.get("container_exists", True),
        container_ok=kwargs.get("container_ok", True),
        private_ok=kwargs.get("private_ok", True),
        routes_ok=kwargs.get("routes_ok", True),
        owned_files=kwargs.get("owned_files", True),
        data_port=kwargs.get("data_port", 56053),
        check_target=kwargs.get("check_target", True),
    )


class ReadinessTests(unittest.TestCase):
    def test_existing_ir_kh_pilot(self):
        self.assertEqual([], evaluate("ir", "existing"))
        self.assertEqual([], evaluate("kh", "existing"))

    def test_ir_dynamic_data_port_waits_for_kh_without_false_pass(self):
        # Real field sequence: installing IR first starts :3080, but the
        # dynamic :21235 listener appears only after KH connects.
        ir = ports_ir()
        ir.pop(56053)
        reasons = evaluate("ir", "existing", ports=ir, data_port=21235)
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith("WAITING_FOR_KH_PEER:"))
        self.assertIn("21235", reasons[0])
        ir[21235] = [("127.0.0.1", "backhaul")]
        self.assertEqual([], evaluate("ir", "existing", ports=ir,
                                      data_port=21235))

    def test_ir_unexpected_data_port_owner_not_mislabeled_waiting(self):
        ir = ports_ir()
        ir.pop(56053)
        ir[21235] = [("127.0.0.1", "other-process")]
        reasons = evaluate("ir", "existing", ports=ir, data_port=21235)
        self.assertEqual(len(reasons), 1)
        self.assertNotIn("WAITING_FOR_KH_PEER", reasons[0])
        self.assertIn("21235", reasons[0])
        # Any unrelated failure also prevents the benign waiting-only case.
        ir.pop(21235)
        reasons = evaluate("ir", "existing", ports=ir, data_port=21235,
                           routes_ok=False)
        self.assertEqual(len(reasons), 2)

    def test_waiting_cli_keeps_nonzero_exit_without_exposing_secrets(self):
        waiting = "WAITING_FOR_KH_PEER: IR data port 127.0.0.1:21235 not listening yet."
        with patch.object(audit, "inspect_local", return_value=[waiting]), \
             patch.object(sys, "argv", ["audit", "--role", "ir", "--mode", "existing"]), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(audit.main(), 2)
            self.assertIn("LOCAL_CHECK_INCOMPLETE_PEER_NOT_CONNECTED", output.getvalue())
            self.assertIn("do NOT re-run", output.getvalue())
            self.assertNotIn("EXISTING_SIDECAR_LOCAL_CHECKS_PASSED", output.getvalue())

    def test_fresh_on_empty_reserved_ports(self):
        ir = ports_ir()
        del ir[3080], ir[56053]
        kh = ports_kh()
        del kh[13080]
        self.assertEqual([], evaluate("ir", "new", ports=ir,
                                      container_exists=False, owned_files=False))
        self.assertEqual([], evaluate("kh", "new", ports=kh,
                                      container_exists=False, owned_files=False))

    def test_early_pairing_ignores_unused_legacy_data_port(self):
        ir = ports_ir()
        del ir[3080]
        ir[56053] = [("127.0.0.1", "another-service")]
        # IR may use another data port; pairing cannot demand legacy :56053.
        self.assertEqual([], evaluate("ir", "new", ports=ir,
                                      container_exists=False, owned_files=False,
                                      check_target=False))
        self.assertTrue(evaluate("ir", "new", ports=ir,
                                 container_exists=False, owned_files=False,
                                 check_target=True))
        kh = ports_kh()
        del kh[13080], kh[56053]
        kh[45123] = [("127.0.0.1", "xray-linux-amd6")]
        self.assertEqual([], evaluate("kh", "new", ports=kh,
                                      container_exists=False, owned_files=False,
                                      data_port=45123))
        self.assertTrue(evaluate("kh", "new", ports=kh,
                                 container_exists=False, owned_files=False,
                                 data_port=56053))

    def test_existing_or_partial_does_not_get_overwritten(self):
        for role in ("ir", "kh"):
            self.assertTrue(evaluate(role, "new"))
            self.assertTrue(evaluate(role, "new", container_exists=False))
        self.assertTrue(evaluate("kh", "existing", private_ok=False))
        self.assertTrue(evaluate("ir", "existing", routes_ok=False))
        self.assertTrue(evaluate("ir", "existing", container_ok=False))

    def test_public_binding_and_ambiguous_ownership_block(self):
        ir = ports_ir()
        ir[3080] = [("0.0.0.0", "backhaul")]
        self.assertTrue(any("3080" in x for x in evaluate("ir", "existing", ports=ir)))
        kh = ports_kh()
        kh[13080].append(("0.0.0.0", "nginx"))
        self.assertTrue(any("13080" in x for x in evaluate("kh", "existing", ports=kh)))
        ir = ports_ir()
        ir[3080] = [("127.0.0.1", "unexpected")]
        self.assertTrue(evaluate("ir", "existing", ports=ir))

    def test_parse_realistic_ss_output(self):
        raw = (
            'LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=11,fd=7))\n'
            'LISTEN 0 4096 127.0.0.1:56053 0.0.0.0:* users:(("backhaul",pid=42,fd=7))\n'
            'LISTEN 0 4096 127.0.0.1:3080 0.0.0.0:* users:(("backhaul",pid=42,fd=3))\n'
        )
        result = audit.parse_listeners(raw)
        self.assertEqual([("127.0.0.1", "backhaul")], result[3080])
        self.assertEqual([("0.0.0.0", "nginx")], result[443])
        with self.assertRaises(ValueError):
            audit.parse_listeners('LISTEN 0 1 127.0.0.1:3080 *:*\n')

    def test_nginx_ownership_guard_and_tls_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panel = root / "panel.conf"
            control = root / "control.inc"
            xhttp = root / "xhttp.inc"
            bridge = root / "bridge.conf"
            vhost = root / "vhost.conf"
            panel.write_text(
                "include /etc/nginx/u-opti-backhaul-sidecar-control.inc;\n"
                "include /etc/nginx/u-opti-backhaul-sidecar-xhttp.inc;\n"
            )
            control.write_text(
                "location = /channel { proxy_pass http://127.0.0.1:3080; }\n"
                "location ^~ /tunnel/ { proxy_pass http://127.0.0.1:3080; }\n"
            )
            xhttp.write_text(
                "location ^~ /56053/www/ { proxy_pass http://127.0.0.1:56053; }\n"
            )
            bridge.write_text(
                "listen 127.0.0.1:13080;\n"
                "location = /channel {}\nlocation ^~ /tunnel/ {}\n"
                "proxy_ssl_verify on;\nproxy_ssl_server_name on;\n"
                "proxy_pass https://ir.example.com;\n"
            )
            vhost.write_text(
                "location ~ ^/0*13080(/|$) {}\n"
                "location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {}\n"
            )
            with patch.multiple(audit, IR_PANEL=panel, IR_CONTROL=control, IR_XHTTP=xhttp,
                                KH_BRIDGE=bridge, KH_VHOST=vhost):
                self.assertTrue(audit.nginx_routes("ir"))
                self.assertTrue(audit.nginx_routes("kh"))
                vhost.write_text(vhost.read_text().splitlines()[::-1][0] + "\n"
                                 + vhost.read_text().splitlines()[0] + "\n")
                self.assertFalse(audit.nginx_routes("kh"))
                vhost.write_text(
                    "location ~ ^/0*13080(/|$) {}\n"
                    "location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {}\n"
                )
                bridge.write_text(bridge.read_text().replace("proxy_ssl_verify on;",
                                                               "proxy_ssl_verify off;"))
                self.assertFalse(audit.nginx_routes("kh"))

    def test_readiness_does_not_print_secrets(self):
        with patch.object(audit, "run_readonly", return_value=None), \
             patch.object(audit, "installed_profile", return_value=(56053, "/56053/www")):
            self.assertEqual(["Listener ownership unavailable; refuse inference"],
                             audit.inspect_local("ir", "existing"))
        with patch.object(audit, "installed_profile", return_value=None):
            self.assertEqual(["Installed Sidecar profile missing or invalid"],
                             audit.inspect_local("kh", "existing"))
        # Refuse all other commands, including container starts and live mutation.
        with self.assertRaises(ValueError):
            audit.run_readonly(("docker", "run", "alpine"))
        with self.assertRaises(ValueError):
            audit.run_readonly(("systemctl", "reload", "nginx"))

    def test_docker_pinning(self):
        data = "true|unless-stopped|host|" + audit.IMAGE
        with patch.object(audit, "run_readonly", return_value=data):
            self.assertEqual((True, True), audit.docker_state("ir"))
        with patch.object(audit, "run_readonly", return_value="true|always|host|" + audit.IMAGE):
            self.assertEqual((True, False), audit.docker_state("kh"))
        with patch.object(audit, "run_readonly", return_value=None):
            self.assertEqual((False, False), audit.docker_state("ir"))


if __name__ == "__main__":
    unittest.main()
