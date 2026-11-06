#!/usr/bin/env python3
"""PR-only real signed Nodes + FRP WSS/443 forwarding, NO recreation.

Two ordinary Docker containers on a private --internal bridge, never on real
IR/Grandoptical. This tests the existing RC7 *filesystem* two-receipt lab
while genuine signed Smite API and FRP 0.71.0 WSS-over-TLS forwarding persist.
A disposable Nginx runs in a third isolated container: NO host port publish,
no production Nginx/443 access. Real isolated Broker/Node UDS denial\nis checked without bypassing the missing committed XHTTP Bridge.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
NODE_SOURCE = REPO / ".managed-smite-source"
CHILD_SOURCE = REPO / ".signed-owner-smite-source"
CHILD_SHA = "115f032761564a069d0aa2ca891e55d53a1c6ea0"
SMITE_SHA = "02d05056d3a4baf577c9d3781d62af61c000f1ac"
IMAGE = ("ghcr.io/aghajani82/smite-node@sha256:"
         "03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263")
FRP_ARCHIVE_SHA = "84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716"
BACKHAUL_ARCHIVE_SHA = "57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc"
MARKER = "U-OPTI-BACKHAUL-ISOLATED-LAB-V1\n"
DOCKER_NAMES = ("ci-uopti-ir", "ci-uopti-foreign", "ci-uopti-wss",
                "ci-uopti-bh-bridge", "ci-uopti-broker")
BROKER_GID = 1348
BROKER_INSTANCE = "ci-broker-ir-0001"


class Hold(RuntimeError):
    pass


def check(condition: bool, code: str):
    if not condition:
        raise Hold(code)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(*command: str, timeout: int = 75) -> str:
    """Never echo potentially sensitive subprocess output."""
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("ISOLATED_PROCESS_UNAVAILABLE") from exc
    if result.returncode != 0:
        # Static error category only. Never echo command arguments: these
        # may include ephemeral credentials or private filesystem paths.
        category = ("DOCKER_" + command[1].upper()
                    if command[0] == "docker" and len(command) >= 2
                    else "OPENSSL" if command[0] == "openssl"
                    else "OTHER")
        raise Hold("ISOLATED_" + category + "_PROCESS_FAILED")
    return result.stdout.strip()


def write(path: Path, payload: bytes, mode: int = 0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def directory(path: Path):
    path.mkdir(mode=0o700)
    path.chmod(0o700)


def load(name: str, source: Path):
    spec = importlib.util.spec_from_file_location(name, source)
    check(spec is not None and spec.loader is not None, "CI_HELPER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def official_frp(archive: Path) -> dict[str, bytes]:
    raw = archive.read_bytes()
    check(sha(raw) == FRP_ARCHIVE_SHA, "FRP_OFFICIAL_ARCHIVE_PIN_MISMATCH")
    results = {}
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        for binary in ("frpc", "frps"):
            name = f"frp_0.71.0_linux_amd64/{binary}"
            matches = [member for member in members if member.name == name]
            check(len(matches) == 1 and matches[0].isfile()
                  and 0 < matches[0].size <= 48 * 1024 * 1024,
                  "FRP_OFFICIAL_ARCHIVE_SHAPE_INVALID")
            fp = tf.extractfile(matches[0])
            check(fp is not None, "FRP_OFFICIAL_BINARY_MISSING")
            data = fp.read(48 * 1024 * 1024 + 1)
            check(len(data) == matches[0].size and data.startswith(b"\x7fELF"),
                  "FRP_OFFICIAL_BINARY_UNTRUSTED")
            results[binary] = data
    return results


def initial_role(root: Path, role: str, frp: dict[str, bytes],
                 backhaul: bytes, secret: str, token: str, tx):
    write(root / "EXPERIMENTAL-LAB", MARKER.encode())
    directory(root / "node")
    directory(root / "node/config")
    directory(root / "node/config/engine-state")
    directory(root / "node/config/identity")
    directory(root / "node-data")
    directory(root / "node-data/auth")
    directory(root / "stages")
    directory(root / "engines")
    directory(root / "rc7-frp-enrollment")
    # Existing Node Compose and environment are immutable through this test.
    write(root / "node/docker-compose.yml",
          b"services:\n  smite-node:\n    image: smite-node:stage15-local\n"
          b"    network_mode: host\n    volumes:\n      - ./config:/etc/smite-node\n")
    write(root / "node/.env",
          (f"NODE_ROLE={role}\nSMITE_AGENT_AUTH_MODE=strict\n"
           "SMITE_ENGINE_INVENTORY_MODE=managed\n").encode())
    for name, binary in frp.items():
        write(root / "engines" / name, binary, 0o555)
    write(root / "engines/backhaul", backhaul, 0o555)
    manifest = (json.dumps({
        "schema": 1, "engines": {
            "frp": {"sha256": sha(frp["frpc"]), "server_sha256": sha(frp["frps"])},
            "gost": {"sha256": "d" * 64},
        },
    }, sort_keys=True, indent=2) + "\n").encode()
    write(root / "node/config/engine-state/engines.json", manifest)
    receipt = (json.dumps({
        "schema": 1, "role": role, "state": "COMMITTED", "old": None,
        "new": sha(manifest),
        "binaries": {"frpc": sha(frp["frpc"]), "frps": sha(frp["frps"])},
    }, sort_keys=True) + "\n").encode()
    write(root / "rc7-frp-enrollment/record.json", receipt)
    write(root / "node/config/identity/node-identity.json",
          (json.dumps({"node_id": ("smitecibackhaul01" if role == "ir"
                                   else "smitecibackhaul02"),
                       "node_secret": secret}) + "\n").encode())
    # Synthetic preserved-data fixtures are NOT signed runtime observations.
    for name, doc in (
        ("frp-owner-child.fixture.json", {"role": role, "frp": "0.71.0",
                                          "tunnels": ["20182", "optical", "nahavi"]}),
        ("broker-replay.fixture.json", {"role": role, "identity": role + "-ci",
                                       "broker": "up", "replay": "durable"}),
    ):
        write(root / "node-data" / name,
              (json.dumps(doc, sort_keys=True) + "\n").encode())
    if role != "ir":
        config = ("serverAddr = \"ci-uopti-wss\"\nserverPort = 443\n"
                  "loginFailExit = false\n"
                  "auth.method = \"token\"\nauth.token = " + json.dumps(token) + "\n"
                  "transport.protocol = \"wss\"\n"
                  "transport.tls.enable = true\n"
                  "transport.tls.trustedCaFile = \"/etc/smite-node/ci-ca.crt\"\n"
                  "transport.tls.serverName = \"ci-uopti-wss\"\n"
                  "[[proxies]]\nname = \"ci-only-20182\"\ntype = \"tcp\"\n"
                  "localIP = \"127.0.0.1\"\nlocalPort = 39001\n"
                  "remotePort = 20182\n")
        write(root / "node/config/frpc.toml", config.encode())
    return manifest, receipt


PROBE = r"""
import json,sys,urllib.request,urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
phase=sys.argv[1]
node_id,secret=read_identity('/etc/smite-node/identity/node-identity.json')
def get(path,headers=None):
 req=urllib.request.Request('http://127.0.0.1:8888'+path,headers=headers or {})
 try:
  with urllib.request.urlopen(req,timeout=4) as resp:
   return resp.status,json.load(resp)
 except urllib.error.HTTPError as exc:
  return exc.code,{}
endpoint='/api/agent/engines'
assert get(endpoint)[0]==401
# Even an authentically signed request for the *other* CI Node must
# not be accepted by this Node. Both identities persist through rollback.
foreign_id=('smitecibackhaul02' if node_id=='smitecibackhaul01'
            else 'smitecibackhaul01')
assert get(endpoint,sign_request(secret=secret,node_id=foreign_id,
             method='GET',target=endpoint,body=b''))[0]==401, \
       'cross-node identity accepted'
signed=sign_request(secret=secret,node_id=node_id,method='GET',target=endpoint,body=b'')
status,body=get(endpoint,signed)
assert status==200 and body['mode']=='managed',(status,body)
assert body['engines']['frp']=='ready',body
assert body['engines']['backhaul']==('ready' if phase=='ready' else 'not-installed'),body
assert get(endpoint,signed)[0]==401,'nonce replay accepted'
status,data=get('/api/agent/status',sign_request(secret=secret,node_id=node_id,method='GET',target='/api/agent/status',body=b''))
assert status==200 and data['status']=='ok',(status,data)
print('REAL_SIGNED_NODE_ENGINE_AND_REPLAY=PASS')
"""

FORWARD = r"""
import socket,sys
payload=b'rc7-ci-continuity-'+sys.argv[1].encode()
with socket.create_connection(('127.0.0.1',20182),timeout=3) as conn:
 conn.settimeout(3)
 conn.sendall(payload)
 reply=conn.recv(256)
assert reply==b'CI-ACK:'+payload,reply
print('REAL_ISOLATED_FRP_FORWARDING=PASS')
"""

ECHO = r"""
import socket
with socket.socket() as srv:
 srv.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 srv.bind(('127.0.0.1',39001))
 srv.listen(16)
 while True:
  conn,_=srv.accept()
  with conn:
   data=conn.recv(256)
   conn.sendall(b'CI-ACK:'+data)
"""


# Actual Nginx HTTP Upgrade and real CA/hostname validation are tested
# inside the internal-only bridge. Existing repository WSS control-stall
# Dockerfile is reused, not a separate production gateway/installer.
HTTPS_PROBE = r"""
import socket,ssl,sys,urllib.request
ca='/etc/smite-node/ci-ca.crt'
ctx=ssl.create_default_context(cafile=ca)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                  urllib.request.HTTPSHandler(context=ctx))
with opener.open('https://ci-uopti-wss:443/ci-health',timeout=5) as response:
 assert response.status==200 and response.read()==b'ci-wss-gateway-ok'
# Connect to the SAME Nginx address while requiring the WRONG hostname.
# This must fail actual X.509 hostname verification, not network routing.
with socket.create_connection(('ci-uopti-wss',443),timeout=4) as conn:
 try:
  with ctx.wrap_socket(conn,server_hostname='wrong.invalid'):
   raise AssertionError('invalid WSS hostname unexpectedly accepted')
 except ssl.SSLCertVerificationError:
  pass
print('CI_REAL_NGINX_TLS_CA_AND_HOSTNAME=PASS')
"""


def wss_gateway(network: str, root_ir: Path, root_foreign: Path):
    """Disposable Nginx on a private bridge, no host port mappings."""
    tls = root_ir / "tls"
    directory(tls)
    cert = tls / "cert.pem"
    key = tls / "key.pem"
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-days", "1", "-subj", "/CN=ci-uopti-wss",
        "-addext", "subjectAltName=DNS:ci-uopti-wss,DNS:ci-uopti-wss.local",
        "-keyout", str(key), "-out", str(cert), timeout=40)
    cert.chmod(0o600)
    key.chmod(0o600)
    write(root_foreign / "node/config/ci-ca.crt", cert.read_bytes())
    conf = tls / "nginx.conf"
    # Render existing reviewed Standard Backhaul WS locations. These are
    # added only to the disposable Nginx, never to a live 443 gateway.
    ir_control = run("bash", str(REPO / "modules/smite-backhaul-standard.sh"),
                     "--render-ir-control", "3080")
    check("location = /channel {" in ir_control
          and "location ^~ /tunnel/ {" in ir_control,
          "CI_BACKHAUL_IR_WS_ROUTES_NOT_REVIEWED")
    write(conf, b"""user root;
pid /tmp/ci-nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 256; }
http {
  access_log off;
  client_body_temp_path /tmp;
  proxy_temp_path /tmp;
  fastcgi_temp_path /tmp;
  uwsgi_temp_path /tmp;
  scgi_temp_path /tmp;
  server {
    listen 443 ssl;
    server_name ci-uopti-wss;
    ssl_certificate /ci/cert.pem;
    ssl_certificate_key /ci/key.pem;
    location = /ci-health { return 200 "ci-wss-gateway-ok"; }
    location = /~!frp {
      proxy_pass http://127.0.0.1:7000;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
      proxy_buffering off;
    }
""" + ir_control.encode() + b"""  }
}
""")
    image = "uopti-ci-wss-issue102"
    print("CI_WSS_STAGE=BUILD_NGINX_IMAGE", flush=True)
    run("docker", "build", "-t", image,
        str(REPO / "tests/lab/frp-control-stall"), timeout=280)
    print("CI_WSS_STAGE=START_PRIVATE_NGINX", flush=True)
    run("docker", "run", "-d", "--name", "ci-uopti-wss",
        "--network", "container:ci-uopti-ir",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "96", "--memory", "192m",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m",
        "--mount", f"type=bind,src={conf},dst=/ci/nginx.conf,readonly",
        "--mount", f"type=bind,src={cert},dst=/ci/cert.pem,readonly",
        "--mount", f"type=bind,src={key},dst=/ci/key.pem,readonly",
        "--entrypoint", "nginx", image, "-c", "/ci/nginx.conf",
        "-g", "daemon off;", timeout=150)
    doc = json.loads(run("docker", "inspect", "ci-uopti-wss"))[0]
    # Docker may normalize a "container:name" network mode to the owner's
    # immutable full/short container ID. Match only the exact active IR
    # container, never any arbitrary shared namespace.
    ir_doc = json.loads(run("docker", "inspect", "ci-uopti-ir"))[0]
    mode = doc["HostConfig"]["NetworkMode"]
    check(mode in ("container:ci-uopti-ir", "container:" + ir_doc["Id"],
                   "container:" + ir_doc["Id"][:12]),
          "CI_NGINX_NETWORK_NAMESPACE_MISMATCH")
    check(doc["HostConfig"]["ReadonlyRootfs"] is True
          and doc["HostConfig"]["CapDrop"] == ["ALL"]
          and not doc["HostConfig"]["PortBindings"]
          and doc["HostConfig"]["PublishAllPorts"] is False
          and doc["State"]["Running"] is True,
          "CI_NGINX_WSS_ISOLATION_FAILED")
    return doc["Id"], doc["State"]["StartedAt"]


def https_probe():
    out = run("docker", "exec", "ci-uopti-foreign",
              "python", "-B", "-c", HTTPS_PROBE, timeout=18)
    check("CI_REAL_NGINX_TLS_CA_AND_HOSTNAME=PASS" in out,
          "CI_TLS_CA_HOSTNAME_PROOF_FAILED")






def foreign_backhaul_bridge(root_foreign: Path):
    """Actual existing KH Standard renderer with isolated, verified TLS."""
    config = root_foreign / "backhaul-bridge.conf"
    rendered = run(
        "bash", str(REPO / "modules/smite-backhaul-standard.sh"),
        "--render-kh-bridge", "ci-uopti-wss.local", "13080")
    check("listen 127.0.0.1:13080;" in rendered
          and "proxy_ssl_verify on;" in rendered
          and "proxy_ssl_name ci-uopti-wss.local;" in rendered,
          "CI_FOREIGN_BACKHAUL_BRIDGE_NOT_TLS_VERIFIED")
    write(config, ("""user root;
pid /tmp/ci-bh-nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 256; }
http {
  access_log off;
  client_body_temp_path /tmp;
  proxy_temp_path /tmp;
  fastcgi_temp_path /tmp;
  uwsgi_temp_path /tmp;
  scgi_temp_path /tmp;
""" + rendered + "\n}\n").encode(), 0o600)
    cert = root_foreign / "node/config/ci-ca.crt"
    check(cert.is_file() and cert.stat().st_size > 1000,
          "CI_FOREIGN_TRUSTED_CA_UNAVAILABLE")
    run("docker", "run", "-d", "--name", "ci-uopti-bh-bridge",
        "--network", "container:ci-uopti-foreign",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "96", "--memory", "192m",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m",
        "--mount", f"type=bind,src={config},dst=/ci/nginx.conf,readonly",
        "--mount", f"type=bind,src={cert},dst=/etc/ssl/certs/ca-certificates.crt,readonly",
        "--entrypoint", "nginx", "uopti-ci-wss-issue102",
        "-c", "/ci/nginx.conf", "-g", "daemon off;", timeout=150)
    doc = json.loads(run("docker", "inspect", "ci-uopti-bh-bridge"))[0]
    foreign = json.loads(run("docker", "inspect", "ci-uopti-foreign"))[0]
    mode = doc["HostConfig"]["NetworkMode"]
    check(mode in ("container:ci-uopti-foreign",
                   "container:" + foreign["Id"],
                   "container:" + foreign["Id"][:12])
          and doc["HostConfig"]["ReadonlyRootfs"] is True
          and doc["HostConfig"]["CapDrop"] == ["ALL"]
          and not doc["HostConfig"]["PortBindings"]
          and doc["HostConfig"]["PublishAllPorts"] is False
          and doc["State"]["Running"] is True,
          "CI_FOREIGN_BACKHAUL_TLS_BRIDGE_ISOLATION_FAILED")
    return doc["Id"], doc["State"]["StartedAt"]


BRIDGE_LOOPBACK_ONLY = r"""
import socket
with socket.socket() as peer:
 peer.settimeout(1)
 try:
  peer.connect(('ci-uopti-foreign',13080))
 except (ConnectionRefusedError,TimeoutError,OSError):
  pass
 else:
  raise AssertionError('foreign bridge exposed on private network')
print('CI_FOREIGN_BRIDGE_LOOPBACK_ONLY=PASS')
"""


BACKHAUL_FOREIGN_ECHO = r"""
from http.server import HTTPServer,BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path!='/ci-backhaul-health':
   self.send_error(404)
   return
  payload=b'CI-REAL-FOREIGN-BACKHAUL-ROUNDTRIP'
  self.send_response(200)
  self.send_header('Content-Length',str(len(payload)))
  self.end_headers()
  self.wfile.write(payload)
 def log_message(self,*args):pass
HTTPServer(('127.0.0.1',56053),Handler).serve_forever()
"""


BACKHAUL_IR_FORWARD = r"""
import sys,time,urllib.request
if sys.argv[1]=='absent':
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
          'http://127.0.0.1:56053/ci-backhaul-health',timeout=1):
   raise AssertionError('data path still published after signed removal')
 except (OSError,TimeoutError):
  print('CI_BACKHAUL_DATA_LISTENER_REMOVED=PASS')
else:
 for attempt in range(40):
  try:
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
   with opener.open('http://127.0.0.1:56053/ci-backhaul-health',timeout=2) as resp:
    assert resp.status==200
    assert resp.read()==b'CI-REAL-FOREIGN-BACKHAUL-ROUNDTRIP'
    print('CI_BACKHAUL_REAL_FOREIGN_DATA_OVER_VERIFIED_TLS_443=PASS')
    break
  except (OSError,TimeoutError):
   if attempt==39:raise
   time.sleep(0.5)
"""


def backhaul_data_probe(phase: str):
    check(phase in ("active", "absent"), "CI_BACKHAUL_DATA_PROBE_PHASE_INVALID")
    try:
        proc = subprocess.run(
            ["docker", "exec", "ci-uopti-ir", "python", "-B", "-c",
             BACKHAUL_IR_FORWARD,phase],
            capture_output=True,text=True,timeout=110,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise Hold("CI_BACKHAUL_REAL_DATA_PROBE_UNAVAILABLE") from exc
    label=("CI_BACKHAUL_REAL_FOREIGN_DATA_OVER_VERIFIED_TLS_443=PASS"
           if phase=="active" else "CI_BACKHAUL_DATA_LISTENER_REMOVED=PASS")
    check(proc.returncode==0 and label in proc.stdout,
          "CI_BACKHAUL_FOREIGN_DATA_ROUNDTRIP_NOT_PROVEN")
    print(label,flush=True)


BROKER_BRIDGE_GATE_AUDIT = r"""
import importlib.util,sys
path='/usr/local/lib/u-opti/modules/smite-rc5-xhttp-root-broker.py'
spec=importlib.util.spec_from_file_location('ci_real_broker_gate',path)
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
conf=mod._configuration()
mod._verify_helper(conf)  # The real root-owned, digest-pinned helper bytes.
try:
 mod._verify_bridge()      # No fake Bridge receipt; fail closed.
except mod.BrokerHold as exc:
 assert str(exc)=='XHTTP_BRIDGE_REQUIRED','unexpected Bridge status'
else:
 raise AssertionError('uncommitted Bridge accepted')
print('CI_REAL_BROKER_PINNED_HELPER_AND_BRIDGE_HOLD=PASS')
"""


BROKER_REAL_SIGNED_UNAPPROVED = r"""
import base64,json,sys,urllib.request,urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id,key=read_identity('/etc/smite-node/identity/node-identity.json')
with open(sys.argv[1],'rb') as f:
 intent=f.read()
wire=json.dumps({'intent_b64':base64.b64encode(intent).decode('ascii')},
                separators=(',',':')).encode('utf-8')
target='/api/agent/uopti/xhttp-route'
url='http://127.0.0.1:8888'+target
def request(headers=None):
 h={'Content-Type':'application/json'}
 h.update(headers or {})
 req=urllib.request.Request(url,data=wire,headers=h,method='POST')
 try:
  with urllib.request.urlopen(req,timeout=8) as response:
   return response.status
 except urllib.error.HTTPError as exc:
  return exc.code
assert request()==401,'anonymous route accepted'
assert request(sign_request(secret=key,node_id='smitecibackhaul02',
    method='POST',target=target,body=wire))==401,'foreign identity accepted'
headers=sign_request(secret=key,node_id=node_id,method='POST',
                     target=target,body=wire)
assert request(headers)==503,'missing Bridge must HOLD valid signed intent'
assert request(headers)==401,'agent request Replay accepted'
print('CI_CANONICAL_HMAC_INTENT_MISSING_BRIDGE_FAIL_CLOSED=PASS')
"""


def fresh_unapproved_intent(root: Path) -> str:
    """Private, canonical Broker HMAC wire; synthetic evidence is NEVER a grant."""
    spec = importlib.util.spec_from_file_location(
        "ci_broker_intent_contract",
        REPO / "modules/smite-rc5-xhttp-signed-intent.py")
    check(spec is not None and spec.loader is not None,
          "CI_BROKER_SIGNED_CONTRACT_MISSING")
    contract = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = contract
    spec.loader.exec_module(contract)
    key = (root / "broker-conf/route-broker.key").read_bytes()
    now = int(time.time())
    body = {
        "schema": 1, "audience": contract.AUDIENCE, "action": "create",
        "ir_node": "smitecibackhaul01", "kh_node": "smitecibackhaul02",
        "owner": "ci-owner", "child": "ci-child-20282",
        "lease": "ci-lease-20282", "port": 20282,
        "path": "/20282/ci-xhttp",
        "owner_proof_sha256": "a" * 64, # deliberately untrusted
        "kh_inventory_sha256": "b" * 64, # deliberately untrusted
        "issued_at": now, "expires_at": now + 45,
        "nonce": secrets.token_hex(16),
    }
    wire = contract.canonical({
        **body, "mac": hmac.new(key, contract.canonical(body),
                              hashlib.sha256).hexdigest(),
    })
    path = root / "node/config" / ("ci-unsigned-root-grant-" +
                                 secrets.token_hex(8) + ".json")
    write(path, wire, 0o600)
    # No Broker HMAC key is ever present in Node or supplied via command line.
    return "/etc/smite-node/" + path.name


BROKER_IR_SIGNED_DENIAL = r"""
import base64,json,urllib.request,urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id,key=read_identity('/etc/smite-node/identity/node-identity.json')
target='/api/agent/uopti/xhttp-route'
wire=json.dumps({'intent_b64':base64.b64encode(b'{}').decode('ascii')},
                separators=(',',':')).encode('utf-8')
url='http://127.0.0.1:8888'+target
def post(headers=None):
 http_headers={'Content-Type':'application/json'}
 http_headers.update(headers or {})
 req=urllib.request.Request(url,data=wire,headers=http_headers,method='POST')
 try:
  with urllib.request.urlopen(req,timeout=9) as response:
   return response.status
 except urllib.error.HTTPError as exc:
  return exc.code
assert post()==401,'anonymous broker access accepted'
assert post(sign_request(secret=key,node_id='smitecibackhaul02',
    method='POST',target=target,body=wire))==401,'foreign ID accepted'
headers=sign_request(secret=key,node_id=node_id,
                     method='POST',target=target,body=wire)
headers['Content-Type']='application/json'
assert post(headers)==503,'unapproved broker route must HOLD'
assert post(headers)==401,'broker intent replay accepted'
print('CI_REAL_SIGNED_NODE_TO_BROKER_FAIL_CLOSED=PASS')
"""

BROKER_IR_SOCKET_AUDIT = r"""
import os,socket,stat
path='/run/u-opti/smite/xhttp-broker.sock'
dirpath='/run/u-opti/smite'
dir_st=os.stat(dirpath)
sock_st=os.stat(path)
assert stat.S_ISDIR(dir_st.st_mode) and (dir_st.st_mode & 0o777)==0o750
assert stat.S_ISSOCK(sock_st.st_mode) and (sock_st.st_mode & 0o777)==0o660
assert sock_st.st_uid==0 and sock_st.st_gid==1348
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(5)
 s.connect(path)
 s.sendall(b'{}\n')
 assert s.recv(64)==b'HOLD\n','invalid wire must never publish'
print(str(dir_st.st_dev)+':'+str(dir_st.st_ino))
print('CI_REAL_NODE_BROKER_UNIX_SOCKET_DENIAL=PASS')
"""


def broker_prepare(root: Path):
    """Real root-broker state; no grant and no Nginx/helper route is installed."""
    conf = root / "broker-conf"
    runtime = root / "broker-runtime"
    state = root / "broker-ledger"
    for path in (conf, runtime, state):
        directory(path)
    directory(conf / "route-grants")
    bin_dir = root / "broker-bin"
    directory(bin_dir)
    bin_dir.chmod(0o755)
    for tool in ("smite-xhttp-nginx-route", "smite_xhttp_nginx_plan.py"):
        write(bin_dir / tool, (REPO / "modules" / tool).read_bytes(), 0o755)
    runtime.chmod(0o750)
    os.chown(runtime, 0, BROKER_GID)
    # Broker trusts neither Node identities nor a caller-created root grant.
    write(conf / "route-broker.key", secrets.token_bytes(32))
    doc = {"schema": 1, "instance_id": BROKER_INSTANCE,
           "peer_uid": 0, "peer_gid": BROKER_GID,
           "helper_sha256": sha((REPO / "modules/smite-xhttp-nginx-route").read_bytes()),
           "planner_sha256": sha((REPO / "modules/smite_xhttp_nginx_plan.py").read_bytes())}
    write(conf / "route-broker.json",
          (json.dumps(doc, sort_keys=True) + "\n").encode())
    ledger = load("ci_broker_nonce", REPO / "modules/smite-rc5-xhttp-nonce-ledger.py")
    ledger.DurableNonceLedger.bootstrap_new(
        state / "nonce.db", instance_id=BROKER_INSTANCE)
    return conf, runtime, state


def broker_start(root: Path):
    name = "ci-uopti-broker"
    run("docker", "run", "-d", "--name", name, "--hostname", "ir",
        "--network", "none", "--platform", "linux/amd64",
        "--read-only", "--cap-drop", "ALL", "--cap-add", "CHOWN",
        "--security-opt", "no-new-privileges", "--pids-limit", "64",
        "--memory", "192m", "--user", "0:0",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=8m",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--mount", f"type=bind,src={REPO}/modules,dst=/usr/local/lib/u-opti/modules,readonly",
        "--mount", f"type=bind,src={root}/broker-conf,dst=/etc/u-opti/smite,readonly",
        "--mount", f"type=bind,src={root}/broker-bin,dst=/usr/local/libexec,readonly",
        "--mount", f"type=bind,src={root}/broker-ledger,dst=/var/lib/u-opti/smite-xhttp-broker",
        "--mount", f"type=bind,src={root}/broker-runtime,dst=/run/u-opti/smite",
        "--entrypoint", "python", IMAGE, "-B",
        "/usr/local/lib/u-opti/modules/smite-rc5-xhttp-root-broker.py",
        "--serve", timeout=150)
    doc = json.loads(run("docker", "inspect", name))[0]
    assertions = {
        "network_none": doc["HostConfig"]["NetworkMode"] == "none",
        "readonly_root": doc["HostConfig"]["ReadonlyRootfs"] is True,
        "drop_all": doc["HostConfig"]["CapDrop"] == ["ALL"],
        "only_chown": doc["HostConfig"]["CapAdd"] in (["CHOWN"], ["CAP_CHOWN"]),
        "no_ports": not doc["HostConfig"]["PortBindings"]
                    and doc["HostConfig"]["PublishAllPorts"] is False,
        "running": doc["State"]["Running"] is True,
    }
    # Emit only the failed safe assertion name, never container logs,
    # config, passwords, HTTP headers or private paths.
    for label, passed in assertions.items():
        if not passed:
            print("CI_BROKER_ISOLATION_" + label.upper() + "=HOLD", flush=True)
    check(all(assertions.values()), "CI_BROKER_DOCKER_ISOLATION_FAILED")
    return doc["Id"], doc["State"]["StartedAt"]


def broker_probe(root: Path, original: dict):
    """Both genuine UDS and signed Node->Broker request must deny mutation."""
    for attempt in range(35):
        try:
            reply = run("docker", "exec", "ci-uopti-ir", "python", "-B",
                        "-c", BROKER_IR_SOCKET_AUDIT, timeout=11)
            if "CI_REAL_NODE_BROKER_UNIX_SOCKET_DENIAL=PASS" in reply:
                break
        except Hold:
            if attempt == 34:
                raise Hold("CI_REAL_BROKER_UNIX_SOCKET_NOT_READY") from None
            time.sleep(0.25)
    else:
        raise Hold("CI_BROKER_UDS_READINESS_HOLD")
    directory_inode = reply.strip().splitlines()[0]
    actual_dir = root / "broker-runtime"
    check(directory_inode == str(actual_dir.stat().st_dev) + ":" +
          str(actual_dir.stat().st_ino),
          "CI_BROKER_NODE_MOUNT_INODE_DRIFT")
    real_gate = run("docker", "exec", "ci-uopti-broker", "python",
                    "-B", "-c", BROKER_BRIDGE_GATE_AUDIT, timeout=18)
    check("CI_REAL_BROKER_PINNED_HELPER_AND_BRIDGE_HOLD=PASS" in real_gate,
          "CI_BROKER_COMMITTED_BRIDGE_UNPROVEN")
    signed_path = fresh_unapproved_intent(root)
    real_intent = run("docker", "exec", "ci-uopti-ir", "python", "-B",
                      "-c", BROKER_REAL_SIGNED_UNAPPROVED, signed_path,
                      timeout=18)
    check("CI_CANONICAL_HMAC_INTENT_MISSING_BRIDGE_FAIL_CLOSED=PASS" in real_intent,
          "CI_VALID_INTENT_BROKER_BRIDGE_GATE_FAILED")
    response = run("docker", "exec", "ci-uopti-ir", "python", "-B",
                   "-c", BROKER_IR_SIGNED_DENIAL, timeout=16)
    check("CI_REAL_SIGNED_NODE_TO_BROKER_FAIL_CLOSED=PASS" in response,
          "CI_REAL_SIGNED_BROKER_DENIAL_UNPROVEN")
    tracked = {
        "conf": sha((root / "broker-conf/route-broker.json").read_bytes()),
        "key": sha((root / "broker-conf/route-broker.key").read_bytes()),
        "ledger": sha((root / "broker-ledger/nonce.db").read_bytes()),
        "dir_inode": directory_inode,
    }
    check(tracked == original and not list((root / "broker-conf/route-grants").iterdir())
          and not (root / "broker-ledger/approval-request.json").exists(),
          "CI_BROKER_GRANT_LEDGER_OR_INODE_DRIFT")
    print("CI_REAL_SIGNED_NODE_BROKER_UDS_DENIAL=PASS", flush=True)


def broker_restart(root: Path):
    before = json.loads(run("docker", "inspect", "ci-uopti-broker"))[0]
    old_inode = (root / "broker-runtime").stat()
    old_socket = (root / "broker-runtime/xhttp-broker.sock").stat()
    run("docker", "restart", "ci-uopti-broker", timeout=40)
    after = json.loads(run("docker", "inspect", "ci-uopti-broker"))[0]
    new_inode = (root / "broker-runtime").stat()
    check(before["Id"] == after["Id"]
          and before["State"]["StartedAt"] != after["State"]["StartedAt"]
          and after["State"]["Running"]
          and (old_inode.st_dev, old_inode.st_ino)
              == (new_inode.st_dev, new_inode.st_ino),
          "CI_BROKER_PRESERVED_DIRECTORY_RESTART_FAILED")
    # New broker must safely retire its own stale UDS pathname; it must
    # never unlink a live or unexpected socket or require restarting Node.
    for attempt in range(35):
        try:
            new_socket = (root / "broker-runtime/xhttp-broker.sock").stat()
            if stat.S_ISSOCK(new_socket.st_mode) and (
                old_socket.st_dev, old_socket.st_ino
            ) != (new_socket.st_dev, new_socket.st_ino):
                break
        except OSError:
            pass
        if attempt == 34:
            raise Hold("CI_BROKER_SOCKET_NOT_RECOVERED") from None
        time.sleep(0.25)
    print("CI_REAL_BROKER_RESTART_PRESERVED_NODE_BIND=PASS", flush=True)
    return after["Id"], after["State"]["StartedAt"]



SIGNED_OWNER_CONTROL = r"""
import json,sys,urllib.request,urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id,key=read_identity('/etc/smite-node/identity/node-identity.json')
mode=sys.argv[1]
target='/api/agent/frp/owners' if mode=='status' else '/api/agent/tunnels/apply'
def call(headers=None,wire=None):
 req=urllib.request.Request('http://127.0.0.1:8888'+target,
     data=wire,headers=headers or {},method='POST' if wire is not None else 'GET')
 try:
  with urllib.request.urlopen(req,timeout=12) as response:
   return response.status,json.load(response)
 except urllib.error.HTTPError as exc:
  return exc.code,{}
if mode=='status':
 assert call()[0]==401,'unsigned owner status accepted'
 other='smitecibackhaul02'
 assert call(sign_request(secret=key,node_id=other,
     method='GET',target=target,body=b''))[0]==401,'foreign identity accepted'
 signed=sign_request(secret=key,node_id=node_id,method='GET',
                     target=target,body=b'')
 status,body=call(signed)
 assert status==200 and isinstance(body,dict),(status,body)
 assert set(body)=={'status','owners'} and body['status']=='success',body
 assert len(body['owners'])==1 and isinstance(body['owners'][0],dict),body
 owner=body['owners'][0]
 assert set(owner)=={'tunnel_id','control_port','proxy_ports'} and \
        owner['tunnel_id']=='ci-owner' and owner['control_port']==7000,owner
 assert isinstance(owner['proxy_ports'],list),owner
 if sys.argv[2]=='active':
  assert 20182 in owner['proxy_ports'],'real owner proxy listener absent'
 else:
  assert owner['proxy_ports']==[],'unexpected owner proxy before child'
 assert call(signed)[0]==401,'owner replay accepted'
 print('CI_SIGNED_REAL_MANAGED_FRPS_OWNER_STATUS=PASS')
elif mode in ('apply','duplicate'):
 token=sys.argv[2]
 payload={'tunnel_id':'ci-owner' if mode=='apply' else 'ci-owner-duplicate',
          'core':'frp','type':'tcp','spec':{'mode':'server',
          'bind_port':7000,'token':token}}
 wire=json.dumps(payload,separators=(',',':')).encode('utf-8')
 headers=sign_request(secret=key,node_id=node_id,method='POST',
                      target=target,body=wire)
 headers['Content-Type']='application/json'
 status,body=call(headers,wire)
 if mode=='apply':
  assert status==200 and body.get('status')=='success',status
  print('CI_SIGNED_REAL_MANAGED_FRPS_OWNER_APPLY=PASS')
 else:
  assert status==500,'second FRPS owner not refused'
  print('CI_SECOND_FRPS_OWNER_REFUSED=PASS')
else:
 raise AssertionError('invalid owner CI action')
"""


OWNER_FRPS_PID_AUDIT = r"""
import json,psutil
expected=['/usr/local/bin/frps','-c','/etc/smite-node/frp/frps_ci-owner.yaml']
matches=[]
for p in psutil.process_iter(['pid','cmdline','create_time','status']):
 try:
  if p.info['cmdline']!=expected or p.info['status']==psutil.STATUS_ZOMBIE:
   continue
  method=p.net_connections if hasattr(p,'net_connections') else p.connections
  ports={(getattr(c.laddr,'ip',None),getattr(c.laddr,'port',None))
         for c in method(kind='tcp') if c.status==psutil.CONN_LISTEN}
  if ('127.0.0.1',7000) in ports:
   matches.append({'pid':p.info['pid'],'start':p.info['create_time']})
 except (psutil.Error,OSError,ValueError,KeyError):
  continue
assert len(matches)==1,'real managed FRPS owner PID/listener not unique'
print(json.dumps(matches[0],sort_keys=True))
"""


def signed_owner_action(action: str, value: str):
    check(action in ("apply", "status", "duplicate"), "CI_OWNER_ACTION_INVALID")
    # No raw HTTP body/config/credentials are exposed by CI.
    try:
        result = subprocess.run(
            ["docker", "exec", "ci-uopti-ir", "python", "-B", "-c",
             SIGNED_OWNER_CONTROL, action, value],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("CI_SIGNED_FRPS_OWNER_ACTION_UNAVAILABLE") from exc
    label = {
        "apply": "CI_SIGNED_REAL_MANAGED_FRPS_OWNER_APPLY=PASS",
        "status": "CI_SIGNED_REAL_MANAGED_FRPS_OWNER_STATUS=PASS",
        "duplicate": "CI_SECOND_FRPS_OWNER_REFUSED=PASS",
    }[action]
    check(result.returncode == 0 and label in result.stdout,
          "CI_SIGNED_REAL_MANAGED_FRPS_OWNER_UNPROVEN")
    print(label, flush=True)


def tracked_owner_process_identity():
    try:
        result = subprocess.run(
            ["docker", "exec", "ci-uopti-ir", "python", "-B", "-c",
             OWNER_FRPS_PID_AUDIT],
            capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("CI_OWNER_PID_AUDIT_UNAVAILABLE") from exc
    check(result.returncode == 0, "CI_OWNER_PID_AUDIT_FAILED")
    try:
        identity = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise Hold("CI_OWNER_PID_AUDIT_INVALID") from exc
    check(set(identity)=={"pid","start"}
          and type(identity["pid"]) is int and identity["pid"] > 1
          and type(identity["start"]) in (float,int),
          "CI_OWNER_PID_AUDIT_INVALID")
    return identity



SIGNED_BACKHAUL_SERVER = r"""
import json,socket,sys,urllib.request,urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id,secret=read_identity('/etc/smite-node/identity/node-identity.json')
action=sys.argv[1]
token=sys.argv[2]
tunnel='ci-backhaul-server-56053'
host='http://127.0.0.1:8888'
def request(target,body=None,headers=None):
 h=dict(headers or {})
 if body is not None:
  h['Content-Type']='application/json'
 req=urllib.request.Request(host+target,data=body,method='POST' if body else 'GET',headers=h)
 try:
  with urllib.request.urlopen(req,timeout=14) as r:
   return r.status,json.load(r)
 except urllib.error.HTTPError as exc:
  return exc.code,{}
def signed(target,wire=None):
 return sign_request(secret=secret,node_id=node_id,
                     method='POST' if wire else 'GET',target=target,
                     body=wire or b'')
def control_port(open_expected):
 with socket.socket() as conn:
  conn.settimeout(1)
  try:
   conn.connect(('127.0.0.1',3080))
   open_now=True
  except OSError:
   open_now=False
 assert open_now==open_expected,'Backhaul control port unexpected'
if action in ('deny','apply'):
 target='/api/agent/tunnels/apply'
 payload={'tunnel_id':tunnel,'core':'backhaul','type':'ws',
          'spec':{'uopti_standard_backhaul':True,
                  'mode':'server','transport':'ws','type':'ws',
                  'token':token,'control_port':3080,'data_port':56053,
                  'bridge_port':13080,'ports':[56053]}}
 wire=json.dumps(payload,separators=(',',':')).encode()
 assert request(target,wire)[0]==401,'unsigned Backhaul apply accepted'
 other=sign_request(secret=secret,node_id='smitecibackhaul02',
                    method='POST',target=target,body=wire)
 assert request(target,wire,other)[0]==401,'cross-node Backhaul apply accepted'
 auth=signed(target,wire)
 status,doc=request(target,wire,auth)
 assert status==(409 if action=='deny' else 200),(action,status)
 if action=='apply':
  assert doc.get('status')=='success','signed Backhaul apply not accepted'
 assert request(target,wire,auth)[0]==401,'Backhaul replay accepted'
 if action=='deny':
  control_port(False)
  print('CI_BACKHAUL_BEFORE_ENROLLMENT_409=PASS')
 else:
  control_port(True)
  print('CI_BACKHAUL_SIGNED_SERVER_STARTED_WITHOUT_RECREATE=PASS')
elif action in ('status','remove','absent'):
 if action=='remove':
  target='/api/agent/tunnels/remove'
  wire=json.dumps({'tunnel_id':tunnel},separators=(',',':')).encode()
  assert request(target,wire)[0]==401,'unsigned Backhaul remove accepted'
  auth=signed(target,wire)
  status,doc=request(target,wire,auth)
  assert status==200 and doc.get('status')=='success','signed Backhaul remove denied'
  assert request(target,wire,auth)[0]==401,'Backhaul remove replay accepted'
 target='/api/agent/tunnels/status?tunnel_id='+tunnel
 auth=signed(target)
 status,doc=request(target,headers=auth)
 assert status==200 and doc.get('status')=='success',(action,status)
 actual=doc.get('data',{})
 expected=(action=='status')
 assert actual.get('active') is expected,(action,actual)
 assert request(target,headers=auth)[0]==401,'Backhaul status replay accepted'
 control_port(expected)
 print('CI_BACKHAUL_SIGNED_'+action.upper()+'=PASS')
else:
 raise AssertionError('unexpected Backhaul CI action')
"""


def signed_backhaul_action(action: str, token: str):
    check(action in ("deny", "apply", "status", "remove", "absent"),
          "CI_BACKHAUL_ACTION_UNTRUSTED")
    try:
        result = subprocess.run(
            ["docker","exec","ci-uopti-ir","python","-B","-c",
             SIGNED_BACKHAUL_SERVER,action,token],
            capture_output=True,text=True,timeout=40,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise Hold("CI_BACKHAUL_SIGNED_API_UNAVAILABLE") from exc
    label = {
        "deny":"CI_BACKHAUL_BEFORE_ENROLLMENT_409=PASS",
        "apply":"CI_BACKHAUL_SIGNED_SERVER_STARTED_WITHOUT_RECREATE=PASS",
        "status":"CI_BACKHAUL_SIGNED_STATUS=PASS",
        "remove":"CI_BACKHAUL_SIGNED_REMOVE=PASS",
        "absent":"CI_BACKHAUL_SIGNED_ABSENT=PASS",
    }[action]
    check(result.returncode == 0 and label in result.stdout,
          "CI_BACKHAUL_SIGNED_RUNTIME_UNPROVEN")
    print(label, flush=True)


def verify_frp_registry_with_backhaul(root: Path, baseline: bytes):
    """A temporary lab Backhaul entry must never edit any existing FRP spec."""
    original = json.loads(baseline)
    current = json.loads((root/"node-data/tunnels.json").read_bytes())
    check(set(current) == set(original) | {"ci-backhaul-server-56053"},
          "CI_BACKHAUL_REGISTRY_SCOPE_DRIFT")
    check(all(current[k] == v for k,v in original.items()),
          "CI_BACKHAUL_FRP_PERSISTED_SPEC_CHANGED")
    check(current["ci-backhaul-server-56053"].get("core") == "backhaul",
          "CI_BACKHAUL_REGISTRY_ENGINE_INVALID")



SIGNED_BACKHAUL_CLIENT = r"""
import json,socket,sys,urllib.request,urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id,key=read_identity('/etc/smite-node/identity/node-identity.json')
action=sys.argv[1]
token=sys.argv[2]
tunnel='ci-backhaul-client-56053'
base='http://127.0.0.1:8888'
def call(target,wire=None,headers=None):
 h=dict(headers or {})
 if wire is not None:
  h['Content-Type']='application/json'
 method='POST' if wire is not None else 'GET'
 req=urllib.request.Request(base+target,data=wire,method=method,headers=h)
 try:
  with urllib.request.urlopen(req,timeout=16) as response:
   return response.status,json.load(response)
 except urllib.error.HTTPError as error:
  return error.code,{}
def signed(target,wire=None,identity=None):
 return sign_request(secret=key,node_id=identity or node_id,
                     method='POST' if wire is not None else 'GET',
                     target=target,body=wire or b'')
if action in ('deny','apply'):
 target='/api/agent/tunnels/apply'
 payload={'tunnel_id':tunnel,'core':'backhaul','type':'ws',
          'spec':{'uopti_standard_backhaul':True,'mode':'client',
                  'transport':'ws','type':'ws','token':token,
                  'control_port':3080,'bridge_port':13080,'data_port':56053,
                  'remote_addr':'127.0.0.1:13080','ports':[56053]}}
 wire=json.dumps(payload,separators=(',',':')).encode()
 assert call(target,wire)[0]==401,'unauthenticated client Apply accepted'
 assert call(target,wire,signed(target,wire,'smitecibackhaul01'))[0]==401,\
       'wrong-node client Apply accepted'
 auth=signed(target,wire)
 status,doc=call(target,wire,auth)
 assert status==(409 if action=='deny' else 200),(action,status)
 if action=='apply':
  assert doc.get('status')=='success','signed client Apply did not succeed'
 assert call(target,wire,auth)[0]==401,'replay of client Apply accepted'
 print('CI_BACKHAUL_SIGNED_FOREIGN_CLIENT_'+action.upper()+'=PASS')
elif action in ('status','remove','absent'):
 if action=='remove':
  target='/api/agent/tunnels/remove'
  wire=json.dumps({'tunnel_id':tunnel},separators=(',',':')).encode()
  assert call(target,wire)[0]==401,'unsigned client Remove accepted'
  auth=signed(target,wire)
  status,doc=call(target,wire,auth)
  assert status==200 and doc.get('status')=='success',(action,status)
  assert call(target,wire,auth)[0]==401,'client Remove replay accepted'
 target='/api/agent/tunnels/status?tunnel_id='+tunnel
 auth=signed(target)
 status,doc=call(target,headers=auth)
 assert status==200 and doc.get('status')=='success',(action,status)
 active=doc.get('data',{}).get('active')
 assert active is (action=='status'),(action,active)
 assert call(target,headers=auth)[0]==401,'client Status replay accepted'
 print('CI_BACKHAUL_SIGNED_FOREIGN_CLIENT_'+action.upper()+'=PASS')
else:
 raise AssertionError('invalid signed client action')
"""


def signed_backhaul_client(action: str, token: str):
    check(action in ("deny","apply","status","remove","absent"),
          "CI_BACKHAUL_CLIENT_ACTION_UNTRUSTED")
    try:
        process=subprocess.run(
            ["docker","exec","ci-uopti-foreign","python","-B","-c",
             SIGNED_BACKHAUL_CLIENT,action,token],
            capture_output=True,text=True,timeout=45,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise Hold("CI_BACKHAUL_CLIENT_SIGNED_REQUEST_UNAVAILABLE") from exc
    label="CI_BACKHAUL_SIGNED_FOREIGN_CLIENT_"+action.upper()+"=PASS"
    check(process.returncode==0 and label in process.stdout,
          "CI_BACKHAUL_CLIENT_SIGNED_RUNTIME_UNPROVEN")
    print(label,flush=True)


def verify_foreign_frp_registry_with_backhaul(root: Path, baseline: bytes):
    saved=json.loads(baseline)
    current=json.loads((root/"node-data/tunnels.json").read_bytes())
    check(set(current)==set(saved)|{"ci-backhaul-client-56053"},
          "CI_BACKHAUL_FOREIGN_REGISTRY_SCOPE_DRIFT")
    check(all(current[k]==v for k,v in saved.items()),
          "CI_BACKHAUL_FOREIGN_FRP_SPECS_CHANGED")
    check(current["ci-backhaul-client-56053"].get("core")=="backhaul",
          "CI_BACKHAUL_FOREIGN_RUNTIME_CORE_INVALID")


SIGNED_CHILD_APPLY = r"""
import json,sys,urllib.request,urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id,key=read_identity('/etc/smite-node/identity/node-identity.json')
token=sys.argv[1]
target='/api/agent/tunnels/apply'
payload={'tunnel_id':'ci-child-20182','core':'frp','type':'tcp','spec':{
 'mode':'client', 'shared_frps_owner':'ci-owner',
 'server_addr':'ci-uopti-wss.local','server_port':7000,'frp_gateway_port':443,
 'frp_tls_server_name':'ci-uopti-wss.local',
 'token':token,'type':'tcp','local_ip':'127.0.0.1',
 'local_port':39001,'remote_port':20182,
}}
wire=json.dumps(payload,separators=(',',':')).encode('utf-8')
headers=sign_request(secret=key,node_id=node_id,method='POST',
                     target=target,body=wire)
headers['Content-Type']='application/json'
request=urllib.request.Request(
 'http://127.0.0.1:8888'+target,data=wire,headers=headers,method='POST')
try:
 with urllib.request.urlopen(request,timeout=16) as resp:
  data=json.load(resp)
  assert resp.status==200 and data['status']=='success',data
except urllib.error.HTTPError as exc:
 print('CI_FOREIGN_SIGNED_APPLY_STATUS='+str(exc.code),flush=True)
 raise
except urllib.error.URLError:
 print('CI_FOREIGN_SIGNED_APPLY_STATUS=API_UNAVAILABLE',flush=True)
 raise
print('CI_FOREIGN_SIGNED_APPLY=PASS')
"""


SIGNED_CHILD_STATUS = r"""
import json,urllib.request,urllib.error
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id,key=read_identity('/etc/smite-node/identity/node-identity.json')
target='/api/agent/tunnels/status?tunnel_id=ci-child-20182'
url='http://127.0.0.1:8888'+target
def get(headers=None):
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers=headers or {}),timeout=5) as response:
   return response.status,json.load(response)
 except urllib.error.HTTPError as exc:
  return exc.code,{}
assert get()[0]==401,'unsigned child status accepted'
other='smitecibackhaul01'
assert get(sign_request(secret=key,node_id=other,method='GET',
                       target=target,body=b''))[0]==401,'foreign node identity accepted'
valid=sign_request(secret=key,node_id=node_id,method='GET',target=target,body=b'')
status,doc=get(valid)
print('CI_CHILD_SIGNED_STATUS_HTTP='+str(status))
print('CI_CHILD_SIGNED_STATUS_ACTIVE='+(
 'YES' if isinstance(doc,dict) and isinstance(doc.get('data'),dict)
 and doc['data'].get('active') is True else 'NO'))
assert status==200 and doc.get('status')=='success',(status,doc)
assert doc['data']=={'active':True,'type':'frp','process_running':True},doc
assert get(valid)[0]==401,'signed child status nonce replay accepted'
print('CI_SIGNED_REAL_MANAGED_FOREIGN_CHILD_STATUS=PASS')
"""


CHILD_FRPC_PID_AUDIT = r"""
import json,psutil
configs='/etc/smite-node/frp/frpc_ci-child-20182.yaml'
expected=['/usr/local/bin/frpc','-c',configs]
found=[]
matched_commands=0
for p in psutil.process_iter(['pid','cmdline','create_time','status']):
 try:
  if p.info['cmdline'] != expected or p.info['status']==psutil.STATUS_ZOMBIE:
   continue
  matched_commands+=1
  # A running process is NOT sufficient. psutil 5.9.6, used by the
  # pinned Smite image, exposes Process.connections(), while >=6 exposes
  # Process.net_connections(). Both inspect the actual tracked PID.
  method=(p.net_connections if hasattr(p,'net_connections')
          else p.connections)
  socks=method(kind='tcp')
  if not any(s.status==psutil.CONN_ESTABLISHED
             and getattr(s.raddr,'port',None)==443 for s in socks):
   continue
  found.append({'pid':p.info['pid'],'start':p.info['create_time']})
 except (psutil.Error,OSError,ValueError,KeyError):
  continue
print('CI_CHILD_FRPC_CMD_MATCH_COUNT='+str(matched_commands))
print('CI_CHILD_FRPC_WSS_ESTABLISHED_COUNT='+str(len(found)))
assert matched_commands==1 and len(found)==1,'REAL_FRPC_WSS_CONTROL_PID_NOT_UNIQUE'
print(json.dumps(found[0],sort_keys=True))
"""


def signed_owner_ready():
    for attempt in range(35):
        try:
            signed_probe("ci-uopti-ir", "absent")
            return
        except Hold:
            if attempt == 34:
                raise Hold("CI_IR_SIGNED_API_NOT_READY") from None
            time.sleep(0.3)


def signed_child_ready():
    # Require the actual signed Node API to be ready *before* requesting
    # a new child. A Docker Running flag alone does not prove FastAPI boot.
    for i in range(35):
        try:
            signed_probe("ci-uopti-foreign", "absent")
            return
        except Hold:
            if i == 34:
                raise Hold("CI_FOREIGN_SIGNED_API_NOT_READY") from None
            time.sleep(0.3)


def signed_child_apply(token: str):
    try:
        result = subprocess.run(
            ["docker", "exec", "ci-uopti-foreign", "python", "-B", "-c",
             SIGNED_CHILD_APPLY, token],
            capture_output=True, text=True, timeout=35, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("CI_SIGNED_FOREIGN_CHILD_APPLY_PROCESS_FAILED") from exc
    # Only fixed proof labels and the numeric HTTP status may reach CI logs.
    # Never print raw subprocess stdout/stderr: the signed body has a token.
    for line in result.stdout.splitlines():
        if line.startswith("CI_FOREIGN_SIGNED_APPLY_STATUS="):
            code = line.removeprefix("CI_FOREIGN_SIGNED_APPLY_STATUS=")
            if code == "API_UNAVAILABLE" or (code.isdecimal() and len(code) == 3):
                print("CI_FOREIGN_SIGNED_APPLY_STATUS=" + code, flush=True)
    check(result.returncode == 0
          and "CI_FOREIGN_SIGNED_APPLY=PASS" in result.stdout,
          "CI_SIGNED_FOREIGN_CHILD_APPLY_UNPROVEN")


def signed_child_probe():
    try:
        result = subprocess.run(
            ["docker", "exec", "ci-uopti-foreign", "python", "-B", "-c",
             SIGNED_CHILD_STATUS],
            capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("CI_SIGNED_FOREIGN_CHILD_STATUS_PROCESS_FAILED") from exc
    for line in result.stdout.splitlines():
        if line.startswith("CI_CHILD_SIGNED_STATUS_HTTP="):
            status = line.removeprefix("CI_CHILD_SIGNED_STATUS_HTTP=")
            if status.isdecimal() and len(status) == 3:
                print("CI_CHILD_SIGNED_STATUS_HTTP=" + status, flush=True)
        if line in ("CI_CHILD_SIGNED_STATUS_ACTIVE=YES",
                    "CI_CHILD_SIGNED_STATUS_ACTIVE=NO"):
            print(line, flush=True)
    check(result.returncode == 0
          and "CI_SIGNED_REAL_MANAGED_FOREIGN_CHILD_STATUS=PASS"
          in result.stdout,
          "CI_SIGNED_FOREIGN_CHILD_STATUS_UNPROVEN")


def tracked_child_process_identity():
    # The PID/create-time and ESTABLISHED 443 socket are from the real
    # foreign Node container; never accept just "process_running=true".
    try:
        result = subprocess.run(
            ["docker", "exec", "ci-uopti-foreign", "python", "-B", "-c",
             CHILD_FRPC_PID_AUDIT],
            capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("CI_CHILD_FRPC_PID_AUDIT_UNAVAILABLE") from exc
    for line in result.stdout.splitlines():
        for key in ("CI_CHILD_FRPC_CMD_MATCH_COUNT=",
                    "CI_CHILD_FRPC_WSS_ESTABLISHED_COUNT="):
            if line.startswith(key) and line[len(key):].isdigit():
                print(key + line[len(key):], flush=True)
    check(result.returncode == 0, "CI_CHILD_FRPC_PID_AUDIT_FAILED")
    lines = result.stdout.strip().splitlines()
    check(bool(lines), "CI_CHILD_FRPC_PID_AUDIT_EMPTY")
    try:
        doc = json.loads(lines[-1])
    except ValueError as exc:
        raise Hold("CI_CHILD_FRPC_PID_AUDIT_INVALID") from exc
    check(set(doc) == {"pid", "start"}
          and type(doc["pid"]) is int and doc["pid"] > 1
          and type(doc["start"]) in (float, int),
          "CI_SIGNED_FOREIGN_CHILD_REAL_PROCESS_INVALID")
    return doc


def docker_node(name: str, network: str, root: Path):
    child = name == "ci-uopti-foreign"
    # Both roles use the exact reviewed Smite revision with signed Owner API.
    command = [
        "docker", "run", "-d", "--name", name, "--network", network,
        "--network-alias", name,
        *([] if child else ["--network-alias", "ci-uopti-wss",
                            "--network-alias", "ci-uopti-wss.local"]),
        "--platform", "linux/amd64",
        "--read-only", "--cap-drop", "ALL", "--pids-limit", "128",
        "--memory", "384m", "--security-opt", "no-new-privileges",
        "--user", "0:0" if child else f"0:{BROKER_GID}",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16m",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "SMITE_AGENT_AUTH_MODE=strict",
        "--env", "SMITE_NODE_PANEL_AUTH_MODE=paused",
        "--env", "SMITE_ENGINE_INVENTORY_MODE=managed",
        "--env", "SMITE_FRP_STANDARD_WSS=1",
        "--env", "PANEL_ADDRESS=ci-uopti-wss.local:443",
        "--env", "SMITE_AGENT_IDENTITY_PATH=/etc/smite-node/identity/node-identity.json",
        "--env", "SMITE_AGENT_REPLAY_DB=/var/lib/smite-node/auth/agent-replay.sqlite3",
        "--env", "SMITE_ENGINE_MANIFEST_PATH=/etc/smite-node/engine-state/engines.json",
        "--env", "NODE_API_PORT=8888",
        "--env", "NODE_ROLE=foreign" if child else "NODE_ROLE=iran",
        *([] if child else [
            "--env", "SMITE_UOPTI_ROUTE_BROKER_ENABLED=true",
            "--env", "SMITE_UOPTI_ROUTE_BROKER_SOCKET=/run/u-opti/smite/xhttp-broker.sock",
            "--mount", f"type=bind,src={root}/broker-runtime,dst=/run/u-opti/smite,readonly",
        ]),
        "--mount", f"type=bind,src={root}/node/config,dst=/etc/smite-node",
        "--mount", f"type=bind,src={root}/node-data,dst=/var/lib/smite-node",
        *([
            "--mount", f"type=bind,src={root}/node/config/ci-ca.crt,dst=/etc/ssl/certs/ca-certificates.crt,readonly",
        ] if child else []),
        "--entrypoint", "python", IMAGE,
        "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
        "--port", "8888", "--no-access-log",
    ]
    run(*command, timeout=150)
    state = json.loads(run("docker", "inspect", name))
    check(len(state) == 1 and state[0]["HostConfig"]["NetworkMode"] == network
          and state[0]["HostConfig"]["ReadonlyRootfs"] is True
          and not state[0]["HostConfig"]["PortBindings"]
          and state[0]["HostConfig"]["CapDrop"] == ["ALL"]
          and state[0]["HostConfig"]["PublishAllPorts"] is False,
          "CI_NODE_DOCKER_ISOLATION_FAILED")
    mounts = state[0]["Mounts"]
    check(len([m for m in mounts if m["Destination"] == "/etc/smite-node"
               and m["Source"] == str(root / "node/config")]) == 1,
          "CI_NODE_PRIVATE_CONFIG_MOUNT_INVALID")
    return state[0]["Id"], state[0]["State"]["StartedAt"]


def enrollment(root: Path, *, role: str):
    # The newer signed foreign Child source added an independently
    # authenticated identity/Replay key-binding marker. Enroll each role
    # with exactly the code that will authenticate its later requests.
    check(role in ("ir", "foreign"), "CI_REPLAY_ROLE_INVALID")
    run("docker", "run", "--rm", "--platform", "linux/amd64",
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", "0:0",
        "--mount", f"type=bind,src={root}/node/config,dst=/etc/smite-node",
        "--mount", f"type=bind,src={root}/node-data,dst=/var/lib/smite-node",
        "--entrypoint", "python", IMAGE, "-m", "app.replay_enrollment",
        "--identity", "/etc/smite-node/identity/node-identity.json",
        "--replay-db", "/var/lib/smite-node/auth/agent-replay.sqlite3",
        "--confirm-first-provision", timeout=150)
    check((root / "node-data/auth/agent-replay.sqlite3").is_file()
          and (root / "node/config/identity/replay-enrollment.json").is_file(),
          "CI_NODE_DURABLE_REPLAY_ENROLLMENT_MISSING")


def signed_probe(name: str, phase: str):
    value = run("docker", "exec", name, "python", "-B", "-c",
                PROBE, phase, timeout=25)
    check("REAL_SIGNED_NODE_ENGINE_AND_REPLAY=PASS" in value,
          "CI_REAL_SIGNED_NODE_PROBE_FAILED")


def wait_frps_loopback():
    # FRPC loginFailExit default may terminate on an early 502 from Nginx.
    # Wait for *real* FRPS listening before launching the WSS client.
    probe = """import socket
with socket.create_connection(('127.0.0.1',7000),timeout=2):
 print('CI_FRPS_LISTENER=PASS')
"""
    for attempt in range(28):
        try:
            out = run("docker", "exec", "ci-uopti-ir",
                      "python", "-B", "-c", probe, timeout=7)
            if "CI_FRPS_LISTENER=PASS" in out:
                return
        except Hold:
            pass
        time.sleep(0.35)
    raise Hold("CI_FRPS_LISTENER_UNAVAILABLE")


TRANSPORT_AUDIT = r"""
import os,socket,ssl,sys
name=sys.argv[1]
port=int(sys.argv[2])
has_process=False
for pid in os.listdir('/proc'):
 if not pid.isdecimal():continue
 try:
  proc=open('/proc/'+pid+'/comm').read().strip()
 except (OSError,UnicodeError):continue
 if proc==name:has_process=True
try:
 with socket.create_connection(('127.0.0.1',port),timeout=2):
  socket_ok=True
except OSError:socket_ok=False
print('CI_PROCESS_'+name.upper()+'='+('PRESENT' if has_process else 'MISSING'))
print('CI_LOOPBACK_'+str(port)+'='+('OPEN' if socket_ok else 'CLOSED'))
"""


WSS_UPGRADE_AUDIT = r"""
import socket,ssl
ctx=ssl.create_default_context(cafile='/etc/smite-node/ci-ca.crt')
request=('GET /~!frp HTTP/1.1\r\n'
         'Host: ci-uopti-wss\r\n'
         'Upgrade: websocket\r\n'
         'Connection: Upgrade\r\n'
         'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
         'Sec-WebSocket-Version: 13\r\n\r\n').encode()
with socket.create_connection(('ci-uopti-wss',443),timeout=4) as raw:
 with ctx.wrap_socket(raw,server_hostname='ci-uopti-wss') as peer:
  peer.settimeout(4);peer.sendall(request)
  code=peer.recv(128).split(b'\r\n',1)[0].split()
  status=code[1].decode('ascii') if len(code)>=2 else 'UNKNOWN'
assert status in ('101','400','403','404','502','503','500'),status
print('CI_WSS_UPGRADE_HTTP='+status)
"""


def private_transport_audit():
    # Print only fixed public readiness states and HTTP status, never logs,
    # private keys, FRP tokens or raw headers.
    for node, proc, port in (("ci-uopti-ir", "frps", "7000"),
                             ("ci-uopti-foreign", "frpc", "39001")):
        try:
            out = run("docker", "exec", node, "python", "-B", "-c",
                      TRANSPORT_AUDIT, proc, port, timeout=10)
            print(out, flush=True)
        except Hold:
            print("CI_TRANSPORT_AUDIT_"+proc.upper()+"=UNAVAILABLE", flush=True)
    try:
        out = run("docker", "exec", "ci-uopti-foreign",
                  "python", "-B", "-c", WSS_UPGRADE_AUDIT, timeout=10)
        print(out, flush=True)
    except Hold:
        print("CI_WSS_UPGRADE_AUDIT=UNAVAILABLE", flush=True)



def official_retained_binary_probe(node: str):
    """Run the actual production read-only file verifier in a live CI Node.

    This CI fixture mounts the independently verified official Backhaul
    executable already when Node starts. Real hosts must prove their own
    running image has these bytes; this does NOT authorize host enrollment.
    """
    check(node in ("ci-uopti-ir", "ci-uopti-foreign"),
          "CI_BINARY_NODE_IDENTITY_UNTRUSTED")
    source = REPO / "modules/smite-managed-backhaul-host-executor.py"
    spec = importlib.util.spec_from_file_location(
        "ci_retained_node_binary_review", source)
    check(spec is not None and spec.loader is not None,
          "CI_RETAINED_BACKHAUL_REVIEW_MISSING")
    executor = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = executor
    spec.loader.exec_module(executor)
    digest = executor.package.OFFICIAL_BINARY_SHA256["amd64"]
    try:
        result = subprocess.run([
            "docker", "exec", "-i", "--env",
            "UOPTI_EXPECTED_BACKHAUL_SHA256=" + digest,
            node, "python", "-B", "-",
        ], input=executor.IN_PLACE_BINARY_PROBE,
            capture_output=True,text=True,timeout=18,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise Hold("CI_RETAINED_BACKHAUL_BINARY_READ_FAILED") from exc
    check(result.returncode == 0
          and result.stdout.strip() == "OFFICIAL_BUNDLED_BACKHAUL_BYTES=PASS",
          "CI_RETAINED_BACKHAUL_BINARY_NOT_VERIFIED")


def forward_probe(phase: str):
    for attempt in range(28):
        try:
            result = run("docker", "exec", "ci-uopti-ir", "python", "-B",
                         "-c", FORWARD, phase, timeout=12)
            check("REAL_ISOLATED_FRP_FORWARDING=PASS" in result,
                  "CI_FRP_FORWARDING_PROBE_FAILED")
            return
        except Hold:
            if attempt == 27:
                private_transport_audit()
                raise Hold("CI_ACTIVE_FRP_FORWARDING_UNAVAILABLE")
            time.sleep(0.6)


def main():
    check(os.environ.get("GITHUB_ACTIONS") == "true"
          and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
          and os.environ.get("GITHUB_REPOSITORY") == "aghajani82/u-opti"
          and os.geteuid() == 0, "PR_ROOT_CI_ONLY")
    check(len(sys.argv) == 3, "EXACT_TWO_OFFICIAL_ARCHIVES_REQUIRED")
    runner = Path(os.environ.get("RUNNER_TEMP", "/"))
    check(runner.is_absolute() and runner.is_dir(), "RUNNER_TEMP_REQUIRED")
    check(run("git", "-C", str(NODE_SOURCE), "rev-parse", "HEAD") == SMITE_SHA,
          "REVIEWED_SIGNED_NODE_SOURCE_MISMATCH")
    check(run("git", "-C", str(CHILD_SOURCE), "rev-parse", "HEAD") == CHILD_SHA,
          "REVIEWED_SIGNED_CHILD_SOURCE_MISMATCH")
    tx = load("two_live_node_tx",
              REPO / "modules/smite-managed-backhaul-transaction.py")
    pkg = load("two_live_node_pkg",
               REPO / "modules/smite-managed-backhaul.py")
    frp = official_frp(Path(sys.argv[1]))
    backhaul_bytes = pkg._verified_binary(Path(sys.argv[2]), BACKHAUL_ARCHIVE_SHA)
    check(sha(backhaul_bytes) == pkg.OFFICIAL_BINARY_SHA256["amd64"],
          "OFFICIAL_BACKHAUL_BINARY_PIN_MISMATCH")
    root_ir = Path(tempfile.mkdtemp(prefix="backhaul-live-ir-", dir=runner))
    root_foreign = Path(tempfile.mkdtemp(prefix="backhaul-live-foreign-", dir=runner))
    network = "uopti-bh-pr-" + secrets.token_hex(6)
    started = {}
    try:
        roots = (("ir", root_ir, "ci-uopti-ir"),
                 ("foreign", root_foreign, "ci-uopti-foreign"))
        token = secrets.token_hex(32)
        originals = {}
        print("CI_WSS_STAGE=PREPARE_TWO_PRIVATE_ROLES", flush=True)
        for role, root, _ in roots:
            originals[role] = initial_role(root, role, frp, backhaul_bytes,
                                          secrets.token_hex(32), token, tx)
            enrollment(root, role=role)
        broker_prepare(root_ir)
        print("CI_WSS_STAGE=START_INTERNAL_DOCKER_NETWORK", flush=True)
        run("docker", "network", "create", "--internal", "--driver",
            "bridge", network)
        print("CI_WSS_STAGE=START_SIGNED_IR_NODE", flush=True)
        # IR must exist before Nginx can resolve its internal FRPS upstream.
        # Then the foreign Node mounts the ephemeral trusted CA at startup.
        started["ci-uopti-ir"] = docker_node("ci-uopti-ir", network, root_ir)
        print("CI_WSS_STAGE=START_REAL_PRIVATE_ROOT_BROKER", flush=True)
        started["ci-uopti-broker"] = broker_start(root_ir)
        broker_baseline = {
            "conf": sha((root_ir / "broker-conf/route-broker.json").read_bytes()),
            "key": sha((root_ir / "broker-conf/route-broker.key").read_bytes()),
            "ledger": sha((root_ir / "broker-ledger/nonce.db").read_bytes()),
            "dir_inode": str((root_ir / "broker-runtime").stat().st_dev) + ":" +
                         str((root_ir / "broker-runtime").stat().st_ino),
        }
        print("CI_WSS_STAGE=START_TLS_GATEWAY", flush=True)
        started["ci-uopti-wss"] = wss_gateway(
            network, root_ir, root_foreign)
        print("CI_WSS_STAGE=START_SIGNED_FOREIGN_CHILD_NODE", flush=True)
        started["ci-uopti-foreign"] = docker_node(
            "ci-uopti-foreign", network, root_foreign)
        print("CI_WSS_STAGE=START_FOREIGN_BACKHAUL_TLS_BRIDGE", flush=True)
        started["ci-uopti-bh-bridge"] = foreign_backhaul_bridge(root_foreign)
        isolation = run("docker","exec","ci-uopti-ir","python","-B","-c",
                        BRIDGE_LOOPBACK_ONLY, timeout=10)
        check("CI_FOREIGN_BRIDGE_LOOPBACK_ONLY=PASS" in isolation,
              "CI_FOREIGN_BACKHAUL_BRIDGE_PUBLIC_EXPOSURE")
        print("CI_WSS_STAGE=PROBE_TLS_CA_HOSTNAME", flush=True)
        https_probe()
        # Genuine FRP 0.71.0 via real WSS/443 Upgrade + verified CA.
        print("CI_WSS_STAGE=START_REAL_FRP_WSS_CONTROL", flush=True)
        run("docker", "exec", "-d", "ci-uopti-foreign",
            "python", "-B", "-c", ECHO)
        run("docker", "exec", "-d", "ci-uopti-foreign",
            "python", "-B", "-c", BACKHAUL_FOREIGN_ECHO)
        # The IR Node must itself create and track its sole FRPS owner via
        # strict HMAC and durable replay, rather than docker-exec orphan FRPS.
        print("CI_WSS_STAGE=SIGNED_IR_OWNER_API_PREFLIGHT", flush=True)
        signed_owner_ready()
        broker_probe(root_ir, broker_baseline)
        print("CI_WSS_STAGE=SIGNED_IR_OWNER_APPLY", flush=True)
        signed_owner_action("apply", token)
        wait_frps_loopback()
        signed_owner_action("status", "before")
        owner_process_identity = tracked_owner_process_identity()
        saved_owner_state = (root_ir / "node-data/tunnels.json").read_bytes()
        # The actual foreign Smite Node (not a docker-exec orphan) must
        # receive the signed apply, create and track its own FRPC child.
        print("CI_WSS_STAGE=FOREIGN_SIGNED_API_PREFLIGHT", flush=True)
        signed_child_ready()
        print("CI_WSS_STAGE=SIGNED_FOREIGN_CHILD_APPLY", flush=True)
        signed_child_apply(token)
        print("CI_WSS_STAGE=SIGNED_FOREIGN_CHILD_APPLY_PASS", flush=True)
        forward_probe("initial")
        official_retained_binary_probe("ci-uopti-ir")
        official_retained_binary_probe("ci-uopti-foreign")
        print("CI_WSS_STAGE=RETAINED_NODE_OFFICIAL_BINARY_READ_PASS", flush=True)
        print("CI_WSS_STAGE=SIGNED_FOREIGN_CHILD_FORWARD_PASS", flush=True)
        signed_child_probe()
        signed_owner_action("status", "active")
        signed_owner_action("duplicate", token)
        signed_owner_action("status", "active")
        check(tracked_owner_process_identity() == owner_process_identity,
              "CI_DUPLICATE_OWNER_REPLACED_FRPS")
        print("CI_WSS_STAGE=SIGNED_FOREIGN_CHILD_STATUS_PASS", flush=True)
        saved_child_state = (root_foreign / "node-data/tunnels.json").read_bytes()
        child_process_identity = tracked_child_process_identity()
        print("CI_WSS_STAGE=SIGNED_FOREIGN_CHILD_PID_PASS", flush=True)
        print("CI_WSS_STAGE=RUN_PAIRED_MANIFEST_RECEIPT_TEST", flush=True)
        seen = []
        rehearse_broker_restart = False
        broker_restarted = False
        backhaul_active = False
        backhaul_client_active = False
        backhaul_token = secrets.token_hex(24)

        def observe(phase, ir, foreign):
            nonlocal broker_restarted, backhaul_active, backhaul_client_active
            if phase == "after-ir" and rehearse_broker_restart and not broker_restarted:
                started["ci-uopti-broker"] = broker_restart(root_ir)
                broker_restarted = True
            check(ir == root_ir and foreign == root_foreign,
                  "CI_TWO_HOST_ROLE_PATH_DRIFT")
            ir_state = "ready" if phase in ("after-ir", "after-both") else "absent"
            foreign_state = "ready" if phase == "after-both" else "absent"
            signed_probe("ci-uopti-ir", ir_state)
            signed_probe("ci-uopti-foreign", foreign_state)
            if phase == "before":
                signed_backhaul_action("deny", backhaul_token)
                signed_backhaul_client("deny", backhaul_token)
            elif phase == "after-ir":
                signed_backhaul_action("apply", backhaul_token)
                backhaul_active = True
                signed_backhaul_action("status", backhaul_token)
                signed_backhaul_client("absent", backhaul_token)
            elif phase == "after-both":
                check(backhaul_active, "CI_BACKHAUL_RUNTIME_MISSING_AT_BOTH")
                signed_backhaul_action("status", backhaul_token)
                signed_backhaul_client("apply", backhaul_token)
                backhaul_client_active = True
                signed_backhaul_client("status", backhaul_token)
                backhaul_data_probe("active")
            elif phase == "after-rollback":
                if backhaul_client_active:
                    signed_backhaul_client("remove", backhaul_token)
                    backhaul_client_active = False
                if backhaul_active:
                    signed_backhaul_action("remove", backhaul_token)
                    backhaul_active = False
                signed_backhaul_client("absent", backhaul_token)
                signed_backhaul_action("absent", backhaul_token)
                backhaul_data_probe("absent")
            signed_child_probe()
            official_retained_binary_probe("ci-uopti-ir")
            official_retained_binary_probe("ci-uopti-foreign")
            broker_probe(root_ir, broker_baseline)
            signed_owner_action("status", "active")
            check(tracked_owner_process_identity() == owner_process_identity,
                  "CI_IR_OWNER_FRPS_RESTARTED_OR_REPLACED")
            if backhaul_active:
                verify_frp_registry_with_backhaul(root_ir, saved_owner_state)
            else:
                check((root_ir / "node-data/tunnels.json").read_bytes() == saved_owner_state,
                      "CI_IR_OWNER_SAVED_TUNNEL_DRIFT")
            check(tracked_child_process_identity() == child_process_identity,
                  "CI_FOREIGN_CHILD_FRPC_RESTARTED_OR_REPLACED")
            if backhaul_client_active:
                verify_foreign_frp_registry_with_backhaul(
                    root_foreign, saved_child_state)
            else:
                check((root_foreign / "node-data/tunnels.json").read_bytes() ==
                      saved_child_state, "CI_FOREIGN_CHILD_SAVED_TUNNEL_DRIFT")
            forward_probe(phase)
            https_probe()
            for name in DOCKER_NAMES:
                doc = json.loads(run("docker", "inspect", name))[0]
                check((doc["Id"], doc["State"]["StartedAt"]) == started[name]
                      and doc["State"]["Running"] is True,
                      "CI_NODE_RECREATED_OR_RESTARTED")
            if phase == "after-both":
                # No Backhaul runtime may survive the paired receipt rollback.
                # Remove ONLY each engine's ephemeral signed CI tunnel.
                signed_backhaul_client("remove", backhaul_token)
                backhaul_client_active = False
                signed_backhaul_client("absent", backhaul_token)
                check((root_foreign / "node-data/tunnels.json").read_bytes() ==
                      saved_child_state,
                      "CI_SIGNED_BACKHAUL_CLIENT_REMOVE_FRP_REGISTRY_DRIFT")
                signed_backhaul_action("remove", backhaul_token)
                backhaul_active = False
                signed_backhaul_action("absent", backhaul_token)
                backhaul_data_probe("absent")
                check((root_ir / "node-data/tunnels.json").read_bytes() ==
                      saved_owner_state, "CI_SIGNED_BACKHAUL_REMOVE_FRP_REGISTRY_DRIFT")
            seen.append(phase)
            return True

        # Exercise the host executor on the signed image, without application
        # overlays. Snapshot stable identity, never private credentials in logs.
        executor = load("ci_host_retained_executor",
                        REPO / "modules/smite-managed-backhaul-host-executor.py")

        def host_step(role, root, name, action):
            paths = executor.Paths(node=root / "node", state=root / "host-state",
                                   frp_state=root / "rc7-frp-enrollment",
                                   lock=root / ".smite-engine-transaction.lock")

            def witness():
                doc = json.loads(run("docker", "inspect", name))[0]
                check(doc["Config"]["Image"] == IMAGE and doc["State"]["Running"]
                      and (doc["Id"], doc["State"]["StartedAt"]) == started[name],
                      "CI_RETAINED_SIGNED_NODE_REPLACED")
                signed_child_probe()
                signed_owner_action("status", "active")
                identity = root / "node/config/identity"
                immutable = [sha(path.read_bytes()) for path in (
                    identity / "node-identity.json", identity / "replay-enrollment.json",
                    root / "node/docker-compose.yml", root / "node/.env")]
                values = [immutable, doc["Id"], doc["State"]["StartedAt"],
                          tracked_owner_process_identity(), tracked_child_process_identity(),
                          sha((root / "node-data/tunnels.json").read_bytes())]
                for path in (root / "node-data/auth/agent-replay.sqlite3",
                             root_ir / "broker-runtime/xhttp-broker.sock"):
                    info = path.stat()
                    values.extend((info.st_dev, info.st_ino))
                return sha(json.dumps(values, sort_keys=True).encode())

            official_retained_binary_probe(name)
            return executor._retained_step(paths, action=action, role=role,
                                           arch="amd64", witness=witness)

        for _, root, _ in roots:
            directory(root / "host-state")
        observe("before", root_ir, root_foreign)
        for role, root, name in roots:
            check(host_step(role, root, name, "install") == "COMMITTED",
                  "CI_RETAINED_COMMIT_MISSING")
            observe("after-ir" if role == "ir" else "after-both", root_ir, root_foreign)
        for role, root, name in reversed(roots):
            check(host_step(role, root, name, "rollback") == "RESTORED",
                  "CI_RETAINED_ROLLBACK_MISSING")
        observe("after-rollback", root_ir, root_foreign)
        seen.clear()
        print("RC7_RETAINED_HOST_TRANSACTION_REAL_DATA_AND_ROLLBACK=PASS", flush=True)

        # A successful complete dual-host file transition is *always* undone.
        rehearse_broker_restart = True
        report = tx.rc7_two_host_rehearsal_lab(
            root_ir, root_foreign, sha(backhaul_bytes), observe=observe)
        check(seen == ["before", "after-ir", "after-both", "after-rollback"]
              and report["INSTALL_ALLOWED"] == "NO"
              and report["ACTIVATION_GATE"] == "HOLD"
              and report["SIGNED_OWNER_CHILD_CONTINUITY"] == "NOT_PROVEN",
              "CI_TWO_HOST_FALSE_PRODUCTION_AUTHORIZATION")
        # A crash in the second host's manifest write MUST restore both,
        # while the same running FRP forwarding and two Node APIs persist.
        seen.clear()
        try:
            tx.rc7_two_host_rehearsal_lab(
                root_ir, root_foreign, sha(backhaul_bytes),
                observe=observe, inject="foreign-after-manifest")
        except tx.Hold as exc:
            check(str(exc) == "RC7_TWO_HOST_ABORTED_EXACT_ROLLBACK_PROVED",
                  "CI_TWO_HOST_UNEXPECTED_RECOVERY_HOLD")
        else:
            raise Hold("CI_TWO_HOST_FOREIGN_CRASH_NOT_DETECTED")
        check(seen == ["before", "after-ir", "after-rollback"],
              "CI_TWO_HOST_CRASH_PROBE_PHASES_INVALID")
        for role, root, _ in roots:
            manifest, receipt = originals[role]
            check((root / "node/config/engine-state/engines.json").read_bytes() == manifest
                  and (root / "rc7-frp-enrollment/record.json").read_bytes() == receipt
                  and not (root / tx.PAIR_JOURNAL).exists()
                  and not (root / tx.PAIR_CLEANUP_SEAL).exists(),
                  "CI_TWO_HOST_EXACT_FRP_RECEIPT_ROLLBACK_FAILED")
        check(broker_restarted, "CI_BROKER_LIFECYCLE_NOT_EXERCISED")
        print("RC7_BROKER_ROOT_PINNED_HELPERS_AND_COMMITTED_BRIDGE_GATE=PASS")
        print("RC7_CANONICAL_HMAC_INTENT_REJECTED_WITHOUT_BRIDGE=PASS")
        print("RC7_REAL_ROOT_BROKER_UDS_SIGNED_DENIAL=PASS")
        print("RC7_REAL_BROKER_RESTART_NO_NODE_RECREATE=PASS")
        print("RC7_BROKER_ROUTE_PUBLISH=NOT_PROVEN")
        check(not backhaul_active and not backhaul_client_active,
              "CI_BACKHAUL_LEFT_RUNNING_AFTER_RECOVERY")
        print("RC7_SIGNED_BACKHAUL_FOREIGN_CLIENT_TLS_443_WS_DATA_ROUNDTRIP=PASS")
        print("RC7_SIGNED_BACKHAUL_FOREIGN_CLIENT_EXACT_ROLLBACK=PASS")
        print("RC7_SIGNED_BACKHAUL_SERVER_WITH_LIVE_FRP_OWNER_CHILD=PASS")
        print("RC7_SIGNED_BACKHAUL_REMOVE_AND_FRP_REGISTRY_EXACT_RESTORE=PASS")
        print("RC7_BACKHAUL_CROSS_HOST_DATA_TUNNEL=PASS_ISOLATED_REAL_WS_TLS_443")
        print("RC7_BACKHAUL_PUBLIC_HOST_DEPLOYMENT=NOT_PROVEN")
        print("RC7_RETAINED_FRP_NODE_OFFICIAL_BACKHAUL_BYTES_WITHOUT_RECREATE=PASS")
        print("RC7_LIVE_HOST_IN_PLACE_TRANSACTION=NOT_IMPLEMENTED")
        print("RC7_SIGNED_MANAGED_IR_OWNER_AND_FOREIGN_CHILD=PASS")
        print("RC7_TRACKED_IR_FRPS_OWNER_SAVED_TUNNEL_AND_PID_STABLE=PASS")
        print("RC7_SECOND_OWNER_FAIL_CLOSED=PASS")
        print("RC7_SIGNED_FOREIGN_CHILD_APPLY_AND_STATUS=PASS")
        print("RC7_TRACKED_FOREIGN_FRPC_SAVED_TUNNEL_AND_PID_STABLE=PASS")
        print("RC7_REAL_TWO_NODE_SIGNED_INVENTORY_AND_REPLAY=PASS")
        print("RC7_REAL_FRP_0_71_0_WSS_443_TLS_FORWARDING_ALL_PHASES=PASS")
        print("RC7_REAL_NGINX_CA_HOSTNAME_VALIDATION=PASS")
        print("RC7_WSS_443_SHARED_HOST_EDGE=NOT_PROVEN")
        print("RC7_REAL_TWO_NODE_NO_RECREATE=PASS")
        print("RC7_REAL_TWO_NODE_DUAL_RECEIPT_ROLLBACK=PASS")
        print("RC7_REAL_SIGNED_OWNER_AND_CHILD_CONTINUITY=PASS")
        print("RC7_BROKER_UDS_DENIAL_AND_INODE_CONTINUITY=PASS")
        print("RC7_BROKER_XHTTP_ROUTE_PUBLISH=NOT_PROVEN")
        print("INSTALL_ALLOWED=NO")
        print("ACTIVATION_GATE=HOLD")
    finally:
        for name in DOCKER_NAMES:
            subprocess.run(["docker", "rm", "-f", name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False, timeout=35)
        subprocess.run(["docker", "network", "rm", network],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False, timeout=35)
        shutil.rmtree(root_ir)
        shutil.rmtree(root_foreign)


if __name__ == "__main__":
    try:
        main()
    except (Hold, OSError, AssertionError, ValueError, KeyError) as exc:
        # Only fixed codes: never raw subprocess output or synthetic secrets.
        reason = str(exc) if isinstance(exc, Hold) else "ISOLATED_UNEXPECTED_TEST_ERROR"
        if re.fullmatch(r"[A-Z0-9_]{1,100}", reason) is None:
            reason = "ISOLATED_UNEXPECTED_TEST_ERROR"
        print("HOLD: " + reason, file=sys.stderr)
        print("HOLD: REAL_TWO_NODE_SIGNED_FRP_CI_NOT_PROVEN", file=sys.stderr)
        raise SystemExit(2) from None
