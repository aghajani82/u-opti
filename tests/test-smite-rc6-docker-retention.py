#!/usr/bin/env python3
"""Disposable CI Docker ownership/volume-retention test; no host ports."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('j', root/'modules/smite-rc6-install-journal.py')
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as tmp:
    j=m.Journal(Path(tmp));j.folder.mkdir(parents=True,mode=0o700)
    tx=j.begin('foreign');volume=tx+'_retention';cid=None
    try:
        p=j.root/'opt/smite-node';p.mkdir(parents=True);(p/'.env').write_text('retained\n')
        j.docker('volume','create',volume)
        cid=j.docker('run','-d','--network','none','--name','smite-node',
                     '--label','com.docker.compose.project='+tx,
                     '--env','SMITE_NODE_PANEL_AUTH_MODE=paused',
                     '--restart','unless-stopped','--mount','type=volume,source='+volume+',target=/evidence',
                     '--entrypoint','python',m.IMAGES['smite-node'],'-c',
                     "from pathlib import Path; import time; Path('/evidence/replay-proof').write_text('preserved'); time.sleep(300)").strip()
        for _ in range(20):
            r=subprocess.run(['docker','--host','unix:///var/run/docker.sock','exec',cid,'test','-f','/evidence/replay-proof'])
            if r.returncode==0: break
            time.sleep(0.2)
        else: raise AssertionError('fixture not ready')
        assert 'PASS' in j.rollback()
        obj=json.loads(j.docker('inspect',cid))[0]
        assert not obj['State']['Running']
        assert obj['HostConfig']['RestartPolicy']['Name']=='no'
        assert obj['Name']=='/smite-node-'+tx
        assert json.loads(j.docker('volume','inspect',volume))[0]['Name']==volume
        out=j.docker('run','--rm','--network','none','--mount','type=volume,source='+volume+',target=/evidence,readonly',
                     '--entrypoint','python',m.IMAGES['smite-node'],'-c',
                     "from pathlib import Path; print(Path('/evidence/replay-proof').read_text())")
        assert out.strip()=='preserved'
        print('RC6_REAL_DOCKER_ROLLBACK_RETAINED_CONTAINER_AND_VOLUME=PASS')
        print('REAL_VPS_INSTALLATION=NOT_TESTED')
    finally:
        if cid: j.docker('rm','-f',cid)
        j.docker('volume','rm',volume)
