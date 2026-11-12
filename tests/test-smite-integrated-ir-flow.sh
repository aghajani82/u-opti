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


# A single fresh-install approval is sufficient for Iran/Foreign core.
# Exercise the ACTUAL existing functions through their first preflight:
# each mandatory name/domain remains prompted, but the second consent does
# not appear. Failing preflight avoids any Docker or host mutation.
smite_install_require_tools() { return 0; }
smite_install_ensure_docker() { return 0; }
smite_container_exists() { return 1; }
smite_install_clean_rc_preflight() { return 2; }
clear() { :; }
SMITE_INSTALL_PROFILE=clean-rc
SMITE_SELECTED_FRESH=1
SMITE_INSTALL_FAILURE_CODE=2
SMITE_RC_SIGNED_REGISTRY=1
SMITE_FRP_TRIAL_ONLY=0
SMITE_PANEL_COMPOSE="$TMP/nonexistent-panel.yml"
SMITE_NODE_COMPOSE="$TMP/nonexistent-node.yml"
PROMPTS="$TMP/prompts"
read() {
    local prompt="${2:-}" target="${!#}" answer=""
    printf '%s\n' "$prompt" >> "$PROMPTS"
    case "$prompt" in
        "Panel domain"* ) answer="iran.example.org" ;;
        "Iran node name"* ) answer="node-ir" ;;
        "This foreign server domain"* ) answer="kh.example.org" ;;
        "Foreign node name"* ) answer="node-kh" ;;
        "Install "* ) answer="n" ;;
        * ) return 99 ;;
    esac
    printf -v "$target" '%s' "$answer"
}
: > "$PROMPTS"
if smite_install_panel_iran > "$TMP/ir-consent" 2>&1; then
    echo "FAIL: isolated IR preflight must block"; exit 1
fi
grep -qx 'IR_CORE_CONSENT=INHERITED_FROM_SELECTED_OPTION_1' "$TMP/ir-consent"
! grep -q '^Install Smite Panel' "$PROMPTS"
[ "$(wc -l < "$PROMPTS")" -eq 2 ]
: > "$PROMPTS"
if smite_install_foreign_node > "$TMP/foreign-consent" 2>&1; then
    echo "FAIL: isolated Foreign preflight must block"; exit 1
fi
grep -qx 'FOREIGN_CORE_CONSENT=INHERITED_FROM_SELECTED_OPTION_2' "$TMP/foreign-consent"
! grep -q '^Install the Foreign' "$PROMPTS"
[ "$(wc -l < "$PROMPTS")" -eq 3 ]

# An independent/unselected call retains its existing explicit consent.
SMITE_SELECTED_FRESH=0
: > "$PROMPTS"
smite_install_foreign_node > "$TMP/foreign-independent" 2>&1
grep -qx 'Install the Foreign Smite Node? [y/N]: ' "$PROMPTS"
! grep -q 'FOREIGN_CORE_CONSENT=INHERITED' "$TMP/foreign-independent"
unset -f read clear
echo 'SELECTED_IR_FOREIGN_SINGLE_APPROVAL=PASS'

