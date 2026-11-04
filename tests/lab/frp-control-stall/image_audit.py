#!/usr/bin/env python3
"""Inspect pinned RC7 image binaries with entrypoint overridden; network none."""
import json,subprocess,pathlib
pins={'node':'03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263',
      'panel':'180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8'}
rows=json.loads(pathlib.Path('evidence/official-binary-hashes.json').read_text())
expected=next(r['binaries'] for r in rows if r['version']=='0.71.0' and r['arch']=='amd64')
result={}
for role,digest in pins.items():
    image=f'ghcr.io/aghajani82/smite-{role}@sha256:{digest}'
    subprocess.run(['docker','pull',image],check=True)
    binaries=['frpc','frps'] if role=='node' else ['frps']
    raw=subprocess.check_output(['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
                                 '--security-opt','no-new-privileges','--entrypoint','sha256sum',image,
                                 *['/usr/local/bin/'+b for b in binaries]],text=True)
    got={line.split()[1].rsplit('/',1)[1]:line.split()[0] for line in raw.splitlines()}
    assert got=={b:expected[b] for b in binaries},'PINNED_IMAGE_BINARY_DIFFERS_FROM_RELEASE'
    result[role]={'image':image,'sha256':got,'matches_official_0710':True}
pathlib.Path('evidence/rc7-image-binaries.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
