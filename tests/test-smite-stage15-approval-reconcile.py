"""Read-only expired route reconciliation never clears uncertain publication.

This test never calls Nginx or touches an actual broker/FRPS. It proves
the conservative check rejects route/journal/grant/consumed nonce and
does not try to repair or publish.
"""
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/"modules"
spec=importlib.util.spec_from_file_location("root_expired_reconcile",ROOT/"smite-stage15-approval-reconcile.py")
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)


class ReadOnlyInspectTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        ledger=self.root/"var/lib/u-opti/smite-xhttp-broker/nonce.db"
        ledger.parent.mkdir(parents=True)
        with sqlite3.connect(ledger) as c:
            c.execute("CREATE TABLE consumed_nonces(nonce TEXT,request_sha256 TEXT,consumed_at INTEGER)")
        ledger.chmod(0o600)
        (self.root/"etc/nginx/smite-xhttp-routes").mkdir(parents=True)
        (self.root/"etc/u-opti/smite/route-grants").mkdir(parents=True)
        p=patch.object(m,"_root_file",return_value=None)
        p.start();self.addCleanup(p.stop)
        self.binding=dict(owner="owner-0001",child="child-0001",
                          port=38658,path="/38658/shop")
        self.nonce="a"*32

    def check(self):
        return m._read_only_inspect(self.binding,self.nonce,1001,root=self.root)

    def test_unconfirmed_runtime_never_auto_closes(self):
        with self.assertRaisesRegex(m.ReconcileHold,"LIVE_NGINX_VERIFICATION_REQUIRED"):
            self.check()

    def test_existing_grant_makes_closure_ambiguous(self):
        (self.root/"etc/u-opti/smite/route-grants/child-0001.json").write_text("{}")
        with self.assertRaisesRegex(m.ReconcileHold,"ROUTE_OR_TRANSACTION"):
            self.check()

    def test_prepared_or_committed_journal_blocks_closure(self):
        (self.root/"etc/nginx/smite-xhttp-routes/.38658.transaction.json").write_text("{}")
        with self.assertRaisesRegex(m.ReconcileHold,"ROUTE_OR_TRANSACTION"):
            self.check()

    def test_route_file_blocks_closure(self):
        (self.root/"etc/nginx/smite-xhttp-routes/38658.conf").write_text("location /38658/shop {}")
        with self.assertRaisesRegex(m.ReconcileHold,"ROUTE_OR_TRANSACTION"):
            self.check()

    def test_consumed_nonce_always_holds_even_when_route_absent(self):
        ledger=self.root/"var/lib/u-opti/smite-xhttp-broker/nonce.db"
        with sqlite3.connect(ledger) as c:
            c.execute("INSERT INTO consumed_nonces VALUES(?,?,?)",(self.nonce,"b"*64,999))
        with self.assertRaisesRegex(m.ReconcileHold,"NONCE_CONSUMED"):
            self.check()

if __name__=="__main__":
    unittest.main()
