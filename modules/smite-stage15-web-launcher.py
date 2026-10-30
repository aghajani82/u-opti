#!/usr/bin/env python3
"""Explicit, separately approved Stage15 Root Web Approval service launcher.

No public listener, no automatic provisioning, no TLS or DNS management.
Reads a root-owned 0600 config once and refuses incomplete live attestation
sources, missing persistent state or invalid credential pinning.
"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


class LaunchHold(RuntimeError):pass


HERE=Path(__file__).resolve().parent
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    if not spec or not spec.loader:raise LaunchHold("APPROVAL_MODULE_MISSING")
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m


def _private(path,mode=0o600):
    s=path.lstat()
    if (not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_nlink!=1
            or stat.S_IMODE(s.st_mode)!=mode or not 0<s.st_size<=16384):
        raise LaunchHold("ROOT_CONFIGURATION_UNTRUSTED")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        if (os.fstat(fd).st_ino,os.fstat(fd).st_dev)!=(s.st_ino,s.st_dev):
            raise LaunchHold("ROOT_CONFIGURATION_CHANGED")
        return os.read(fd,16385)
    finally:os.close(fd)


def load_config(path:Path):
    c=json.loads(_private(path))
    required={"schema","origin","panel_origin","socket_path","socket_gid",
              "queue_dir","ledger_path","credentials_path","broker_key_path",
              "ir_public_key_path","kh_public_key_path","lease_public_key_path",
              "lease_private_key_path","node_ir","node_kh","panel_snapshot_path"}
    if (type(c) is not dict or set(c)!=required or type(c["schema"]) is not int
            or c["schema"]!=1 or type(c["socket_gid"]) is not int
            or not 1<=c["socket_gid"]<=65535):
        raise LaunchHold("ROOT_APPROVAL_CONFIG_SCHEMA_MISMATCH")
    for name in required-{"schema","origin","panel_origin","socket_gid","node_ir","node_kh"}:
        v=c[name]
        if type(v) is not str or not v.startswith("/") or ".." in Path(v).parts:
            raise LaunchHold("UNTRUSTED_REVIEW_PATH")
    for node in ("node_ir","node_kh"):
        source=c[node]
        if type(source) is not dict or set(source)!={"node_id","url","secret_path"}:
            raise LaunchHold("UNTRUSTED_NODE_CONFIG")
    return c


def serve(config_path:Path):
    if os.geteuid()!=0 or os.uname().nodename.split(".")[0].lower()!="ir":
        raise LaunchHold("IR_ROOT_SERVICE_ONLY")
    c=load_config(config_path)
    gate=load("root_service_gate","smite-stage15-web-approval.py")
    enroll=load("root_service_enrollment","smite-stage15-passkey-enrollment.py")
    srv=load("root_service_http","smite-stage15-web-service.py")
    runtime=load("root_service_evidence","smite-stage15-live-evidence.py")
    p=load("root_service_grant","smite-rc5-xhttp-broker-provision.py")
    def key(path,mode):
        return _private(Path(c[path]),mode)
    broker_key=key("broker_key_path",0o600)
    ir_key=key("ir_public_key_path",0o600)
    kh_key=key("kh_public_key_path",0o600)
    lease_key=key("lease_public_key_path",0o600)
    if any(len(k)!=32 for k in (broker_key,ir_key,kh_key,lease_key)):
        raise LaunchHold("ROOT_APPROVAL_KEY_PINS_INVALID")
    credentials=enroll.CredentialStore(Path(c["credentials_path"]))
    ledger=gate.ApprovalLedger(Path(c["ledger_path"]))
    sources={"ir":c["node_ir"],"kh":c["node_kh"],"db_path":c["panel_snapshot_path"]}
    def evidence(binding):
        return runtime.collect(binding,settings=sources,
                               root_private_key=Path(c["lease_private_key_path"]))
    def grant(binding):
        return p.install_grant(binding,confirmed_child=binding["child"])
    app=srv.IndependentApproval(queue_dir=Path(c["queue_dir"]),broker_key=broker_key,
             origin=c["origin"],panel_origin=c["panel_origin"],
             ledger=ledger,credential_store=credentials,
             ir_public_key=ir_key,kh_public_key=kh_key,
             lease_public_key=lease_key,
             evidence_provider=evidence,grant_writer=grant)
    try:
        with srv.ApprovalUDSServer(c["socket_path"],app) as http:
            os.chown(c["socket_path"],0,c["socket_gid"])
            http.serve_forever(poll_interval=.2)
    finally:
        ledger.close()
        credentials.close()


if __name__=="__main__":
    if len(sys.argv)!=3 or sys.argv[1]!="--serve":
        raise SystemExit("HOLD_EXPLICIT_ROOT_SERVICE_CONFIG_REQUIRED")
    try:
        serve(Path(sys.argv[2]))
    except Exception:
        raise SystemExit("HOLD_ROOT_APPROVAL_SERVICE_UNAVAILABLE")
