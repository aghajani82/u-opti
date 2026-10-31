#!/usr/bin/env python3
"""Standalone, local-only WebAuthn browser test.

This is NOT U-OPTI Approval, NOT the Root service, NOT a tunnel publisher.
No files, databases, secrets, API clients, OS trust changes, or production
connections. All public test credential material lives in RAM until exit.
Run only on the operator's own laptop with a venv containing fido2==2.0.0.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import secrets
import threading
import time
import re

from fido2.server import Fido2Server
from fido2.webauthn import PublicKeyCredentialRpEntity, PublicKeyCredentialUserEntity

HOST = "127.0.0.1"
PORT = 8765
ORIGIN = f"http://localhost:{PORT}"
MAX_BYTES = 16384
TTL = 120

PAGE = r'''<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>آزمایش محلی Passkey</title>
<style>
body {font: 17px Tahoma, sans-serif; max-width:700px; margin:5vh auto; padding:0 18px; line-height:1.9; background:#f4f7fb; color:#18253b}
section {background:white;padding:22px;border-radius:18px;box-shadow:0 4px 18px #dce2eb}
button {background:#2458bd;color:white;border:0;border-radius:9px;font:16px Tahoma;padding:12px;margin:8px 0;cursor:pointer}
button:disabled {opacity:.5} #result {background:#eaf0ff;padding:16px;white-space:pre-wrap;border-radius:9px;min-height:32px}
small {color:#435371}
</style></head><body><section>
<h2>🔐 آزمایش محلی Passkey با یاندکس و گوشی</h2>
<p>این سرویس فقط روی لپ‌تاپ خودت اجرا شده. هیچ ارتباطی با IR، KH، Grandoptical، Broker یا انتشار تانل ندارد.</p>
<p><button id="register">۱. ثبت Passkey آزمایشی</button> <button id="login">۲. ورود با Passkey</button></p>
<p id="result" role="status">آماده بررسی قابلیت مرورگر...</p>
<small>Passkey مربوط به «localhost» در گوشی ایجاد می‌شود و ممکن است بعد از بستن تست در مدیر Passkey گوشی باقی بماند. این یک آزمایش گذراست، نه سرویس واقعی پروژه.</small>
</section>
<script>
"use strict";
let csrf = null;
let busy = false;
let phase = "idle";
const out=document.getElementById("result");
const register=document.getElementById("register"), login=document.getElementById("login");
async function post(path, obj){
 const r=await fetch(path,{method:"POST",cache:"no-store",credentials:"omit",headers:{"Content-Type":"application/json","X-Lab-CSRF":csrf},body:JSON.stringify(obj)});
 if(!r.ok) throw new Error("TEST_HOLD_HTTP_"+r.status);
 return r.json();
}
async function refresh(){
 const r=await fetch("/api/status",{cache:"no-store",credentials:"omit"});
 if(!r.ok) throw new Error("LAB_OFFLINE");
 const s=await r.json();csrf=s.csrf;
 return "تعداد Passkeyهای ثبت‌شده در آزمایش: "+s.registered+" | ورود موفق: "+s.authenticated;
}
async function run(kind){
 if(busy)return;
 busy=true; register.disabled=login.disabled=true;
 try {
  phase="preflight";
  if(!window.isSecureContext || location.origin!=="http://localhost:8765") throw Error("ORIGIN_OR_SECURE_CONTEXT_HOLD");
  if(typeof PublicKeyCredential==="undefined" || !navigator.credentials || typeof PublicKeyCredential.parseCreationOptionsFromJSON!=="function" || typeof PublicKeyCredential.parseRequestOptionsFromJSON!=="function") throw Error("BROWSER_WEBAUTHN_API_HOLD");
  phase="start";
  const start=await post("/api/"+kind+"/start",{});
  out.textContent="در انتظار انتخاب گوشی و تأیید اثر انگشت یا PIN...";
  // python-fido2 wraps browser-ready creation/request fields in "publicKey".
  // Browser parse*OptionsFromJSON expects only that INNER object, not the wrapper.
  if (!start.options || typeof start.options.publicKey!=="object" || !start.options.publicKey)
    throw Error("SERVER_WEBAUTHN_OPTIONS_HOLD");
  phase="parse_options";
  const opts=kind==="register"
    ? PublicKeyCredential.parseCreationOptionsFromJSON(start.options.publicKey)
    : PublicKeyCredential.parseRequestOptionsFromJSON(start.options.publicKey);
  phase="device";
  const c=kind==="register"
    ? await navigator.credentials.create({publicKey:opts})
    : await navigator.credentials.get({publicKey:opts});
  if(!c || typeof c.toJSON!=="function") throw Error("AUTHENTICATOR_RESULT_HOLD");
  phase="complete";
  const done=await post("/api/"+kind+"/complete",{ceremony:start.ceremony,response:c.toJSON()});
  out.textContent=done.status+" ✅\n"+await refresh();
 } catch(err) {
  out.textContent="HOLD: "+(err && err.name ? err.name : "UnknownError")+" | STAGE="+phase+"\n"+(err && /^TEST_HOLD|^LAB_OFFLINE|^BROWSER_|^ORIGIN_|^SERVER_WEBAUTHN/.test(err.message||"") ? err.message : "عملیات تکمیل نشد؛ بدون تغییر روی سرورها.");
 } finally {busy=false;phase="idle";register.disabled=login.disabled=false;}
}
register.onclick=()=>run("register");login.onclick=()=>run("authenticate");
(async()=>{
 try {
  if(!isSecureContext) throw Error("SECURE_CONTEXT_UNAVAILABLE");
  out.textContent="آماده ✅\n"+await refresh();
 } catch(e) {out.textContent="HOLD: WebAuthn در این آدرس در دسترس نیست.";}
})();
</script></body></html>'''

class State:
    def __init__(self):
        self.lock=threading.RLock()
        self.server=Fido2Server(
            PublicKeyCredentialRpEntity(id="localhost",name="Temporary Local Passkey Test"),
            verify_origin=lambda origin: origin==ORIGIN)
        self.user_id=secrets.token_bytes(32)
        self.csrf=secrets.token_urlsafe(32)
        self.credentials={}
        self.pending={}
        self.authenticated=0

    def start(self,kind):
        with self.lock:
            if kind=="register":
                if len(self.credentials)>=2:
                    raise ValueError("MAX_TWO_TEST_PASSKEYS")
                user=PublicKeyCredentialUserEntity(
                    id=self.user_id,name="local-test",display_name="Local Test Only")
                options,server_state=self.server.register_begin(
                    user,credentials=list(self.credentials.values()),
                    resident_key_requirement="required",user_verification="required")
            elif kind=="authenticate":
                if not self.credentials:
                    raise ValueError("NO_REGISTERED_PASSKEY")
                options,server_state=self.server.authenticate_begin(
                    list(self.credentials.values()),user_verification="required")
            else:
                raise ValueError("UNKNOWN_ACTION")
            ceremony=secrets.token_hex(16)
            self.pending.clear()
            self.pending[ceremony]=(kind,server_state,time.monotonic()+TTL)
            return {"ceremony":ceremony,"options":dict(options)}

    def complete(self,kind,payload):
        if (not isinstance(payload,dict) or set(payload)!={"ceremony","response"}
            or not isinstance(payload["ceremony"],str)
            or not re.fullmatch(r"[0-9a-f]{32}",payload["ceremony"])
            or type(payload["response"]) is not dict):
            raise ValueError("INVALID_RESPONSE")
        with self.lock:
            saved=self.pending.pop(payload["ceremony"],None)
            if (saved is None or saved[0]!=kind or time.monotonic()>saved[2]):
                raise ValueError("CHALLENGE_EXPIRED_OR_REPLAY")
            if kind=="register":
                verified=self.server.register_complete(saved[1],payload["response"])
                if not verified.is_user_verified():
                    raise ValueError("USER_VERIFICATION_REQUIRED")
                cred=verified.credential_data
                if cred is None or not cred.credential_id or cred.credential_id in self.credentials:
                    raise ValueError("DUPLICATE_OR_INVALID_CREDENTIAL")
                self.credentials[cred.credential_id]=cred
                return {"status":"LOCAL_REGISTER_PASS"}
            if kind=="authenticate":
                cred=self.server.authenticate_complete(saved[1],list(self.credentials.values()),payload["response"])
                if cred.credential_id not in self.credentials:
                    raise ValueError("UNREGISTERED_PASSKEY")
                self.authenticated+=1
                return {"status":"LOCAL_AUTHENTICATION_PASS_NO_GRANT"}
            raise ValueError("UNKNOWN_ACTION")

class Handler(BaseHTTPRequestHandler):
    server_version="PasskeyLocalOnly"
    sys_version=""

    def log_message(self,format,*args):
        return  # avoid logging credentials or browser details

    def answer(self,status,obj,*,html=False):
        raw=PAGE.encode("utf-8") if html else json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","text/html; charset=utf-8" if html else "application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def admit(self,write=False):
        if self.headers.get("Host")!=f"localhost:{PORT}":
            raise ValueError("HOST_NOT_LOCALHOST")
        if self.headers.get("Cookie") or self.headers.get("Authorization"):
            raise ValueError("AUTH_HEADERS_FORBIDDEN")
        if any(k.lower().startswith(("x-forwarded-","forwarded")) for k in self.headers):
            raise ValueError("PROXY_HEADERS_FORBIDDEN")
        if "?" in self.path or "#" in self.path:
            raise ValueError("URL_PARAMETER_FORBIDDEN")
        if write:
            if (self.headers.get("Origin")!=ORIGIN or
                self.headers.get("X-Lab-CSRF")!=self.server.state.csrf or
                self.headers.get("Content-Type")!="application/json"):
                raise ValueError("ORIGIN_OR_CSRF_REJECTED")

    def do_GET(self):
        try:
            self.admit()
            if self.path=="/":
                self.answer(200,{},html=True)
            elif self.path=="/api/status":
                with self.server.state.lock:
                    self.answer(200,{"registered":len(self.server.state.credentials),
                        "authenticated":self.server.state.authenticated,
                        "csrf":self.server.state.csrf,
                        "root_grants":"NONE", "tunnel_changes":"NONE"})
            else:
                raise ValueError("UNKNOWN_PATH")
        except ValueError:
            self.answer(409,{"status":"LOCAL_TEST_HOLD"})

    def do_POST(self):
        try:
            self.admit(write=True)
            content_length=self.headers.get("Content-Length")
            if not content_length or not content_length.isdigit() or not 0<int(content_length)<=MAX_BYTES:
                raise ValueError("INVALID_CONTENT_LENGTH")
            payload=json.loads(self.rfile.read(int(content_length)))
            kind,action=(self.path.split("/")[2:] if self.path.startswith("/api/") else (None,None))
            if kind not in ("register","authenticate") or action not in ("start","complete"):
                raise ValueError("UNKNOWN_ACTION")
            if action=="start":
                if payload!={}: raise ValueError("UNEXPECTED_DATA")
                result=self.server.state.start(kind)
            else:
                result=self.server.state.complete(kind,payload)
            self.answer(200,result)
        except (ValueError,TypeError,KeyError,IndexError,json.JSONDecodeError):
            self.answer(409,{"status":"LOCAL_TEST_HOLD"})

    def do_OPTIONS(self):
        self.answer(405,{"status":"LOCAL_TEST_HOLD"})


def main():
    import sys
    if sys.argv[1:] != ["--local-test-only"]:
        raise SystemExit("HOLD: explicit --local-test-only required")
    httpd=ThreadingHTTPServer((HOST,PORT),Handler)
    httpd.daemon_threads=True
    httpd.state=State()
    print("LOCAL_PASSKEY_TEST=http://localhost:8765",flush=True)
    print("BIND=127.0.0.1; NO_TLS_CA; NO_MKCERT; NO_GRANTS; NO_SERVER_CHANGES",flush=True)
    print("STOP=Ctrl+C; ALL_LOCAL_SERVER_PASSKEYS_IN_MEMORY_WILL_BE_LOST",flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

if __name__=="__main__":
    main()