#!/usr/bin/env bash
# U-OPTI Tunnel Control Center — read-only local dashboard and safe navigation.
# Sourced by smite-tunnel-wizard.sh. No live mutation is performed here.
# FRP setup is delegated ONLY when the operator explicitly selects its wizard.
# "LOCAL READY" is NOT a claim of an authenticated end-to-end tunnel.

twcc_badge() {
    local status="$1" color
    case "$status" in
        LOCAL-READY|IR-CONTROLLER-SEEN|SMITE-NODE-SEEN) color=32 ;;
        REVIEW-BINDING|NEEDS-REVIEW) color=31 ;;
        *) color=33 ;;
    esac
    if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ -z "${NO_COLOR+x}" ]; then
        printf '\033[1;%sm[%s]\033[0m' "$color" "$status"
    else
        printf '[%s]' "$status"
    fi
}

twcc_line() { printf '%s\n' '------------------------------------------------------------'; }

twcc_header() {
    printf '\n'
    printf '%s\n' '============================================================'
    printf '%s\n' '             U-OPTI  |  TUNNEL CONTROL CENTER'
    printf '%s\n' '============================================================'
    printf '  Machine role : %s\n' "$1"
    printf '%s\n' '  Mode         : LOCAL INSPECTION / NO AUTO-CHANGES'
    twcc_line
}

twcc_container() {
    local found
    if ! command -v docker >/dev/null 2>&1; then
        printf 'unknown\n'
        return
    fi
    found="$(docker inspect -f '{{.State.Running}}|{{.HostConfig.RestartPolicy.Name}}' "$1" 2>/dev/null)" || {
        printf 'absent\n'
        return
    }
    case "$found" in
        'true|unless-stopped'|'true|always') printf 'ready\n' ;;
        'true|'*) printf 'manual-restart\n' ;;
        'false|'*) printf 'stopped\n' ;;
        *) printf 'unknown\n' ;;
    esac
}

twcc_listener() {
    # Return a CATEGORY, never a public/private address from the host.
    # Every matching binding must be an IPv4 loopback listener.
    local port="$1" record found=0 lines address
    case "$port" in 7000|3080|56053|13080) ;; *) printf 'unknown\n'; return ;; esac
    if ! command -v ss >/dev/null 2>&1; then
        printf 'unknown\n'
        return
    fi
    lines="$(ss -H -lnt "( sport = :$port )" 2>/dev/null)" || {
        printf 'unknown\n'
        return
    }
    while IFS= read -r record; do
        [ -n "$record" ] || continue
        found=1
        address="$(printf '%s\n' "$record" | awk '{print $4}')"
        case "$address" in
            "127.0.0.1:$port") ;;
            *) printf 'unsafe-bind\n'; return ;;
        esac
    done <<< "$lines"
    if [ "$found" = 1 ]; then
        printf 'loopback\n'
    else
        printf 'absent\n'
    fi
}

twcc_backhaul() {
    local role="$1" state first second
    case "$role" in
        ir)
            state="$(twcc_container uopti-backhaul-sidecar-ir)"
            first="$(twcc_listener 3080)"
            second="$(twcc_listener 56053)"
            ;;
        kh)
            state="$(twcc_container uopti-backhaul-sidecar-kh)"
            first="$(twcc_listener 13080)"
            second="$(twcc_listener 56053)"
            ;;
        *) printf 'UNVERIFIED\n'; return ;;
    esac
    if [ "$first" = unsafe-bind ] || [ "$second" = unsafe-bind ]; then
        printf 'REVIEW-BINDING\n'
    elif [ "$state" = ready ] && [ "$first" = loopback ] && [ "$second" = loopback ]; then
        printf 'LOCAL-READY\n'
    elif [ "$state" = absent ] && [ "$first" = absent ]; then
        # A KH Xray :56053 may exist without an installed Sidecar.
        printf 'NOT-INSTALLED\n'
    elif [ "$state" = unknown ] || [ "$first" = unknown ] || [ "$second" = unknown ]; then
        printf 'UNVERIFIED\n'
    else
        printf 'NEEDS-REVIEW\n'
    fi
}

twcc_frp() {
    local role="$1" state
    if [ "$role" = ir ]; then
        state="$(twcc_listener 7000)"
        case "$state" in
            loopback) printf 'IR-CONTROLLER-SEEN\n' ;;
            unsafe-bind) printf 'REVIEW-BINDING\n' ;;
            absent) printf 'NOT-SEEN\n' ;;
            *) printf 'UNVERIFIED\n' ;;
        esac
    elif [ "$role" = kh ]; then
        state="$(twcc_container smite-node)"
        case "$state" in
            ready|manual-restart) printf 'SMITE-NODE-SEEN\n' ;;
            absent) printf 'NOT-SEEN\n' ;;
            *) printf 'UNVERIFIED\n' ;;
        esac
    else
        printf 'UNVERIFIED\n'
    fi
}

twcc_status_text() {
    case "$1" in
        LOCAL-READY) printf 'Container + loopback listeners seen; audit still required' ;;
        NOT-INSTALLED) printf 'No independent Sidecar found locally' ;;
        REVIEW-BINDING) printf 'Unexpected public/non-loopback listener' ;;
        NEEDS-REVIEW) printf 'Sidecar or listeners require review' ;;
        IR-CONTROLLER-SEEN) printf 'IR FRP controller port seen (local only)' ;;
        SMITE-NODE-SEEN) printf 'Smite Node seen; FRP tunnel unverified' ;;
        NOT-SEEN) printf 'Expected local component not seen' ;;
        UNVERIFIED) printf 'Could not verify local state' ;;
        PLAN-ONLY) printf 'Design checklist only; no installer yet' ;;
        *) printf 'Unknown state' ;;
    esac
}

twcc_topology() {
    local role="$1"
    printf '\n%s\n' '  CONNECTION MAP  (reference architecture, not a live route)'
    if [ "$role" = ir ]; then
        printf '%s\n' '  CLIENT --TLS:443--> IR Nginx --WS--> Backhaul --to KH--> Xray'
    else
        printf '%s\n' '  IR Nginx --verified HTTPS--> KH Bridge --WS--> Sidecar --> Xray'
    fi
}

twcc_recommend() {
    local role="$1" bh="$2" frp="$3"
    twcc_line
    printf '%s\n' '  RECOMMENDED NEXT ACTION'
    case "$bh" in
        LOCAL-READY)
            printf '%s\n' '  1. Run full Sidecar audit for route and listener ownership.'
            printf '%s\n' '  2. Inspect IR and KH separately, then test actual VLESS/XHTTP.'
            printf '%s\n' '  3. HTTP 401/400 is NOT proof of tunnel connectivity.'
            ;;
        NOT-INSTALLED)
            printf '%s\n' '  1. Run Backhaul fresh-host preflight (read-only).'
            printf '%s\n' '  2. Review private Nginx and Sidecar plans before installation.'
            printf '%s\n' '  3. Automatic live Backhaul installation is NOT released.'
            ;;
        REVIEW-BINDING)
            printf '%s\n' '  HOLD: Unexpected listener exposure. Review binds/firewall.'
            printf '%s\n' '  Do not activate any new tunnel until it is resolved.'
            ;;
        *)
            printf '%s\n' '  HOLD: Use Backhaul local readiness audit to find the mismatch.'
            printf '%s\n' '  Do not restart/recreate existing Smite, FRP or Sidecar blindly.'
            ;;
    esac
    if [ "$frp" = NOT-SEEN ] || [ "$frp" = REVIEW-BINDING ]; then
        printf '%s\n' '  FRP: Inspect existing Smite/FRP before changing anything.'
    fi
    if [ "$role" = kh ]; then
        printf '%s\n' '  KH: Keep public /13080 forwarding blocked.'
    fi
}

twcc_dashboard() {
    local role="$1" mode="$2" bh frp
    case "$role" in ir|kh) ;; *) printf 'ERROR: Choose IR or KH.\n' >&2; return 2 ;; esac
    if [ "$mode" = demo ]; then
        bh=LOCAL-READY
        if [ "$role" = ir ]; then frp=IR-CONTROLLER-SEEN; else frp=SMITE-NODE-SEEN; fi
    else
        bh="$(twcc_backhaul "$role")"
        frp="$(twcc_frp "$role")"
    fi
    twcc_header "$role"
    if [ "$mode" = demo ]; then
        printf '%s\n' '  SAMPLE DISPLAY ONLY — no real service inspection'
    else
        printf '%s\n' '  Snapshot of LOCAL metadata only; no remote probe'
    fi
    printf '\n'
    printf '  BACKHAUL  '; twcc_badge "$bh"; printf '\n'
    printf '            %s\n' "$(twcc_status_text "$bh")"
    printf '  FRP       '; twcc_badge "$frp"; printf '\n'
    printf '            %s\n' "$(twcc_status_text "$frp")"
    printf '  RATHOLE   '; twcc_badge PLAN-ONLY; printf '\n'
    printf '            %s\n' "$(twcc_status_text PLAN-ONLY)"
    twcc_topology "$role"
    twcc_recommend "$role" "$bh" "$frp"
    twcc_line
    printf '%s\n' '  SAFETY: No secrets displayed. No files or services changed.'
    printf '%s\n' '  NOTE: A real two-host client test is always required.'
}

twcc_open_backhaul() {
    local role="$1"
    if declare -F smite_tw_backhaul_menu >/dev/null 2>&1; then
        smite_tw_backhaul_menu "$role"
    else
        printf '%s\n' 'Backhaul wizard unavailable; update the preview modules.'
    fi
}

twcc_open_frp() {
    if declare -F smite_frp_wizard_menu >/dev/null 2>&1; then
        printf '%s\n' 'Opening existing FRP wizard (may offer opt-in setup actions).'
        smite_frp_wizard_menu
    else
        printf '%s\n' 'FRP wizard unavailable; update the preview modules.'
    fi
}

twcc_open_rathole() {
    local role="$1"
    if declare -F smite_tw_rathole_menu >/dev/null 2>&1; then
        smite_tw_rathole_menu "$role"
    else
        printf '%s\n' 'Rathole planning menu unavailable.'
    fi
}

twcc_menu() {
    local role="$1" choice
    case "$role" in ir|kh) ;; *) printf 'ERROR: Unknown machine role.\n'; return 2 ;; esac
    while true; do
        if declare -F smite_tw_clear >/dev/null 2>&1; then smite_tw_clear; fi
        twcc_dashboard "$role" live
        printf '\n%s\n' '  1) Backhaul — inspect, preflight or prepare OFFLINE plan'
        printf '%s\n' '  2) FRP — open existing opt-in setup wizard'
        printf '%s\n' '  3) Rathole — safe topology/port planner'
        printf '%s\n' '  4) Refresh local snapshot'
        printf '%s\n' '  0) Back'
        read -rp '  Choose [0-4]: ' choice || return
        case "$choice" in
            1) twcc_open_backhaul "$role" ;;
            2) twcc_open_frp ;;
            3) twcc_open_rathole "$role" ;;
            4) : ;;
            0) return ;;
            *) printf '%s\n' 'Invalid selection.' ;;
        esac
    done
}

# Allows a pretty preview without ever touching the host:
# bash modules/smite-tunnel-control-center.sh --demo ir
if [[ "$0" == *smite-tunnel-control-center.sh ]]; then
    if [ "$1" = --demo ] && { [ "$2" = ir ] || [ "$2" = kh ]; }; then
        twcc_dashboard "$2" demo
    else
        printf '%s\n' 'Usage: smite-tunnel-control-center.sh --demo ir|kh' >&2
        exit 2
    fi
fi
