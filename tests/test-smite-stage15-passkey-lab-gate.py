"""Offline only. No browser/hardware, DNS, TLS, network, FRP or live writes."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
NAME=ROOT/"modules/smite-stage15-passkey-lab-gate.py"
SPEC=importlib.util.spec_from_file_location("isolated_passkey_lab_gate",NAME)
lab=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=lab
SPEC.loader.exec_module(lab)

class PhysicalLabBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=ROOT/"docs/examples/stage15-passkey-browser-lab.json"
        self.doc=json.loads(self.fixture.read_text(encoding="utf-8"))

    def test_documented_manifest_matches_exact_fail_closed_contract(self):
        result=lab.check_file(self.fixture)
        self.assertEqual(result["isolation_contract"],"PASS_STATIC_ONLY")
        self.assertEqual(result["approval_or_grant"],"DISABLED")
        self.assertEqual(result["publish_fourth_route"],"DENIED")
        self.assertEqual(result["physical_primary_passkey"],"NOT_TESTED")
        self.assertEqual(result["physical_backup_passkey"],"NOT_TESTED")
        self.assertEqual(result["independent_hardware"],"NOT_VERIFIED")
        self.assertEqual(result["real_tls_and_dns"],"NOT_VERIFIED")
        self.assertEqual(result["live_ir_kh_changes"],"FORBIDDEN")
        self.assertNotIn("approved",result.values())

    def test_any_production_authority_or_connectivity_intent_holds(self):
        bad={
          "host_boundary":["ir","kh","grandoptical","production"],
          "approval_origin":["https://approve.kolbe1.ir","http://passkey-lab.test",
                             "https://passkey-lab.test:8443",
                             "https://panel-lab.test","https://passkey-lab.test/"],
          "panel_origin":["https://01ir.kolbe1.ir","https://passkey-lab.test"],
          "test_only_host_resolution":["1.2.3.4","::1","auto"],
          "bind_address":["0.0.0.0","::","192.168.1.3"],
          "https_port":[80,443.0,8443],
          "tls":["self-signed-untrusted","production-le-cert"],
          "approval_socket":["/run/u-opti-smite-review/web-approval.sock"],
          "credential_store":["/var/lib/u-opti/smite-web-approval/credentials.db"],
          "source":["production-node-image"],
          "broker":["enabled","read-only"],
          "grant_writer":["enabled","mock-after-live"],
          "signed_ir_kh":["real-live-pairing","node-live"],
          "real_ir_kh_connectivity":["allowed","read-only"],
          "frp_owner":["restart","reapply"],
          "production_dns":["yes"],
          "production_nginx":["yes"],
          "production_keys":["yes"],
          "production_database":["yes","copy-from-live"],
          "web_approval_marker":["enabled","present"],
          "route_publication":["enabled","test-grant"],
          "physical_passkeys_verified":[True],
          "hardware_independence_verified":[True],
          "field_trial_authorized":[True],
        }
        for field,changes in bad.items():
            for change in changes:
                with self.subTest(field=field,change=change):
                    doc={**self.doc,field:change}
                    with self.assertRaises(lab.LabHold):
                        lab.validate(doc)

    def test_silent_unknown_keys_missing_keys_and_bool_int_confusion_hold(self):
        for change in (
            {**self.doc,"extra":"run-approval"},
            {k:v for k,v in self.doc.items() if k!="broker"},
            {**self.doc,"schema":True},
            {**self.doc,"schema":"1"},
            {**self.doc,"https_port":True},
            {**self.doc,"physical_passkeys_verified":0},
            [],
            None,
        ):
            with self.subTest(candidate=repr(change)[:80]):
                with self.assertRaises(lab.LabHold):
                    lab.validate(change)

    def test_unknown_or_garbled_file_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"lab.json"
            with self.assertRaises(lab.LabHold):
                lab.check_file(path)
            for data in ("{", "{}", "x"*8193):
                path.write_text(data)
                with self.assertRaises(lab.LabHold):
                    lab.check_file(path)

    def test_lab_tool_is_pure_and_not_a_live_launcher(self):
        s=NAME.read_text(encoding="utf-8")
        for forbidden in (
            "import subprocess", "import socket", "import httpx",
            "import requests", "import sqlite3", "from cryptography",
            "docker restart","docker compose","systemctl",
            "install_grant(", "socketserver", "serve_forever",
            "certbot", "nginx -s reload", "os.system(",
        ):
            self.assertNotIn(forbidden,s)
        self.assertIn("OFFLINE_LIBRARY_ONLY_NO_BROWSER_OR_LIVE_ACTIVATION",s)

if __name__=="__main__":
    unittest.main()
