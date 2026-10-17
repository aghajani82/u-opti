#!/usr/bin/env bash
# Hermetic test of the ACTUAL beginner menu dispatch and the guarded actions.
set -euo pipefail
cd "$(dirname "$0")/.."
bash -n modules/smite-frp-wizard.sh
grep -Fq 'source "$MODULES_PATH/smite-frp-wizard.sh"' u-opti
grep -Fq '"smite-frp-wizard.sh"' install.sh
grep -Fq '1) START HERE - Install/check Smite + HTTPS Gateway' modules/smite-frp-wizard.sh
grep -Fq '2) PORT + PATH - Save IR profile before Smite tunnel' modules/smite-frp-wizard.sh
grep -Fq '3) VERIFY - XHTTP, client settings and real-traffic checklist' modules/smite-frp-wizard.sh
grep -Fq 'Choose [0-4]' modules/smite-frp-wizard.sh
grep -Fq 'FRP ADVANCED' modules/smite-frp-wizard.sh

MODE=standard ROLE=panel-iran DOMAIN=ir.kolbe1.ir
smite_frp_std_state() {
    case "$1" in
        SMITE_CONNECTION_MODE) printf '%s' "$MODE" ;;
        SMITE_ROLE) printf '%s' "$ROLE" ;;
        SMITE_PANEL_DOMAIN) printf '%s' "$DOMAIN" ;;
    esac
}
smite_frp_std_running() { return 0; }
clear() { :; }
docker() {
    if [ "$1" = compose ]; then echo "2.1.0"; return 0; fi
    return 1  # No containers on a mock fresh host.
}
systemctl() { return 0; }
smite_frp_std_install() {
    echo "INSTALL_STEP_$1"
    MODE=standard
    if [ "$1" = ir ]; then ROLE=panel-iran; else ROLE=foreign; fi
}
smite_gateway_configure_panel() { echo "IR_GATEWAY_STEP"; }
smite_foreign_gateway_configure() { echo "KH_GATEWAY_STEP"; }
show_docker_3xui_menu() { echo "SANAEI_STEP"; }
docker_smite_open_setup_wizard() { echo "PRIVATE_WIZARD"; }
docker_smite_frp_standard_guide() { echo "LEGACY_GUIDE"; }
smite_frp_wizard_port() { printf 13914; }
SMITE_FRP_XHTTP_PATH_HELPER="$PWD/modules/smite-frp-xhttp-paths.py"
FRP_TEST_PATH="/13914/web"
smite_frp_xhttp_get_path() { printf '%s\n' "$FRP_TEST_PATH"; }
smite_frp_xhttp_register_path() { echo "FRP_PATH_APPLIED:$1:$2"; }
smite_frp_xhttp_stage_path() { echo "FRP_XHTTP_PROFILE_SAVED_PENDING_TUNNEL=$1 $2"; }
smite_frp_xhttp_verify_path() { return 0; }
curl() {
    local arg="" prev=""
    for arg in "$@"; do
        if [ "$prev" = -D ]; then printf 'HTTP/1.1 200 OK\nX-Padding: test\n' > "$arg"; fi
        prev="$arg"
    done
    printf '200'
}

source modules/smite-frp-wizard.sh
smite_frp_wizard_pause() { :; }
# The module intentionally defines its own prompt; test supplies a fixed safe port.
smite_frp_wizard_port() { printf 13914; }
test "$(smite_frp_wizard_mode_label)" = standard
test "$(smite_frp_wizard_role)" = ir
test "$(smite_frp_wizard_client)" != ""
out="$(smite_frp_wizard_client)"
grep -Fq 'ALPN: http/1.1' <<< "$out"
grep -Fq 'Path: /13914/web' <<< "$out"

# Real new profile selector uses custom user-provided path and rejects unsafe.
out="$(printf '/13914/shop\ny\n' | smite_frp_wizard_easy_configure ir)"
grep -Fq 'FRP_XHTTP_PROFILE_SAVED_PENDING_TUNNEL=13914 /13914/shop' <<< "$out"
if grep -Fq 'IR_XHTTP_NGINX_PATH_VERIFIED=' <<< "$out"; then
    echo "ERROR: Pending FRP profile mislabeled as active"; exit 1
fi
out="$(printf '/13914/shop\nn\n' | smite_frp_wizard_easy_configure ir)"
grep -Fq 'IR FRP profile not saved' <<< "$out"
! grep -Fq 'FRP_XHTTP_PROFILE_SAVED_PENDING' <<< "$out"
out="$(printf '/api/bad\n' | smite_frp_wizard_easy_configure ir)" && {
    echo "ERROR: reserved FRP namespace was accepted" >&2; exit 1;
}
grep -Fq 'HOLD: Invalid/reserved' <<< "$out"

# KH never writes IR Nginx even when port/path chosen.
ROLE=foreign
out="$(printf '/13914/shop\n' | smite_frp_wizard_easy_configure kh)"
grep -Fq 'KH GUIDE ONLY' <<< "$out"
if grep -Fq 'FRP_PATH_APPLIED:' <<< "$out"; then
    echo "ERROR: KH attempted to publish IR route" >&2; exit 1;
fi
out="$(printf '/13914/shop\n' | smite_frp_wizard_easy_verify kh)"
grep -Fq 'XHTTP_HANDLER_REACHED=YES' <<< "$out"
grep -Fq 'Path=/13914/shop' <<< "$out"

ROLE=panel-iran
out="$(printf '/13914/web\n' | smite_frp_wizard_easy_verify ir)"
grep -Fq 'XHTTP_HANDLER_REACHED=YES' <<< "$out"
grep -Fq 'https://ir.kolbe1.ir/13914/web/' <<< "$out"

# A naked HTTP 200 without the Xray X-Padding header is NOT a PASS.
original_curl_mock="$(declare -f curl)"
curl() {
    local arg="" prev=""
    for arg in "$@"; do
        if [ "$prev" = -D ]; then printf 'HTTP/1.1 200 OK\n' > "$arg"; fi
        prev="$arg"
    done
    printf 200
}
if out="$(printf '/13914/web\n' | smite_frp_wizard_easy_verify ir)"; then
    echo "ERROR: HTTP 200 without X-Padding incorrectly counted as XHTTP PASS" >&2
    exit 1
fi
grep -Fq 'XHTTP_HANDLER_REACHED=NO' <<< "$out"
eval "$original_curl_mock"
DOMAIN='bad/host'
if out="$(printf '/13914/web\n' | smite_frp_wizard_easy_verify ir)"; then
    echo "ERROR: Malformed HTTPS hostname accepted" >&2; exit 1
fi
grep -Fq 'unsafe' <<< "$out"
DOMAIN=ir.kolbe1.ir

# Fresh-host role mode is accurately labeled, and START HERE never silently
# invokes installs or gateways without explicit confirmation.
MODE="" ROLE=""
test "$(smite_frp_wizard_mode_label)" = 'NOT INSTALLED (fresh host)'
out="$(printf 'n\n' | smite_frp_wizard_start_here ir)"
grep -Fq 'No changes.' <<< "$out"
! grep -Fq 'INSTALL_STEP' <<< "$out"
out="$(printf 'y\ny\n' | smite_frp_wizard_start_here ir)"
grep -Fq 'INSTALL_STEP_ir' <<< "$out"
grep -Fq 'IR_GATEWAY_STEP' <<< "$out"
MODE=private
if out="$(printf '0\n' | smite_frp_wizard_menu ir)"; then
    echo "ERROR: Private mode entered Standard wizard" >&2; exit 1
fi
grep -Fq 'not Standard' <<< "$out"

MODE=standard ROLE=foreign
if out="$(printf '0\n' | smite_frp_wizard_menu ir)"; then
    echo "ERROR: Mismatched trusted role entered FRP wizard" >&2; exit 1
fi
grep -Fq 'conflicts' <<< "$out"

# START HERE ends after IR/KH foundation; no premature port/path or
# Sanaei step. Separate option 2 can stage an IR profile before Smite tunnel.
MODE=standard ROLE=foreign
smite_frp_wizard_easy_configure() { echo "UNEXPECTED_AUTOMATIC_PROFILE:$1"; }
out="$(printf 'n\n' | smite_frp_wizard_start_here kh)"
grep -Fq 'KH FOUNDATION COMPLETE' <<< "$out"
! grep -Fq 'UNEXPECTED_AUTOMATIC_PROFILE:' <<< "$out"
! grep -Fq 'SANAEI_STEP' <<< "$out"
MODE=standard ROLE=panel-iran
out="$(printf 'n\n' | smite_frp_wizard_start_here ir)"
grep -Fq 'IR FOUNDATION COMPLETE' <<< "$out"
! grep -Fq 'UNEXPECTED_AUTOMATIC_PROFILE:' <<< "$out"

# Exercise actual PRIMARY menu routing (not just grep text).
MODE=standard ROLE=panel-iran
smite_frp_wizard_start_here() { echo "PRIMARY_START_ROLE:$1"; }
smite_frp_wizard_easy_configure() { echo "PRIMARY_CONFIGURE_ROLE:$1"; }
smite_frp_wizard_easy_verify() { echo "PRIMARY_VERIFY_ROLE:$1"; }
out="$(printf '1\n2\n3\n0\n' | smite_frp_wizard_menu ir)"
grep -Fq 'PRIMARY_START_ROLE:ir' <<< "$out"
grep -Fq 'PRIMARY_CONFIGURE_ROLE:ir' <<< "$out"
grep -Fq 'PRIMARY_VERIFY_ROLE:ir' <<< "$out"
# The original individual installer is reachable ONLY under Advanced.
out="$(printf '4\n2\n0\n0\n' | smite_frp_wizard_menu ir)"
grep -Fq 'INSTALL_STEP_ir' <<< "$out"
# Role choice is a single explicit prompt if Smite not installed.
MODE="" ROLE=""
out="$(printf '2\n0\n' | smite_frp_wizard_menu)"
grep -Fq 'This server: kh | Smite: NOT INSTALLED' <<< "$out"

echo 'PASS: real 4-action FRP menu, guarded fresh install, custom Path, KH read-only, role guards and Advanced'
