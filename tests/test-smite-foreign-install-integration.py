"""Cross-repository offline ASGI contract; SMITE_SOURCE must name pinned checkout."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

source=Path(os.environ['SMITE_SOURCE'])
sys.path.insert(0,str(source/'tests'));sys.path.insert(0,str(source/'panel'))
import test_foreign_install_http as http_fixture
from app.config import settings
from app.routers import signed_nodes
from app.signed_node_registration import initialize_replay_schema
spec=importlib.util.spec_from_file_location('trial_client',Path(__file__).resolve().parents[1]/'modules/smite-foreign-install-client.py')
c=importlib.util.module_from_spec(spec);sys.modules[spec.name]=c;spec.loader.exec_module(c)

class Integration(unittest.TestCase):
    def test_real_redemption_lost_reply_expired_recovery_and_revocation(self):
        fixture=http_fixture.ForeignInstallHTTP();fixture.setUp();self.addCleanup(fixture.doCleanups)
        settings.smite_foreign_install_origin_trust_enabled=True
        parent=Path(fixture.tmp.name)/'trust';parent.mkdir(mode=0o700)
        old=settings.smite_signed_node_origins_path
        settings.smite_signed_node_origins_path=str(parent/'origins.json')
        self.addCleanup(setattr,settings,'smite_signed_node_origins_path',old)
        initialize_replay_schema(fixture.db)
        fixture.client.app.include_router(signed_nodes.router,prefix='/api/node-control')
        response=fixture.issue();self.assertEqual(response.status_code,200)
        packet=dict(protocol='smi1',panel_url='https://panel.example.com',**response.json())
        stage=Path(fixture.tmp.name)/'stage';stage.mkdir(mode=0o700)
        targets=[]
        def wire(panel,target,body,headers):
            targets.append(target)
            if target==c.REDEEM:headers={**headers,'X-Smite-Pairing-Ingress':fixture.ingress}
            result=fixture.client.post(target,content=body,headers={**headers,'Content-Type':'application/json'})
            if result.status_code!=200:raise c.Hold('Rejected')
            if target==c.REDEEM:raise TimeoutError('simulate lost acknowledgement after real commit')
            return result.json()
        args=dict(directory=stage,live_identity=stage/'live.json',transport=wire)
        self.assertEqual(c.enroll(json.dumps(packet),**args)['status'],'enrolled')
        before=(stage/'foreign-install-identity.json').read_bytes()
        packet['expires_at']=int(time.time())-1
        settings.smite_foreign_install_enabled=False
        targets.clear()
        self.assertEqual(c.enroll(json.dumps(packet),**args)['status'],'enrolled')
        self.assertEqual(targets,[c.STATUS])
        self.assertEqual(before,(stage/'foreign-install-identity.json').read_bytes())
        from app.node_pairing_store import revoke_node
        revoke_node(fixture.db,node_id=fixture.node)
        with self.assertRaises(c.Hold):c.enroll(json.dumps(packet),**args)
        self.assertEqual(before,(stage/'foreign-install-identity.json').read_bytes())

if __name__=='__main__':unittest.main()
