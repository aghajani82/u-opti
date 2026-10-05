#!/bin/bash

# U-OPTI - Smite Private Setup Progress Actions
# Action layer for the clean-install Wizard.
#
# This module intentionally keeps installation/repair actions explicit:
# selecting a setup step opens its page first; the user must then choose
# the action to run. The only extra persistent value introduced here is a
# non-secret provisional Wizard host role used before Smite/EasyTier state
# exists on a freshly rebuilt server.

SMITE_SETUP_ACTIONS_STATE="${SMITE_SETUP_PROGRESS_STATE:-/etc/u-opti/smite/setup-progress/state.env}"

smite_setup_actions_pause() {
    echo
    read -rp "Press Enter to return..."
}

smite_setup_actions_actual_role() {
    local role et_role

    role="$(smite_setup_progress_sm_state SMITE_ROLE 2>/dev/null || true)"
    if [ -n "$role" ]; then
        printf '%s' "$role"
        return 0
    fi

    et_role="$(smite_setup_progress_et_state SMITE_ET_ROLE 2>/dev/null || true)"
    case "$et_role" in
        panel) printf 'panel-iran' ;;
        foreign) printf 'foreign' ;;
        *) printf '' ;;
    esac
}

# Override the core host-role resolver with one extra, safe fallback for
# brand-new hosts. Real Smite/EasyTier state always wins once it exists.
smite_setup_progress_host_role() {
    local actual provisional

    actual="$(smite_setup_actions_actual_role)"
    if [ -n "$actual" ]; then
        printf '%s' "$actual"
        return 0
    fi

    provisional="$(smite_setup_progress_value SMITE_SETUP_HOST_ROLE "$SMITE_SETUP_ACTIONS_STATE" 2>/dev/null || true)"
    case "$provisional" in
        panel-iran|foreign) printf '%s' "$provisional" ;;
        *) printf '' ;;
    esac
}

smite_setup_actions_role_label() {
    case "$1" in
        panel-iran) printf 'IR / Panel' ;;
        foreign) printf 'KH / Foreign' ;;
        *) printf 'not selected' ;;
    esac
}

smite_setup_actions_select_host_role() {
    local actual current choice selected

    actual="$(smite_setup_actions_actual_role)"
    if [ -n "$actual" ]; then
        clear
        echo "======================================"
        echo "        Wizard Host Role"
        echo "======================================"
        echo
        echo "A real Smite/EasyTier role is already configured on this host."
        echo "Detected role : $(smite_setup_actions_role_label "$actual")"
        echo
        echo "The Wizard will follow the real runtime state and will not override it."
        smite_setup_actions_pause
        return 0
    fi

    current="$(smite_setup_progress_value SMITE_SETUP_HOST_ROLE "$SMITE_SETUP_ACTIONS_STATE" 2>/dev/null || true)"

    while true; do
        clear
        echo "======================================"
        echo "      Select This Server Role"
        echo "======================================"
        echo
        echo "This is a fresh host, so Smite/EasyTier has not created a role yet."
        echo "Choose which server this Wizard is running on."
        echo
        echo "This choice is only Wizard bookkeeping."
        echo "It does not configure Smite, EasyTier, Nginx, or Docker."
        echo
        if [ -n "$current" ]; then
            echo "Current Wizard role: $(smite_setup_actions_role_label "$current")"
            echo
        fi
        echo "1) IR / Panel server"
        echo "2) KH / Foreign server"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-2]: " choice

        case "$choice" in
            1) selected="panel-iran" ;;
            2) selected="foreign" ;;
            0) return 1 ;;
            *) echo; echo "Invalid selection!"; sleep 2; continue ;;
        esac

        if ! smite_setup_progress_set_value SMITE_SETUP_HOST_ROLE "$selected"; then
            echo "ERROR: Could not save the Wizard host role."
            smite_setup_actions_pause
            return 1
        fi

        echo
        echo "Wizard host role saved: $(smite_setup_actions_role_label "$selected")"
        echo "Real Smite/EasyTier state will automatically take priority later."
        sleep 1
        return 0
    done
}

smite_setup_actions_initial_role_prompt() {
    local role
    role="$(smite_setup_progress_host_role)"
    [ -n "$role" ] && return 0

    smite_setup_actions_select_host_role || return 1
}

smite_setup_actions_status_line() {
    local step="$1" status
    smite_setup_progress_collect
    status="${SMITE_SETUP_STATUS[$step]:-todo}"
    printf '%s %s' "$(smite_setup_progress_symbol "$status")" "$(smite_setup_ui_status_text "$status")"
}

smite_setup_actions_wrong_host() {
    local step="$1" role
    role="$(smite_setup_progress_host_role)"

    clear
    echo "======================================"
    printf ' Step %s - %s\n' "$step" "$(smite_setup_ui_step_title "$step")"
    echo "======================================"
    echo
    echo "Required host : $(smite_setup_ui_required_host "$step")"
    echo "Current host  : $(smite_setup_actions_role_label "$role")"
    echo
    echo "This step belongs to the other server."
    echo "No settings were changed."
    echo
    echo "Use .$step from the main Wizard page to read the full instructions."
    smite_setup_actions_pause
}

smite_setup_actions_step_docker() {
    local choice status detail

    while true; do
        smite_setup_progress_collect
        status="${SMITE_SETUP_STATUS[1]:-todo}"
        detail="${SMITE_SETUP_DETAIL[1]:-No verification detail is available.}"

        clear
        echo "======================================"
        echo " Step 1 - BOTH -> Docker"
        echo "======================================"
        echo
        echo "Required host : BOTH"
        echo "Current host  : $(smite_setup_actions_role_label "$(smite_setup_progress_host_role)")"
        echo "Status        : $(smite_setup_progress_symbol "$status") $(smite_setup_ui_status_text "$status")"
        echo
        echo "Current check:"
        echo "$detail"
        echo
        echo "1) Install / Verify Docker on This Host"
        echo "2) Show Step Details"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-2]: " choice

        case "$choice" in
            1)
                if declare -F docker_install >/dev/null 2>&1; then
                    docker_install
                else
                    echo "ERROR: U-OPTI Docker installer is not loaded in this Wizard session."
                    smite_setup_actions_pause
                fi
                ;;
            2) smite_setup_ui_show_step_details 1 ;;
            0) return ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}

smite_setup_actions_step_3xui() {
    local role choice status detail
    role="$(smite_setup_progress_host_role)"
    [ -n "$role" ] || { smite_setup_actions_select_host_role || return; role="$(smite_setup_progress_host_role)"; }

    if [ "$role" != "foreign" ]; then
        smite_setup_actions_wrong_host 2
        return
    fi

    while true; do
        smite_setup_progress_collect
        status="${SMITE_SETUP_STATUS[2]:-todo}"
        detail="${SMITE_SETUP_DETAIL[2]:-No verification detail is available.}"

        clear
        echo "======================================"
        echo " Step 2 - KH -> 3x-UI"
        echo "======================================"
        echo
        echo "Required host : KH / Foreign"
        echo "Current host  : KH / Foreign"
        echo "Status        : $(smite_setup_progress_symbol "$status") $(smite_setup_ui_status_text "$status")"
        echo
        echo "Current check:"
        echo "$detail"
        echo
        echo "1) Install 3x-UI in Docker"
        echo "2) Open 3x-UI Docker Management"
        echo "3) Show Step Details"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-3]: " choice

        case "$choice" in
            1)
                if ! smite_setup_progress_docker_local; then
                    echo
                    echo "Docker is not ready on this host. Complete Step 1 first."
                    smite_setup_actions_pause
                elif declare -F docker_3xui_install >/dev/null 2>&1; then
                    docker_3xui_install
                else
                    echo "ERROR: 3x-UI Docker installer is not loaded."
                    smite_setup_actions_pause
                fi
                ;;
            2)
                if declare -F show_docker_3xui_menu >/dev/null 2>&1; then
                    show_docker_3xui_menu
                else
                    echo "ERROR: 3x-UI Docker Management is not loaded."
                    smite_setup_actions_pause
                fi
                ;;
            3) smite_setup_ui_show_step_details 2 ;;
            0) return ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}

smite_setup_actions_step_easytier() {
    local step="$1" required_role="$2" role choice status detail
    role="$(smite_setup_progress_host_role)"
    [ -n "$role" ] || { smite_setup_actions_select_host_role || return; role="$(smite_setup_progress_host_role)"; }

    if [ "$role" != "$required_role" ]; then
        smite_setup_actions_wrong_host "$step"
        return
    fi

    while true; do
        smite_setup_progress_collect
        status="${SMITE_SETUP_STATUS[$step]:-todo}"
        detail="${SMITE_SETUP_DETAIL[$step]:-No verification detail is available.}"

        clear
        echo "======================================"
        printf ' Step %s - %s\n' "$step" "$(smite_setup_ui_step_title "$step")"
        echo "======================================"
        echo
        echo "Required host : $(smite_setup_ui_required_host "$step")"
        echo "Current host  : $(smite_setup_actions_role_label "$role")"
        echo "Status        : $(smite_setup_progress_symbol "$status") $(smite_setup_ui_status_text "$status")"
        echo
        echo "Current check:"
        echo "$detail"
        echo
        echo "1) Open EasyTier Private Network Setup"
        echo "2) Show Step Details"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-2]: " choice

        case "$choice" in
            1)
                if declare -F show_smite_easytier_menu >/dev/null 2>&1; then
                    show_smite_easytier_menu
                elif declare -F show_smite_private_network_menu >/dev/null 2>&1; then
                    show_smite_private_network_menu
                else
                    echo "ERROR: EasyTier Private Network setup is not loaded."
                    smite_setup_actions_pause
                fi
                ;;
            2) smite_setup_ui_show_step_details "$step" ;;
            0) return ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}

smite_setup_actions_step_smite_install() {
    local step="$1" required_role="$2" role choice status detail
    role="$(smite_setup_progress_host_role)"
    [ -n "$role" ] || { smite_setup_actions_select_host_role || return; role="$(smite_setup_progress_host_role)"; }

    if [ "$role" != "$required_role" ]; then
        smite_setup_actions_wrong_host "$step"
        return
    fi

    while true; do
        smite_setup_progress_collect
        status="${SMITE_SETUP_STATUS[$step]:-todo}"
        detail="${SMITE_SETUP_DETAIL[$step]:-No verification detail is available.}"

        clear
        echo "======================================"
        printf ' Step %s - %s\n' "$step" "$(smite_setup_ui_step_title "$step")"
        echo "======================================"
        echo
        echo "Required host : $(smite_setup_ui_required_host "$step")"
        echo "Current host  : $(smite_setup_actions_role_label "$role")"
        echo "Status        : $(smite_setup_progress_symbol "$status") $(smite_setup_ui_status_text "$status")"
        echo
        echo "Current check:"
        echo "$detail"
        echo
        echo "1) Open Smite Component Installer"
        echo "2) Show Step Details"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-2]: " choice

        case "$choice" in
            1)
                if declare -F show_smite_install_menu >/dev/null 2>&1; then
                    show_smite_install_menu
                else
                    echo "ERROR: Smite Component Installer is not loaded."
                    smite_setup_actions_pause
                fi
                ;;
            2) smite_setup_ui_show_step_details "$step" ;;
            0) return ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}

smite_setup_actions_step_gateway() {
    local role choice status detail
    role="$(smite_setup_progress_host_role)"
    [ -n "$role" ] || { smite_setup_actions_select_host_role || return; role="$(smite_setup_progress_host_role)"; }

    if [ "$role" != "panel-iran" ]; then
        smite_setup_actions_wrong_host 7
        return
    fi

    while true; do
        smite_setup_progress_collect
        status="${SMITE_SETUP_STATUS[7]:-todo}"
        detail="${SMITE_SETUP_DETAIL[7]:-No verification detail is available.}"

        clear
        echo "======================================"
        echo " Step 7 - IR -> Panel 443 Gateway"
        echo "======================================"
        echo
        echo "Required host : IR / Panel"
        echo "Current host  : IR / Panel"
        echo "Status        : $(smite_setup_progress_symbol "$status") $(smite_setup_ui_status_text "$status")"
        echo
        echo "Current check:"
        echo "$detail"
        echo
        echo "1) Open Panel 443 Gateway Management"
        echo "2) Show Step Details"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-2]: " choice

        case "$choice" in
            1)
                if declare -F show_smite_gateway_menu >/dev/null 2>&1; then
                    show_smite_gateway_menu
                else
                    echo "ERROR: Panel 443 Gateway module is not loaded."
                    smite_setup_actions_pause
                fi
                ;;
            2) smite_setup_ui_show_step_details 7 ;;
            0) return ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}

smite_setup_actions_step_backhaul() {
    local role status detail
    role="$(smite_setup_progress_host_role)"
    [ -n "$role" ] || { smite_setup_actions_select_host_role || return; role="$(smite_setup_progress_host_role)"; }

    if [ "$role" != "panel-iran" ]; then
        smite_setup_actions_wrong_host 9
        return
    fi

    smite_setup_progress_collect
    status="${SMITE_SETUP_STATUS[9]:-todo}"
    detail="${SMITE_SETUP_DETAIL[9]:-No verification detail is available.}"

    clear
    echo "======================================"
    echo " Step 9 - PANEL -> Backhaul"
    echo "======================================"
    echo
    echo "Required host : IR / Panel"
    echo "Current host  : IR / Panel"
    echo "Status        : $(smite_setup_progress_symbol "$status") $(smite_setup_ui_status_text "$status")"
    echo
    echo "Current check:"
    echo "$detail"
    echo
    echo "Backhaul tunnel creation is performed in the Smite web panel."
    echo "No tunnel is created automatically from this shell Wizard."
    echo
    smite_setup_ui_step_path 9
    smite_setup_actions_pause
}

# Override the UI dispatcher so the main 1..10 list is not merely a read-only
# checklist: each setup step now opens the relevant explicit action page.
smite_setup_ui_open_step() {
    case "$1" in
        1) smite_setup_actions_step_docker ;;
        2) smite_setup_actions_step_3xui ;;
        3) smite_setup_actions_step_easytier 3 foreign ;;
        4) smite_setup_actions_step_easytier 4 panel-iran ;;
        5) smite_setup_actions_step_smite_install 5 panel-iran ;;
        6) smite_setup_actions_step_smite_install 6 foreign ;;
        7) smite_setup_actions_step_gateway ;;
        8) smite_setup_ui_step_xray ;;
        9) smite_setup_actions_step_backhaul ;;
        10) smite_setup_ui_step_reboot ;;
        *) echo "Invalid setup step."; sleep 1 ;;
    esac
}
