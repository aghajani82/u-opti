#!/usr/bin/env python3
"""Offline tests for Signed RC2 wizard's dynamic FRP/XHTTP admission."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"modules/smite-frp-rc2-guided-publish.py"
spec=importlib.util.spec_from_file_location("rc2_guided",SOURCE)
gp=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)


def block(port,path):
    shared=(
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "        proxy_buffering off;\n"
        "        proxy_request_buffering off;\n"
        "        proxy_connect_timeout 10s;\n"
        "        proxy_read_timeout 3600s;\n"
        "        proxy_send_timeout 3600s;\n"
    )
    return (
        f"\n    location = {path} {{\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
        + shared+"    }\n"
        f"\n    location ^~ {path}/ {{\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
        + shared+"    }\n"
    )


class TestRC2GuidedPublisher(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp=Path(temp.name)
        self.snippet=self.tmp/"snippet.conf"
        self.txroot=self.tmp/"records"
        self.existing=block(45121,"/45121/www")
        self.next=block(45678,"/assets/v1/connect")
        self.before=(gp.HEADER+self.existing).encode()
        self.after=(gp.HEADER+self.existing+self.next).encode()
        self.snippet.write_bytes(self.before)
        self.snippet.chmod(0o644)
        self.patch("SNIPPET",self.snippet)
        self.patch("TX_ROOT",self.txroot)
        self.patch("host",lambda:None)
        self.patch("signed_gate",lambda:None)
        self.patch("timer_idle",lambda:None)
        self.patch("listener",lambda p:None)
        self.patch("nginx_test",lambda:None)
        self.patch("reload_nginx",lambda:None)
        self.patch("panel_health",lambda:None)
        self.patch("state_render",lambda:self.after)
        self.patch("lock_engine",lambda:os.open(os.devnull,os.O_RDONLY))
        self.patch("trusted_dir",lambda path,private=False:None)
        self.patch("trusted_read",
                   lambda path,maximum=131072,mode=None:Path(path).read_bytes())
        self.patch("BACKEND",self.tmp/"backend")
        gp.BACKEND.write_text(gp.INCLUDE)
        self.patch("REGISTRY",self.tmp/"registry")
        gp.REGISTRY.write_text(json.dumps({"45121":"/45121/www",
                                           "45678":"/assets/v1/connect"}))
        self.patch("execute",self.fake_execute)

    def patch(self,name,value):
        m=patch.object(gp,name,value)
        m.start();self.addCleanup(m.stop)

    def fake_execute(self,argv,timeout=30):
        if argv[0:3]==["python3","-B",str(gp.HELPER)]:
            return b""
        raise AssertionError("Unexpected subprocess "+repr(argv))

    def test_renderer_canonical_and_dynamic_multi_port(self):
        self.assertEqual(list(gp.parse_blocks(self.before)),[45121])
        got=gp.parse_blocks(self.after)
        self.assertEqual(list(got),[45121,45678])
        self.assertEqual(got[45678][0],"/assets/v1/connect")

    def test_preflight_preserves_existing_and_adds_only_selected_port(self):
        path,old,new,changed=gp.inspection(45678)
        self.assertEqual(path,"/assets/v1/connect")
        self.assertTrue(changed)
        self.assertEqual(old,self.before)
        self.assertEqual(new,self.after)
        self.assertFalse(self.txroot.exists())

    def test_first_published_port_status_is_idempotent(self):
        gp.state_render=lambda:self.before
        path,old,new,changed=gp.inspection(45121)
        self.assertFalse(changed)
        self.assertEqual(path,"/45121/www")

    def test_apply_records_private_backup_and_updates_only_new_route(self):
        gp.apply(45678)
        self.assertEqual(self.snippet.read_bytes(),self.after)
        self.assertEqual(stat.S_IMODE((self.txroot/"ir-45678"/"snippet.before.conf").stat().st_mode),0o600)
        self.assertEqual(gp.load_record(45678)[0]["state"],"COMMITTED")
        gp.verify(45678)

    def test_rollback_removes_only_new_port(self):
        gp.apply(45678)
        gp.rollback(45678)
        self.assertEqual(self.snippet.read_bytes(),self.before)
        self.assertEqual(gp.load_record(45678)[0]["state"],"ROLLED_BACK")

    def test_fail_reload_rolls_back_atomically(self):
        with patch.object(gp,"reload_nginx",
                          side_effect=[gp.Hold("COMMAND_FAILED"),None]):
            with self.assertRaisesRegex(gp.Hold,"PUBLISH_FAILED_ROLLED_BACK"):
                gp.apply(45678)
        self.assertEqual(self.snippet.read_bytes(),self.before)

    def test_external_drift_blocks_rollback(self):
        gp.apply(45678)
        self.snippet.write_bytes(b"# malicious or operator-edited config")
        with self.assertRaisesRegex(gp.Hold,"CRITICAL_SNIPPET_EXTERNAL_EDIT"):
            gp.rollback(45678)

    def test_extra_active_port_never_silently_published(self):
        self.patch("state_render",lambda:(
            gp.HEADER+self.existing+self.next+block(45679,"/45679/test")
        ).encode())
        with self.assertRaisesRegex(gp.Hold,"EXTRA_UNAPPROVED_PORTS"):
            gp.inspection(45678)

    def test_mismatch_or_untrusted_locations_rejected(self):
        for blob in (
            (gp.HEADER+self.existing.replace(
                "127.0.0.1:45121","0.0.0.0:45121")).encode(),
            (gp.HEADER+self.existing.replace(
                "proxy_read_timeout 3600s","proxy_read_timeout 42s")).encode(),
            (gp.HEADER+self.existing+"    location /foo { return 200; }\n").encode(),
            (gp.HEADER+self.existing.replace(
                "location ^~ /45121/www/","location ^~ /45121/web/")).encode(),
        ):
            with self.subTest(blob=gp.digest(blob)):
                with self.assertRaises(gp.Hold):
                    gp.parse_blocks(blob)

    def test_busy_lock_blocks_mutation(self):
        self.patch("lock_engine",lambda:(_ for _ in ()).throw(
            gp.Hold("ENGINE_LOCK_BUSY")))
        with self.assertRaisesRegex(gp.Hold,"ENGINE_LOCK_BUSY"):
            gp.apply(45678)
        self.assertEqual(self.snippet.read_bytes(),self.before)
        self.assertFalse(self.txroot.exists())

    def test_no_persistent_auto_timer_or_node_mutation(self):
        contents=SOURCE.read_text()
        self.assertNotIn("systemctl enable",contents)
        self.assertNotIn("docker compose up",contents)
        self.assertNotIn("docker compose down",contents)
        self.assertNotIn("systemctl restart",contents)
        self.assertIn("code=f",contents)
        self.assertIn("-IR-FRP-{port}",contents)
        self.assertIn("INTERACTIVE_TTY_REQUIRED",contents)
        self.assertIn("ENGINE_LOCK_BUSY",contents)


if __name__=="__main__":
    unittest.main(verbosity=2)
