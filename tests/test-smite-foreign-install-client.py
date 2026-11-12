import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor

spec=importlib.util.spec_from_file_location('install_client',Path(__file__).resolve().parents[1]/'modules/smite-foreign-install-client.py')
c=importlib.util.module_from_spec(spec);sys.modules[spec.name]=c;spec.loader.exec_module(c)

class Client(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.root.chmod(0o700)
        self.live=self.root/'live.json';self.now=1850000000
        self.data=dict(protocol='smi1',panel_url='https://panel.example.com',node_id='foreign-node-1234',node_name='node-kh',
            origin='https://kh.example.com:443',control_url='https://kh.example.com:443/smite-node/'+'a'*32,
            installation_code='smi1_'+'b'*43,expires_at=self.now+7200)
        self.keys=[];self.calls=[]
    def network(self,panel,target,body,headers):
        self.calls.append(target)
        record=json.loads((self.root/'foreign-install-identity.json').read_text())
        self.assertEqual((self.root/'foreign-install-identity.json').stat().st_mode & 0o777,0o600)
        request=json.loads(body)
        if target==c.REDEEM:
            self.assertEqual(request['node_secret'],record['node_secret']);self.keys.append(request['node_secret'])
            return {'status':'enrolled','node_id':self.data['node_id']}
        self.assertNotIn(record['node_secret'].encode(),body)
        self.assertNotIn(self.data['installation_code'].encode(),body)
        signature=headers['X-Smite-Signature']
        message='\n'.join(('smite-node-hmac-v1',self.data['node_id'],'POST',c.STATUS,headers['X-Smite-Timestamp'],headers['X-Smite-Nonce'],c.hashlib.sha256(body).hexdigest())).encode()
        self.assertEqual(signature,c.hmac.new(record['node_secret'].encode(),message,'sha256').hexdigest())
        return {'status':'enrolled',**{k:self.data[k] for k in ('node_id','node_name','origin','control_url')}}
    def run_client(self,**kw):
        args=dict(directory=self.root,live_identity=self.live,transport=self.network,now=self.now);args.update(kw)
        return c.enroll(json.dumps(self.data),**args)
    def test_stage_before_request_and_retry_same_key(self):
        self.run_client();self.run_client();self.assertEqual(len(set(self.keys)),1)
        raw=(self.root/'foreign-install-identity.json').read_text()
        self.assertNotIn(self.data['installation_code'],raw)
        self.assertNotIn(self.data['installation_code'],repr(c.parse_packet(json.dumps(self.data))))
    def test_lost_reply_proved_with_same_secret(self):
        def transport(*args):
            result=self.network(*args)
            if args[1]==c.REDEEM: raise TimeoutError()
            return result
        self.assertEqual(self.run_client(transport=transport)['status'],'enrolled')
    def test_expired_existing_uses_signed_proof_only(self):
        self.run_client();self.calls.clear()
        self.run_client(now=self.data['expires_at']+100)
        self.assertEqual(self.calls,[c.STATUS])
    def test_expired_fresh_does_not_create_identity_or_send(self):
        with self.assertRaises(c.Hold):self.run_client(now=self.data['expires_at'])
        self.assertFalse((self.root/'foreign-install-identity.json').exists());self.assertFalse(self.calls)
    def test_reissued_code_retains_key(self):
        self.run_client();self.data['installation_code']='smi1_'+'c'*43;self.run_client()
        self.assertEqual(len(set(self.keys)),1)
    def test_scope_change_does_not_rekey(self):
        self.run_client();before=(self.root/'foreign-install-identity.json').read_bytes()
        for key,value in [('node_id','foreign-other-1234'),('node_name','other'),('panel_url','https://other.example.com')]:
            old=self.data[key];self.data[key]=value
            with self.assertRaises(c.Hold):self.run_client()
            self.data[key]=old
        self.assertEqual(before,(self.root/'foreign-install-identity.json').read_bytes())
    def test_live_identity_refused(self):
        self.live.write_text('existing')
        with self.assertRaises(c.Hold):self.run_client()
        self.assertEqual(self.live.read_text(),'existing');self.assertFalse(self.calls)
    def test_symlink_and_hardlink_refused(self):
        path=self.root/'foreign-install-identity.json';other=self.root/'other';other.write_text('{}');other.chmod(0o600)
        path.symlink_to(other)
        with self.assertRaises(c.Hold):self.run_client()
        path.unlink();os.link(other,path)
        with self.assertRaises(c.Hold):self.run_client()
        self.assertFalse(self.calls)
    def test_corrupt_record_never_replaced(self):
        path=self.root/'foreign-install-identity.json';path.write_text('{');path.chmod(0o600)
        with self.assertRaises(c.Hold):self.run_client()
        self.assertEqual(path.read_text(),'{')
    def test_fsync_failure_never_sends(self):
        with patch.object(c.os,'fsync',side_effect=OSError('fixture')):
            with self.assertRaises(c.Hold):self.run_client()
        self.assertFalse(self.calls)
    def test_parallel_installations_preserve_one_key(self):
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:self.run_client(),range(2)))
        self.assertEqual(len(set(self.keys)),1)
    def test_bad_packets(self):
        for key,value in [('panel_url','http://panel.example.com'),('panel_url','https://127.0.0.1'),
            ('panel_url','https://panel.example.com/'),('expires_at',True),('node_id','bad'),
            ('control_url',self.data['control_url']+'?x=1'),('protocol','wrong')]:
            packet={**self.data,key:value}
            with self.assertRaises(c.Hold):c.parse_packet(json.dumps(packet))
        with self.assertRaises(c.Hold):c.parse_packet(json.dumps(self.data)[:-1]+',"protocol":"smi1"}')
    def test_private_dns_rejected(self):
        with patch.object(c.socket,'getaddrinfo',return_value=[(c.socket.AF_INET,c.socket.SOCK_STREAM,c.socket.IPPROTO_TCP,'',('127.0.0.1',443))]),patch.object(c.socket,'create_connection') as dial:
            with self.assertRaises(c.Hold):c.post(self.data['panel_url'],c.STATUS,b'{}',{})
            dial.assert_not_called()
    def test_tls_uses_pinned_ip_and_original_verified_hostname_without_redirect(self):
        seen=[]
        sock=MagicMock()
        def wrap(context, raw, server_hostname):
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode,c.ssl.CERT_REQUIRED)
            self.assertEqual(server_hostname,'panel.example.com')
            return sock
        def send(connection,method,target,body,headers):
            connection.connect();seen.append((connection.host,method,target))
        response=MagicMock();response.status=200;response.read.return_value=b'{}'
        with patch.object(c.socket,'getaddrinfo',return_value=[(c.socket.AF_INET,c.socket.SOCK_STREAM,c.socket.IPPROTO_TCP,'',('8.8.8.8',443))]), \
             patch.object(c.socket,'create_connection',return_value=sock) as dial, \
             patch.object(c.ssl.SSLContext,'wrap_socket',wrap), \
             patch.object(c.http.client.HTTPSConnection,'request',send), \
             patch.object(c.http.client.HTTPSConnection,'getresponse',return_value=response):
            self.assertEqual(c.post(self.data['panel_url'],c.STATUS,b'{}',{}),{})
            dial.assert_called_with(('8.8.8.8',443),timeout=15)
            response.status=302
            with self.assertRaises(c.Hold):c.post(self.data['panel_url'],c.STATUS,b'{}',{})
        self.assertEqual(len(seen),2)
        self.assertEqual(seen[0],('panel.example.com','POST',c.STATUS))

    def test_failed_proof_retains_secret_and_never_returns_success(self):
        def bad(*args):
            result=self.network(*args)
            if args[1]==c.STATUS:result['node_name']='other'
            return result
        with self.assertRaises(c.Hold):self.run_client(transport=bad)
        self.run_client();self.assertEqual(len(set(self.keys)),1)

if __name__=='__main__':unittest.main()
