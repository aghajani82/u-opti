import importlib.util
import json
import copy
import os
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('upgrade_test',ROOT/'modules/smite-stage15-upgrade.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
REAL_PLAN=u.plan
REAL_HEALTH=u.health
REAL_VALIDATE=u.validate
REAL_NORMAL=u.normal

@unittest.skipUnless(os.geteuid()==0,'root-owned fixture')
class Upgrade(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='/root');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.patch(u,'STATE',self.root/'state');self.patch(u.w,'LOCK',self.root/'lock')
        self.patch(u.w,'no_tunnels',lambda:None);self.patch(u.w,'protected',lambda *a:{'identity':'preserved','replay':'same-inode'})
        self.obj={'Image':u.OLD['node']};self.patch(u.w,'inspect',lambda role:self.obj)
        self.patch(u,'validate',lambda *a,**k:None);self.health=[];self.patch(u,'health',lambda doc,new:self.health.append(new))
        self.doc={'schema':1,'state':'PREPARED','roles':['node'],'runtime':{},'protected':u.w.protected([])}
        self.bundle={'images':{'node':{'file':'image.tar.gz','archive_sha256':'expected'}}}
        self.patch(u,'plan',lambda role,folder:(dict(self.doc),self.bundle));self.patch(u,'copy_archive',lambda *a:None);self.patch(u,'backup_state',lambda doc:None)
        self.calls=[];self.fail=False
        def run(args,**kwargs):
            self.calls.append(args)
            if args[:3]==['docker','image','inspect']:
                return u.OLD['node'] if args[3]==u.OLD['node'] else u.w.REVIEWED_IMAGES['node']
            if args[:2]==['docker','compose']:
                if self.fail:self.fail=False;raise u.h.Hold('SIMULATED_UPGRADE_FAILURE')
                self.obj['Image']=u.w.REVIEWED_IMAGES['node']
            return ''
        self.patch(u.h,'run',run)
    def patch(self,obj,key,value):
        p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
    def test_upgrade_commits_without_identity_or_replay_restore(self):
        u.apply('KH',self.root);self.assertEqual(u.record()['state'],'COMMITTED');self.assertEqual(self.health,[True])
        self.assertFalse(any('rm' in cmd for cmd in self.calls))
    def test_failed_recreate_restores_original_tag(self):
        self.fail=True
        with self.assertRaisesRegex(u.h.Hold,'ROLLED_BACK'):u.apply('KH',self.root)
        self.assertEqual(u.record()['state'],'ROLLED_BACK');self.assertIn(['docker','tag',u.OLD['node'],'smite-node:stage15-local'],self.calls)
        self.assertEqual(self.health,[False])
    def test_real_plan_and_health_require_signed_not_installed(self):
        # Regression: Smite engine_inventory() emits "not-installed" for
        # an unenrolled FRP engine, never "absent". Both preflight and
        # post-upgrade checks must use the exact API response value.
        # Supply the minimal realistic inspect fields required by the real
        # no-image-changing runtime signature (the older fixture only had Image).
        self.obj.update({
            'Config': {'Env': ['SMITE_AGENT_AUTH_MODE=strict'],
                       'Cmd': list(u.h.SAFE_NODE_COMMANDS[1])},
            'Mounts': [], 'HostConfig': {'NetworkMode': 'host'},
        })
        observed=[]
        def signed_inventory(state):
            observed.append(state)
            if state != 'not-installed':
                raise u.h.Hold('SIGNED_FRP_INVENTORY_REJECTED')
        self.patch(u.h,'signed_inventory',signed_inventory)
        self.patch(u.w,'NODE',self.root/'node')
        self.patch(u.verify_bundle,'verify',
                   lambda **kwargs:{'images':{'node':{
                       'local_image_id':u.w.REVIEWED_IMAGES['node']}}})
        self.patch(u,'plan',REAL_PLAN)
        doc,bundle=u.plan('KH',self.root)
        self.assertEqual(doc['roles'],['node'])
        self.assertEqual(bundle['images']['node']['local_image_id'],
                         u.w.REVIEWED_IMAGES['node'])
        self.patch(u,'health',REAL_HEALTH)
        self.obj['Image']=u.w.REVIEWED_IMAGES['node']
        u.health(doc,True)
        self.assertEqual(observed,['not-installed','not-installed'])

    def test_ir_prepared_journal_bind_reordering_only(self):
        # Reproduce the live IR incident: both containers are already new
        # and healthy, all inspected mounts are equal, only HostConfig.Binds
        # appears in a different order after Compose force-recreate.
        original={
            'Image':u.w.REVIEWED_IMAGES['node'],
            'Config':{'Env':['SMITE_AGENT_AUTH_MODE=strict'],
                      'Cmd':list(u.h.SAFE_NODE_COMMANDS[1])},
            'Mounts':[{'Destination':'/etc/smite-node',
                       'Source':'/opt/smite-node/config','RW':True,'Type':'bind'},
                      {'Destination':'/run/smite-node-identity',
                       'Source':'/etc/u-opti/smite/identities','RW':False,
                       'Type':'bind'}],
            'HostConfig':{'NetworkMode':'host','Privileged':False,
                          'Binds':['/opt/smite-node/config:/etc/smite-node:rw',
                                   '/etc/u-opti/smite/identities:/run/smite-node-identity:ro']}
        }
        saved=REAL_NORMAL(copy.deepcopy(original))
        # Existing PREPARED journal was written before this fix, when Binds
        # was stored in Docker's observed (unsorted) order.
        saved['host']['Binds']=list(original['HostConfig']['Binds'])
        doc={'runtime':{'node':saved}}
        obj=copy.deepcopy(original)
        obj['HostConfig']['Binds'].reverse()
        self.patch(u.w,'runtime',lambda *a,**k:None)
        self.patch(u,'validate',REAL_VALIDATE)
        u.validate('node',obj,doc)
        # Do not admit any true source/target/mode drift, missing entries,
        # duplicate bind, changed container mount, or other HostConfig drift.
        mutations=(
            lambda x:x['HostConfig']['Binds'].__setitem__(0,
                '/etc/u-opti/smite/identities:/run/smite-node-identity:rw'),
            lambda x:x['HostConfig']['Binds'].pop(),
            lambda x:x['HostConfig']['Binds'].append(
                '/tmp/extra:/run/extra:rw'),
            lambda x:x['HostConfig'].__setitem__('Privileged',True),
            lambda x:x['Mounts'][0].__setitem__('RW',False),
        )
        for mutate in mutations:
            with self.subTest(mutate=repr(mutate)):
                changed=copy.deepcopy(obj)
                mutate(changed)
                with self.assertRaisesRegex(u.h.Hold,
                                            'UPGRADE_RUNTIME_SECURITY_DRIFT'):
                    u.validate('node',changed,doc)

    def make_prepared_resume_state(self):
        self.root.joinpath('state').mkdir(mode=0o700)
        self.root.joinpath('state','record.json').write_text(json.dumps(self.doc)+'\n')
        self.root.joinpath('state','record.json').chmod(0o600)
        for filename in ('node-identity.before.json','node.image-before.tar'):
            target=self.root/'state'/filename
            target.write_bytes(b'CI-PRIVATE-BACKUP')
            target.chmod(0o600)
        db=self.root/'state'/'replay.before.sqlite3'
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE TABLE replay_ci (id INTEGER PRIMARY KEY)')
        db.chmod(0o600)
        return db

    def test_resume_prepared_verified_new_runtime_without_recreate(self):
        self.make_prepared_resume_state()
        self.assertEqual(u.record()['state'],'PREPARED')
        u.resume_prepared('KH')
        self.assertEqual(u.record()['state'],'COMMITTED')
        self.assertEqual(self.health,[True])
        self.assertTrue(all(cmd[:2]!=['docker','compose'] for cmd in self.calls))
        self.assertEqual((self.root/'state'/'node-identity.before.json').read_bytes(),
                         b'CI-PRIVATE-BACKUP')

    def test_ir_prepared_resume_requires_both_healthy_and_signed_proof(self):
        self.make_prepared_resume_state()
        panel_tar=self.root/'state'/'panel.image-before.tar'
        panel_tar.write_bytes(b'CI-PANEL-ORIGINAL-ARCHIVE')
        panel_tar.chmod(0o600)
        panel_db=self.root/'state'/'panel.before.sqlite3'
        with sqlite3.connect(panel_db) as conn:
            conn.execute('CREATE TABLE panel_ci (id INTEGER PRIMARY KEY)')
        panel_db.chmod(0o600)
        live={}
        for role in ('panel','node'):
            binds=['/opt/smite-node/config:/etc/smite-node:rw',
                   '/etc/u-opti/smite/identities:/run/smite-node-identity:ro'] if role=='node' else [
                   '/opt/smite/panel/data:/app/data:rw']
            live[role]={
                'Image':u.w.REVIEWED_IMAGES[role],
                'Config':{'Env':['CI_RUNTIME_POLICY=unchanged'],
                          'Cmd':list(u.h.SAFE_NODE_COMMANDS[1]) if role=='node' else ['CI-PANEL-CMD']},
                'Mounts':[{'Destination':'/etc/smite-node','Source':'/opt/smite-node/config',
                           'RW':True,'Type':'bind'}] if role=='node' else [],
                'HostConfig':{'NetworkMode':'host','Privileged':False,'Binds':list(reversed(binds))},
                'State':{'Running':True,'Health':{'Status':'healthy'}}
            }
        runtime={}
        for role in ('panel','node'):
            original=copy.deepcopy(live[role])
            original['HostConfig']['Binds'].reverse()
            runtime[role]=REAL_NORMAL(original)
        self.doc.update(roles=['panel','node'],runtime=runtime)
        (self.root/'state'/'record.json').write_text(json.dumps(self.doc)+'\n')
        self.patch(u.w,'inspect',lambda role:copy.deepcopy(live[role]))
        self.patch(u.w,'runtime',lambda role,obj,enabled,healthy=True,**kw:
            u.h.require(obj['State']['Running'] and obj['State']['Health']['Status']=='healthy'
                        and obj['Image']==u.w.REVIEWED_IMAGES[role],
                        'SIMULATED_UNHEALTHY_OR_WRONG_IMAGE'))
        signed=[]
        self.patch(u.h,'signed_inventory',lambda expected: signed.append(expected))
        self.patch(u,'validate',REAL_VALIDATE)
        self.patch(u,'health',REAL_HEALTH)
        commands=[]
        def inspect_images(args,**_):
            commands.append(args)
            if args[:3]!=['docker','image','inspect']:
                raise AssertionError('UNEXPECTED_DOCKER_CALL')
            target=args[3]
            for role in ('panel','node'):
                if target==u.OLD[role]:return u.OLD[role]
                if target=='smite-'+role+':stage15-local':return u.w.REVIEWED_IMAGES[role]
            raise AssertionError('UNKNOWN_IMAGE_INSPECTION')
        self.patch(u.h,'run',inspect_images)
        u.resume_prepared('IR')
        self.assertEqual(u.record()['state'],'COMMITTED')
        self.assertEqual(signed,['not-installed'])
        self.assertEqual(len(commands),4)
        self.assertTrue(all(c[:3]==['docker','image','inspect'] for c in commands))

    def test_resume_fails_closed_and_does_not_commit(self):
        db=self.make_prepared_resume_state()
        db.unlink()
        with self.assertRaisesRegex(u.h.Hold,'MISSING_OR_UNSAFE_RESUME_BACKUP'):
            u.resume_prepared('KH')
        self.assertEqual(u.record()['state'],'PREPARED')
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE TABLE replay_ci (id INTEGER PRIMARY KEY)')
        db.chmod(0o600)
        with self.assertRaisesRegex(u.h.Hold,'RESUME_REQUIRES_MATCHING_PREPARED_JOURNAL'):
            u.resume_prepared('IR')
        self.assertEqual(u.record()['state'],'PREPARED')
        self.patch(u,'health',lambda *a: (_ for _ in ()).throw(
            u.h.Hold('UPGRADE_RUNTIME_SECURITY_DRIFT')))
        with self.assertRaisesRegex(u.h.Hold,'UPGRADE_RUNTIME_SECURITY_DRIFT'):
            u.resume_prepared('KH')
        self.assertEqual(u.record()['state'],'PREPARED')

    def test_copy_checks_same_private_bytes(self):
        # Exercise the real implementation, independent of the transaction mock.
        spec=importlib.util.spec_from_file_location('upgrade_copy',ROOT/'modules/smite-stage15-upgrade.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        src=self.root/'source';src.write_bytes(b'archive-fixture');src.chmod(0o600)
        dest=self.root/'copy';m.copy_archive(src,dest,m.hashlib.sha256(src.read_bytes()).hexdigest())
        self.assertEqual(dest.stat().st_mode&0o777,0o600)
        with self.assertRaises(m.h.Hold):m.copy_archive(src,self.root/'wrong','0'*64)
        link=self.root/'link';link.symlink_to(src)
        with self.assertRaises(m.h.Hold):m.copy_archive(link,self.root/'linked','0'*64)
if __name__=='__main__':unittest.main()
