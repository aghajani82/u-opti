"""Offline image graph validation; no extraction, Docker or live services."""
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('bundle',Path(__file__).resolve().parents[1]/'modules/smite-stage15-bundle-verify.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SHA='a'*40

def sha(raw):return hashlib.sha256(raw).hexdigest()
def js(obj):return json.dumps(obj).encode()

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'image.tar.gz'
        self.members={}
        raw=b'test-layer';layer=gzip.compress(raw,mtime=0)
        ld=self.blob(layer)
        self.config=dict(architecture='amd64',os='linux',config={'Labels':{'org.opencontainers.image.revision':SHA}},rootfs={'diff_ids':['sha256:'+sha(raw)]})
        cd=self.blob(js(self.config));self.config_name='blobs/sha256/'+cd['digest'][7:]
        manifest=self.blob(js(dict(schemaVersion=2,config=cd,layers=[ld])))
        manifest['platform']={'architecture':'amd64','os':'linux'}
        index=self.blob(js(dict(schemaVersion=2,manifests=[manifest])))
        self.identity=index['digest']
        self.members['index.json']=js(dict(schemaVersion=2,manifests=[index]))
        self.members['manifest.json']=js([dict(Config=self.config_name,RepoTags=['smite-panel:stage15-local'],Layers=['blobs/sha256/'+ld['digest'][7:]])])
    def blob(self,raw):
        d=sha(raw);self.members['blobs/sha256/'+d]=raw
        return {'digest':'sha256:'+d,'size':len(raw)}
    def write(self,extra=None):
        with tarfile.open(self.path,'w:gz') as t:
            for name,raw in self.members.items():
                info=tarfile.TarInfo(name);info.size=len(raw);t.addfile(info,io.BytesIO(raw))
            if extra:t.addfile(extra)
    def check(self,**kw):
        return m.inspect_archive(self.path,role='panel',source_sha=kw.get('source',SHA),image_id=kw.get('identity',self.identity))
    def test_containerd_index_bound_to_config(self):
        self.write();r=self.check();self.assertEqual(r['index_id'],self.identity)
        self.assertEqual(r['config_id'],'sha256:'+sha(self.members[self.config_name]));self.assertFalse(r['activation_allowed'])
    def test_classic_docker_config_id(self):
        self.members.pop('index.json');self.write()
        r=self.check(identity='sha256:'+sha(self.members[self.config_name]));self.assertIsNone(r['index_id'])
    def test_unrelated_id_rejected(self):
        self.write()
        with self.assertRaises(m.BundleHold):self.check(identity='sha256:'+'f'*64)
    def test_wrong_revision_rejected(self):
        self.write()
        with self.assertRaises(m.BundleHold):self.check(source='b'*40)
    def test_blob_tampering_rejected(self):
        self.members[self.config_name]+=b' ';self.write()
        with self.assertRaises(m.BundleHold):self.check()
    def test_wrong_tag_rejected(self):
        d=json.loads(self.members['manifest.json']);d[0]['RepoTags']=['smite-node:stage15-local'];self.members['manifest.json']=js(d);self.write()
        with self.assertRaises(m.BundleHold):self.check()
    def test_wrong_layer_graph_rejected(self):
        d=json.loads(self.members['manifest.json']);d[0]['Layers']=[self.config_name];self.members['manifest.json']=js(d);self.write()
        with self.assertRaises(m.BundleHold):self.check()
    def test_duplicate_members_rejected(self):
        self.write(tarfile.TarInfo('manifest.json'))
        with self.assertRaises(m.BundleHold):self.check()
    def test_traversal_and_link_rejected(self):
        for name,kind in [('../outside',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),('link',tarfile.SYMTYPE)]:
            info=tarfile.TarInfo(name);info.type=kind;info.linkname='/etc/passwd';self.write(info)
            with self.assertRaises(m.BundleHold):self.check()
    def test_index_descriptor_size_rejected(self):
        d=json.loads(self.members['index.json']);d['manifests'][0]['size']+=1;self.members['index.json']=js(d);self.write()
        with self.assertRaises(m.BundleHold):self.check()
    def test_multiple_runtime_images_rejected(self):
        d=json.loads(self.members['index.json']);d['manifests']*=2;self.members['index.json']=js(d);self.write()
        with self.assertRaises(m.BundleHold):self.check()
    def test_symlink_archive_rejected(self):
        self.write();link=self.path.with_name('link');link.symlink_to(self.path)
        with self.assertRaises(m.BundleHold):m.inspect_archive(link,role='panel',source_sha=SHA,image_id=self.identity)

if __name__=='__main__':unittest.main()
