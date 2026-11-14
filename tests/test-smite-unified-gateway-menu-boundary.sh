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
chmod 0700 "$SMITE_STATE_DIR"
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
CLEAR_CALLS=0
clear() { CLEAR_CALLS=$((CLEAR_CALLS + 1)); }
id() { echo 0; }
sleep() { :; }
smite_foreign_gateway_require_node() { :; }
smite_foreign_gateway_require_rc_paused() { :; }
smite_foreign_gateway_site_path() { printf '%s\n' "$TMP/site"; }
smite_foreign_gateway_enabled_path() { printf '%s\n' "$TMP/enabled"; }
smite_foreign_gateway_resolve_panel_ipv4() { printf '1.1.1.1\n'; }
smite_foreign_gateway_ensure_packages() { echo PACKAGE_PREP_REACHED >> "$TMP/mutations"; return 99; }
smite_foreign_gateway_ensure_certificate() { echo BAD_CERT >> "$TMP/mutations"; return 99; }
smite_foreign_gateway_write_site() { echo BAD_NGINX >> "$TMP/mutations"; return 99; }
smite_foreign_gateway_recreate_node() { echo BAD_NODE >> "$TMP/mutations"; return 99; }
smite_foreign_gateway_pause() { :; }

expect() {
    local expected="$1" marker="$2" package_reached="$3" input="${4:-}" status=0
    rm -f -- "$TMP/mutations"
    CLEAR_CALLS=0
    if [ -n "$input" ]; then
        smite_foreign_gateway_configure <<< "$input" > "$TMP/log" 2>&1 || status=$?
    else
        smite_foreign_gateway_configure <<< $'\nN\n' > "$TMP/log" 2>&1 || status=$?
    fi
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
    if [ "$package_reached" = yes ]; then
        # The already-confirmed option-2 installation reaches the SAME
        # existing Gateway function's packages stage without a second Y/N.
        [ "$(cat "$TMP/mutations")" = PACKAGE_PREP_REACHED ]
        grep -qx 'UNIFIED_FOREIGN_GATEWAY=CONTINUING_APPROVED_FRESH_INSTALL' "$TMP/log"
    else
        [ ! -e "$TMP/mutations" ]
        ! grep -q 'UNIFIED_FOREIGN_GATEWAY=CONTINUING_APPROVED_FRESH_INSTALL' "$TMP/log"
    fi
    if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        [ "$CLEAR_CALLS" -eq 0 ] || { echo "FAIL: inline Gateway erased install progress"; exit 1; }
    else
        [ "$CLEAR_CALLS" -eq 1 ] || { echo "FAIL: independent Gateway menu clear changed"; exit 1; }
    fi
    ! grep -q 'smi1_B' "$TMP/log"
    ! grep -q 'FOREIGN_RC_GATEWAY_TRANSPORT=READY_ROOT_ONLY' "$TMP/log"
}
# An explicitly selected fresh option 2 with a valid signed packet reaches
# the EXISTING Gateway installer without an extra second confirmation.
# The package mock fails before it can make a host change.
expect 2 yes yes

# Wrong Panel-issued path is refused before any installation action.
python3 - "$PACKET" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
p["control_url"]="https://kh.example.org:443/smite-node/"+"e"*16
with open(sys.argv[1],"w") as handle:json.dump(p,handle)
PY
chmod 0600 "$PACKET"
expect 2 no no

# Private transport and unowned/existing Node are never admitted.
sed -i 's/SMITE_CONNECTION_MODE=standard/SMITE_CONNECTION_MODE=private/' "$SMITE_STATE_FILE"
expect 2 no no
sed -i 's/SMITE_CONNECTION_MODE=private/SMITE_CONNECTION_MODE=standard/' "$SMITE_STATE_FILE"
SMITE_SELECTED_FRESH=0
expect 2 no no

# Repair the fixture packet and verify the source IPv4 validation still runs
# BEFORE the unified flow can even reach the package/SSL stage.
SMITE_SELECTED_FRESH=1
python3 - "$PACKET" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
p["control_url"]="https://kh.example.org:443/smite-node/"+"a"*32
with open(sys.argv[1],"w") as handle:json.dump(p,handle)
PY
chmod 0600 "$PACKET"
expect 2 yes no 'not-an-ip'

# An independent Gateway repair still has its own Y/N confirmation.
# It cannot inherit the option-2 install approval.
UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE=
expect 2 no no


# The earlier prewrite boundary deliberately mocked the recreate
# function to detect unexpected mutation. Restore the REAL existing
# gateway functions for the following retained-Node verification.
source "$ROOT/modules/smite-foreign-gateway.sh"
# Verify the REAL RC7 gateway runtime function retains the already
# prebound, healthy paused Node during selected one-choice installation.
# Independent option-6 repair keeps its existing recreation behavior.
SMITE_NODE_DIR="$TMP/node"
mkdir -p "$SMITE_NODE_DIR"
CONTROL_URL="https://kh.example.org:443/smite-node/$(printf 'a%.0s' {1..32})"
cat > "$SMITE_NODE_DIR/.env" <<EOF
SMITE_CONTROL_ADDRESS=$CONTROL_URL
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
EOF
RUNTIME_URL="$CONTROL_URL"
RUNTIME_DUPLICATE=0
docker() {
    [ "$*" = 'inspect -f {{range .Config.Env}}{{println .}}{{end}} smite-node' ] || return 99
    printf 'SMITE_CONTROL_ADDRESS=%s\n' "$RUNTIME_URL"
    if [ "$RUNTIME_DUPLICATE" = 1 ]; then
        printf 'SMITE_CONTROL_ADDRESS=%s\n' "$RUNTIME_URL"
    fi
    printf 'SMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_AGENT_AUTH_MODE=strict\nSMITE_ENGINE_INVENTORY_MODE=managed\n'
}
: > "$TMP/compose-calls"
smite_foreign_gateway_rc7_compose() {
    printf '%s\n' "$*" >> "$TMP/compose-calls"
    return 0
}
smite_foreign_gateway_wait_healthy() { return 0; }
SMITE_SELECTED_FRESH=1
UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE="$PACKET"
status=0
smite_foreign_gateway_recreate_node > "$TMP/retain.log" 2>&1 || status=$?
[ "$status" = 0 ]
grep -qx 'UNIFIED_FOREIGN_GATEWAY_NODE=RETAINED_NO_RECREATE' "$TMP/retain.log"
[ "$(cat "$TMP/compose-calls")" = 'config --quiet' ]
# Actual runtime mismatch or duplicate must HOLD without Compose restart.
for RUNTIME_URL in "https://wrong.example.org:443/smite-node/$(printf 'b%.0s' {1..32})" "$CONTROL_URL"; do
    [ "$RUNTIME_URL" = "$CONTROL_URL" ] && RUNTIME_DUPLICATE=1
    : > "$TMP/compose-calls"
    status=0
    smite_foreign_gateway_recreate_node > "$TMP/drift.log" 2>&1 || status=$?
    [ "$status" -eq 2 ]
    [ "$(cat "$TMP/compose-calls")" = 'config --quiet' ]
    ! grep -q 'UNIFIED_FOREIGN_GATEWAY_NODE=RETAINED' "$TMP/drift.log"
done
RUNTIME_DUPLICATE=0
RUNTIME_URL="$CONTROL_URL"
# The same existing setter should not rewrite a correct env under option 2.
before="$(sha256sum "$SMITE_NODE_DIR/.env" | cut -d' ' -f1)"
smite_foreign_gateway_set_node_control_address "$CONTROL_URL" "$TMP/env-backup" > "$TMP/env-log"
[ "$(sha256sum "$SMITE_NODE_DIR/.env" | cut -d' ' -f1)" = "$before" ]
grep -q 'UNIFIED_FOREIGN_CONTROL_ADDRESS=PREBOUND_UNCHANGED' "$TMP/env-log"
status=0
smite_foreign_gateway_set_node_control_address 'https://other.example.org:443/smite-node/no' "$TMP/env-mismatch" > "$TMP/set-failure" 2>&1 || status=$?
[ "$status" = 2 ]
[ "$(sha256sum "$SMITE_NODE_DIR/.env" | cut -d' ' -f1)" = "$before" ]
# Standalone Gateway keeps its established recreate step.
UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE=
: > "$TMP/compose-calls"
smite_foreign_gateway_recreate_node > "$TMP/standalone-recreate.log"
grep -q -- '--force-recreate smite-node' "$TMP/compose-calls"

echo 'UNIFIED_GATEWAY_OPTION_TWO_PREWRITE_ADMISSION=PASS (6 scenarios + no-recreate witness)'

# Run the selected Gateway through the real write and compensation boundary.
# Only Gateway files in the fixture may change.
UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE="$PACKET"
smite_foreign_gateway_require_node() { :; }
smite_foreign_gateway_require_rc_paused() { :; }
smite_foreign_gateway_site_path() { printf '%s\n' "$TMP/site"; }
smite_foreign_gateway_enabled_path() { printf '%s\n' "$TMP/enabled"; }
smite_foreign_gateway_resolve_panel_ipv4() { printf '1.1.1.1\n'; }
smite_foreign_gateway_ensure_packages() { :; }
smite_foreign_gateway_ensure_certificate() { :; }
mkdir() {
    if [[ "$*" == *"/etc/nginx/sites-available"* ]]; then return 0; fi
    command mkdir "$@"
}
smite_foreign_gateway_write_site() {
    printf 'candidate vhost\n' > "$4"
}
nginx() { [ "$*" = "-t" ]; }
systemctl() {
    [ "$*" = "reload nginx" ] || return 1
    if [ "$FAULT" = interrupted ]; then exit 77; fi
}
smite_foreign_gateway_verify_local() { [ "$FAULT" != tls ]; }
smite_foreign_gateway_recreate_node() { [ "$FAULT" != node ]; }
smite_foreign_gateway_write_renew_hook() { [ "$FAULT" != hook ]; }
mv() {
    if [ "$FAULT" = write ] && [ "${*: -1}" = "$TMP/site" ]; then return 1; fi
    if [ "$FAULT" = receipt ] && [ "${*: -1}" = "$SMITE_FOREIGN_GATEWAY_STATE_FILE" ]; then
        return 1
    fi
    command mv "$@"
}
printf 'SMITE_CONTROL_ADDRESS=https://kh.example.org:443/smite-node/%s\n' "$(printf 'a%.0s' {1..32})" > "$SMITE_NODE_DIR/.env"
for FAULT in write tls node hook receipt; do
    rm -f "$TMP/site" "$TMP/enabled" "$SMITE_FOREIGN_GATEWAY_STATE_FILE"
    if [ "$FAULT" != write ]; then
        printf 'original vhost\n' > "$TMP/site"
        ln -s "$TMP/original-link" "$TMP/enabled"
    fi
    status=0
    smite_foreign_gateway_configure <<< "" > "$TMP/rollback-log" 2>&1 || status=$?
    [ "$status" = 2 ]
    grep -qx 'FOREIGN_GATEWAY_SITE=ROLLED_BACK' "$TMP/rollback-log" || { cat "$TMP/rollback-log"; exit 1; }
    [ ! -e "$SMITE_FOREIGN_GATEWAY_STATE_FILE" ]
    if [ "$FAULT" = write ]; then
        [ ! -e "$TMP/site" ] && [ ! -L "$TMP/enabled" ]
    else
        grep -qx 'original vhost' "$TMP/site"
        [ "$(readlink "$TMP/enabled")" = "$TMP/original-link" ]
    fi
done
# Exit the stage subprocess after the new site is installed and before commit.
FAULT=interrupted
status=0
smite_foreign_gateway_configure <<< "" > "$TMP/interrupted" 2>&1 || status=$?
[ "$status" = 77 ]
[ -d "$SMITE_STATE_DIR/foreign-gateway.pending" ]
[ ! -e "$SMITE_FOREIGN_GATEWAY_STATE_FILE" ]
grep -qx 'candidate vhost' "$TMP/site"
FAULT=
printf 'independent edit\n' > "$TMP/site"
status=0
smite_foreign_gateway_configure <<< "" > "$TMP/drift" 2>&1 || status=$?
[ "$status" = 2 ]
grep -qx 'independent edit' "$TMP/site"
[ -d "$SMITE_STATE_DIR/foreign-gateway.pending" ]
cp "$SMITE_STATE_DIR/foreign-gateway.pending/candidate" "$TMP/site"
smite_foreign_gateway_configure <<< "" > "$TMP/retry-log" 2>&1
grep -qx 'FOREIGN_GATEWAY_SITE=ROLLED_BACK_AFTER_INTERRUPTION' "$TMP/retry-log"
[ ! -e "$SMITE_STATE_DIR/foreign-gateway.pending" ]
grep -qx 'FOREIGN_RC_GATEWAY_TRANSPORT=READY_ROOT_ONLY' "$TMP/retry-log"
grep -qx 'candidate vhost' "$TMP/site"
[ "$(readlink "$TMP/enabled")" = "$TMP/site" ]
[ "$(stat -c %a "$SMITE_FOREIGN_GATEWAY_STATE_FILE")" = 600 ]
echo 'UNIFIED_GATEWAY_SITE_ROLLBACK_AND_RETRY=PASS'
