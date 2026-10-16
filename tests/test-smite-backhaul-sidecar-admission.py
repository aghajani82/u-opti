#!/usr/bin/env python3
"""Hermetic test for read-only host admission of paired private stages."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "backhaul_admission_under_test", ROOT / "modules/smite-backhaul-sidecar-admission.py")
gate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(gate)

IR = [
    {"path": "/etc/u-opti/backhaul-sidecar/ir.toml", "operation": "create",
     "before": None, "after": b"private"},
    {"path": "/etc/nginx/u-opti-backhaul-sidecar-control.inc",
     "operation": "create", "before": None, "after": b"private"},
    {"path": "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf",
     "operation": "edit", "before": b"server { safe old config }",
     "after": b"server { safe new config }"},
]
KH = [
    {"path": "/etc/u-opti/backhaul-sidecar/kh.toml", "operation": "create",
     "before": None, "after": b"private"},
    {"path": "/etc/nginx/conf.d/u-opti-backhaul-sidecar-bridge.conf",
     "operation": "create", "before": None, "after": b"private"},
    {"path": "/etc/nginx/sites-available/3xui-kh.kolbe1.ir",
     "operation": "edit", "before": b"old guarded vhost",
     "after": b"guard before numeric forward"},
]


class AdmissionTests(unittest.TestCase):
    def verify(self, role, rows, *, conflicts=None, baseline=None,
               source_error=None, bad_ancestor=None):
        conflicts = conflicts or set()
        baseline = baseline or []
        with patch.object(gate.paired, "reconcile", return_value=rows), \
             patch.object(gate.local, "inspect_local", return_value=baseline), \
             patch.object(gate, "_existing_ancestors_safe",
                          side_effect=lambda path: path.name not in (bad_ancestor or set())), \
             patch.object(gate, "_created_resource_available",
                          side_effect=lambda path: (
                              "Resource already exists; NO OVERWRITE: " + path.name
                              if path.name in conflicts else None
                          )), \
             patch.object(gate, "_original_source", return_value=source_error):
            return gate.admission(role, Path("/tmp/secret1"), Path("/tmp/secret2"))

    def test_both_roles_pass_with_exact_candidates_and_fresh_baseline(self):
        self.assertEqual([], self.verify("ir", IR))
        self.assertEqual([], self.verify("kh", KH))

    def test_existing_container_ports_or_invalid_nginx_blocks(self):
        fail = "Independent Sidecar container already exists"
        self.assertEqual([fail], self.verify("ir", IR, baseline=[fail]))
        self.assertEqual([fail], self.verify("kh", KH, baseline=[fail]))

    def test_guard_bridge_and_other_created_file_collisions(self):
        for role, rows, filename in (
            ("ir", IR, "ir.toml"),
            ("kh", KH, "u-opti-backhaul-sidecar-bridge.conf"),
        ):
            if role == "kh":
                filename = "u-opti-backhaul-sidecar-bridge.conf"
            issues = self.verify(role, rows, conflicts={filename})
            if role == "ir":
                self.assertEqual(len(issues), 1)
                self.assertIn("NO OVERWRITE", issues[0])
            else:
                # Use actual path basename from the fixture, not a guess.
                exact = Path(KH[1]["path"]).name
                issues = self.verify(role, rows, conflicts={exact})
                self.assertTrue(any("NO OVERWRITE" in item for item in issues))

    def test_drifted_original_or_bad_ancestor_refuses(self):
        self.assertTrue(any("drift" in x for x in
                            self.verify("ir", IR, source_error="Nginx source drifted")))
        self.assertTrue(any("ancestor" in x for x in self.verify(
            "kh", KH, bad_ancestor={Path(KH[-1]["path"]).name})))

    def test_cannot_accept_incomplete_or_tampered_candidate(self):
        with patch.object(gate.paired, "reconcile",
                          side_effect=gate.paired.ReconcileRefused("private-token-secret")):
            with self.assertRaisesRegex(gate.AdmissionRefused, "Candidate identity"):
                gate.admission("ir", Path("/tmp/invalid"), Path("/tmp/invalid"))
        with self.assertRaises(gate.AdmissionRefused):
            gate.admission("bogus", Path("/tmp/invalid"), Path("/tmp/invalid"))

    def test_real_frp_collision_guard_for_numeric_xhttp(self):
        import io
        import stat as os_stat
        from types import SimpleNamespace

        frp = b"""# Managed FRP XHTTP
    location = /45561/web {
        proxy_pass http://127.0.0.1:45561;
    }
    location ^~ /45561/web/ {
        proxy_pass http://127.0.0.1:45561;
    }
"""
        baseline = SimpleNamespace(
            st_mode=os_stat.S_IFREG | 0o644, st_uid=0, st_gid=0,
            st_dev=1, st_ino=22, st_size=len(frp), st_mtime_ns=19
        )

        class PrivateFixture:
            def lstat(self):
                return baseline

            def open(self, mode):
                return io.BytesIO(frp)

        with patch.object(gate, "FRP_XHTTP", PrivateFixture()):
            source = ("server {\n"
                      "include /etc/nginx/u-opti-smite-frp-xhttp.conf;\n"
                      "}").encode()
            self.assertIn("existing FRP route",
                          gate.existing_frp_route_collision(source, "/45561/web"))
            self.assertIsNone(gate.existing_frp_route_collision(source, "/48123/web"))
            self.assertIsNone(gate.existing_frp_route_collision(source, "/assets/ok"))
            self.assertIsNone(gate.existing_frp_route_collision(
                b"server { location / {} }", "/45561/web"))

    def test_fails_closed_on_world_writable_or_nonroot_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "original.conf"
            source.write_bytes(b"server {}\n" * 10)
            source.chmod(0o666)
            self.assertIn("not a safe", gate._original_source(source, source.read_bytes()))
            source.chmod(0o600)
            if source.stat().st_uid != 0:
                self.assertIn("not a safe",
                              gate._original_source(source, source.read_bytes()))
            source.unlink()
            self.assertIn("unreadable", gate._original_source(source, b"data"))

    def test_no_mutation_or_network_actions(self):
        code = (ROOT / "modules/smite-backhaul-sidecar-admission.py").read_text()
        for phrase in ("docker run", "docker stop", "nginx -s reload",
                       "subprocess.Popen", "unlink(", "os.replace(", "mkdir("):
            self.assertNotIn(phrase, code)


if __name__ == "__main__":
    unittest.main()
