#!/bin/bash

# U-OPTI - Smite Private Setup Progress flow semantics
#
# Presentation / sequencing rules for the clean-install Wizard:
#   [✓] = verified/completed on this host (or directly observable peer state)
#   [~] = the single next recommended setup step
#   [ ] = pending
#
# This layer intentionally keeps the runtime verification core separate from
# the workflow marker semantics. It also treats Docker as complete once it is
# verified on the current host; the peer host has its own Wizard and must
# verify Docker there separately.

if declare -F smite_setup_progress_collect >/dev/null 2>&1 && \
   ! declare -F smite_setup_progress_collect_base >/dev/null 2>&1; then
    eval "$(declare -f smite_setup_progress_collect | sed '1s/^smite_setup_progress_collect /smite_setup_progress_collect_base /')"
fi

smite_setup_progress_collect() {
    local i

    smite_setup_progress_collect_base

    # Step 1 is a BOTH-host requirement, but each host verifies its own Docker
    # runtime independently. Once Docker is healthy locally, mark this host's
    # Step 1 complete instead of leaving it in an ambiguous partial state.
    if smite_setup_progress_docker_local; then
        SMITE_SETUP_STATUS[1]="done"
        SMITE_SETUP_DETAIL[1]="Docker Engine, Docker Compose, and Docker service verified on this server"
    else
        SMITE_SETUP_STATUS[1]="todo"
        SMITE_SETUP_DETAIL[1]="Docker Engine/Compose is not ready on this server"
    fi

    # The main Wizard reserves [~] exclusively for "next step". Convert old
    # partial evidence into pending state so there is never more than one [~]
    # marker on the progress page.
    for i in 2 3 4 5 6 7 8 9; do
        if [ "${SMITE_SETUP_STATUS[$i]:-todo}" = "partial" ]; then
            SMITE_SETUP_STATUS[$i]="todo"
        fi
    done

    # Final reboot validation is also host-local. The peer host validates its
    # own reboot independently in its own Wizard session.
    if smite_setup_progress_reboot_local_complete; then
        SMITE_SETUP_STATUS[10]="done"
        SMITE_SETUP_DETAIL[10]="This server passed post-reboot validation; validate the peer server separately"
    else
        SMITE_SETUP_STATUS[10]="todo"
        SMITE_SETUP_DETAIL[10]="Prepare and validate reboot on this host after end-to-end testing"
    fi
}

smite_setup_progress_next_step() {
    local i status
    for i in 1 2 3 4 5 6 7 8 9 10; do
        status="${SMITE_SETUP_STATUS[$i]:-todo}"
        if [ "$status" != "done" ]; then
            printf '%s' "$i"
            return 0
        fi
    done
    printf ''
}

smite_setup_progress_following_step() {
    local current="$1" i status
    [ -n "$current" ] || { printf ''; return 0; }

    for ((i=current + 1; i<=10; i++)); do
        status="${SMITE_SETUP_STATUS[$i]:-todo}"
        if [ "$status" != "done" ]; then
            printf '%s' "$i"
            return 0
        fi
    done
    printf ''
}

smite_setup_progress_step_host() {
    case "$1" in
        1) printf 'BOTH' ;;
        2|3|6|8) printf 'KH / Foreign' ;;
        4|5|7) printf 'IR / Panel' ;;
        9) printf 'IR / Smite Panel' ;;
        10) printf 'BOTH' ;;
        *) printf 'Unknown' ;;
    esac
}

smite_setup_progress_step_action() {
    case "$1" in
        1) printf 'Install / verify Docker on this server' ;;
        2) printf 'Install 3x-UI in Docker' ;;
        3) printf 'Initialize EasyTier Foreign' ;;
        4) printf 'Initialize EasyTier Panel' ;;
        5) printf 'Install Smite Panel + Iran Node' ;;
        6) printf 'Install Smite Foreign Node' ;;
        7) printf 'Configure Panel 443 Gateway' ;;
        8) printf 'Create / verify Xray loopback target' ;;
        9) printf 'Create and verify Backhaul tunnel' ;;
        10) printf 'Run final test + reboot validation' ;;
        *) printf 'Unknown action' ;;
    esac
}

smite_setup_progress_main_symbol() {
    local step="$1" next="$2" status
    status="${SMITE_SETUP_STATUS[$step]:-todo}"

    if [ "$status" = "done" ]; then
        printf '[✓]'
    elif [ -n "$next" ] && [ "$step" = "$next" ]; then
        printf '[~]'
    else
        printf '[ ]'
    fi
}

smite_setup_progress_render() {
    local role mode i done_count=0 next following
    role="$(smite_setup_progress_host_role)"
    mode="$(smite_setup_progress_mode)"

    smite_setup_progress_collect

    for i in 1 2 3 4 5 6 7 8 9 10; do
        [ "${SMITE_SETUP_STATUS[$i]:-todo}" = "done" ] && done_count=$((done_count + 1))
    done

    next="$(smite_setup_progress_next_step)"
    following="$(smite_setup_progress_following_step "$next")"

    clear
    echo "======================================"
    echo "     Smite Private Setup Progress"
    echo "======================================"
    echo
    echo "Host role : ${role:-not detected}"
    echo "Mode      : ${mode:-not detected}"
    echo
    printf '%s 1. BOTH  -> Docker\n' "$(smite_setup_progress_main_symbol 1 "$next")"
    printf '%s 2. KH    -> 3x-UI\n' "$(smite_setup_progress_main_symbol 2 "$next")"
    printf '%s 3. KH    -> EasyTier Foreign\n' "$(smite_setup_progress_main_symbol 3 "$next")"
    printf '%s 4. IR    -> EasyTier Panel\n' "$(smite_setup_progress_main_symbol 4 "$next")"
    printf '%s 5. IR    -> Smite Panel + Iran Node\n' "$(smite_setup_progress_main_symbol 5 "$next")"
    printf '%s 6. KH    -> Smite Foreign Node\n' "$(smite_setup_progress_main_symbol 6 "$next")"
    printf '%s 7. IR    -> Panel 443 Gateway\n' "$(smite_setup_progress_main_symbol 7 "$next")"
    printf '%s 8. KH    -> Xray/VLESS loopback\n' "$(smite_setup_progress_main_symbol 8 "$next")"
    printf '%s 9. PANEL -> Backhaul\n' "$(smite_setup_progress_main_symbol 9 "$next")"
    printf '%s 10. BOTH -> Final + Reboot tests\n' "$(smite_setup_progress_main_symbol 10 "$next")"
    echo
    echo "--------------------------------------"
    echo "Verified : $done_count / 10"
    if [ -n "$next" ]; then
        echo "Next     : Step $next | $(smite_setup_progress_step_host "$next") | $(smite_setup_progress_step_action "$next")"
        if [ -n "$following" ]; then
            echo "Then     : Step $following | $(smite_setup_progress_step_host "$following") | $(smite_setup_progress_step_action "$following")"
        fi
    else
        echo "Next     : All 10 steps are verified on this server"
    fi
    echo "--------------------------------------"
    echo
    echo "Legend: [✓] verified   [~] next recommended step   [ ] pending"
}

smite_setup_progress_show_next() {
    local next following
    smite_setup_progress_collect
    next="$(smite_setup_progress_next_step)"

    clear
    echo "======================================"
    echo "         Smite Next Setup Step"
    echo "======================================"
    echo

    if [ -z "$next" ]; then
        echo "All 10 steps are verified on this server."
        smite_setup_progress_pause
        return
    fi

    following="$(smite_setup_progress_following_step "$next")"
    echo "Next:"
    echo "  Step $next | $(smite_setup_progress_step_host "$next")"
    echo "  $(smite_setup_progress_step_action "$next")"
    echo
    echo "Current check:"
    echo "${SMITE_SETUP_DETAIL[$next]}"

    if [ -n "$following" ]; then
        echo
        echo "After that:"
        echo "  Step $following | $(smite_setup_progress_step_host "$following")"
        echo "  $(smite_setup_progress_step_action "$following")"
    fi

    smite_setup_progress_pause
}
