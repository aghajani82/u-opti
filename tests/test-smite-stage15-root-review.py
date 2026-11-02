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
REAL_INSTALL_GRANT=p.install_grant
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
    def approve(self):return '1'
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
    def test_wrong_host_nonroot_and_arguments_never_prompt(self):
        for guard in (patch.object(r.os,'uname',return_value=SimpleNamespace(nodename='kh')),
                      patch.object(r.os,'geteuid',return_value=1000),
                      patch.object(r.sys,'argv',['review','--approve'])):
            with guard,patch('builtins.input') as prompt,self.assertRaisesRegex(b.BrokerHold,'IR_ROOT_TTY_ONLY'):
                r.review()
            prompt.assert_not_called()
        self.assertEqual(self.grants,[])
    def test_request_permissions_changed_during_confirmation_hold(self):
        def answer(*args):self.request.chmod(0o644);return '1'
        with patch('builtins.input',side_effect=answer),self.assertRaises(b.BrokerHold):r.review()
        self.assertEqual(self.grants,[])
    def test_request_replacement_before_approval_rejected(self):
        def answer(*args):self.request.write_bytes(b'{}');return self.approve()
        with patch('builtins.input',side_effect=answer),self.assertRaises(b.BrokerHold):r.review()
        self.assertEqual(self.grants,[])
    def test_summary_displays_signed_identity_and_all_binding_fields(self):
        with patch('builtins.print') as output, patch('builtins.input',return_value='1'):
            r.review()
        lines='\n'.join(str(call.args[0]) for call in output.call_args_list)
        for value in ('Tunnel ID: owner-0001','IR node ID: ir-node-0001',
                      'KH node ID: kh-node-0001','Port: 45121','Path: /custom/connect',
                      'Tunnel name: unavailable', 'submit a fresh Panel request.'):
            self.assertIn(value,lines)
        for field in self.facts:
            self.assertIn('"'+field+'"',lines)
    def test_default_cancel_and_invalid_choices_have_no_side_effects(self):
        for answer in ('','0','yes','Approve','APPROVE '+hashlib.sha256(self.wire).hexdigest()):
            with self.subTest(answer=answer), patch('builtins.input',return_value=answer), self.assertRaises(b.BrokerHold):
                r.review()
            self.assertEqual(self.grants,[])
            self.assertEqual(self.request.read_bytes(),self.wire)
            self.assertEqual(list(self.root.glob('approval-*.json')),[self.request])
    def test_expired_or_forged_request_never_prompts(self):
        for expired in (True,False):
            self.now=1031 if expired else 1001
            self.request.write_bytes(self.wire if expired else self.wire.replace(b'/custom/connect',b'/custom/changed'))
            with patch('builtins.input') as prompt, self.assertRaises(c.IntentHold):
                r.review()
            prompt.assert_not_called()
        self.assertEqual(self.grants,[])
    def test_eof_cancels_without_audit_or_grant(self):
        with patch('builtins.input',side_effect=EOFError),self.assertRaises(EOFError):r.review()
        self.assertEqual(self.grants,[])
        self.assertEqual(list(self.root.glob('approval-*.json')),[self.request])
    def test_validly_signed_replacement_of_each_binding_is_rejected(self):
        for field in self.facts:
            self.request.write_bytes(self.wire)
            changed=json.loads(self.wire)
            changed[field]=(45122 if field=='port' else '/other/path' if field=='path'
                            else 'd'*64 if field.endswith('sha256') else 'changed-0001')
            changed.pop('mac')
            replacement=c.canonical(dict(changed,mac=hmac.new(self.key,c.canonical(changed),hashlib.sha256).hexdigest()))
            def answer(*args):self.request.write_bytes(replacement);return '1'
            with self.subTest(field=field),patch('builtins.input',side_effect=answer),self.assertRaisesRegex(b.BrokerHold,'PROPOSAL_CHANGED'):
                r.review()
            self.assertEqual(self.grants,[])
    def test_repeated_approved_proposal_cannot_issue_second_grant(self):
        with patch('builtins.input',return_value='1'):r.review()
        audit=self.root/('approval-'+hashlib.sha256(self.wire).hexdigest()+'.json')
        before=audit.read_bytes()
        self.request.write_bytes(self.wire);self.request.chmod(0o600)
        with patch('builtins.input',return_value='1'),self.assertRaises(p.ProvisionHold):r.review()
        self.assertEqual(len(self.grants),1)
        self.assertEqual(audit.read_bytes(),before)
    def test_existing_grants_never_overwritten_and_new_grant_is_private(self):
        grants=self.root/'grants';grants.mkdir(mode=0o700)
        old={}
        for child in ('existing-45121','existing-38658','existing-28897'):
            target=grants/(child+'.json');target.write_bytes(child.encode());target.chmod(0o600)
            old[target]=target.read_bytes()
        with patch.object(p,'install_grant',side_effect=REAL_INSTALL_GRANT),patch.object(p,'_grant_context',return_value=grants),patch('builtins.input',return_value='1'):
            r.review()
            target=grants/(self.facts['child']+'.json')
            granted=target.read_bytes()
            self.assertEqual(target.stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads(granted),dict(schema=1,**self.facts))
            # A different fresh intent for the same child must not overwrite its grant.
            changed=json.loads(self.wire);changed.pop('mac');changed['nonce']='d'*32
            self.request.write_bytes(c.canonical(dict(changed,mac=hmac.new(self.key,c.canonical(changed),hashlib.sha256).hexdigest())))
            self.request.chmod(0o600)
            with self.assertRaises(p.ProvisionHold):r.review()
            self.assertEqual(target.read_bytes(),granted)
        for target,data in old.items():
            self.assertEqual(target.read_bytes(),data)
            self.assertEqual(target.stat().st_mode & 0o777,0o600)
if __name__=='__main__':unittest.main()
