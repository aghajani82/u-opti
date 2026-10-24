#!/usr/bin/env python3
"""Guarded IR RC2 two-vhost XHTTP include/snippet transaction.

Public 443 SNI+IP routing, 8444 KH-WSS, Signed Node, and FRP tunnels stay
untouched. Only the trusted managed 8443 Panel backend and one EMPTY Nginx
include file may change; no XHTTP location is published by this controller.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
GATE_PATH=HERE/"smite-frp-rc2-gateway-ready.py"
spec=importlib.util.spec_from_file_location("uopti_rc2_dual_gate",GATE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("HOLD: GATE_MODULE_MISSING")
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

BACKEND=Path(gate.ORIGIN)
SNIPPET=Path(gate.SNIPPET)
TX_ROOT=Path("/var/lib/u-opti/smite-rc2-xhttp-include")
TX_DIR=TX_ROOT/"ir"
BACKUP=TX_DIR/"panel-backend.before"
RECORD=TX_DIR/"record.json"
LOCK=Path("/run/lock/u-opti-smite-engine.lock")
INCLUDE=b"    include /etc/nginx/u-opti-smite-frp-xhttp.conf;\n"
ROOT=b"    location / {\n"
HEADER=b"# Managed by U-OPTI - Standard FRP XHTTP\n"
CONSENT="AUTHORIZE-IR-RC2-XHTTP-INCLUDE"
OPTIN="UOPTI_RC2_IR_XHTTP_INCLUDE_TRIAL"


class Hold(Exception):pass


def need(value:bool,reason:str)->None:
    if not value:raise Hold(reason)


def digest(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def absent(path:Path)->bool:
    return not path.exists() and not path.is_symlink()


def directory(path:Path, *, private:bool=False)->None:
    obj=path.lstat()
    need(stat.S_ISDIR(obj.st_mode) and obj.st_uid==0 and
         not (obj.st_mode & 0o022),"UNTRUSTED_TRANSACTION_DIRECTORY")
    if private:
        need(stat.S_IMODE(obj.st_mode)==0o700,"UNTRUSTED_PRIVATE_DIRECTORY")


def trusted(path:Path,limit:int=131072,mode:int|None=None)->bytes:
    return gate.read_root_file(path,max_bytes=limit,mode=mode)


def write_new(path:Path,data:bytes,mode:int)->None:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,"wb") as handle:
        os.fchmod(handle.fileno(),mode)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    sync_dir(path.parent)


def sync_dir(path:Path)->None:
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def replace_known(path:Path,data:bytes,mode:int)->None:
    # Caller validates original SHA and owner, and holds the common engine lock.
    fd,name=tempfile.mkstemp(prefix=".rc2-xhttp-",dir=str(path.parent))
    stage=Path(name)
    try:
        with os.fdopen(fd,"wb") as handle:
            os.fchmod(handle.fileno(),mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(stage,path)
        sync_dir(path.parent)
    finally:
        if stage.exists():
            stage.unlink()


def check_host()->None:
    need(os.geteuid()==0 and os.uname().nodename.split(".")[0].lower()=="ir",
         "IR_ROOT_ONLY")
    directory(BACKEND.parent)
    directory(SNIPPET.parent)


def candidate(before:bytes)->bytes:
    need(before.count(ROOT)==1,"UNKNOWN_PANEL_LOCATION_LAYOUT")
    need(INCLUDE not in before and
         b"u-opti-smite-frp-xhttp.conf;" not in before,
         "XHTTP_INCLUDE_ALREADY_PRESENT")
    return before.replace(ROOT,INCLUDE+b"\n"+ROOT,1)


def probe_panel()->None:
    try:
        p=subprocess.run(
            ["curl","-q","--noproxy","*","-4","--http1.1",
             "--connect-timeout","6","--max-time","14","-sS",
             "-o","/dev/null","-w","%{http_code}",
             "--resolve","ir.kolbe1.ir:443:127.0.0.1",
             "https://ir.kolbe1.ir/"],
            text=True,capture_output=True,timeout=18)
    except (OSError,subprocess.TimeoutExpired) as e:
        raise Hold("PANEL_HTTPS_PROBE_FAILED") from e
    need(p.returncode==0 and p.stdout.strip().isdigit() and
         200 <= int(p.stdout.strip()) < 400,
         "PANEL_HTTPS_PROBE_FAILED")


def nginx_test()->None:
    try:
        p=subprocess.run(["nginx","-t"],text=True,capture_output=True,timeout=25)
    except (OSError,subprocess.TimeoutExpired) as e:
        raise Hold("NGINX_CONFIG_INVALID") from e
    need(p.returncode==0,"NGINX_CONFIG_INVALID")


def reload_nginx()->None:
    try:
        p=subprocess.run(["systemctl","reload","nginx"],text=True,
                         capture_output=True,timeout=25)
    except (OSError,subprocess.TimeoutExpired) as e:
        raise Hold("NGINX_RELOAD_FAILED") from e
    need(p.returncode==0,"NGINX_RELOAD_FAILED")


def acquire_lock():
    need(not LOCK.is_symlink(),"UNTRUSTED_ENGINE_LOCK")
    fd=os.open(LOCK,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    st=os.fstat(fd)
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0 and
         stat.S_IMODE(st.st_mode)==0o600,"UNTRUSTED_ENGINE_LOCK")
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(fd)
        raise Hold("ENGINE_LOCK_BUSY") from e
    return fd


def tx_prepare(before:bytes,after:bytes)->dict:
    need(absent(TX_ROOT) or TX_ROOT.is_dir(),"TRANSACTION_ROOT_UNTRUSTED")
    if absent(TX_ROOT):TX_ROOT.mkdir(mode=0o700)
    directory(TX_ROOT,private=True)
    need(absent(TX_DIR),"EXISTING_TRANSACTION_REQUIRES_REVIEW")
    TX_DIR.mkdir(mode=0o700)
    directory(TX_DIR,private=True)
    write_new(BACKUP,before,0o600)
    data={
        "schema":1,"state":"PREPARED","before_sha":digest(before),
        "after_sha":digest(after),"snippet_sha":digest(HEADER),
    }
    write_new(RECORD,(json.dumps(data,sort_keys=True)+"\n").encode(),0o600)
    return data


def get_record()->dict:
    directory(TX_ROOT,private=True)
    directory(TX_DIR,private=True)
    x=json.loads(trusted(RECORD,8192,0o600))
    need(isinstance(x,dict) and set(x)=={
        "schema","state","before_sha","after_sha","snippet_sha"
    } and x.get("schema")==1 and
         x.get("state") in ("PREPARED","COMMITTED","ROLLED_BACK")
         and all(isinstance(x[k],str) and len(x[k])==64
                 for k in ("before_sha","after_sha","snippet_sha")),
         "TRANSACTION_RECORD_INVALID")
    before=trusted(BACKUP,131072,0o600)
    need(digest(before)==x["before_sha"] and
         digest(candidate(before))==x["after_sha"] and
         x["snippet_sha"]==digest(HEADER),
         "TRANSACTION_BACKUP_DRIFT")
    return x


def update_state(x:dict,value:str)->None:
    now=dict(x,state=value)
    need(json.loads(trusted(RECORD,8192,0o600))==x,
         "TRANSACTION_JOURNAL_CHANGED")
    replace_known(RECORD,(json.dumps(now,sort_keys=True)+"\n").encode(),0o600)


def before()->tuple[bytes,bytes]:
    check_host()
    need(absent(RECORD) and absent(TX_DIR),"EXISTING_TRANSACTION_REQUIRES_REVIEW")
    need(absent(SNIPPET),"EXISTING_XHTTP_SNIPPET_REFUSED")
    gate.audit(allow_missing_snippet=True)
    original=trusted(BACKEND,131072)
    need(stat.S_IMODE(BACKEND.lstat().st_mode)==0o644,
         "PANEL_BACKEND_MODE_DRIFT")
    modified=candidate(original)
    nginx_test()
    probe_panel()
    need(absent(SNIPPET) and absent(RECORD),"PREFLIGHT_STATE_CHANGED")
    return original,modified


def rollback_written(x:dict, *, reload:bool)->None:
    before_bytes=trusted(BACKUP,131072,0o600)
    backend_bytes=trusted(BACKEND,131072)
    need(digest(backend_bytes) in (x["before_sha"],x["after_sha"]),
         "CRITICAL_BACKEND_MODIFIED_EXTERNALLY")
    if not absent(SNIPPET):
        need(digest(trusted(SNIPPET,131072))==x["snippet_sha"],
             "CRITICAL_SNIPPET_MODIFIED_EXTERNALLY")
    if digest(backend_bytes)!=x["before_sha"]:
        replace_known(BACKEND,before_bytes,0o644)
    if not absent(SNIPPET):
        SNIPPET.unlink()
        sync_dir(SNIPPET.parent)
    nginx_test()
    if reload:
        reload_nginx()
        probe_panel()
    update_state(x,"ROLLED_BACK")


def apply()->None:
    fd=acquire_lock()
    try:
        original,modified=before()
        x=tx_prepare(original,modified)
        try:
            need(trusted(BACKEND,131072)==original and absent(SNIPPET),
                 "LIVE_STATE_CHANGED_BEFORE_EDIT")
            write_new(SNIPPET,HEADER,0o644)
            need(trusted(BACKEND,131072)==original,
                 "PANEL_BACKEND_CHANGED_BEFORE_REPLACE")
            replace_known(BACKEND,modified,0o644)
            gate.audit()
            nginx_test()
            reload_nginx()
            probe_panel()
            update_state(x,"COMMITTED")
        except Exception as exc:
            # Recovery is deliberately fail-closed. A modified snippet or
            # backend with an unknown SHA must never be deleted or replaced.
            rollback_written(x,reload=True)
            raise Hold("INCLUDE_FAILED_ROLLED_BACK") from exc
        print("RC2_IR_XHTTP_INCLUDE=COMMITTED")
        print("SIGNED_WSS_NODE=VERIFIED")
        print("PANEL_HTTPS=PASS")
        print("NGINX_TEST=PASS")
        print("WSS_8444=UNCHANGED")
        print("XHTTP_ROUTES_PUBLISHED=NONE")
    finally:os.close(fd)


def verify()->None:
    check_host()
    x=get_record()
    need(x["state"]=="COMMITTED","TRANSACTION_NOT_COMMITTED")
    need(digest(trusted(BACKEND))==x["after_sha"] and
         digest(trusted(SNIPPET))==x["snippet_sha"],
         "LIVE_INCLUDE_DRIFT")
    gate.audit()
    nginx_test()
    probe_panel()
    print("RC2_IR_XHTTP_INCLUDE_VERIFY=PASS_READ_ONLY")
    print("SIGNED_WSS_NODE=VERIFIED")
    print("PANEL_HTTPS=PASS")
    print("LIVE_CHANGES=NONE")


def rollback()->None:
    fd=acquire_lock()
    try:
        check_host()
        x=get_record()
        need(x["state"] in ("PREPARED","COMMITTED"),
             "TRANSACTION_NOT_ROLLBACKABLE")
        rollback_written(x,reload=True)
        print("RC2_IR_XHTTP_INCLUDE_ROLLBACK=PASS")
        print("PANEL_HTTPS=PASS")
    finally:os.close(fd)


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("plan","apply","verify","rollback"))
    args=parser.parse_args()
    try:
        if args.action=="plan":
            before()
            print("RC2_IR_XHTTP_INCLUDE_PLAN=PASS_READ_ONLY")
            print("WSS_8444=UNCHANGED")
            print("XHTTP_ROUTES_PUBLISHED=NONE")
            print("LIVE_CHANGES=NONE")
        elif args.action=="verify":
            verify()
        else:
            need(sys.stdin.isatty(),"INTERACTIVE_APPROVAL_REQUIRED")
            need(os.environ.get(OPTIN)=="YES","EXPLICIT_OPT_IN_REQUIRED")
            need(input("Type "+CONSENT+" to authorize: ").strip()==CONSENT,
                 "OPERATOR_CANCELLED")
            if args.action=="apply":apply()
            else:rollback()
        return 0
    except (Hold,gate.GateHold,OSError,ValueError,KeyError,TypeError,
            UnicodeError,subprocess.SubprocessError) as exc:
        reason=str(exc)
        if not reason or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789"
                             for ch in reason):
            reason="UNTRUSTED_TRANSACTION_STATE"
        print("HOLD: "+reason,file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
