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
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${NODE_API_PORT:-8888}/healthz')"]
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
grep -qx 'SMITE_ENGINE_INVENTORY_MODE=managed' "$SMITE_NODE_DIR/.env"
grep -qx 'PANEL_ADDRESS=panel.example.com:443' "$SMITE_NODE_DIR/.env"
grep -q 'FOREIGN_RC_CA_DOWNLOAD=DEFERRED_UNTIL_SECURE_ADMISSION' "$TMP/log"
grep -q 'FOREIGN_RC_PAIRING=PENDING_NO_OUTBOUND_REGISTRATION' "$TMP/log"
test ! -e "$SMITE_NODE_DIR/certs/ca.crt"
grep -qF "/healthz" "$SMITE_NODE_COMPOSE"
! grep -qF "/api/agent/status" "$SMITE_NODE_COMPOSE"
grep -qF '"127.0.0.1"' "$SMITE_NODE_COMPOSE"
grep -qF "smite-node:stage15-local" "$SMITE_NODE_COMPOSE"
! grep -Eq 'SMITE_NODE_PANEL_AUTH_MODE=legacy|SMITE_AGENT_AUTH_MODE=legacy' "$SMITE_NODE_DIR/.env"

# If upstream's healthcheck drifted, do not create a falsely healthy KH Node.
sed -i 's|/healthz|/healthz-unreviewed|' "$TMP/node-upstream.yml"
if smite_install_node_files node-kh foreign panel.example.com:443 "" "" "" standard >"$TMP/changed.log" 2>&1; then
    echo "FAIL: unsafe unknown upstream healthcheck was accepted" >&2
    exit 1
fi
grep -q "HOLD: Reviewed local /healthz required" "$TMP/changed.log"

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
! grep -q '^SMITE_ENGINE_INVENTORY_MODE=' "$SMITE_NODE_DIR/.env"
grep -qF "/api/agent/status" "$SMITE_NODE_COMPOSE"
# RC.1 Foreign Gateway uses loopback-only /healthz for local Node readiness,
# but the proxied root / for transport reachability. Neither grants signed
# /api/agent/status or anonymous Panel discovery before secure pairing.
source "$ROOT/modules/smite-foreign-gateway.sh"
SMITE_STATE_DIR="$TMP/state"
SMITE_STATE_FILE="$SMITE_STATE_DIR/state.env"
SMITE_FOREIGN_GATEWAY_STATE_FILE="$SMITE_STATE_DIR/foreign-gateway.env"
mkdir -p "$SMITE_STATE_DIR"
cat > "$SMITE_STATE_FILE" <<'EOF_STATE'
SMITE_ROLE=foreign
SMITE_CONNECTION_MODE=standard
SMITE_MANAGED_VERSION=2.0.0-rc.1
EOF_STATE
cat > "$SMITE_NODE_DIR/.env" <<'EOF_RC_ENV'
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
EOF_RC_ENV

docker() {
    if [ "$1" = inspect ] && [ "$2" = -f ]; then
        case "$3" in
            '{{.State.Status}}') printf 'running\n' ;;
            '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}') printf 'healthy\n' ;;
            *) echo "Unexpected docker inspect template" >&2; return 90 ;;
        esac
    elif [ "$1" = compose ] && [ "$2" = -f ]; then
        printf '%s\n' "$*" >> "$TMP/docker-calls"
    else
        echo "Unexpected docker operation" >&2; return 91
    fi
}
curl() {
    local endpoint=""
    for endpoint in "$@"; do :; done
    printf '%s\n' "$endpoint" >> "$TMP/curl-urls"
    case "$endpoint" in
        http://127.0.0.1:8888/healthz|\
        http://127.0.0.1:8888/api/agent/status|https://kh.example.test/smite-node/trial/api/agent/status)
            printf '{"status":"ok"}\n' ;;
        https://kh.example.test/smite-node/trial/)
            printf '{"status":"ok","service":"smite-node"}\n' ;;
        *) echo "Unexpected URL: $endpoint" >&2; return 92 ;;
    esac
}
smite_foreign_gateway_is_clean_rc
smite_foreign_gateway_require_rc_paused
smite_foreign_gateway_require_node
smite_foreign_gateway_verify_local kh.example.test /smite-node/trial
grep -Fxq 'http://127.0.0.1:8888/healthz' "$TMP/curl-urls"
grep -Fxq 'https://kh.example.test/smite-node/trial/' "$TMP/curl-urls"
! grep -Fxq 'https://kh.example.test/smite-node/trial/healthz' "$TMP/curl-urls"
! grep -Fq '/api/agent/status' "$TMP/curl-urls"

# Pre-pairing RC must not query anonymous /api/nodes; use signed pairing later.
if smite_foreign_gateway_verify_panel panel.example.test node-kh https://kh.example.test/smite-node/trial; then
    echo "FAIL: unpaired RC permitted Panel verification" >&2
    exit 1
fi
! grep -Fq '/api/nodes' "$TMP/curl-urls"

smite_foreign_gateway_recreate_node
grep -Fq -- '--force-recreate smite-node' "$TMP/docker-calls"
! test -e "$TMP/fresh/node/docker-compose.signed-control.yml"

# Reject downgrading a new RC Node from strict to legacy agent auth.
sed -i 's/SMITE_AGENT_AUTH_MODE=strict/SMITE_AGENT_AUTH_MODE=legacy/' "$SMITE_NODE_DIR/.env"
if smite_foreign_gateway_require_rc_paused >"$TMP/unsafe.log" 2>&1; then
    echo "FAIL: RC accepted non-strict Node" >&2
    exit 1
fi
grep -Fq 'HOLD: Foreign RC Node is not in the reviewed paused/strict/managed state.' "$TMP/unsafe.log"
sed -i 's/SMITE_AGENT_AUTH_MODE=legacy/SMITE_AGENT_AUTH_MODE=strict/' "$SMITE_NODE_DIR/.env"

# Historical stable mode retains the old Agent readiness endpoint.
sed -i 's/SMITE_MANAGED_VERSION=2.0.0-rc.1/SMITE_MANAGED_VERSION=0.1.7/' "$SMITE_STATE_FILE"
! smite_foreign_gateway_is_clean_rc
: > "$TMP/curl-urls"
smite_foreign_gateway_require_node
smite_foreign_gateway_verify_local kh.example.test /smite-node/trial
grep -Fxq 'http://127.0.0.1:8888/api/agent/status' "$TMP/curl-urls"
grep -Fxq 'https://kh.example.test/smite-node/trial/api/agent/status' "$TMP/curl-urls"
! grep -Fq '/healthz' "$TMP/curl-urls"

# Source-level safety invariant: clean-RC config skips legacy metadata overlay
# and stops at pending signed pairing, not the anonymous Panel API.
python3 - "$ROOT/modules/smite-foreign-gateway.sh" <<'PY_RC_GATE'
from pathlib import Path
import sys
script = Path(sys.argv[1]).read_text()
configure = script.split("smite_foreign_gateway_configure() {", 1)[1].split(
    "\n# Opt-in sharing", 1)[0]
assert 'FOREIGN_RC_LEGACY_METADATA_OVERLAY=SKIPPED' in configure
assert 'FOREIGN_RC_SIGNED_CONTROL=HOLD_PENDING_PAIRING' in configure
assert configure.index('if smite_foreign_gateway_is_clean_rc; then\n        echo "FOREIGN_RC_LEGACY_METADATA_OVERLAY=SKIPPED"') < configure.index('smite_foreign_gateway_patch_control_metadata ||')
assert configure.index('FOREIGN_RC_SIGNED_CONTROL=HOLD_PENDING_PAIRING') < configure.index('smite_foreign_gateway_verify_panel "$panel_domain"')
PY_RC_GATE

echo "FOREIGN_RC1_GATEWAY_READINESS_AND_AUTH_HOLD=PASS"

echo "FOREIGN_PAUSED_PAIRING_INSTALL_TESTS=PASSED"
