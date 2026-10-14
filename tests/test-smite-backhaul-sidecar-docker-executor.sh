#!/usr/bin/env bash
# Real Docker Nginx + Backhaul apply/recovery LAB. GitHub-hosted PR ONLY.
set -Eeuo pipefail
if [[ "$GITHUB_ACTIONS" != true || "$RUNNER_ENVIRONMENT" != github-hosted ||
      "$GITHUB_EVENT_NAME" != pull_request || "$GITHUB_REPOSITORY" != aghajani82/u-opti ]]; then
    echo "REFUSED: GitHub-hosted PR only" >&2; exit 2
fi
cd "$(dirname "$0")/.."
umask 077
tag="$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
network="uopti-net-executor-$tag"
ng="uopti-ng-executor-$tag"
bh="uopti-bh-executor-$tag"
image="ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
root="$(mktemp -d "/tmp/uopti-bh-executor-$tag-XXXXXX")"
stage=""
network_created=0
ng_created=0
bh_created=0
cleanup() {
    set +e
    if (( bh_created )); then docker rm -f "$bh" >/dev/null 2>&1; fi
    if (( ng_created )); then docker rm -f "$ng" >/dev/null 2>&1; fi
    if (( network_created )); then docker network rm "$network" >/dev/null 2>&1; fi
    if [[ "$stage" == /tmp/uopti-backhaul-sidecar-* ]]; then rm -rf -- "$stage"; fi
    if [[ "$root" == /tmp/uopti-bh-executor-"$tag"-* ]]; then rm -rf -- "$root"; fi
}
trap cleanup EXIT

printf 'UOPTI_BACKHAUL_DOCKER_LAB_V1\n' > "$root/.uopti-lab-marker"
openssl rand -hex 32 > "$root/token"
out="$(python3 -B modules/smite-backhaul-sidecar.py --role ir \
    --token-file "$root/token" --ir-domain ir.example.com --kh-host kh.example.com)"
stage="$(printf '%s\n' "$out" | sed -n 's/^PREPARED PRIVATE OFFLINE CANDIDATE: \(.*\) (ir)$/\1/p')"
[[ "$stage" == /tmp/uopti-backhaul-sidecar-* && -d "$stage" ]]

python3 - "$root" "$stage" "$bh" <<'PY'
from pathlib import Path
import sys
root, stage = map(Path, sys.argv[1:3])
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
control = (stage / "ir-control.inc").read_text()
xhttp = (stage / "ir-xhttp.inc").read_text()
assert "location = /channel {" in control
assert "location ^~ /56053/www/ {" in xhttp
(root / "ir-control.inc").write_text(
    control.replace("http://127.0.0.1:3080", f"http://{bh}:3080"))
(root / "ir-xhttp.inc").write_text(
    xhttp.replace("http://127.0.0.1:56053", f"http://{bh}:56053"))
active = baseline.replace("# UOPTI_SYNTHETIC_HOOK",
    "include /run/uopti-lab/ir-control.inc;\n"
    "    include /run/uopti-lab/ir-xhttp.inc;\n"
    "    # UOPTI_SYNTHETIC_HOOK")
for name, text in (("baseline.conf", baseline),
                   ("nginx.conf", baseline), ("active.conf", active)):
    (root / name).write_text(text)
toml = (stage / "ir.toml").read_text()
assert 'bind_addr = "127.0.0.1:3080"' in toml
(root / "ir.toml").write_text(
    toml.replace('bind_addr = "127.0.0.1:3080"',
                 'bind_addr = "0.0.0.0:3080"'))
PY
chmod 0600 "$root/"*

docker pull --platform linux/amd64 "$image" >/dev/null
docker pull nginx:stable-alpine >/dev/null
docker network create --internal "$network" >/dev/null
network_created=1
docker run -d --name "$ng" --network "$network" --network-alias nginx.lab.invalid \
    --label uopti.lab=backhaul-executor-v1 \
    --mount "type=bind,src=$root,dst=/run/uopti-lab" \
    --entrypoint nginx nginx:stable-alpine \
    -c /run/uopti-lab/nginx.conf -g 'daemon off;' >/dev/null
ng_created=1
docker run -d --name "$bh" --platform linux/amd64 \
    --network "$network" --read-only --cap-drop ALL \
    --user "$(id -u):$(id -g)" --security-opt no-new-privileges \
    --mount "type=bind,src=$root/ir.toml,dst=/tmp/bh.toml,readonly" \
    --entrypoint /usr/local/bin/backhaul "$image" -c /tmp/bh.toml >/dev/null
bh_created=1

controller() {
    python3 -B modules/smite-backhaul-sidecar-docker-lab.py \
        --workspace "$root" --container "$ng" "$@"
}
probe() {
    docker exec -i "$bh" python3 - "$1" "$2" <<'PY'
import sys, time, urllib.request, urllib.error
path, expected = sys.argv[1], int(sys.argv[2])
for _ in range(35):
    try:
        with urllib.request.urlopen(
            "http://nginx.lab.invalid:8080" + path, timeout=2
        ) as r:
            code, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, body = e.code, e.read()
    except Exception:
        code, body = 0, b""
    if code == expected and (path != "/legacy" or body == b"legacy-healthy"):
        print("PASS: " + path + " -> " + str(code))
        sys.exit(0)
    time.sleep(.25)
raise SystemExit("FAIL: unexpected isolated response " + path)
PY
}

probe /legacy 200
probe /channel 404
test "$(controller --action apply)" = APPLIED_WITH_RECOVERY_JOURNAL
probe /legacy 200
probe /channel 401
if controller --action apply >/dev/null 2>&1; then
    echo 'FAIL: duplicate apply accepted' >&2; exit 1
fi
test "$(controller --action rollback)" = ROLLED_BACK_TO_EXACT_BASELINE
probe /channel 404
cmp -s "$root/baseline.conf" "$root/nginx.conf"

cp "$root/active.conf" "$root/active.good"
printf '\nsynthetic_bad_nginx_directive yes;\n' >> "$root/active.conf"
if controller --action apply >/dev/null 2>&1; then
    echo 'FAIL: bad candidate accepted' >&2; exit 1
fi
test "$(controller --action status)" = NO_PENDING_LAB_TRANSACTION
cmp -s "$root/baseline.conf" "$root/nginx.conf"
probe /legacy 200
mv "$root/active.good" "$root/active.conf"

set +e
controller --action apply --simulate-crash-after-journal >/dev/null 2>&1
rc=$?
set -e
test "$rc" = 89
test "$(controller --action status)" = RECOVERY_JOURNAL_PRESENT
test "$(controller --action rollback)" = ROLLED_BACK_UNCHANGED_BASELINE
cmp -s "$root/baseline.conf" "$root/nginx.conf"
probe /legacy 200

set +e
controller --action apply --simulate-crash-after-write >/dev/null 2>&1
rc=$?
set -e
test "$rc" = 88
test "$(controller --action status)" = RECOVERY_JOURNAL_PRESENT
test "$(controller --action rollback)" = ROLLED_BACK_TO_EXACT_BASELINE
probe /channel 404

test "$(controller --action apply)" = APPLIED_WITH_RECOVERY_JOURNAL
printf '\n# third party drift\n' >> "$root/nginx.conf"
if controller --action rollback >/dev/null 2>&1; then
    echo 'FAIL: third party modification overwritten' >&2; exit 1
fi
grep -Fq '# third party drift' "$root/nginx.conf"
test "$(controller --action status)" = RECOVERY_JOURNAL_PRESENT
cp "$root/active.conf" "$root/nginx.conf"  # Only lab-owned injected drift.
chmod 0600 "$root/nginx.conf"
test "$(controller --action rollback)" = ROLLED_BACK_TO_EXACT_BASELINE
probe /legacy 200
probe /channel 404
echo 'PASS: real Docker-only Nginx apply, invalid-config rollback, crash recovery, drift refusal'
