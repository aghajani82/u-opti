"""Disposable FIDO2 HTTPS lab: mocked hardware + local-only HTTP contract.

Does NOT contact real authenticators, IR, KH, Grandoptical, Broker or Nginx.
Real browser, TLS certificate trust and physical key independence NOT tested.
"""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/"tests/labs/stage15-passkey-https-lab.py"
SPEC=importlib.util.spec_from_file_location("disposable_passkey_browser_lab",FILE)
lab=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


class FakeFido2:
    def __init__(self):
        self.count=0
    def register_begin(self,user,credentials,user_verification):
        assert user_verification=="required"
        class Options:
            def to_json(self):
                return '{"publicKey":{"challenge":"Ym9ndXMtY2hhbGxlbmdl"}}'
        return Options(),{"challenge":"registration"}
    def register_complete(self,state,response):
        assert state["challenge"]=="registration"
        if response.get("proof")!="UV":
            raise ValueError("invalid user verification")
        self.count+=1
        class AuthData:
            def is_user_verified(self):return True
        a=AuthData()
        a.credential_data=type("Credential",(),{
            "credential_id":f"lab-credential-{self.count}".encode("ascii")
        })()
        return a
    def authenticate_begin(self,credentials,user_verification):
        assert user_verification=="required"
        class Options:
            def to_json(self):
                return '{"publicKey":{"challenge":"YXV0aA"}}'
        return Options(),{"challenge":"login"}
    def authenticate_complete(self,state,credentials,response):
        assert state["challenge"]=="login"
        if response.get("proof")!="SIGNED_UV":
            raise ValueError("invalid signed assertion")
        return credentials[-1]


class LabTests(unittest.TestCase):
    def setUp(self):
        self.lab=lab.LabState()
        self.lab.server=FakeFido2()

    def test_real_fido2_mock_register_two_and_verify_no_grant(self):
        for _ in range(2):
            p=self.lab.start("register")
            with self.assertRaisesRegex(lab.LabHold,"FIDO2_VERIFICATION_REJECTED"):
                self.lab.complete("register",p["ceremony"],{"proof":"INVALID"})
            with self.assertRaisesRegex(lab.LabHold,"EXPIRED_OR_SPENT_CEREMONY"):
                self.lab.complete("register",p["ceremony"],{"proof":"UV"})
            p=self.lab.start("register")
            done=self.lab.complete("register",p["ceremony"],{"proof":"UV"})
            self.assertEqual(done["status"],"LAB_REGISTERED")
        self.assertEqual(self.lab.status()["registered_credentials"],2)
        self.assertEqual(self.lab.status()["grant_writer"],"ABSENT")
        with self.assertRaisesRegex(lab.LabHold,"MAXIMUM_TWO_LAB_CREDENTIALS"):
            self.lab.start("register")
        a=self.lab.start("authenticate")
        done=self.lab.complete("authenticate",a["ceremony"],{"proof":"SIGNED_UV"})
        self.assertEqual(done["status"],"LAB_AUTHENTICATED_NO_GRANT")
        self.assertEqual(self.lab.status()["verified_sign_ins"],1)

    def test_previous_challenge_is_invalidated_by_new_one(self):
        a=self.lab.start("register")
        b=self.lab.start("register")
        with self.assertRaisesRegex(lab.LabHold,"EXPIRED_OR_SPENT_CEREMONY"):
            self.lab.complete("register",a["ceremony"],{"proof":"UV"})
        self.assertEqual(self.lab.complete("register",b["ceremony"],
                          {"proof":"UV"})["status"],"LAB_REGISTERED")

    def test_expired_challenge_is_single_use(self):
        p=self.lab.start("register")
        kind,state,_=self.lab.pending[p["ceremony"]]
        self.lab.pending[p["ceremony"]]=(kind,state,time.monotonic()-5)
        with self.assertRaisesRegex(lab.LabHold,"EXPIRED_OR_SPENT_CEREMONY"):
            self.lab.complete("register",p["ceremony"],{"proof":"UV"})
        self.assertEqual(self.lab.status()["registered_credentials"],0)

    def test_no_lab_sign_in_before_registration(self):
        with self.assertRaisesRegex(lab.LabHold,"NO_LAB_CREDENTIAL"):
            self.lab.start("authenticate")

    def test_production_hostname_and_tls_paths_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert=Path(tmp)/"lab.crt";cert.write_text("lab-cert")
            key=Path(tmp)/"lab.key";key.write_text("lab-key")
            for name in ("ir","kh","grandoptical","smite-node"):
                with self.subTest(name=name),self.assertRaises(lab.LabHold):
                    lab.check_lab_host(hostname=name,
                        confirm="I_CONFIRM_DISPOSABLE_OFFLINE_LAB",
                        cert=cert,key=key)
            with self.assertRaises(lab.LabHold):
                lab.check_lab_host(hostname="lab-vm",confirm="",
                    cert=cert,key=key)
            lab.check_lab_host(hostname="disposable-lab",
                confirm="I_CONFIRM_DISPOSABLE_OFFLINE_LAB",
                cert=cert,key=key)

    def request(self,connection,method,path,body=None,headers=None):
        hdr={"Host":"passkey-lab.test",**(headers or {})}
        if body is not None:
            data=json.dumps(body).encode()
            hdr.setdefault("Content-Type","application/json")
        else:
            data=None
        connection.request(method,path,data,hdr)
        response=connection.getresponse()
        raw=response.read()
        return response.status,raw,response.getheaders()

    def test_http_is_loopback_only_rejects_bad_origin_and_proxy_headers(self):
        # CI HTTP is deliberately on an ephemeral 127.0.0.1 port, WITHOUT
        # browser TLS, so no claim about physical HTTPS WebAuthn is made.
        server=lab.ThreadingHTTPServer(("127.0.0.1",0),lab.LabHandler)
        server.state=self.lab
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        self.addCleanup(worker.join,2)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=2)
        self.addCleanup(conn.close)
        status,raw,_=self.request(conn,"GET","/api/status")
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)["grant_writer"],"ABSENT")
        headers={"Origin":"https://passkey-lab.test",
                 "X-Lab-CSRF":self.lab.csrf}
        for tweak in (
            {"Origin":"https://approve.kolbe1.ir"},
            {"Origin":"http://passkey-lab.test"},
            {"X-Lab-CSRF":"bad"},
            {"Cookie":"session=forged"},
            {"X-Forwarded-Host":"passkey-lab.test"},
            {"Host":"127.0.0.1"},
        ):
            code,_,_=self.request(conn,"POST","/api/register/start",{},
                                 {**headers,**tweak})
            self.assertEqual(code,409)
        code,raw,_=self.request(conn,"POST","/api/register/start",{},headers)
        self.assertEqual(code,200,raw)
        chall=json.loads(raw)["ceremony"]
        code,raw,_=self.request(conn,"POST","/api/register/finish",
            {"ceremony":chall,"response":{"proof":"UV"}},headers)
        self.assertEqual(code,200,raw)
        code,_,_=self.request(conn,"POST","/api/register/finish",
            {"ceremony":chall,"response":{"proof":"UV"}},headers)
        self.assertEqual(code,409)
        code,raw,_=self.request(conn,"GET","/")
        self.assertEqual(code,200)
        self.assertIn(b"NO LIVE GRANTS",raw)
        code,raw,_=self.request(conn,"GET","/lab.js")
        self.assertEqual(code,200)
        self.assertIn(b"navigator.credentials.create",raw)

    def test_unconditional_no_live_dependencies_in_lab_script(self):
        raw=FILE.read_text()
        for token in ("install_grant(", "docker restart","nginx -s reload",
                      "subprocess.","requests.","httpx.","sqlite3.",
                      "smite-panel",):
            # smite-panel is permitted only in an explicit deny list.
            if token=="smite-panel":
                self.assertIn('"smite-panel"',raw)
            else:
                self.assertNotIn(token,raw)
        self.assertIn('("127.0.0.1",PORT)',raw)
        self.assertNotIn('("0.0.0.0",PORT)',raw)


if __name__=="__main__":
    unittest.main()
