"""Real filesystem transactions, mocked host commands; no live hosts."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bridge_test', ROOT/'modules/smite-stage15-xhttp-bridge.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
real_effective = b.effective

@unittest.skipUnless(os.geteuid() == 0, 'root-owned fixtures')
class BridgeTests(unittest.TestCase):
    def patch(self, obj, key, value):
        p = patch.object(obj, key, value); p.start(); self.addCleanup(p.stop)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.patch(b, 'STATE', self.root/'bridge-state')
        self.patch(b, 'EDGE', self.root/'edge.json')
        self.patch(b.base, 'BACKEND', self.root/'backend')
        self.patch(b.base, 'BRIDGE', self.root/'bridge')
        self.patch(b.base, 'ROUTE_DIR', self.root/'routes')
        self.patch(b.base, 'TX_DIR', self.root/'legacy-journal')
        self.patch(b.base.admission, 'LEGACY', self.root/'legacy')
        b.base.ROUTE_DIR.mkdir(mode=0o755)
        self.old = b'# Managed by U-OPTI - Smite Panel TLS backend\nserver {\n    listen 127.0.0.1:8443 ssl;\n    server_name ir.example.net;\n    location / {\n        proxy_pass http://127.0.0.1:8000;\n    }\n}\n'
        b.base.BACKEND.write_bytes(self.old); b.base.BACKEND.chmod(0o644)
        self.edge = b.edge_module()
        self.patch(b, 'edge_module', lambda: self.edge)
        self.patch(self.edge, 'STATE', self.root)
        self.patch(self.edge, 'bridge_source', lambda raw, **kw: b.original_backend(raw, **kw) if b.STATE.exists() else raw)
        self.patch(self.edge.edge, 'TLS_SOURCE', b.base.BACKEND)
        for key in ('STREAM_SOURCE','FRP_MAP','ALT_CANDIDATE'):
            self.patch(self.edge.edge, key, self.root/key)
        self.edge.edge.DOMAIN = 'ir.example.net'
        e = self.edge.edge
        e.STREAM_SOURCE.write_bytes(b'stream')
        old_map = e.MAP_HEADER
        doc = dict(schema=1,state='COMMITTED',domain=e.DOMAIN,peer='8.8.8.8',backend=b.base.digest(self.old),stream=b.base.digest(b'stream'),old_map=old_map,new_map=e.render_map(old_map,'8.8.8.8'),alt=e.render_alt(self.old.decode()),mode=0o644)
        e.FRP_MAP.write_text(doc['new_map']); e.ALT_CANDIDATE.write_text(doc['alt'])
        raw = json.dumps(doc).encode()
        b.EDGE.write_bytes(raw); b.EDGE.chmod(0o600)
        (self.root/'record.json').write_bytes(raw); (self.root/'record.json').chmod(0o600)
        self.protected = [(p, p.read_bytes()) for p in (b.EDGE,e.FRP_MAP,e.ALT_CANDIDATE,e.STREAM_SOURCE)]
        self.patch(self.edge.wss,'read_record',lambda:dict(state='COMMITTED',roles=['panel','node'],domain=e.DOMAIN))
        self.patch(self.edge.wss,'health',lambda *a:None)
        self.patch(self.edge.host,'run',lambda *a:None)
        self.patch(b.base,'host_gate',lambda:None)
        self.patch(b.base.admission,'_timer_is_unsafe',lambda:False)
        self.calls = []
        for name in ('nginx_test','nginx_reload','probe_panel'):
            self.patch(b.base,name,lambda *a:self.calls.append(a))
        self.patch(b,'effective',lambda:None)

    def preserved(self):
        for p, raw in self.protected: self.assertEqual(p.read_bytes(),raw)

    def test_apply_verify_and_rollback_preserve_wss(self):
        b.apply(); b.verify(); self.edge.verify(self.edge.state())
        self.assertEqual(b.record()[0]['state'],'COMMITTED')
        self.assertEqual(b.base.BACKEND.read_bytes(),b.candidate(self.old))
        self.preserved(); b.restore(); self.preserved()
        self.assertEqual(b.base.BACKEND.read_bytes(),self.old)
        self.assertFalse(b.base.BRIDGE.exists())
        self.assertEqual(b.record()[0]['state'],'ROLLED_BACK')

    def test_partial_transaction_recovery(self):
        b.apply()
        doc,_,_ = b.record(); doc['state']='PREPARED'; b.save(doc)
        with self.assertRaises(b.base.Hold): b.verify()
        b.restore(); self.preserved()
        self.assertEqual(b.base.BACKEND.read_bytes(),self.old)

    def test_external_backend_drift_never_overwritten(self):
        b.apply(); b.base.BACKEND.write_bytes(b'external')
        with self.assertRaises(b.base.Hold): b.restore()
        self.assertEqual(b.base.BACKEND.read_bytes(),b'external')

    def test_populated_route_directory_blocks_bridge_rollback(self):
        b.apply(); (b.base.ROUTE_DIR/'45121.conf').write_text('owned route')
        with self.assertRaises(b.base.Hold): b.restore()
        self.assertEqual(b.record()[0]['state'],'COMMITTED')

    def test_wss_journal_drift_rejected(self):
        b.apply(); b.EDGE.write_bytes(b'{}')
        with self.assertRaises(b.base.Hold): b.verify()

    def test_symlink_journal_rejected(self):
        b.apply(); path=b.STATE/'journal.json'; raw=path.read_bytes(); path.unlink()
        target=self.root/'target'; target.write_bytes(raw); target.chmod(0o600); path.symlink_to(target)
        with self.assertRaises(b.base.Hold): b.verify()

    def test_reload_failure_rolls_back(self):
        count = 0
        def reload():
            nonlocal count
            count += 1
            if count == 1: raise RuntimeError('failure')
        self.patch(b.base,'nginx_reload',reload)
        with self.assertRaisesRegex(b.base.Hold,'FAILURE_ROLLED_BACK'): b.apply()
        self.assertEqual(b.base.BACKEND.read_bytes(),self.old); self.preserved()

    def test_no_duplicate_include(self):
        with self.assertRaises(b.base.Hold): b.candidate(b.candidate(self.old))


class RC7BridgeTests(BridgeTests):
    """Same transaction and adversarial tests against the real RC7 renderer."""
    def setUp(self):
        super().setUp()
        self.patch(b, 'EDGE', self.root/'absent-stage15'/'record.json')
        folder = self.root/'rc7-edge'; folder.mkdir(mode=0o700)
        self.patch(b, 'RC7_EDGE', folder/'record.json')
        self.edge = b.load('rc7_fixture_edge', 'smite-rc7-wss-edge.py')
        self.patch(b, 'edge_module', lambda: self.edge)
        e = self.edge
        self.patch(e, 'STATE', folder)
        self.patch(e, 'bridge_source', lambda raw: b.original_backend(raw, committed=True) if b.STATE.exists() else raw)
        self.patch(e.q, 'TLS_SOURCE', b.base.BACKEND)
        for key in ('STREAM_SOURCE', 'FRP_MAP', 'ALT_CANDIDATE'):
            self.patch(e.q, key, self.root/key)
        stream = ('# Managed by U-OPTI - Smite TCP/443 SNI gateway\n'
                  'map "$ssl_preread_server_name|$remote_addr" $uopti_frp_canary_backend {\n'
                  'include '+str(e.q.FRP_MAP)+';\n'
                  'default $uopti_smite_backend;\n}\n'
                  'server {\nlisten 443;\nssl_preread on;\n'
                  'proxy_pass $uopti_frp_canary_backend;\n}\n').encode()
        mapping = e.q.MAP_HEADER.encode()
        alt, new = e.render('ir.example.net', '8.8.8.8', before=self.old, stream=stream, mapping=mapping)
        doc = dict(schema=1, state='COMMITTED', domain='ir.example.net', peer='8.8.8.8',
                   tls_before=e.sha(self.old), stream=e.sha(stream), map_before=e.sha(mapping),
                   map_after=e.sha(new), alternate=e.sha(alt), map_mode=0o644)
        for path, raw, mode in ((b.RC7_EDGE, json.dumps(doc).encode(), 0o600),
                                (folder/'map.before', mapping, 0o600),
                                (e.q.STREAM_SOURCE, stream, 0o644),
                                (e.q.FRP_MAP, new, 0o644), (e.q.ALT_CANDIDATE, alt, 0o644)):
            path.write_bytes(raw); path.chmod(mode)
        self.protected = [(p, p.read_bytes()) for p in (b.RC7_EDGE, folder/'map.before', e.q.STREAM_SOURCE, e.q.FRP_MAP, e.q.ALT_CANDIDATE)]
        self.patch(e.p, 'state', lambda: dict(SMITE_ROLE='panel-iran', SMITE_MANAGED_VERSION='2.0.0-rc.7', SMITE_PANEL_DOMAIN='ir.example.net'))
        self.patch(e, 'expected_runtime', lambda *a: None)
        self.patch(e.p, 'run', lambda *a: '')
        self.patch(e.rt, 'panel_probe', lambda *a: None)
        self.patch(e, 'alternate_probe', lambda *a: None)

    def test_apply_verify_and_rollback_preserve_wss(self):
        b.plan(); b.apply(); b.verify(); self.edge.validate_committed(self.edge.journal())
        self.assertEqual(b.record()[0]['schema'], 2)
        self.preserved()
        with self.assertRaisesRegex(b.base.Hold, 'EXISTING_BRIDGE_JOURNAL'): b.apply()
        b.restore(); self.preserved(); self.edge.validate_committed(self.edge.journal())
        self.assertEqual(b.base.BACKEND.read_bytes(), self.old)

    def test_wss_journal_drift_rejected(self):
        b.apply(); b.RC7_EDGE.write_bytes(b'{}')
        with self.assertRaises(b.base.Hold): b.verify()

    def test_generation_ambiguity_and_partial_edge_fail_closed(self):
        b.EDGE.parent.mkdir(mode=0o700)
        with self.assertRaisesRegex(b.base.Hold, 'AMBIGUOUS_WSS_GENERATION'): b.plan()
        b.EDGE.parent.rmdir(); b.RC7_EDGE.unlink()
        with self.assertRaises(FileNotFoundError): b.plan()

    def test_wrong_host_role_and_uncommitted_edge(self):
        self.patch(self.edge.p, 'state', lambda: dict(SMITE_ROLE='foreign'))
        with self.assertRaisesRegex(b.base.Hold, 'IR_RC7_STATE_INVALID'): b.plan()

    def test_uncommitted_edge(self):
        doc = self.edge.journal(); doc['state'] = 'APPLYING'
        b.RC7_EDGE.write_text(json.dumps(doc))
        with self.assertRaisesRegex(b.base.Hold, 'WSS_EDGE_NOT_COMMITTED'): b.plan()

    def test_bridge_permission_and_generation_drift(self):
        b.apply(); b.STATE.chmod(0o777)
        with self.assertRaises(b.base.Hold): b.verify()
        b.STATE.chmod(0o700)
        doc, _, _ = b.record(); doc['schema'] = 1; b.save(doc)
        with self.assertRaisesRegex(b.base.Hold, 'BRIDGE_GENERATION_MISMATCH'): b.verify()

    def test_protected_map_drift_blocks_apply_and_recovery(self):
        b.apply(); self.edge.q.FRP_MAP.write_bytes(b'external')
        with self.assertRaises(b.base.Hold): b.verify()
        with self.assertRaises(b.base.Hold): b.restore()
        self.assertEqual(self.edge.q.FRP_MAP.read_bytes(), b'external')

    def test_incomplete_recovery_then_retry_recovery(self):
        b.apply()
        self.patch(b.base, 'nginx_reload', lambda: (_ for _ in ()).throw(RuntimeError('reload failed')))
        with self.assertRaises(RuntimeError): b.restore()
        self.assertEqual(b.record()[0]['state'], 'RECOVERING')
        with self.assertRaises(b.base.Hold): b.verify()
        self.patch(b.base, 'nginx_reload', lambda: None)
        b.restore(); self.preserved()
        self.assertEqual(b.record()[0]['state'], 'ROLLED_BACK')

    def test_partial_before_image_recovery(self):
        b.STATE.mkdir(mode=0o700)
        b.base.new_file(b.STATE/'backend.before', self.old, 0o600)
        b.restore(); self.assertFalse(b.STATE.exists()); self.preserved()

    def test_broker_missing_bridge_does_not_fall_back(self):
        broker = b.load('rc7_fixture_broker', 'smite-rc5-xhttp-root-broker.py')
        self.patch(broker, '_load_module', lambda *a: b)
        with self.assertRaisesRegex(broker.BrokerHold, 'RC7_XHTTP_BRIDGE_REQUIRED'): broker._verify_bridge()
        b.apply(); broker._verify_bridge()
        doc, _, _ = b.record(); doc['state'] = 'PREPARED'; b.save(doc)
        with self.assertRaisesRegex(broker.BrokerHold, 'BRIDGE_NOT_COMMITTED'): broker._verify_bridge()

    def test_real_nginx_effective_rc7_route_and_rollback(self):
        binary = os.environ.get('RC7_TEST_NGINX') or shutil.which('nginx')
        module = Path(os.environ.get('RC7_TEST_STREAM_MODULE', '/usr/lib/nginx/modules/ngx_stream_module.so'))
        if not binary or not module.is_file():
            if os.environ.get('RC7_REQUIRE_NGINX') == '1': self.fail('Nginx/stream required')
            self.skipTest('Nginx/stream unavailable; CI requires both')
        cert, key = self.root/'cert.pem', self.root/'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1',
                        '-subj', '/CN=ir.example.net'], check=True, capture_output=True)
        config = self.root/'nginx.conf'
        config.write_text('user root;\nload_module '+str(module)+';\n'
                          'pid '+str(self.root/'nginx.pid')+';\n'
                          'error_log '+str(self.root/'error.log')+';\nevents {}\n'
                          'http { access_log off; '+''.join(name+'_temp_path '+str(self.root/name)+'; ' for name in ('client_body','proxy','fastcgi','uwsgi','scgi'))+'ssl_certificate '+str(cert)+';\n'
                          'ssl_certificate_key '+str(key)+';\n'
                          'include '+str(b.base.BACKEND)+';\n'
                          'include '+str(self.edge.q.ALT_CANDIDATE)+'; }\n'
                          'stream { map $ssl_preread_server_name $uopti_smite_backend { default 127.0.0.1:8443; }\n'
                          'include '+str(self.edge.q.STREAM_SOURCE)+'; }\n')
        self.patch(b.base.admission, 'INCLUDE', ('    include '+str(b.base.BRIDGE)+';').encode())
        self.patch(b.base, 'BRIDGE_BYTES', ('include '+str(b.base.ROUTE_DIR)+'/*.conf;\n').encode())
        def run(args):
            result = subprocess.run([binary, '-p', str(self.root), '-c', str(config), args[-1]],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.returncode, result.stdout + result.stderr
        self.patch(b.base.admission, '_run', run)
        self.patch(b.base, 'nginx_test', lambda: run(['-t']))
        self.patch(b, 'effective', real_effective)
        b.plan(); b.apply(); b.verify()
        planner = b.load('rc7_test_route_plan', 'smite_xhttp_nginx_plan.py')
        route = planner.plan_xhttp_nginx_route(dict(port=20182, path='/20182/category-software-99',
                 listen='127.0.0.1', network='xhttp', protocol='vless', enabled=True),
                 registered_routes={}, frps_listener_ports={7000, 20182})
        # Offline rendered fixture only: production publication remains broker/G gated.
        route_file = b.base.ROUTE_DIR/'20182.conf'
        route_file.write_text(route.snippet); route_file.chmod(0o644)
        b.verify(); self.edge.validate_committed(self.edge.journal())
        _, dump = run(['-T'])
        self.assertEqual(dump.count('location = /20182/category-software-99 {'), 1)
        self.assertEqual(dump.count('location ^~ /20182/category-software-99/ {'), 1)
        self.assertEqual(dump.count('location = /~!frp {'), 1)
        self.assertIn('listen 127.0.0.1:8443 ssl;', dump)
        self.assertIn('listen 127.0.0.1:8444 ssl;', dump)
        self.assertIn('"ir.example.net|8.8.8.8" 127.0.0.1:8444;', dump)
        self.assertNotRegex(dump, r'listen\s+(?:0\.0\.0\.0:)?(?:7000|20182)\b')
        self.assertNotIn(b.base.admission.INCLUDE, self.edge.q.ALT_CANDIDATE.read_bytes())
        self.preserved()
        with self.assertRaises(b.base.Hold): b.restore()
        route_file.unlink()  # dispose only the offline route fixture
        b.restore(); run(['-t']); self.preserved()

    def test_rc7_verifier_uses_durable_bridge_proof(self):
        b.apply()
        # Exercise production bridge_source, rather than the filesystem adapter.
        edge = b.load('rc7_verifier_adapter', 'smite-rc7-wss-edge.py')
        self.patch(edge, 'load', lambda *a: b)
        self.assertEqual(edge.bridge_source(b.base.BACKEND.read_bytes()), self.old)
        with self.assertRaises(edge.Hold): edge.bridge_source(b.base.BACKEND.read_bytes()+b'# drift')

if __name__ == '__main__': unittest.main()
