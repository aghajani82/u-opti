#!/usr/bin/env python3
"""Offline tests for one-time RC2 IR XHTTP Nginx snippet bootstrap."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"modules/smite-frp-rc2-xhttp-bootstrap.py"
spec=importlib.util.spec_from_file_location("smite_rc2_snippet_bootstrap",SOURCE)
bootstrap=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class SnippetBootstrap(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(prefix="smite-rc2-snippet-")
        self.addCleanup(self.t.cleanup)
        self.path=Path(self.t.name)/"managed-xhttp.conf"
        x=patch.object(bootstrap,"SNIPPET",self.path)
        x.start();self.addCleanup(x.stop)
        a=patch.object(bootstrap,"safe_dir",return_value=None)
        a.start();self.addCleanup(a.stop)
        b=patch.object(bootstrap.gate,"audit",return_value=None)
        b.start();self.addCleanup(b.stop)
        c=patch.object(bootstrap.os,"geteuid",return_value=0)
        c.start();self.addCleanup(c.stop)
        d=patch.object(bootstrap.os,"uname",return_value=type("U",(),{"nodename":"ir"})())
        d.start();self.addCleanup(d.stop)
        e=patch.object(bootstrap,"nginx_test",return_value=None)
        e.start();self.addCleanup(e.stop)
        l=patch.object(bootstrap,"lock",side_effect=lambda:os.open(os.devnull,os.O_RDONLY))
        l.start();self.addCleanup(l.stop)

    def test_explicit_plan_never_creates_snippet(self):
        bootstrap.before()
        self.assertFalse(self.path.exists())

    def test_one_time_create_exact_header_and_mode(self):
        bootstrap.apply()
        self.assertEqual(self.path.read_bytes(),bootstrap.HEADER)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o644)
        with self.assertRaisesRegex(bootstrap.Hold,"EXISTING_XHTTP_SNIPPET"):
            bootstrap.apply()

    def test_nginx_test_failure_rolls_back_own_new_file(self):
        with patch.object(bootstrap,"nginx_test",side_effect=bootstrap.Hold("NGINX_SYNTAX_CHECK_FAILED")):
            with self.assertRaisesRegex(bootstrap.Hold,"XHTTP_BOOTSTRAP_FAILED_ROLLED_BACK"):
                bootstrap.apply()
        self.assertFalse(self.path.exists())

    def test_signed_gate_failure_does_not_create_snippet(self):
        with patch.object(bootstrap.gate,"audit",
                          side_effect=bootstrap.gate.GateHold("SIGNED_WSS_NODE_DRIFT")):
            with self.assertRaisesRegex(bootstrap.gate.GateHold,"SIGNED_WSS_NODE_DRIFT"):
                bootstrap.apply()
        self.assertFalse(self.path.exists())

    def test_symlink_refuses_and_does_not_change_target(self):
        target=Path(self.t.name)/"elsewhere"
        target.write_text("keep")
        self.path.symlink_to(target)
        with self.assertRaisesRegex(bootstrap.Hold,"EXISTING_XHTTP_SNIPPET"):
            bootstrap.before()
        self.assertEqual(target.read_text(),"keep")

    def test_never_publishes_route_or_reloads_nginx(self):
        s=SOURCE.read_text()
        self.assertNotIn("systemctl reload",s)
        self.assertNotIn("nginx -s reload",s)
        self.assertNotIn("docker compose up",s)
        self.assertNotIn("proxy_pass http://127.0.0.1:45121",s)
        self.assertIn('os.O_EXCL|os.O_NOFOLLOW',s)
        self.assertIn("gate.audit(allow_missing_snippet=True)",s)
        self.assertIn("gate.audit()",s)


if __name__=="__main__":
    unittest.main(verbosity=2)
