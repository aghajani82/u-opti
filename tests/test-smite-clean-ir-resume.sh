#!/usr/bin/env bash
# Offline regression for the explicit recovery of the interrupted clean-RC IR
# install. Only temporary files are touched; Docker/systemd are mocked.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
grep -Fq 'local bundle="${SMITE_RC_BUNDLE_DIR:-/opt/smite-stage15-bundle}"' "$ROOT/modules/smite-clean-ir-resume.sh"
grep -Fq 'local manifest_sha="${SMITE_RC_MANIFEST_SHA256:-fe32c9c54714cfdb482f27112829eba13d5188e9e1e7e26c7266d8d54e85462a}"' "$ROOT/modules/smite-clean-ir-resume.sh"
grep -Fq 'local source_sha="${SMITE_RC_SOURCE_SHA:-4e16633a304db6c03f7f2911cc7d77213b0c4ec1}"' "$ROOT/modules/smite-clean-ir-resume.sh"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT

export SMITE_INSTALL_PROFILE=stable
export SMITE_RC_BUNDLE_DIR="$TMP/bundle"
export SMITE_RC_SOURCE_SHA="da1c08896508a5c9b3d7601d2943575b90f5c223"
mkdir -p "$SMITE_RC_BUNDLE_DIR" "$TMP/ir/panel" "$TMP/ir/node" "$TMP/state"
PANEL_ID="sha256:$(printf '1%.0s' {1..64})"
NODE_ID="sha256:$(printf '2%.0s' {1..64})"
cat > "$SMITE_RC_BUNDLE_DIR/stage15-images.json" <<EOF
{"images":{"panel":{"local_image_id":"$PANEL_ID"},"node":{"local_image_id":"$NODE_ID"}}}
EOF
export SMITE_RC_MANIFEST_SHA256="$(sha256sum "$SMITE_RC_BUNDLE_DIR/stage15-images.json" | cut -d' ' -f1)"

cat > "$TMP/ir/panel/.env" <<'EOF_PANEL_ENV'
PANEL_PORT=8000
PANEL_HOST=127.0.0.1
PANEL_DOMAIN=ir.kolbe1.ir
SMITE_VERSION=2.0.0-rc.1
SECRET_KEY=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
SMITE_NODE_REGISTRATION_MODE=signed
SMITE_PANEL_AGENT_AUTH_MODE=signed
SMITE_NODE_PAIRING_PREVIEW_ENABLED=false
SMITE_ENGINE_MANAGEMENT_MODE=managed
EOF_PANEL_ENV
cat > "$TMP/ir/node/.env" <<'EOF_NODE_ENV'
NODE_API_PORT=8888
NODE_NAME=node-ir
NODE_ROLE=iran
SMITE_VERSION=2.0.0-rc.1
PANEL_ADDRESS=127.0.0.1:8000
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
SMITE_UOPTI_BROKER_GID=39100
SMITE_UOPTI_ROUTE_BROKER_ENABLED=false
SMITE_UOPTI_ROUTE_BROKER_SOCKET=/run/u-opti/smite/xhttp-broker.sock
EOF_NODE_ENV
chmod 0600 "$TMP/ir/panel/.env" "$TMP/ir/node/.env"
cat > "$TMP/ir/panel/docker-compose.yml" <<'EOF_PANEL_COMPOSE'
services:
  smite-panel:
    image: smite-panel:stage15-local
    volumes:
      - ./docker-compose.yml:/app/config/docker-compose.yml:ro
EOF_PANEL_COMPOSE
cat > "$TMP/ir/node/docker-compose.yml" <<'EOF_NODE_COMPOSE'
services:
  smite-node:
    image: smite-node:stage15-local
    container_name: smite-node
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
EOF_NODE_COMPOSE
chmod 0644 "$TMP/ir/panel/docker-compose.yml" "$TMP/ir/node/docker-compose.yml"

source "$ROOT/modules/smite-install.sh"
source "$ROOT/modules/smite-clean-ir-resume.sh"
smite_gateway_ensure_packages() { return 0; }
smite_install_clean_rc_nginx_paths_ready() { return 0; }
SMITE_PANEL_DIR="$TMP/ir/panel"
SMITE_NODE_DIR="$TMP/ir/node"
SMITE_PANEL_COMPOSE="$SMITE_PANEL_DIR/docker-compose.yml"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
SMITE_STATE_DIR="$TMP/state"
SMITE_STATE_FILE="$SMITE_STATE_DIR/state.env"
SMITE_OVERLAY_DIR="$TMP/overlay"
node_exists=0
node_broker_starts=0
admin_created=0

hostname() { echo ir; }
clear() { :; }
smite_install_pause() { :; }
smite_container_exists() {
  case "$1" in smite-panel) return 0 ;; smite-node) [ "$node_exists" = 1 ] ;; *) return 1 ;; esac
}
smite_container_running() { smite_container_exists "$1"; }
smite_wait_healthy() { smite_container_exists "$1"; }
curl() { return 0; }
python3() {
  if [[ " $* " == *"smite-clean-image-pair.py"* ]]; then
    printf 'CLEAN_RC_PAIR=ARCHIVES_VERIFIED\n'
    return 0
  fi
  command python3 "$@"
}
docker() {
  case "$1" in
    inspect)
      if [[ "$*" == *"smite-panel"* ]]; then echo smite-panel:stage15-local
      elif [[ "$*" == *"smite-node"* ]]; then echo smite-node:stage15-local
      else return 1; fi
      ;;
    image)
      if [[ "$*" == *"smite-panel:stage15-local"* ]]; then echo "$PANEL_ID"
      elif [[ "$*" == *"smite-node:stage15-local"* ]]; then echo "$NODE_ID"
      else return 1; fi
      ;;
    compose)
      if [[ "$*" == *" config"* ]]; then return 0
      elif [[ "$*" == *" up "* ]]; then node_exists=1; return 0
      fi
      ;;
    exec) return 0 ;;
    *) echo "Unexpected docker call: $*" >&2; return 1 ;;
  esac
}
smite_install_create_admin() { admin_created=1; }
smite_install_clean_rc_broker_start_node_forwarding() {
  node_broker_starts=$((node_broker_starts + 1))
  sed -i 's/^SMITE_UOPTI_ROUTE_BROKER_ENABLED=false$/SMITE_UOPTI_ROUTE_BROKER_ENABLED=true/' "$SMITE_NODE_DIR/.env"
}

# Wrong auth mode is rejected before confirmation or host mutation.
sed -i 's/^SMITE_AGENT_AUTH_MODE=strict$/SMITE_AGENT_AUTH_MODE=legacy/' "$SMITE_NODE_DIR/.env"
answer=""
smite_install_resume_clean_ir >"$TMP/reject.log" 2>&1
grep -q 'Partial-install files do not match' "$TMP/reject.log"
[ "$node_exists" = 0 ] && [ "$node_broker_starts" = 0 ] && [ ! -e "$SMITE_STATE_FILE" ]
sed -i 's/^SMITE_AGENT_AUTH_MODE=legacy$/SMITE_AGENT_AUTH_MODE=strict/' "$SMITE_NODE_DIR/.env"

# Exact interrupted state resumes only after the explicit phrase.
read() {
  if [[ "$*" == *"Type RESUME-CLEAN-IR-FIELD-TRIAL"* ]]; then
    answer="RESUME-CLEAN-IR-FIELD-TRIAL"
  elif [[ "$*" == *"Install/enable the host gateway packages now?"* ]]; then
    confirm="y"
  fi
  return 0
}
smite_install_resume_clean_ir >"$TMP/resume.log" 2>&1
# Verify the exact success markers. The original tail was accidentally
# duplicated with unterminated shell quoting, so bash -n missed runtime expansion.
grep -qx 'PANEL_ADMIN_ACCOUNT=CREATED' "$TMP/resume.log"
grep -qx 'CLEAN_RC_IR_RESUME=PASS' "$TMP/resume.log"
grep -qx 'IR_RC_PAIRING=PENDING_SIGNED_ADMIN_APPROVAL' "$TMP/resume.log"
grep -qx 'TRUSTED_GRANTS=NONE' "$TMP/resume.log"
grep -qx 'LIVE_ROUTE_CHANGE=NO' "$TMP/resume.log"
[ "$node_exists" = 1 ] && [ "$node_broker_starts" = 1 ] && [ "$admin_created" = 1 ]
grep -qx 'SMITE_ROLE=panel-iran' "$SMITE_STATE_FILE"
grep -qx 'SMITE_NODE_NAME=node-ir' "$SMITE_STATE_FILE"
grep -qx 'SMITE_MANAGED_VERSION=2.0.0-rc.1' "$SMITE_STATE_FILE"
grep -Fq 'user: "0:${SMITE_UOPTI_BROKER_GID:-0}"' "$SMITE_NODE_COMPOSE"
grep -Fq -- '- /run/u-opti/smite:/run/u-opti/smite:ro' "$SMITE_NODE_COMPOSE"
grep -Fq 'source "$SMITE_BH_DIR/smite-clean-ir-resume.sh"' "$ROOT/modules/smite-backhaul-management.sh"
grep -Fq 'read -rp "Press Enter to return..."' "$ROOT/modules/smite-backhaul-management.sh"
grep -Fq '|| "$FILE" = "smite-clean-ir-resume.sh"' "$ROOT/u-opti"
echo 'SMITE_CLEAN_IR_EXPLICIT_RESUME_AND_FAIL_CLOSED_TESTS=PASS'
