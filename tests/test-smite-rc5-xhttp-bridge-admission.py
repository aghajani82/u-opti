#!/usr/bin/env python3
"""Offline U-OPTI/Smite RC5 stream 443 -> TLS 8443 bridge admission tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "smite_rc5_bridge_admission",
    ROOT / "modules" / "smite-rc5-xhttp-bridge-admission.py",
)
tx = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tx
spec.loader.exec_module(tx)

DOMAIN = "ir.kolbe1.ir"
BACKEND = (f"""# Managed by U-OPTI - Smite Panel TLS backend
server {{
    listen 127.0.0.1:8443 ssl;
    server_name {DOMAIN};
    ssl_certificate     /etc/letsencrypt/live/{DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{DOMAIN}/privkey.pem;
    location = /~!frp {{
        proxy_pass http://127.0.0.1:7000;
    }}
    include /etc/nginx/u-opti-smite-frp-xhttp.conf;
    location / {{
        proxy_pass http://127.0.0.1:8000;
    }}
}}
""").encode()
STREAM = b"""# Managed by U-OPTI - Smite TCP/443 SNI gateway
stream {
    map $ssl_preread_server_name $uopti_smite_backend {
        include /etc/nginx/u-opti-smite-stream-map.conf;
        default 127.0.0.1:8443;
    }
    server {
        listen 443;
        ssl_preread on;
        proxy_pass $uopti_frp_canary_backend;
    }
}
"""
SNI_MAP = b"# U-OPTI SNI map\nir.kolbe1.ir    127.0.0.1:8443;\n"
LEGACY = b"""# Managed by U-OPTI - Standard FRP XHTTP
    location = /45121/www {
        proxy_pass http://127.0.0.1:45121;
    }
    location ^~ /45121/www/ {
        proxy_pass http://127.0.0.1:45121;
    }
    location = /49328/sso {
        proxy_pass http://127.0.0.1:49328;
    }
    location ^~ /49328/sso/ {
        proxy_pass http://127.0.0.1:49328;
    }
"""


class BridgeAdmissionTests(unittest.TestCase):
    def plan(self, **kwargs):
        data = {
            "backend": BACKEND, "stream": STREAM, "sni_map": SNI_MAP,
            "legacy": LEGACY, "domain": DOMAIN, "timer_enabled": False,
            "bridge_exists": False, "directory_exists": False,
        }
        data.update(kwargs)
        return tx.propose_bridge(**data)

    def test_exact_443_stream_to_8443_backend_only_and_legacy_unchanged(self):
        result = self.plan()
        self.assertEqual(result.change_count, 1)
        self.assertEqual(result.domain, DOMAIN)
        self.assertEqual(result.original, BACKEND)
        self.assertIn(tx.OLD_INCLUDE, result.candidate)
        self.assertIn(tx.INCLUDE, result.candidate)
        self.assertLess(result.candidate.index(tx.INCLUDE),
                        result.candidate.index(tx.ROOT_LOCATION))
        self.assertEqual(result.candidate.replace(tx.INCLUDE + b"\n", b""), BACKEND)
        self.assertNotIn(b"45121", result.candidate)
        self.assertNotIn(b"49328", result.candidate)
        self.assertEqual(LEGACY.count(b"location = "), 2)
        self.assertEqual(STREAM.count(b"listen 443;"), 1)

    def test_wrong_tls_backend_and_domain_fail_closed(self):
        cases = [
            {"backend": BACKEND.replace(b"127.0.0.1:8443 ssl", b"0.0.0.0:8443 ssl")},
            {"backend": BACKEND.replace(DOMAIN.encode(), b"other.example.net")},
            {"backend": BACKEND.replace(b"ssl_certificate_key", b"ssl_certificateXX")},
            {"backend": BACKEND.replace(tx.OLD_INCLUDE, b"")},
            {"backend": BACKEND + b"server {\n}\n"},
            {"backend": BACKEND.replace(tx.ROOT_LOCATION, b"location / {\n")},
            {"domain": "bad\nserver { return 200; }"},
            {"domain": "example.com;"},
        ]
        for item in cases:
            with self.subTest(item=item), self.assertRaises(tx.BridgeHold):
                self.plan(**item)

    def test_sni_drift_and_bypass_refused(self):
        for item in (
            {"stream": STREAM.replace(b"listen 443;", b"listen 8443;")},
            {"stream": STREAM.replace(b"ssl_preread on;", b"ssl_preread off;")},
            {"stream": STREAM.replace(b"$uopti_frp_canary_backend", b"0.0.0.0:7000")},
            {"stream": STREAM + b"listen 443;"},
            {"sni_map": SNI_MAP.replace(b"127.0.0.1:8443", b"127.0.0.1:9443")},
            {"sni_map": SNI_MAP + b"ir.kolbe1.ir 127.0.0.1:8443;\n"},
            {"sni_map": SNI_MAP.replace(b"ir.kolbe1.ir", b"kh.kolbe1.ir")},
        ):
            with self.subTest(item=item), self.assertRaises(tx.BridgeHold):
                self.plan(**item)

    def test_reject_competing_legacy_timer_or_bridge_and_untrusted_sources(self):
        for item in (
            {"timer_enabled": True},
            {"bridge_exists": True},
            {"directory_exists": True},
            {"backend": BACKEND + b"\ninclude /etc/nginx/smite-xhttp-bridge.conf;\n"},
            {"legacy": b"# unknown template\n"},
            {"legacy": b""},
            {"backend": b"\x00" * (tx.MAX_BYTES + 1)},
        ):
            with self.subTest(item=item), self.assertRaises(tx.BridgeHold):
                self.plan(**item)

    def test_backend_dual_rule_not_modified(self):
        varied = BACKEND.replace(
            tx.OLD_INCLUDE,
            tx.OLD_INCLUDE + b"    location = /status { return 404; }\n"
        )
        result = self.plan(backend=varied)
        self.assertIn(b"location = /status { return 404; }", result.candidate)
        self.assertEqual(result.candidate.replace(tx.INCLUDE + b"\n", b""), varied)

    def test_cli_refuses_any_apply_attempt(self):
        for args in (["--apply"], [], ["--check", "--apply"]):
            with patch.object(sys, "argv", ["bridge"] + args):
                self.assertEqual(tx.main(), 2)

    def test_live_inspection_does_not_touch_files_or_services(self):
        source = {
            tx.BACKEND: BACKEND, tx.STREAM: STREAM,
            tx.SNI_MAP: SNI_MAP, tx.LEGACY: LEGACY,
            tx.STATE: b"SMITE_PANEL_DOMAIN=ir.kolbe1.ir\n",
        }
        dump = "".join(f"# configuration file {p}:\n" for p in (
            tx.BACKEND, tx.STREAM, tx.SNI_MAP, tx.LEGACY
        ))
        calls = []

        def fake_run(command):
            calls.append(tuple(command))
            if command == [tx.NGINX, "-T"]:
                return (0, dump)
            return (0, "")

        with (patch.object(tx.os, "geteuid", return_value=0),
              patch.object(tx.os, "uname") as uname,
              patch.object(tx, "_read_root_file", side_effect=source.__getitem__),
              patch.object(tx, "_run", side_effect=fake_run),
              patch.object(tx, "_timer_is_unsafe", return_value=False),
              patch.object(Path, "exists", return_value=False),
              patch.object(Path, "is_symlink", return_value=False)):
            uname.return_value.nodename = "ir"
            proposed = tx.audit_read_only()
        self.assertEqual(proposed.original, BACKEND)
        self.assertEqual(calls, [(tx.NGINX, "-t"), (tx.NGINX, "-T")])
        self.assertNotIn((tx.NGINX, "-s", "reload"), calls)

    def test_live_inspection_rejects_unrecognized_effective_source(self):
        source = {
            tx.BACKEND: BACKEND, tx.STREAM: STREAM,
            tx.SNI_MAP: SNI_MAP, tx.LEGACY: LEGACY,
            tx.STATE: b"SMITE_PANEL_DOMAIN=ir.kolbe1.ir\n",
        }
        with (patch.object(tx.os, "geteuid", return_value=0),
              patch.object(tx.os, "uname") as uname,
              patch.object(tx, "_read_root_file", side_effect=source.__getitem__),
              patch.object(tx, "_run", return_value=(0, "unrelated config")),
              patch.object(Path, "exists", return_value=False),
              patch.object(Path, "is_symlink", return_value=False)):
            uname.return_value.nodename = "ir"
            with self.assertRaises(tx.BridgeHold):
                tx.audit_read_only()


if __name__ == "__main__":
    unittest.main()
