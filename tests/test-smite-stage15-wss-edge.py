import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('edge_test',ROOT/'modules/smite-stage15-wss-edge.py')
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)

@unittest.skipUnless(os.geteuid()==0,'root fixture')
class EdgeTransaction(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='/root');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.patch(e,'STATE',self.root/'state');self.patch(e.wss,'LOCK',self.root/'lock')
        for name in ('TLS_SOURCE','STREAM_SOURCE','FRP_MAP','ALT_CANDIDATE'):self.patch(e.edge,name,self.root/name)
        self.patch(e.edge,'DOMAIN','ir.example.net')
        self.source=e.edge.BACKEND_HEADER+'server {\n    listen 127.0.0.1:8443 ssl;\n    server_name ir.example.net;\n    location / {\n        proxy_pass http://127.0.0.1:8000;\n    }\n}\n'
        e.edge.TLS_SOURCE.write_text(self.source);e.edge.STREAM_SOURCE.write_text('fixture-stream');e.edge.FRP_MAP.write_text(e.edge.MAP_HEADER)
        self.doc={'schema':1,'state':'PREPARED','domain':'ir.example.net','peer':'8.8.8.8','backend':e.host.digest(self.source.encode()),'stream':e.host.digest(b'fixture-stream'),'old_map':e.edge.MAP_HEADER,'new_map':e.edge.render_map(e.edge.MAP_HEADER,'8.8.8.8'),'alt':e.edge.render_alt(self.source),'mode':0o644}
        self.patch(e,'plan',lambda peer:dict(self.doc));self.calls=[]
        self.patch(e.host,'run',lambda args:self.calls.append(args))
    def patch(self,obj,name,value):
        p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
    def test_peer_scoped_map_and_unmodified_original_vhost(self):
        e.apply('8.8.8.8');self.assertEqual(e.state()['state'],'COMMITTED')
        self.assertEqual(e.edge.TLS_SOURCE.read_text(),self.source)
        self.assertIn('"ir.example.net|8.8.8.8" 127.0.0.1:8444;',e.edge.FRP_MAP.read_text())
        self.assertIn('proxy_pass http://127.0.0.1:7000;',e.edge.ALT_CANDIDATE.read_text())
        e.restore(e.state());self.assertEqual(e.edge.FRP_MAP.read_text(),e.edge.MAP_HEADER);self.assertFalse(e.edge.ALT_CANDIDATE.exists())
    def test_external_edit_blocks_rollback(self):
        e.apply('8.8.8.8');e.edge.FRP_MAP.write_text('external change');self.calls.clear()
        with self.assertRaises(e.host.Hold):e.restore(e.state())
        self.assertEqual(self.calls,[])
    def test_private_peer_rejected(self):
        for peer in ('127.0.0.1','10.0.0.1','0.0.0.0','::1','8.8.8.8; include bad;'):
            with self.assertRaises(e.edge.Hold):e.edge.kh_ip(peer)
    def test_recover_partial_map_write(self):
        e.apply('8.8.8.8')
        temp=e.edge.FRP_MAP.with_name(e.edge.FRP_MAP.name+'.next');temp.write_bytes(self.doc['old_map'].encode()[:12]);temp.chmod(0o600)
        e.restore(e.state());self.assertFalse(temp.exists());self.assertEqual(e.state()['state'],'ROLLED_BACK')
if __name__=='__main__':unittest.main()
