"""Independent root approval, expiry and audit ordering on private temp files."""
import contextlib
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'modules'/file)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
r=load('root_review_test','smite-stage15-root-review.py')
b=load('root_review_broker_test','smite-rc5-xhttp-root-broker.py')
p=load('root_review_provision_test','smite-rc5-xhttp-broker-provision.py')
c=b._contract_module()

@unittest.skipUnless(os.geteuid()==0,'root-owned fixtures')
class ReviewTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.now=1001;self.grants=[]
        self.facts=dict(ir_node='ir-node-0001',kh_node='kh-node-0001',owner='owner-0001',child='owner-0001',lease='owner-0001',port=45121,path='/custom/connect',owner_proof_sha256='a'*64,kh_inventory_sha256='b'*64)
        body=dict(self.facts,schema=1,audience=c.AUDIENCE,action='create',issued_at=1000,expires_at=1030,nonce='c'*32)
        self.key=b'k'*32
        self.wire=c.canonical(dict(body,mac=hmac.new(self.key,c.canonical(body),hashlib.sha256).hexdigest()))
        self.request=self.root/'approval-request.json';self.request.write_bytes(self.wire);self.request.chmod(0o600)
        keypath=self.root/'key';keypath.write_bytes(self.key);keypath.chmod(0o600)
        patches=[patch.object(r,'load',side_effect=lambda name,file:b if 'broker' in name else p),
            patch.object(b,'KEY',keypath),patch.object(b,'LEDGER',self.root/'nonce.db'),
            patch.object(b,'_configuration',return_value={}),patch.object(b,'_verify_helper'),patch.object(b,'_verify_bridge'),
            patch.object(b,'_lock',side_effect=contextlib.nullcontext),
            patch.object(r.os,'uname',return_value=SimpleNamespace(nodename='ir')),
            patch.object(r.sys,'argv',['review']),patch.object(r.sys.stdin,'isatty',return_value=True),
            patch.object(r.time,'time',side_effect=lambda:self.now),
            patch.object(p,'install_grant',side_effect=self.install),patch('builtins.print')]
        for patcher in patches:patcher.start();self.addCleanup(patcher.stop)
    def install(self,facts,*,confirmed_child):
        audits=list(self.root.glob('approval-*.json'))
        self.assertTrue(any(a.name!='approval-request.json' for a in audits))
        self.grants.append((facts,confirmed_child))
    def approve(self):return 'APPROVE '+hashlib.sha256(self.wire).hexdigest()
    def test_exact_root_confirmation_audited_before_grant(self):
        with patch('builtins.input',return_value=self.approve()):r.review()
        self.assertEqual(self.grants,[(self.facts,self.facts['child'])]);self.assertFalse(self.request.exists())
    def test_cancel_cannot_create_grant(self):
        with patch('builtins.input',return_value='yes'),self.assertRaises(b.BrokerHold):r.review()
        self.assertEqual(self.grants,[]);self.assertEqual(list(self.root.glob('approval-*.json')),[self.request])
    def test_expiration_during_confirmation_cannot_create_grant(self):
        def answer(*args):self.now=1031;return self.approve()
        with patch('builtins.input',side_effect=answer),self.assertRaises(c.IntentHold):r.review()
        self.assertEqual(self.grants,[])
    def test_noninteractive_root_cannot_approve(self):
        with patch.object(r.sys.stdin,'isatty',return_value=False),self.assertRaises(b.BrokerHold):r.review()
        self.assertEqual(self.grants,[])
    def test_request_replacement_before_approval_rejected(self):
        def answer(*args):self.request.write_bytes(b'{}');return self.approve()
        with patch('builtins.input',side_effect=answer),self.assertRaises(b.BrokerHold):r.review()
        self.assertEqual(self.grants,[])
if __name__=='__main__':unittest.main()
