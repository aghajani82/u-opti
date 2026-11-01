#!/usr/bin/env python3
"""CI-only disposable Panel static-serving fixture. Never use live container names."""
import hashlib,json,os,pathlib,subprocess,sys,tempfile,zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
name='uopti-ui-lab-'+str(os.getpid())
def docker(*args,input=None):
 return subprocess.check_output(['docker',*args],input=input)
with tempfile.TemporaryDirectory() as tmp:
 p=pathlib.Path(tmp);repo=pathlib.Path(sys.argv[1]);bundle=pathlib.Path(sys.argv[2])
 import shutil
 shutil.copytree(repo/'panel/app',p/'app');shutil.copy(repo/'panel/main.py',p/'main.py')
 (p/'static/assets').mkdir(parents=True);(p/'static/index.html').write_text('OLD UI');(p/'static/assets/old.js').write_text('OLD ASSET')
 with zipfile.ZipFile(bundle) as z:
  m=json.loads(z.read('manifest.json'));source=z.read('ui-trial.py').decode()
  import base64
  new={n[7:]:base64.b64encode(z.read(n)).decode() for n in m['files_sha256'] if n.startswith('static/')}
 try:
  docker('run','-d','--name',name,'--network','none','python:3.11-alpine','python3','-m','http.server','8765','--bind','127.0.0.1','--directory','/app/static')
  docker('cp',str(p)+'/.',name+':/app')
  # Docker cp preserves runner checkout modes; normalize ONLY this disposable fixture.
  docker('exec',name,'python3','-c',"import os,pathlib; r=pathlib.Path('/app'); paths=[r,*r.rglob('*')]; [(os.chown(p,0,0),os.chmod(p,0o755 if p.is_dir() else 0o644)) for p in paths]")
  before=json.loads(docker('inspect',name))[0]
  def worker(action,**kw):
   payload=json.dumps(dict(action=action,backend=m['backend_sha256'],**kw)).encode()
   return json.loads(docker('exec','-i',name,'python3','-c',source,'--container-worker',input=payload))
  def get(path):return docker('exec',name,'python3','-c',"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8765/"+path+"').read().decode())")
  old=worker('snapshot');assert get('index.html').strip()==b'OLD UI'
  worker('apply',old=old,new=new);worker('verify',old=old,new=new)
  assert hashlib.sha256(get('index.html')[:-1]).hexdigest()==m['files_sha256']['static/index.html']
  assert get('assets/old.js').strip()==b'OLD ASSET'
  worker('rollback',old=old,new=new);assert get('index.html').strip()==b'OLD UI'
  after=json.loads(docker('inspect',name))[0]
  assert all(before[k]==after[k] for k in ('Id','Image','RestartCount'))
  assert before['State']['Pid']==after['State']['Pid'] and before['State']['StartedAt']==after['State']['StartedAt']
  print('PASS: Docker worker, HTTP old/new/rollback, old assets, unchanged serving process; fixture only')
 finally:docker('rm','-f',name)
