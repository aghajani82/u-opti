#!/bin/bash

# U-OPTI - Smite Private Setup Progress UI
# Presentation layer for smite-setup-progress.sh.
#
# Input model:
#   1 .. 10   -> open that setup step
#   .1 .. .10 -> show read-only details for that setup step
#   r          -> refresh progress
#   n          -> show the next recommended step
#   0          -> back
#
# Selecting a step never performs an installation or repair automatically.
# Potentially state-changing actions remain explicit inside the relevant step.

SMITE_SETUP_UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"

if ! declare -F smite_setup_progress_render >/dev/null 2>&1; then
    if [ -f "$SMITE_SETUP_UI_DIR/smite-setup-progress.sh" ]; then
        # shellcheck disable=SC1090
        source "$SMITE_SETUP_UI_DIR/smite-setup-progress.sh"
    fi
fi

smite_setup_ui_require_core() {
    declare -F smite_setup_progress_render >/dev/null 2>&1 &&
    declare -F smite_setup_progress_collect >/dev/null 2>&1 &&
    declare -F smite_setup_progress_symbol >/dev/null 2>&1
}

smite_setup_ui_step_title() {
    case "$1" in
        1)  printf 'BOTH  -> Docker' ;;
        2)  printf 'KH    -> 3x-UI' ;;
        3)  printf 'KH    -> EasyTier Foreign' ;;
        4)  printf 'IR    -> EasyTier Panel' ;;
        5)  printf 'IR    -> Smite Panel + Iran Node' ;;
        6)  printf 'KH    -> Smite Foreign Node' ;;
        7)  printf 'IR    -> Panel 443 Gateway' ;;
        8)  printf 'KH    -> Xray/VLESS loopback' ;;
        9)  printf 'PANEL -> Backhaul' ;;
        10) printf 'BOTH  -> Final + Reboot tests' ;;
        *)  printf 'Unknown step' ;;
    esac
}

smite_setup_ui_required_host() {
    case "$1" in
        1|10) printf 'BOTH' ;;
        2|3|6|8) printf 'KH / Foreign' ;;
        4|5|7) printf 'IR / Panel' ;;
        9) printf 'Smite Panel' ;;
        *) printf 'Unknown' ;;
    esac
}

smite_setup_ui_status_text() {
    case "$1" in
        done) printf 'VERIFIED' ;;
        partial) printf 'PARTIAL' ;;
        *) printf 'NOT VERIFIED' ;;
    esac
}

smite_setup_ui_step_purpose() {
    case "$1" in
        1)
            cat <<'EOF'
Prepare Docker Engine, Docker Compose, and the Docker service on both hosts.
Both servers must have a working Docker runtime before the Smite stack is installed.
EOF
            ;;
        2)
            cat <<'EOF'
Install the Sanaei 3x-UI Docker instance on KH first.
Its U-OPTI-managed Nginx/SSL vhost is also reused by the EasyTier WSS endpoint.
EOF
            ;;
        3)
            cat <<'EOF'
Initialize EasyTier on KH as the Foreign side of the private overlay.
KH receives 10.89.10.20/24 and exposes the hidden EasyTier WSS path through its existing TLS/443 vhost.
EOF
            ;;
        4)
            cat <<'EOF'
Initialize EasyTier on IR as the Panel side using the pairing information created on KH.
IR receives 10.89.10.10/24 and must reach KH over the private overlay.
EOF
            ;;
        5)
            cat <<'EOF'
Install the Smite Panel and the local Iran node in Private Network mode.
The local Panel API remains available on the Iran host while the private overlay is used for cross-host control traffic.
EOF
            ;;
        6)
            cat <<'EOF'
Install the Smite Foreign node on KH in Private Network mode.
Panel -> Foreign control must remain on the EasyTier private address http://10.89.10.20:8888.
EOF
            ;;
        7)
            cat <<'EOF'
Configure the IR Panel TCP/443 gateway before creating the first Backhaul tunnel.
Nginx owns public TCP/443, Panel TLS goes to 127.0.0.1:8443, and 127.0.0.1:9443 is reserved for future Backhaul data.
EOF
            ;;
        8)
            cat <<'EOF'
Create the Xray/VLESS inbound on KH and bind it to loopback only.
Then register its non-secret TCP port in this Wizard so U-OPTI can verify the listener before Backhaul is created.
EOF
            ;;
        9)
            cat <<'EOF'
Create the Smite Backhaul tunnel from the Panel with logical/public port 443.
The custom target must point to the KH Xray loopback port selected in Step 8.
EOF
            ;;
        10)
            cat <<'EOF'
Run the final end-to-end client test, then verify persistence across host reboots.
Use the reboot baseline/validation actions separately on KH and IR so the Wizard can confirm that each host really rebooted and recovered.
EOF
            ;;
    esac
}

smite_setup_ui_step_path() {
    case "$1" in
        1)
            cat <<'EOF'
BOTH servers:
U-OPTI -> Docker Management -> Install Docker
EOF
            ;;
        2)
            cat <<'EOF'
KH:
U-OPTI -> Docker Management -> 3x-UI Docker Management
-> Install 3x-UI in Docker
EOF
            ;;
        3)
            cat <<'EOF'
KH:
U-OPTI -> Docker Management -> Smite Management
-> EasyTier Private Network -> Initialize Foreign / KH
-> Show Pairing Details
EOF
            ;;
        4)
            cat <<'EOF'
IR:
U-OPTI -> Docker Management -> Smite Management
-> EasyTier Private Network -> Initialize Panel / Iran
EOF
            ;;
        5)
            cat <<'EOF'
IR:
U-OPTI -> Docker Management -> Smite Management
-> Install Smite Components -> Install Panel + Iran Node
-> Private Network
EOF
            ;;
        6)
            cat <<'EOF'
KH:
U-OPTI -> Docker Management -> Smite Management
-> Install Smite Components -> Install Foreign Node
-> Private Network
EOF
            ;;
        7)
            cat <<'EOF'
IR:
U-OPTI -> Docker Management -> Smite Management
-> Panel 443 Gateway (Iran) -> Configure / Repair Panel Gateway
EOF
            ;;
        8)
            cat <<'EOF'
KH:
Open the managed 3x-UI panel and create the desired Xray/VLESS inbound.
Listen address must be loopback, for example 127.0.0.1:10000.
Then return to this Wizard and open Step 8.
EOF
            ;;
        9)
            cat <<'EOF'
Smite Panel:
Create Backhaul -> TCP -> Control Port 3080 -> logical Port 443
Advanced / Custom Ports:
443=127.0.0.1:<Step-8-Xray-port>
EOF
            ;;
        10)
            cat <<'EOF'
BOTH servers, one host at a time:
1. Confirm the client works end-to-end.
2. Open Step 10 and record the reboot baseline on this host.
3. Exit the Wizard and run: reboot
4. Reconnect after the host returns.
5. Open Step 10 again and validate after reboot.
6. Repeat on the peer host.
EOF
            ;;
    esac
}

smite_setup_ui_current_host_matches() {
    local step="$1" role
    role="$(smite_setup_progress_host_role)"

    case "$step" in
        1|10) return 0 ;;
        2|3|6|8) [ "$role" = "foreign" ] ;;
        4|5|7|9) [ "$role" = "panel-iran" ] ;;
        *) return 1 ;;
    esac
}

smite_setup_ui_show_step_details() {
    local step="$1" status detail role mode

    smite_setup_progress_collect
    status="${SMITE_SETUP_STATUS[$step]:-todo}"
    detail="${SMITE_SETUP_DETAIL[$step]:-No verification detail is available.}"
    role="$(smite_setup_progress_host_role)"
    mode="$(smite_setup_progress_mode)"

    clear
    echo "======================================"
    printf ' Step %s Details\n' "$step"
    echo "======================================"
    echo
    echo "Title         : $(smite_setup_ui_step_title "$step")"
    echo "Required host : $(smite_setup_ui_required_host "$step")"
    echo "Current host  : ${role:-not detected}"
    echo "Mode          : ${mode:-not detected}"
    echo "Status        : $(smite_setup_ui_status_text "$status") $(smite_setup_progress_symbol "$status")"
    echo
    echo "Purpose:"
    smite_setup_ui_step_purpose "$step"
    echo
    echo "Path / procedure:"
    smite_setup_ui_step_path "$step"
    echo
    echo "Current verification:"
    echo "$detail"
    echo
    echo "This page is read-only. No settings were changed."
    smite_setup_progress_pause
}

smite_setup_ui_step_generic() {
    local step="$1" status detail

    smite_setup_progress_collect
    status="${SMITE_SETUP_STATUS[$step]:-todo}"
    detail="${SMITE_SETUP_DETAIL[$step]:-No verification detail is available.}"

    clear
    echo "======================================"
    printf ' Step %s - %s\n' "$step" "$(smite_setup_ui_step_title "$step")"
    echo "======================================"
    echo
    echo "Required host : $(smite_setup_ui_required_host "$step")"
    echo "Current host  : $(smite_setup_progress_host_role)"
    echo "Status        : $(smite_setup_ui_status_text "$status") $(smite_setup_progress_symbol "$status")"
    echo
    echo "Current check :"
    echo "$detail"
    echo

    if ! smite_setup_ui_current_host_matches "$step"; then
        echo "This step belongs to another host."
        echo "Use .$step from the main Wizard page to read its full instructions here,"
        echo "then switch to the required server to perform or verify it."
        echo
        echo "No changes were made."
        smite_setup_progress_pause
        return
    fi

    echo "Procedure:"
    smite_setup_ui_step_path "$step"
    echo
    echo "No installation or repair is started automatically from this page."
    smite_setup_progress_pause
}

smite_setup_ui_step_xray() {
    local status detail port choice role
    role="$(smite_setup_progress_host_role)"
    smite_setup_progress_collect
    status="${SMITE_SETUP_STATUS[8]:-todo}"
    detail="${SMITE_SETUP_DETAIL[8]:-No verification detail is available.}"
    port="$(smite_setup_progress_xray_port)"

    clear
    echo "======================================"
    echo " Step 8 - KH -> Xray/VLESS loopback"
    echo "======================================"
    echo
    echo "Required host : KH / Foreign"
    echo "Current host  : ${role:-not detected}"
    echo "Status        : $(smite_setup_ui_status_text "$status") $(smite_setup_progress_symbol "$status")"
    echo "Saved port    : ${port:-not set}"
    echo
    echo "Current check :"
    echo "$detail"
    echo

    if [ "$role" != "foreign" ]; then
        echo "This step must be completed on the KH / Foreign server."
        echo "Use .8 for the full read-only instructions."
        echo
        echo "No changes were made."
        smite_setup_progress_pause
        return
    fi

    echo "1) Set / Verify Xray Target Port"
    echo "2) Show Step Details"
    echo
    echo "0) Back"
    echo
    read -rp "Please enter your selection [0-2]: " choice
    case "$choice" in
        1) smite_setup_progress_set_xray_port ;;
        2) smite_setup_ui_show_step_details 8 ;;
        0) return ;;
        *) echo; echo "Invalid selection!"; sleep 2 ;;
    esac
}

smite_setup_ui_step_reboot() {
    local status detail choice
    smite_setup_progress_collect
    status="${SMITE_SETUP_STATUS[10]:-todo}"
    detail="${SMITE_SETUP_DETAIL[10]:-No verification detail is available.}"

    clear
    echo "======================================"
    echo " Step 10 - Final + Reboot tests"
    echo "======================================"
    echo
    echo "Required host : BOTH (one host at a time)"
    echo "Current host  : $(smite_setup_progress_host_role)"
    echo "Status        : $(smite_setup_ui_status_text "$status") $(smite_setup_progress_symbol "$status")"
    echo
    echo "Current check :"
    echo "$detail"
    echo
    echo "1) Record Reboot Baseline (does not reboot)"
    echo "2) Validate This Host After Reboot"
    echo "3) Show Step Details"
    echo
    echo "After option 1, exit and run 'reboot', then return and use option 2."
    echo
    echo "0) Back"
    echo
    read -rp "Please enter your selection [0-3]: " choice
    case "$choice" in
        1) smite_setup_progress_prepare_reboot ;;
        2) smite_setup_progress_validate_after_reboot ;;
        3) smite_setup_ui_show_step_details 10 ;;
        0) return ;;
        *) echo; echo "Invalid selection!"; sleep 2 ;;
    esac
}

smite_setup_ui_open_step() {
    case "$1" in
        8) smite_setup_ui_step_xray ;;
        10) smite_setup_ui_step_reboot ;;
        1|2|3|4|5|6|7|9) smite_setup_ui_step_generic "$1" ;;
        *) echo "Invalid setup step."; sleep 1 ;;
    esac
}

smite_setup_ui_render_detail_choices() {
    echo "Step Details"
    echo "--------------------------------------"
    echo ".1)  BOTH  -> Docker"
    echo ".2)  KH    -> 3x-UI"
    echo ".3)  KH    -> EasyTier Foreign"
    echo ".4)  IR    -> EasyTier Panel"
    echo ".5)  IR    -> Smite Panel + Iran Node"
    echo ".6)  KH    -> Smite Foreign Node"
    echo ".7)  IR    -> Panel 443 Gateway"
    echo ".8)  KH    -> Xray/VLESS loopback"
    echo ".9)  PANEL -> Backhaul"
    echo ".10) BOTH  -> Final + Reboot tests"
    echo "--------------------------------------"
}

show_smite_setup_progress_menu() {
    local choice step

    if ! smite_setup_ui_require_core; then
        clear
        echo "ERROR: Smite setup progress core module is not loaded."
        echo "Expected: $SMITE_SETUP_UI_DIR/smite-setup-progress.sh"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    while true; do
        smite_setup_progress_render
        echo
        smite_setup_ui_render_detail_choices
        echo
        echo "Enter:"
        echo "  1-10   Open step"
        echo "  .1-.10 Show step details"
        echo "  n      Show next step"
        echo "  r      Refresh progress"
        echo "  0      Back"
        echo
        read -rp "Selection: " choice

        case "$choice" in
            0) break ;;
            n|N) smite_setup_progress_show_next ;;
            r|R) : ;;
            1|2|3|4|5|6|7|8|9|10)
                smite_setup_ui_open_step "$choice"
                ;;
            .1|.2|.3|.4|.5|.6|.7|.8|.9|.10)
                step="${choice#.}"
                smite_setup_ui_show_step_details "$step"
                ;;
            *)
                echo
                echo "Invalid selection! Use 1-10, .1-.10, n, r, or 0."
                sleep 2
                ;;
        esac
    done
}
