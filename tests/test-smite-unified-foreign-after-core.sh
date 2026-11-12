#!/usr/bin/env bash
# One-choice Foreign option-2 post-core choreography, offline only.
# No Docker, network, TLS, certificate issuance, Nginx or host writes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SMITE_STATE_DIR="$TMP/state"
SMITE_STATE_FILE="$SMITE_STATE_DIR/state.env"
SMITE_NODE_DIR="$TMP/node"
mkdir -p "$SMITE_STATE_DIR/staging" "$SMITE_NODE_DIR"
chmod 0700 "$SMITE_STATE_DIR" "$SMITE_STATE_DIR/staging"
cat > "$SMITE_STATE_FILE" <<'STATE'
SMITE_ROLE=foreign
SMITE_MANAGED_VERSION=2.0.0-rc.7
SMITE_CONNECTION_MODE=standard
SMITE_PANEL_DOMAIN=iran.example.org
SMITE_FOREIGN_DOMAIN=kh.example.org
SMITE_NODE_NAME=node-kh
STATE
chmod 0600 "$SMITE_STATE_FILE"
PACKET="$SMITE_STATE_DIR/staging/foreign-install-packet.json"
python3 - "$PACKET" <<'PY'
import json,sys
packet={
  "protocol":"smi1",
  "panel_url":"https://iran.example.org:443",
  "node_id":"foreign-node-0001",
  "node_name":"node-kh",
  "origin":"https://kh.example.org:443",
  "control_url":"https://kh.example.org:443/smite-node/"+"a"*32,
  "installation_code":"smi1_"+"B"*43,
  "expires_at":1799999999,
}
with open(sys.argv[1],"w") as handle:json.dump(packet,handle)
PY
chmod 0600 "$PACKET"

source "$ROOT/modules/smite-install.sh"
source "$ROOT/modules/smite-foreign-gateway.sh"

SMITE_INSTALL_PROFILE=clean-rc
SMITE_SELECTED_FRESH=1
MODE=ok
calls=()
smite_install_unified_signed_pair_review() {
    calls+=(signed)
    [ "$MODE" != bad_signature ]
}
NODE_ID="sha256:$(printf 'd%.0s' {1..64})"
docker() {
    case "$*" in
        'inspect -f {{.Config.Image}} smite-node')
            if [ "$MODE" = wrong_image ]; then
                echo 'ghcr.io/aghajani82/smite-node:latest'
            else
                echo 'ghcr.io/aghajani82/smite-node@sha256:587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483'
            fi
            ;;
        'inspect -f {{.Image}} smite-node')
            if [ "$MODE" = wrong_runtime_id ]; then
                printf 'sha256:%064d\n' 0
            else
                printf '%s\n' "$NODE_ID"
            fi
            ;;
        'image inspect -f {{.Id}} ghcr.io/aghajani82/smite-node@sha256:587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483')
            printf '%s\n' "$NODE_ID"
            ;;
        *) return 99 ;;
    esac
}
smite_foreign_gateway_require_rc_paused() {
    calls+=(paused)
    [ "$MODE" != bad_paused ]
}
smite_foreign_gateway_rc7_compose() {
    calls+=(compose)
    [ "$*" = 'config --quiet' ] && [ "$MODE" != bad_compose ]
}
smite_install_unified_foreign_sanaei() {
    calls+=(sanaei)
    [ "$MODE" != failed_sanaei ]
}
smite_foreign_gateway_configure() {
    calls+=(gateway)
    [ "$UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE" = "$PACKET" ] || return 2
    if [ "$MODE" = failed_gateway ]; then
        return 2
    fi
    local exact="/smite-node/$(printf 'a%.0s' {1..32})"
    if [ "$MODE" = wrong_persisted_path ]; then exact="/smite-node/$(printf 'b%.0s' {1..32})"; fi
    cat > "$SMITE_STATE_DIR/foreign-gateway.env" <<ENV
SMITE_FOREIGN_GATEWAY_DOMAIN=kh.example.org
SMITE_FOREIGN_PANEL_DOMAIN=iran.example.org
SMITE_FOREIGN_CONTROL_PATH=$exact
SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443
SMITE_FOREIGN_GATEWAY_MODE=https-control-path
ENV
    chmod 0600 "$SMITE_STATE_DIR/foreign-gateway.env"
}

run() {
    local expected="$1" stages="$2" result=0 actual
    calls=()
    rm -f "$SMITE_STATE_DIR/foreign-gateway.env"
    smite_install_unified_foreign_after_core "$PACKET" > "$TMP/output" 2>&1 || result=$?
    actual="$(IFS=,; echo "${calls[*]-}")"
    if [ "$result" != "$expected" ] || [ "$actual" != "$stages" ]; then
        cat "$TMP/output"
        echo "FAIL: $MODE result=$result expected=$expected events=$actual expected_events=$stages"
        exit 1
    fi
    if [ "$result" = 0 ]; then
        grep -qx 'UNIFIED_FOREIGN_SANAEI_GATEWAY=PREPARED_FOR_SIGNED_ENROLLMENT' "$TMP/output"
        grep -qx 'UNIFIED_FOREIGN_CONNECTED=NOT_YET_VERIFIED' "$TMP/output"
    else
        ! grep -q 'UNIFIED_FOREIGN_SANAEI_GATEWAY=PREPARED_FOR_SIGNED_ENROLLMENT' "$TMP/output"
    fi
    ! grep -q 'smi1_B' "$TMP/output"
    ! grep -q 'PANEL_AND_IR_INSTALL=COMPLETE' "$TMP/output"
}

run 0 signed,paused,compose,sanaei,gateway
MODE=bad_signature; run 2 signed
MODE=wrong_image; run 2 signed
MODE=wrong_runtime_id; run 2 signed
MODE=bad_paused; run 2 signed,paused
MODE=bad_compose; run 2 signed,paused,compose
MODE=failed_sanaei; run 2 signed,paused,compose,sanaei
MODE=failed_gateway; run 2 signed,paused,compose,sanaei,gateway
MODE=wrong_persisted_path; run 2 signed,paused,compose,sanaei,gateway

MODE=ok
SMITE_SELECTED_FRESH=0
run 2 ""
SMITE_SELECTED_FRESH=1
SMITE_INSTALL_PROFILE=stable
run 2 ""
SMITE_INSTALL_PROFILE=clean-rc
sed -i 's/SMITE_ROLE=foreign/SMITE_ROLE=iran/' "$SMITE_STATE_FILE"
run 2 ""
sed -i 's/SMITE_ROLE=iran/SMITE_ROLE=foreign/' "$SMITE_STATE_FILE"

# An exact nonmatching host/domain must HOLD BEFORE any Sanaei/Gateway calls.
sed -i 's/SMITE_FOREIGN_DOMAIN=kh.example.org/SMITE_FOREIGN_DOMAIN=other.example.org/' "$SMITE_STATE_FILE"
run 2 signed,paused,compose
sed -i 's/SMITE_FOREIGN_DOMAIN=other.example.org/SMITE_FOREIGN_DOMAIN=kh.example.org/' "$SMITE_STATE_FILE"

# An interrupted/missing ephemeral grant packet cannot be silently rebuilt.
mv "$PACKET" "$PACKET.unavailable"
run 2 signed,paused,compose
mv "$PACKET.unavailable" "$PACKET"

# The selected Foreign core must return control to this SAME option, never
# display a completed installation or claim Connected while enrollment is HOLD.
python3 - "$ROOT/modules/smite-install.sh" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1]).read_text()
core=src.split('smite_install_foreign_node() {',1)[1].split(
    '\nsmite_install_sanaei_foreign() {',1)[0]
assert 'FOREIGN_CORE=READY_PAUSED_FOR_UNIFIED_CONTINUATION' in core
assert core.index('FOREIGN_CORE=READY_PAUSED_FOR_UNIFIED_CONTINUATION') < core.index(
    'Foreign Node Install Complete')
assert 'FOREIGN_CONNECTED=NOT_PROVEN' in core
selected=src.split('smite_install_selected_fresh() (',1)[1].split(
    '\nsmite_install_finish_local_ir() {',1)[0]
assert 'FOREIGN_ONE_CHOICE_INSTALL=INCOMPLETE_RETAIN_CORE' in selected
assert "echo 'FOREIGN_CONNECTED=NOT_PROVEN'" in selected
assert 'return 2' in selected.split('FOREIGN_ONE_CHOICE_INSTALL=INCOMPLETE_RETAIN_CORE',1)[1]
assert 'smite_install_finish_local_ir || return 2' in selected
PY

# No publicly-selected fresh Option-2 entry may use this incomplete phase
# sequence until the signed trial runtime activation has been reviewed.
python3 - "$ROOT/modules/smite-install.sh" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1]).read_text()
start=src.index('smite_install_selected_fresh() (')
end=src.index('\nsmite_install_finish_local_ir() {',start)
assert 'smite_install_unified_foreign_after_core' not in src[start:end]
assert 'smite_install_foreign_node || return 2' in src[start:end]
assert 'smite_install_finish_local_ir || return 2' in src[start:end]
PY

echo 'UNIFIED_FOREIGN_POST_CORE_CHOREOGRAPHY=PASS (14 scenarios)'
