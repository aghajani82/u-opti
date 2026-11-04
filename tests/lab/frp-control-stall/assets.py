#!/usr/bin/env python3
"""Release-byte audit. Only reviewed HTTPS asset URLs; never install live."""
import hashlib,json,pathlib,subprocess,tarfile,urllib.request
PINS={
 '0.71.0':{'amd64':'84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716','arm64':'f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266'},
 '0.71.1':{'amd64':'1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803','arm64':'8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019'}}
def verified(raw,pin):
    if hashlib.sha256(raw).hexdigest()!=pin:raise ValueError('ARCHIVE_SHA256_MISMATCH')
    return raw
out=pathlib.Path('evidence');out.mkdir(exist_ok=True)
rows=[]
for version,arches in PINS.items():
 for arch,pin in arches.items():
    name=f'frp_{version}_linux_{arch}'
    archive=out/(name+'.tar.gz')
    subprocess.run(['curl','-fLsS','--proto','=https','--proto-redir','=https','--retry','3',
                    '--connect-timeout','15','--max-time','180',
                    f'https://github.com/fatedier/frp/releases/download/v{version}/{name}.tar.gz','-o',str(archive)],check=True)
    raw=archive.read_bytes();verified(raw,pin)
    try:verified(raw+b'tampered',pin)
    except ValueError:pass
    else:raise AssertionError('CORRUPT_ARCHIVE_ACCEPTED')
    destination=out/version/arch;destination.mkdir(parents=True,exist_ok=True)
    row={'version':version,'arch':arch,'archive_sha256':pin,'binaries':{}}
    with tarfile.open(archive,'r:gz') as tf:
      for role in ('frpc','frps'):
        members=[m for m in tf.getmembers() if m.name==name+'/'+role]
        assert len(members)==1 and members[0].isfile() and 0<members[0].size<48*1024*1024
        data=tf.extractfile(members[0]).read()
        assert data[:4]==b'\x7fELF' and int.from_bytes(data[18:20],'little')=={'amd64':62,'arm64':183}[arch]
        target=destination/role;target.write_bytes(data);target.chmod(0o755)
        row['binaries'][role]=hashlib.sha256(data).hexdigest()
        if arch=='amd64':
          assert subprocess.check_output([str(target),'--version'],text=True).strip()==version
          (destination/(role+'.buildinfo.txt')).write_text(subprocess.check_output(['go','version','-m',str(target)],text=True))
    rows.append(row)
(out/'official-binary-hashes.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
print('CORRUPT_ARCHIVE_NEGATIVE=PASS')
