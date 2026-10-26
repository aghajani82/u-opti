#!/usr/bin/env bash
# Stage28: model an entire IR clean-RC first-boot CONFIGURATION, no VPS,
# no real Docker, network, tunneling, Admin creation or live TLS. Ensures
# no anonymous legacy machine registration is needed to finish IR setup.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
export SMITE_INSTALL_PROFILE=clean-rc
source "$ROOT/modules/smite-install.sh"
# This is a disposable install-state fixture, not an IR host. Broker root
# provisioning and Compose mount admission have separate dedicated tests.
smite_install_clean_rc_broker_prepare() {
    SMITE_UOPTI_BROKER_GID=39100
    return 0
}
smite_install_clean_rc_broker_panel_mount() { return 0; }
python3() {
    if [[ " $* " == *"smite-rc5-xhttp-broker-compose.py"* ]]; then return 0; fi
    command python3 "$@"
}
SMITE_PANEL_DIR="$TMP/ir/panel"
SMITE_NODE_DIR="$TMP/ir/node"
SMITE_PANEL_COMPOSE="$SMITE_PANEL_DIR/docker-compose.yml"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
SMITE_PANEL_IMAGE=smite-panel:stage15-local
SMITE_NODE_IMAGE=smite-node:stage15-local

cat > "$TMP/panel-upstream.yml" <<'EOF_PANEL'
services:
  smite-panel:
    image: ghcr.io/zzedix/smite-panel:${SMITE_VERSION:-latest}
    env_file:
      - .env
EOF_PANEL
cat > "$TMP/node-upstream.yml" <<'EOF_NODE'
services:
  smite-node:
    image: ghcr.io/zzedix/smite-node:${SMITE_VERSION:-latest}
    container_name: smite-node
    network_mode: host
    volumes:
      - ./certs:/etc/smite-node/certs:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:${NODE_API_PORT:-8888}/api/agent/status')"]
EOF_NODE
smite_download_upstream() {
    case "$1" in
       docker-compose.yml) cp "$TMP/panel-upstream.yml" "$2" ;;
       node/docker-compose.yml) cp "$TMP/node-upstream.yml" "$2" ;;
       *) echo "Unexpected download path" >&2; return 1 ;;
    esac
}
smite_frp_prepare_binaries() { :; }
smite_frp_mount_compose() { :; }
docker() {
    test "$1" = compose && test "$2" = -f && test "$4" = config
}
smite_install_panel_files ir.example.com 127.0.0.1 > "$TMP/panel.log"
test "$(stat -c %a "$SMITE_PANEL_DIR/.env")" = 600
grep -qx 'PANEL_HOST=127.0.0.1' "$SMITE_PANEL_DIR/.env"
grep -qx 'SMITE_NODE_REGISTRATION_MODE=signed' "$SMITE_PANEL_DIR/.env"
grep -qx 'SMITE_PANEL_AGENT_AUTH_MODE=signed' "$SMITE_PANEL_DIR/.env"
grep -qx 'SMITE_ENGINE_MANAGEMENT_MODE=managed' "$SMITE_PANEL_DIR/.env"
grep -qx 'SMITE_NODE_PAIRING_PREVIEW_ENABLED=false' "$SMITE_PANEL_DIR/.env"
! grep -Eq 'SMITE_NODE_REGISTRATION_MODE=legacy|SMITE_PANEL_AGENT_AUTH_MODE=legacy' "$SMITE_PANEL_DIR/.env"
grep -qx 'PANEL_RC_LEGACY_MACHINE_REGISTRATION=DISABLED' "$TMP/panel.log"

printf '%s\n' '-----BEGIN CERTIFICATE-----' 'FAKE' '-----END CERTIFICATE-----' > "$TMP/ca.pem"
smite_install_node_files node-ir iran 127.0.0.1:8000 "$TMP/ca.pem" "" "" standard > "$TMP/node.log"
test "$(stat -c %a "$SMITE_NODE_DIR/.env")" = 600
grep -qx 'SMITE_NODE_PANEL_AUTH_MODE=paused' "$SMITE_NODE_DIR/.env"
grep -qx 'SMITE_AGENT_AUTH_MODE=strict' "$SMITE_NODE_DIR/.env"
grep -qx 'SMITE_ENGINE_INVENTORY_MODE=managed' "$SMITE_NODE_DIR/.env"
grep -qx 'PANEL_ADDRESS=127.0.0.1:8000' "$SMITE_NODE_DIR/.env"
grep -qx 'NODE_RC_REGISTRATION=PAUSED_UNTIL_SIGNED_PAIRING' "$TMP/node.log"
grep -qx 'NODE_RC_PAIRING=PENDING_NO_OUTBOUND_REGISTRATION' "$TMP/node.log"
grep -qF '/healthz' "$SMITE_NODE_COMPOSE"
! grep -qF '/api/agent/status' "$SMITE_NODE_COMPOSE"

# Full Panel installer must NOT wait for an unsigned local IR Node to
# become active or preemptively write a guessed control address.
python3 - "$ROOT/modules/smite-install.sh" <<'PY'
from pathlib import Path
import sys
source=Path(sys.argv[1]).read_text()
section=source.split("smite_install_panel_iran() {",1)[1].split("\nsmite_install_foreign_node() {",1)[0]
assert 'IR_RC_PAIRING=PENDING_SIGNED_ADMIN_APPROVAL' in section
assert 'IR_RC_LEGACY_REGISTRATION_WAIT=SKIPPED' in section
assert 'IR_RC_CONTROL_ORIGIN=DEFERRED_UNTIL_SECURE_PAIRING' in section
assert 'elif ! smite_wait_node_registration_local "$node_name"; then' in section
assert 'if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then' in section
PY

# The Stable profile must retain original settings and original local
# Node healthcheck/registration, without any clean-RC security edits.
SMITE_INSTALL_PROFILE=stable
SMITE_PANEL_DIR="$TMP/stable/panel"
SMITE_NODE_DIR="$TMP/stable/node"
SMITE_PANEL_COMPOSE="$SMITE_PANEL_DIR/docker-compose.yml"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
SMITE_PANEL_IMAGE="$SMITE_PANEL_REPO@$SMITE_PANEL_DIGEST"
SMITE_NODE_IMAGE="$SMITE_NODE_REPO@$SMITE_NODE_DIGEST"
smite_install_panel_files ir.example.com 127.0.0.1 > "$TMP/stable-panel.log"
! grep -q '^SMITE_NODE_REGISTRATION_MODE=' "$SMITE_PANEL_DIR/.env"
! grep -q '^SMITE_PANEL_AGENT_AUTH_MODE=' "$SMITE_PANEL_DIR/.env"
! grep -q '^SMITE_ENGINE_MANAGEMENT_MODE=' "$SMITE_PANEL_DIR/.env"
# Stable is intentionally left on the original legacy source health route.
sed -i 's|127.0.0.1:${NODE_API_PORT:-8888}/healthz|localhost:${NODE_API_PORT:-8888}/api/agent/status|' "$TMP/node-upstream.yml"
smite_install_node_files node-ir iran 127.0.0.1:8000 "$TMP/ca.pem" "" "" standard > "$TMP/stable-node.log"
! grep -q '^SMITE_NODE_PANEL_AUTH_MODE=paused' "$SMITE_NODE_DIR/.env"
! grep -q '^SMITE_AGENT_AUTH_MODE=strict' "$SMITE_NODE_DIR/.env"
! grep -q '^SMITE_ENGINE_INVENTORY_MODE=' "$SMITE_NODE_DIR/.env"
grep -qF '/api/agent/status' "$SMITE_NODE_COMPOSE"
echo "IR_CLEAN_RC_SIGNED_PANEL_PAUSED_NODE_FAIL_CLOSED_TESTS=PASS"
