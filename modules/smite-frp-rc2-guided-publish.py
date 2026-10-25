#!/usr/bin/env python3
"""Signed RC2 IR-only, one-port-at-a-time XHTTP route admission (not a daemon).

A beginner's selected FRP port must ALREADY be an applied signed Smite Node
server port and must have a saved, validated IR XHTTP path. Never invent a
port/path, create a tunnel, restart Docker, modify KH, or enable a timer.

Existing canonical routes are preserved byte-for-byte. Only ONE newly applied
port may be published in a transaction. More unapproved changes => HOLD.
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

MODULES=Path("/usr/local/lib/u-opti/modules")
GATE=MODULES/"smite-frp-rc2-gateway-ready.py"
HELPER=MODULES/"smite-frp-xhttp-paths.py"
FRP_MODULE=MODULES/"smite-frp-xhttp.sh"
PINNED={
    GATE:"ca813fb97f6057f88bec5910eec395810b628d3c",
    HELPER:"2410ee6719375869d367ba80ac36946c098182b3",
    FRP_MODULE:"079cc4994dad84d8f9bb42dd0f11a63cec480578",
}
SNIPPET=Path("/etc/nginx/u-opti-smite-frp-xhttp.conf")
BACKEND=Path("/etc/nginx/conf.d/u-opti-smite-panel-backend.conf")
REGISTRY=Path("/etc/u-opti/smite/frp-xhttp-paths.json")
LOCK=Path("/run/lock/u-opti-smite-engine.lock")
TX_ROOT=Path("/var/lib/u-opti/smite-rc2-frp-guided-publish")
HEADER="# Managed by U-OPTI - Standard FRP XHTTP\n"
INCLUDE="    include /etc/nginx/u-opti-smite-frp-xhttp.conf;\n"
OPTIN="UOPTI_RC2_IR_FRP_GUIDED_PUBLISH_TRIAL"

class Hold(Exception):pass

def need(condition,label):
    if not condition:raise Hold(label)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def absent(path):
    return not path.exists() and not path.is_symlink()

def trusted_dir(path,private=False):
    s=path.lstat()
    need(stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode & 0o022,
         "UNTRUSTED_DIRECTORY")
    if private:need(stat.S_IMODE(s.st_mode)==0o700,"UNTRUSTED_PRIVATE_DIR")

def trusted_read(path,maximum=131072,mode=None):
    s=path.lstat()
    need(stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1
         and not s.st_mode & 0o022 and s.st_size<=maximum,"UNTRUSTED_FILE")
    if mode is not None:need(stat.S_IMODE(s.st_mode)==mode,
                             "UNTRUSTED_FILE_MODE")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as file:
        t=os.fstat(file.fileno())
        need((t.st_dev,t.st_ino)==(s.st_dev,s.st_ino),"READ_RACE")
        raw=file.read(maximum+1)
    need(len(raw)<=maximum,"FILE_LIMIT")
    return raw

def execute(argv,timeout=30):
    try:
        p=subprocess.run(argv,capture_output=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired) as e:
        raise Hold("COMMAND_TIMEOUT_OR_UNAVAILABLE") from e
    need(p.returncode==0,"COMMAND_FAILED")
    return p.stdout

def host():
    need(os.geteuid()==0 and os.uname().nodename.split(".")[0].lower()=="ir",
         "IR_ROOT_ONLY")
    for p in (MODULES,SNIPPET.parent,BACKEND.parent,REGISTRY.parent,
              TX_ROOT.parent):
        trusted_dir(p)
    for path,sha in PINNED.items():
        need(blob(trusted_read(path,65536))==sha,"REVIEWED_MODULE_DRIFT")

def signed_gate():
    x=execute(["python3","-B",str(GATE)],60)
    need(b"RC2_IR_FRP_XHTTP_GATE=PASS_READ_ONLY" in x,
         "SIGNED_GATE_HOLD")

def timer_idle():
    p=subprocess.run(["systemctl","is-active",
                      "u-opti-smite-frp-xhttp.timer"],
                     capture_output=True,timeout=12)
    need(p.stdout.strip()!=b"active","AUTO_SYNC_TIMER_ACTIVE")

def listener(port):
    data=execute(["ss","-H","-lnt",f"( sport = :{port} )"],12)
    addrs=[row.split()[3].decode("ascii","ignore")
           for row in data.splitlines() if len(row.split())>=4]
    need(addrs,"LISTENER_ABSENT")
    need(all(x.startswith(("127.","[::1]:","::1:"))
             for x in addrs),"PUBLIC_PORT_BIND_REJECTED")

def nginx_test():
    execute(["nginx","-t"],30)

def reload_nginx():
    execute(["systemctl","reload","nginx"],30)

def panel_health():
    out=execute(["curl","-q","--noproxy","*","-4","--http1.1",
                 "--connect-timeout","5","--max-time","14","-sS",
                 "-o","/dev/null","-w","%{http_code}",
                 "--resolve","ir.kolbe1.ir:443:127.0.0.1",
                 "https://ir.kolbe1.ir/"],20)
    need(re.fullmatch(rb"[23]\d\d",out.strip()),"PANEL_HTTPS_HOLD")

def lock_engine():
    st=LOCK.lstat()
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0
         and stat.S_IMODE(st.st_mode)==0o600,"ENGINE_LOCK_POLICY")
    fd=os.open(LOCK,os.O_RDWR|os.O_NOFOLLOW)
    live=os.fstat(fd)
    need((live.st_dev,live.st_ino)==(st.st_dev,st.st_ino),
         "ENGINE_LOCK_CHANGED")
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(fd)
        raise Hold("ENGINE_LOCK_BUSY") from e
    return fd

# The exact reviewed renderer has two canonical locations per forwarded port:
# an exact path and its trailing-slash subpath, both proxy to loopback.
# Require its full template with no additional Nginx directives.
BLOCK=re.compile(
    r"\n    location = (?P<path>/[A-Za-z0-9_/-]+) \{\n"
    r"(?P<first>(?:        [^\n]+\n)+)"
    r"    \}\n\n"
    r"    location \^~ (?P=path)/ \{\n"
    r"(?P<second>(?:        [^\n]+\n)+)"
    r"    \}\n"
)

def parse_blocks(raw):
    text=raw.decode("utf-8")
    need(text.startswith(HEADER),"ROUTE_HEADER_INVALID")
    remainder=text[len(HEADER):]
    routes={}
    cursor=0
    while cursor<len(remainder):
        m=BLOCK.match(remainder,cursor)
        need(m is not None,"NONCANONICAL_NGINX_ROUTE")
        for key in ("first","second"):
            section=m.group(key)
            targets=re.findall(r"(?m)^        proxy_pass http://127\.0\.0\.1:(\d+);$",
                               section)
            need(len(targets)==1,"ROUTE_UPSTREAM_INVALID")
            port=int(targets[0])
            need(1024<=port<=65535,"ROUTE_PORT_INVALID")
            if key=="first":first_port=port
            else:need(port==first_port,"ROUTE_SPLIT_UPSTREAM")
            # Reject any template extension not emitted by the reviewed
            # renderer; extra custom headers/dangerous directives HOLD.
            expected=(
                f"        proxy_pass http://127.0.0.1:{port};\n"
                "        proxy_http_version 1.1;\n"
                "        proxy_set_header Host $host;\n"
                "        proxy_set_header X-Forwarded-Proto https;\n"
                "        proxy_buffering off;\n"
                "        proxy_request_buffering off;\n"
                "        proxy_connect_timeout 10s;\n"
                "        proxy_read_timeout 3600s;\n"
                "        proxy_send_timeout 3600s;\n"
            )
            need(section==expected,"ROUTE_TEMPLATE_DRIFT")
        need(first_port not in routes,"DUPLICATE_ROUTE_PORT")
        routes[first_port]=(m.group("path"),m.group(0))
        cursor=m.end()
    need(sorted(routes)==list(routes),"ROUTE_ORDER_DRIFT")
    return routes

def state_render():
    raw=execute(["docker","exec","smite-node","cat",
                 "/var/lib/smite-node/tunnels.json"],25)
    need(0<len(raw)<=1048576,"NO_PERSISTED_TUNNELS")
    need(isinstance(json.loads(raw),dict),"INVALID_TUNNEL_STATE")
    with tempfile.TemporaryDirectory(prefix="uopti-frp-guided-",dir="/run") as temp:
        snapshot=Path(temp)/"tunnels.json"
        output=Path(temp)/"nginx.conf"
        fd=os.open(snapshot,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"wb") as file:file.write(raw)
        execute(["python3","-B",str(HELPER),"render",
                 str(snapshot),str(output)],30)
        rendered=output.read_bytes()
    need(len(rendered)<=131072,"RENDERED_ROUTES_OVERSIZE")
    return rendered

def inspection(port):
    host()
    signed_gate()
    timer_idle()
    need(trusted_read(BACKEND).decode().count(INCLUDE)==1,
         "PANEL_ROUTE_INCLUDE_DRIFT")
    registry=json.loads(trusted_read(REGISTRY,65536,0o600))
    need(isinstance(registry,dict),"INVALID_PATH_REGISTRY")
    saved=registry.get(str(port))
    need(isinstance(saved,str),"SELECTED_PORT_NOT_SAVED")
    chk=execute(["python3","-B",str(HELPER),"check",str(port),saved])
    need(saved.startswith(f"/{port}/") and not saved.endswith("/"),
         "INVALID_SELECTED_PATH")
    current=trusted_read(SNIPPET,131072,0o644)
    new=state_render()
    current_routes=parse_blocks(current)
    new_routes=parse_blocks(new)
    need(port in new_routes,"SELECTED_TUNNEL_NOT_APPLIED")
    need(new_routes[port][0]==saved,"TUNNEL_PATH_REGISTRY_MISMATCH")
    need(all(k in new_routes and new_routes[k]==v
             for k,v in current_routes.items()),
         "EXISTING_PUBLISHED_ROUTE_DRIFT")
    listener(7000);listener(port)
    nginx_test();panel_health()
    # If more than one unapplied route is present, do not publish them
    # implicitly when the operator approved just one selected port.
    missing=set(new_routes)-set(current_routes)
    need(missing in (set(),{port}),"EXTRA_UNAPPROVED_PORTS")
    if not missing:need(new==current,"RENDERED_ROUTE_DRIFT")
    return saved,current,new,bool(missing)

def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def exclusive_file(path,data,mode):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,"wb") as file:
        os.fchmod(file.fileno(),mode)
        file.write(data);file.flush();os.fsync(file.fileno())
    fsync_dir(path.parent)

def atomic_write(path,data,mode):
    fd,filename=tempfile.mkstemp(prefix=".uopti-frp-guided-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as file:
            os.fchmod(file.fileno(),mode)
            file.write(data);file.flush();os.fsync(file.fileno())
        os.replace(filename,path);fsync_dir(path.parent)
    finally:
        if os.path.lexists(filename):os.unlink(filename)

def journal_dir(port):
    return TX_ROOT/("ir-"+str(port))

def load_record(port):
    root=journal_dir(port)
    trusted_dir(TX_ROOT,private=True)
    trusted_dir(root,private=True)
    doc=json.loads(trusted_read(root/"record.json",8192,0o600))
    need(isinstance(doc,dict)
         and set(doc)=={"schema","state","port","path","before","after"}
         and doc["schema"]==1 and doc["port"]==port
         and doc["state"] in ("PREPARED","COMMITTED","ROLLED_BACK")
         and re.fullmatch(r"/[0-9]+/[A-Za-z0-9_/-]+",doc["path"])
         and all(re.fullmatch(r"[a-f0-9]{64}",doc[k]) for k in ("before","after")),
         "INVALID_PUBLISH_JOURNAL")
    backup=trusted_read(root/"snippet.before.conf",131072,0o600)
    need(digest(backup)==doc["before"],"BACKUP_INTEGRITY_HOLD")
    return doc,backup

def change_state(port,doc,state):
    root=journal_dir(port)
    need(json.loads(trusted_read(root/"record.json",8192,0o600))==doc,
         "JOURNAL_DRIFT")
    changed=dict(doc,state=state)
    atomic_write(root/"record.json",
                 (json.dumps(changed,sort_keys=True)+"\n").encode(),0o600)

def restore(port,doc,backup):
    now=trusted_read(SNIPPET,131072,0o644)
    need(digest(now) in (doc["before"],doc["after"]),
         "CRITICAL_SNIPPET_EXTERNAL_EDIT")
    if digest(now)==doc["after"]:
        atomic_write(SNIPPET,backup,0o644)
    nginx_test()
    reload_nginx()
    panel_health()
    change_state(port,doc,"ROLLED_BACK")

def apply(port):
    fd=lock_engine()
    try:
        saved,before,after,needed=inspection(port)
        need(needed,"ROUTE_ALREADY_PUBLISHED")
        if absent(TX_ROOT):TX_ROOT.mkdir(mode=0o700)
        trusted_dir(TX_ROOT,private=True)
        root=journal_dir(port)
        need(absent(root),"PREVIOUS_PUBLISH_TRANSACTION")
        root.mkdir(mode=0o700)
        trusted_dir(root,private=True)
        exclusive_file(root/"snippet.before.conf",before,0o600)
        doc={"schema":1,"state":"PREPARED","port":port,
             "path":saved,"before":digest(before),"after":digest(after)}
        exclusive_file(root/"record.json",
                       (json.dumps(doc,sort_keys=True)+"\n").encode(),0o600)
        try:
            need(trusted_read(SNIPPET,131072,0o644)==before,
                 "RACE_SNIPPET_CHANGED")
            atomic_write(SNIPPET,after,0o644)
            nginx_test()
            reload_nginx()
            panel_health()
            need(trusted_read(SNIPPET,131072,0o644)==after,
                 "POST_RELOAD_ROUTE_DRIFT")
            change_state(port,doc,"COMMITTED")
        except Exception as original:
            try:restore(port,doc,before)
            except Exception as recovery:
                raise Hold("CRITICAL_MANUAL_ROUTE_RECOVERY_REQUIRED") from recovery
            raise Hold("PUBLISH_FAILED_ROLLED_BACK") from original
        print("FRP_GUIDED_PUBLISH=COMMITTED")
        print("PUBLISHED_PORT="+str(port))
        print("PUBLISHED_PATH="+saved)
        print("EXISTING_ROUTES=PRESERVED")
        print("PANEL_HTTPS=PASS")
        print("NGINX_TEST=PASS")
        print("SYNC_TIMER=NOT_STARTED")
        print("TUNNEL_REAPPLY=NOT_PERFORMED")
    finally:os.close(fd)

def verify(port):
    path,current,new,needed=inspection(port)
    need(not needed,"ROUTE_NOT_YET_PUBLISHED")
    print("FRP_GUIDED_VERIFY=PASS_READ_ONLY")
    print("PUBLISHED_PORT="+str(port))
    print("PUBLISHED_PATH="+path)
    print("LIVE_CHANGES=NONE")

def rollback(port):
    fd=lock_engine()
    try:
        host();timer_idle()
        doc,backup=load_record(port)
        need(doc["state"]=="COMMITTED","ROLLBACK_STATE_HOLD")
        restore(port,doc,backup)
        print("FRP_GUIDED_ROLLBACK=PASS")
    finally:os.close(fd)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action",choices=("status","plan","apply","verify","rollback"))
    ap.add_argument("--port",required=True)
    a=ap.parse_args()
    try:
        need(re.fullmatch(r"[1-9][0-9]{3,4}",a.port) is not None,
             "INVALID_PORT")
        port=int(a.port)
        need(1024<=port<=65535 and port not in
             (2087,7000,8000,8443,8444,8888),"RESERVED_PORT")
        if a.action in ("status","plan"):
            path,_,_,needed=inspection(port)
            print("FRP_GUIDED_ROUTE_STATUS="+
                  ("PENDING" if needed else "ALREADY_PUBLISHED"))
            print("SELECTED_PORT="+str(port))
            print("SAVED_PATH="+path)
            print("IR_SIGNED_GATE=PASS")
            print("LIVE_CHANGES=NONE")
            if a.action=="plan":
                need(needed,"ROUTE_ALREADY_PUBLISHED")
                need(absent(journal_dir(port)),"PREVIOUS_PUBLISH_TRANSACTION")
                print("FRP_GUIDED_PUBLISH_PLAN=PASS_READ_ONLY")
        elif a.action=="verify":verify(port)
        else:
            need(sys.stdin.isatty(),"INTERACTIVE_TTY_REQUIRED")
            need(os.environ.get(OPTIN)=="YES","EXPLICIT_TRIAL_OPTIN_REQUIRED")
            code=f"{'PUBLISH' if a.action=='apply' else 'ROLLBACK'}-IR-FRP-{port}"
            need(input("Type "+code+" to authorize: ").strip()==code,
                 "OPERATOR_CANCELLED")
            if a.action=="apply":apply(port)
            else:rollback(port)
        return 0
    except (Hold,OSError,ValueError,TypeError,KeyError,UnicodeError,
            json.JSONDecodeError,subprocess.SubprocessError) as e:
        reason=str(e)
        if not re.fullmatch(r"[A-Z0-9_]{1,100}",reason):
            reason="UNTRUSTED_STATE"
        print("HOLD: "+reason,file=sys.stderr)
        print("FRP_GUIDED_ACTION=HOLD")
        return 2

if __name__=="__main__":
    raise SystemExit(main())
