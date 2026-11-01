#!/usr/bin/env python3
"""Package an exact already-built static frontend; no image/runtime mutation."""
import hashlib,json,os,pathlib,subprocess,sys,zipfile
SOURCE='3969855298ce7e63ea8a3f7824a0ae20aea09b2c'
def main():
    repo,out=map(pathlib.Path,sys.argv[1:])
    def git(*args):return subprocess.check_output(['git','-C',str(repo),*args]).decode().strip()
    if git('rev-parse','HEAD')!=SOURCE or git('status','--porcelain','--','frontend','panel'):
        raise ValueError('Exact clean Smite source required')
    # Rebuild instead of trusting a pre-existing dist directory. No local dotenv overrides.
    if list((repo/'frontend').glob('.env*')):raise ValueError('Local dotenv files forbidden')
    env={k:v for k,v in os.environ.items() if not k.startswith('VITE_')}
    env['VITE_STAGE15_APPROVAL_ORIGIN']=''
    subprocess.run(['npm','ci','--ignore-scripts','--no-audit','--no-fund'],cwd=repo/'frontend',env=env,check=True)
    subprocess.run(['npm','run','build'],cwd=repo/'frontend',env=env,check=True)
    files={}
    for p in sorted((repo/'frontend/dist').rglob('*')):
        if p.is_file():files['static/'+p.relative_to(repo/'frontend/dist').as_posix()]=p.read_bytes()
    if 'static/index.html' not in files or any(not(n=='static/index.html' or n.startswith('static/assets/')) for n in files):
        raise ValueError('Unexpected frontend build')
    # The build command must explicitly disable the optional approval origin.
    if any(b'https://approve.' in x for x in files.values()):raise ValueError('Approval origin enabled')
    root=pathlib.Path(__file__).resolve().parents[1]
    files['ui-trial.py']=(root/'modules/smite-stage15-ui-trial.py').read_bytes()
    files['README.md']=(root/'docs/SMITE-STAGE15-UI-TRIAL.md').read_bytes()
    h=lambda x:hashlib.sha256(x).hexdigest()
    backend={p.relative_to(repo/'panel').as_posix():h(p.read_bytes()) for p in (repo/'panel/app').rglob('*.py')}
    backend['main.py']=h((repo/'panel/main.py').read_bytes())
    m=dict(schema=1,source_repo='aghajani82/Smite',source_commit=SOURCE,
           web_approval_enabled=False,activation_allowed=False,scope='static frontend only',
           backend_sha256=backend,files_sha256={n:h(b) for n,b in files.items()},
           lockfile_sha256=h((repo/'frontend/package-lock.json').read_bytes()),
           build_command="VITE_STAGE15_APPROVAL_ORIGIN='' npm run build")
    files['manifest.json']=(json.dumps(m,sort_keys=True,indent=2)+'\n').encode()
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n,b in sorted(files.items()):
            i=zipfile.ZipInfo(n,(2026,11,1,0,0,0));i.external_attr=0o100644<<16;i.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(i,b)
    sha=h(out.read_bytes());out.with_suffix('.sha256').write_text(sha+'  '+out.name+'\n')
    print(sha+'  '+out.name)
if __name__=='__main__':main()
