"""Real HTTP/Unix-socket integration: no TCP, no real host, no active FRP.

The Fido2 authenticator is a deterministic in-memory test double here. Ed25519
Node/Root evidence, canonical intents, queue, durable sqlite, HTTP framing,
CSRF and one-use grants are real. Dedicated Fido2 cryptographic tests remain
a separate required acceptance gate for actual browser/Passkey hardware.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

ROOT=Path(__file__).resolve().parents[1]/"modules"
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

service=load("real_uds_approval","smite-stage15-web-service.py")
gate=load("real_uds_gate","smite-stage15-web-approval.py")
queue=load("real_uds_queue","smite-stage15-approval-queue.py")
contract=load("real_uds_contract","smite-rc5-xhttp-signed-intent.py")
ev=load("real_uds_evidence","smite-stage15-approval-evidence.py")

class FakeWebAuthn:
    def authenticate_begin(self,keys,user_verification):
        assert user_verification=="required"
        class Options:
            def to_json(self):
                return '{"publicKey":{"challenge":"ZmFrZWNob2xsZW5nZQ","allowCredentials":[]}}'
        return Options(),{"challenge":"test-challenge","user_verification":"required"}
    def authenticate_complete(self,state,keys,assertion):
        if state.get("challenge")!="test-challenge" or assertion.get("proof")!="VALID_PASSKEY_UV":
            raise ValueError("invalid Passkey")
        class Verified:
            credential_id=b"isolated-test-credential"
        return Verified()

class MockCredentialStore:
    def encoded(self):return ["A"*64]
    def check_and_advance(self,credential,assertion):
        if len(credential)!=64 or assertion.get("proof")!="VALID_PASSKEY_UV":
            raise ValueError("invalid credential counter")

class LiveUDSTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        self.q=root/"pending";self.q.mkdir(mode=0o700)
        self.key=b"k"*32
        self.now=int(time.time())
        self.ir=Ed25519PrivateKey.generate()
        self.kh=Ed25519PrivateKey.generate()
        self.lease_key=Ed25519PrivateKey.generate()
        self.binding=dict(ir_node="node-ir-0001",kh_node="node-kh-0001",
           owner="owner-0001",child="child-0001",lease="child-0001",
           port=38658,path="/38658/shop",owner_proof_sha256="",
           kh_inventory_sha256="")
        self.owner={"tunnel_id":"owner-0001","control_port":7000,"proxy_port":38658}
        self.inbound={"port":38658,"listen":"127.0.0.1","protocol":"vless",
          "network":"xhttp","path":"/38658/shop","enabled":True}
        self.binding["owner_proof_sha256"]=ev.sha256(self.owner)
        self.binding["kh_inventory_sha256"]=ev.sha256(self.inbound)
        self.lease={"ir_node":"node-ir-0001","kh_node":"node-kh-0001",
           "owner":"owner-0001","child":"child-0001","lease":"child-0001",
           "port":38658,"role":"shared","state":"active","unique":True,
           "owner_count":1,"proxy_port_count":1}
        body={**self.binding,"schema":1,"audience":contract.AUDIENCE,
              "action":"create","issued_at":self.now,
              "expires_at":self.now+30,"nonce":"a"*32}
        wire=contract.canonical({**body,"mac":hmac.new(self.key,contract.canonical(body),
                                                      hashlib.sha256).hexdigest()})
        self.digest=queue.stage(directory=self.q,wire=wire,key=self.key,
                                now=self.now,root_check=False)
        self.ledger=gate.ApprovalLedger(root/"audit.db",root_check=False)
        self.addCleanup(self.ledger.close)
        self.grants=[]
        fake_server=FakeWebAuthn()
        self.server_module=service.module("uopti_web_gate","smite-stage15-web-approval.py")
        p=patch.object(self.server_module,"_server",return_value=fake_server)
        p.start();self.addCleanup(p.stop)
        c=patch.object(self.server_module,"_credentials",return_value=[object()])
        c.start();self.addCleanup(c.stop)
        for name,value in (("_server",fake_server),("_credentials",[object()])):
            local=patch.object(gate,name,return_value=value)
            local.start();self.addCleanup(local.stop)
        self.fail_evidence=False
        def public(k):
            return k.public_key().public_bytes(
                serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.sign=lambda k,kind,node,facts,nonce: self._sign(k,kind,node,facts,nonce)
        app=service.IndependentApproval(
            queue_dir=self.q,broker_key=self.key,ledger=self.ledger,
            credential_store=MockCredentialStore(),origin="https://review.example.invalid",
            panel_origin="https://panel.example.invalid",
            evidence_provider=self.evidence,grant_writer=lambda b:self.grants.append(b),
            ir_public_key=public(self.ir),kh_public_key=public(self.kh),
            lease_public_key=public(self.lease_key),root_check=False)
        self.sock=str(root/"approval.sock")
        self.http=service.ApprovalUDSServer(self.sock,app)
        self.addCleanup(self.http.server_close)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.http.shutdown)
        self.client=httpx.Client(transport=httpx.HTTPTransport(uds=self.sock),
                  base_url="http://review.example.invalid",timeout=2)
        self.addCleanup(self.client.close)
        self.headers={"Origin":"https://review.example.invalid"}

    def _sign(self,key,kind,node,facts,nonce):
        body={"schema":1,"audience":ev.AUDIENCE,"kind":kind,"node":node,
              "issued_at":int(time.time()),"expires_at":int(time.time())+30,
              "nonce":nonce,"facts":facts}
        sig=key.sign(ev.canonical(body))
        return {**body,"signature":base64.urlsafe_b64encode(sig).rstrip(b"=").decode()}

    def evidence(self,binding):
        if self.fail_evidence:raise ValueError("LIVE_EVIDENCE_UNAVAILABLE")
        return {"ir_owner":self.sign(self.ir,"frps_owner",binding["ir_node"],self.owner,"1"*32),
                "kh_inbound":self.sign(self.kh,"xhttp_inbound",binding["kh_node"],self.inbound,"2"*32),
                "ir_lease":self.sign(self.lease_key,"active_lease",binding["ir_node"],self.lease,"3"*32)}

    def post(self,path,payload,headers=None):
        return self.client.post(path,json=payload,headers=self.headers if headers is None else headers)

    def start(self):
        return self.post("/api/challenge",{"child":"child-0001","digest":self.digest})

    def finish(self,challenge,proof="VALID_PASSKEY_UV"):
        return self.post("/api/complete",{"child":"child-0001",
            "digest":self.digest,"challenge_id":challenge,
            "assertion":{"proof":proof}})

    def test_end_to_end_http_uds_approval_grant_and_audit(self):
        review=self.client.get("/api/pending?child=child-0001")
        self.assertEqual(review.status_code,200)
        self.assertEqual(review.json()["binding"]["path"],"/38658/shop")
        page=self.client.get("/review?child=child-0001")
        self.assertEqual(page.status_code,200)
        self.assertIn("script-src 'nonce-",page.headers["content-security-policy"])
        self.assertIn("https://panel.example.invalid",page.text)
        started=self.start()
        self.assertEqual(started.status_code,200,started.text)
        done=self.finish(started.json()["challenge_id"])
        self.assertEqual(done.status_code,200,done.text)
        self.assertEqual(done.json()["status"],"approved")
        self.assertEqual(self.grants,[self.binding])
        self.assertEqual(self.ledger.conn.execute("SELECT count(*) FROM approvals").fetchone()[0],1)
        self.assertEqual(self.finish(started.json()["challenge_id"]).status_code,409)
        self.assertEqual(self.start().status_code,409)

    def test_csrf_rejected_without_consuming_challenge(self):
        self.assertEqual(self.post("/api/challenge",{"child":"child-0001",
            "digest":self.digest},headers={}).status_code,409)
        self.assertEqual(self.post("/api/challenge",{"child":"child-0001",
            "digest":self.digest},headers={"Origin":"https://panel.example.invalid"}).status_code,409)
        self.assertEqual(self.post("/api/challenge",{"child":"child-0001",
            "digest":self.digest},headers={**self.headers,"Cookie":"smite=session"}).status_code,409)
        self.assertEqual(self.post("/api/challenge",{"child":"child-0001",
            "digest":self.digest},headers={**self.headers,"X-Forwarded-For":"1.2.3.4"}).status_code,409)
        self.assertEqual(self.start().status_code,200)

    def test_invalid_passkey_consumes_challenge_no_grant(self):
        c=self.start().json()["challenge_id"]
        self.assertEqual(self.finish(c,proof="FORGED_PANEL_SESSION").status_code,409)
        self.assertEqual(self.finish(c).status_code,409)
        self.assertEqual(self.grants,[])

    def test_unavailable_independent_evidence_holds_after_passkey(self):
        self.fail_evidence=True
        c=self.start().json()["challenge_id"]
        self.assertEqual(self.finish(c).status_code,409)
        self.assertEqual(self.grants,[])
        self.assertEqual(self.ledger.conn.execute("SELECT count(*) FROM approvals").fetchone()[0],0)

    def test_only_unix_socket_no_network_listener(self):
        import socket
        sock=self.http.socket
        self.assertEqual(sock.family,socket.AF_UNIX)
        self.assertTrue(Path(self.sock).is_socket())


if __name__=="__main__":
    unittest.main()
