#!/usr/bin/env python3
"""Read-only KH-source-scoped FRP WSS dual-TLS backend planner tests."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

SRC=Path(__file__).resolve().parents[1]/"modules/smite-rc2-frp-wss-edge-plan.py"
spec=importlib.util.spec_from_file_location("rc2_edge_plan",SRC)
edge=importlib.util.module_from_spec(spec)
spec.loader.exec_module(edge)

BACKEND=(
    "# Managed by U-OPTI - Smite Panel TLS backend\n"
    "server {\n"
    "    listen 127.0.0.1:8443 ssl;\n"
    "    server_name ir.kolbe1.ir;\n"
    "    location = /current-route {\n"
    "        proxy_pass http://127.0.0.1:32555;\n"
    "    }\n"
    "    location / {\n"
    "        proxy_pass http://127.0.0.1:8000;\n"
    "    }\n"
    "}\n"
)
MAP=edge.MAP_HEADER+('    "other.test|1.2.3.4" 127.0.0.1:7443;\n')
STREAM=(
    "# Managed by U-OPTI - Smite TCP/443 SNI gateway\n"
    "stream {\n"
    '    map "$ssl_preread_server_name|$remote_addr" $uopti_frp_canary_backend {\n'
    "        include /etc/nginx/u-opti-smite-frp-sni-map.conf;\n"
    "        default $uopti_smite_backend;\n"
    "    }\n"
    "    server {\n"
    "        listen 443;\n"
    "        ssl_preread on;\n"
    "        proxy_pass $uopti_frp_canary_backend;\n"
    "    }\n"
    "}\n"
)
IP="203.0.113.1"  # TEST fixture only. Never use as live approved IP.

class EdgeReview(unittest.TestCase):
    def test_exact_clone_preserves_panel_and_other_routes(self):
        modified=edge.render_alt(BACKEND)
        self.assertEqual(modified.count("location = /~!frp {"),1)
        self.assertIn("listen 127.0.0.1:8444 ssl;",modified)
        self.assertIn("location = /current-route",modified)
        self.assertIn("proxy_pass http://127.0.0.1:8000;",modified)
        self.assertIn("proxy_pass http://127.0.0.1:7000;",modified)
        self.assertEqual(modified.count("listen 127.0.0.1:8444 ssl;"),1)

    def test_untouched_existing_backend_never_contains_frp(self):
        self.assertNotIn("location = /~!frp {", BACKEND)
        edge.render_alt(BACKEND)
        self.assertNotIn("location = /~!frp {", BACKEND)

    def test_no_expansion_of_untrusted_backend(self):
        for value in (BACKEND.replace("# Managed by U-OPTI","untrusted"),
                      BACKEND.replace("127.0.0.1:8443","0.0.0.0:8443"),
                      BACKEND.replace("ir.kolbe1.ir","attacker.example"),
                      BACKEND.replace("    location / {",
                        "    location = /~!frp { return 200; }\n    location / {")):
            with self.subTest(source=value[-80:]):
                with self.assertRaises(edge.Hold):
                    edge.render_alt(value)

    def test_stream_source_ip_precedes_http_tls_backend(self):
        edge.stream_gate(STREAM)
        with self.assertRaisesRegex(edge.Hold,"STREAM_SOURCE_ALLOWLIST_NOT_ACTIVE"):
            edge.stream_gate(STREAM.replace(
                '$ssl_preread_server_name|$remote_addr',
                '$ssl_preread_server_name|127.0.0.1'))
        with self.assertRaisesRegex(edge.Hold,"STREAM_PROXY_NOT_USING_IP_MAP"):
            edge.stream_gate(STREAM.replace(
                "proxy_pass $uopti_frp_canary_backend;",
                "proxy_pass $uopti_smite_backend;"))

    def test_add_exact_ipv4_peer_rule_preserves_other_rules(self):
        before=MAP
        after=edge.render_map(before,"8.8.8.8")
        self.assertTrue(after.startswith(before))
        self.assertIn('"ir.kolbe1.ir|8.8.8.8" 127.0.0.1:8444;',after)
        self.assertIn('"other.test|1.2.3.4" 127.0.0.1:7443;',after)
        with self.assertRaisesRegex(edge.Hold,"KH_STREAM_RULE_ALREADY_REGISTERED"):
            edge.render_map(after,"8.8.8.8")

    def test_reject_nonpublic_ip(self):
        for ip in ("127.0.0.1","10.23.20.20","::1",
                   "192.168.0.2","172.16.0.1","0.0.0.0",
                   "255.255.255.255","not-a-valid-ip"):
            with self.subTest(ip=ip):
                with self.assertRaisesRegex(edge.Hold,
                    "VALID_KH_PUBLIC_IPV4_REQUIRED"):
                    edge.kh_ip(ip)

    def test_no_live_write_or_reload_actions(self):
        text=SRC.read_text()
        for forbidden in ("--force-recreate", "nginx -s reload",
                          "systemctl reload", "os.replace(", ".write_text(",
                          "unlink(", ".mkdir(", "docker compose up",
                          "iptables ", "ufw "):
            self.assertNotIn(forbidden,text)
        self.assertIn("DURABLE_RECONCILIATION=NOT_IMPLEMENTED",text)
        self.assertIn("KH_PEER_IP_OWNERSHIP=OPERATOR_VERIFICATION_REQUIRED",text)

if __name__=="__main__":
    unittest.main(verbosity=2)
