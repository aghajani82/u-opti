#!/usr/bin/env python3
"""One-time root TTY bootstrap for inert Stage15 Web Approval state.

DOES NOT install/enable service, write web-approval-mode.json, configure TLS,
touch Nginx, change Panel/Node images or issue any TrustedGrant.
Interrupted or existing state is HOLD: never silently reset audit DB.
"""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import stat
import sys


class BootstrapHold(RuntimeError):pass


def _load(file):
    spec=importlib.util.spec_from_file_location("stage15_boot_"+file.replace("-","_"),
                          Path(__file__).resolve().parent/file)
    if not spec or not spec.loader:raise BootstrapHold("BOOTSTRAP_MODULE_MISSING")
    m=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=m
    spec.loader.exec_module(m)
    return m


def prepare(*,state_dir:Path=Path("/var/lib/u-opti/smite-web-approval"),
            queue_dir:Path=Path("/var/lib/u-opti/smite-xhttp-broker/approval-pending"),
            root_check:bool=True):
    if root_check and (os.geteuid()!=0 or not sys.stdin.isatty()
                       or os.uname().nodename.split(".")[0].lower()!="ir"):
        raise BootstrapHold("IR_ROOT_TTY_ONLY")
    state_dir,queue_dir=Path(state_dir),Path(queue_dir)
    for target in (state_dir,queue_dir):
        parent=target.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or (root_check and parent.st_uid!=0)
                or parent.st_mode & 0o022 or target.exists() or target.is_symlink()):
            raise BootstrapHold("EXISTING_OR_UNTRUSTED_APPROVAL_STATE")
    # Preflight every destination before the first mutation.
    state_dir.mkdir(mode=0o700)
    os.chmod(state_dir,0o700)
    queue_dir.mkdir(mode=0o700)
    os.chmod(queue_dir,0o700)
    fd=os.open(state_dir/"approval.db",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    os.close(fd)
    gate=_load("smite-stage15-web-approval.py")
    ledger=gate.ApprovalLedger(state_dir/"approval.db",root_check=root_check)
    ledger.close()
    enroll=_load("smite-stage15-passkey-enrollment.py")
    if root_check:
        enroll.bootstrap(state_dir/"credentials.db")
    else:
        import sqlite3
        fd=os.open(state_dir/"credentials.db",os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.close(fd)
        with sqlite3.connect(state_dir/"credentials.db") as conn:
            conn.executescript(enroll.SCHEMA)
            conn.commit()
    return {"state":"PASS_INERT","broker_replay_db":"UNCHANGED",
            "root_grants":"UNCHANGED","service":"NOT_ENABLED",
            "web_mode_marker":"NOT_CREATED","live_routes":"UNCHANGED"}


if __name__=="__main__":
    if sys.argv!=[sys.argv[0],"--prepare"]:
        raise SystemExit("HOLD_EXPLICIT_BOOTSTRAP_COMMAND_ONLY")
    try:
        result=prepare()
        for k,v in result.items():print(k.upper()+"="+v)
    except Exception:
        raise SystemExit("HOLD_BOOTSTRAP_PARTIAL_REQUIRES_OPERATOR_REVIEW")
