#!/usr/bin/env bash
# Live WS data round-trip on a PRIVATE GitHub-hosted Docker network ONLY.
# No production hosts/domains/ports are contacted or modified.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != true ||
      "${RUNNER_ENVIRONMENT:-}" != github-hosted ||
      "${GITHUB_EVENT_NAME:-}" != pull_request ||
      "${GITHUB_REPOSITORY:-}" != aghajani82/u-opti ]]; then
    echo "REFUSED: GitHub-hosted PR runner required" >&2
    exit 2
fi

cd "$(dirname "$0")/.."
image="ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
tag="${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:-1}"
network="uopti-bh-test-${tag}"
server="uopti-bh-ir-${tag}"
client="uopti-bh-kh-${tag}"
tmp="$(mktemp -d)"
umask 077
created_network=0
created_server=0
created_client=0
ir_stage=""
kh_stage=""

cleanup() {
    local status="$?"
    set +e
    if (( status != 0 )); then
        echo "Isolated WS smoke failed; container states and redacted errors:"
        for name in "$server" "$client"; do
            if docker container inspect "$name" >/dev/null 2>&1; then
                docker inspect -f '{{.Name}} status={{.State.Status}} exit={{.State.ExitCode}}' "$name"
                docker logs "$name" 2>&1 | grep -Ei 'error|fail|fatal|permission|not found' |
                    sed -E 's/[0-9a-fA-F]{32,}/[redacted]/g;s/Bearer [^[:space:]]+/Bearer [redacted]/g' |
                    tail -n 12 || true
            fi
        done
    fi
    if (( created_client )); then docker rm -f "$client" >/dev/null 2>&1; fi
    if (( created_server )); then docker rm -f "$server" >/dev/null 2>&1; fi
    if (( created_network )); then docker network rm "$network" >/dev/null 2>&1; fi
    [[ -z "$ir_stage" ]] || rm -rf -- "$ir_stage"
    [[ -z "$kh_stage" ]] || rm -rf -- "$kh_stage"
    rm -rf -- "$tmp"
}
trap cleanup EXIT

openssl rand -hex 32 > "$tmp/token"
chmod 0600 "$tmp/token"
make_stage() {
    local role="$1" output stage
    output="$(python3 modules/smite-backhaul-sidecar.py \
        --role "$role" --token-file "$tmp/token")"
    stage="$(printf '%s\n' "$output" |
        sed -n "s/^PREPARED PRIVATE OFFLINE CANDIDATE: \(.*\) ($role)$/\1/p")"
    [[ -n "$stage" && -d "$stage" ]] || return 1
    printf '%s\n' "$stage"
}
ir_stage="$(make_stage ir)"
kh_stage="$(make_stage kh)"
# Only this ephemeral network fixture changes loopback binds to container
# interface binds. Real Sidecar generator output is NOT changed.
python3 - "$ir_stage" "$kh_stage" "$tmp" "$server" <<'PY'
from pathlib import Path
import sys
ir, kh, tmp = map(Path, sys.argv[1:4])
server = sys.argv[4]
s = (ir / "ir.toml").read_text()
c = (kh / "kh.toml").read_text()
assert s.count('bind_addr = "127.0.0.1:3080"') == 1
assert s.count('127.0.0.1:56053=127.0.0.1:56053') == 1
assert c.count('remote_addr = "127.0.0.1:13080"') == 1
s = s.replace('bind_addr = "127.0.0.1:3080"', 'bind_addr = "0.0.0.0:3080"')
s = s.replace('127.0.0.1:56053=127.0.0.1:56053',
              '0.0.0.0:56053=127.0.0.1:56053')
c = c.replace('remote_addr = "127.0.0.1:13080"',
              f'remote_addr = "{server}:3080"')
(tmp / "ir.toml").write_text(s)
(tmp / "kh.toml").write_text(c)
(tmp / "echo.py").write_text("""
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/health':
            self.send_error(404)
            return
        payload = b'uopti-isolated-ws-roundtrip-ok'
        self.send_response(200)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass

HTTPServer(('127.0.0.1', 56053), Handler).serve_forever()
""")
PY
chmod 0600 "$tmp/"*.toml "$tmp/echo.py"

docker pull --platform linux/amd64 "$image" >/dev/null
docker network create --internal "$network" >/dev/null
created_network=1

docker run -d --platform linux/amd64 --name "$server" \
    --network "$network" --read-only --cap-drop ALL \
    --security-opt no-new-privileges \
    --mount "type=bind,src=$tmp/ir.toml,dst=/tmp/sidecar.toml,readonly" \
    --entrypoint /usr/local/bin/backhaul \
    "$image" -c /tmp/sidecar.toml >/dev/null
created_server=1

docker run -d --platform linux/amd64 --name "$client" \
    --network "$network" --read-only --cap-drop ALL \
    --security-opt no-new-privileges \
    --mount "type=bind,src=$tmp/kh.toml,dst=/tmp/sidecar.toml,readonly" \
    --mount "type=bind,src=$tmp/echo.py,dst=/tmp/echo.py,readonly" \
    --entrypoint /usr/local/bin/backhaul \
    "$image" -c /tmp/sidecar.toml >/dev/null
created_client=1
docker exec -d "$client" python3 /tmp/echo.py >/dev/null

# Actual traffic crosses Backhaul WS control/data channels between the two
# ephemeral containers. This is not the final TLS/Nginx integration test.
docker exec -i "$server" python3 - <<'PY'
import time
import urllib.request
import sys
expected = b'uopti-isolated-ws-roundtrip-ok'
for i in range(40):
    try:
        with urllib.request.urlopen("http://127.0.0.1:56053/health", timeout=2) as response:
            if response.status == 200 and response.read() == expected:
                print("PASS: Backhaul v0.7.2 isolated WS control and data roundtrip")
                sys.exit(0)
    except Exception:
        time.sleep(1)
print("FAIL: isolated Backhaul WS roundtrip not established")
sys.exit(1)
PY
