#!/usr/bin/env bash
# Exercise the *real* option-2 Foreign Gateway function, stopping at its
# confirmation boundary. Mock all mutating packages/certs/Nginx/Node ops.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

SMITE_STATE_DIR="$TMP/state"
SMITE_STATE_FILE="$SMITE_STATE_DIR/state.env"
SMITE_NODE_DIR="$TMP/node"
mkdir -m 0700 -p "$SMITE_STATE_DIR/staging" "$SMITE_NODE_DIR"
cat > "$SMITE_STATE_FILE" <<'EOF'
SMITE_ROLE=foreign
SMITE_MANAGED_VERSION=2.0.0-rc.7
SMITE_CONNECTION_MODE=standard
SMITE_PANEL_DOMAIN=iran.example.org
SMITE_FOREIGN_DOMAIN=kh.example.org
SMITE_NODE_NAME=node-kh
EOF
chmod 0600 "$SMITE_STATE_FILE"
PACKET="$SMITE_STATE_DIR/staging/foreign-install-packet.json"
python3 - "$PACKET" <<'PY'
import json,sys
p=dict(
 protocol="smi1",panel_url="https://iran.example.org:443",
 node_id="foreign-node-001",node_name="node-kh",
 origin="https://kh.example.org:443",
 control_url="https://kh.example.org:443/smite-node/"+"a"*32,
 installation_code="smi1_"+"B"*43,expires_at=1799999999)
with open(sys.argv[1],"w") as handle:
    json.dump(p,handle)
PY
chmod 0600 "$PACKET"

source "$ROOT/modules/smite-foreign-gateway.sh"
SMITE_SELECTED_FRESH=1
UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE="$PACKET"
clear() { :; }
id() { echo 0; }
sleep() { :; }
smite_foreign_gateway_require_node() { :; }
smite_foreign_gateway_require_rc_paused() { :; }
smite_foreign_gateway_site_path() { printf '%s\n' "$TMP/site"; }
smite_foreign_gateway_enabled_path() { printf '%s\n' "$TMP/enabled"; }
smite_foreign_gateway_resolve_panel_ipv4() { printf '1.1.1.1\n'; }
smite_foreign_gateway_ensure_packages() { echo BAD_PACKAGES >> "$TMP/mutations"; return 99; }
smite_foreign_gateway_ensure_certificate() { echo BAD_CERT >> "$TMP/mutations"; return 99; }
smite_foreign_gateway_write_site() { echo BAD_NGINX >> "$TMP/mutations"; return 99; }
smite_foreign_gateway_recreate_node() { echo BAD_NODE >> "$TMP/mutations"; return 99; }
smite_foreign_gateway_pause() { :; }

expect() {
    local expected="$1" marker="$2" output="" status=0
    smite_foreign_gateway_configure <<< $'\nN\n' > "$TMP/log" 2>&1 || status=$?
    if [ "$status" != "$expected" ]; then
        cat "$TMP/log"
        echo "FAIL: expected $expected, got $status"
        exit 1
    fi
    if [ "$marker" = yes ]; then
        grep -qx 'UNIFIED_FOREIGN_GATEWAY_PATH=VERIFIED_PANEL_SCOPE' "$TMP/log"
    else
        ! grep -q 'UNIFIED_FOREIGN_GATEWAY_PATH=VERIFIED_PANEL_SCOPE' "$TMP/log"
    fi
    [ ! -e "$TMP/mutations" ]
    ! grep -q 'smi1_B' "$TMP/log"
}
# Valid scope, then user cancels before any file/SSL write. Must be failure.
expect 2 yes

# A canceled or mismatched Panel credential never chooses a random path.
python3 - "$PACKET" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
p["control_url"]="https://kh.example.org:443/smite-node/"+"e"*16
with open(sys.argv[1],"w") as handle:json.dump(p,handle)
PY
chmod 0600 "$PACKET"
expect 2 no

# A foreign IP / transport mismatch cannot silently bypass validation.
sed -i 's/SMITE_CONNECTION_MODE=standard/SMITE_CONNECTION_MODE=private/' "$SMITE_STATE_FILE"
expect 2 no

# Never use the trial packet in an existing/non-owned Node install.
sed -i 's/SMITE_CONNECTION_MODE=private/SMITE_CONNECTION_MODE=standard/' "$SMITE_STATE_FILE"
SMITE_SELECTED_FRESH=0
expect 2 no

echo 'UNIFIED_GATEWAY_OPTION_TWO_PREWRITE_ADMISSION=PASS (4 scenarios)'
