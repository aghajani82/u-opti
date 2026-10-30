#!/usr/bin/env python3
"""Inert immutable queue primitive for root-authenticated Stage15 requests.

Not connected to the active broker. The current single-slot review request
will be migrated only after an isolated transactional test and authorization.
This module neither issues a TrustedGrant nor publishes a route.
"""
from __future__ import annotations
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

HEX = re.compile(r"[a-f0-9]{64}\Z")
IDENT = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
MAX_REVIEW_AGE = 600
MAX_WIRE = 4096


class QueueHold(RuntimeError):
    pass


def _contract():
    path = Path(__file__).with_name("smite-rc5-xhttp-signed-intent.py")
    spec = importlib.util.spec_from_file_location("stage15_queue_signed_contract", path)
    if spec is None or spec.loader is None:
        raise QueueHold("SIGNED_CONTRACT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _trusted_directory(path: Path, *, root_check: bool) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
            or (root_check and info.st_uid != 0)):
        raise QueueHold("UNTRUSTED_PENDING_DIRECTORY")


def _file(path: Path, *, root_check: bool) -> bytes:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or (root_check and info.st_uid != 0)
            or not 0 < info.st_size < MAX_WIRE * 3):
        raise QueueHold("UNTRUSTED_PENDING_FILE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise QueueHold("PENDING_FILE_CHANGED")
        raw = os.read(fd, MAX_WIRE * 3)
        if len(raw) != info.st_size:
            raise QueueHold("PENDING_FILE_CHANGED")
        return raw
    finally:
        os.close(fd)


def _atomic_new(target: Path, wire: bytes) -> None:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as out:
            out.write(wire)
            out.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    dirfd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(dirfd)
    finally: os.close(dirfd)


def _locked(path: Path):
    lock = path / ".queue.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        os.close(fd)
        raise QueueHold("UNTRUSTED_PENDING_LOCK")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def stage(*, directory: Path, wire: bytes, key: bytes, now: int,
          root_check: bool = True) -> str:
    """Stage only an already authentic *current* signed intent.

    A different proposal for the same child is HOLD, never overwrite.
    This prevents a concurrent Panel submission from replacing the exact
    facts shown in the independent approval browser.
    """
    directory = Path(directory)
    _trusted_directory(directory, root_check=root_check)
    if type(wire) is not bytes or not 0 < len(wire) <= MAX_WIRE:
        raise QueueHold("INVALID_PENDING_WIRE")
    c = _contract()
    try:
        v = json.loads(wire)
        if not isinstance(v, dict) or set(v) != c.WIRE_FIELDS:
            raise QueueHold("INVALID_PENDING_WIRE")
        trusted = c.TrustedGrant(**{k: v[k] for k in c.TrustedGrant.__dataclass_fields__})
        c.admit(wire, key=key, expected=trusted, seen_nonces=frozenset(), now=now)
    except (ValueError, TypeError, KeyError) as exc:
        raise QueueHold("UNAUTHENTICATED_PENDING_INTENT") from exc
    if type(now) is not int or now < 0 or not IDENT.fullmatch(v["child"]):
        raise QueueHold("INVALID_STAGE_CONTEXT")
    digest = hashlib.sha256(wire).hexdigest()
    target = directory / ("proposal-" + digest + ".json")
    entry = {"schema": 1, "digest": digest, "child": v["child"],
             "staged_at": now, "wire_b64": base64.b64encode(wire).decode("ascii")}
    encoded = (json.dumps(entry, sort_keys=True, separators=(",", ":"))+"\n").encode("ascii")
    lockfd = _locked(directory)
    try:
        for other in directory.glob("proposal-*.json"):
            item = _file(other, root_check=root_check)
            try:
                previous = json.loads(item)
            except ValueError as exc:
                raise QueueHold("CORRUPT_PENDING_QUEUE") from exc
            if (not isinstance(previous, dict) or set(previous) != set(entry)
                    or previous.get("digest") != other.name[9:-5]):
                raise QueueHold("CORRUPT_PENDING_QUEUE")
            if other != target and previous["child"] == v["child"]:
                raise QueueHold("CONCURRENT_CHILD_PENDING_REQUIRES_REVIEW")
        if target.exists() or target.is_symlink():
            if _file(target, root_check=root_check) != encoded:
                raise QueueHold("PENDING_PROPOSAL_CHANGED")
            return digest
        _atomic_new(target, encoded)
        return digest
    finally:
        fcntl.flock(lockfd, fcntl.LOCK_UN)
        os.close(lockfd)


def review(*, directory: Path, digest: str, key: bytes, now: int,
           root_check: bool = True) -> dict:
    """Review historical envelope after intent expiry; NEVER publish it.

    The separate root approval engine MUST collect fresh signed node
    attestations and recheck the lease immediately before issuing any grant.
    """
    directory = Path(directory)
    _trusted_directory(directory, root_check=root_check)
    if type(digest) is not str or not HEX.fullmatch(digest) or type(now) is not int:
        raise QueueHold("INVALID_REVIEW_CONTEXT")
    encoded = _file(directory / ("proposal-" + digest + ".json"), root_check=root_check)
    try:
        entry = json.loads(encoded)
        if (type(entry) is not dict or set(entry) != {
                "schema", "digest", "child", "staged_at", "wire_b64"}
                or type(entry["schema"]) is not int or entry["schema"] != 1
                or entry["digest"] != digest or type(entry["staged_at"]) is not int
                or not 0 <= now - entry["staged_at"] <= MAX_REVIEW_AGE):
            raise QueueHold("STALE_OR_MISMATCHED_REVIEW")
        wire = base64.b64decode(entry["wire_b64"], validate=True)
        if hashlib.sha256(wire).hexdigest() != digest:
            raise QueueHold("PENDING_DIGEST_MISMATCH")
        c = _contract()
        intent = json.loads(wire)
        trusted = c.TrustedGrant(**{k: intent[k] for k in c.TrustedGrant.__dataclass_fields__})
        # Recheck exact original HMAC and canonical fields at its issuance.
        # Its actual 30s lifetime is NOT extended; the publisher must sign
        # a completely NEW 30s intent after a separate Root grant.
        c.admit(wire, key=key, expected=trusted, seen_nonces=frozenset(),
                now=entry["staged_at"])
        if entry["child"] != intent["child"]:
            raise QueueHold("PENDING_CHILD_MISMATCH")
        return {k: getattr(trusted, k) for k in c.TrustedGrant.__dataclass_fields__}
    except (ValueError, KeyError, TypeError, base64.binascii.Error) as exc:
        raise QueueHold("UNTRUSTED_PENDING_REVIEW") from exc
