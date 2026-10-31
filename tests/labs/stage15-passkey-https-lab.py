#!/usr/bin/env python3
"""Disposable-only HTTPS WebAuthn/browser lab. NEVER deploy on IR/KH.

No FRP, Panel, Broker, grants, routing, SQLite, Node agents or outbound HTTP.
Credential/state are ephemeral process memory only. A successful real
WebAuthn signature proves browser RP/UV at this lab origin, not production.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import sys
import threading
import time

ORIGIN="https://passkey-lab.test"
RP_ID="passkey-lab.test"
HOST=RP_ID
PORT=443
MAX_BODY=32768
MAX_AGE=120
HERE=Path(__file__).resolve().parent


class LabHold(RuntimeError):
    pass


def check_lab_host(*, hostname, confirm, cert, key):
    if (hostname.split(".")[0].lower() in
        {"ir","kh","grandoptical","smite-panel","smite-node"}
        or confirm!="I_CONFIRM_DISPOSABLE_OFFLINE_LAB"):
        raise LabHold("DISPOSABLE_MACHINE_CONFIRMATION_REQUIRED")
    for p in (cert,key):
        path=Path(p)
        if (not path.is_absolute() or not path.is_file()
            or path.is_symlink() or path.stat().st_size > 1024*1024
            or path.stat().st_size < 1 or any(
                part in ("letsencrypt","u-opti","smite") for part in path.parts
            )):
            raise LabHold("DISPOSABLE_TLS_FILES_REQUIRED")
    if Path(cert).resolve()==Path(key).resolve():
        raise LabHold("DISPOSABLE_TLS_FILES_REQUIRED")
    # This check cannot prove network or filesystem isolation. The
    # operator must independently verify the disposable VM boundary.


class LabState:
    def __init__(self):
        from fido2.server import Fido2Server
        from fido2.webauthn import PublicKeyCredentialRpEntity
        self.server=Fido2Server(PublicKeyCredentialRpEntity(
            id=RP_ID,name="Isolated Passkey Lab"),
            verify_origin=lambda candidate: candidate==ORIGIN)
        self.lock=threading.RLock()
        self.csrf=secrets.token_urlsafe(32)
        self.user=secrets.token_bytes(24)
        self.credentials={}  # keyed by credential ID bytes
        self.pending={}      # one-shot, in-memory, expires
        self.auth_success=0

    def status(self):
        with self.lock:
            return {
                "registered_credentials":len(self.credentials),
                "verified_sign_ins":self.auth_success,
                "independent_physical_devices":"MANUAL_VERIFICATION_REQUIRED",
                "persistent_credentials":"NONE_ON_SERVER",
                "grant_writer":"ABSENT",
                "route_publication":"IMPOSSIBLE",
                "real_ir_kh":"DISCONNECTED",
            }

    def start(self,kind):
        from fido2.webauthn import PublicKeyCredentialUserEntity
        if kind not in ("register","authenticate"):
            raise LabHold("UNKNOWN_CEREMONY")
        with self.lock:
            if kind=="register":
                if len(self.credentials)>=2:
                    raise LabHold("MAXIMUM_TWO_LAB_CREDENTIALS")
                user=PublicKeyCredentialUserEntity(
                    id=self.user,name="disposable-test",
                    display_name="Disposable Test Only")
                opts,state=self.server.register_begin(
                    user,credentials=list(self.credentials.values()),
                    user_verification="required")
            else:
                if not self.credentials:
                    raise LabHold("NO_LAB_CREDENTIAL")
                opts,state=self.server.authenticate_begin(
                    list(self.credentials.values()),
                    user_verification="required")
            challenge=secrets.token_hex(16)
            # Only one pending ceremony for the whole in-memory lab.
            # Starting a new one invalidates the prior request.
            self.pending.clear()
            self.pending[challenge]=(kind,state,time.monotonic()+MAX_AGE)
            # python-fido2 2.0.0 credential options are Mapping-style,
            # not guaranteed to expose .to_json(). The mock may provide
            # .to_json() to keep old isolated test fixtures compatible.
            data=dict(opts) if hasattr(opts,"keys") else json.loads(opts.to_json())
            if type(data) is not dict or "publicKey" not in data:
                raise LabHold("LAB_WEBAUTHN_OPTIONS_UNAVAILABLE")
            return {"ceremony":challenge,"options":data}

    def complete(self,kind,ceremony,response):
        if (kind not in ("register","authenticate")
            or not isinstance(ceremony,str)
            or not re.fullmatch("[0-9a-f]{32}",ceremony)
            or type(response) is not dict):
            raise LabHold("INVALID_CEREMONY")
        with self.lock:
            saved=self.pending.pop(ceremony,None)  # consume BEFORE verify
            if saved is None or saved[0]!=kind or time.monotonic()>saved[2]:
                raise LabHold("EXPIRED_OR_SPENT_CEREMONY")
            try:
                if kind=="register":
                    result=self.server.register_complete(saved[1],response)
                    if not result.is_user_verified():
                        raise ValueError("user verification required")
                    credential=result.credential_data
                    if credential is None or not credential.credential_id:
                        raise ValueError("credential missing")
                    if credential.credential_id in self.credentials:
                        raise ValueError("duplicate passkey")
                    self.credentials[credential.credential_id]=credential
                    return {"status":"LAB_REGISTERED",
                            "registered_credentials":len(self.credentials),
                            "physical_independence":"MANUAL_CONFIRMATION_REQUIRED"}
                credential=self.server.authenticate_complete(
                    saved[1],list(self.credentials.values()),response)
                if credential.credential_id not in self.credentials:
                    raise ValueError("credential not enrolled")
                self.auth_success+=1
                return {"status":"LAB_AUTHENTICATED_NO_GRANT",
                        "verified_sign_ins":self.auth_success}
            except Exception as exc:
                raise LabHold("FIDO2_VERIFICATION_REJECTED") from exc


class LabHandler(BaseHTTPRequestHandler):
    server_version="StandalonePasskeyLab"
    sys_version=""

    def log_message(self,fmt,*args):
        # Never print assertions, tickets, challenge bytes or client IP data.
        return

    def _headers(self,code,type_="application/json; charset=utf-8"):
        self.send_response(code)
        for k,v in (
            ("Content-Type",type_),("Cache-Control","no-store"),
            ("X-Content-Type-Options","nosniff"),
            ("Referrer-Policy","no-referrer"),
            ("X-Frame-Options","DENY"),
            ("Content-Security-Policy",
             "default-src 'none'; script-src 'self'; connect-src 'self'; "
             "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"),
        ):
            self.send_header(k,v)
        self.end_headers()

    def _allowed(self,*,write):
        if self.headers.get("Host")!=HOST:
            raise LabHold("LAB_HOST_MISMATCH")
        if self.headers.get("Cookie") or self.headers.get("Authorization"):
            raise LabHold("NO_SESSIONS_OR_AUTH_HEADERS")
        if any(name.lower().startswith(("x-forwarded-","forwarded"))
               for name in self.headers):
            raise LabHold("NO_PROXY_HEADERS")
        if "?" in self.path or "#" in self.path:
            raise LabHold("NO_URL_PARAMETERS")
        if write:
            if (self.headers.get("Origin")!=ORIGIN
                or self.headers.get("X-Lab-CSRF")!=self.server.state.csrf
                or self.headers.get("Content-Type")!="application/json"):
                raise LabHold("WRONG_ORIGIN_OR_CSRF")

    def _json(self,code,obj):
        raw=json.dumps(obj,separators=(",",":"),ensure_ascii=True).encode()
        self._headers(code)
        self.wfile.write(raw)

    def do_GET(self):
        try:
            self._allowed(write=False)
            if self.path=="/":
                path=HERE/"stage15-passkey-browser-lab.html"
                mime="text/html; charset=utf-8"
            elif self.path=="/lab.js":
                path=HERE/"stage15-passkey-browser-lab.js"
                mime="text/javascript; charset=utf-8"
            elif self.path=="/api/status":
                result=self.server.state.status()
                result["csrf"]=self.server.state.csrf
                self._json(200,result)
                return
            else:
                raise LabHold("UNKNOWN_PATH")
            raw=path.read_bytes()
            if len(raw)>100000:raise LabHold("LAB_ASSET_OVERSIZE")
            self._headers(200,mime)
            self.wfile.write(raw)
        except (LabHold,OSError):
            self._json(409,{"status":"LAB_HOLD"})

    def do_POST(self):
        try:
            self._allowed(write=True)
            length=self.headers.get("Content-Length")
            if not length or not length.isdigit() or not 0<int(length)<=MAX_BODY:
                raise LabHold("BAD_BODY_LENGTH")
            data=json.loads(self.rfile.read(int(length)))
            if type(data) is not dict:raise LabHold("BAD_BODY")
            parts=self.path.strip("/").split("/")
            if len(parts)!=3 or parts[0]!="api" or parts[1] not in (
                "register","authenticate") or parts[2] not in ("start","finish"):
                raise LabHold("UNKNOWN_PATH")
            kind,action=parts[1:]
            if action=="start":
                if data:
                    raise LabHold("UNEXPECTED_REQUEST_DATA")
                answer=self.server.state.start(kind)
            else:
                if set(data)!={"ceremony","response"}:
                    raise LabHold("BAD_BODY")
                answer=self.server.state.complete(
                    kind,data["ceremony"],data["response"])
            self._json(200,answer)
        except (LabHold,ValueError,TypeError,KeyError,OverflowError):
            self._json(409,{"status":"LAB_HOLD"})

    def do_OPTIONS(self):
        self._json(405,{"status":"LAB_HOLD"})


def serve(*,cert,key,confirm):
    check_lab_host(hostname=socket.gethostname(),
                   confirm=confirm,cert=cert,key=key)
    # Deliberately bind only the loopback interface, never the WAN.
    server=ThreadingHTTPServer(("127.0.0.1",PORT),LabHandler)
    server.daemon_threads=True
    server.state=LabState()
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert,keyfile=key)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    print("DISPOSABLE_LAB_ONLY=https://passkey-lab.test")
    print("REAL_BROKER_GRANTS=DISABLED; NO_PRODUCTION_ACCESS")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__=="__main__":
    if len(sys.argv)!=5 or sys.argv[1]!="--isolated-lab":
        raise SystemExit(
            "HOLD: use --isolated-lab ABSOLUTE_TEST_CERT ABSOLUTE_TEST_KEY "
            "I_CONFIRM_DISPOSABLE_OFFLINE_LAB")
    try:
        serve(cert=sys.argv[2],key=sys.argv[3],confirm=sys.argv[4])
    except (LabHold,OSError,ssl.SSLError):
        raise SystemExit("HOLD_LAB_NOT_ISOLATED_OR_TLS_NOT_READY")
