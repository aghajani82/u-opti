#!/usr/bin/env bash
# CI ONLY: authentic WS over two isolated Nginx proxies and verified TLS.
# Never connect to, change or publish ports on production IR/KH.
set -euo pipefail
[[ "$GITHUB_ACTIONS" == true && "$RUNNER_ENVIRONMENT" == github-hosted &&
   "$GITHUB_EVENT_NAME" == pull_request &&
   "$GITHUB_REPOSITORY" == aghajani82/u-opti ]] || {
    echo "REFUSED: GitHub-hosted PR job only" >&2; exit 2;
}
cd "$(dirname "$0")/.."
umask 077
tag="$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
network="uopti-tls-$tag"
ir_bh="uopti-tls-ibh-$tag"
kh_bh="uopti-tls-kbh-$tag"
ir_ng="uopti-tls-ing-$tag"
kh_ng="uopti-tls-kng-$tag"
bad_ng="uopti-tls-bng-$tag"
image="ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
tmp="$(mktemp -d)"
created=""
network_created=no
ir_stage=""
kh_stage=""
cleanup() {
    status="$?"
    set +e
    if (( status != 0 )); then
        echo "TLS smoke failed. Isolated container statuses and redacted errors:"
        for name in "$ir_bh" "$kh_bh" "$ir_ng" "$kh_ng" "$bad_ng"; do
            if docker inspect "$name" >/dev/null 2>&1; then
                docker inspect -f '{{.Name}} {{.State.Status}} exit={{.State.ExitCode}}' "$name"
                docker logs "$name" 2>&1 | grep -Ei 'fail|error|fatal|cert|permission' |
                    sed -E 's/Bearer [^[:space:]]+/Bearer [redacted]/g;s/[0-9a-fA-F]{32,}/[redacted]/g' |
                    tail -n 10 || true
            fi
        done
    fi
    for name in $created; do docker rm -f "$name" >/dev/null 2>&1; done
    [[ "$network_created" != yes ]] || docker network rm "$network" >/dev/null 2>&1
    [[ -z "$ir_stage" ]] || rm -rf -- "$ir_stage"
    [[ -z "$kh_stage" ]] || rm -rf -- "$kh_stage"
    rm -rf -- "$tmp"
}
trap cleanup EXIT

openssl rand -hex 32 > "$tmp/token"
for role in ir kh; do
    output="$(python3 modules/smite-backhaul-sidecar.py --role "$role" --token-file "$tmp/token")"
    stage="$(printf '%s\n' "$output" | sed -n "s/^PREPARED PRIVATE OFFLINE CANDIDATE: \(.*\) ($role)$/\1/p")"
    [[ "$stage" == /tmp/uopti-backhaul-sidecar-* && -d "$stage" ]]
    if [[ "$role" == ir ]]; then ir_stage="$stage"; else kh_stage="$stage"; fi
done
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -sha256 \
    -keyout "$tmp/ca.key" -out "$tmp/ca.pem" -subj '/CN=UOPTI Synthetic Root' >/dev/null 2>&1
openssl req -new -newkey rsa:2048 -nodes \
    -keyout "$tmp/ir.key" -out "$tmp/ir.csr" -subj '/CN=ir.kolbe1.ir' >/dev/null 2>&1
printf '%s\n' 'subjectAltName=DNS:ir.kolbe1.ir' 'extendedKeyUsage=serverAuth' > "$tmp/ext"
openssl x509 -req -in "$tmp/ir.csr" -CA "$tmp/ca.pem" -CAkey "$tmp/ca.key" \
    -CAcreateserial -out "$tmp/ir.crt" -days 1 -extfile "$tmp/ext" >/dev/null 2>&1
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -keyout "$tmp/bad-ca.key" -out "$tmp/bad-ca.pem" \
    -subj '/CN=Unrelated Synthetic Root' >/dev/null 2>&1
openssl verify -CAfile "$tmp/ca.pem" -verify_hostname ir.kolbe1.ir "$tmp/ir.crt" |
    grep -Fq ': OK'

python3 - "$ir_stage" "$kh_stage" "$tmp" "$ir_bh" "$kh_ng" <<'PY'
from pathlib import Path
import sys
ir,kh,dst=map(Path,sys.argv[1:4])
server,bridge=sys.argv[4:6]
s=(ir/"ir.toml").read_text()
c=(kh/"kh.toml").read_text()
il=(ir/"ir-control.inc").read_text()
ix=(ir/"ir-xhttp.inc").read_text()
kl=(kh/"kh-bridge.conf").read_text()
assert s.count('skip_optz = true')==1 and c.count('skip_optz = true')==1
assert s.count('bind_addr = "127.0.0.1:3080"')==1
assert c.count('remote_addr = "127.0.0.1:13080"')==1
assert il.count('proxy_pass http://127.0.0.1:3080;')==2
assert il.count('location ^~ /tunnel/ {')==1
assert ix.count('location ^~ /56053/www/ {')==1
assert ix.count('proxy_set_header Host kh.kolbe1.ir;')==2
assert kl.count('proxy_ssl_verify on;')==2
assert kl.count('proxy_ssl_server_name on;')==2
assert kl.count('location ^~ /tunnel/ {')==1
s=s.replace('bind_addr = "127.0.0.1:3080"','bind_addr = "0.0.0.0:3080"')
s=s.replace('127.0.0.1:56053=127.0.0.1:56053',
            '0.0.0.0:56053=127.0.0.1:56053')
c=c.replace('remote_addr = "127.0.0.1:13080"',
            f'remote_addr = "{bridge}:13080"')
il=il.replace('proxy_pass http://127.0.0.1:3080;',
              f'proxy_pass http://{server}:3080;')
ix=ix.replace('http://127.0.0.1:56053',
              f'http://{server}:56053')
kl=kl.replace('listen 127.0.0.1:13080;','listen 0.0.0.0:13080;')
kl=kl.replace('/etc/ssl/certs/ca-certificates.crt','/run/kh-lab/ca.pem')
(dst/"ir.toml").write_text(s)
(dst/"kh.toml").write_text(c)
(dst/"ir-control.inc").write_text(il)
(dst/"ir-xhttp.inc").write_text(ix)
(dst/"kh-bridge.conf").write_text(kl)
(dst/"bad-bridge.conf").write_text(kl.replace('ca.pem','bad-ca.pem'))
(dst/"ir-nginx.conf").write_text("""events { worker_connections 256; }
http {
 server {
  listen 443 ssl;
  server_name ir.kolbe1.ir;
  ssl_certificate /etc/nginx/conf.d/ir.crt;
  ssl_certificate_key /etc/nginx/conf.d/ir.key;
  include /etc/nginx/conf.d/ir-control.inc;
  include /etc/nginx/conf.d/ir-xhttp.inc;
  location / { return 404; }
 }
}
""")
(dst/"kh-nginx.conf").write_text("""events { worker_connections 256; }
http {
 server {
  listen 13081;
  location = /legacy { return 200 'kh-legacy-preserved'; }
 }
 include /run/kh-lab/bridge.conf;
}
""")
# Per-Nginx separate directories, so replacement happens atomically and does
# not mutate a mounted file inode.
import os
for label, content in (('kh-good', kl), ('kh-bad', kl.replace('ca.pem','bad-ca.pem'))):
 directory=dst/label
 directory.mkdir(mode=0o700)
 (directory/'bridge.candidate.conf').write_text(content)
 (directory/'bridge.conf').write_text(
     '# REVIEWED SYNTHETIC KH BRIDGE NOT ACTIVE\n' if label=='kh-good'
     else content
 )
 if label=='kh-good':
  (directory/'ca.pem').write_bytes((dst/'ca.pem').read_bytes())
 else:
  (directory/'bad-ca.pem').write_bytes((dst/'bad-ca.pem').read_bytes())
(dst/"echo.py").write_text("""
from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path not in ('/health','/56053/www/'):
   self.send_error(404); return
  if self.path=='/56053/www/' and self.headers.get('Host')!='kh.kolbe1.ir':
   self.send_error(421); return
  body=(b'uopti-tls-nginx-backhaul-ok' if self.path=='/health'
        else b'uopti-ir-xhttp-backhaul-ok')
  self.send_response(200)
  self.send_header('Content-Length',str(len(body)))
  self.end_headers()
  self.wfile.write(body)
 def log_message(self,*args): pass
HTTPServer(('127.0.0.1',56053),Handler).serve_forever()
""")
PY
chmod 0600 "$tmp/"*
docker pull --platform linux/amd64 "$image" >/dev/null
docker pull nginx:stable-alpine >/dev/null
docker network create --internal "$network" >/dev/null
network_created=yes

docker run -d --name "$ir_bh" --network "$network" --read-only \
    --platform linux/amd64 --cap-drop ALL \
    --user "$(id -u):$(id -g)" --security-opt no-new-privileges \
    --mount "type=bind,src=$tmp/ir.toml,dst=/tmp/config.toml,readonly" \
    --mount "type=bind,src=$tmp/ca.pem,dst=/tmp/test-root-ca.pem,readonly" \
    --entrypoint /usr/local/bin/backhaul "$image" -c /tmp/config.toml >/dev/null
created="$ir_bh $created"

docker run -d --name "$ir_ng" --network "$network" --network-alias ir.kolbe1.ir \
    --mount "type=bind,src=$tmp/ir-nginx.conf,dst=/etc/nginx/nginx.conf,readonly" \
    --mount "type=bind,src=$tmp/ir-control.inc,dst=/etc/nginx/conf.d/ir-control.inc,readonly" \
    --mount "type=bind,src=$tmp/ir-xhttp.inc,dst=/etc/nginx/conf.d/ir-xhttp.inc,readonly" \
    --mount "type=bind,src=$tmp/ir.crt,dst=/etc/nginx/conf.d/ir.crt,readonly" \
    --mount "type=bind,src=$tmp/ir.key,dst=/etc/nginx/conf.d/ir.key,readonly" \
    nginx:stable-alpine >/dev/null
created="$ir_ng $created"

for name in "$kh_ng" "$bad_ng"; do
    if [[ "$name" == "$kh_ng" ]]; then
        bundle="ca.pem"
        snippet="kh-good"
    else
        bundle="bad-ca.pem"
        snippet="kh-bad"
    fi
    docker run -d --name "$name" --network "$network" \
        --mount "type=bind,src=$tmp/kh-nginx.conf,dst=/etc/nginx/nginx.conf,readonly" \
        --mount "type=bind,src=$tmp/$snippet,dst=/run/kh-lab" \
        nginx:stable-alpine >/dev/null
    created="$name $created"
done
for name in "$ir_ng" "$kh_ng" "$bad_ng"; do docker exec "$name" nginx -t >/dev/null 2>&1; done

# KH bridge is initially absent, but the separate synthetic legacy endpoint
# remains healthy. Enable only the owned KH bridge via atomic config swap.
docker exec -i "$ir_bh" python3 - "$kh_ng" <<'PY'
from urllib.request import urlopen
from urllib.error import URLError
import sys
with urlopen('http://'+sys.argv[1]+':13081/legacy',timeout=2) as r:
 assert r.status==200 and r.read()==b'kh-legacy-preserved'
try:
 urlopen('http://'+sys.argv[1]+':13080/channel',timeout=2)
except (URLError, OSError):
 pass
else:
 raise SystemExit('FAIL: KH bridge unexpectedly active in synthetic baseline')
print('PASS: KH legacy endpoint up; optional bridge absent before activation')
PY
python3 - "$tmp/kh-good" <<'PY'
from pathlib import Path
import os,sys,tempfile
d=Path(sys.argv[1])
payload=(d/'bridge.candidate.conf').read_bytes()
fd,p=tempfile.mkstemp(prefix='.uopti-kh-',dir=d)
with os.fdopen(fd,'wb') as f:
 f.write(payload);f.flush();os.fsync(f.fileno())
os.replace(p,d/'bridge.conf')
PY
docker exec "$kh_ng" nginx -t >/dev/null 2>&1
docker exec "$kh_ng" nginx -s reload >/dev/null 2>&1

# No Authorization header: good TLS reaches Backhaul and yields 401.
# Wrong CA: verification fails at KH Nginx and yields 502.
docker exec -i "$ir_bh" python3 - "$kh_ng" "$bad_ng" <<'PY'
from urllib.request import urlopen
from urllib.error import HTTPError
import sys,time
for label,host,expected in [('verified CA',sys.argv[1],401),
                            ('wrong CA',sys.argv[2],502)]:
 for i in range(15):
  try: urlopen(f'http://{host}:13080/channel',timeout=2); code=200
  except HTTPError as e: code=e.code
  except Exception: code=None
  if code==expected: break
  time.sleep(1)
 else:
  raise SystemExit(f'FAIL: {label}, expected {expected}, got {code}')
 print(f'PASS: {label} produced HTTP {expected}')
PY

docker run -d --name "$kh_bh" --network "$network" --read-only \
    --platform linux/amd64 --cap-drop ALL \
    --user "$(id -u):$(id -g)" --security-opt no-new-privileges \
    --mount "type=bind,src=$tmp/kh.toml,dst=/tmp/config.toml,readonly" \
    --mount "type=bind,src=$tmp/echo.py,dst=/tmp/echo.py,readonly" \
    --entrypoint /usr/local/bin/backhaul "$image" -c /tmp/config.toml >/dev/null
created="$kh_bh $created"
docker exec -d "$kh_bh" python3 /tmp/echo.py >/dev/null

docker exec -i "$ir_bh" python3 - <<'PY'
from urllib.request import urlopen
import time,sys
expected=b'uopti-tls-nginx-backhaul-ok'
for i in range(40):
 try:
  with urlopen('http://127.0.0.1:56053/health',timeout=2) as r:
   if r.status==200 and r.read()==expected:
    print('PASS: two Nginx proxies, verified TLS, Backhaul WS data roundtrip')
    sys.exit(0)
 except Exception: time.sleep(1)
raise SystemExit('FAIL: full Nginx/TLS/Backhaul roundtrip not established')
PY


# Verify the actual generated IR XHTTP reverse-proxy route over the same
# authenticated Backhaul data tunnel, with hostname verification of the IR
# synthetic TLS certificate. Requests stay inside the ephemeral network.
docker exec -i "$ir_bh" python3 - <<'PY'
import ssl
import sys
import time
from urllib.request import urlopen
expected=b'uopti-ir-xhttp-backhaul-ok'
ctx=ssl.create_default_context(cafile='/tmp/test-root-ca.pem')
for path in ('/56053/www/', '/56053/www'):
 for attempt in range(20):
  try:
   with urlopen('https://ir.kolbe1.ir:443'+path,context=ctx,timeout=2) as r:
    if r.status==200 and r.read()==expected:
     print('PASS: IR TLS Nginx XHTTP path '+path+' -> WS Backhaul -> KH mock')
     break
  except Exception:
   time.sleep(1)
 else:
  raise SystemExit('FAIL: isolated IR XHTTP location '+path)
PY
