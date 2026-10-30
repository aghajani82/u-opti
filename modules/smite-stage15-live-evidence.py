#!/usr/bin/env python3
"""Fresh independent Stage15 attestation collection on IR root only.

No Panel API is trusted as approval. Reads a separately authorized *read-only*
copy of Panel SQLite to verify a unique active lease, then separately obtains
Node-origin Ed25519 runtime attestations from independently pinned IR/KH
Signed Agent endpoints. The approved Root signer independently attests the
lease AFTER these checks. No mutations to FRPS/FRPC/Node/Panel/Replay DB.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
from urllib.parse import urlsplit

AUDIENCE="u-opti:stage15:root-review-evidence:v1"
TARGET="/api/agent/approval/evidence"
RESERVED={"api","assets","auth","admin","login","health","metrics","static","ws","sub"}
HEX=re.compile(r"[a-f0-9]{64}\Z")
IDENT=re.compile(r"[A-Za-z0-9_-]{8,128}\Z")


class LiveEvidenceHold(RuntimeError):pass


def canonical(x):
    return json.dumps(x,ensure_ascii=True,sort_keys=True,separators=(",",":"),
                      allow_nan=False).encode("ascii")


def _trusted_file(path,mode=0o600,max_size=8192):
    path=Path(path);s=path.lstat()
    if (not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=0
            or stat.S_IMODE(s.st_mode)!=mode or not 0<s.st_size<=max_size):
        raise LiveEvidenceHold("ROOT_EVIDENCE_SOURCE_UNTRUSTED")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        f=os.fstat(fd)
        if (s.st_dev,s.st_ino)!=(f.st_dev,f.st_ino):
            raise LiveEvidenceHold("EVIDENCE_SOURCE_CHANGED")
        raw=os.read(fd,max_size+1)
        if len(raw)!=s.st_size:raise LiveEvidenceHold("EVIDENCE_SOURCE_CHANGED")
        return raw
    finally:os.close(fd)


def _db_query(path: Path, sql: str, *args):
    """Read-only SQL on pre-mounted review copy; no direct Panel API trust."""
    path=Path(path)
    s=path.lstat()
    if (not stat.S_ISREG(s.st_mode) or s.st_nlink!=1
            or (s.st_mode&0o022) or not 0<s.st_size<=256*1024*1024):
        raise LiveEvidenceHold("PANEL_LEASE_SNAPSHOT_UNTRUSTED")
    try:
        with sqlite3.connect(path.absolute().as_uri()+"?mode=ro",uri=True,
                             isolation_level=None,timeout=1) as db:
            db.execute("PRAGMA query_only=ON")
            return db.execute(sql,args).fetchall()
    except sqlite3.Error as exc:
        raise LiveEvidenceHold("LEASE_SNAPSHOT_UNAVAILABLE") from exc


def _lease(binding, db_path):
    """Require an active unique DB lease corroborated by a live Node port."""
    child_rows=_db_query(db_path,
        "SELECT id,core,status,node_id,iran_node_id,foreign_node_id,spec FROM tunnels WHERE id=?",
        binding["child"])
    owner_rows=_db_query(db_path,
        "SELECT id,core,status,node_id,iran_node_id,foreign_node_id,spec FROM tunnels WHERE id=?",
        binding["owner"])
    if len(child_rows)!=1 or len(owner_rows)!=1:
        raise LiveEvidenceHold("LEASE_ROWS_NOT_UNIQUE")
    child,owner=child_rows[0],owner_rows[0]
    def pair(row):
        return (row[4] or row[3],row[5])
    if (child[1:3]!=("frp","active") or owner[1:3]!=("frp","active")
            or pair(child)!=(binding["ir_node"],binding["kh_node"])
            or pair(owner)!=(binding["ir_node"],binding["kh_node"])):
        raise LiveEvidenceHold("LEASE_IDENTITY_OR_STATUS_MISMATCH")
    try:
        cs=json.loads(child[6]);ospec=json.loads(owner[6])
    except (ValueError,TypeError) as exc:
        raise LiveEvidenceHold("LEASE_SPEC_CORRUPT") from exc
    if not isinstance(cs,dict) or not isinstance(ospec,dict):
        raise LiveEvidenceHold("LEASE_SPEC_INVALID")
    rows=_db_query(db_path,"SELECT tunnel_id,owner_tunnel_id,iran_node_id,foreign_node_id,remote_port FROM frp_proxy_leases WHERE iran_node_id=? AND remote_port=?",
                   binding["ir_node"],binding["port"])
    direct=binding["child"]==binding["owner"]
    if direct:
        if binding["lease"]!=binding["owner"] or rows:
            raise LiveEvidenceHold("DIRECT_LEASE_CONFLICT")
    else:
        if (len(rows)!=1 or rows[0]!=(
                binding["child"],binding["owner"],binding["ir_node"],
                binding["kh_node"],binding["port"])
                or cs.get("shared_frps_owner")!=binding["owner"]
                or binding["lease"]!=binding["child"]):
            raise LiveEvidenceHold("SHARED_LEASE_CONFLICT")
    # The owner process/port is checked separately against a live IR Node
    # attestation and is NOT inferred from this potentially writable DB.
    if ospec.get("bind_port")!=7000:
        raise LiveEvidenceHold("FRPS_OWNER_SPEC_MISMATCH")
    return {"ir_node":binding["ir_node"],"kh_node":binding["kh_node"],
            "owner":binding["owner"],"child":binding["child"],"lease":binding["lease"],
            "port":binding["port"],"role":"direct" if direct else "shared",
            "state":"active","unique":True,"owner_count":1,"proxy_port_count":1}


def _signed_headers(node_id,secret,body):
    nonce=secrets.token_hex(16);now=str(int(time.time()))
    wire="\n".join(("smite-node-hmac-v1",node_id,"POST",TARGET,now,nonce,
                    hashlib.sha256(body).hexdigest())).encode("utf-8")
    return {"X-Smite-Node-ID":node_id,"X-Smite-Timestamp":now,"X-Smite-Nonce":nonce,
            "X-Smite-Signature":hmac.new(secret,wire,hashlib.sha256).hexdigest(),
            "Content-Type":"application/json"}


def _node_attestation(config,kind,port):
    """Exactly one signed POST to pinned HTTPS:443 or IR loopback HTTP.

    No redirects, proxies, query credentials, TLS bypass or automatic retry.
    Root's own read-only transport identity is provisioned separately and
    never shared with browser or JS.
    """
    import httpx
    if type(config) is not dict or set(config)!={"node_id","url","secret_path"}:
        raise LiveEvidenceHold("INVALID_NODE_ORIGIN_CONFIG")
    url=config["url"]
    if type(url) is not str:
        raise LiveEvidenceHold("NODE_ORIGIN_UNAVAILABLE")
    u=urlsplit(url)
    if (u.username or u.password or u.query or u.fragment
            or (u.scheme=="https" and u.port not in (None,443))
            or (u.scheme=="http" and (u.hostname!="127.0.0.1" or u.port!=8888))
            or u.scheme not in ("https","http")
            or not u.path.endswith(TARGET)):
        raise LiveEvidenceHold("UNAPPROVED_NODE_EVIDENCE_ORIGIN")
    node_id=config["node_id"]
    if type(node_id) is not str or not IDENT.fullmatch(node_id):
        raise LiveEvidenceHold("UNAPPROVED_NODE_ID")
    secret=_trusted_file(Path(config["secret_path"]),mode=0o600,max_size=64)
    if len(secret)!=64 or not HEX.fullmatch(secret.decode("ascii")):
        raise LiveEvidenceHold("UNTRUSTED_NODE_HMAC_COPY")
    body=canonical({"kind":kind,"port":port})
    try:
        with httpx.Client(trust_env=False,verify=True,follow_redirects=False,timeout=5) as client:
            response=client.post(url,content=body,headers=_signed_headers(node_id,secret,body))
        if response.status_code!=200 or len(response.content)>8192:
            raise LiveEvidenceHold("SIGNED_NODE_EVIDENCE_UNAVAILABLE")
        value=response.json()
    except (httpx.HTTPError,ValueError) as exc:
        raise LiveEvidenceHold("SIGNED_NODE_EVIDENCE_UNAVAILABLE") from exc
    if (type(value) is not dict or set(value)!={"status","attestation"}
            or value["status"]!="success" or type(value["attestation"]) is not dict
            or value["attestation"].get("node")!=node_id):
        raise LiveEvidenceHold("SIGNED_NODE_ATTESTATION_INVALID")
    return value["attestation"]


def collect(binding,*,settings,root_private_key: Path):
    """Produce three fresh attestations. Signature validation by Root is later.

    Every call performs live HTTP reads, read-only Panel DB lease inspection
    and signs its own derived lease assertion. No cached evidence fallback.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if type(settings) is not dict or set(settings)!={"ir","kh","db_path"}:
        raise LiveEvidenceHold("UNCONFIGURED_INDEPENDENT_EVIDENCE")
    if type(binding) is not dict:
        raise LiveEvidenceHold("UNTRUSTED_BINDING")
    ir=_node_attestation(settings["ir"],"frps_owner",binding["port"])
    kh=_node_attestation(settings["kh"],"xhttp_inbound",binding["port"])
    if (ir.get("node")!=binding["ir_node"] or kh.get("node")!=binding["kh_node"]
            or ir.get("facts")!={"tunnel_id":binding["owner"],
                "control_port":7000,"proxy_port":binding["port"]}
            or kh.get("facts")!={"port":binding["port"],"listen":"127.0.0.1",
                "protocol":"vless","network":"xhttp","path":binding["path"],"enabled":True}):
        raise LiveEvidenceHold("INDEPENDENT_RUNTIME_DRIFT")
    lease=_lease(binding,Path(settings["db_path"]))
    key=Ed25519PrivateKey.from_private_bytes(_trusted_file(root_private_key,mode=0o400,max_size=32))
    now=int(time.time())
    record={"schema":1,"audience":AUDIENCE,"kind":"active_lease",
            "node":binding["ir_node"],"issued_at":now,"expires_at":now+30,
            "nonce":secrets.token_hex(16),"facts":lease}
    record["signature"]=base64.urlsafe_b64encode(key.sign(canonical(record))).rstrip(b"=").decode("ascii")
    return {"ir_owner":ir,"kh_inbound":kh,"ir_lease":record}
