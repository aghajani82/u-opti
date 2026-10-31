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

    def test_two_independent_passkeys_survive_reopen_and_single_revocation(self):
        """Offline simulated registrations, NOT physical WebAuthn validation.

        Primary and spare use independent one-time root tickets; revoking
        one credential must not disable its distinct enrolled backup.
        """
        from fido2.server import Fido2Server
        import hashlib

        class FakeCredential:
            def __init__(self, name):
                self.credential_id=name.encode("ascii")
            def __bytes__(self):
                # This test does not claim the bytes are real FIDO2 data.
                return b"simulated-credential-"+self.credential_id

        class FakeAuthentication:
            def __init__(self, name):
                self.credential_data=FakeCredential(name)
                self.counter=1
            def is_user_verified(self):
                return True

        names=("primary-physical-key-sim","spare-physical-key-sim")
        hashes=[]
        for name in names:
            token=self.store.ticket(root_tty=True)
            # Existing simulated bytes are intentionally NOT valid
            # AttestedCredentialData. Mock only that parsing boundary;
            # real hardware FIDO2 parsing still needs a separate E2E test.
            with patch("fido2.webauthn.AttestedCredentialData",
                       side_effect=lambda raw: SimpleNamespace(credential_id=bytes(raw))), \
                 patch.object(Fido2Server,"register_begin",
                       return_value=({"publicKey":{"challenge":"offline-only"}},
                                     {"challenge":"offline-only"})):
                beginning=self.store.enroll_begin(
                    token,origin="https://review.example.invalid")
            with patch.object(Fido2Server,"register_complete",
                              return_value=FakeAuthentication(name)):
                self.store.enroll_complete(
                    beginning["ceremony"],{"id":"offline-fixture"},
                    token,origin="https://review.example.invalid")
            # Ticket status is independent from mock FIDO2 parsing.
            with self.assertRaises(en.EnrollmentHold):
                self.store._ticket(token,now=int(time.time()))
            hashes.append(hashlib.sha256(name.encode("ascii")).hexdigest())

        self.assertNotEqual(hashes[0],hashes[1])
        self.assertEqual(len(self.store.encoded()),2)
        self.store.close()
        reopened=en.CredentialStore(self.db,root_check=False)
        self.addCleanup(reopened.close)
        self.assertEqual(len(reopened.encoded()),2)
        reopened.revoke(hashes[0],root_tty=True)
        self.assertEqual(len(reopened.encoded()),1)
        self.assertEqual(
            reopened.conn.execute("SELECT revoked FROM credentials WHERE id_hash=?",
                                  (hashes[1],)).fetchone(), (0,))
        with self.assertRaises(en.EnrollmentHold):
            reopened.revoke(hashes[0],root_tty=True)
        with self.assertRaisesRegex(en.EnrollmentHold,"LAST_PASSKEY_RECOVERY_REQUIRED"):
            reopened.revoke(hashes[1],root_tty=True)

    def test_failed_second_registration_does_not_consume_existing_spare(self):
        """Invalid UV leaves prior credential intact and does not grant."""
        from fido2.server import Fido2Server
        class FakeCredential:
            credential_id=b"primary-test"
            def __bytes__(self):
                return b"simulated-primary"
        class Verified:
            credential_data=FakeCredential()
            counter=0
            def is_user_verified(self):
                return True
        class NotVerified:
            credential_data=FakeCredential()
            counter=0
            def is_user_verified(self):
                return False
        primary=self.store.ticket(root_tty=True)
        first=self.store.enroll_begin(primary,
            origin="https://review.example.invalid")
        with patch.object(Fido2Server,"register_complete",return_value=Verified()):
            self.store.enroll_complete(first["ceremony"],{"id":"offline"},
                primary,origin="https://review.example.invalid")
        backup=self.store.ticket(root_tty=True)
        with patch("fido2.webauthn.AttestedCredentialData",
                   side_effect=lambda raw: SimpleNamespace(credential_id=bytes(raw))), \
             patch.object(Fido2Server,"register_begin",
                   return_value=({"publicKey":{"challenge":"offline-only"}},
                                 {"challenge":"offline-only"})):
            second=self.store.enroll_begin(backup,
                origin="https://review.example.invalid")
        with patch.object(Fido2Server,"register_complete",return_value=NotVerified()):
            with self.assertRaises(en.EnrollmentHold):
                self.store.enroll_complete(second["ceremony"],{"id":"offline"},
                    backup,origin="https://review.example.invalid")
        self.assertEqual(len(self.store.encoded()),1)
        self.assertEqual(
            self.store.conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0],
            1,
        )

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

    def test_revocation_requires_root_tty_and_a_distinct_backup(self):
        primary="b"*64
        backup="c"*64
        self.store.conn.execute("INSERT INTO credentials VALUES(?,?,?, ?,?,0)",
                                (primary,b"opaque-primary",0,"primary",1000))
        with self.assertRaisesRegex(en.EnrollmentHold,"REVOCATION_REQUIRES_ROOT_TTY"):
            self.store.revoke(primary,root_tty=False)
        with self.assertRaisesRegex(en.EnrollmentHold,"LAST_PASSKEY_RECOVERY_REQUIRED"):
            self.store.revoke(primary,root_tty=True)
        self.assertEqual(len(self.store.encoded()),1)
        self.assertEqual(
            self.store.conn.execute("SELECT COUNT(*) FROM audit WHERE event='PASSKEY_REVOKED'").fetchone()[0],
            0,
        )
        self.store.conn.execute("INSERT INTO credentials VALUES(?,?,?, ?,?,0)",
                                (backup,b"opaque-backup",0,"backup",1000))
        self.store.revoke(primary,root_tty=True)
        self.assertEqual(len(self.store.encoded()),1)
        with self.assertRaisesRegex(en.EnrollmentHold,"LAST_PASSKEY_RECOVERY_REQUIRED"):
            self.store.revoke(backup,root_tty=True)
        with self.assertRaisesRegex(en.EnrollmentHold,"CREDENTIAL_NOT_ACTIVE"):
            self.store.revoke(primary,root_tty=True)
        self.assertEqual(
            self.store.conn.execute("SELECT COUNT(*) FROM audit WHERE event='PASSKEY_REVOKED'").fetchone()[0],
            1,
        )

    def test_last_passkey_guard_survives_database_reopen(self):
        h="d"*64
        self.store.conn.execute("INSERT INTO credentials VALUES(?,?,?, ?,?,0)",
                                (h,b"opaque-final",0,"last",1000))
        self.store.close()
        reopened=en.CredentialStore(self.db,root_check=False)
        self.addCleanup(reopened.close)
        with self.assertRaisesRegex(en.EnrollmentHold,"LAST_PASSKEY_RECOVERY_REQUIRED"):
            reopened.revoke(h,root_tty=True)
        self.assertEqual(reopened.conn.execute(
            "SELECT revoked FROM credentials WHERE id_hash=?",(h,)).fetchone(),(0,))

    def test_pending_recovery_ticket_is_not_an_enrolled_backup(self):
        h="e"*64
        self.store.conn.execute("INSERT INTO credentials VALUES(?,?,?, ?,?,0)",
                                (h,b"opaque-primary",0,"primary",1000))
        unused_ticket=self.store.ticket(root_tty=True)
        self.assertTrue(unused_ticket)
        with self.assertRaisesRegex(en.EnrollmentHold,"LAST_PASSKEY_RECOVERY_REQUIRED"):
            self.store.revoke(h,root_tty=True)
        self.assertEqual(len(self.store.encoded()),1)

    def test_unknown_or_already_revoked_passkey_stays_blocked(self):
        h="f"*64
        self.store.conn.execute("INSERT INTO credentials VALUES(?,?,?, ?,?,1)",
                                (h,b"opaque-revoked",0,"revoked",1000))
        with self.assertRaisesRegex(en.EnrollmentHold,"CREDENTIAL_NOT_ACTIVE"):
            self.store.revoke(h,root_tty=True)
        with self.assertRaisesRegex(en.EnrollmentHold,"CREDENTIAL_NOT_ACTIVE"):
            self.store.revoke("0"*64,root_tty=True)


if __name__=="__main__":
    unittest.main()
