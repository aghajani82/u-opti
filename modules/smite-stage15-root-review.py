#!/usr/bin/env python3
"""Root-console review of a signed Panel proposal; never execute a route.

The Panel cannot approve itself. The operator reviews the exact node/owner,
port/path and evidence hashes, then authorizes via a root-authenticated TTY.
This removes manual field transcription; it does not make signatures an
approval. Publication still needs a fresh request, root grant and replay gate.
"""
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
ROUTES = Path('/etc/nginx/smite-xhttp-routes')
HISTORY = ROUTES.with_name('smite-xhttp-route-history')
ROUTE_LOCK = Path('/run/lock/smite-xhttp-nginx-route.lock')

def load(name, file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return m


def archive_rolled_back_frp_route(b, port, path):
    """Called under the broker lock after explicit approval of a fresh proposal."""
    journal = ROUTES / f'.{port}.transaction.json'
    if not os.path.lexists(journal):
        return
    b._dir(ROUTES, mode=0o755)
    fd = os.open(ROUTE_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_nlink != 1
                or stat.S_IMODE(meta.st_mode) != 0o600):
            raise b.BrokerHold('UNTRUSTED_ROUTE_LOCK')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw = b._file(journal, mode=0o600, max_size=16384)
        record = b._json(raw, {'state', 'port', 'path', 'snippet'})
        if (record['state'] != 'ROLLED_BACK' or type(record['port']) is not int
                or record['port'] != port or os.path.lexists(ROUTES / f'{port}.conf')):
            raise b.BrokerHold('ROUTE_REUSE_REQUIRES_COMPLETED_ROLLBACK')
        planner = b._load_module('stage15_review_pinned_planner', b.PLANNER)
        plan = planner.plan_xhttp_nginx_route(
            {'port': port, 'path': record['path'], 'network': 'xhttp',
             'protocol': 'vless', 'listen': '127.0.0.1', 'enabled': True},
            registered_routes={}, frps_listener_ports={7000, port})
        if record['snippet'] != plan.snippet:
            raise b.BrokerHold('ROUTE_REUSE_RECEIPT_DRIFT')
        result = b.subprocess.run([str(b.HELPER), '--port', str(port), '--path', path],
                                  capture_output=True, timeout=35, check=False)
        if result.returncode or b'RESULT=PASS_LOCAL_READ_ONLY' not in result.stdout.splitlines():
            raise b.BrokerHold('ROUTE_REUSE_PREFLIGHT_FAILED')
        b._dir(HISTORY.parent, mode=0o755)
        if not os.path.lexists(HISTORY):
            HISTORY.mkdir(mode=0o700)
            b._dir(HISTORY, mode=0o700)
            directory = os.open(HISTORY.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        b._dir(HISTORY, mode=0o700)
        archive = HISTORY / (f'frp-rollback-{port}-' + b.hashlib.sha256(raw).hexdigest() + '.json')
        if os.path.lexists(archive) and b._file(archive, mode=0o600, max_size=16384) != raw:
            raise b.BrokerHold('ROUTE_ARCHIVE_DRIFT')
        os.replace(journal, archive)
        for folder in (HISTORY, ROUTES):
            directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        os.close(fd)


def review():
    b=load('stage15_review_broker','smite-rc5-xhttp-root-broker.py')
    p=load('stage15_review_provision','smite-rc5-xhttp-broker-provision.py')
    if not sys.stdin.isatty() or sys.argv[1:]:
        raise b.BrokerHold('IR_ROOT_TTY_ONLY')
    try:
        b._require_ir_root_role()
    except b.BrokerHold as exc:
        raise b.BrokerHold('IR_ROOT_TTY_ONLY') from exc
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
        print('Tunnel ID: '+facts['child'])
        print('Tunnel name: unavailable in the signed proposal; identify by ID.')
        print('IR node ID: '+facts['ir_node'])
        print('KH node ID: '+facts['kh_node'])
        print('Port: '+str(facts['port']))
        print('Path: '+facts['path'])
        print('Signed request expires at (Unix seconds): '+str(hint['expires_at']))
        print('Full signed binding and evidence hashes:')
        print(json.dumps(facts,sort_keys=True,indent=2))
        print('First compare with current trusted Signed IR owner, Signed KH inbound and active lease.')
        print('1) Approve this exact request   0) Cancel (default)')
        if input('Choose [1/0]: ').strip()!='1':
            raise b.BrokerHold('OPERATOR_CANCELLED')
        contract.admit(wire,key=key,expected=proposal,seen_nonces=frozenset(),now=int(time.time()))
        if b._file(request,mode=0o600)!=wire:
            raise b.BrokerHold('PROPOSAL_CHANGED')
        # Exclusive, durable audit BEFORE grant issuance. Never overwrite.
        audit=b.LEDGER.parent/('approval-'+digest+'.json')
        p._write_new(audit,(json.dumps({'request_sha256':digest,'approved_at':int(time.time()),
            'uid':os.geteuid(),'facts':facts},sort_keys=True)+'\n').encode(),0o600)
        archive_rolled_back_frp_route(b, facts['port'], facts['path'])
        p.install_grant(facts,confirmed_child=facts['child'])
        request.unlink()
        print('ROOT_GRANT_APPROVED; ROUTE_NOT_CHANGED; submit a fresh Panel request.')

if __name__=='__main__':
    try: review()
    except Exception:
        print('HOLD_ROOT_REVIEW_REQUIRED',file=sys.stderr);raise SystemExit(2)
