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
smite_install_ui_action() { echo ui >> "$TMP/events"; [ "${FAIL_STAGE:-}" != ui ]; }
smite_install_finish_local_ir > "$TMP/output"
[ "$(cat "$TMP/events")" = $'gateway\ntls\npairing\nadmin\nui' ]
grep -qx 'IR_PANEL_STATIC_UI=APPLIED' "$TMP/output"
grep -qx 'PANEL_AND_IR_INSTALL=COMPLETE' "$TMP/output"
for FAIL_STAGE in gateway tls pairing admin; do
    : > "$TMP/events"
    if smite_install_finish_local_ir > "$TMP/output"; then
        echo "FAIL: swallowed $FAIL_STAGE"; exit 1
    fi
    ! grep -q 'PANEL_AND_IR_INSTALL=COMPLETE' "$TMP/output"
    if [ "$FAIL_STAGE" != admin ]; then ! grep -qx admin "$TMP/events"; fi
done
# A noncritical UI update MUST NOT abort a successful signed IR install,
# prevent local Node Connected, or force an unnecessary fresh reinstall.
: > "$TMP/events"
FAIL_STAGE=ui smite_install_finish_local_ir > "$TMP/ui-warning"
grep -qx 'PANEL_AND_IR_INSTALL=COMPLETE' "$TMP/ui-warning"
grep -qx 'IR_PANEL_STATIC_UI=REVIEW_OPTION_8' "$TMP/ui-warning"
[ "$(cat "$TMP/events")" = $'gateway\ntls\npairing\nadmin\nui' ]
# Failed pairing MUST stop BEFORE admin and cosmetic UI.
: > "$TMP/events"
if FAIL_STAGE=pairing smite_install_finish_local_ir > "$TMP/ir-no-ui"; then
    echo 'FAIL: pairing should prevent admin and optional UI'; exit 1
fi
[ "$(cat "$TMP/events")" = $'gateway\ntls\npairing' ]
unset FAIL_STAGE
# Same option-1 function resumes only the next incomplete stage. These
# are *function-boundary mocks*: real journal/Compose drift tests are in the
# existing RC6 journal test, and the real signed probe remains mandatory.
smite_install_ir_advance() {
    local next="$1"
    echo "checkpoint:$next" >> "$TMP/events"
    SMITE_IR_STAGE="$next"
}
ADMIN_EXISTS=0
smite_install_ir_admin_present() { [ "$ADMIN_EXISTS" = 1 ]; }
SMITE_IR_RESUMABLE=1
SMITE_IR_STAGE=CORE_COMMITTED
: > "$TMP/events"
smite_install_finish_local_ir > "$TMP/resume-fresh"
[ "$(cat "$TMP/events")" = $'gateway\ntls\ncheckpoint:GATEWAY_VERIFIED\npairing\ncheckpoint:PAIRING_VERIFIED\nadmin\ncheckpoint:ADMIN_CREATED\nui\ncheckpoint:COMPLETE' ]
grep -qx 'PANEL_AND_IR_INSTALL=COMPLETE' "$TMP/resume-fresh"
SMITE_IR_STAGE=GATEWAY_VERIFIED
: > "$TMP/events"
FAIL_STAGE=pairing
if smite_install_finish_local_ir > "$TMP/resume-pairing-fail"; then
    echo 'FAIL: signed Pairing error silently advanced to Admin'; exit 1
fi
[ "$(cat "$TMP/events")" = $'tls\npairing' ]
[ "$SMITE_IR_STAGE" = GATEWAY_VERIFIED ]
unset FAIL_STAGE
SMITE_IR_STAGE=PAIRING_VERIFIED
ADMIN_EXISTS=1
: > "$TMP/events"
smite_install_finish_local_ir > "$TMP/resume-admin"
[ "$(cat "$TMP/events")" = $'tls\npairing\ncheckpoint:ADMIN_CREATED\nui\ncheckpoint:COMPLETE' ]
SMITE_IR_STAGE=COMPLETE
: > "$TMP/events"
smite_install_finish_local_ir > "$TMP/resume-finished"
[ "$(cat "$TMP/events")" = $'tls\npairing' ]
grep -qx 'IR_PANEL_STATIC_UI=ALREADY_COMPLETED' "$TMP/resume-finished"
SMITE_IR_STAGE=GATEWAY_VERIFIED
: > "$TMP/events"
FAIL_STAGE=tls
if smite_install_finish_local_ir > "$TMP/resume-gateway-drift"; then
    echo 'FAIL: previously completed Gateway was silently reconfigured'; exit 1
fi
[ "$(cat "$TMP/events")" = tls ]
unset FAIL_STAGE
unset SMITE_IR_RESUMABLE SMITE_IR_STAGE ADMIN_EXISTS
unset -f smite_install_ir_advance smite_install_ir_admin_present
echo 'IR_OPTION_1_RESUME_CHECKPOINT_ORDER=PASS'

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
independent_result=0
smite_install_foreign_node > "$TMP/foreign-independent" 2>&1 || independent_result=$?
[ "$independent_result" -eq 2 ] || {
    echo "FAIL: independent Foreign cancellation must retain its nonzero result"; exit 1;
}
grep -Fxq 'Install the Foreign Smite Node? [y/N]: ' "$PROMPTS"
! grep -q 'FOREIGN_CORE_CONSENT=INHERITED' "$TMP/foreign-independent"
unset -f read clear
echo 'SELECTED_IR_FOREIGN_SINGLE_APPROVAL=PASS'



# The selected official RC7 images, source and original rollback journal
# are one exact pinned transaction. The signed unified trial has a distinct
# unapproved source and may not be substituted by a manual flag change.
unset -f python3
PAIR_ROOT="$TMP/selected-rc7-source"
mkdir -p "$PAIR_ROOT"
for file in smite-rc6-install-journal.py smite-rc7-registry-pair.json \
            smite-unified-trial-registry-pair.json; do
    cp "$ROOT/modules/$file" "$PAIR_ROOT/$file"
done
SMITE_FIELD_TRIAL_SOURCE_SHA=9a1270b31e8d44f13d09b71ab6b9798410b09c12
SMITE_FIELD_TRIAL_VERSION=2.0.0-rc.7
SMITE_FIELD_TRIAL_PUBLISH_REF=refs/tags/v2.0.0-rc.7
SMITE_FIELD_TRIAL_MANIFEST_SHA256=58bebfc605a5c1a64cf02ce38e6397dbcdae5f1c3289a01952f361b6a8aa660e
smite_install_selected_pair_journal_review "$PAIR_ROOT" > "$TMP/pair-review"
grep -qx 'SELECTED_RC7_PAIR_JOURNAL=EXACT_MATCH' "$TMP/pair-review"
grep -qx 'UNIFIED_TRIAL_JOURNAL=SEPARATE_NOT_ADMITTED' "$TMP/pair-review"
sed -i 's/^SOURCE = .*/SOURCE = "0000000000000000000000000000000000000000"/' \
    "$PAIR_ROOT/smite-rc6-install-journal.py"
status=0
smite_install_selected_pair_journal_review "$PAIR_ROOT" >/dev/null 2>&1 || status=$?
[ "$status" -eq 2 ]
cp "$ROOT/modules/smite-rc6-install-journal.py" "$PAIR_ROOT/"
sed -i 's/"release_approved":false/"release_approved":true/' \
    "$PAIR_ROOT/smite-unified-trial-registry-pair.json"
status=0
smite_install_selected_pair_journal_review "$PAIR_ROOT" >/dev/null 2>&1 || status=$?
[ "$status" -eq 2 ]
cp "$ROOT/modules/smite-unified-trial-registry-pair.json" "$PAIR_ROOT/"
status=0
SMITE_FIELD_TRIAL_SOURCE_SHA=b865be93e22153c60769f6329e6e55e781494ded \
    smite_install_selected_pair_journal_review "$PAIR_ROOT" >/dev/null 2>&1 || status=$?
[ "$status" -eq 2 ]
python3 - "$ROOT/modules/smite-install.sh" <<'PY_REVIEW_ORDER'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text()
selected=s.split("smite_install_selected_fresh() (",1)[1].split(
    "\n# Core transaction is committed before enrollment:",1)[0]
review='smite_install_selected_pair_journal_review "$module_dir"'
assert selected.index(review) < selected.index('smite_install_ensure_docker || return 2')
assert selected.index(review) < selected.index('smite-rc6-install-journal.py" begin')
assert selected.index('FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES') < selected.index(review)
PY_REVIEW_ORDER
echo 'SELECTED_SIGNED_RC7_JOURNAL_COHERENCE=PASS'
