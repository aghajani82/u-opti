"""Run against a separately checked out, exact Smite source revision."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
SMITE=Path(sys.argv.pop(1)).resolve()

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return m

issuer=load('cross_issuer',SMITE/'panel/app/xhttp_route_intent.py')
admitter=load('cross_admitter',ROOT/'modules/smite-rc5-xhttp-signed-intent.py')

class CrossRepoTests(unittest.TestCase):
    def test_worker_and_planner_are_byte_identical(self):
        for a,b in [('smite-xhttp-nginx-route','smite_xhttp_nginx_transaction.py'),('smite_xhttp_nginx_plan.py','smite_xhttp_nginx_plan.py')]:
            self.assertEqual((ROOT/'modules'/a).read_bytes(),(SMITE/'scripts'/b).read_bytes())

    def test_direct_owner_and_child_canonical_signed_contract(self):
        for subject in ('owner-0001','child-0001'):
            facts=dict(ir_node='ir-node-0001',kh_node='kh-node-0001',owner='owner-0001',child=subject,
                       lease=subject,port=45121,path='/custom/connect',owner_proof_sha256='a'*64,kh_inventory_sha256='b'*64)
            wire=issuer.sign_route_intent(issuer.ApprovedRouteBinding(**facts),dedicated_broker_key=b'k'*32,now=1000)
            approved=admitter.admit(wire,key=b'k'*32,expected=admitter.TrustedGrant(**facts),seen_nonces=frozenset(),now=1001)
            self.assertEqual(approved.path,facts['path'])
            with self.assertRaises(admitter.IntentHold):
                admitter.admit(wire,key=b'k'*32,expected=admitter.TrustedGrant(**facts),seen_nonces=frozenset({approved.nonce}),now=1001)
            with self.assertRaises(admitter.IntentHold):
                admitter.admit(wire,key=b'x'*32,expected=admitter.TrustedGrant(**facts),seen_nonces=frozenset(),now=1001)
            changed=dict(facts,path='/other/path')
            with self.assertRaises(admitter.IntentHold):
                admitter.admit(wire,key=b'k'*32,expected=admitter.TrustedGrant(**changed),seen_nonces=frozenset(),now=1001)

if __name__=='__main__': unittest.main()
