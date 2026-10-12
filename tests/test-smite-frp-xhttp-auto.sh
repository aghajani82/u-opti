#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export SMITE_GATEWAY_BACKEND_CONF="$tmp/backend.conf"
export SMITE_FRP_XHTTP_CONF="$tmp/xhttp.conf"
export SMITE_STATE_FILE="$tmp/state.env"
export SMITE_OVERLAY_DIR="$tmp/overlay"
export MOCK_FRP_TUNNELS="$tmp/tunnels.json"
mkdir -p "$SMITE_OVERLAY_DIR/node"
touch "$SMITE_OVERLAY_DIR/node/frp_gateway_config.py"
echo 'SMITE_CONNECTION_MODE=standard' > "$SMITE_STATE_FILE"
cat > "$SMITE_GATEWAY_BACKEND_CONF" <<'EOF'
# Managed by U-OPTI - Smite Panel TLS backend
server {
    listen 127.0.0.1:8443 ssl;
    server_name ir.kolbe1.ir;
    location = /~!frp {
        proxy_pass http://127.0.0.1:7000;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
EOF
source "$root/modules/smite-frp-xhttp.sh"
# CI runs as a non-root user; stub external commands, never touch the host.
id() {
    if [ "$1" = "-u" ]; then printf '0\n'; else command id "$@"; fi
}
docker() {
    [ "$1" = exec ] && [ "$2" = smite-node ] && [ "$3" = cat ] || return 1
    cat "$MOCK_FRP_TUNNELS"
}
nginx() {
    [ "$1" = -t ] || return 1
    [ "${MOCK_NGINX_FAIL:-0}" != 1 ]
}
systemctl() {
    [ "$1" = reload ] && [ "$2" = nginx ]
}
smite_frp_xhttp_include ir.kolbe1.ir
grep -Fq "    include $SMITE_FRP_XHTTP_CONF;" "$SMITE_GATEWAY_BACKEND_CONF"
cp "$SMITE_GATEWAY_BACKEND_CONF" "$tmp/backend.expected"
smite_frp_xhttp_include ir.kolbe1.ir
cmp -s "$SMITE_GATEWAY_BACKEND_CONF" "$tmp/backend.expected"

cat > "$MOCK_FRP_TUNNELS" <<'JSON'
{
  "one": {
    "core": "frp",
    "spec": {"mode": "server", "type": "tcp", "bind_port": 7000, "ports": [13914]}
  },
  "other": {
    "core": "backhaul",
    "spec": {"mode": "server", "type": "tcp", "ports": [30000]}
  },
  "foreign": {
    "core": "frp",
    "spec": {"mode": "client", "type": "tcp", "ports": [30001]}
  }
}
JSON
smite_frp_xhttp_sync
grep -Fq 'location = /13914/web {' "$SMITE_FRP_XHTTP_CONF"
grep -Fq 'location ^~ /13914/web/ {' "$SMITE_FRP_XHTTP_CONF"
grep -Fq 'proxy_pass http://127.0.0.1:13914/web;' "$SMITE_FRP_XHTTP_CONF"
grep -Fq 'proxy_pass http://127.0.0.1:13914/web/;' "$SMITE_FRP_XHTTP_CONF"
if grep -Fq '30000' "$SMITE_FRP_XHTTP_CONF" || grep -Fq '30001' "$SMITE_FRP_XHTTP_CONF"; then
    echo "ERROR: Non-server FRP ports were exposed"
    exit 1
fi
cp "$SMITE_FRP_XHTTP_CONF" "$tmp/expected"
smite_frp_xhttp_sync
cmp -s "$SMITE_FRP_XHTTP_CONF" "$tmp/expected"

# Fail-closed on corrupt, unsafe, or newly invalid tunnel state.
printf '%s\n' '{"bad":{"core":"frp","spec":{"mode":"server","type":"tcp","ports":[7000]}}}' > "$MOCK_FRP_TUNNELS"
if smite_frp_xhttp_sync; then
    echo "ERROR: FRPS bind port was accepted as a public route"
    exit 1
fi
cmp -s "$SMITE_FRP_XHTTP_CONF" "$tmp/expected"

printf '%s\n' '{"two":{"core":"frp","spec":{"mode":"server","type":"tcp","ports":[15432]}}}' > "$MOCK_FRP_TUNNELS"
MOCK_NGINX_FAIL=1
export MOCK_NGINX_FAIL
if smite_frp_xhttp_sync; then
    echo "ERROR: Simulated invalid Nginx configuration was accepted"
    exit 1
fi
cmp -s "$SMITE_FRP_XHTTP_CONF" "$tmp/expected"
unset MOCK_NGINX_FAIL

smite_frp_xhttp_sync
grep -Fq 'location = /15432/web {' "$SMITE_FRP_XHTTP_CONF"
! grep -Fq '/13914/web' "$SMITE_FRP_XHTTP_CONF"
printf '{}\n' > "$MOCK_FRP_TUNNELS"
smite_frp_xhttp_sync
! grep -Fq '/15432/web' "$SMITE_FRP_XHTTP_CONF"
echo 'SMITE_CONNECTION_MODE=private' > "$SMITE_STATE_FILE"
cp "$SMITE_FRP_XHTTP_CONF" "$tmp/private.expected"
smite_frp_xhttp_sync
cmp -s "$SMITE_FRP_XHTTP_CONF" "$tmp/private.expected"
echo 'PASS: FRP XHTTP routes are automatic, bounded, idempotent, reversible, and Standard-only'
