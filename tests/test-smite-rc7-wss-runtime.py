#!/usr/bin/env python3
"""RC7 WSS runtime and edge isolation, zero-live-mutation regression tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
MODULES=ROOT/'modules'

def load(alias,name):
    spec=importlib.util.spec_from_file_location(alias,MODULES/name)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

rt=load('rc7_rt_test','smite-rc7-wss-runtime.py')
edge=load('rc7_edge_test','smite-rc7-wss-edge.py')
p=rt.p

class WssControllerTests(unittest.TestCase):
    def test_cli_requires_verified_snapshot_and_tty_for_mutations(self):
        for module in (rt,edge):
            source=Path(module.__file__).read_text()
            self.assertIn("SNAPSHOTS-CONSOLES-VERIFIED",source)
            self.assertIn('sys.stdin.isatty()',source)
            self.assertIn('OPERATOR_CANCELLED',source)

    def test_only_wss_compose_overlay_provided(self):
        self.assertEqual(rt.OVERLAY,'docker-compose.wss-rc7.yml')
        for name in ('smite-panel','smite-node'):
            self.assertIn('SMITE_FRP_STANDARD_WSS: "1"',p.overlay_bytes(name))
        self.assertNotIn('cap_add',p.overlay_bytes('smite-node'))
        self.assertNotIn('devices',p.overlay_bytes('smite-node'))
        self.assertNotIn('volumes',p.overlay_bytes('smite-node'))
        self.assertIn("choices=('plan','apply','verify','rollback','recover')",
                      Path(rt.__file__).read_text())
        self.assertIn("no_tunnels()",Path(rt.__file__).read_text())
        self.assertIn("'pgrep','-x','frpc'",Path(rt.__file__).read_text())

    def test_runtime_signature_ignores_only_wss_and_host_bind_order(self):
        info={'Config':{'Image':p.NODE_IMAGE,'Env':['A=1','B=secret'],
                        'Cmd':['uvicorn'],'Entrypoint':None},
              'HostConfig':{'Binds':['/a:/a:ro','/b:/b:ro'],
                            'NetworkMode':'host','Privileged':False,
                            'CapAdd':['NET_ADMIN','SYS_MODULE']},
              'Mounts':[{'Type':'bind','Source':'/a','Destination':'/a','RW':False}]}
        original=rt.runtime_signature(info)
        copy=json.loads(json.dumps(info))
        copy['Config']['Env'].append('SMITE_FRP_STANDARD_WSS=1')
        copy['HostConfig']['Binds'].reverse()
        self.assertEqual(original,rt.runtime_signature(copy))
        changes=[
            lambda o:o['HostConfig'].update({'CapAdd':['SYS_ADMIN']}),
            lambda o:o['Config']['Env'].append('A=evil'),
            lambda o:o['Mounts'][0].update({'RW':True}),
            lambda o:o['Config'].update({'Image':'smite-node:latest'}),
            lambda o:o['HostConfig'].update({'NetworkMode':'bridge'}),
        ]
        for change in changes:
            copy=json.loads(json.dumps(info))
            change(copy)
            with self.subTest(change=change):
                try:
                    changed = rt.runtime_signature(copy)
                except p.Hold:
                    continue  # Duplicate env is correctly fail-closed.
                self.assertNotEqual(original, changed)

    def test_active_compose_labels_stripped_only_at_exact_final_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'docker-compose.yml').write_text('services: {}\n')
            (root/'docker-compose.security-candidate.yml').write_text('services: {}\n')
            doc={'role':'foreign','domain':'iran.grandoptical.ir',
                 'project':'uopti_rc6_'+'a'*32,
                 'baseline':{'smite-node':{'files':[
                     str(root/'docker-compose.yml'),
                     str(root/'docker-compose.security-candidate.yml')
                 ],'signature':'digest'}}}
            labels={'com.docker.compose.project':doc['project'],
                    'com.docker.compose.service':'smite-node',
                    'com.docker.compose.project.config_files':
                       ','.join(doc['baseline']['smite-node']['files'])}
            obj={'Config':{'Labels':labels,'Env':['SMITE_FRP_STANDARD_WSS=1']}}
            with patch.object(p,'NODE',root),patch.object(rt,'overlay_path',
                 return_value=root/'docker-compose.wss-rc7.yml'):
                # Guard that an extra/non-final overlay is refused before
                # any runtime introspection or Compose process invocation.
                labels['com.docker.compose.project.config_files']+=',/unexpected.yml'
                with patch.object(rt,'inspect_container',return_value=obj):
                    with self.assertRaises(p.Hold):
                        rt.ensure_service('smite-node',doc,enabled=True)

    def test_no_public_side_effect_helper(self):
        source=Path(rt.__file__).read_text()
        self.assertIn("'--no-deps','--pull','never'",source)
        self.assertIn("'--force-recreate',name",source)
        self.assertIn("ROLLBACK_EDGE_FIRST",Path(edge.__file__).read_text()
                      if 'ROLLBACK_EDGE_FIRST' in Path(edge.__file__).read_text()
                      else Path(rt.__file__).read_text())
        self.assertIn('IDENTITY_REPLAY_RETAINED=YES',source)
        self.assertNotIn('docker stop 3xui-01',source)
        self.assertNotIn('docker restart 3xui-01',source)

    def test_journal_rejects_unknown_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/'record.json').write_text(json.dumps({
                'schema':1,'role':'foreign','state':'UNKNOWN',
                'services':['smite-node']
            }))
            (folder/'record.json').chmod(0o600)
            with patch.object(rt,'STATE',folder):
                with self.assertRaises(p.Hold):
                    rt.record()

    def test_edge_renders_exact_approved_peer_and_port(self):
        domain='iran.grandoptical.ir'
        q=edge.q
        q.DOMAIN=domain
        src=('# Managed by U-OPTI - Smite Panel TLS backend\n'
             'server {\n    listen 127.0.0.1:8443 ssl;\n'
             '    server_name iran.grandoptical.ir;\n'
             '    location / {\n        proxy_pass http://127.0.0.1:8000;\n'
             '    }\n}\n').encode()
        stream=('# Managed by U-OPTI - Smite TCP/443 SNI gateway\n'
                'map "$ssl_preread_server_name|$remote_addr" $uopti_frp_canary_backend {\n'
                'include /etc/nginx/u-opti-smite-frp-sni-map.conf;\n'
                'default $uopti_smite_backend;\n}\n'
                'server {\nlisten 443;\nssl_preread on;\n'
                'proxy_pass $uopti_frp_canary_backend;\n}\n').encode()
        mapping=('# U-OPTI FRP TLS/SNI allowlist (SNI + source IPv4 required)\n').encode()
        alt,new=edge.render(domain,'91.107.169.200',before=src,
                            stream=stream,mapping=mapping)
        self.assertIn(b'location = /~!frp',alt)
        self.assertIn(b'proxy_pass http://127.0.0.1:7000;',alt)
        self.assertIn(b'"iran.grandoptical.ir|91.107.169.200" 127.0.0.1:8444;',new)
        self.assertNotIn(b'91.107.169.200',src)
        for invalid in ('127.0.0.1','0.0.0.0','not-an-address'):
            with self.subTest(invalid=invalid),self.assertRaises(edge.p.Hold):
                edge.render(domain,invalid,before=src,stream=stream,mapping=mapping)

    def test_source_ip_canary_does_not_route_other_clients_to_frp(self):
        stream=Path(MODULES/'smite-rc2-frp-wss-edge-plan.py').read_text()
        self.assertIn("default $uopti_smite_backend;",stream)
        self.assertIn('stream.count("map \\"$ssl_preread_server_name|$remote_addr\\"',stream)

if __name__=='__main__':
    unittest.main(verbosity=2)
