#!/usr/bin/env python3
"""RC2 IR-only, journaled exact-version FRP/XHTTP module compatibility repair.

Replace only the proven legacy XHTTP shell module with its pinned reviewed RC2
source and install the pinned fail-closed readiness gate. The existing matching
XHTTP path helper is not modified. No Nginx reload, tunnel Apply, Docker edit,
timer start, or KH writes. Unknown host state always HOLDs before modification.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import urllib.request

REPO="aghajani82/u-opti"
REVIEWED_REF="542cba0d6d79116ef149e8df3ac7c74e7d53efaa"
OLD_SHELL="b381abfb77b3a8cb0cc55d35e54d86369d0d3251"
NEW_SHELL="079cc4994dad84d8f9bb42dd0f11a63cec480578"
PATH_HELPER="2410ee6719375869d367ba80ac36946c098182b3"
GATE_BLOB="ca813fb97f6057f88bec5910eec395810b628d3c"
MOD_DIR=Path("/usr/local/lib/u-opti/modules")
SHELL=MOD_DIR/"smite-frp-xhttp.sh"
HELPER=MOD_DIR/"smite-frp-xhttp-paths.py"
GATE=MOD_DIR/"smite-frp-rc2-gateway-ready.py"
STAGED_GATE=Path("/root/uopti-rc2-frp-xhttp-gate/include-v1/smite-frp-rc2-gateway-ready.py")
SNIPPET=Path("/etc/nginx/u-opti-smite-frp-xhttp.conf")
LOCK=Path("/run/lock/u-opti-smite-engine.lock")
TX_BASE=Path("/var/lib/u-opti/smite-rc2-xhttp-module-upgrade")
TX=TX_BASE/"ir"
BACKUP=TX/"smite-frp-xhttp.before"
RECORD=TX/"record.json"
HEADER=b"# Managed by U-OPTI - Standard FRP XHTTP\n"
CONSENT="AUTHORIZE-IR-RC2-XHTTP-MODULE-UPGRADE"
OPTIN="UOPTI_RC2_IR_XHTTP_MODULE_TRIAL"


class Hold(Exception): pass


def need(ok:bool,why:str):
    if not ok:raise Hold(why)


def blob(data:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()


def secure_dir(path:Path,private:bool=False):
    obj=path.lstat()
    need(stat.S_ISDIR(obj.st_mode) and obj.st_uid==0 and
         not obj.st_mode & 0o022,"UNTRUSTED_PARENT")
    if private:
        need(stat.S_IMODE(obj.st_mode)==0o700,"UNTRUSTED_PRIVATE_DIRECTORY")


def read_root(path:Path,limit:int,mode:int|None=None)->bytes:
    st=path.lstat()
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0
         and st.st_nlink==1 and not st.st_mode & 0o022 and
         st.st_size<=limit,"UNTRUSTED_MODULE_FILE")
    if mode is not None:
        need(stat.S_IMODE(st.st_mode)==mode,"MODULE_MODE_DRIFT")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        with os.fdopen(fd,"rb") as f:
            live=os.fstat(f.fileno())
            need((live.st_dev,live.st_ino)==(st.st_dev,st.st_ino),
                 "MODULE_FILE_CHANGED")
            data=f.read(limit+1)
    except BaseException:
        raise
    need(len(data)<=limit,"MODULE_TOO_LARGE")
    return data


def absent(path:Path)->bool:
    return not path.exists() and not path.is_symlink()


def reviewed_shell()->bytes:
    url=("https://raw.githubusercontent.com/"+REPO+"/"+
         REVIEWED_REF+"/modules/smite-frp-xhttp.sh")
    with urllib.request.urlopen(url,timeout=25) as f:
        raw=f.read(60001)
    need(0<len(raw)<=60000 and blob(raw)==NEW_SHELL,
         "REVIEWED_SHELL_HASH_MISMATCH")
    p=subprocess.run(["bash","-n"],input=raw,capture_output=True,timeout=15)
    need(p.returncode==0,"REVIEWED_SHELL_SYNTAX_INVALID")
    return raw


def gate_check(path:Path):
    p=subprocess.run(["python3","-B",str(path)],
                     capture_output=True,text=True,timeout=60)
    required=("RC2_IR_FRP_XHTTP_GATE=PASS_READ_ONLY",
              "XHTTP_INCLUDE=VERIFIED",
              "SIGNED_WSS_NODE=VERIFIED",
              "STANDARD_FRP_GATEWAY=VERIFIED")
    need(p.returncode==0 and all(x in p.stdout for x in required),
         "SIGNED_RC2_GATE_HOLD")


def timer_idle():
    p=subprocess.run(["systemctl","is-active","u-opti-smite-frp-xhttp.timer"],
                     capture_output=True,text=True,timeout=10)
    need(p.stdout.strip()!="active","SYNC_TIMER_ALREADY_ACTIVE")


def prepare():
    need(os.geteuid()==0 and os.uname().nodename.split(".")[0].lower()=="ir",
         "IR_ROOT_ONLY")
    secure_dir(MOD_DIR)
    secure_dir(STAGED_GATE.parent,private=True)
    need(absent(TX),"TRANSACTION_EXISTS_REVIEW_FIRST")
    need(absent(GATE),"EXISTING_GATE_DO_NOT_REPLACE")
    live=read_root(SHELL,60000)
    need(blob(live)==OLD_SHELL,"UNKNOWN_INSTALLED_XHTTP_SHELL")
    need(blob(read_root(HELPER,60000))==PATH_HELPER,
         "PATH_HELPER_VERSION_DRIFT")
    staged=read_root(STAGED_GATE,20000,mode=0o600)
    need(blob(staged)==GATE_BLOB,"UNREVIEWED_GATE_SOURCE")
    need(read_root(SNIPPET,131072)==HEADER,
         "XHTTP_ROUTES_ALREADY_EXIST")
    timer_idle()
    p=subprocess.run(["bash","-n",str(SHELL)],
                     capture_output=True,timeout=15)
    need(p.returncode==0,"INSTALLED_SHELL_SYNTAX_INVALID")
    gate_check(STAGED_GATE)
    new=reviewed_shell()
    need(absent(GATE) and blob(read_root(SHELL,60000))==OLD_SHELL,
         "MODULE_CHANGED_DURING_PREFLIGHT")
    return live,new,staged,stat.S_IMODE(SHELL.lstat().st_mode)


def sync_dir(path:Path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def create_exact(path:Path,data:bytes,mode:int):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,"wb") as f:
        os.fchmod(f.fileno(),mode)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    sync_dir(path.parent)


def replace_atomic(path:Path,data:bytes,mode:int):
    fd,name=tempfile.mkstemp(prefix=".rc2-frp-",dir=str(path.parent))
    stage=Path(name)
    try:
        with os.fdopen(fd,"wb") as f:
            os.fchmod(f.fileno(),mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(stage,path)
        sync_dir(path.parent)
    finally:
        if stage.exists():stage.unlink()


def journal(x:dict):
    replace_atomic(RECORD,(json.dumps(x,sort_keys=True)+"\n").encode(),0o600)


def record():
    secure_dir(TX_BASE,private=True)
    secure_dir(TX,private=True)
    x=json.loads(read_root(RECORD,8192,mode=0o600))
    need(isinstance(x,dict) and set(x)=={"schema","state","old","new","gate","mode"}
         and x["schema"]==1
         and x["state"] in ("PREPARED","COMMITTED","ROLLED_BACK")
         and x["old"]==OLD_SHELL and x["new"]==NEW_SHELL
         and x["gate"]==GATE_BLOB
         and type(x["mode"]) is int
         and not (x["mode"] & 0o022) and 0o400<=x["mode"]<=0o755,
         "UNTRUSTED_MODULE_JOURNAL")
    need(blob(read_root(BACKUP,60000,mode=0o600))==OLD_SHELL,
         "UNTRUSTED_BACKUP")
    return x


def do_rollback(x:dict):
    current=blob(read_root(SHELL,60000))
    need(current in (OLD_SHELL,NEW_SHELL),"CRITICAL_EXTERNAL_SHELL_CHANGE")
    if not absent(GATE):
        need(blob(read_root(GATE,20000))==GATE_BLOB,
             "CRITICAL_EXTERNAL_GATE_CHANGE")
    need(blob(read_root(SNIPPET,131072))==blob(HEADER),
         "CRITICAL_ACTIVE_ROUTE_PREVENTS_ROLLBACK")
    timer_idle()
    if current!=OLD_SHELL:
        replace_atomic(SHELL,read_root(BACKUP,60000,mode=0o600),x["mode"])
    if not absent(GATE):
        GATE.unlink()
        sync_dir(GATE.parent)
    journal(dict(x,state="ROLLED_BACK"))


def engine_lock():
    need(not LOCK.is_symlink(),"UNTRUSTED_ENGINE_LOCK")
    fd=os.open(LOCK,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    st=os.fstat(fd)
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0
         and stat.S_IMODE(st.st_mode)==0o600,"UNTRUSTED_ENGINE_LOCK")
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(fd)
        raise Hold("ENGINE_LOCK_BUSY") from e
    return fd


def apply():
    lock=engine_lock()
    try:
        live,new,staged,mode=prepare()
        secure_dir(TX_BASE.parent)
        need(absent(TX_BASE) or TX_BASE.is_dir(),"UNTRUSTED_TX_ROOT")
        if absent(TX_BASE):TX_BASE.mkdir(mode=0o700)
        secure_dir(TX_BASE,private=True)
        TX.mkdir(mode=0o700)
        secure_dir(TX,private=True)
        create_exact(BACKUP,live,0o600)
        x={"schema":1,"state":"PREPARED","old":OLD_SHELL,
           "new":NEW_SHELL,"gate":GATE_BLOB,"mode":mode}
        create_exact(RECORD,(json.dumps(x,sort_keys=True)+"\n").encode(),0o600)
        try:
            need(absent(GATE) and blob(read_root(SHELL,60000))==OLD_SHELL,
                 "MODULE_CHANGED_BEFORE_INSTALL")
            create_exact(GATE,staged,0o644)
            replace_atomic(SHELL,new,mode)
            need(blob(read_root(SHELL,60000))==NEW_SHELL and
                 blob(read_root(GATE,20000))==GATE_BLOB,
                 "INSTALLED_MODULE_HASH_MISMATCH")
            gate_check(GATE)
            p=subprocess.run(["bash","-n",str(SHELL)],
                             capture_output=True,timeout=15)
            need(p.returncode==0,"INSTALLED_MODULE_SYNTAX_HOLD")
            journal(dict(x,state="COMMITTED"))
        except Exception as exc:
            do_rollback(x)
            raise Hold("MODULE_UPGRADE_FAILED_ROLLED_BACK") from exc
        print("RC2_IR_XHTTP_MODULE_UPGRADE=COMMITTED")
        print("MODULE_RC2_GATE=VERIFIED")
        print("XHTTP_ROUTES_PUBLISHED=NONE")
        print("NGINX_RELOAD=NOT_PERFORMED")
        print("TUNNEL_APPLY=NOT_PERFORMED")
        print("SYNC_TIMER=NOT_STARTED")
    finally:os.close(lock)


def verify():
    x=record()
    need(x["state"]=="COMMITTED","MODULE_UPGRADE_NOT_COMMITTED")
    need(blob(read_root(SHELL,60000))==NEW_SHELL and
         blob(read_root(GATE,20000))==GATE_BLOB and
         blob(read_root(HELPER,60000))==PATH_HELPER,
         "LIVE_MODULE_VERSION_DRIFT")
    gate_check(GATE)
    print("RC2_IR_XHTTP_MODULE_VERIFY=PASS_READ_ONLY")
    print("LIVE_CHANGES=NONE")


def rollback():
    lock=engine_lock()
    try:
        x=record()
        need(x["state"] in ("PREPARED","COMMITTED"),
             "TRANSACTION_NOT_ROLLBACKABLE")
        do_rollback(x)
        print("RC2_IR_XHTTP_MODULE_ROLLBACK=PASS")
    finally:os.close(lock)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action",choices=("plan","apply","verify","rollback"))
    args=ap.parse_args()
    try:
        if args.action=="plan":
            prepare()
            print("RC2_IR_XHTTP_MODULE_UPGRADE_PLAN=PASS_READ_ONLY")
            print("LOCAL_SHELL=REVIEWED_OLD_VERSION")
            print("LOCAL_PATH_HELPER=REVIEWED_MATCH")
            print("SIGNED_GATE_STAGING=VERIFIED")
            print("FILES_MODIFIED=NONE")
        elif args.action=="verify":verify()
        else:
            need(sys.stdin.isatty(),"INTERACTIVE_APPROVAL_REQUIRED")
            need(os.environ.get(OPTIN)=="YES","EXPLICIT_OPT_IN_REQUIRED")
            need(input("Type "+CONSENT+" to authorize: ").strip()==CONSENT,
                 "OPERATOR_CANCELLED")
            if args.action=="apply":apply()
            else:rollback()
        return 0
    except (Hold,OSError,ValueError,TypeError,KeyError,UnicodeError,
            subprocess.SubprocessError) as e:
        reason=str(e)
        if not reason or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789"
                             for c in reason):
            reason="UNTRUSTED_UPGRADE_STATE"
        print("HOLD: "+reason,file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
