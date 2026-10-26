#!/usr/bin/env python3
"""Offline, no-Nginx, no-Docker tests for signed RC2 two-vhost XHTTP include transaction."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"modules/smite-frp-rc2-xhttp-include-transaction.py"
spec=importlib.util.spec_from_file_location("rc2_xhttp_include",SOURCE)
tx=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)


class DualVhostTransactionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="rc2-include-")
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.backend=self.root/"panel-8443.conf"
        self.snippet=self.root/"xhttp.conf"
        self.tx_root=self.root/"private"
        self.tx_dir=self.tx_root/"ir"
        self.backup=self.tx_dir/"panel-backend.before"
        self.record=self.tx_dir/"record.json"
        self.before_bytes=(
            b"# Managed by U-OPTI - Smite Panel TLS backend\n"
            b"server {\n"
            b"    listen 127.0.0.1:8443 ssl;\n"
            b"    server_name ir.kolbe1.ir;\n"
            b"    location = /healthz {\n"
            b"        proxy_pass http://127.0.0.1:8000;\n"
            b"    }\n"
            b"    location / {\n"
            b"        proxy_pass http://127.0.0.1:8000;\n"
            b"    }\n"
            b"}\n"
        )
        self.backend.write_bytes(self.before_bytes)
        self.backend.chmod(0o644)
        patches=[
            patch.object(tx,"BACKEND",self.backend),
            patch.object(tx,"SNIPPET",self.snippet),
            patch.object(tx,"TX_ROOT",self.tx_root),
            patch.object(tx,"TX_DIR",self.tx_dir),
            patch.object(tx,"BACKUP",self.backup),
            patch.object(tx,"RECORD",self.record),
            patch.object(tx,"check_host",return_value=None),
            patch.object(tx,"acquire_lock",
                         side_effect=lambda:os.open(os.devnull,os.O_RDONLY)),
            patch.object(tx.gate,"audit",return_value=None),
            patch.object(tx,"nginx_test",return_value=None),
            patch.object(tx,"probe_panel",return_value=None),
            patch.object(tx,"reload_nginx",return_value=None),
            patch.object(tx,"directory",return_value=None),
            patch.object(tx,"trusted",
                         side_effect=lambda path,limit=131072,mode=None:path.read_bytes()),
        ]
        for p in patches:
            p.start();self.addCleanup(p.stop)

    def test_plan_is_read_only(self):
        a,b=tx.before()
        self.assertEqual(a,self.before_bytes)
        self.assertEqual(b,tx.candidate(self.before_bytes))
        self.assertEqual(self.backend.read_bytes(),self.before_bytes)
        self.assertFalse(self.snippet.exists())
        self.assertFalse(self.tx_root.exists())

    def test_create_exact_8443_include_and_empty_snippet(self):
        tx.apply()
        self.assertEqual(self.snippet.read_bytes(),tx.HEADER)
        self.assertEqual(self.backend.read_bytes(),tx.candidate(self.before_bytes))
        self.assertEqual(self.backend.read_bytes().count(tx.INCLUDE),1)
        self.assertEqual(stat.S_IMODE(self.backend.stat().st_mode),0o644)
        self.assertEqual(stat.S_IMODE(self.snippet.stat().st_mode),0o644)
        self.assertEqual(stat.S_IMODE(self.backup.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(self.record.stat().st_mode),0o600)
        tx.verify()
        with self.assertRaisesRegex(tx.Hold,"EXISTING_TRANSACTION_REQUIRES_REVIEW"):
            tx.apply()
        self.assertEqual(self.snippet.read_bytes(),tx.HEADER)

    def test_rollback_after_commit_restores_original_exact_bytes(self):
        tx.apply()
        tx.rollback()
        self.assertFalse(self.snippet.exists())
        self.assertEqual(self.backend.read_bytes(),self.before_bytes)
        self.assertEqual(tx.get_record()["state"],"ROLLED_BACK")

    def test_rollback_refuses_any_active_snippet_routes(self):
        tx.apply()
        self.snippet.write_bytes(tx.HEADER+b"    location = /45121/www {}\n")
        with self.assertRaisesRegex(tx.Hold,"CRITICAL_SNIPPET_MODIFIED_EXTERNALLY"):
            tx.rollback()
        self.assertIn(tx.INCLUDE,self.backend.read_bytes())

    def test_rollback_refuses_backend_drift(self):
        tx.apply()
        self.backend.write_bytes(b"changed externally")
        with self.assertRaisesRegex(tx.Hold,"CRITICAL_BACKEND_MODIFIED_EXTERNALLY"):
            tx.rollback()
        self.assertEqual(self.backend.read_bytes(),b"changed externally")

    def test_nginx_syntax_failure_auto_restores(self):
        with patch.object(tx,"nginx_test",side_effect=[
            None,
            tx.Hold("NGINX_CONFIG_INVALID"),
            None,
        ]):
            with self.assertRaisesRegex(tx.Hold,"INCLUDE_FAILED_ROLLED_BACK"):
                tx.apply()
        self.assertFalse(self.snippet.exists())
        self.assertEqual(self.backend.read_bytes(),self.before_bytes)
        self.assertEqual(tx.get_record()["state"],"ROLLED_BACK")

    def test_failed_tls_probe_auto_restores(self):
        with patch.object(tx,"probe_panel",side_effect=[
            None,
            tx.Hold("PANEL_HTTPS_PROBE_FAILED"),
            None,
        ]):
            with self.assertRaisesRegex(tx.Hold,"INCLUDE_FAILED_ROLLED_BACK"):
                tx.apply()
        self.assertFalse(self.snippet.exists())
        self.assertEqual(self.backend.read_bytes(),self.before_bytes)

    def test_symlink_snippet_and_unknown_root_layout_hold(self):
        target=self.root/"other"
        target.write_text("keep")
        self.snippet.symlink_to(target)
        with self.assertRaisesRegex(tx.Hold,"EXISTING_XHTTP_SNIPPET_REFUSED"):
            tx.before()
        self.assertEqual(target.read_text(),"keep")
        self.snippet.unlink()
        self.backend.write_bytes(self.before_bytes.replace(
            b"    location / {\n",b"  location / {\n"
        ))
        with self.assertRaisesRegex(tx.Hold,"UNKNOWN_PANEL_LOCATION_LAYOUT"):
            tx.before()

    def test_never_edits_wss_8444_or_signed_node(self):
        contents=SOURCE.read_text()
        self.assertNotIn("docker compose up",contents)
        self.assertNotIn("nginx -s reload",contents)
        self.assertNotIn("127.0.0.1:8444 ssl;",contents)
        self.assertNotIn("proxy_pass http://127.0.0.1:7000",contents)
        self.assertNotIn("location = /45121/www",contents)
        self.assertIn("gate.audit(allow_missing_snippet=True)",contents)
        self.assertIn("gate.audit()",contents)


if __name__=="__main__":
    unittest.main(verbosity=2)
