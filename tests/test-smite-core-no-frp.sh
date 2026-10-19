#!/usr/bin/env bash
# Phase 1: the experimental Smite Core must install on IR and KH without
# downloading, mounting, verifying or starting host FRP. Stable unchanged.
# Disposable files and mocked Docker; no server, network, or real binaries.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lab="$(mktemp -d)"
trap 'rm -rf -- "$lab"' EXIT
export SMITE_INSTALL_PROFILE=clean-rc
source "$root/modules/smite-install.sh"
SMITE_PANEL_IMAGE="smite-panel:stage15-local"
SMITE_NODE_IMAGE="smite-node:stage15-local"
SMITE_FRP_BIN_DIR="$lab/nonexistent-frp"
SMITE_PANEL_DIR="$lab/ir/panel"
SMITE_PANEL_COMPOSE="$SMITE_PANEL_DIR/docker-compose.yml"
SMITE_NODE_DIR="$lab/ir/node"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
cat > "$lab/panel.yml" <<'EOF_PANEL'
services:
  smite-panel:
    image: ghcr.io/zzedix/smite-panel:${SMITE_VERSION:-latest}
    volumes:
      - ./panel/data:/app/data
EOF_PANEL
cat > "$lab/node.yml" <<'EOF_NODE'
services:
  smite-node:
    image: ghcr.io/zzedix/smite-node:${SMITE_VERSION:-latest}
    container_name: smite-node
    network_mode: host
    volumes:
      - ./certs:/etc/smite-node/certs:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${NODE_API_PORT:-8888}/healthz')"]
EOF_NODE
smite_download_upstream() {
  case "$1" in
    docker-compose.yml) cp "$lab/panel.yml" "$2" ;;
    node/docker-compose.yml) cp "$lab/node.yml" "$2" ;;
    *) return 1 ;;
  esac
}
docker() {
  [ "$1" = compose ] && [ "$2" = -f ] && [ "$4" = config ]
}
printf '0\n' > "$lab/prepares"
printf '0\n' > "$lab/mounts"
printf '0\n' > "$lab/verifies"
bump() { echo $(( $(cat "$1") + 1 )) > "$1"; }
smite_frp_prepare_binaries() {
  bump "$lab/prepares"
  return 0
}
smite_frp_mount_compose() {
  bump "$lab/mounts"
  local file="$1" service="$2"
  # A visible marker simulates Stable FRP bind mounts.
  printf '    # STABLE_FRP_MOUNT=%s\n' "$service" >> "$file"
}
smite_frp_verify_container() {
  bump "$lab/verifies"
  return 0
}
assert_calls() {
  [ "$(cat "$lab/prepares")" = "$1" ]
  [ "$(cat "$lab/mounts")" = "$2" ]
  [ "$(cat "$lab/verifies")" = "$3" ]
}

# No prepared FRP directory is present or created. Both core roles must
# still produce safe, valid local config with no FRP mounts.
# The clean IR path currently preserves a local, loopback-fetched CA
# for backward compatibility. This fixture emulates that CA; it is NOT
# FRP and does not authorize legacy machine registration.
printf '%s\n' '-----BEGIN CERTIFICATE-----' 'TEST' '-----END CERTIFICATE-----' > "$lab/fake-ca.crt"
smite_install_panel_files ir.example.org 127.0.0.1 > "$lab/panel.log"
smite_install_node_files node-ir iran 127.0.0.1:8000 "$lab/fake-ca.crt" "" "" standard > "$lab/ir.log"
assert_calls 0 0 0
smite_install_core_optional_frp_verify smite-panel > "$lab/ir-verify.log"
smite_install_core_optional_frp_verify smite-node >> "$lab/ir-verify.log"
assert_calls 0 0 0
[ ! -e "$SMITE_FRP_BIN_DIR" ]
[ -s "$SMITE_NODE_DIR/certs/ca.crt" ]
# Local IR CA compatibility is separate from FRP, and will be reviewed
# in a later Core minimization step. KH remains CA-free until pairing.
grep -Fq "SMITE_CORE_FRP_HOST_INSTALL=SKIPPED" "$lab/panel.log"
grep -Fq "SMITE_CORE_FRP_HOST_INSTALL=SKIPPED" "$lab/ir.log"
grep -Fq "SMITE_CORE_FRP_VERSION_CHECK=NOT_REQUIRED" "$lab/ir-verify.log"
! grep -Fq "STABLE_FRP_MOUNT" "$SMITE_PANEL_COMPOSE"
! grep -Fq "STABLE_FRP_MOUNT" "$SMITE_NODE_COMPOSE"
! grep -Eq '/usr/local/bin/frp(c|s):ro' "$SMITE_NODE_COMPOSE"
grep -qx 'SMITE_NODE_PANEL_AUTH_MODE=paused' "$SMITE_NODE_DIR/.env"
grep -qx 'SMITE_AGENT_AUTH_MODE=strict' "$SMITE_NODE_DIR/.env"
grep -qx 'SMITE_ENGINE_INVENTORY_MODE=managed' "$SMITE_NODE_DIR/.env"
grep -qx 'SMITE_NODE_REGISTRATION_MODE=signed' "$SMITE_PANEL_DIR/.env"
grep -qx 'SMITE_PANEL_AGENT_AUTH_MODE=signed' "$SMITE_PANEL_DIR/.env"
grep -qx 'SMITE_ENGINE_MANAGEMENT_MODE=managed' "$SMITE_PANEL_DIR/.env"

SMITE_NODE_DIR="$lab/kh/node"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
smite_install_node_files node-kh foreign ir.example.org:443 "" "" "" standard > "$lab/kh.log"
smite_install_core_optional_frp_verify smite-node > /dev/null
assert_calls 0 0 0
[ ! -e "$SMITE_FRP_BIN_DIR" ]
! grep -Fq "STABLE_FRP_MOUNT" "$SMITE_NODE_COMPOSE"
grep -qx 'SMITE_NODE_PANEL_AUTH_MODE=paused' "$SMITE_NODE_DIR/.env"
grep -qx 'SMITE_AGENT_AUTH_MODE=strict' "$SMITE_NODE_DIR/.env"
grep -qx 'SMITE_ENGINE_INVENTORY_MODE=managed' "$SMITE_NODE_DIR/.env"
[ ! -e "$SMITE_NODE_DIR/certs/ca.crt" ]
echo "PHASE1_IR_KH_CORE_NO_HOST_FRP=PASS"

# Stable must STILL call the original FRP preparation, mounts and
# version checks. Do not inadvertently change existing installations.
SMITE_INSTALL_PROFILE=stable
SMITE_PANEL_IMAGE="$SMITE_PANEL_REPO@$SMITE_PANEL_DIGEST"
SMITE_NODE_IMAGE="$SMITE_NODE_REPO@$SMITE_NODE_DIGEST"
SMITE_PANEL_DIR="$lab/stable/panel"
SMITE_PANEL_COMPOSE="$SMITE_PANEL_DIR/docker-compose.yml"
SMITE_NODE_DIR="$lab/stable/node"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
smite_install_panel_files ir.example.org 127.0.0.1 > /dev/null
smite_install_node_files node-ir iran 127.0.0.1:8000 "$lab/fake-ca.crt" "" "" standard > /dev/null
assert_calls 2 2 0
smite_install_core_optional_frp_verify smite-panel > /dev/null
smite_install_core_optional_frp_verify smite-node > /dev/null
assert_calls 2 2 2
grep -Fq "STABLE_FRP_MOUNT=smite-panel" "$SMITE_PANEL_COMPOSE"
grep -Fq "STABLE_FRP_MOUNT=smite-node" "$SMITE_NODE_COMPOSE"
[ -e "$SMITE_NODE_DIR/certs/ca.crt" ]
! grep -q '^SMITE_ENGINE_INVENTORY_MODE=' "$SMITE_NODE_DIR/.env"
! grep -q '^SMITE_ENGINE_MANAGEMENT_MODE=' "$SMITE_PANEL_DIR/.env"
echo "PHASE1_STABLE_FRP_PATH_UNCHANGED=PASS"

# Unknown profiles fail closed before installing or verifying engines.
SMITE_INSTALL_PROFILE=unapproved
if smite_install_core_optional_frp_prepare "$SMITE_NODE_COMPOSE" smite-node >/dev/null 2>&1; then
  echo "HOLD: unknown profile installed optional FRP" >&2; exit 1
fi
if smite_install_core_optional_frp_verify smite-node >/dev/null 2>&1; then
  echo "HOLD: unknown profile bypassed engine verification" >&2; exit 1
fi
assert_calls 2 2 2
echo "PHASE1_UNKNOWN_PROFILE_DENIED=PASS"
