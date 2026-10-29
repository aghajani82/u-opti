import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('wss_test',ROOT/'modules/smite-stage15-wss.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
spec=importlib.util.spec_from_file_location('compose_test',ROOT/'modules/smite-compose-safe.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

def node(enabled=False):
    env=['SMITE_AGENT_AUTH_MODE=strict','SMITE_NODE_PANEL_AUTH_MODE=signed','SMITE_ENGINE_INVENTORY_MODE=managed',
         'SMITE_AGENT_IDENTITY_PATH=/run/smite-node-identity/node-identity.json',
         'SMITE_AGENT_REPLAY_DB=/var/lib/smite-node/auth/agent-replay.sqlite3','PANEL_ADDRESS=ir.example.net:443']
    if enabled:env.append('SMITE_FRP_STANDARD_WSS=1')
    files=w.service_files('node')+([w.overlay('node')] if enabled else [])
    mounts=[{'Destination':a,'Source':b,'RW':rw,'Type':'bind'} for a,b,rw in (
        ('/etc/smite-node','/opt/smite-node/config',True),('/run/smite-node-identity','/etc/u-opti/smite/identities',False),
        ('/var/lib/smite-node/auth','/var/lib/u-opti/smite-node-security/replay',True),
        ('/usr/local/bin/frpc',str(w.host.Paths().binaries/'frpc'),False),('/usr/local/bin/frps',str(w.host.Paths().binaries/'frps'),False))]
    return {'Image':w.REVIEWED_IMAGES['node'],'State':{'Running':True,'Health':{'Status':'healthy'}},
        'HostConfig':{'NetworkMode':'host','PortBindings':{},'Privileged':False},'Mounts':mounts,
        'Config':{'Image':'smite-node:stage15-local','Cmd':['uvicorn','main:app','--host','127.0.0.1','--port','8888'],'Env':env,
                  'Labels':{'com.docker.compose.service':'smite-node','com.docker.compose.project.config_files':','.join(map(str,files))}}}

class RuntimePolicy(unittest.TestCase):
    def test_signed_runtime_and_wss_only_signature_change(self):
        self.assertEqual(w.runtime('node',node(),False),'ir.example.net')
        self.assertEqual(w.runtime('node',node(True),True),'ir.example.net')
        self.assertEqual(w.signature(node()),w.signature(node(True)))
    def test_docker_bind_order_only_is_canonical_but_security_drift_is_not(self):
        old=node()
        old['HostConfig']['Binds']=[
            '/opt/smite-node/config:/etc/smite-node:rw',
            '/etc/u-opti/smite/identities:/run/smite-node-identity:ro',
            '/var/lib/u-opti/smite-node-security/replay:/var/lib/smite-node/auth:rw',
            '/opt/u-opti/engines/frp/v0.71.0/frpc:/usr/local/bin/frpc:ro',
            '/opt/u-opti/engines/frp/v0.71.0/frps:/usr/local/bin/frps:ro',
        ]
        before=w.signature(old)
        after=copy.deepcopy(old)
        after['HostConfig']['Binds'].reverse()
        after['Config']['Env'].append('SMITE_FRP_STANDARD_WSS=1')
        self.assertEqual(before,w.signature(after))
        # WSS apply/rollback must still fail closed on actual bind changes,
        # including added or deleted entries, even if the rest is reordered.
        for changes in (
            lambda x:x['HostConfig']['Binds'].__setitem__(0,'/tmp/evil:/run/smite-node-identity:rw'),
            lambda x:x['HostConfig']['Binds'].append('/tmp/evil:/tmp/evil:rw'),
            lambda x:x['HostConfig']['Binds'].pop(),
            lambda x:x['HostConfig'].update(Privileged=True),
            lambda x:x['Mounts'][1].update(Source='/tmp/evil'),
            lambda x:x['Config']['Cmd'].append('--proxy-headers'),
        ):
            changed=copy.deepcopy(after);changes(changed)
            self.assertNotEqual(before,w.signature(changed))
        for bad in ('untrusted', ['valid',1], {'unexpected':'dict'}):
            obj=copy.deepcopy(after);obj['HostConfig']['Binds']=bad
            with self.assertRaisesRegex(w.Hold,'INVALID_HOST_BINDS'):
                w.signature(obj)

    def test_exact_standard_installer_loopback_command_is_admitted(self):
        # smite-node-local-bind.py ships these exact extra Uvicorn flags.
        self.assertEqual(len(w.host.SAFE_NODE_COMMANDS),2)
        for argv in w.host.SAFE_NODE_COMMANDS:
            obj=node()
            obj['Config']['Cmd']=list(argv)
            self.assertEqual(w.runtime('node',obj,False),'ir.example.net')
        for argv in (
            list(w.host.SAFE_NODE_COMMANDS[1])+['--proxy-headers'],
            ['uvicorn','main:app','--host','0.0.0.0','--port','8888',
             '--log-level','info','--access-log'],
            ['uvicorn','main:app','--host','127.0.0.1','--port','9999',
             '--log-level','info','--access-log'],
        ):
            obj=node()
            obj['Config']['Cmd']=argv
            with self.assertRaisesRegex(w.Hold,'NODE_API_NOT_LOOPBACK'):
                w.runtime('node',obj,False)

    def test_unknown_image_mount_privilege_api_and_policy_rejected(self):
        changes=[lambda x:x.update(Image='sha256:'+'0'*64),lambda x:x['Mounts'][1].update(Source='/tmp/identity'),
            lambda x:x['Mounts'][1].update(RW=True),lambda x:x['HostConfig'].update(Privileged=True),
            lambda x:x['Config']['Cmd'].__setitem__(3,'0.0.0.0'),lambda x:x['Config']['Env'].append('SMITE_AGENT_AUTH_MODE=legacy'),
            lambda x:x['Mounts'].append(x['Mounts'][0]),lambda x:x['Config']['Labels'].update({'com.docker.compose.project.config_files':'/opt/smite-node/docker-compose.yml'})]
        for mutate in changes:
            obj=node();mutate(obj)
            with self.assertRaises(w.Hold):w.runtime('node',obj,False)
    def test_stopped_service_only_recovery_lane(self):
        obj=node(True);obj['State']['Running']=False
        with self.assertRaises(w.Hold):w.runtime('node',obj,True)
        w.runtime('node',obj,True,healthy=False)
    def test_domains_reject_config_injection(self):
        for value in ('ir.example;evil','http://ir.example','ir.example\n','127.0.0.1:443','x'):
            with self.assertRaises(w.Hold):w.domain(value)
    def test_no_automatic_candidate_activation(self):
        base=Path('/opt/smite-node/docker-compose.yml');obj=node()
        obj['Config']['Labels']['com.docker.compose.project.config_files']=str(base)
        with patch.object(c,'trusted'):
            self.assertEqual(c.active_files(base,obj),[base])
            self.assertEqual(c.active_files(base,node(True)),w.service_files('node')+[w.overlay('node')])
    def test_nondefault_frps_listener_blocks_wss_changes(self):
        # A live Owner must block WSS changes even when control port != 7000.
        # Test is completely offline and reads no actual host sockets.
        with tempfile.TemporaryDirectory() as temp:
            def fake_ss(argv):
                if argv == ['ss','-H','-lnt','( sport = :7000 )']:
                    return ''
                if argv == ['ss','-H','-lntp']:
                    return 'LISTEN 0 128 127.0.0.1:17000 0.0.0.0:* users:(("frps",pid=123,fd=3))'
                raise AssertionError('unexpected host query')
            with patch.object(w,'NODE',Path(temp)),patch.object(w,'run',side_effect=fake_ss):
                with self.assertRaisesRegex(w.Hold,'FRPS_OWNER_STILL_RUNNING'):
                    w.no_tunnels()

    def test_unknown_duplicate_or_external_compose_rejected(self):
        base=Path('/opt/smite-node/docker-compose.yml')
        for extra in ('/tmp/evil.yml',str(base),'/opt/smite-node/unreviewed.yml'):
            obj=node();obj['Config']['Labels']['com.docker.compose.project.config_files']=str(base)+','+extra
            with patch.object(c,'trusted'),self.assertRaises(c.Hold):c.active_files(base,obj)

@unittest.skipUnless(os.geteuid()==0,'root-owned transaction fixture')
class WssTransaction(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/root');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.patch('STATE',self.root/'state');self.patch('LOCK',self.root/'engine.lock');self.patch('NODE',self.root/'node');w.NODE.mkdir(mode=0o700)
        self.obj=node();self.doc={'schema':1,'state':'PREPARED','roles':['node'],'domain':'ir.example.net','runtime':{'node':w.signature(self.obj)},'protected':{'fixture':'unchanged'}}
        self.patch('plan',lambda role:copy.deepcopy(self.doc));self.patch('protected',lambda roles:{'fixture':'unchanged'})
        self.patch('no_tunnels',lambda:None);self.patch('runtime',lambda *a,**k:None);self.patch('inspect',lambda role:self.obj)
        self.health=[];self.patch('health',lambda doc,enabled:self.health.append(enabled))
        self.calls=[];self.fail=False
        def run(argv,**kwargs):
            self.calls.append(argv)
            if argv[:3]==['docker','image','inspect']:return self.obj['Image']
            if self.fail and str(w.overlay('node')) in argv:self.fail=False;raise w.Hold('SIMULATED_RECREATE_FAILURE')
            return ''
        self.patch('run',run)
    def patch(self,key,value):
        p=patch.object(w,key,value);p.start();self.addCleanup(p.stop)
    def test_commit_and_rollback_keep_receipt_and_protected_state(self):
        w.apply('KH');self.assertEqual(w.read_record()['state'],'COMMITTED');self.assertEqual(w.overlay('node').stat().st_mode&0o777,0o600)
        w.restore(w.read_record());self.assertFalse(w.overlay('node').exists());self.assertEqual(w.read_record()['state'],'ROLLED_BACK');self.assertEqual(self.health,[True,False])
    def test_failed_recreation_restores_original_and_no_tunnel_created(self):
        self.fail=True
        with self.assertRaisesRegex(w.Hold,'ROLLED_BACK'):w.apply('KH')
        self.assertEqual(w.read_record()['state'],'ROLLED_BACK');self.assertFalse(w.overlay('node').exists())
        self.assertTrue(all('smite-node' in cmd or cmd[:3]==['docker','image','inspect'] for cmd in self.calls))
    def test_tampered_overlay_stops_before_recreate(self):
        w.apply('KH');w.overlay('node').write_text('tampered');self.calls.clear()
        with self.assertRaisesRegex(w.Hold,'OVERLAY_DRIFT'):w.restore(w.read_record())
        self.assertFalse(any('up' in cmd for cmd in self.calls))
    def test_symlink_and_unsafe_private_state_rejected(self):
        target=self.root/'target';target.write_text('sentinel');link=self.root/'link';link.symlink_to(target)
        with self.assertRaises(w.Hold):w.host.file(link)
        w.STATE.mkdir(mode=0o755)
        with self.assertRaises(w.Hold):w.read_record()
        self.assertEqual(target.read_text(),'sentinel')

if __name__=='__main__':unittest.main()
