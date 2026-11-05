#!/usr/bin/env python3
"""PR-only real signed Nodes + FRP WSS/443 forwarding, NO recreation.

Two ordinary Docker containers on a private --internal bridge, never on real
IR/Grandoptical. This tests the existing RC7 *filesystem* two-receipt lab
while genuine signed Smite API and FRP 0.71.0 WSS-over-TLS forwarding persist.
A disposable Nginx runs in a third isolated container: NO host port publish,
no production Nginx/443 access, no Broker or signed Owner/Child claim.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
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
SMITE_SHA = "02d05056d3a4baf577c9d3781d62af61c000f1ac"
IMAGE = ("ghcr.io/zzedix/smite-node@sha256:"
         "967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e")
FRP_ARCHIVE_SHA = "84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716"
BACKHAUL_ARCHIVE_SHA = "57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc"
MARKER = "U-OPTI-BACKHAUL-ISOLATED-LAB-V1\n"
DOCKER_NAMES = ("ci-uopti-ir", "ci-uopti-foreign", "ci-uopti-wss")


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
        raise Hold("ISOLATED_PROCESS_FAILED")
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
    if role == "ir":
        config = ("bindAddr = \"0.0.0.0\"\nbindPort = 7000\n"
                  "auth.method = \"token\"\nauth.token = " + json.dumps(token) + "\n")
        write(root / "node/config/frps.toml", config.encode())
    else:
        config = ("serverAddr = \"ci-uopti-wss\"\nserverPort = 443\n"
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
import ssl,sys,urllib.error,urllib.request
ca='/etc/smite-node/ci-ca.crt'
ctx=ssl.create_default_context(cafile=ca)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                  urllib.request.HTTPSHandler(context=ctx))
with opener.open('https://ci-uopti-wss:443/ci-health',timeout=5) as response:
 assert response.status==200 and response.read()==b'ci-wss-gateway-ok\n'
# Same TLS server, invalid hostname: cert checking must refuse it.
try:
 opener.open('https://ci-uopti-ir:443/ci-health',timeout=3)
except (ssl.SSLError,urllib.error.URLError,ConnectionError,OSError):
 pass
else:
 raise AssertionError('invalid WSS hostname unexpectedly accepted')
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
        "-addext", "subjectAltName=DNS:ci-uopti-wss",
        "-keyout", str(key), "-out", str(cert), timeout=40)
    cert.chmod(0o600)
    key.chmod(0o600)
    write(root_foreign / "node/config/ci-ca.crt", cert.read_bytes())
    conf = tls / "nginx.conf"
    write(conf, b"""pid /tmp/ci-nginx.pid;
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
    location = /ci-health { return 200 "ci-wss-gateway-ok\\n"; }
    location = /~!frp {
      proxy_pass http://ci-uopti-ir:7000;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
      proxy_buffering off;
    }
  }
}
""")
    image = "uopti-ci-wss-issue102"
    run("docker", "build", "-t", image,
        str(REPO / "tests/lab/frp-control-stall"), timeout=280)
    run("docker", "run", "-d", "--name", "ci-uopti-wss",
        "--network", network, "--network-alias", "ci-uopti-wss",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--sysctl", "net.ipv4.ip_unprivileged_port_start=0",
        "--pids-limit", "96", "--memory", "192m",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m",
        "--mount", f"type=bind,src={conf},dst=/ci/nginx.conf,readonly",
        "--mount", f"type=bind,src={cert},dst=/ci/cert.pem,readonly",
        "--mount", f"type=bind,src={key},dst=/ci/key.pem,readonly",
        "--entrypoint", "nginx", image, "-c", "/ci/nginx.conf",
        "-g", "daemon off;", timeout=150)
    doc = json.loads(run("docker", "inspect", "ci-uopti-wss"))[0]
    check(doc["HostConfig"]["NetworkMode"] == network
          and doc["HostConfig"]["ReadonlyRootfs"] is True
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


def docker_node(name: str, network: str, root: Path):
    command = [
        "docker", "run", "-d", "--name", name, "--network", network,
        "--network-alias", name, "--platform", "linux/amd64",
        "--read-only", "--cap-drop", "ALL", "--pids-limit", "128",
        "--memory", "384m", "--security-opt", "no-new-privileges",
        "--user", "0:0", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16m",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "SMITE_AGENT_AUTH_MODE=strict",
        "--env", "SMITE_NODE_PANEL_AUTH_MODE=paused",
        "--env", "SMITE_ENGINE_INVENTORY_MODE=managed",
        "--env", "SMITE_AGENT_IDENTITY_PATH=/etc/smite-node/identity/node-identity.json",
        "--env", "SMITE_AGENT_REPLAY_DB=/var/lib/smite-node/auth/agent-replay.sqlite3",
        "--env", "SMITE_ENGINE_MANIFEST_PATH=/etc/smite-node/engine-state/engines.json",
        "--env", "NODE_API_PORT=8888",
        "--mount", f"type=bind,src={NODE_SOURCE}/node/app,dst=/app/app,readonly",
        "--mount", f"type=bind,src={NODE_SOURCE}/node/main.py,dst=/app/main.py,readonly",
        "--mount", f"type=bind,src={root}/node/config,dst=/etc/smite-node",
        "--mount", f"type=bind,src={root}/node-data,dst=/var/lib/smite-node",
        "--mount", f"type=bind,src={root}/engines/frpc,dst=/usr/local/bin/frpc,readonly",
        "--mount", f"type=bind,src={root}/engines/frps,dst=/usr/local/bin/frps,readonly",
        "--mount", f"type=bind,src={root}/engines/backhaul,dst=/usr/local/bin/backhaul,readonly",
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


def enrollment(root: Path):
    run("docker", "run", "--rm", "--platform", "linux/amd64",
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", "0:0",
        "--mount", f"type=bind,src={NODE_SOURCE}/node/app,dst=/app/app,readonly",
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
        for role, root, _ in roots:
            originals[role] = initial_role(root, role, frp, backhaul_bytes,
                                          secrets.token_hex(32), token, tx)
            enrollment(root)
        run("docker", "network", "create", "--internal", "--driver",
            "bridge", network)
        # Build and run the Nginx TLS sidecar with the same Docker
        # internal-only network. Nodes and WSS gateway are never restarted
        # during any RC7 transaction or rollback.
        started["ci-uopti-wss"] = wss_gateway(
            network, root_ir, root_foreign)
        for role, root, name in roots:
            started[name] = docker_node(name, network, root)
        https_probe()
        # Genuine FRP 0.71.0 via real WSS/443 Upgrade + verified CA.
        run("docker", "exec", "-d", "ci-uopti-foreign",
            "python", "-B", "-c", ECHO)
        run("docker", "exec", "-d", "ci-uopti-ir",
            "/usr/local/bin/frps", "-c", "/etc/smite-node/frps.toml")
        run("docker", "exec", "-d", "ci-uopti-foreign",
            "/usr/local/bin/frpc", "-c", "/etc/smite-node/frpc.toml")
        forward_probe("initial")
        seen = []

        def observe(phase, ir, foreign):
            check(ir == root_ir and foreign == root_foreign,
                  "CI_TWO_HOST_ROLE_PATH_DRIFT")
            ir_state = "ready" if phase in ("after-ir", "after-both") else "absent"
            foreign_state = "ready" if phase == "after-both" else "absent"
            signed_probe("ci-uopti-ir", ir_state)
            signed_probe("ci-uopti-foreign", foreign_state)
            forward_probe(phase)
            https_probe()
            for name in DOCKER_NAMES:
                doc = json.loads(run("docker", "inspect", name))[0]
                check((doc["Id"], doc["State"]["StartedAt"]) == started[name]
                      and doc["State"]["Running"] is True,
                      "CI_NODE_RECREATED_OR_RESTARTED")
            seen.append(phase)
            return True

        # A successful complete dual-host file transition is *always* undone.
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
        print("RC7_REAL_TWO_NODE_SIGNED_INVENTORY_AND_REPLAY=PASS")
        print("RC7_REAL_FRP_0_71_0_WSS_443_TLS_FORWARDING_ALL_PHASES=PASS")
        print("RC7_REAL_NGINX_CA_HOSTNAME_VALIDATION=PASS")
        print("RC7_WSS_443_SHARED_HOST_EDGE=NOT_PROVEN")
        print("RC7_REAL_TWO_NODE_NO_RECREATE=PASS")
        print("RC7_REAL_TWO_NODE_DUAL_RECEIPT_ROLLBACK=PASS")
        print("RC7_BROKER_AND_SIGNED_OWNER_CHILD_CONTINUITY=NOT_PROVEN")
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
        # Only fixed public status, never synthetic secret or archive content.
        print("HOLD: REAL_TWO_NODE_SIGNED_FRP_CI_NOT_PROVEN", file=sys.stderr)
        raise SystemExit(2) from None
