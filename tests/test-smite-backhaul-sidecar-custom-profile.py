#!/usr/bin/env python3
"""Custom KH Xray port + independent XHTTP path, tested as an exact pair.

Hermetic CI: creates only private /tmp proposals, never touches a running host.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

MOD = Path(__file__).resolve().parents[1] / "modules"


def load(alias, name):
    spec = importlib.util.spec_from_file_location(alias, MOD / name)
    assert spec and spec.loader
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


sidecar = load("custom_sidecar", "smite-backhaul-sidecar.py")
nginx = load("custom_nginx", "smite-backhaul-sidecar-nginx-plan.py")
paired = load("custom_paired", "smite-backhaul-sidecar-reconcile.py")
gate = load("custom_gate", "smite-backhaul-sidecar-admission.py")
audit = load("custom_audit", "smite-backhaul-sidecar-readiness.py")

IR = """server {
    listen 127.0.0.1:8443 ssl;
    server_name ir.example.com;
    location = /~!frp { proxy_pass http://127.0.0.1:7000; }
    location / { proxy_pass http://127.0.0.1:8000; }
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
PORT = 45123
PATH = "/assets/v1/connect"
SECRET = "A" * 43


class CustomFullBundle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token = Path(self.temp.name) / "shared.token"
        self.token.write_text(SECRET + "\n")
        self.token.chmod(0o600)

    def bundles(self, role):
        sc = sidecar.prepare(role, self.token, "ir.example.com", "kh.example.com",
                             data_port=PORT, xhttp_path=PATH)
        self.addCleanup(shutil.rmtree, sc)
        original = IR if role == "ir" else KH
        vhost = nginx.IR_PATH if role == "ir" else nginx.KH_PATH
        with patch.object(nginx, "original_bytes", return_value=original.encode()):
            ng = nginx.prepare(role, Path(vhost), "ir.example.com",
                               "kh.example.com", PORT, PATH)
        self.addCleanup(shutil.rmtree, ng)
        return sc, ng

    def test_exact_custom_pair_on_both_roles(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                sc, ng = self.bundles(role)
                result = paired.reconcile(role, sc, ng)
                self.assertEqual(len(result), len(paired.LAYOUT[role]))
                profile = audit.profile_from_text((sc / (role + ".toml")).read_text())
                self.assertEqual(profile, (PORT, PATH))
                plan = json.loads((ng / "plan.json").read_text())
                self.assertEqual(plan["profile"],
                                 {"data_port": PORT, "xhttp_path": PATH})
                if role == "ir":
                    output = (ng / "ir-xhttp.inc").read_text()
                    self.assertIn("location = /assets/v1/connect {", output)
                    self.assertIn("location ^~ /assets/v1/connect/ {", output)
                    self.assertIn("proxy_pass http://127.0.0.1:45123;", output)
                    self.assertNotIn("location ^~ /56053/www/", output)
                else:
                    kh = (ng / "patched.conf").read_text()
                    self.assertLess(kh.index("location ~ ^/0*13080(/|$)"),
                                    kh.index(nginx.KH_FWD_ANCHOR))

                with patch.object(gate, "_existing_ancestors_safe", return_value=True), \
                     patch.object(gate, "_created_resource_available", return_value=None), \
                     patch.object(gate, "_original_source", return_value=None), \
                     patch.object(gate.local, "inspect_local", return_value=[]) as inspected:
                    self.assertEqual([], gate.admission(role, sc, ng))
                inspected.assert_called_with(role, "new", data_port=PORT, xhttp_path=PATH)

    def test_tampered_custom_port_or_path_is_not_reconciled(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                sc, ng = self.bundles(role)
                manifest = ng / "plan.json"
                old = manifest.read_bytes()
                meta = json.loads(old)
                meta["profile"]["data_port"] = PORT + 1
                manifest.write_text(json.dumps(meta) + "\n")
                with self.assertRaises(paired.ReconcileRefused):
                    paired.reconcile(role, sc, ng)
                manifest.write_bytes(old)

                conf = sc / (role + ".toml")
                old_config = conf.read_bytes()
                conf.write_bytes(old_config.replace(
                    b"UOPTI_PROFILE_XHTTP_PATH=/assets/v1/connect",
                    b"UOPTI_PROFILE_XHTTP_PATH=/another/path"))
                with self.assertRaises(paired.ReconcileRefused):
                    paired.reconcile(role, sc, ng)
                conf.write_bytes(old_config)

    def test_custom_listener_checks_and_private_installed_metadata(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                sc, _ = self.bundles(role)
                with patch.object(audit, "CONFIG_DIR", sc):
                    # The reader expects role.toml; it never prints credentials.
                    self.assertEqual(audit.installed_profile(role), (PORT, PATH))
                actual = ('backhaul' if role == 'ir' else 'xray-linux-amd6')
                raw = (f'LISTEN 0 128 127.0.0.1:{PORT} 0.0.0.0:* '
                       f'users:(("{actual}",pid=42,fd=4))')
                listeners = audit.parse_listeners(raw, {PORT})
                self.assertIn(PORT, listeners)
                self.assertEqual([( "127.0.0.1", actual)], listeners[PORT])


if __name__ == "__main__":
    unittest.main()
