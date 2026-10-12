#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source_text="$(cat modules/smite-frp-wizard.sh)"
grep -Fq 'source "$MODULES_PATH/smite-frp-wizard.sh"' u-opti
grep -Fq '"smite-frp-wizard.sh"' install.sh
grep -Fq '"smite-frp-wizard.sh"' u-opti
grep -Fq 'smite-frp-xhttp.sh' u-opti

MODE=standard
ROLE=panel-iran
smite_frp_std_state() {
    case "$1" in
        SMITE_CONNECTION_MODE) printf '%s' "$MODE" ;;
        SMITE_ROLE) printf '%s' "$ROLE" ;;
        SMITE_PANEL_DOMAIN) printf '%s' 'ir.kolbe1.ir' ;;
    esac
}
smite_frp_std_running() { return 0; }
clear() { :; }
smite_frp_wizard_pause() { :; }
docker_smite_open_setup_wizard() { echo PRIVATE_WIZARD_CALLED; }
docker_smite_frp_standard_guide() { echo OLD_FRP_GUIDE_CALLED; }
smite_frp_std_install() { echo "INSTALL_STEP_$1"; }
smite_gateway_configure_panel() { echo "IR_GATEWAY_STEP"; }
smite_foreign_gateway_configure() { echo "KH_GATEWAY_STEP"; }
show_docker_3xui_menu() { echo "SANAEI_STEP"; }
smite_frp_wizard_port() { printf 13914; }

# The original functions above must remain untouched when wizard is sourced.
source modules/smite-frp-wizard.sh
smite_frp_wizard_pause() { :; }
smite_frp_wizard_port() { printf 13914; }
test "$(smite_frp_wizard_role)" = ir
smite_frp_wizard_client_out="$(smite_frp_wizard_client)"
grep -Fq 'ALPN: http/1.1' <<< "$smite_frp_wizard_client_out"
grep -Fq 'Path: /13914/web' <<< "$smite_frp_wizard_client_out"
grep -Fq 'Address: ir.kolbe1.ir | Port: 443' <<< "$smite_frp_wizard_client_out"
grep -Fq 'Smite' <<< "$(smite_frp_wizard_tunnel ir)"

out="$(printf '1\n0\n' | docker_smite_management_menu)"
grep -Fq PRIVATE_WIZARD_CALLED <<< "$out"
out="$(printf '2\n0\n' | docker_smite_management_menu)"
grep -Fq OLD_FRP_GUIDE_CALLED <<< "$out"
out="$(printf '2\n0\n' | smite_frp_wizard_menu)"
grep -Fq INSTALL_STEP_ir <<< "$out"

ROLE=foreign
test "$(smite_frp_wizard_role)" = kh
out="$(printf '2\n0\n' | smite_frp_wizard_menu)"
grep -Fq INSTALL_STEP_kh <<< "$out"
out="$(printf '3\n0\n' | smite_frp_wizard_menu)"
grep -Fq KH_GATEWAY_STEP <<< "$out"
out="$(printf '4\n0\n' | smite_frp_wizard_menu)"
grep -Fq SANAEI_STEP <<< "$out"

MODE=private
out="$(printf '0\n' | smite_frp_wizard_menu)"
grep -Fq 'FRP Wizard requires Standard' <<< "$out"
if grep -Fq 'INSTALL_STEP_' <<< "$out"; then
    echo "ERROR: Private mode executed Standard install step"
    exit 1
fi
echo 'PASS: Independent FRP Wizard, role routing, Private guard and tested ALPN recipe'
