#!/usr/bin/env python3
"""Independent Stage15 Passkey gate (offline primitive; NOT an HTTP endpoint).

This module only verifies a WebAuthn assertion, binds it to an exact pending
route digest and records a single-use decision. It NEVER grants privileges,
sends Signed Intents or calls the route broker. The root-owned approval service
must call the independent evidence verifier and issue a grant after this gate.
An unconfigured origin or credential refuses every attempt.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import sys
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
from urllib.parse import urlsplit


class WebApprovalHold(RuntimeError):
    pass


HEX = re.compile(r"[0-9a-f]{64}\Z")
CHALLENGE_TTL = 90
SCHEMA = """CREATE TABLE IF NOT EXISTS challenges(
    id TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL,
    expires INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS successful_passkeys(
    digest TEXT NOT NULL, credential_sha256 TEXT NOT NULL,
    PRIMARY KEY(digest,credential_sha256));
CREATE TABLE IF NOT EXISTS evidence_nonces(nonce TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS approvals(
    digest TEXT PRIMARY KEY, credential_sha256 TEXT NOT NULL,
    approved_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    digest TEXT NOT NULL, event TEXT NOT NULL, happened INTEGER NOT NULL);
"""


def _server(origin: str):
    """Require a dedicated HTTPS origin, never same-origin with Smite."""
    try:
        parts = urlsplit(origin)
        hostname = parts.hostname
        valid = (
            parts.scheme == "https" and hostname and
            parts.port in (None, 443) and not parts.username and
            not parts.password and parts.path in ("", "/") and
            not parts.query and not parts.fragment and
            hostname == hostname.lower() and
            re.fullmatch(r"[a-z0-9.-]{4,253}", hostname)
        )
        if not valid or origin.endswith("/") or hostname in ("localhost", "127.0.0.1"):
            raise ValueError("invalid origin")
        from fido2.server import Fido2Server
        from fido2.webauthn import PublicKeyCredentialRpEntity
        rp = PublicKeyCredentialRpEntity(id=hostname, name="U-OPTI Independent Route Approval")
        return Fido2Server(rp, verify_origin=lambda seen: seen == origin)
    except (ImportError, ValueError, TypeError, AttributeError) as exc:
        raise WebApprovalHold("INDEPENDENT_WEBAUTHN_ORIGIN_UNAVAILABLE") from exc


def _credentials(encoded: list[str]):
    if not isinstance(encoded, list) or not 1 <= len(encoded) <= 5:
        raise WebApprovalHold("NO_INDEPENDENT_PASSKEY")
    try:
        from fido2.webauthn import AttestedCredentialData
        result = []
        seen = set()
        for token in encoded:
            if type(token) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{20,4096}", token):
                raise ValueError("credential data")
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            credential = AttestedCredentialData(raw)
            if credential.credential_id in seen:
                raise ValueError("duplicate passkey")
            seen.add(credential.credential_id)
            result.append(credential)
        return result
    except (ImportError, ValueError, TypeError) as exc:
        raise WebApprovalHold("UNTRUSTED_PASSKEY_STORE") from exc


class ApprovalLedger:
    """Private SQLite state; caller must run as dedicated root service only."""

    def __init__(self, path: Path, *, root_check: bool = True):
        self.path = Path(path)
        if root_check:
            if os.geteuid() != 0:
                raise WebApprovalHold("ROOT_BOUNDARY_REQUIRED")
            for p in (self.path.parent,):
                s = p.lstat()
                if (not stat.S_ISDIR(s.st_mode) or s.st_uid != 0
                        or stat.S_IMODE(s.st_mode) != 0o700):
                    raise WebApprovalHold("UNTRUSTED_APPROVAL_DIRECTORY")
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or (root_check and info.st_uid != 0)):
                raise WebApprovalHold("UNTRUSTED_APPROVAL_LEDGER")
        elif root_check:
            raise WebApprovalHold("APPROVAL_LEDGER_NOT_BOOTSTRAPPED")
        self.conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=0.15,
                                    check_same_thread=False)
        self.conn.execute("PRAGMA busy_timeout=150")
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(SCHEMA)
        if root_check:
            if stat.S_IMODE(self.path.stat().st_mode) != 0o600:
                raise WebApprovalHold("APPROVAL_LEDGER_MODE_DRIFT")

    def close(self):
        self.conn.close()

    def _record(self, digest: str, event: str, now: int):
        self.conn.execute("INSERT INTO audit(digest,event,happened) VALUES(?,?,?)",
                          (digest, event, now))

    def begin(self, digest: str, *, origin: str,
              passkeys: list[str], now: int | None = None) -> dict:
        now = int(time.time()) if now is None else now
        if type(digest) is not str or not HEX.fullmatch(digest):
            raise WebApprovalHold("INVALID_REVIEW_ID")
        server = _server(origin)
        options, state = server.authenticate_begin(
            _credentials(passkeys), user_verification="required"
        )
        challenge_id = secrets.token_hex(16)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if self.conn.execute("SELECT 1 FROM approvals WHERE digest=?", (digest,)).fetchone():
                raise WebApprovalHold("ALREADY_APPROVED")
            self.conn.execute("INSERT INTO challenges(id,digest,state,expires) VALUES(?,?,?,?)",
                              (challenge_id, digest, json.dumps(state), now + CHALLENGE_TTL))
            self._record(digest, "CHALLENGE_ISSUED", now)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        option_data = dict(options) if hasattr(options, "keys") else json.loads(options.to_json())
        return {"challenge_id": challenge_id, "options": option_data}

    def consume(self, challenge_id: str, *, digest: str, origin: str,
                passkeys: list[str], assertion: dict,
                now: int | None = None) -> str:
        """Consume challenge BEFORE cryptographic verification, even on failure.

        A successful response is only an authenticated review decision.
        Caller must separately verify fresh IR/KH/lease evidence, atomically
        commit its nonces and issue a root-owned TrustedGrant. No Panel callback
        can perform those latter steps.
        """
        now = int(time.time()) if now is None else now
        if (type(challenge_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", challenge_id)
                or type(digest) is not str or not HEX.fullmatch(digest)
                or type(assertion) is not dict):
            raise WebApprovalHold("INVALID_PASSKEY_RESPONSE")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT digest,state,expires,consumed FROM challenges WHERE id=?",
                                    (challenge_id,)).fetchone()
            if (row is None or row[0] != digest or row[3] != 0 or now > row[2]
                    or self.conn.execute("SELECT 1 FROM approvals WHERE digest=?", (digest,)).fetchone()):
                raise WebApprovalHold("PASSKEY_CHALLENGE_EXPIRED_OR_SPENT")
            # Do not permit stolen Panel sessions to recycle a challenge.
            self.conn.execute("UPDATE challenges SET consumed=1 WHERE id=? AND consumed=0", (challenge_id,))
            self._record(digest, "CHALLENGE_CONSUMED", now)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        try:
            server = _server(origin)
            credential = server.authenticate_complete(
                json.loads(row[1]), _credentials(passkeys), assertion
            )
        except Exception as exc:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self._record(digest, "PASSKEY_REJECTED", now)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            raise WebApprovalHold("INDEPENDENT_PASSKEY_REJECTED") from exc
        credential_hash = hashlib.sha256(credential.credential_id).hexdigest()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute("INSERT OR IGNORE INTO successful_passkeys(digest,credential_sha256) VALUES(?,?)",
                              (digest, credential_hash))
            self._record(digest, "PASSKEY_VERIFIED", now)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return credential_hash

    def record_verified_approval(self, *, digest: str, credential_sha256: str,
                                 binding: dict, bundle: dict,
                                 ir_public_key: bytes, kh_public_key: bytes,
                                 lease_public_key: bytes | None = None,
                                 now: int | None = None) -> None:
        """Perform independent evidence verification and record approval; NO grant.

        This ledger records unique proof nonces independently of the existing
        route broker's nonce.db. The publisher must still use its separate
        durable one-time Signed Intent nonce.
        """
        now = int(time.time()) if now is None else now
        if (type(digest) is not str or not HEX.fullmatch(digest)
                or type(credential_sha256) is not str or not HEX.fullmatch(credential_sha256)):
            raise WebApprovalHold("UNVERIFIED_APPROVAL_CONTEXT")
        path = Path(__file__).with_name("smite-stage15-approval-evidence.py")
        spec = importlib.util.spec_from_file_location("stage15_independent_review_evidence", path)
        if spec is None or spec.loader is None:
            raise WebApprovalHold("INDEPENDENT_EVIDENCE_VERIFIER_MISSING")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if not self.conn.execute(
                "SELECT 1 FROM successful_passkeys WHERE digest=? AND credential_sha256=?",
                (digest, credential_sha256)
            ).fetchone():
                raise WebApprovalHold("UNAUTHENTICATED_APPROVAL")
            consumed = frozenset(n for (n,) in self.conn.execute(
                "SELECT nonce FROM evidence_nonces"
            ))
            evidence_nonces = module.verify_bundle(
                bundle, binding, ir_public_key=ir_public_key,
                kh_public_key=kh_public_key, lease_public_key=lease_public_key,
                now=now, consumed_nonces=consumed,
            )
            for nonce in sorted(evidence_nonces):
                self.conn.execute("INSERT INTO evidence_nonces(nonce) VALUES(?)", (nonce,))
            self.conn.execute("INSERT INTO approvals(digest,credential_sha256,approved_at) VALUES(?,?,?)",
                              (digest, credential_sha256, now))
            self._record(digest, "EVIDENCE_APPROVED_GRANT_NOT_ISSUED", now)
            self.conn.execute("COMMIT")
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
            self.conn.execute("ROLLBACK")
            raise WebApprovalHold("DUPLICATE_APPROVAL_OR_EVIDENCE_REPLAY") from exc
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
