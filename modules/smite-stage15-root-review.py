#!/usr/bin/env python3
"""Root-console review of a signed Panel proposal; never execute a route.

The Panel cannot approve itself. The operator reviews the exact node/owner,
port/path and evidence hashes, then authorizes via a root-authenticated TTY.
This removes manual field transcription; it does not make signatures an
approval. Publication still needs a fresh request, root grant and replay gate.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent

def load(name, file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return m


def review():
    b=load('stage15_review_broker','smite-rc5-xhttp-root-broker.py')
    p=load('stage15_review_provision','smite-rc5-xhttp-broker-provision.py')
    if (os.geteuid()!=0 or os.uname().nodename.split('.')[0].lower()!='ir'
            or not sys.stdin.isatty() or sys.argv[1:]):
        raise b.BrokerHold('IR_ROOT_TTY_ONLY')
    with b._lock():
        config=b._configuration(); b._verify_helper(config); b._verify_bridge()
        b._dir(b.LEDGER.parent,mode=0o700)
        request=b.LEDGER.parent/'approval-request.json'
        wire=b._file(request,mode=0o600)
        contract=b._contract_module()
        hint=b._json(wire,set(contract.WIRE_FIELDS))
        key=b._file(b.KEY,mode=0o600,max_size=32)
        facts={k:hint[k] for k in contract.TrustedGrant.__dataclass_fields__}
        proposal=contract.TrustedGrant(**facts)
        contract.admit(wire,key=key,expected=proposal,seen_nonces=frozenset(),now=int(time.time()))
        digest=b.hashlib.sha256(wire).hexdigest()
        print('SIGNED PANEL PROPOSAL — review against trusted IR/KH evidence.')
        print('Role: '+('DIRECT OWNER' if facts['owner']==facts['child'] else 'SHARED CHILD'))
        print(json.dumps(facts,sort_keys=True,indent=2))
        if input('Type APPROVE '+digest+': ').strip()!='APPROVE '+digest:
            raise b.BrokerHold('OPERATOR_CANCELLED')
        contract.admit(wire,key=key,expected=proposal,seen_nonces=frozenset(),now=int(time.time()))
        if b._file(request,mode=0o600)!=wire:
            raise b.BrokerHold('PROPOSAL_CHANGED')
        # Exclusive, durable audit BEFORE grant issuance. Never overwrite.
        audit=b.LEDGER.parent/('approval-'+digest+'.json')
        p._write_new(audit,(json.dumps({'request_sha256':digest,'approved_at':int(time.time()),
            'uid':os.geteuid(),'facts':facts},sort_keys=True)+'\n').encode(),0o600)
        p.install_grant(facts,confirmed_child=facts['child'])
        request.unlink()
        print('ROOT_GRANT_APPROVED; ROUTE_NOT_CHANGED; submit a fresh Panel request.')

if __name__=='__main__':
    try: review()
    except Exception:
        print('HOLD_ROOT_REVIEW_REQUIRED',file=sys.stderr);raise SystemExit(2)
