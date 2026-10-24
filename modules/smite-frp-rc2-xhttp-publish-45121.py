#!/usr/bin/env python3
"""Guarded IR-only RC2 XHTTP /45121/www publisher: one-time, reversible.

plan: no service or persistent file writes.
apply: explicit interactive approval, shared engine flock, pinned reviewed
render, private journal+backup, atomic snippet replace, nginx test/reload,
verified Panel HTTPS, auto rollback on failed postconditions.
No tunnel reapply, timer enable, KH or Grandoptical changes.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

MOD=Path("/usr/local/lib/u-opti/modules")
SHELL=MOD/"smite-frp-xhttp.sh"
HELPER=MOD/"smite-frp-xhttp-paths.py"
GATE=MOD/"smite-frp-rc2-gateway-ready.py"
SNIP=Path("/etc/nginx/u-opti-smite-frp-xhttp.conf")
BACKEND=Path("/etc/nginx/conf.d/u-opti-smite-panel-backend.conf")
REGISTRY=Path("/etc/u-opti/smite/frp-xhttp-paths.json")
LOCK=Path("/run/lock/u-opti-smite-engine.lock")
TXROOT=Path("/var/lib/u-opti/smite-rc2-xhttp-route-publish")
TX=TXROOT/"ir-45121"
BACKUP=TX/"snippet.before.conf"
JOURNAL=TX/"record.json"
EXPECTED={
    SHELL:"079cc4994dad84d8f9bb42dd0f11a63cec480578",
    HELPER:"2410ee6719375869d367ba80ac36946c098182b3",
    GATE:"ca813fb97f6057f88bec5910eec395810b628d3c",
}
HEADER=b"# Managed by U-OPTI - Standard FRP XHTTP\n"
INCLUDE=b"    include /etc/nginx/u-opti-smite-frp-xhttp.conf;\n"
CONSENT={"apply":"PUBLISH-IR-XHTTP-45121",
         "rollback":"ROLLBACK-IR-XHTTP-45121"}
OPTIN="UOPTI_RC2_IR_XHTTP_45121_PUBLISH_TRIAL"


class Hold(Exception):pass


def need(value,why):
    if not value:raise Hold(why)


def git_blob(raw):
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def absent(path):
    return not path.exists() and not path.is_symlink()


def safe_dir(path,private=False):
    st=path.lstat()
    need(stat.S_ISDIR(st.st_mode) and st.st_uid==0 and not st.st_mode & 0o022,
         "UNTRUSTED_DIRECTORY")
    if private:need(stat.S_IMODE(st.st_mode)==0o700,
                    "UNTRUSTED_PRIVATE_DIRECTORY")


def safe_read(path,maximum,mode=None):
    st=path.lstat()
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1
         and not st.st_mode & 0o022 and st.st_size<=maximum,
         "UNTRUSTED_FILE")
    if mode is not None:need(stat.S_IMODE(st.st_mode)==mode,
                             "UNTRUSTED_FILE_MODE")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as f:
        live=os.fstat(f.fileno())
        need((live.st_dev,live.st_ino)==(st.st_dev,st.st_ino),
             "FILE_CHANGED")
        data=f.read(maximum+1)
    need(len(data)<=maximum,"FILE_OVERSIZE")
    return data


def run(argv,timeout=30):
    try:
        p=subprocess.run(argv,capture_output=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise Hold("COMMAND_UNAVAILABLE") from exc
    need(p.returncode==0,"SUBPROCESS_FAILED")
    return p.stdout


def check_gate():
    r=run(["python3","-B",str(GATE)],60)
    need(b"RC2_IR_FRP_XHTTP_GATE=PASS_READ_ONLY" in r
         and b"XHTTP_INCLUDE=VERIFIED" in r,
         "SIGNED_GATE_HOLD")


def timer_inactive():
    p=subprocess.run(["systemctl","is-active",
                      "u-opti-smite-frp-xhttp.timer"],
                     capture_output=True,timeout=12)
    need(p.stdout.strip()!=b"active","SYNC_TIMER_ALREADY_ACTIVE")


def nginx_test():run(["nginx","-t"],30)


def nginx_reload():run(["systemctl","reload","nginx"],30)


def panel_check():
    data=run(["curl","-q","--noproxy","*","-4","--http1.1",
              "--connect-timeout","5","--max-time","14","-sS",
              "-o","/dev/null","-w","%{http_code}",
              "--resolve","ir.kolbe1.ir:443:127.0.0.1",
              "https://ir.kolbe1.ir/"],20)
    need(re.fullmatch(rb"[23][0-9][0-9]",data.strip()),
         "PANEL_HTTPS_NOT_HEALTHY")


def listeners():
    for port in (7000,45121):
        data=run(["ss","-H","-lnt",f"( sport = :{port} )"],12)
        addresses=[row.split()[3].decode("ascii","ignore")
                   for row in data.splitlines() if len(row.split())>=4]
        need(addresses,"REQUIRED_FRP_LISTENER_MISSING")
        need(all(x.startswith(("127.","[::1]:","::1:"))
                 for x in addresses),"EXTERNAL_FRP_BIND_REFUSED")


def validate_rendered(raw):
    need(raw.startswith(HEADER),"ROUTE_HEADER_DRIFT")
    text=raw.decode("utf-8")
    locations=re.findall(r"(?m)^\s*location\s+(=|\^~)\s+(\S+)\s*\{",
                         text)
    need(locations==[("=","/45121/www"),("^~","/45121/www/")],
         "ROUTE_LOCATIONS_DRIFT")
    targets=re.findall(r"(?m)^\s*proxy_pass\s+([^;]+);",text)
    need(targets==["http://127.0.0.1:45121"]*2,"ROUTE_TARGET_DRIFT")


def host_and_pins():
    need(os.geteuid()==0 and os.uname().nodename.split(".")[0].lower()=="ir",
         "IR_ROOT_ONLY")
    for p in (MOD,SNIP.parent,BACKEND.parent,REGISTRY.parent,
              TXROOT.parent):
        safe_dir(p)
    for p,expected in EXPECTED.items():
        need(git_blob(safe_read(p,60000))==expected,
             "INSTALLED_MODULE_HASH_DRIFT")


def render_candidate():
    # Never reveal or persist the raw signed Node tunnels state outside a
    # private temporary directory. Only one 45121 location is admissible.
    state=run(["docker","exec","smite-node","cat",
               "/var/lib/smite-node/tunnels.json"],25)
    need(0<len(state)<=1048576 and isinstance(json.loads(state),dict),
         "TUNNEL_STATE_HOLD")
    with tempfile.TemporaryDirectory(prefix="uopti-rc2-route-",dir="/run") as t:
        source=Path(t)/"tunnels.json"
        output=Path(t)/"routes.conf"
        fd=os.open(source,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"wb") as f:f.write(state)
        run(["python3","-B",str(HELPER),"render",str(source),str(output)],30)
        raw=output.read_bytes()
    validate_rendered(raw)
    return raw


def preflight():
    host_and_pins()
    need(absent(TX),"EXISTING_PUBLISH_TRANSACTION")
    need(safe_read(SNIP,131072,0o644)==HEADER,"SNIPPET_NOT_EMPTY")
    need(safe_read(BACKEND,131072).count(INCLUDE)==1,
         "PANEL_INCLUDE_DRIFT")
    need(json.loads(safe_read(REGISTRY,65536,0o600))==
         {"45121":"/45121/www"},"SAVED_PROFILE_DRIFT")
    check_gate()
    timer_inactive()
    listeners()
    nginx_test()
    panel_check()
    candidate=render_candidate()
    need(safe_read(SNIP,131072,0o644)==HEADER,
         "SNIPPET_CHANGED_DURING_PLAN")
    return candidate


def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def create_exact(path,data,mode):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,"wb") as f:
        os.fchmod(f.fileno(),mode)
        f.write(data);f.flush();os.fsync(f.fileno())
    sync_dir(path.parent)


def atomic_replace(path,data,mode=0o644):
    fd,name=tempfile.mkstemp(prefix=".uopti-rc2-route-",dir=str(path.parent))
    temp=Path(name)
    try:
        with os.fdopen(fd,"wb") as f:
            os.fchmod(f.fileno(),mode)
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        sync_dir(path.parent)
    finally:
        if temp.exists():temp.unlink()


def acquire_lock():
    st=LOCK.lstat()
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0
         and stat.S_IMODE(st.st_mode)==0o600,"ENGINE_LOCK_UNTRUSTED")
    fd=os.open(LOCK,os.O_RDWR|os.O_NOFOLLOW)
    live=os.fstat(fd)
    need((st.st_ino,st.st_dev)==(live.st_ino,live.st_dev),
         "ENGINE_LOCK_CHANGED")
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise Hold("ENGINE_LOCK_BUSY") from exc
    return fd


def create_record(raw):
    if absent(TXROOT):TXROOT.mkdir(mode=0o700)
    safe_dir(TXROOT,private=True)
    need(absent(TX),"EXISTING_PUBLISH_TRANSACTION")
    TX.mkdir(mode=0o700)
    safe_dir(TX,private=True)
    create_exact(BACKUP,HEADER,0o600)
    data={"schema":1,"state":"PREPARED",
          "previous_sha":sha(HEADER),"published_sha":sha(raw),
          "port":45121,"path":"/45121/www"}
    create_exact(JOURNAL,(json.dumps(data,sort_keys=True)+"\n").encode(),
                 0o600)
    return data


def record():
    safe_dir(TXROOT,private=True)
    safe_dir(TX,private=True)
    doc=json.loads(safe_read(JOURNAL,8192,0o600))
    need(type(doc) is dict
         and set(doc)=={"schema","state","previous_sha","published_sha",
                        "port","path"}
         and doc["schema"]==1 and doc["state"] in
         ("PREPARED","COMMITTED","ROLLED_BACK")
         and doc["port"]==45121 and doc["path"]=="/45121/www"
         and doc["previous_sha"]==sha(HEADER)
         and re.fullmatch("[a-f0-9]{64}",str(doc["published_sha"])),
         "TRANSACTION_JOURNAL_DRIFT")
    need(safe_read(BACKUP,131072,0o600)==HEADER,"BACKUP_DRIFT")
    return doc


def update_record(doc,new_state):
    need(json.loads(safe_read(JOURNAL,8192,0o600))==doc,
         "JOURNAL_CHANGED_EXTERNALLY")
    new=dict(doc,state=new_state)
    atomic_replace(JOURNAL,(json.dumps(new,sort_keys=True)+"\n").encode(),
                   0o600)


def restore(doc):
    current=safe_read(SNIP,131072,0o644)
    need(sha(current) in (doc["previous_sha"],doc["published_sha"]),
         "CRITICAL_EXTERNAL_SNIPPET_CHANGE")
    if sha(current)==doc["published_sha"]:
        atomic_replace(SNIP,safe_read(BACKUP,131072,0o600))
    nginx_test()
    nginx_reload()
    panel_check()
    update_record(doc,"ROLLED_BACK")


def apply():
    lock=acquire_lock()
    try:
        raw=preflight()
        doc=create_record(raw)
        try:
            need(safe_read(SNIP,131072,0o644)==HEADER,
                 "SNIPPET_CHANGED_BEFORE_WRITE")
            atomic_replace(SNIP,raw)
            nginx_test()
            nginx_reload()
            panel_check()
            need(safe_read(SNIP,131072,0o644)==raw,
                 "POST_RELOAD_ROUTES_CHANGED")
            update_record(doc,"COMMITTED")
        except Exception as exc:
            try:restore(doc)
            except Exception as recovery:
                raise Hold("CRITICAL_MANUAL_ROUTE_RECOVERY") from recovery
            raise Hold("ROUTE_PUBLISH_FAILED_ROLLED_BACK") from exc
        print("RC2_XHTTP_45121_PUBLISH=COMMITTED")
        print("XHTTP_LOCATIONS=EXACT_AND_SUBPATH")
        print("UPSTREAM=LOOPBACK_45121")
        print("PANEL_HTTPS=PASS")
        print("NGINX_TEST=PASS")
        print("TUNNEL_REAPPLY=NOT_PERFORMED")
        print("XHTTP_TIMER=NOT_STARTED")
    finally:os.close(lock)


def verify():
    doc=record()
    need(doc["state"]=="COMMITTED","PUBLISH_NOT_COMMITTED")
    raw=safe_read(SNIP,131072,0o644)
    need(sha(raw)==doc["published_sha"],"LIVE_SNIPPET_DRIFT")
    validate_rendered(raw)
    check_gate();nginx_test();panel_check()
    print("RC2_XHTTP_45121_PUBLISH_VERIFY=PASS_READ_ONLY")
    print("LIVE_CHANGES=NONE")


def rollback():
    lock=acquire_lock()
    try:
        host_and_pins();timer_inactive()
        doc=record()
        need(doc["state"]=="COMMITTED","ROLLBACK_STATE_HOLD")
        restore(doc)
        print("RC2_XHTTP_45121_ROLLBACK=PASS")
    finally:os.close(lock)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("plan","apply","verify","rollback"))
    args=p.parse_args()
    try:
        if args.action=="plan":
            preflight()
            print("RC2_XHTTP_45121_PUBLISH_PLAN=PASS_READ_ONLY")
            print("SIGNED_GATE=PASS")
            print("RENDERED_ROUTES=45121_ONLY")
            print("ENGINE_LOCK=NOT_ACQUIRED")
            print("LIVE_CHANGES=NONE")
        elif args.action=="verify":verify()
        else:
            need(sys.stdin.isatty(),"TTY_REQUIRED")
            need(os.environ.get(OPTIN)=="YES","OPERATOR_OPT_IN_REQUIRED")
            need(input("Type "+CONSENT[args.action]+" to authorize: ").strip()
                 == CONSENT[args.action],"OPERATOR_CANCELLED")
            if args.action=="apply":apply()
            else:rollback()
        return 0
    except (Hold,OSError,ValueError,TypeError,KeyError,UnicodeError,
            json.JSONDecodeError,subprocess.SubprocessError) as exc:
        reason=str(exc)
        if not re.fullmatch(r"[A-Z0-9_]{1,100}",reason):
            reason="UNTRUSTED_RUNTIME_STATE"
        print("HOLD: "+reason,file=sys.stderr)
        print("RC2_XHTTP_45121_TRANSACTION=HOLD")
        return 2


if __name__=="__main__":
    raise SystemExit(main())
