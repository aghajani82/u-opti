#!/usr/bin/env python3
"""Root-only passkey enrollment, backup credential and offline recovery.

No normal Panel authentication, no public self-registration. The only
enrollment authority is a short-lived, one-time token generated at a local
root-authenticated TTY. Recovery requires the same local root ceremony and
NEVER approves an XHTTP route by itself. Keys and attestation state are not
shared with Smite Panel.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import sys
import time

TOKEN_TTL=600
CEREMONY_TTL=120
SCHEMA="""CREATE TABLE credentials(
 id_hash TEXT PRIMARY KEY, raw BLOB NOT NULL, counter INTEGER NOT NULL,
 label TEXT NOT NULL, enrolled_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE enrollment_tickets(
 token_hash TEXT PRIMARY KEY, issued_at INTEGER NOT NULL, expires INTEGER NOT NULL,
 used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE ceremonies(
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, state TEXT NOT NULL,
 expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
 subject TEXT NOT NULL, happened INTEGER NOT NULL);
PRAGMA user_version=1;
"""


class EnrollmentHold(RuntimeError):
    pass


def _open(path: Path, *, root_check=True):
    p=Path(path)
    info=p.lstat()
    parent=p.parent.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1
            or stat.S_IMODE(info.st_mode)!=0o600
            or not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode)!=0o700
            or (root_check and (info.st_uid!=0 or parent.st_uid!=0))):
        raise EnrollmentHold("UNTRUSTED_CREDENTIAL_STORE")
    conn=sqlite3.connect(p.absolute().as_uri()+"?mode=rw",uri=True,
                         isolation_level=None,timeout=0.1)
    conn.execute("PRAGMA busy_timeout=100")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    if conn.execute("PRAGMA user_version").fetchone()!=(1,):
        conn.close();raise EnrollmentHold("CREDENTIAL_STORE_SCHEMA_MISMATCH")
    return conn


def bootstrap(path: Path) -> None:
    if os.geteuid()!=0 or not sys.stdin.isatty():
        raise EnrollmentHold("BOOTSTRAP_REQUIRES_ROOT_TTY")
    path=Path(path)
    parent=path.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=0
            or stat.S_IMODE(parent.st_mode)!=0o700
            or path.exists() or path.is_symlink()):
        raise EnrollmentHold("BOOTSTRAP_REQUIRES_EMPTY_ROOT_DIRECTORY")
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    os.close(fd)
    try:
        with sqlite3.connect(path) as conn:
            conn.executescript(SCHEMA)
            conn.commit()
    except Exception:
        # Never silently destroy partial bootstraps.
        raise EnrollmentHold("BOOTSTRAP_PARTIAL_REQUIRES_REVIEW")


class CredentialStore:
    def __init__(self,path: Path,*,root_check=True):
        self.path=Path(path)
        self.conn=_open(self.path,root_check=root_check)
    def close(self):self.conn.close()
    def _audit(self,event,subject,now):
        self.conn.execute("INSERT INTO audit(event,subject,happened) VALUES(?,?,?)",
                          (event,subject,now))

    def ticket(self,*,root_tty: bool,now: int|None=None) -> str:
        if not root_tty or os.geteuid()!=0:
            raise EnrollmentHold("TICKET_REQUIRES_LOCAL_ROOT_TTY")
        now=int(time.time()) if now is None else now
        token=secrets.token_urlsafe(32)
        digest=hashlib.sha256(token.encode()).hexdigest()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute("INSERT INTO enrollment_tickets VALUES(?,?,?,0)",
                              (digest,now,now+TOKEN_TTL))
            self._audit("RECOVERY_OR_ENROLLMENT_TICKET_ISSUED",digest,now)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK");raise
        return token

    def _ticket(self,token,now):
        if type(token) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{35,128}",token):
            raise EnrollmentHold("INVALID_ENROLLMENT_TICKET")
        digest=hashlib.sha256(token.encode()).hexdigest()
        row=self.conn.execute("SELECT expires,used FROM enrollment_tickets WHERE token_hash=?",
                              (digest,)).fetchone()
        if row is None or row[1] or row[0]<now:
            raise EnrollmentHold("ENROLLMENT_TICKET_EXPIRED_OR_USED")
        return digest

    def encoded(self):
        rows=self.conn.execute("SELECT raw FROM credentials WHERE revoked=0 ORDER BY enrolled_at").fetchall()
        return [base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") for (raw,) in rows]

    def enroll_begin(self,ticket: str,*,origin: str,now: int|None=None):
        from fido2.webauthn import PublicKeyCredentialUserEntity
        import importlib.util
        now=int(time.time()) if now is None else now
        # The passkey gate validates the dedicated HTTPS Origin with exact match.
        g=Path(__file__).with_name("smite-stage15-web-approval.py")
        spec=importlib.util.spec_from_file_location("stage15_enroll_gate",g)
        if not spec or not spec.loader:raise EnrollmentHold("WEBAUTHN_GATE_MISSING")
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        server=m._server(origin)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            digest=self._ticket(ticket,now)
            user=PublicKeyCredentialUserEntity(id=b"u-opti-root-manager",
                     name="route-approver",display_name="Independent Route Approver")
            options,state=server.register_begin(
                user,credentials=m._credentials(self.encoded()) if self.encoded() else [],
                user_verification="required")
            cid=secrets.token_hex(16)
            self.conn.execute("INSERT INTO ceremonies VALUES(?,?,?,?,0)",
                              (cid,digest,json.dumps(state),now+CEREMONY_TTL))
            self._audit("ENROLLMENT_CHALLENGE_ISSUED",digest,now)
            self.conn.execute("COMMIT")
            return {"ceremony":cid,"options":json.loads(options.to_json())}
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def enroll_complete(self,ceremony: str,response: dict,ticket: str,*,
                        origin: str,now: int|None=None):
        import importlib.util
        now=int(time.time()) if now is None else now
        if (type(ceremony) is not str or not re.fullmatch(r"[0-9a-f]{32}",ceremony)
                or type(response) is not dict):
            raise EnrollmentHold("INVALID_REGISTRATION_RESPONSE")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            digest=self._ticket(ticket,now)
            row=self.conn.execute("SELECT state,expires,used,token_hash FROM ceremonies WHERE id=?",
                                  (ceremony,)).fetchone()
            if row is None or row[2] or row[1]<now or row[3]!=digest:
                raise EnrollmentHold("REGISTRATION_EXPIRED_OR_SPENT")
            self.conn.execute("UPDATE ceremonies SET used=1 WHERE id=?",(ceremony,))
            self._audit("REGISTRATION_CHALLENGE_CONSUMED",digest,now)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK");raise
        g=Path(__file__).with_name("smite-stage15-web-approval.py")
        spec=importlib.util.spec_from_file_location("stage15_enroll_finish_gate",g)
        if not spec or not spec.loader:raise EnrollmentHold("WEBAUTHN_GATE_MISSING")
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        try:
            auth=m._server(origin).register_complete(json.loads(row[0]),response)
            credential=auth.credential_data
            if credential is None or not auth.is_user_verified():
                raise EnrollmentHold("PASSKEY_USER_VERIFICATION_REQUIRED")
            raw=bytes(credential)
            hashed=hashlib.sha256(credential.credential_id).hexdigest()
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self._ticket(ticket,now)
                self.conn.execute("INSERT INTO credentials VALUES(?,?,?,?,?,0)",
                                  (hashed,raw,int(auth.counter),"passkey",now))
                self.conn.execute("UPDATE enrollment_tickets SET used=1 WHERE token_hash=?",(digest,))
                self._audit("PASSKEY_ENROLLED",hashed,now)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK");raise
        except Exception as exc:
            raise EnrollmentHold("PASSKEY_REGISTRATION_REJECTED") from exc

    def check_and_advance(self,credential_hash: str,assertion: dict,*,now: int|None=None):
        """Persist authenticator signature counter after Fido2 signature check.

        Browsers may report zero for synchronized passkeys; a positive counter
        must strictly advance. Never reset an observed positive counter.
        """
        from fido2.webauthn import AuthenticationResponse
        now=int(time.time()) if now is None else now
        try:
            a=AuthenticationResponse.from_dict(assertion)
            current=int(a.response.authenticator_data.counter)
            self.conn.execute("BEGIN IMMEDIATE")
            row=self.conn.execute("SELECT counter,revoked FROM credentials WHERE id_hash=?",
                                  (credential_hash,)).fetchone()
            if (row is None or row[1]!=0 or (row[0] and current<=row[0])
                    or (row[0] and current==0)):
                raise EnrollmentHold("PASSKEY_COUNTER_OR_REVOCATION_HOLD")
            self.conn.execute("UPDATE credentials SET counter=? WHERE id_hash=?",
                              (max(row[0],current),credential_hash))
            self._audit("PASSKEY_COUNTER_VERIFIED",credential_hash,now)
            self.conn.execute("COMMIT")
        except Exception as exc:
            self.conn.execute("ROLLBACK")
            raise EnrollmentHold("PASSKEY_COUNTER_HOLD") from exc

    def revoke(self,credential_hash: str,*,root_tty: bool):
        if os.geteuid()!=0 or not root_tty or not re.fullmatch(r"[0-9a-f]{64}",credential_hash):
            raise EnrollmentHold("REVOCATION_REQUIRES_ROOT_TTY")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row=self.conn.execute("SELECT revoked FROM credentials WHERE id_hash=?",(credential_hash,)).fetchone()
            if row is None or row[0]:raise EnrollmentHold("CREDENTIAL_NOT_ACTIVE")
            self.conn.execute("UPDATE credentials SET revoked=1 WHERE id_hash=?",(credential_hash,))
            self._audit("PASSKEY_REVOKED",credential_hash,int(time.time()))
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK");raise


if __name__=="__main__":
    if os.geteuid()!=0 or not sys.stdin.isatty():
        raise SystemExit("HOLD_ROOT_TTY_REQUIRED")
    if len(sys.argv)==3 and sys.argv[1]=="--bootstrap":
        bootstrap(Path(sys.argv[2]));print("BOOTSTRAPPED_INERT")
    elif len(sys.argv)==3 and sys.argv[1]=="--ticket":
        store=CredentialStore(Path(sys.argv[2]))
        try: print("ONE_TIME_ENROLLMENT_TICKET="+store.ticket(root_tty=True))
        finally: store.close()
    elif len(sys.argv)==4 and sys.argv[1]=="--revoke":
        store=CredentialStore(Path(sys.argv[2]))
        try: store.revoke(sys.argv[3],root_tty=True);print("CREDENTIAL_REVOKED")
        finally: store.close()
    else:
        raise SystemExit("HOLD_USE_EXPLICIT_BOOTSTRAP_TICKET_OR_REVOKE")
