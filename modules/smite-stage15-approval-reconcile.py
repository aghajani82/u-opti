#!/usr/bin/env python3
"""IR ROOT TTY ONLY: read-only reconciliation of an expired Stage15 proposal.

Never deletes an intent/ledger entry, consumes a nonce, rewrites an active
route or restarts nginx/frps. A crash or uncertain outcome stays HOLD. The
durable closure receipt is created only after proving no grant, no route or
journal and no consumed original nonce. Exceptional recovery only: normal
new tunnel publication uses browser Passkey without this command.
"""
from __future__ import annotations
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
LOCK=Path("/run/lock/u-opti-smite-engine.lock")
GRANTS=Path("/etc/u-opti/smite/route-grants")
ROUTES=Path("/etc/nginx/smite-xhttp-routes")
LEDGER=Path("/var/lib/u-opti/smite-xhttp-broker/nonce.db")
QUEUE=Path("/var/lib/u-opti/smite-xhttp-broker/approval-pending")
KEY=Path("/etc/u-opti/smite/route-broker.key")
HEX=re.compile(r"[0-9a-f]{64}\Z")


class ReconcileHold(RuntimeError):
    pass


def _module(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    if not spec or not spec.loader:raise ReconcileHold("VERIFIED_QUEUE_UNAVAILABLE")
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m


def _root_file(path,mode=0o600):
    try:st=path.lstat()
    except OSError as exc:raise ReconcileHold("REQUIRED_ROOT_STATE_MISSING") from exc
    if (not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_nlink!=1
            or stat.S_IMODE(st.st_mode)!=mode):
        raise ReconcileHold("ROOT_STATE_UNTRUSTED")
    return st


def _absent(path):
    if path.exists() or path.is_symlink():
        raise ReconcileHold("ROUTE_OR_TRANSACTION_MAY_HAVE_APPLIED")


def _read_only_inspect(binding:dict,nonce:str,now:int,*,root=Path("/")) -> dict:
    port=binding["port"]
    if (type(port) is not int or not 1024<=port<=65535
            or type(nonce) is not str or not re.fullmatch(r"[0-9a-f]{32}",nonce)):
        raise ReconcileHold("INVALID_RECONCILIATION_TARGET")
    route=root/ROUTES.relative_to("/")/f"{port}.conf"
    journal=root/ROUTES.relative_to("/")/f".{port}.transaction.json"
    grant=root/GRANTS.relative_to("/")/(binding["child"]+".json")
    for p in (route,journal,grant):
        _absent(p)
    ledger=root/LEDGER.relative_to("/")
    _root_file(ledger)
    try:
        with sqlite3.connect(ledger.absolute().as_uri()+"?mode=ro",
                             uri=True,isolation_level=None,timeout=1) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):
                raise ReconcileHold("BROKER_NONCE_LEDGER_CORRUPT")
            matches=db.execute("SELECT request_sha256 FROM consumed_nonces WHERE nonce=?",
                               (nonce,)).fetchall()
            if matches:raise ReconcileHold("NONCE_CONSUMED_UNCERTAIN_OUTCOME")
            db.execute("ROLLBACK")
    except sqlite3.Error as exc:
        raise ReconcileHold("BROKER_NONCE_LEDGER_UNAVAILABLE") from exc
    if root!=Path("/"):
        # Disposable test roots cannot prove Nginx's loaded configuration.
        raise ReconcileHold("LIVE_NGINX_VERIFICATION_REQUIRED")
    try:
        # Read-only Nginx configuration parse. No reload, -s reload or write.
        proc=subprocess.run(["/usr/sbin/nginx","-T"],capture_output=True,
                            timeout=5,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ReconcileHold("NGINX_READONLY_INSPECTION_UNAVAILABLE") from exc
    if (proc.returncode!=0 or len(proc.stdout)>2_000_000
            or not proc.stdout):
        raise ReconcileHold("NGINX_READONLY_INSPECTION_HOLD")
    active=proc.stdout.decode("utf-8","replace")
    # Conservative: even a route string in another vhost blocks closure.
    if (binding["path"] in active or f":{port}" in active
            or f"{port}.conf" in active):
        raise ReconcileHold("NGINX_ROUTE_STATUS_AMBIGUOUS")
    return {"route":"ABSENT","journal":"ABSENT","broker_nonce":"UNCONSUMED",
            "checked_at":now,"binding_sha256":hashlib.sha256(
                json.dumps(binding,sort_keys=True,separators=(",",":"),
                           ensure_ascii=True).encode("ascii")).hexdigest()}


def close_expired(digest:str,*,now:int|None=None):
    if (os.geteuid()!=0 or not sys.stdin.isatty()
            or os.uname().nodename.split(".")[0].lower()!="ir"
            or type(digest) is not str or not HEX.fullmatch(digest)):
        raise ReconcileHold("IR_ROOT_TTY_ONLY")
    now=int(time.time()) if now is None else now
    lockfd=os.open(LOCK,os.O_RDWR|os.O_NOFOLLOW)
    try:
        st=os.fstat(lockfd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
            raise ReconcileHold("UNTRUSTED_ENGINE_LOCK")
        fcntl.flock(lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        _root_file(KEY)
        key=KEY.read_bytes()
        if len(key)!=32:raise ReconcileHold("ROOT_BROKER_KEY_INVALID")
        q=_module("root_review_queue_reconciler",
                  "smite-stage15-approval-queue.py")
        return q.close_expired_after_reconciliation(
            directory=QUEUE,digest=digest,key=key,now=now,
            read_only_reconciler=lambda b,n:_read_only_inspect(b,n,now),
            root_check=True)
    finally:
        os.close(lockfd)


if __name__=="__main__":
    if len(sys.argv)!=3 or sys.argv[1]!="--close-expired":
        raise SystemExit("HOLD_EXPLICIT_RECONCILIATION_ONLY")
    if input("Type REVIEW "+sys.argv[2]+" to inspect and close ONLY proven-unpublished: ").strip()!="REVIEW "+sys.argv[2]:
        raise SystemExit("HOLD_NOT_CONFIRMED")
    try:
        record=close_expired(sys.argv[2])
        print("CLOSED_VERIFIED_UNPUBLISHED="+record["digest"])
        print("INTENT_AND_AUDIT_PRESERVED=YES")
        print("FRPS_NGINX_RESTART=NO")
    except Exception:
        raise SystemExit("HOLD_UNKNOWN_OR_UNVERIFIED_PUBLICATION_NO_RETRY")
