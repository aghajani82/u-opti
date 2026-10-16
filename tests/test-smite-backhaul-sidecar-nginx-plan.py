#!/usr/bin/env python3
"""Hermetic tests: render proposal files under /tmp only, never modify /etc."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "modules/smite-backhaul-sidecar-nginx-plan.py"
spec = importlib.util.spec_from_file_location("sidecar_nginx_plan", FILE)
plan = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(plan)

IR = """server {
    listen 127.0.0.1:8443 ssl;
    server_name ir.example.com;

    location = /~!frp {
        proxy_pass http://127.0.0.1:7000;
    }

    include /etc/nginx/u-opti-smite-frp-xhttp.conf;

    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
"""
KH = """server {
    listen 443 ssl http2;
    server_name kh.example.com;

    location / { return 404; }

    location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {
        proxy_pass http://127.0.0.1:$fwdport$is_args$args;
    }
}
"""


class NginxPlanTests(unittest.TestCase):
    def compile(self, role, source=None):
        return plan.compile_nginx(role, (source or (IR if role == "ir" else KH)).encode(),
                                  "ir.example.com", "kh.example.com")

    def test_ir_exact_include_paths_and_legacy_preserved(self):
        patched, additional, destination = self.compile("ir")
        rendered = patched.decode()
        self.assertEqual(destination, plan.IR_PATH)
        self.assertEqual(set(additional), {plan.IR_CONTROL, plan.IR_XHTTP})
        self.assertIn("proxy_pass http://127.0.0.1:7000;", rendered)
        self.assertIn("include /etc/nginx/u-opti-smite-frp-xhttp.conf;", rendered)
        self.assertIn(f"include {plan.IR_CONTROL};", rendered)
        self.assertIn(f"include {plan.IR_XHTTP};", rendered)
        self.assertIn(b"location = /channel", additional[plan.IR_CONTROL])
        self.assertIn(b"location ^~ /tunnel/", additional[plan.IR_CONTROL])
        self.assertIn(b"proxy_pass http://127.0.0.1:56053;", additional[plan.IR_XHTTP])
        self.assertIn(b"Host kh.example.com", additional[plan.IR_XHTTP])
        self.assertLess(rendered.index(plan.IR_CONTROL), rendered.index("    location / {"))
        self.assertEqual(rendered.count("proxy_pass http://127.0.0.1:8000;"), 1)

    def test_kh_bridge_strict_tls_and_public_guard_order(self):
        patched, additional, destination = self.compile("kh")
        self.assertEqual(destination, plan.kh_vhost_path("kh.example.com"))
        self.assertEqual(set(additional), {plan.KH_BRIDGE})
        text = patched.decode()
        self.assertIn("location ~ ^/0*13080(/|$)", text)
        self.assertLess(text.index("location ~ ^/0*13080(/|$)"),
                        text.index(plan.KH_FWD_ANCHOR))
        self.assertEqual(text.count(plan.KH_FWD_ANCHOR), 1)
        bridge = additional[plan.KH_BRIDGE]
        self.assertIn(b"proxy_ssl_verify on;", bridge)
        self.assertIn(b"proxy_ssl_server_name on;", bridge)
        self.assertIn(b"proxy_pass https://ir.example.com:443;", bridge)
        self.assertIn(b"listen 127.0.0.1:13080", bridge)

    def test_kh_custom_domain_resolves_exact_expected_vhost(self):
        new_host = "01kh.kolbe1.ir"
        source = KH.replace("kh.example.com", new_host)
        patched, additional, destination = plan.compile_nginx(
            "kh", source.encode(), "01ir.kolbe1.ir", new_host,
            42809, "/42809/tu")
        self.assertEqual(destination, "/etc/nginx/sites-available/3xui-01kh.kolbe1.ir")
        self.assertIn(b"location ~ ^/0*13080(/|$)", patched)
        self.assertIn(plan.KH_BRIDGE, additional)
        with patch.object(plan, "original_bytes", return_value=source.encode()):
            with self.assertRaises(plan.PlanRefused):
                plan.prepare("kh", Path(plan.KH_PATH),
                             "01ir.kolbe1.ir", new_host, 42809, "/42809/tu")

    def test_ir_refuses_duplicate_locations_and_layout(self):
        malformed = (
            IR.replace("    location / {", "    location = /channel {\n    }\n    location / {"),
            IR.replace("127.0.0.1:8443", "0.0.0.0:8443"),
            IR.replace("127.0.0.1:8000", "127.0.0.1:9000"),
            IR.replace("server_name ir.example.com", "server_name other.example.com"),
            IR + "server {\n}\n",
            IR.replace("    location / {", "    include /etc/nginx/u-opti-backhaul-sidecar-control.inc;\n    location / {"),
        )
        for source in malformed:
            with self.subTest(source=source[-140:]), self.assertRaises(plan.PlanRefused):
                self.compile("ir", source)

    def test_kh_refuses_already_guarded_or_unknown_forward(self):
        for source in (
            KH.replace(plan.KH_FWD_ANCHOR, "location /wrong/ {"),
            KH.replace(plan.KH_FWD_ANCHOR, plan.GUARD + plan.KH_FWD_ANCHOR),
            KH.replace("443 ssl http2", "444 ssl http2"),
            KH.replace("kh.example.com", "else.example.com"),
            KH.replace(plan.KH_FWD_ANCHOR, plan.KH_FWD_ANCHOR + "\n    " + plan.KH_FWD_ANCHOR),
        ):
            with self.subTest(source=source[-100:]), self.assertRaises(plan.PlanRefused):
                self.compile("kh", source)

    def test_input_symlink_refused_without_side_effect(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "config"
            link = Path(root) / "linked"
            source.write_text(IR)
            link.symlink_to(source)
            with self.assertRaises(plan.PlanRefused):
                plan.original_bytes(link)
            self.assertEqual(source.read_text(), IR)

    def test_private_atomic_candidate_files_manifest_and_no_live_edit(self):
        for role, original, target in (
            ("ir", IR, plan.IR_PATH), ("kh", KH, plan.kh_vhost_path("kh.example.com"))
        ):
            with self.subTest(role=role), patch.object(plan, "original_bytes",
                                                       return_value=original.encode()):
                stage = plan.prepare(role, Path(target),
                                     "ir.example.com", "kh.example.com")
                try:
                    self.assertEqual(stat.S_IMODE(stage.stat().st_mode), 0o700)
                    files = list(stage.iterdir())
                    self.assertTrue(files)
                    for file in files:
                        self.assertTrue(file.is_file())
                        self.assertFalse(file.is_symlink())
                        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
                    saved = json.loads((stage / "plan.json").read_text())
                    self.assertEqual(saved["status"], "REVIEW_ONLY_NO_DEPLOYMENT")
                    self.assertEqual(saved["nginx_edit"]["path"], target)
                    self.assertEqual(saved["nginx_edit"]["original_sha256"],
                                     plan.digest(original.encode()))
                    self.assertEqual(saved["nginx_edit"]["patched_sha256"],
                                     plan.digest((stage / "patched.conf").read_bytes()))
                    for f in saved["new_files"]:
                        self.assertEqual(f["sha256"], plan.digest(
                            (stage / f["candidate"]).read_bytes()))
                    self.assertEqual((stage / "original.conf").read_text(), original)
                    self.assertIn("NOT INSTALLED",
                                  (stage / "NOT-INSTALLED.txt").read_text())
                finally:
                    shutil.rmtree(stage)

    def test_refuses_wrong_path_or_secret_domain_injection(self):
        with patch.object(plan, "original_bytes", return_value=IR.encode()):
            with self.assertRaises(plan.PlanRefused):
                plan.prepare("ir", Path(plan.KH_PATH),
                             "ir.example.com", "kh.example.com")
        with self.assertRaises(plan.PlanRefused):
            self.compile("ir", IR.replace("ir.example.com",
                                         "ir.example.com; return 200;"))
        for domain in ("example..com", "https://example.com", "a.example.com;",
                       "UPPER.example.com", "a.example.com\nlocation / {}"):
            with self.subTest(domain=domain), self.assertRaises(plan.PlanRefused):
                plan.compile_nginx("ir", IR.encode(), domain, "kh.example.com")


if __name__ == "__main__":
    unittest.main()
