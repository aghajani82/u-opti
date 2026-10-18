#!/usr/bin/env bash
# Simulate KH pending pairing from the real installer; no Docker/network/VPS.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/fresh/node" "$TMP/fresh/node/certs" "$TMP/fresh/node/config"
export SMITE_INSTALL_PROFILE=clean-rc
source "$ROOT/modules/smite-install.sh"
SMITE_NODE_IMAGE="smite-node:stage15-local"
SMITE_NODE_DIR="$TMP/fresh/node"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"

cat > "$TMP/node-upstream.yml" <<'EOF_COMPOSE'
# CI fixture: exact essential v0.1.7 service fields, not a runtime Compose image.
services:
  smite-node:
    image: ghcr.io/zzedix/smite-node:${SMITE_VERSION:-latest}
    container_name: smite-node
    network_mode: host
    volumes:
      - ./certs:/etc/smite-node/certs:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:${NODE_API_PORT:-8888}/api/agent/status')"]
EOF_COMPOSE
smite_download_upstream() {
    test "$1" = "node/docker-compose.yml"
    cp "$TMP/node-upstream.yml" "$2"
}
smite_frp_prepare_binaries() { :; }
smite_frp_mount_compose() { :; }
docker() {
    test "$1" = compose && test "$2" = -f && test "$4" = config
}
smite_install_node_files node-kh foreign panel.example.com:443 "" "" "" standard > "$TMP/log"

grep -qx 'SMITE_NODE_PANEL_AUTH_MODE=paused' "$SMITE_NODE_DIR/.env"
grep -qx 'SMITE_AGENT_AUTH_MODE=strict' "$SMITE_NODE_DIR/.env"
grep -qx 'PANEL_ADDRESS=panel.example.com:443' "$SMITE_NODE_DIR/.env"
grep -q 'FOREIGN_RC_CA_DOWNLOAD=DEFERRED_UNTIL_SECURE_ADMISSION' "$TMP/log"
grep -q 'FOREIGN_RC_PAIRING=PENDING_NO_OUTBOUND_REGISTRATION' "$TMP/log"
test ! -e "$SMITE_NODE_DIR/certs/ca.crt"
grep -qF "http://127.0.0.1:8888/" "$SMITE_NODE_COMPOSE"
! grep -qF "/api/agent/status" "$SMITE_NODE_COMPOSE"
grep -qF '"127.0.0.1"' "$SMITE_NODE_COMPOSE"
grep -qF "smite-node:stage15-local" "$SMITE_NODE_COMPOSE"
! grep -Eq 'SMITE_NODE_PANEL_AUTH_MODE=legacy|SMITE_AGENT_AUTH_MODE=legacy' "$SMITE_NODE_DIR/.env"

# If upstream's healthcheck drifted, do not create a falsely healthy KH Node.
sed -i 's|/api/agent/status|/api/agent/changed-status|' "$TMP/node-upstream.yml"
if smite_install_node_files node-kh foreign panel.example.com:443 "" "" "" standard >"$TMP/changed.log" 2>&1; then
    echo "FAIL: unsafe unknown upstream healthcheck was accepted" >&2
    exit 1
fi
grep -q "HOLD: Unknown Node healthcheck" "$TMP/changed.log"

# Stable source path retains its old CA and registration behavior.
export SMITE_INSTALL_PROFILE=stable
SMITE_NODE_IMAGE="$SMITE_NODE_REPO@$SMITE_NODE_DIGEST"
cp "$SMITE_NODE_COMPOSE" "$TMP/rc-result.yml"
cat > "$TMP/node-upstream.yml" <<'EOF_COMPOSE'
# CI fixture: exact essential v0.1.7 service fields, not a runtime Compose image.
services:
  smite-node:
    image: ghcr.io/zzedix/smite-node:${SMITE_VERSION:-latest}
    container_name: smite-node
    network_mode: host
    volumes:
      - ./certs:/etc/smite-node/certs:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:${NODE_API_PORT:-8888}/api/agent/status')"]
EOF_COMPOSE
printf '%s\n' '-----BEGIN CERTIFICATE-----' 'MOCK' '-----END CERTIFICATE-----' > "$TMP/test-ca.crt"
smite_install_node_files node-kh foreign panel.example.com:443 "$TMP/test-ca.crt" "" "" standard >"$TMP/stable.log"
test -f "$SMITE_NODE_DIR/certs/ca.crt"
! grep -q '^SMITE_NODE_PANEL_AUTH_MODE=paused' "$SMITE_NODE_DIR/.env"
grep -qF "/api/agent/status" "$SMITE_NODE_COMPOSE"
echo "FOREIGN_PAUSED_PAIRING_INSTALL_TESTS=PASSED"
