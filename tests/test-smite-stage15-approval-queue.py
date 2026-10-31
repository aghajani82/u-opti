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


    def reconciliation(self, binding, nonce, now, *, route="ABSENT", journal="ABSENT", broker="UNCONSUMED"):
        self.assertEqual(nonce,"1"*32)
        return {"route":route,"journal":journal,"broker_nonce":broker,
                "checked_at":now,
                "binding_sha256":hashlib.sha256(
                    json.dumps(binding,sort_keys=True,separators=(",",":"),
                               ensure_ascii=True).encode("ascii")).hexdigest()}

    def test_expired_unknown_is_never_deleted_or_auto_retried(self):
        digest=self.stage(self.wire())
        self.assertEqual(len(list(self.dir.glob("proposal-*.json"))),1)
        now=self.now+601
        for route,journal,broker in (
            ("UNKNOWN","ABSENT","UNCONSUMED"),
            ("ABSENT","PREPARED","UNCONSUMED"),
            ("ABSENT","ABSENT","CONSUMED"),
            ("PUBLISHED","COMMITTED","CONSUMED"),
        ):
            with self.subTest((route,journal,broker)),self.assertRaises(q.QueueHold):
                q.close_expired_after_reconciliation(directory=self.dir,digest=digest,
                    key=self.key,now=now,root_check=False,
                    read_only_reconciler=lambda b,n:self.reconciliation(
                        b,n,now,route=route,journal=journal,broker=broker))
        self.assertTrue((self.dir/("proposal-"+digest+".json")).exists())
        self.assertEqual(list(self.dir.glob("closed-*.json")),[])

    def test_only_verified_absent_unconsumed_expired_can_close(self):
        digest=self.stage(self.wire())
        now=self.now+601
        receipt=q.close_expired_after_reconciliation(directory=self.dir,
              digest=digest,key=self.key,now=now,root_check=False,
              read_only_reconciler=lambda b,n:self.reconciliation(b,n,now))
        self.assertEqual(receipt["outcome"],"CONFIRMED_NOT_PUBLISHED")
        self.assertTrue((self.dir/("proposal-"+digest+".json")).exists())
        with self.assertRaises(q.QueueHold):self.review(digest,now)
        with self.assertRaises(q.QueueHold):
            q.close_expired_after_reconciliation(directory=self.dir,
                digest=digest,key=self.key,now=now,root_check=False,
                read_only_reconciler=lambda b,n:self.reconciliation(b,n,now))
        # A newly signed fresh intent may stage after independent closure
        self.now+=1000
        replacement=self.wire(nonce="4"*32)
        self.assertNotEqual(self.stage(replacement),digest)
        self.assertEqual(len(list(self.dir.glob("proposal-*.json"))),2)

    def test_unexpired_proposal_cannot_be_closed(self):
        digest=self.stage(self.wire())
        now=self.now+10
        with self.assertRaises(q.QueueHold):
            q.close_expired_after_reconciliation(directory=self.dir,digest=digest,
                key=self.key,now=now,root_check=False,read_only_reconciler=lambda b,n:None)

if __name__=="__main__":unittest.main()
