#!/usr/bin/env python3
"""Stage15 independent review via an HTTP-only UNIX socket.

Never listens on TCP. Does not share Panel session/cookies, does not make a
TrustedGrant from a Panel assertion. Production requires explicitly provisioned
read-only, independently verified evidence_provider and root grant_writer.
The root-owned broker remains the ONLY component that executes Nginx changes.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import socketserver
import stat
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
IDENT = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
HEX = re.compile(r"[a-f0-9]{64}\Z")
SAFE = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}
MAX_BODY = 16 * 1024


class ApprovalServiceHold(RuntimeError):
    pass


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise ApprovalServiceHold("APPROVAL_DEPENDENCY_MISSING")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _read_private(path: Path, *, max_bytes: int = 8192) -> bytes:
    s = path.lstat()
    if (not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_nlink != 1
            or stat.S_IMODE(s.st_mode) != 0o600 or not 0 < s.st_size <= max_bytes):
        raise ApprovalServiceHold("UNTRUSTED_APPROVAL_FILE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        t = os.fstat(fd)
        if (s.st_dev, s.st_ino) != (t.st_dev, t.st_ino):
            raise ApprovalServiceHold("APPROVAL_FILE_CHANGED")
        result = os.read(fd, max_bytes + 1)
        if len(result) != s.st_size:
            raise ApprovalServiceHold("APPROVAL_FILE_CHANGED")
        return result
    finally:
        os.close(fd)


class IndependentApproval:
    """Transport-agnostic lifecycle; all authority resides on root side."""

    def __init__(self, *, queue_dir: Path, broker_key: bytes, ledger,
                 credential_store, origin: str, evidence_provider=None,
                 grant_writer=None, ir_public_key: bytes = b"",
                 kh_public_key: bytes = b"", lease_public_key: bytes = b"",
                 root_check: bool = True):
        gate = module("uopti_web_gate", "smite-stage15-web-approval.py")
        self.queue = module("uopti_web_queue", "smite-stage15-approval-queue.py")
        self.queue_dir = Path(queue_dir)
        self.queue._trusted_directory(self.queue_dir, root_check=root_check)
        gate._server(origin)
        if type(broker_key) is not bytes or len(broker_key) != 32:
            raise ApprovalServiceHold("INVALID_BROKER_KEY")
        self.gate, self.ledger = gate, ledger
        self.credentials = credential_store
        self.origin, self.key = origin, broker_key
        self.ir_public_key, self.kh_public_key = ir_public_key, kh_public_key
        self.lease_public_key = lease_public_key
        self.evidence_provider = evidence_provider
        self.grant_writer = grant_writer
        self.root_check = root_check

    def pending(self, child: str) -> dict:
        if type(child) is not str or not IDENT.fullmatch(child):
            raise ApprovalServiceHold("INVALID_CHILD")
        entries = []
        for path in self.queue_dir.glob("proposal-*.json"):
            try:
                meta = json.loads(self.queue._file(path, root_check=self.root_check))
                if meta.get("child") == child:
                    digest = meta.get("digest")
                    facts = self.queue.review(
                        directory=self.queue_dir, digest=digest, key=self.key,
                        now=int(time.time()), root_check=self.root_check)
                    entries.append({"digest": digest, "binding": facts})
            except Exception as exc:
                # A corrupt or expired entry must not be silently skipped.
                raise ApprovalServiceHold("PENDING_QUEUE_HOLD") from exc
        if len(entries) != 1:
            raise ApprovalServiceHold("NO_UNIQUE_PENDING_PROPOSAL")
        return entries[0]

    def challenge(self, *, child: str, digest: str) -> dict:
        pending = self.pending(child)
        if pending["digest"] != digest:
            raise ApprovalServiceHold("PENDING_PROPOSAL_CHANGED")
        return self.ledger.begin(digest, origin=self.origin,
                                 passkeys=self.credentials.encoded(), now=int(time.time()))

    def complete(self, *, child: str, digest: str, challenge_id: str,
                 assertion: dict) -> dict:
        # Consumes the one-use WebAuthn challenge before any grant or publish.
        pending = self.pending(child)
        if pending["digest"] != digest:
            raise ApprovalServiceHold("PENDING_PROPOSAL_CHANGED")
        credential_hash = self.ledger.consume(challenge_id, digest=digest,
            origin=self.origin, passkeys=self.credentials.encoded(),
            assertion=assertion, now=int(time.time()))
        self.credentials.check_and_advance(credential_hash, assertion)
        if self.evidence_provider is None or self.grant_writer is None:
            raise ApprovalServiceHold("ROOT_INDEPENDENT_EVIDENCE_NOT_CONFIGURED")
        binding = self.pending(child)["binding"]
        if binding != pending["binding"]:
            raise ApprovalServiceHold("PENDING_CHANGED_DURING_REVIEW")
        # This callback MUST query current, separately authenticated IR/KH
        # runtime and the independently mounted read-only lease database.
        bundle = self.evidence_provider(dict(binding))
        self.ledger.record_verified_approval(
            digest=digest, credential_sha256=credential_hash,
            binding=binding, bundle=bundle,
            ir_public_key=self.ir_public_key, kh_public_key=self.kh_public_key,
            lease_public_key=self.lease_public_key,
            now=int(time.time()))
        # Exclusive root-owned create. Any interruption after the durable
        # approval ledger commit is HOLD and requires explicit reconciliation.
        self.grant_writer(dict(binding))
        return {"status":"approved","child":binding["child"],
                "port":binding["port"],"path":binding["path"],"digest":digest}

    def enroll_begin(self, *, ticket: str) -> dict:
        return self.credentials.enroll_begin(ticket, origin=self.origin)

    def enroll_complete(self, *, ceremony: str, response: dict, ticket: str) -> dict:
        self.credentials.enroll_complete(ceremony, response, ticket, origin=self.origin)
        return {"status":"enrolled"}


# Browser runs ONLY on the dedicated independent HTTPS origin. The root
# service itself has no TLS: the reviewed reverse proxy must terminate TLS.
HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Independent XHTTP Approval</title><style>
body{font:16px system-ui;background:#0e172b;color:#f4f7ff;max-width:670px;margin:3rem auto;padding:1rem}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#1b2a45;padding:1.2rem;border-radius:.6rem}
button{background:#536dff;color:white;border:0;padding:1rem;border-radius:.6rem;cursor:pointer}
button:disabled{opacity:.4}#message{margin:1rem 0}
</style></head><body><h1>Independent route approval</h1>
<p>Verify the exact owner, child, lease, port, path and independent evidence hashes.</p>
<pre id="facts">Loading…</pre><button id="approve" disabled>Verify passkey & approve</button>
<p id="message" role="status"></p>
<script>
const search=new URLSearchParams(location.search),child=search.get('child');
const digestText=document.getElementById('facts'),button=document.getElementById('approve');
const message=document.getElementById('message');
function bytes(b64){const s=b64.replace(/-/g,'+').replace(/_/g,'/');
  const decoded=atob(s+'='.repeat((4-s.length%4)%4));
  return Uint8Array.from(decoded,c=>c.charCodeAt(0));}
function encoded(value){let binary='';for(const b of new Uint8Array(value))binary+=String.fromCharCode(b);
  return btoa(binary).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
async function call(endpoint,payload){
  const res=await fetch(endpoint,{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)});if(!res.ok)throw Error('Independent approval HOLD: '+res.status);
  return res.json();}
let current=null;
(async()=>{try{
  if(!/^[A-Za-z0-9_-]{8,128}$/.test(child||''))throw Error('Invalid child');
  const res=await fetch('/api/pending?child='+encodeURIComponent(child),{credentials:'omit'});
  if(!res.ok)throw Error('Pending review unavailable');
  current=await res.json();
  digestText.textContent=JSON.stringify(current.binding,null,2)+'\nProposal SHA256: '+current.digest;
  button.disabled=false;
}catch(e){message.textContent=String(e);}})();
button.onclick=async()=>{button.disabled=true;try{
  const c=await call('/api/challenge',{child,digest:current.digest});
  const p=c.options.publicKey;p.challenge=bytes(p.challenge);
  p.allowCredentials=(p.allowCredentials||[]).map(v=>({...v,id:bytes(v.id)}));
  const assertion=await navigator.credentials.get({publicKey:p});
  const a={id:assertion.id,rawId:encoded(assertion.rawId),type:'public-key',
    response:{clientDataJSON:encoded(assertion.response.clientDataJSON),
      authenticatorData:encoded(assertion.response.authenticatorData),
      signature:encoded(assertion.response.signature),
      userHandle:assertion.response.userHandle?encoded(assertion.response.userHandle):null}};
  const outcome=await call('/api/complete',{child,digest:current.digest,
    challenge_id:c.challenge_id,assertion:a});
  message.textContent='Approved by independent Root review. Returning to Smite.';
  if(window.opener)window.opener.postMessage({
    type:'u-opti:stage15:root-review:v1',status:'approved',
    child:outcome.child,port:outcome.port,path:outcome.path,
    digest:outcome.digest},location.origin);
}catch(e){message.textContent='HOLD / Requires Review: '+String(e);}
};
</script></body></html>"""


class ApprovalHandler(BaseHTTPRequestHandler):
    server_version = "Independent-Approval/1"
    def log_message(self, format, *args):
        return  # Do not log credentials, queries, signatures or raw response.

    def _reply(self, status: int, data, *, html=False):
        raw = data.encode("utf-8") if html else json.dumps(data, separators=(",",":")).encode("utf-8")
        self.send_response(status)
        for k,v in SAFE.items():
            self.send_header(k, "text/html; charset=utf-8" if k=="Content-Type" and html else v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _admit(self, *, mutate: bool):
        origin = self.server.application.origin
        if (self.headers.get("Host") != urlsplit(origin).netloc
                or self.headers.get("X-Forwarded-Host")
                or self.headers.get("X-Forwarded-Proto")
                or self.headers.get("X-Forwarded-For")):
            raise ApprovalServiceHold("UNTRUSTED_PROXY_HOST")
        # No CORS at all. Same-origin POST with explicit exact Origin;
        # stolen Panel cookies are irrelevant because none are accepted.
        if mutate and (self.headers.get("Origin") != origin
                       or self.headers.get("Cookie")
                       or self.headers.get("Content-Type") != "application/json"):
            raise ApprovalServiceHold("CROSS_ORIGIN_OR_CSRF_REFUSED")

    def do_GET(self):
        try:
            self._admit(mutate=False)
            u=urlsplit(self.path)
            q=parse_qs(u.query)
            if u.path == "/review" and set(q)=={"child"} and len(q["child"])==1:
                self._reply(200,HTML,html=True)
            elif u.path=="/api/pending" and set(q)=={"child"} and len(q["child"])==1:
                self._reply(200,self.server.application.pending(q["child"][0]))
            else:
                self._reply(404,{"status":"HOLD"})
        except Exception:
            self._reply(409,{"status":"HOLD"})

    def do_POST(self):
        try:
            self._admit(mutate=True)
            raw_size=self.headers.get("Content-Length")
            if raw_size is None or not raw_size.isdecimal() or not 1<=int(raw_size)<=MAX_BODY:
                raise ApprovalServiceHold("INVALID_REQUEST_SIZE")
            data=json.loads(self.rfile.read(int(raw_size)))
            if type(data) is not dict:
                raise ApprovalServiceHold("INVALID_REQUEST")
            u=urlsplit(self.path)
            if u.query: raise ApprovalServiceHold("QUERY_NOT_ALLOWED")
            a=self.server.application
            if u.path=="/api/challenge" and set(data)=={"child","digest"}:
                outcome=a.challenge(**data)
            elif u.path=="/api/complete" and set(data)=={"child","digest","challenge_id","assertion"}:
                outcome=a.complete(**data)
            elif u.path=="/api/enroll/begin" and set(data)=={"ticket"}:
                outcome=a.enroll_begin(**data)
            elif u.path=="/api/enroll/complete" and set(data)=={"ceremony","response","ticket"}:
                outcome=a.enroll_complete(**data)
            else:
                raise ApprovalServiceHold("UNKNOWN_MUTATION")
            self._reply(200,outcome)
        except Exception:
            self._reply(409,{"status":"HOLD"})


class ApprovalUDSServer(socketserver.UnixStreamServer):
    allow_reuse_address=False
    def __init__(self,path: str,app: IndependentApproval):
        self.application=app
        p=Path(path)
        if p.exists() or p.is_symlink():
            raise ApprovalServiceHold("REVIEW_SOCKET_ALREADY_EXISTS")
        parent=p.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or (os.geteuid()==0 and parent.st_uid!=0)
                or stat.S_IMODE(parent.st_mode) not in (0o700,0o750)):
            raise ApprovalServiceHold("REVIEW_SOCKET_PARENT_UNTRUSTED")
        super().__init__(path, ApprovalHandler, bind_and_activate=True)
        os.chmod(path,0o660)

    def server_close(self):
        path=self.server_address
        try: super().server_close()
        finally: Path(path).unlink(missing_ok=True)


if __name__=="__main__":
    # Deliberately no network CLI and no implicit production bootstrap.
    raise SystemExit("HOLD_SERVICE_REQUIRES_EXPLICIT_ROOT_PROVISIONING")
