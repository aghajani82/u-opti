import importlib.util,json,os,pathlib,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('ui',ROOT/'modules/smite-stage15-ui-trial.py');u=importlib.util.module_from_spec(s);s.loader.exec_module(u)
@unittest.skipUnless(os.geteuid()==0,'root-owned fixtures')
class FilesystemTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir='/root');self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name)
  (self.root/'app').mkdir();(self.root/'static/assets').mkdir(parents=True)
  self.backend={}
  for n in ['main.py']+['app/m%d.py'%i for i in range(11)]:
   p=self.root/n;p.write_text('unchanged backend\n');self.backend[n]=u.digest(p.read_bytes())
  (self.root/'static/index.html').write_text('old index');(self.root/'static/assets/old.js').write_text('old asset')
  self.old=u.read_tree(self.root/'static');self.new={'index.html':u.encoded(b'new index'),'assets/new.js':u.encoded(b'new asset')}
 def call(self,action):return u.worker(self.root,dict(action=action,backend=self.backend,old=self.old,new=self.new))
 def unchanged_backend(self):u.backend(self.root,self.backend)
 def test_apply_verify_rollback_preserves_old_assets_backend(self):
  self.call('apply');self.call('verify');self.unchanged_backend()
  self.call('rollback');self.call('rollback')
  self.assertEqual((self.root/'static/index.html').read_text(),'old index')
  self.assertEqual((self.root/'static/assets/old.js').read_text(),'old asset')
  self.assertEqual((self.root/'static/assets/new.js').read_text(),'new asset')
 def test_asset_collision_before_index(self):
  self.new['assets/old.js']=u.encoded(b'collision')
  with self.assertRaises(u.Hold):self.call('apply')
  self.assertEqual(u.read_tree(self.root/'static'),self.old)
 def test_backend_drift_before_writes(self):
  (self.root/'main.py').write_text('drift')
  with self.assertRaises(u.Hold):self.call('apply')
  self.assertEqual(u.read_tree(self.root/'static'),self.old)
 def test_unknown_asset_or_index_drift_blocks_rollback(self):
  self.call('apply');(self.root/'static/index.html').write_text('foreign')
  with self.assertRaises(u.Hold):self.call('rollback')
 def test_partial_asset_upload_can_rollback(self):
  with patch.object(u,'atomic_file',side_effect=OSError('simulated precommit crash')):
   with self.assertRaises(OSError):self.call('apply')
  self.assertEqual((self.root/'static/index.html').read_text(),'old index')
  self.call('rollback');self.unchanged_backend()
 def test_postcommit_crash_can_verify_then_rollback(self):
  original=u.atomic_file
  def crash(*args):original(*args);raise OSError('after commit')
  with patch.object(u,'atomic_file',side_effect=crash):
   with self.assertRaises(OSError):self.call('apply')
  self.call('verify');self.call('rollback')
 def test_inert_interrupted_temp_is_preserved(self):
  p=self.root/'static/assets/.uopti-ui-interrupted';p.write_text('partial bytes')
  self.call('apply');self.call('rollback');self.assertTrue(p.exists())
 def test_symlink_asset_rejected(self):
  (self.root/'static/assets/link.js').symlink_to(self.root/'main.py')
  with self.assertRaises(u.Hold):self.call('apply')
 def test_path_traversal_rejected(self):
  self.new['assets/../../main.py']=u.encoded(b'bad')
  with self.assertRaises(u.Hold):self.call('apply')
  self.unchanged_backend()
 def test_repeated_apply_and_missing_old_asset_hold(self):
  self.call('apply')
  with self.assertRaises(u.Hold):self.call('apply')
  (self.root/'static/assets/old.js').unlink()
  with self.assertRaises(u.Hold):self.call('rollback')
 def test_group_writable_static_rejected(self):
  (self.root/'static').chmod(0o775)
  with self.assertRaises(u.Hold):self.call('apply')
 def test_corrupt_new_asset_rejected_by_verify(self):
  self.call('apply');(self.root/'static/assets/new.js').write_text('bad')
  with self.assertRaises(u.Hold):self.call('verify')
 def test_drift_before_atomic_commit_does_not_publish(self):
  original=u.read_tree;calls=0
  def drift(path):
   nonlocal calls
   calls+=1
   if calls==2:(self.root/'static/index.html').write_text('drift')
   return original(path)
  with patch.object(u,'read_tree',side_effect=drift),self.assertRaises(u.Hold):self.call('apply')
  self.assertEqual((self.root/'static/index.html').read_text(),'drift')
@unittest.skipUnless(os.geteuid()==0,'root-owned fixtures')
class HostTransactionTests(unittest.TestCase):
 def setUp(self):
  FilesystemTests.setUp(self)
  self.lock=self.root/'lock';self.lock.write_text('');self.lock.chmod(0o600)
  self.fakebundle=self.root/'bundle.zip';self.fakebundle.write_text('fixture')
  self.state=self.root/'receipt'
  self.identity_value=[{'container':'unchanged','frps_pid':42}]
  self.patches=[patch.object(u,'STATE',self.state),patch.object(u,'ENGINE_LOCK',self.lock),
   patch.object(u,'bundle',return_value=({'backend_sha256':self.backend},self.new)),
   patch.object(u,'identity',side_effect=lambda:self.identity_value.copy()),
   patch.object(u,'remote',side_effect=lambda action,manifest,**kw:u.worker(self.root,dict(action=action,backend=self.backend,**kw))),
   patch.object(u.os,'uname',return_value=type('Host',(),{'nodename':'ir'})()),
   patch.object(u.sys.stdin,'isatty',return_value=True)]
  for p in self.patches:p.start();self.addCleanup(p.stop)
 def command(self,action,answer=''):
  with patch.object(u.sys,'argv',['ui-trial.py',action,'--bundle',str(self.fakebundle),'--sha256','a'*64]),patch('builtins.input',return_value=answer):u.main()
 def record(self):return json.loads((self.state/'record.json').read_text())
 def test_full_command_transaction_and_permissions(self):
  self.command('preflight');self.assertFalse(self.state.exists())
  self.command('backup');self.assertEqual(self.record()['phase'],'BACKED_UP')
  self.assertEqual((self.state/'record.json').stat().st_mode&0o777,0o600)
  self.command('apply','APPLY-UI-ONLY');self.assertEqual(self.record()['phase'],'COMMITTED')
  self.command('verify');self.command('rollback','ROLLBACK-UI-ONLY')
  self.assertEqual(self.record()['phase'],'ROLLED_BACK')
  self.assertEqual(u.read_tree(self.root/'static')['index.html'],self.old['index.html'])
 def test_cancel_repeat_backup_and_runtime_drift(self):
  self.command('backup')
  with self.assertRaises(u.Hold):self.command('backup')
  with self.assertRaises(u.Hold):self.command('apply','no')
  self.assertEqual(self.record()['phase'],'BACKED_UP')
  self.identity_value=[{'container':'changed','frps_pid':43}]
  with self.assertRaises(u.Hold):self.command('apply','APPLY-UI-ONLY')
  self.assertEqual(u.read_tree(self.root/'static'),self.old)
 def test_journal_preserved_on_failed_apply_and_recoverable(self):
  self.command('backup');original=u.atomic_file
  def crash(*args):original(*args);raise OSError('crash after switch')
  with patch.object(u,'atomic_file',side_effect=crash),self.assertRaises(OSError):self.command('apply','APPLY-UI-ONLY')
  self.assertEqual(self.record()['phase'],'APPLYING')
  self.command('verify');self.command('rollback','ROLLBACK-UI-ONLY')
 def test_non_tty_denied_before_backup(self):
  with patch.object(u.sys.stdin,'isatty',return_value=False),self.assertRaises(u.Hold):self.command('backup')
  self.assertFalse(self.state.exists())

if __name__=='__main__':unittest.main()
