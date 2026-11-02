#!/usr/bin/env bash
# Isolated dispatch/provenance tests: no Docker, network, packages or host writes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# Replace only the fixed lock path in a temporary copy; production path guard
# is exercised below. All operations stay inside this fixture.
sed "s@/var/lib/u-opti/rc6-install-journal/operation.lock@$TMP/operation.lock@g" "$ROOT/modules/smite-install.sh" > "$TMP/installer.sh"
source "$TMP/installer.sh"
ln -s "$ROOT/modules/smite-clean-rc-preflight.sh" "$TMP/smite-clean-rc-preflight.sh"
# The production guard rejects symlink helpers; copy the fixture dependency.
rm "$TMP/smite-clean-rc-preflight.sh"
cp "$ROOT/modules/smite-clean-rc-preflight.sh" "$TMP/smite-clean-rc-preflight.sh"
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
curl() { printf 'fixture' > "${@: -1}"; }
sha256sum() {
    if [[ "$1" == */cosign ]]; then
        if [ "${BAD_COSIGN:-0}" = 1 ]; then echo 'bad fixture'; else
            echo 'c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74 fixture'
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
    [ "$(command sha256sum "$ROOT/modules/smite-selected-candidate.json" | cut -d' ' -f1)" = "$SMITE_FIELD_TRIAL_MANIFEST_SHA256" ]
    [ -z "${DOCKER_HOST:-}" ]
    [ -z "${DOCKER_CONTEXT:-}" ]
    [ "${FAIL_SIGNATURE:-0}" = 0 ] || return 2
}
python3() {
    if [[ "$*" == *smite-rc6-install-journal.py* ]]; then
        case "$*" in
            *' begin '*) echo uopti_rc6_0123456789abcdef0123456789abcdef ;;
            *' commit') : ;;
            *) return 98 ;;
        esac
        return
    fi
    command python3 "$@"
}
smite_install_panel_iran() { echo panel >> "$TMP/dispatch"; }
smite_install_foreign_node() { echo foreign >> "$TMP/dispatch"; }
export DOCKER_CONTEXT=untrusted DOCKER_HOST=tcp://not-a-real-host:2375
smite_install_selected_fresh foreign <<< y
[ "$(cat "$TMP/dispatch")" = foreign ]
# Settings are scoped to the selected call, leaving old recovery untouched.
[ "$SMITE_FIELD_TRIAL_VERSION" = 2.0.0-rc.1 ]
[ "$SMITE_INSTALL_PROFILE" = stable ]
[ "$DOCKER_CONTEXT" = untrusted ]
rm "$TMP/dispatch"
smite_install_selected_fresh panel-iran <<< y
[ "$(cat "$TMP/dispatch")" = panel ]
rm "$TMP/dispatch"
for flag in FAIL_DOCKER BAD_COSIGN FAIL_SIGNATURE; do
    export "$flag=1"
    if smite_install_selected_fresh foreign <<< y; then echo "FAIL: accepted $flag"; exit 1; fi
    unset "$flag"
    [ ! -e "$TMP/dispatch" ]
done
EXISTING_CONTAINER=smite-node
if smite_install_selected_fresh foreign <<< y; then exit 1; fi
unset EXISTING_CONTAINER
ln -s "$TMP/missing" "$SMITE_STATE_FILE"
if smite_install_selected_fresh foreign <<< y; then exit 1; fi
[ ! -e "$TMP/dispatch" ]
rm "$SMITE_STATE_FILE"
if smite_install_selected_fresh foreign <<< n; then exit 1; fi
[ ! -e "$TMP/dispatch" ]
SMITE_INSTALL_PROFILE=clean-rc
smite_install_selected_fresh foreign
[ "$(cat "$TMP/dispatch")" = foreign ]
rm "$TMP/dispatch"
SMITE_INSTALL_PROFILE=stable
printf '1\ny\n0\n' | show_smite_install_menu > "$TMP/menu.log"
[ "$(cat "$TMP/dispatch")" = panel ]
grep -q 'Selected Smite 2.0.0-rc.7' "$TMP/menu.log"
echo 'OFFICIAL_MENU_OPTION_1=PASS_ISOLATED_FIXTURE'
echo 'SELECTED_RC7_DISPATCH_FIXTURES=PASS (not a real host installation)'
