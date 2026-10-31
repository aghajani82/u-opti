"""Isolated one-time root ticket and Passkey vault lifecycle tests."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/"modules"
spec=importlib.util.spec_from_file_location("enrollment_unit",ROOT/"smite-stage15-passkey-enrollment.py")
en=importlib.util.module_from_spec(spec);sys.modules[spec.name]=en;spec.loader.exec_module(en)

class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        self.db=root/"credentials.db"
        with sqlite3.connect(self.db) as c:c.executescript(en.SCHEMA)
        self.db.chmod(0o600)
        self.store=en.CredentialStore(self.db,root_check=False)
        self.addCleanup(self.store.close)
        p=patch.object(os,"geteuid",return_value=0)
        p.start();self.addCleanup(p.stop)

    def test_ticket_only_local_root_tty(self):
        with self.assertRaises(en.EnrollmentHold):
            self.store.ticket(root_tty=False)
        ticket=self.store.ticket(root_tty=True,now=1000)
        self.assertNotIn(ticket,str(list(self.store.conn.execute("SELECT * FROM enrollment_tickets"))))
        self.assertEqual(len(ticket)>35,True)
        with self.assertRaises(en.EnrollmentHold):self.store._ticket(ticket,now=2000)

    def test_passkey_enroll_begin_is_web_uv_required(self):
        now=int(time.time())
        token=self.store.ticket(root_tty=True,now=now)
        started=self.store.enroll_begin(token,origin="https://review.example.invalid",now=now)
        self.assertIn("publicKey",started["options"])
        self.assertTrue(started["ceremony"])
        self.assertIn("challenge",started["options"]["publicKey"])
        with self.assertRaises(en.EnrollmentHold):
            self.store.enroll_begin("invalid",origin="https://review.example.invalid",now=now)

    def test_completed_registration_consumes_only_root_ticket_once(self):
        from fido2.server import Fido2Server
        class FakeCredential:
            credential_id=b"physical-key-simulator"
            def __bytes__(self):return b"root-test-credential-opaque"
        class FakeAuthentication:
            credential_data=FakeCredential()
            counter=1
            def is_user_verified(self):return True
        token=self.store.ticket(root_tty=True)
        begin=self.store.enroll_begin(token,origin="https://review.example.invalid")
        with patch.object(Fido2Server,"register_complete",return_value=FakeAuthentication()):
            self.store.enroll_complete(begin["ceremony"],{"id":"synthetic"},token,
                origin="https://review.example.invalid")
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0],1)
        with self.assertRaises(en.EnrollmentHold):
            self.store.enroll_begin(token,origin="https://review.example.invalid")
        with self.assertRaises(en.EnrollmentHold):
            self.store.enroll_complete(begin["ceremony"],{},token,
                origin="https://review.example.invalid")

    def test_registration_without_uv_stays_holding(self):
        from fido2.server import Fido2Server
        class FakeAuthentication:
            credential_data=object()
            counter=0
            def is_user_verified(self):return False
        token=self.store.ticket(root_tty=True)
        begin=self.store.enroll_begin(token,origin="https://review.example.invalid")
        with patch.object(Fido2Server,"register_complete",return_value=FakeAuthentication()):
            with self.assertRaises(en.EnrollmentHold):
                self.store.enroll_complete(begin["ceremony"],{},token,
                    origin="https://review.example.invalid")
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0],0)

    def test_ticket_survives_process_reopen(self):
        token=self.store.ticket(root_tty=True)
        self.store.close()
        new=en.CredentialStore(self.db,root_check=False)
        self.addCleanup(new.close)
        self.assertTrue(new._ticket(token,int(time.time())))

    def test_stale_or_spent_registration_holds(self):
        now=int(time.time())
        token=self.store.ticket(root_tty=True,now=now)
        started=self.store.enroll_begin(token,origin="https://review.example.invalid",now=now)
        with self.assertRaises(en.EnrollmentHold):
            self.store.enroll_complete(started["ceremony"],{},token,
                origin="https://review.example.invalid",now=now+200)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0],0)

    def test_revocation_requires_local_root_and_is_durable(self):
        h="b"*64
        self.store.conn.execute("INSERT INTO credentials VALUES(?,?,?, ?,?,0)",
                                (h,b"opaque-credential",0,"spare",1000))
        with self.assertRaises(en.EnrollmentHold):self.store.revoke(h,root_tty=False)
        self.store.revoke(h,root_tty=True)
        self.assertEqual(self.store.encoded(),[])
        with self.assertRaises(en.EnrollmentHold):self.store.revoke(h,root_tty=True)

if __name__=="__main__":
    unittest.main()
