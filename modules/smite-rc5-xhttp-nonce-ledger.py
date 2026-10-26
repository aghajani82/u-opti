#!/usr/bin/env python3
"""Root-only durable replay ledger for the future U-OPTI XHTTP route broker.

Offline/library ONLY: no Unix socket, HTTP endpoint, privileged Nginx action,
automatic database provisioning, background worker or executable route apply.
Both ledger initialization and consumption require separate explicitly
authorized local root operations. Missing/corrupt/restored-untrusted state
must HOLD; there is no silent reset or garbage collection.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys


class LedgerHold(RuntimeError):
    """The future broker MUST fail closed; no host action may follow."""


SCHEMA_VERSION = 1
APPLICATION_ID = 0x534D4954  # "SMIT"
MAX_ENTRIES = 100_000
NONCE = re.compile(r"[a-f0-9]{32}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
BROKER_ID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")
SIBLING_CONTRACT = Path(__file__).resolve().with_name("smite-rc5-xhttp-signed-intent.py")


def _contract_module():
    """Load the existing inert HMAC verifier without invoking a shell/API."""
    module_name = "uopti_xhttp_intent_contract_for_ledger"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(
        module_name, SIBLING_CONTRACT
    )
    if spec is None or spec.loader is None:
        raise LedgerHold("INTENT_CONTRACT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _root_private_parent(path: Path) -> None:
    if os.geteuid() != 0 or not path.is_absolute() or ".." in path.parts:
        raise LedgerHold("ROOT_APPROVED_ABSOLUTE_PATH_REQUIRED")
    try:
        info = path.parent.lstat()
    except OSError as exc:
        raise LedgerHold("BROKER_PRIVATE_PARENT_MISSING") from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise LedgerHold("BROKER_PARENT_NOT_ROOT_PRIVATE")


def _trusted_db(path: Path) -> os.stat_result:
    _root_private_parent(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise LedgerHold("BROKER_LEDGER_MISSING") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
            or not 0 < info.st_size <= 64 * 1024 * 1024):
        raise LedgerHold("BROKER_LEDGER_UNTRUSTED")
    return info


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _check_identity(instance_id: str) -> None:
    if type(instance_id) is not str or not BROKER_ID.fullmatch(instance_id):
        raise LedgerHold("INVALID_BROKER_INSTANCE")


def _open_existing(path: Path) -> sqlite3.Connection:
    original = _trusted_db(path)
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True,
                               timeout=2.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA synchronous=FULL")
        # Do not silently create schema, reset or recreate DB in runtime.
        if (conn.execute("PRAGMA user_version").fetchone() != (SCHEMA_VERSION,)
                or conn.execute("PRAGMA application_id").fetchone() != (APPLICATION_ID,)):
            raise LedgerHold("BROKER_LEDGER_VERSION_MISMATCH")
        meta = conn.execute("PRAGMA table_info(consumed_nonces)").fetchall()
        fields = {x[1] for x in meta}
        if fields != {"nonce", "request_sha256", "consumed_at"}:
            raise LedgerHold("BROKER_LEDGER_SCHEMA_MISMATCH")
        conn.execute("SELECT instance_id FROM broker_identity LIMIT 0")
        # Check the path after SQLite opened it. No root privilege delegated
        # to containers or arbitrary local callers; filesystem race protection
        # is not a replacement for an audited broker launch boundary.
        current = _trusted_db(path)
        if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
            raise LedgerHold("BROKER_LEDGER_REPLACED")
        return conn
    except BaseException:
        if "conn" in locals():
            conn.close()
        raise


class DurableNonceLedger:
    """Versioned root-owned state, intentionally no unapproved default path."""

    def __init__(self, path: Path, *, instance_id: str,
                 max_entries: int = MAX_ENTRIES):
        _check_identity(instance_id)
        if (not isinstance(path, Path) or type(max_entries) is not int
                or not 1 <= max_entries <= MAX_ENTRIES):
            raise LedgerHold("INVALID_LEDGER_CONFIG")
        self.path = path
        self.instance_id = instance_id
        self.max_entries = max_entries

    @staticmethod
    def bootstrap_new(path: Path, *, instance_id: str) -> None:
        """ONE-TIME explicit local root provisioner; never on request path.

        Failure may leave an unusable file as a deliberate HOLD requiring
        manual forensic review. Caller must pre-create a trusted 0700 parent.
        """
        _check_identity(instance_id)
        if not isinstance(path, Path):
            raise LedgerHold("INVALID_LEDGER_PATH")
        _root_private_parent(path)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            os.fsync(fd)
            os.close(fd)
            fd = None
            with closing(sqlite3.connect(
                path.as_uri() + "?mode=rw", uri=True, timeout=2.0,
                isolation_level=None,
            )) as conn:
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("PRAGMA trusted_schema=OFF")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "CREATE TABLE broker_identity "
                    "(instance_id TEXT NOT NULL PRIMARY KEY)"
                )
                conn.execute(
                    "CREATE TABLE consumed_nonces "
                    "(nonce TEXT NOT NULL PRIMARY KEY, "
                    "request_sha256 TEXT NOT NULL, consumed_at INTEGER NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO broker_identity(instance_id) VALUES (?)",
                    (instance_id,),
                )
                conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                conn.commit()
            _fsync_dir(path.parent)
            _trusted_db(path)
        except (sqlite3.Error, OSError) as exc:
            raise LedgerHold("BROKER_BOOTSTRAP_FAILED_NO_AUTO_RETRY") from exc
        finally:
            if "fd" in locals() and fd is not None:
                os.close(fd)

    def consume(self, nonce: str, request_sha256: str, *, now: int) -> None:
        """Consume a valid, independently authenticated intent ONCE.

        SQLite BEGIN IMMEDIATE + UNIQUE PK atomically reject concurrent or
        post-restart duplicate nonces. No automatic expiration/deletion (which
        could admit replay after clock rollback or a crash). At capacity HOLD.
        """
        if (type(nonce) is not str or not NONCE.fullmatch(nonce)
                or type(request_sha256) is not str
                or not HASH.fullmatch(request_sha256)
                or type(now) is not int or now < 0):
            raise LedgerHold("INVALID_REPLAY_RECORD")
        try:
            with closing(_open_existing(self.path)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                identities = conn.execute(
                    "SELECT instance_id FROM broker_identity"
                ).fetchall()
                if identities != [(self.instance_id,)]:
                    raise LedgerHold("BROKER_LEDGER_IDENTITY_MISMATCH")
                if conn.execute("SELECT COUNT(*) FROM consumed_nonces").fetchone()[0] >= self.max_entries:
                    raise LedgerHold("BROKER_LEDGER_CAPACITY_HOLD")
                try:
                    conn.execute(
                        "INSERT INTO consumed_nonces(nonce,request_sha256,consumed_at) "
                        "VALUES (?,?,?)", (nonce, request_sha256, now)
                    )
                except sqlite3.IntegrityError as exc:
                    raise LedgerHold("BROKER_NONCE_ALREADY_CONSUMED") from exc
                conn.commit()
        except sqlite3.Error as exc:
            raise LedgerHold("BROKER_LEDGER_UNAVAILABLE") from exc

    def authenticate_and_consume(
        self, wire: bytes, *,
        key: bytes, expected: object, now: int,
    ):
        """Pure intent verification then atomic ledger consumption; NO apply.

        The caller MUST source expected from an independently verified root
        grant (not from wire). Failure to consume => never call Nginx. A
        future broker must hold the appropriate host lock through both nonce
        consumption and its idempotent root transaction.
        """
        contract = _contract_module()
        if not isinstance(expected, contract.TrustedGrant):
            raise LedgerHold("INDEPENDENT_ROOT_GRANT_REQUIRED")
        authenticated = contract.admit(
            wire, key=key, expected=expected,
            seen_nonces=frozenset(), now=now,
        )
        self.consume(authenticated.nonce, hashlib.sha256(wire).hexdigest(), now=now)
        return authenticated
