#!/usr/bin/env bash
# Isolated dispatch/provenance tests: no Docker, network, packages or host writes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# Replace only the fixed lock path in a temporary copy; production path guard
# is exercised below. All operations stay inside this fixture.
sed -e "s@/var/lib/u-opti/rc6-install-journal/operation.lock@$TMP/operation.lock@g" \
    -e "s@/var/lib/u-opti/rc6-install-journal/current.json@$TMP/current.json@g" "$ROOT/modules/smite-install.sh" > "$TMP/installer.sh"
source "$TMP/installer.sh"
ln -s "$ROOT/modules/smite-clean-rc-preflight.sh" "$TMP/smite-clean-rc-preflight.sh"
# The production guard rejects symlink helpers; copy the fixture dependency.
rm "$TMP/smite-clean-rc-preflight.sh"
for component in smite-clean-rc-preflight.sh smite-rc6-install-journal.py \
    smite-rc7-registry-pair.json smite-unified-trial-registry-pair.json; do
    cp "$ROOT/modules/$component" "$TMP/"
done
# Exercise actual early failure branches with a successful UI pause.
clear() { :; }
smite_install_pause() { :; }
smite_install_require_tools() { return 1; }
SMITE_INSTALL_PROFILE=stable
SMITE_INSTALL_FAILURE_CODE=2
for entry in smite_install_panel_iran smite_install_foreign_node; do
    if "$entry" > "$TMP/failure.log"; then
        echo "FAIL: $entry swallowed dependency failure"; exit 1
    fi
done
unset SMITE_INSTALL_FAILURE_CODE
# A failed state write must not be masked by a successful chmod.
(
    SMITE_STATE_DIR="$TMP/state"
    SMITE_STATE_FILE="$SMITE_STATE_DIR/state.env"
    cat() { return 1; }
    chmod() { :; }
    if smite_write_state foreign panel.example node-kh kh.example standard; then
        echo 'FAIL: state write error was swallowed'; exit 1
    fi
)
SMITE_STATE_FILE="$TMP/state.env"
SMITE_PANEL_DIR="$TMP/panel"
SMITE_NODE_DIR="$TMP/node"
SMITE_OVERLAY_DIR="$TMP/overlay"
SMITE_INSTALL_PROFILE=stable
# Fixture paths must be rejected by the real production guard.
if smite_install_selected_paths; then echo 'FAIL: nonstandard paths accepted'; exit 1; fi
smite_install_selected_paths() { :; }
smite_install_require_tools() { :; }
smite_install_ensure_docker() { :; }
smite_clean_rc_nginx_paths_ready() { return 0; }
source() {
    if [[ "$1" == */smite-clean-rc-preflight.sh ]]; then return 0; fi
    builtin source "$@"
}
docker() {
    [ "$*" = '--host unix:///var/run/docker.sock container ls -a --format {{.Names}}' ] || return 98
    [ "${FAIL_DOCKER:-0}" = 0 ] || return 1
    printf '%s\n' "${EXISTING_CONTAINER:-}"
}
curl() {
    printf '%s\n' "$*" >> "$TMP/curl-calls"
    case "$*" in
      *https://github.com/sigstore/cosign/releases/download/v3.0.6/cosign-linux-amd64*)
        [ "${MOCK_COSIGN_RELEASE_FAIL:-0}" != 1 ] || return 28 ;;
      *https://api.github.com/repos/sigstore/cosign/releases/assets/390331694*)
        [ "${MOCK_COSIGN_API_FAIL:-0}" != 1 ] || return 28 ;;
    esac
    printf 'fixture' > "${@: -1}"
}
sha256sum() {
    if [[ "$1" == */cosign ]]; then
        if [ "${BAD_COSIGN:-0}" = 1 ]; then echo 'bad fixture'; else
            echo 'c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74 fixture'
        fi
    elif [[ "$1" == */trusted_root.json ]]; then
        if [ "${BAD_TRUST_ROOT:-0}" = 1 ]; then echo 'bad root fixture'; else
            echo '6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66 fixture'
        fi
    else command sha256sum "$@"; fi
}
smite_install_clean_rc_preflight() {
    [ "$SMITE_FIELD_TRIAL_SOURCE_SHA" = 9a1270b31e8d44f13d09b71ab6b9798410b09c12 ]
    [ "$SMITE_FIELD_TRIAL_PUBLISH_REF" = refs/tags/v2.0.0-rc.7 ]
    [ "$SMITE_FIELD_TRIAL_VERSION" = 2.0.0-rc.7 ]
    [ "$SMITE_UPSTREAM_REF" = "$SMITE_FIELD_TRIAL_SOURCE_SHA" ]
    [ "$SMITE_UPSTREAM_RAW" = "https://raw.githubusercontent.com/aghajani82/Smite/$SMITE_FIELD_TRIAL_SOURCE_SHA" ]
    [ "$SMITE_SELECTED_FRESH:$SMITE_INSTALL_PROFILE:$SMITE_RC_SIGNED_REGISTRY" = 1:clean-rc:1 ]
    [ -f "$SMITE_SELECTED_TRUSTED_ROOT" ]
    [ "$(command sha256sum "$ROOT/modules/smite-rc7-registry-pair.json" | cut -d' ' -f1)" = "$SMITE_FIELD_TRIAL_MANIFEST_SHA256" ]
    [ -z "${DOCKER_HOST:-}" ]
    [ -z "${DOCKER_CONTEXT:-}" ]
    [ "${FAIL_SIGNATURE:-0}" = 0 ] || return 2
}
python3() {
    if [[ "${2:-}" == */smite-rc6-install-journal.py ]]; then
        case "$*" in
            *' prepare') touch "$TMP/operation.lock" ;;
            *' begin '*) echo "$PROJECT" ;;
            *' commit-ir-panel '*) : ;;
            *' recover-ir-core '*)
                if [ -e "$TMP/current.json" ]; then
                    printf '%s\n' PANEL_COMMITTED "$PROJECT" iran.example.org node-ir 39100
                fi ;;
            *' commit') : ;;
            *) return 98 ;;
        esac
        return
    fi
    command python3 "$@"
}
smite_install_ui_action() { echo "$1" >> "$TMP/ui-dispatch"; [ "${FAIL_UI:-0}" = 0 ]; }
smite_install_finish_local_ir() { echo enrolled >> "$TMP/enrollment"; }
PROJECT=uopti_rc6_0123456789abcdef0123456789abcdef
IR_INPUT=$'y\niran.example.org\nnode-ir'
smite_install_ir_panel_core() {
    [ "$1:$2" = iran.example.org:127.0.0.1 ] || return 1
    echo panel >> "$TMP/dispatch"
}
smite_install_clean_rc_load_images() { [ "$1" = foreign ]; }
smite_wait_panel_api() { :; }
smite_write_state() { [ "$1:$2:$3" = panel-iran:iran.example.org:node-ir ]; }
smite_install_ir_node_core() {
    [ "$1" = node-ir ] && [ "$COMPOSE_PROJECT_NAME" = "$PROJECT" ] || return 1
    echo node >> "$TMP/dispatch"
    if [ "${FAIL_NODE:-0}" = 1 ]; then
        touch "$TMP/current.json"
        return 1
    fi
}
smite_install_foreign_node() { echo foreign >> "$TMP/dispatch"; }
export DOCKER_CONTEXT=untrusted DOCKER_HOST=tcp://not-a-real-host:2375
status=0
smite_install_selected_fresh foreign </dev/null > "$TMP/foreign.log" || status=$?
[ "$status" = 2 ]
grep -qx 'FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES' "$TMP/foreign.log"
[ ! -e "$TMP/operation.lock" ]
smite_install_selected_fresh panel-iran <<< "$IR_INPUT"
[ "$(cat "$TMP/dispatch")" = $'panel\nnode' ]
[ -s "$TMP/enrollment" ]
[ "$SMITE_FIELD_TRIAL_VERSION" = 2.0.0-rc.1 ]
[ "$SMITE_INSTALL_PROFILE" = stable ]
[ "$DOCKER_CONTEXT" = untrusted ]
rm "$TMP/dispatch" "$TMP/enrollment"

# Retry through actual option 1 with no credentials/domain prompt.
status=0
FAIL_NODE=1 smite_install_selected_fresh panel-iran <<< "$IR_INPUT" > "$TMP/node-failure.log" || status=$?
[ "$status" = 2 ]
grep -q '^IR_NODE=ROLLED_BACK' "$TMP/node-failure.log"
[ ! -e "$TMP/enrollment" ]
printf '1\n0\n' | show_smite_install_menu > "$TMP/retry-menu.log"
[ "$(cat "$TMP/dispatch")" = $'panel\nnode\nnode' ]
grep -q '^IR_PANEL=VERIFIED_RETAINED' "$TMP/retry-menu.log"
[ -s "$TMP/enrollment" ]
rm "$TMP/dispatch" "$TMP/current.json"

# Exact selected installer Cosign bootstrap never silently hangs.
: > "$TMP/curl-calls"
MOCK_COSIGN_RELEASE_FAIL=1 smite_install_selected_fresh panel-iran <<< "$IR_INPUT" > "$TMP/fallback.log"
[ "$(cat "$TMP/dispatch")" = $'panel\nnode' ]
grep -q '^RC7_COSIGN_DOWNLOAD=OFFICIAL_GITHUB_API_FALLBACK' "$TMP/fallback.log"
grep -Fq -- '--connect-timeout 10 --max-time 180' "$TMP/curl-calls"
grep -Fq -- '--progress-bar' "$TMP/curl-calls"
grep -Fq 'https://api.github.com/repos/sigstore/cosign/releases/assets/390331694' "$TMP/curl-calls"
grep -q '^RC7_COSIGN_SHA256=VERIFIED' "$TMP/fallback.log"
rm "$TMP/dispatch"
: > "$TMP/curl-calls"
if MOCK_COSIGN_RELEASE_FAIL=1 MOCK_COSIGN_API_FAIL=1 \
  smite_install_selected_fresh panel-iran <<< "$IR_INPUT" > "$TMP/all-downloads-failed.log" 2>&1; then
    echo 'FAIL: RC7 accepted unavailable verifier'; exit 1
fi
grep -q 'HOLD_RC7_COSIGN_VERIFIER_UNAVAILABLE' "$TMP/all-downloads-failed.log"
[ ! -e "$TMP/dispatch" ]
[ "$(grep -c 'cosign-linux-amd64' "$TMP/curl-calls")" = 1 ]
[ "$(grep -c '/assets/390331694' "$TMP/curl-calls")" = 1 ]
echo 'RC7_VISIBLE_BOUNDED_COSIGN_AND_OFFICIAL_FALLBACK=PASS_ISOLATED'

for flag in FAIL_DOCKER BAD_COSIGN BAD_TRUST_ROOT FAIL_SIGNATURE; do
    export "$flag=1"
    if smite_install_selected_fresh panel-iran <<< "$IR_INPUT"; then echo "FAIL: accepted $flag"; exit 1; fi
    unset "$flag"
    [ ! -e "$TMP/dispatch" ]
done
EXISTING_CONTAINER=smite-node
if smite_install_selected_fresh panel-iran <<< "$IR_INPUT"; then exit 1; fi
unset EXISTING_CONTAINER
ln -s "$TMP/missing" "$SMITE_STATE_FILE"
if smite_install_selected_fresh panel-iran <<< "$IR_INPUT"; then exit 1; fi
[ ! -e "$TMP/dispatch" ]
rm "$SMITE_STATE_FILE"
if smite_install_selected_fresh panel-iran <<< n; then exit 1; fi
[ ! -e "$TMP/dispatch" ]
SMITE_INSTALL_PROFILE=clean-rc
smite_install_selected_fresh foreign
[ "$(cat "$TMP/dispatch")" = foreign ]
rm "$TMP/dispatch"
SMITE_INSTALL_PROFILE=stable
printf '1\n%s\n0\n' "$IR_INPUT" | show_smite_install_menu > "$TMP/menu.log"
[ "$(cat "$TMP/dispatch")" = $'panel\nnode' ]
grep -q 'Selected Smite 2.0.0-rc.7' "$TMP/menu.log"
export FAIL_SIGNATURE=1
printf '1\n%s\n0\n' "$IR_INPUT" | show_smite_install_menu > "$TMP/failed-menu.log"
unset FAIL_SIGNATURE
grep -q 'HOLD: Panel + Iran Node installation did not complete' "$TMP/failed-menu.log"
echo 'OFFICIAL_MENU_OPTION_1_AND_NODE_RETRY=PASS_ISOLATED_FIXTURE'

printf '8\ny\n9\ny\n0\n' | show_smite_install_menu > "$TMP/ui-menu.log"
[ "$(tail -n 2 "$TMP/ui-dispatch")" = $'apply\nrollback' ]
echo 'UI_UPDATE_ROLLBACK_MENU=PASS'

# Review only the new menu functions. No host Docker installer is executed.
mkdir -p "$TMP/advanced-pairing"
cat > "$TMP/advanced-pairing/smite-node-pairing-wizard.sh" <<'PAIRING_STUB'
smite_node_pairing_menu() {
    echo 'SIGNED_PAIRING_EXISTING_HANDLER=CALLED'
}
PAIRING_STUB
(
    DOCKER_MODULE_DIR="$TMP/advanced-pairing"
    source <(sed -n '/^docker_smite_open_signed_pairing_advanced() (/,$p' "$ROOT/modules/docker.sh")
    printf '3\n1\n0\n0\n' | docker_smite_management_menu > "$TMP/advanced.log"
)
grep -q '3) Advanced Tools (Signed Pairing)' "$TMP/advanced.log"
grep -q '1) Signed Pairing (Field Trial / admin approval required)' "$TMP/advanced.log"
[ "$(grep -c 'SIGNED_PAIRING_EXISTING_HANDLER=CALLED' "$TMP/advanced.log")" = 1 ]

# Symlinked wizard modules must be rejected, with no attempt to source them.
rm "$TMP/advanced-pairing/smite-node-pairing-wizard.sh"
echo 'echo UNSAFE_SIGNED_PAIRING_MODULE_WAS_RUN' > "$TMP/unauthorized.sh"
ln -s "$TMP/unauthorized.sh" "$TMP/advanced-pairing/smite-node-pairing-wizard.sh"
(
    DOCKER_MODULE_DIR="$TMP/advanced-pairing"
    source <(sed -n '/^docker_smite_open_signed_pairing_advanced() (/,$p' "$ROOT/modules/docker.sh")
    printf '3\n1\n\n0\n0\n' | docker_smite_management_menu > "$TMP/reject-advanced.log"
)
grep -q 'HOLD: Reviewed Smite signed-pairing wizard is missing or unsafe' "$TMP/reject-advanced.log"
! grep -q 'UNSAFE_SIGNED_PAIRING_MODULE_WAS_RUN' "$TMP/reject-advanced.log"

# Fresh IR installer must report that running != registered; only the
# admin-approved HTTPS/443 reservation/code/redemption may populate Iran Nodes.
python3 -B - "$ROOT/modules/smite-install.sh" <<'PY_IR_NODE_NOTICE'
from pathlib import Path
import sys
s = Path(sys.argv[1]).read_text()
start = s.index('smite_install_panel_iran() {')
end = s.index('smite_install_foreign_node() {', start)
section = s[start:end]
for marker in (
    'IR_NODE_CONTAINER=HEALTHY_NOT_YET_PAIRED',
    'IR_PANEL_NODE_REGISTRATION=PENDING_ADMIN_APPROVAL',
    'Do NOT run Install Panel + Iran Node again',
    'Advanced -> Signed Pairing',
    'PAIRING_ACTIVATION=OPERATOR_APPROVAL_REQUIRED',
):
    assert section.count(marker) == 1, marker
assert section.index('IR_NODE_CONTAINER=HEALTHY_NOT_YET_PAIRED') > section.index('smite_write_state')
PY_IR_NODE_NOTICE
echo 'SMITE_ADVANCED_SIGNED_PAIRING=PASS_ISOLATED_NO_AUTO_REGISTRATION'

