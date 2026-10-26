#!/usr/bin/env python3
"""Offline fail-closed RC2 one-path XHTTP publishing transaction tests."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"modules/smite-frp-rc2-xhttp-publish-45121.py"
spec=importlib.util.spec_from_file_location("rc2_45121_publish",SRC)
tx=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)


class Publish45121Contract(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="uopti-rc2-publish-")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.snippet=self.root/"managed.conf"
        self.snippet.write_bytes(tx.HEADER)
        self.snippet.chmod(0o644)
        self.root_tx=self.root/"journal"
        self.raw=(
            tx.HEADER+
            b"\n    location = /45121/www {\n"
            b"        proxy_pass http://127.0.0.1:45121;\n"
            b"    }\n"
            b"\n    location ^~ /45121/www/ {\n"
            b"        proxy_pass http://127.0.0.1:45121;\n"
            b"    }\n"
        )
        values=[
            ("SNIP",self.snippet),
            ("TXROOT",self.root_tx),
            ("TX",self.root_tx/"ir-45121"),
            ("BACKUP",self.root_tx/"ir-45121"/"snippet.before.conf"),
            ("JOURNAL",self.root_tx/"ir-45121"/"record.json"),
        ]
        for name,value in values:
            control=patch.object(tx,name,value)
            control.start();self.addCleanup(control.stop)
        mockers=[
            patch.object(tx,"safe_dir",return_value=None),
            patch.object(tx,"safe_read",
                         side_effect=lambda p,limit,mode=None:Path(p).read_bytes()),
            patch.object(tx,"acquire_lock",
                         side_effect=lambda:os.open(os.devnull,os.O_RDONLY)),
            patch.object(tx,"preflight",return_value=self.raw),
            patch.object(tx,"check_gate",return_value=None),
            patch.object(tx,"nginx_test",return_value=None),
            patch.object(tx,"nginx_reload",return_value=None),
            patch.object(tx,"panel_check",return_value=None),
            patch.object(tx,"host_and_pins",return_value=None),
            patch.object(tx,"timer_inactive",return_value=None),
        ]
        for control in mockers:
            control.start();self.addCleanup(control.stop)

    def test_plan_uses_preflight_but_makes_no_changes(self):
        self.assertEqual(tx.preflight(),self.raw)
        self.assertEqual(self.snippet.read_bytes(),tx.HEADER)
        self.assertFalse(self.root_tx.exists())

    def test_publishes_exact_two_locations_with_private_backup(self):
        tx.apply()
        self.assertEqual(self.snippet.read_bytes(),self.raw)
        self.assertEqual(stat.S_IMODE(self.snippet.stat().st_mode),0o644)
        self.assertEqual(stat.S_IMODE(tx.BACKUP.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(tx.JOURNAL.stat().st_mode),0o600)
        self.assertEqual(tx.record()["state"],"COMMITTED")
        tx.verify()

    def test_second_attempt_refuses_existing_journal(self):
        tx.apply()
        with self.assertRaisesRegex(tx.Hold,"EXISTING_PUBLISH_TRANSACTION"):
            tx.create_record(self.raw)

    def test_explicit_rollback_restores_header_only(self):
        tx.apply()
        tx.rollback()
        self.assertEqual(self.snippet.read_bytes(),tx.HEADER)
        self.assertEqual(tx.record()["state"],"ROLLED_BACK")

    def test_nginx_reload_failure_auto_restores_snippet(self):
        with patch.object(tx,"nginx_reload",
                          side_effect=[tx.Hold("SUBPROCESS_FAILED"),None]):
            with self.assertRaisesRegex(tx.Hold,
                                        "ROUTE_PUBLISH_FAILED_ROLLED_BACK"):
                tx.apply()
        self.assertEqual(self.snippet.read_bytes(),tx.HEADER)
        self.assertEqual(tx.record()["state"],"ROLLED_BACK")

    def test_panel_health_failure_auto_restores_snippet(self):
        with patch.object(tx,"panel_check",
                          side_effect=[tx.Hold("PANEL_HTTPS_NOT_HEALTHY"),None]):
            with self.assertRaisesRegex(tx.Hold,
                                        "ROUTE_PUBLISH_FAILED_ROLLED_BACK"):
                tx.apply()
        self.assertEqual(self.snippet.read_bytes(),tx.HEADER)

    def test_unknown_external_edit_refuses_rollback(self):
        tx.apply()
        self.snippet.write_bytes(b"# external edit, not ours\n")
        with self.assertRaisesRegex(tx.Hold,"CRITICAL_EXTERNAL_SNIPPET_CHANGE"):
            tx.rollback()
        self.assertEqual(self.snippet.read_bytes(),b"# external edit, not ours\n")

    def test_busy_lock_refuses_without_any_mutation(self):
        with patch.object(tx,"acquire_lock",
                          side_effect=tx.Hold("ENGINE_LOCK_BUSY")):
            with self.assertRaisesRegex(tx.Hold,"ENGINE_LOCK_BUSY"):
                tx.apply()
        self.assertFalse(self.root_tx.exists())
        self.assertEqual(self.snippet.read_bytes(),tx.HEADER)

    def test_bad_location_or_upstream_refuses(self):
        for changed in (
            self.raw.replace(b"/45121/www/",b"/45121/web/"),
            self.raw.replace(b"127.0.0.1:45121",b"0.0.0.0:45121"),
            self.raw+b"\nlocation = /fake {}\n",
        ):
            with self.subTest(change=tx.sha(changed)):
                with self.assertRaises(tx.Hold):
                    tx.validate_rendered(changed)

    def test_apply_keeps_other_services_and_timer_untouched(self):
        contents=SRC.read_text()
        self.assertNotIn("systemctl enable",contents)
        self.assertNotIn("docker compose up",contents)
        self.assertNotIn("docker compose down",contents)
        self.assertNotIn("nginx -s reload",contents)
        self.assertIn("PUBLISH-IR-XHTTP-45121",contents)
        self.assertIn("ENGINE_LOCK_BUSY",contents)


if __name__=="__main__":
    unittest.main(verbosity=2)
