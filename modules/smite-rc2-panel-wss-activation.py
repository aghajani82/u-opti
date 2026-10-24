#!/usr/bin/env python3
"""RC2 IR-only signed Smite Panel WSS candidate, bounded journal + backup.

Requires a preapproved VPS snapshot AND console. Existing Panel image must
match immutable reviewed digest; exactly two existing Signed Compose files.
The candidate is a LOCAL already-built image, not pulled/published.
Restarts only smite-panel, preserving data/certs/origin/config mounts.
No tunnel apply, no Node/IR Nginx/FRP/Grandoptical mutation.

Plan and verify are read-only. Apply/rollback/recover require an interactive
operator grant and shared engine transaction lock. A consistent SQLite backup
is made BEFORE Panel recreation; it is retained for manual recovery.
Automatic rollback restores only the original Panel image/Compose. NEVER
automatically overwrite a live database with a saved copy.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

BASE=Path("/opt/smite/docker-compose.yml")
SIGNED=Path("/opt/smite/docker-compose.signed-control.yml")
OVERLAY=Path("/opt/smite/docker-compose.panel-wss-rc2.yml")
STATE=Path("/var/lib/u-opti/smite-rc2-panel-wss")
JOURNAL=STATE/"record.json"
DATABASE_BACKUP=STATE/"smite-db.before.sqlite3"
LOCK=Path("/run/lock/u-opti-smite-engine.lock")
ORIGINAL="ghcr.io/aghajani82/smite-panel@sha256:9101898e19631d334b754ba8e956b63ab7dfaee304a8f9b954cf30a185125e8e"
BASE_ID="sha256:9101898e19631d334b754ba8e956b63ab7dfaee304a8f9b954cf30a185125e8e"
CANDIDATE="smite-panel:rc2-wss-ipless-c992e7723253"
CANDIDATE_ID="sha256:babafe97fbe6e8c29ef46a4485bd8b2e1ea6486b17373941f029f5a623f97cc3"
EXPECTED_SRC={
    "/app/app/config.py": "178f5656f4b199fffd270cf3786c5b45868082fc",
    "/app/app/routers/tunnels.py": "7a006ae99b259775f5db97c8cdfac8cec70db3a6",
    "/app/app/frp_wss_panel.py": "bf5d6c017ab677cb45eca0004610336bdd33a8e1",
}
ENV_KEYS={
    "SMITE_PANEL_AGENT_AUTH_MODE": "signed",
    "SMITE_ENGINE_MANAGEMENT_MODE": "managed",
}
DESTINATIONS={"/app/data", "/app/certs", "/app/config/.env",
              "/app/config/docker-compose.yml", "/etc/smite-panel/trusted-nodes"}
OVERLAY_TEXT=("services:\n  smite-panel:\n"
              f"    image: {CANDIDATE}\n"
              "    environment:\n"
              '      SMITE_FRP_STANDARD_WSS: "1"\n')
TRIAL="UOPTI_SMITE_RC2_PANEL_WSS_TRIAL"
SNAPSHOT="SNAPSHOTS-AND-IR-CONSOLE-VERIFIED"
CHALLENGE={
    "apply":"ACTIVATE-IR-SIGNED-PANEL-WSS",
    "rollback":"ROLLBACK-IR-SIGNED-PANEL-WSS",
    "recover":"RECOVER-IR-SIGNED-PANEL-WSS",
}
SHA=re.compile(r"^[a-f0-9]{64}$")


class Hold(Exception):
    pass


def need(test, label):
    if not test:
        raise Hold(label)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()


def absent(path):
    return not path.exists() and not path.is_symlink()


def safe_dir(path, private=False):
    st=path.lstat()
    need(stat.S_ISDIR(st.st_mode) and st.st_uid==0,"UNTRUSTED_DIRECTORY")
    mode=stat.S_IMODE(st.st_mode)
    need(mode==0o700 if private else mode & 0o022==0,"UNTRUSTED_DIRECTORY_MODE")


def safe_file(path, limit=262144, exact_mode=None):
    st=path.lstat()
    need(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1
         and not st.st_mode & 0o022 and st.st_size<=limit,
         "UNTRUSTED_FILE")
    if exact_mode is not None:
        need(stat.S_IMODE(st.st_mode)==exact_mode,"UNTRUSTED_FILE_MODE")
    fd=os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as f:
        got=os.fstat(f.fileno())
        need((st.st_ino,st.st_dev)==(got.st_ino,got.st_dev),"FILE_CHANGED")
        b=f.read(limit+1)
    need(len(b)<=limit,"FILE_LIMIT")
    return b


def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def create_file(path,raw,mode=0o600):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,"wb") as f:
        os.fchmod(f.fileno(),mode)
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    sync_dir(path.parent)


def replace_file(path,raw):
    need(not path.is_symlink(),"JOURNAL_SYMLINK")
    fd,name=tempfile.mkstemp(prefix=".rc2-journal-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            os.fchmod(f.fileno(),0o600)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def run(args, *, data=None, timeout=40, json_output=False):
    try:
        p=subprocess.run(args,input=data,capture_output=True,text=True,
                         timeout=timeout,cwd=str(BASE.parent))
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise Hold("COMMAND_FAILED") from exc
    need(p.returncode==0,"COMMAND_FAILED")
    if json_output:
        return json.loads(p.stdout)
    return p.stdout.strip()


def lock():
    need(not LOCK.is_symlink(),"ENGINE_LOCK_SYMLINK")
    fd=os.open(LOCK,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    s=os.fstat(fd)
    need(stat.S_ISREG(s.st_mode) and s.st_uid==0 and
         stat.S_IMODE(s.st_mode)==0o600,"ENGINE_LOCK_UNTRUSTED")
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise Hold("ENGINE_LOCK_BUSY") from exc
    return fd


def compose(enabled,args):
    files=["docker","compose","-f",str(BASE),"-f",str(SIGNED)]
    if enabled:files+=["-f",str(OVERLAY)]
    return files+args


def inspect():
    a=run(["docker","inspect","smite-panel"],timeout=20,json_output=True)
    need(len(a)==1,"PANEL_INSPECT_FAILED")
    return a[0]


def label_files(obj):
    return set(x.strip() for x in (
        (obj["Config"].get("Labels") or {}).get(
            "com.docker.compose.project.config_files","")).split(",") if x.strip())


def image_and_mounts(obj,enabled):
    want_img=CANDIDATE_ID if enabled else BASE_ID
    want_files={str(BASE),str(SIGNED)}
    if enabled:want_files.add(str(OVERLAY))
    need(obj["Image"]==want_img, "PANEL_IMAGE_DRIFT")
    need(label_files(obj)==want_files,"PANEL_SIGNED_COMPOSE_DRIFT")
    need((obj["Config"].get("Labels") or {}).get("com.docker.compose.service")=="smite-panel",
         "PANEL_SERVICE_DRIFT")
    mounts={m["Destination"]: m for m in obj.get("Mounts",[])}
    need(DESTINATIONS.issubset(mounts),"PANEL_SECURITY_MOUNTS_MISSING")
    need(all(mounts[d]["Type"]=="bind" for d in DESTINATIONS),
         "PANEL_VOLUME_TYPE_DRIFT")
    return {d:(mounts[d]["Source"],mounts[d].get("RW")) for d in sorted(DESTINATIONS)}


def env_metadata(obj):
    return dict(line.split("=",1) for line in obj["Config"]["Env"]
                if "=" in line)


def panel_settings(enabled):
    source=("from app.config import settings; "
            "print(settings.panel_domain); "
            "print(settings.smite_panel_agent_auth_mode); "
            "print(settings.smite_engine_management_mode); "
            "print(str(getattr(settings,'smite_frp_standard_wss',False))); "
            "print(settings.db_path)")
    out=run(["docker","exec","smite-panel","python3","-B","-c",source],
            timeout=20).splitlines()
    need(len(out)==5,"PANEL_SETTINGS_UNEXPECTED")
    need(out[0]=="ir.kolbe1.ir" and out[1]=="signed" and out[2]=="managed",
         "PANEL_SIGNED_POLICY_DRIFT")
    need(out[3]==("True" if enabled else "False"),"PANEL_WSS_FLAG_DRIFT")
    return out[4]


def database_path(obj,container_path):
    raw=Path(container_path)
    if not raw.is_absolute():
        raw=Path("/app")/raw
    # Normalize only inside /app/data, not any operator-controlled absolute path.
    norm=os.path.normpath(str(raw))
    need(norm.startswith("/app/data/"),"PANEL_DB_NOT_IN_PERSISTENT_MOUNT")
    mounts={m["Destination"]:m for m in obj.get("Mounts",[])}
    source=Path(mounts["/app/data"]["Source"])
    directory=source.resolve(strict=True)
    resolved=(directory/Path(norm).relative_to("/app/data")).resolve(strict=True)
    need(resolved.is_relative_to(directory) and resolved.is_file()
         and not resolved.is_symlink() and resolved.suffix.lower() in {".db",".sqlite",".sqlite3"},
         "PANEL_DB_UNSAFE_PATH")
    return resolved


def source_pin(obj):
    # The running original image is already independently source-verified;
    # do not dump file text or environment secrets.
    if obj["Image"]==BASE_ID:
        raw=run(["docker","exec","smite-panel","python3","-B","-c",
          "from pathlib import Path; import hashlib; "
          "names=['/app/app/config.py','/app/app/routers/tunnels.py']; "
          "print(','.join(hashlib.sha1(b'blob '+str(len(b)).encode()+b'\\0'+b).hexdigest() "
          "for b in [Path(p).read_bytes() for p in names]))"],timeout=20)
        need(raw=="c7c4419cd3a0114d1413c3acdca9646a534b8cfc,"
                  "e45b3efb728f2afbce7f65b1c41261d9aabeab0a",
             "PANEL_ORIGINAL_SOURCE_DRIFT")


def plan():
    need(os.geteuid()==0 and os.uname().nodename.split(".")[0].lower()=="ir",
         "IR_ROOT_ONLY")
    safe_dir(BASE.parent)
    safe_dir(STATE.parent)
    need(absent(STATE) and absent(OVERLAY),"EXISTING_PANEL_WSS_TRANSACTION")
    for path in (BASE,SIGNED):safe_file(path,262144)
    need(run(["docker","image","inspect",CANDIDATE,"--format","{{.Id}}"])==CANDIDATE_ID,
         "CANDIDATE_IMAGE_DRIFT")
    old=inspect()
    mounts=image_and_mounts(old,False)
    need(old["Config"]["Image"]==ORIGINAL,"PANEL_ORIGINAL_REF_DRIFT")
    need(old["State"]["Running"] is True,"ORIGINAL_PANEL_NOT_RUNNING")
    source_pin(old)
    db_name=panel_settings(False)
    db=database_path(old,db_name)
    current=run(compose(False,["config","--format","json"]),json_output=True)
    future=run(["docker","compose","-f",str(BASE),"-f",str(SIGNED),"-f","-",
                "config","--format","json"],data=OVERLAY_TEXT,json_output=True)
    prior=current["services"]["smite-panel"]
    newer=future["services"]["smite-panel"]
    need(newer["image"]==CANDIDATE and
         newer["environment"].get("SMITE_FRP_STANDARD_WSS")=="1" and
         "SMITE_FRP_STANDARD_WSS" not in prior["environment"],
         "WSS_PANEL_COMPOSE_PREVIEW_DRIFT")
    future["services"]["smite-panel"]["image"]=prior["image"]
    del future["services"]["smite-panel"]["environment"]["SMITE_FRP_STANDARD_WSS"]
    need(future==current,"UNEXPECTED_PANEL_COMPOSE_CHANGE")
    return {"base":digest(safe_file(BASE)), "signed":digest(safe_file(SIGNED)),
            "original_image":old["Image"],"candidate_image":CANDIDATE_ID,
            "mounts":mounts,"db_path":str(db),
            "container_before":old["Id"],
            "overlay_sha":digest(OVERLAY_TEXT.encode())}


def verify_pins(doc):
    need(digest(safe_file(BASE))==doc["base"]
         and digest(safe_file(SIGNED))==doc["signed"],
         "PROTECTED_PANEL_COMPOSE_DRIFT")
    need(doc["original_image"]==BASE_ID and doc["candidate_image"]==CANDIDATE_ID
         and doc["overlay_sha"]==digest(OVERLAY_TEXT.encode()),
         "JOURNAL_PIN_DRIFT")


def journal():
    safe_dir(STATE,private=True)
    x=json.loads(safe_file(JOURNAL,16384,0o600))
    need(x["state"] in ("PREPARED","COMMITTED","ROLLED_BACK") and
         x["schema"]==1 and x["role"]=="ir" and
         x["db_path"].startswith("/") and
         x["db_backup"]==str(DATABASE_BACKUP),"JOURNAL_INVALID")
    verify_pins(x)
    return x


def record(source):
    STATE.mkdir(mode=0o700)
    safe_dir(STATE,private=True)
    sync_dir(STATE.parent)
    doc={"schema":1,"role":"ir","state":"PREPARED","db_backup":str(DATABASE_BACKUP),
         **source}
    create_file(JOURNAL,(json.dumps(doc,sort_keys=True)+"\n").encode())
    return doc


def mark(doc,status):
    updated=dict(doc,state=status)
    replace_file(JOURNAL,(json.dumps(updated,sort_keys=True)+"\n").encode())


def backup_db(doc):
    database=Path(doc["db_path"])
    need(database.is_file() and not database.is_symlink(),"DATABASE_DRIFT")
    need(absent(DATABASE_BACKUP),"EXISTING_DB_BACKUP")
    # Reads a transactionally consistent online SQLite snapshot. No service
    # stop and no direct writes into the live database.
    source=sqlite3.connect(database.as_uri()+"?mode=ro",uri=True,timeout=12)
    try:
        target=sqlite3.connect(str(DATABASE_BACKUP),timeout=12)
        try:
            source.backup(target,pages=256,sleep=0.2)
            need(target.execute("PRAGMA integrity_check").fetchone()[0]=="ok",
                 "SQLITE_BACKUP_INTEGRITY_FAILED")
        finally:target.close()
    finally:source.close()
    os.chmod(DATABASE_BACKUP,0o600)
    sync_dir(STATE)
    need(DATABASE_BACKUP.stat().st_size>0,"SQLITE_BACKUP_EMPTY")


def runtime_check(doc, enabled):
    obj=inspect()
    need(obj["State"]["Running"] is True,"PANEL_NOT_RUNNING")
    health=(obj["State"].get("Health") or {}).get("Status")
    need(health in (None,"healthy"),"PANEL_NOT_HEALTHY")
    need(image_and_mounts(obj,enabled)==doc["mounts"],
         "PANEL_MOUNT_SOURCE_CHANGED")
    settings_db=panel_settings(enabled)
    need(str(database_path(obj,settings_db))==doc["db_path"],
         "PANEL_DB_MOUNT_DRIFT")
    # Panel must still serve ordinary HTTPS/443 through the unchanged gateway.
    run(["curl","--noproxy","*","-4","--fail","--silent","--show-error",
         "--connect-timeout","5","--max-time","12",
         "--resolve","ir.kolbe1.ir:443:127.0.0.1",
         "--output","/dev/null","https://ir.kolbe1.ir/"],timeout=18)


def wait_panel(doc,enabled):
    for _ in range(20):
        try:
            runtime_check(doc,enabled)
            return
        except (Hold,OSError,KeyError,ValueError,subprocess.SubprocessError):
            time.sleep(3)
    raise Hold("PANEL_READINESS_TIMEOUT")


def recreate(enabled):
    run(compose(enabled,["up","-d","--no-build","--no-deps",
                        "--pull","never","--force-recreate","smite-panel"]),
        timeout=150)


def restore(doc):
    verify_pins(doc)
    need(doc["state"] in ("PREPARED","COMMITTED"),"INVALID_RESTORE_STATE")
    need(DATABASE_BACKUP.is_file() and
         DATABASE_BACKUP.stat().st_size>0,"DATABASE_BACKUP_NOT_VERIFIED")
    if not absent(OVERLAY):
        need(digest(safe_file(OVERLAY,8192,0o600))==doc["overlay_sha"],
             "PANEL_OVERLAY_TAMPERED")
    try:
        current=inspect()
    except Hold:
        current=None
    if current is not None:
        need(current["Image"] in (BASE_ID,CANDIDATE_ID),
             "UNKNOWN_PANEL_IMAGE_CANNOT_ROLLBACK")
    if current is None or current["Image"]!=BASE_ID or (
            label_files(current)!={str(BASE),str(SIGNED)}) or (
            current["State"]["Running"] is not True):
        recreate(False)
    wait_panel(doc,False)
    if not absent(OVERLAY):
        OVERLAY.unlink()
        sync_dir(OVERLAY.parent)
    mark(doc,"ROLLED_BACK")
    print("RC2_PANEL_WSS_ROLLBACK=PASS")
    print("SIGNED_PANEL_RESTORED=YES")
    print("DATABASE_BACKUP_RETAINED=YES")
    print("DATABASE_AUTORESTORE=NO")


def apply():
    fd=lock()
    try:
        doc=record(plan())
        try:
            backup_db(doc)
            need(absent(OVERLAY),"WSS_OVERLAY_EXISTS")
            create_file(OVERLAY,OVERLAY_TEXT.encode(),0o600)
            recreate(True)
            wait_panel(doc,True)
            verify_pins(doc)
            mark(doc,"COMMITTED")
            print("RC2_PANEL_WSS_ACTIVATION=COMMITTED")
            print("SIGNED_PANEL=PASS")
            print("PANEL_HTTPS=PASS")
            print("DB_BACKUP_RETAINED=YES")
            print("TUNNEL_REAPPLY=NOT_PERFORMED")
        except Exception as exc:
            try:restore(journal())
            except Exception as recovery:
                raise Hold("CRITICAL_MANUAL_PANEL_RECOVERY_REQUIRED") from recovery
            raise Hold("PANEL_ACTIVATION_FAILED_ROLLED_BACK") from exc
    finally:os.close(fd)


def verify():
    doc=journal()
    need(doc["state"]=="COMMITTED","PANEL_NOT_COMMITTED")
    verify_pins(doc)
    need(digest(safe_file(OVERLAY,8192,0o600))==doc["overlay_sha"],
         "PANEL_OVERLAY_DRIFT")
    runtime_check(doc,True)
    print("RC2_PANEL_WSS_VERIFY=PASS_SIGNED")
    print("PANEL_HTTPS=PASS")
    print("WSS_FLAG=ENABLED")
    print("LIVE_CHANGES=NONE")


def rollback(recover=False):
    fd=lock()
    try:
        doc=journal()
        need(doc["state"]==("PREPARED" if recover else "COMMITTED"),
             "WRONG_ROLLBACK_LANE")
        restore(doc)
    finally:os.close(fd)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("plan","apply","verify","rollback","recover"))
    parser.add_argument("--confirm-snapshot",default="")
    args=parser.parse_args()
    try:
        if args.action in ("apply","rollback","recover"):
            need(os.environ.get(TRIAL)=="YES","RC2_TRIAL_OPT_IN_REQUIRED")
            need(args.confirm_snapshot==SNAPSHOT,
                 "SNAPSHOT_AND_CONSOLE_CONFIRMATION_REQUIRED")
            need(sys.stdin.isatty(),"INTERACTIVE_APPROVAL_REQUIRED")
            need(input("Type "+CHALLENGE[args.action]+" to authorize: ").strip()
                 == CHALLENGE[args.action],"OPERATOR_CANCELLED")
        if args.action=="plan":
            plan()
            print("RC2_PANEL_WSS_PLAN=PASS_READ_ONLY")
            print("CANDIDATE_IMAGE=PINNED")
            print("SIGNED_COMPOSE=PRESERVED")
            print("DATABASE_BACKUP=REQUIRED_AT_APPLY")
            print("PANEL_RECREATION=NOT_STARTED")
            print("LIVE_CHANGES=NONE")
        elif args.action=="apply":apply()
        elif args.action=="verify":verify()
        else:rollback(recover=args.action=="recover")
        return 0
    except (Hold,OSError,sqlite3.Error,ValueError,TypeError,KeyError,
            json.JSONDecodeError,subprocess.SubprocessError) as exc:
        reason=str(exc)
        if not re.fullmatch(r"[A-Z0-9_]{1,100}",reason):
            reason="PANEL_TRIAL_UNTRUSTED_STATE"
        print("HOLD: "+reason,file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
