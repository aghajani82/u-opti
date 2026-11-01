#!/usr/bin/env bash
# Isolated dispatch/provenance tests: no Docker, network, packages or host writes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
source "$ROOT/modules/smite-install.sh"
SMITE_STATE_FILE="$TMP/state.env"
SMITE_PANEL_DIR="$TMP/panel"
SMITE_NODE_DIR="$TMP/node"
SMITE_OVERLAY_DIR="$TMP/overlay"
SMITE_INSTALL_PROFILE=stable
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
    [ "$SMITE_FIELD_TRIAL_SOURCE_SHA" = 25ff25585be3f7ff1c8b73b39a23d0509f9a2312 ]
    [ "$SMITE_FIELD_TRIAL_PUBLISH_REF" = refs/tags/v2.0.0-rc.6 ]
    [ "$SMITE_FIELD_TRIAL_VERSION" = 2.0.0-rc.6 ]
    [ "$SMITE_UPSTREAM_RAW" = "https://raw.githubusercontent.com/aghajani82/Smite/$SMITE_FIELD_TRIAL_SOURCE_SHA" ]
    [ "$SMITE_SELECTED_FRESH:$SMITE_INSTALL_PROFILE:$SMITE_RC_SIGNED_REGISTRY" = 1:clean-rc:1 ]
    [ "$(command sha256sum "$ROOT/modules/smite-selected-candidate.json" | cut -d' ' -f1)" = "$SMITE_FIELD_TRIAL_MANIFEST_SHA256" ]
    [ "$DOCKER_HOST" = unix:///var/run/docker.sock ]
    [ -z "${DOCKER_CONTEXT:-}" ]
    [ "${FAIL_SIGNATURE:-0}" = 0 ] || return 2
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
echo 'SELECTED_RC6_DISPATCH_FIXTURES=PASS (not a real host installation)'
