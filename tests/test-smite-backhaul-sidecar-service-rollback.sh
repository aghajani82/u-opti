#!/usr/bin/env bash
# Live Nginx reload/rollback LAB ONLY; disposable GitHub-hosted Docker runner.
# No published host ports, host networking, or production configuration mounts.
set -euo pipefail
if [[ "$GITHUB_ACTIONS" != true || "$RUNNER_ENVIRONMENT" != github-hosted ||
      "$GITHUB_EVENT_NAME" != pull_request ||
      "$GITHUB_REPOSITORY" != aghajani82/u-opti ]]; then
    echo "REFUSED: GitHub-hosted PR only" >&2; exit 2
fi
cd "$(dirname "$0")/.."
umask 077
tag="$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
network="uopti-bh-live-lab-$tag"
ng="uopti-ng-lab-$tag"
bh="uopti-bh-lab-$tag"
image="ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
tmp="$(mktemp -d)"
stage=""
net_created=0
ng_created=0
bh_created=0
cleanup() {
    set +e
    if (( bh_created )); then docker rm -f "$bh" >/dev/null 2>&1; fi
    if (( ng_created )); then docker rm -f "$ng" >/dev/null 2>&1; fi
    if (( net_created )); then docker network rm "$network" >/dev/null 2>&1; fi
    if [[ "$stage" == /tmp/uopti-backhaul-sidecar-* ]]; then rm -rf -- "$stage"; fi
    rm -rf -- "$tmp"
}
trap cleanup EXIT
openssl rand -hex 32 > "$tmp/token"
out="$(python3 modules/smite-backhaul-sidecar.py --role ir --token-file "$tmp/token")"
stage="$(printf '%s\n' "$out" | sed -n 's/^PREPARED PRIVATE OFFLINE CANDIDATE: \(.*\) (ir)$/\1/p')"
[[ "$stage" == /tmp/uopti-backhaul-sidecar-* && -d "$stage" ]]

python3 - "$tmp" "$stage" "$bh" <<'PY'
from pathlib import Path
import sys
d, stage = map(Path,sys.argv[1:3])
bh = sys.argv[3]
baseline = """worker_processes 1;
pid /tmp/uopti-lab-nginx.pid;
events { worker_connections 128; }
http {
  access_log off;
  server {
    listen 8080;
    server_name sandbox.invalid;
    location = /legacy { return 200 'legacy-healthy'; }
    location / { return 404; }
    # UOPTI_SYNTHETIC_HOOK
  }
}
"""
assert baseline.count("# UOPTI_SYNTHETIC_HOOK")==1
(d/"nginx.conf").write_text(baseline)
(d/"baseline.conf").write_text(baseline)
control=(stage/"ir-control.inc").read_text()
xhttp=(stage/"ir-xhttp.inc").read_text()
assert 'location = /channel {' in control
assert 'location ^~ /tunnel/ {' in control
assert 'location ^~ /56053/www/ {' in xhttp
(d/"ir-control.inc").write_text(
    control.replace("http://127.0.0.1:3080",f"http://{bh}:3080"))
(d/"ir-xhttp.inc").write_text(
    xhttp.replace("http://127.0.0.1:56053",f"http://{bh}:56053"))
active=baseline.replace("# UOPTI_SYNTHETIC_HOOK",
    "include /run/uopti-lab/ir-control.inc;\n"
    "    include /run/uopti-lab/ir-xhttp.inc;\n"
    "    # UOPTI_SYNTHETIC_HOOK")
(d/"active.conf").write_text(active)
server=(stage/"ir.toml").read_text()
assert 'bind_addr = "127.0.0.1:3080"' in server
(d/"ir.toml").write_text(server.replace(
    'bind_addr = "127.0.0.1:3080"','bind_addr = "0.0.0.0:3080"'))
PY
chmod 0600 "$tmp/"*
docker pull --platform linux/amd64 "$image" >/dev/null
docker pull nginx:stable-alpine >/dev/null
docker network create --internal "$network" >/dev/null
net_created=1
docker run -d --name "$ng" --network "$network" \
    --network-alias nginx.lab.invalid \
    --mount "type=bind,src=$tmp,dst=/run/uopti-lab" \
    --entrypoint nginx nginx:stable-alpine \
    -c /run/uopti-lab/nginx.conf -g 'daemon off;' >/dev/null
ng_created=1
docker exec "$ng" nginx -t -c /run/uopti-lab/nginx.conf >/dev/null 2>&1
docker run -d --name "$bh" --platform linux/amd64 \
    --network "$network" --read-only --cap-drop ALL \
    --user "$(id -u):$(id -g)" --security-opt no-new-privileges \
    --mount "type=bind,src=$tmp/ir.toml,dst=/tmp/bh.toml,readonly" \
    --entrypoint /usr/local/bin/backhaul "$image" -c /tmp/bh.toml >/dev/null
bh_created=1
probe() {
    docker exec -i "$bh" python3 - "$1" "$2" <<'PY'
import sys,time,urllib.request,urllib.error
path,want=sys.argv[1],int(sys.argv[2])
for attempt in range(40):
    try:
        with urllib.request.urlopen("http://nginx.lab.invalid:8080"+path,timeout=2) as r:
            status,body=r.status,r.read()
    except urllib.error.HTTPError as err:
        status,body=err.code,err.read()
    except Exception:
        status,body=0,b""
    if status==want and (path!="/legacy" or body==b"legacy-healthy"):
        print("PASS: isolated "+path+" -> "+str(want));sys.exit(0)
    time.sleep(.25)
raise SystemExit("FAIL: isolated "+path+" did not return "+str(want))
PY
}
probe /legacy 200
probe /channel 404
python3 - "$tmp" <<'PY'
from pathlib import Path
import hashlib,os,sys,tempfile
root=Path(sys.argv[1])
old=(root/"baseline.conf").read_bytes()
assert (root/"nginx.conf").read_bytes()==old
new=(root/"active.conf").read_bytes()
fd,tmp=tempfile.mkstemp(prefix=".uopti-stage-",dir=root)
with os.fdopen(fd,"wb") as f:
    f.write(new);f.flush();os.fsync(f.fileno())
os.replace(tmp,root/"nginx.conf")
(root/"expected-active.sha256").write_text(hashlib.sha256(new).hexdigest())
PY
docker exec "$ng" nginx -t -c /run/uopti-lab/nginx.conf >/dev/null 2>&1
docker exec "$ng" nginx -s reload -c /run/uopti-lab/nginx.conf >/dev/null 2>&1
probe /legacy 200
probe /channel 401
echo "PASS: isolated Nginx activated Sidecar WS, legacy route still works"

cp "$tmp/ir-control.inc" "$tmp/ir-control.good"
printf '\nsynthetic broken directive;\n' >> "$tmp/ir-control.inc"
if docker exec "$ng" nginx -t -c /run/uopti-lab/nginx.conf >/dev/null 2>&1; then
    echo "FAIL: invalid Nginx config unexpectedly validated" >&2; exit 1
fi
probe /legacy 200
probe /channel 401
mv "$tmp/ir-control.good" "$tmp/ir-control.inc"
echo "PASS: invalid reload candidate rejected without disturbing old worker"

# Unknown drift must make rollback stop *before* any original-file restoration.
printf '\n# simulated third-party drift\n' >> "$tmp/nginx.conf"
if python3 - "$tmp" <<'PY'
from pathlib import Path
import hashlib,sys
root=Path(sys.argv[1])
want=(root/"expected-active.sha256").read_text()
have=hashlib.sha256((root/"nginx.conf").read_bytes()).hexdigest()
sys.exit(0 if want==have else 1)
PY
then
    echo "FAIL: drift was not detected" >&2; exit 1
fi
grep -Fq '# simulated third-party drift' "$tmp/nginx.conf"
echo "PASS: hash drift blocks all attempted rollback changes"

# Only lab-owned injected drift can be cleared by this test; production has
# no equivalent automatic override or reconciliation path.
cp "$tmp/active.conf" "$tmp/nginx.conf"
python3 - "$tmp" <<'PY'
from pathlib import Path
import hashlib,os,sys,tempfile
root=Path(sys.argv[1])
assert hashlib.sha256((root/"nginx.conf").read_bytes()).hexdigest()==(
    root/"expected-active.sha256").read_text()
old=(root/"baseline.conf").read_bytes()
fd,name=tempfile.mkstemp(prefix=".uopti-restore-",dir=root)
with os.fdopen(fd,"wb") as f:
    f.write(old);f.flush();os.fsync(f.fileno())
os.replace(name,root/"nginx.conf")
assert (root/"nginx.conf").read_bytes()==old
PY
docker exec "$ng" nginx -t -c /run/uopti-lab/nginx.conf >/dev/null 2>&1
docker exec "$ng" nginx -s reload -c /run/uopti-lab/nginx.conf >/dev/null 2>&1
probe /legacy 200
probe /channel 404
cmp -s "$tmp/nginx.conf" "$tmp/baseline.conf"
echo "PASS: real isolated Nginx reload restored exact synthetic baseline"
