import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('upgrade_test',ROOT/'modules/smite-stage15-upgrade.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
REAL_PLAN=u.plan
REAL_HEALTH=u.health

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
