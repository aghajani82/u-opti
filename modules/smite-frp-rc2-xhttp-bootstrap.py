#!/usr/bin/env python3
"""IR RC2 signed-WSS XHTTP managed Nginx snippet bootstrap.

One-time, exact missing file only. No reload, no proxy route, no Node/tunnel
apply. The strict signed RC2 gate *must* be independently satisfied before
and after creation. Existing Nginx snippets are never overwritten.
"""
from __future__ import annotations
import argparse
import fcntl
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys

HERE=Path(__file__).resolve().parent
SIBLING=HERE/"smite-frp-rc2-gateway-ready.py"
SNIPPET=Path("/etc/nginx/u-opti-smite-frp-xhttp.conf")
HEADER=b"# Managed by U-OPTI - Standard FRP XHTTP\n"
LOCK=Path("/run/lock/u-opti-smite-engine.lock")
ENV="UOPTI_RC2_IR_XHTTP_BOOTSTRAP_TRIAL"
WORD="CREATE-IR-RC2-XHTTP-SNIPPET"

spec=importlib.util.spec_from_file_location("smite_rc2_xhttp_gate",SIBLING)
if spec is None or spec.loader is None:
    raise SystemExit("HOLD: GATE_MODULE_MISSING")
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class Hold(Exception):pass


def need(value, reason):
    if not value:raise Hold(reason)


def absent(path:Path)->bool:
    return not path.exists() and not path.is_symlink()


def safe_dir(path:Path):
    statinfo=path.lstat()
    need(stat.S_ISDIR(statinfo.st_mode) and statinfo.st_uid==0 and
         not statinfo.st_mode & 0o022,"UNTRUSTED_NGINX_DIRECTORY")


def before():
    need(os.geteuid()==0 and os.uname().nodename.split(".")[0].lower()=="ir",
         "IR_ROOT_ONLY")
    need(absent(SNIPPET),"EXISTING_XHTTP_SNIPPET_DO_NOT_OVERWRITE")
    safe_dir(SNIPPET.parent)
    gate.audit(allow_missing_snippet=True)
    need(absent(SNIPPET),"XHTTP_SNIPPET_CHANGED")


def nginx_test():
    try:
        p=subprocess.run(["nginx","-t"],capture_output=True,text=True,timeout=30)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise Hold("NGINX_SYNTAX_CHECK_FAILED") from exc
    need(p.returncode==0,"NGINX_SYNTAX_CHECK_FAILED")


def new_snippet():
    fd=os.open(SNIPPET, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
    with os.fdopen(fd,"wb") as f:
        os.fchmod(f.fileno(),0o644)
        f.write(HEADER);f.flush();os.fsync(f.fileno())
        obj=os.fstat(f.fileno())
    dirfd=os.open(SNIPPET.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(dirfd)
    finally:os.close(dirfd)
    return obj.st_dev,obj.st_ino


def remove_if_ours(identity):
    obj=SNIPPET.lstat()
    # The preflight verified the parent is trusted, root-owned on IR.
    # Compare ownership to that trusted parent so offline unprivileged CI
    # can exercise the exact same rollback without unsafe root simulation.
    parent=SNIPPET.parent.lstat()
    need((obj.st_dev,obj.st_ino)==identity and
         stat.S_ISREG(obj.st_mode) and obj.st_uid==parent.st_uid,
         "CRITICAL_SNIPPET_ROLLBACK_MANUAL")
    fd=os.open(SNIPPET,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as f:
        current=os.fstat(f.fileno())
        need((current.st_dev,current.st_ino)==identity and f.read(1024)==HEADER,
             "CRITICAL_SNIPPET_ROLLBACK_MANUAL")
    SNIPPET.unlink()
    dirfd=os.open(SNIPPET.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(dirfd)
    finally:os.close(dirfd)


def lock():
    need(not LOCK.is_symlink(),"UNTRUSTED_ENGINE_LOCK")
    fd=os.open(LOCK,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    info=os.fstat(fd)
    need(stat.S_ISREG(info.st_mode) and info.st_uid==0 and
         stat.S_IMODE(info.st_mode)==0o600,"UNTRUSTED_ENGINE_LOCK")
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise Hold("ENGINE_LOCK_BUSY") from exc
    return fd


def apply():
    fd=lock()
    try:
        before()
        identity=new_snippet()
        try:
            gate.audit()
            nginx_test()
        except Exception as exc:
            remove_if_ours(identity)
            raise Hold("XHTTP_BOOTSTRAP_FAILED_ROLLED_BACK") from exc
        print("RC2_IR_XHTTP_SNIPPET=CREATED_VERIFIED")
        print("SIGNED_WSS_GATE=PASS")
        print("NGINX_SYNTAX=PASS")
        print("NGINX_RELOAD=NOT_PERFORMED")
        print("XHTTP_ROUTES_PUBLISHED=NONE")
    finally:os.close(fd)


def verify():
    gate.audit()
    content=gate.read_root_file(SNIPPET,max_bytes=131072)
    need(content==HEADER,"XHTTP_SNIPPET_NOT_EMPTY_BOOTSTRAP")
    nginx_test()
    print("RC2_IR_XHTTP_BOOTSTRAP_VERIFY=PASS_READ_ONLY")
    print("XHTTP_ROUTES_PUBLISHED=NONE")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("plan","apply","verify"))
    args=parser.parse_args()
    try:
        if args.action=="plan":
            before()
            print("RC2_IR_XHTTP_BOOTSTRAP_PLAN=PASS_READ_ONLY")
            print("SIGNED_NODE_GATE=PASS")
            print("NGINX_CHANGES=NONE")
            print("XHTTP_ROUTES_PUBLISHED=NONE")
        elif args.action=="apply":
            need(sys.stdin.isatty(),"INTERACTIVE_APPROVAL_REQUIRED")
            need(os.environ.get(ENV)=="YES","TRIAL_OPT_IN_REQUIRED")
            need(input("Type "+WORD+" to authorize: ").strip()==WORD,
                 "OPERATOR_CANCELLED")
            apply()
        else:verify()
        return 0
    except (Hold,gate.GateHold,OSError,KeyError,ValueError,
            UnicodeError,subprocess.SubprocessError) as exc:
        reason=str(exc)
        if not reason or not all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789" for c in reason):
            reason="UNTRUSTED_BOOTSTRAP_STATE"
        print("HOLD: "+reason,file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
