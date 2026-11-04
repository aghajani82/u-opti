#!/usr/bin/env python3
"""Disposable CI runner only: actual container and Docker daemon restart.

This does not claim a VM power-cycle test. Never run on a production host.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

if os.environ.get('UOPTI_DISPOSABLE_DOCKER_LAB') != 'YES':
    raise SystemExit('HOLD: DISPOSABLE_DOCKER_LAB_REQUIRED')
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rt',root/'modules/smite-rc7-wss-runtime.py')
rt=importlib.util.module_from_spec(spec);spec.loader.exec_module(rt)
def run(*args):return subprocess.check_output(args,text=True).strip()
def inspect():return json.loads(run('docker','inspect','uopti-wss-dns-lab'))[0]
try:
    # No network, published ports, host binds, secrets, Smite or FRP services.
    run('docker','run','-d','--name','uopti-wss-dns-lab','--network','none',
        '--restart','unless-stopped','alpine:3.21','sleep','600')
    before=inspect(); identity=before['Id']
    baseline={'signature':rt.runtime_signature(before),'signature_policy':rt.DNS_EMPTY_POLICY}
    for phase in ('container-restart','daemon-restart'):
        if phase=='container-restart':run('docker','restart','uopti-wss-dns-lab')
        else:run('sudo','systemctl','restart','docker')
        after=inspect()
        assert after['Id']==identity, 'CONTAINER_RECREATED'
        rt.check_runtime_signature(after,baseline)
        print(phase+': PASS; original signature retained; same container ID')
        print('DNS_EMPTY_TYPES='+json.dumps({k:type(after['HostConfig'][k]).__name__
                                           for k in rt.DNS_EMPTY_FIELDS}))
finally:
    subprocess.run(['docker','rm','-f','uopti-wss-dns-lab'],check=False)
