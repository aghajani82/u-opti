"""Web approval marker is root-only and defaults to original console path."""
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/"modules"
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod
broker=load("web_optin_broker_test","smite-rc5-xhttp-root-broker.py")
contract=load("web_optin_contract_test","smite-rc5-xhttp-signed-intent.py")

class BrokerOptInTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.dir=Path(t.name);self.dir.chmod(0o700)
        self.marker=self.dir/"web-approval-mode.json"
        self.key=b"k"*32
        now=int(time.time())
        body={"schema":1,"audience":contract.AUDIENCE,"action":"create",
             "ir_node":"node-ir-0001","kh_node":"node-kh-0001",
             "owner":"owner-0001","child":"child-0001","lease":"child-0001",
             "port":38658,"path":"/38658/shop",
             "owner_proof_sha256":"a"*64,"kh_inventory_sha256":"b"*64,
             "issued_at":now,"expires_at":now+30,"nonce":"c"*32}
        self.wire=contract.canonical({**body,"mac":hmac.new(self.key,
              contract.canonical(body),hashlib.sha256).hexdigest()})
        self.hint=json.loads(self.wire)
        self.record=[]
        class Queue:
            def stage(_this,**kwargs):self.record.append(("queue",kwargs["wire"]))
        class Legacy:
            def replace_file(_this,path,wire,mode):self.record.append(("legacy",wire))
        def loader(name,path):
            return Queue() if "independent_queue" in name else Legacy()
        for target,value in (
            ("WEB_MODE_MARKER",self.marker),("WEB_QUEUE_DIR",self.dir/"queue")):
            p=patch.object(broker,target,value);p.start();self.addCleanup(p.stop)
        p=patch.object(broker,"_dir");p.start();self.addCleanup(p.stop)
        p=patch.object(broker,"_contract_module",return_value=contract)
        p.start();self.addCleanup(p.stop)
        p=patch.object(broker,"_load_module",side_effect=loader)
        p.start();self.addCleanup(p.stop)
        p=patch.object(broker,"_file",side_effect=lambda path,mode,max_size=4096:path.read_bytes())
        p.start();self.addCleanup(p.stop)

    def test_opt_in_queue_no_legacy_overwrite(self):
        self.marker.write_text(json.dumps({"schema":1,"enabled":True,
                       "queue_dir":str(self.dir/"queue")}))
        broker.stage_approval_request(self.wire,self.key,self.hint)
        self.assertEqual(self.record,[("queue",self.wire)])

    def test_absent_marker_keeps_legacy_root_review(self):
        broker.stage_approval_request(self.wire,self.key,self.hint)
        self.assertEqual(self.record,[("legacy",self.wire)])

    def test_corrupt_marker_holds_closed(self):
        self.marker.write_text('{"schema":1,"enabled":false,"queue_dir":"/wrong"}')
        with self.assertRaises(broker.BrokerHold):
            broker.stage_approval_request(self.wire,self.key,self.hint)
        self.assertEqual(self.record,[])

if __name__=="__main__":
    unittest.main()
