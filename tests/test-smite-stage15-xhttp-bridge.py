"""Real filesystem transactions, mocked host commands; no live hosts."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bridge_test', ROOT/'modules/smite-stage15-xhttp-bridge.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)

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

if __name__ == '__main__': unittest.main()
