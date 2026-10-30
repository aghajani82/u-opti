"""Offline immutable root review queue tests (no live broker, no network)."""
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1] / "modules"
def load(name, file):
    spec=importlib.util.spec_from_file_location(name, ROOT/file)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module

q=load("independent_queue_test","smite-stage15-approval-queue.py")
c=load("independent_contract_test","smite-rc5-xhttp-signed-intent.py")

class QueueTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.dir=Path(tmp.name);self.dir.chmod(0o700)
        self.key=b"k"*32
        self.facts={
            "ir_node":"node-ir-0001", "kh_node":"node-kh-0001",
            "owner":"owner-0001","child":"child-0001","lease":"child-0001",
            "port":38658,"path":"/38658/shop","owner_proof_sha256":"a"*64,
            "kh_inventory_sha256":"b"*64,
        }
        self.now=1000

    def wire(self, **changes):
        body={"schema":1,"audience":c.AUDIENCE,"action":"create",
              **self.facts,"issued_at":self.now,"expires_at":self.now+30,
              "nonce":"1"*32, **changes}
        sig=hmac.new(self.key,c.canonical(body),hashlib.sha256).hexdigest()
        return c.canonical({**body,"mac":sig})

    def stage(self,wire):
        return q.stage(directory=self.dir,wire=wire,key=self.key,now=self.now,root_check=False)

    def review(self,digest,now):
        return q.review(directory=self.dir,digest=digest,key=self.key,now=now,root_check=False)

    def test_review_after_30s_expiry_is_not_publication(self):
        digest=self.stage(self.wire())
        self.assertEqual(self.review(digest,self.now+100),self.facts)

    def test_short_lived_intent_must_be_current_when_staged(self):
        with self.assertRaises(q.QueueHold):
            q.stage(directory=self.dir,wire=self.wire(),key=self.key,now=self.now+31,root_check=False)

    def test_stale_review_requires_new_evidence(self):
        digest=self.stage(self.wire())
        with self.assertRaises(q.QueueHold):self.review(digest,self.now+601)

    def test_same_child_conflicting_concurrent_proposal_holds(self):
        self.stage(self.wire())
        with self.assertRaisesRegex(q.QueueHold,"CONCURRENT_CHILD"):
            self.stage(self.wire(nonce="2"*32))

    def test_distinct_child_can_stage_under_same_root(self):
        self.stage(self.wire())
        self.stage(self.wire(child="child-0002",lease="child-0002",nonce="3"*32))
        self.assertEqual(len(list(self.dir.glob("proposal-*.json"))),2)

    def test_changed_payload_fails_signature(self):
        body=json.loads(self.wire())
        body["path"]="/wrong/path"
        with self.assertRaises(q.QueueHold):
            self.stage(c.canonical(body))

    def test_digest_mismatch_rejected(self):
        digest=self.stage(self.wire())
        with self.assertRaises(Exception): self.review("c"*64,self.now+1)

    def test_invalid_directory_permissions_rejected(self):
        self.dir.chmod(0o755)
        with self.assertRaisesRegex(q.QueueHold,"UNTRUSTED_PENDING_DIRECTORY"):
            self.stage(self.wire())

if __name__=="__main__":unittest.main()
