#!/usr/bin/env python3
"""Offline RC7 WSS read-only admission and negative security tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'modules'/'smite-rc7-wss-preflight.py'
spec=importlib.util.spec_from_file_location('rc7_wss_readonly',SOURCE)
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
PROJECT='uopti_rc6_'+'a'*32

class Tests(unittest.TestCase):
    def test_pinned_rc7_images(self):
        self.assertEqual(p.PANEL_IMAGE,'ghcr.io/aghajani82/smite-panel@sha256:180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8')
        self.assertEqual(p.NODE_IMAGE,'ghcr.io/aghajani82/smite-node@sha256:03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263')

    def test_only_one_environment_value_is_added(self):
        base={'name':PROJECT,'services':{'smite-node':{
            'image':p.NODE_IMAGE,'network_mode':'host',
            'cap_add':['NET_ADMIN','SYS_MODULE'],
            'devices':[{'source':'/dev/net/tun','target':'/dev/net/tun','permissions':'rwm'}],
            'volumes':[{'source':'/opt/3x-ui/instances/01/db','target':'/run/smite-sanaei-ro','read_only':True}],
            'environment':{'SMITE_NODE_PANEL_AUTH_MODE':'signed','SMITE_AGENT_AUTH_MODE':'strict'}
        }}}
        after=json.loads(json.dumps(base))
        after['services']['smite-node']['environment']['SMITE_FRP_STANDARD_WSS']='1'
        p.only_wss_change(base,after,'smite-node')
        for field in ('image','network_mode','cap_add','devices','volumes'):
            bad=json.loads(json.dumps(after))
            bad['services']['smite-node'][field]=[]
            with self.subTest(field=field),self.assertRaises(p.Hold):
                p.only_wss_change(base,bad,'smite-node')
        for updates in ({'SMITE_FRP_STANDARD_WSS':'true'},
                        {'SMITE_FRP_STANDARD_WSS':'1','SMITE_AGENT_AUTH_MODE':'paused'}):
            bad=json.loads(json.dumps(base))
            bad['services']['smite-node']['environment'].update(updates)
            with self.assertRaises(p.Hold):
                p.only_wss_change(base,bad,'smite-node')
        self.assertNotIn('SMITE_FRP_STANDARD_WSS',base['services']['smite-node']['environment'])

    def test_preserves_exact_compose_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            base=root/'docker-compose.yml'
            signed=root/'docker-compose.security-candidate.yml'
            base.write_text('services: {}\n')
            signed.write_text('services: {}\n')
            info={'Config':{'Labels':{
                'com.docker.compose.project':PROJECT,
                'com.docker.compose.service':'smite-node',
                'com.docker.compose.project.config_files':str(base)+','+str(signed)}}}
            with patch.object(p,'NODE',root):
                self.assertEqual(p.compose_files('smite-node',info),
                                 (PROJECT,[str(base),str(signed)]))
                for untrusted in (str(base)+','+str(signed)+',/tmp/extra.yml',
                                  str(signed),str(base)+','+str(base)):
                    info['Config']['Labels']['com.docker.compose.project.config_files']=untrusted
                    with self.subTest(files=untrusted),self.assertRaises(p.Hold):
                        p.compose_files('smite-node',info)
                info['Config']['Labels']['com.docker.compose.project']='smite'
                with self.assertRaises(p.Hold):
                    p.compose_files('smite-node',info)

    def test_sanaei_and_signed_policy_remain_secure(self):
        info={'Config':{'Image':p.NODE_IMAGE,'Env':[
            'SMITE_AGENT_AUTH_MODE=strict','SMITE_NODE_PANEL_AUTH_MODE=signed',
            'SMITE_ENGINE_INVENTORY_MODE=managed',
            'PANEL_ADDRESS=iran.grandoptical.ir:443',
            'NODE_ROLE=foreign','SMITE_SANAEI_INVENTORY_ENABLED=true'],
            'Cmd':['uvicorn','main:app','--host','127.0.0.1','--port','8888']},
            'State':{'Running':True,'Health':{'Status':'healthy'}},
            'HostConfig':{'NetworkMode':'host','Privileged':False},
            'Mounts':[{'Type':'bind','Source':'/opt/3x-ui/instances/01/db',
                       'Destination':'/run/smite-sanaei-ro','RW':False}]}
        p.service_gate('smite-node',info,role='foreign',domain='iran.grandoptical.ir')
        for key,value in [('RW',True),('Source','/other'),('Destination','/other')]:
            bad=json.loads(json.dumps(info));bad['Mounts'][0][key]=value
            with self.subTest(key=key),self.assertRaises(p.Hold):
                p.service_gate('smite-node',bad,role='foreign',domain='iran.grandoptical.ir')
        for field,badvalue in [('Env','SMITE_FRP_STANDARD_WSS=1'),('Env','SMITE_AGENT_AUTH_MODE=paused')]:
            bad=json.loads(json.dumps(info));bad['Config']['Env'].append(badvalue)
            with self.assertRaises(p.Hold):
                p.service_gate('smite-node',bad,role='foreign',domain='iran.grandoptical.ir')
        bad=json.loads(json.dumps(info));bad['Config']['Cmd'][3]='0.0.0.0'
        with self.assertRaises(p.Hold):
            p.service_gate('smite-node',bad,role='foreign',domain='iran.grandoptical.ir')

    def test_preview_only_cli(self):
        self.assertIn("choices=('plan',)",SOURCE.read_text())
        self.assertIn("RC7_WSS_ACTIVATION=NOT_IMPLEMENTED",SOURCE.read_text())
        self.assertEqual(p.overlay_bytes('smite-node'),
                         'services:\n  smite-node:\n    environment:\n      SMITE_FRP_STANDARD_WSS: "1"\n')

if __name__=='__main__':
    unittest.main(verbosity=2)
