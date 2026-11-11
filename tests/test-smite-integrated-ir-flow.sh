#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
source "$ROOT/modules/smite-install.sh"
smite_install_pause() { :; }
smite_gateway_configure_panel() { echo gateway >> "$TMP/events"; [ "${FAIL_STAGE:-}" != gateway ]; }
smite_gateway_panel_domain() { echo panel.example.com; }
smite_gateway_verify_443() { echo tls >> "$TMP/events"; [ "${FAIL_STAGE:-}" != tls ]; }
python3() {
    [[ "$*" == *smite-node-pairing.py*--complete-local-ir-install ]] || return 99
    [ "$UOPTI_SMITE_PAIRING_FIELD_TRIAL" = YES ] || return 99
    echo pairing >> "$TMP/events"
    [ "${FAIL_STAGE:-}" != pairing ]
}
smite_install_create_admin() { echo admin >> "$TMP/events"; [ "${FAIL_STAGE:-}" != admin ]; }
smite_install_finish_local_ir > "$TMP/output"
[ "$(cat "$TMP/events")" = $'gateway\ntls\npairing\nadmin' ]
grep -qx 'PANEL_AND_IR_INSTALL=COMPLETE' "$TMP/output"
for FAIL_STAGE in gateway tls pairing admin; do
    : > "$TMP/events"
    if smite_install_finish_local_ir > "$TMP/output"; then
        echo "FAIL: swallowed $FAIL_STAGE"; exit 1
    fi
    ! grep -q 'PANEL_AND_IR_INSTALL=COMPLETE' "$TMP/output"
    if [ "$FAIL_STAGE" != admin ]; then ! grep -qx admin "$TMP/events"; fi
done
unset FAIL_STAGE
# Real gateway entry returns failure for missing dependencies (no host changes).
source "$ROOT/modules/smite-gateway.sh"
id() { echo 0; }
clear() { :; }
smite_gateway_require_panel() { return 1; }
SMITE_GATEWAY_INSTALL_FLOW=1
if smite_gateway_configure_panel > "$TMP/output"; then
    echo 'FAIL: gateway prerequisite failure masked'; exit 1
fi
echo 'INTEGRATED_IR_ORDER_AND_FAILURE_PROPAGATION=PASS'
