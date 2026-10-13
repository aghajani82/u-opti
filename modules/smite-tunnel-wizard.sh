#!/usr/bin/env bash
# U-OPTI Tunnel Setup Wizard — non-destructive, role-aware entry point.
# This file is sourced by smite-backhaul-management.sh. It never mutates the
# active Smite, FRP, Xray, Nginx, Docker or Backhaul configuration.
# Installation actions are delegated only to the existing FRP wizard.
# Backhaul and Rathole remain explicit REVIEW/VERIFY workflows until audited
# installers and rollback have been added and separately validated.

smite_tw_pause() { read -rp "Press Enter to continue..." _smite_tw_unused || :; }
smite_tw_clear() { if [ -t 1 ] && command -v clear >/dev/null 2>&1; then clear; fi; }

smite_tw_header() {
    smite_tw_clear
    printf '%s\n' "============================================" \
        "            U-OPTI TUNNEL WIZARD" \
        "============================================"
}

smite_tw_role() {
    local role=""
    if declare -F smite_bh_role >/dev/null 2>&1; then
        role="$(smite_bh_role 2>/dev/null)" || role=""
    fi
    case "$role" in
        ir|kh) printf '%s\n' "$role" ;;
        *) printf '%s\n' unknown ;;
    esac
}

smite_tw_choose_role() {
    local role choice
    role="$(smite_tw_role)"
    if [ "$role" != unknown ]; then
        printf '%s\n' "$role"
        return
    fi
    # The fallback is used for new hosts without a configured Smite state.
    # Do not persist guessed roles or silently install anything.
    printf '%s\n' "Smite role is not known. Choose this machine's role:" >&2
    printf '%s\n' "1) IR — Iran entry / Nginx HTTPS" >&2
    printf '%s\n' "2) KH — Foreign exit / Xray" >&2
    printf '%s\n' "0) Cancel" >&2
    read -rp "Choose [0-2]: " choice || return 1
    case "$choice" in
        1) printf 'ir\n' ;;
        2) printf 'kh\n' ;;
        *) return 1 ;;
    esac
}

smite_tw_result() {
    case "$1" in
        ready) printf 'READY' ;;
        missing) printf 'NOT FOUND' ;;
        *) printf 'NOT VERIFIED' ;;
    esac
}

smite_tw_container_state() {
    local name="$1" actual
    if ! command -v docker >/dev/null 2>&1; then
        echo "Docker unavailable"
        return
    fi
    actual="$(docker inspect -f '{{.State.Running}}|{{.HostConfig.RestartPolicy.Name}}' "$name" 2>/dev/null)" || {
        echo "not installed"
        return
    }
    case "$actual" in
        true\|unless-stopped|true\|always) echo "running, auto-start" ;;
        true\|*) echo "running, reboot persistence NOT verified ($actual)" ;;
        *) echo "not running ($actual)" ;;
    esac
}

smite_tw_listener() {
    local port="$1" actual
    if ! command -v ss >/dev/null 2>&1; then echo "unknown (ss unavailable)"; return; fi
    actual="$(ss -H -lnt "( sport = :$port )" 2>/dev/null | awk '{print $4}')" || {
        echo "unknown"; return
    }
    if [ -z "$actual" ]; then
        echo "absent"
    else
        printf '%s\n' "$actual"
    fi
}

smite_tw_http() {
    local url="$1" result
    if ! command -v curl >/dev/null 2>&1; then
        echo "curl unavailable"
        return
    fi
    result="$(curl --noproxy '*' -4 --silent --show-error --connect-timeout 3 \
        --max-time 8 --output /dev/null --write-out '%{http_code}' "$url" 2>/dev/null)" || {
        echo "unreachable"; return
    }
    echo "HTTP $result"
}

smite_tw_backhaul_status() {
    local role="$1"
    printf '\n%s\n' "===== Independent Backhaul / READ-ONLY ====="
    printf 'Detected role: %s\n' "$role"
    if command -v nginx >/dev/null 2>&1 && nginx -t >/dev/null 2>&1; then
        echo "Nginx syntax: OK"
    else
        echo "Nginx syntax: NOT VERIFIED"
    fi
    if [ "$role" = ir ]; then
        echo "IR Sidecar: $(smite_tw_container_state uopti-backhaul-sidecar-ir)"
        echo "Control 3080: $(smite_tw_listener 3080)"
        echo "Data 56053: $(smite_tw_listener 56053)"
        if [ -f /etc/nginx/u-opti-backhaul-sidecar-control.inc ] &&
           [ -f /etc/nginx/u-opti-backhaul-sidecar-xhttp.inc ]; then
            echo "Nginx Sidecar files: present (contents not disclosed)"
        else
            echo "Nginx Sidecar files: incomplete"
        fi
        echo "Local channel: $(smite_tw_http http://127.0.0.1:3080/channel)"
        echo "Local data XHTTP: $(smite_tw_http http://127.0.0.1:56053/56053/www/)"
    else
        echo "KH Sidecar: $(smite_tw_container_state uopti-backhaul-sidecar-kh)"
        echo "Nginx bridge 13080: $(smite_tw_listener 13080)"
        echo "Xray 56053: $(smite_tw_listener 56053)"
        echo "Bridge channel: $(smite_tw_http http://127.0.0.1:13080/channel)"
        if command -v docker >/dev/null 2>&1; then
            local n
            n="$(docker top smite-node -eo pid,comm 2>/dev/null |
                awk '$2=="backhaul" {n++} END {print n+0}')"
            echo "Existing Smite Backhaul processes: $n (count only)"
        fi
    fi
    echo "HTTP 401 on /channel is an unauthenticated probe, NOT full WS proof."
    echo "HTTP 400 on XHTTP GET is NOT proof of authenticated VLESS traffic."
    echo "Only a real client and both-host reboot testing verify the data path."
}

smite_tw_backhaul_overview() {
    local role="$1"
    printf '\n%s\n' "===== Backhaul v0.7.2 | role=$role ====="
    echo "Architecture: VLESS/XHTTP -> IR HTTPS:443 -> Nginx ->"
    echo " Backhaul WS /channel + /tunnel/ -> KH TLS-verifying Nginx bridge -> KH Xray"
    if [ "$role" = ir ]; then
        echo "IR: Backhaul server bind 127.0.0.1:3080."
        echo "IR: Backhaul data port 127.0.0.1:56053."
        echo "IR: existing HTTPS backend is 127.0.0.1:8443."
        echo "Public client: IR-DOMAIN:443 | TLS SNI=IR-DOMAIN | path=/56053/www/."
    else
        echo "KH: Backhaul client connects to 127.0.0.1:13080."
        echo "KH: Nginx bridge verifies TLS and SNI of IR domain."
        echo "KH: Xray listens on 127.0.0.1:56053."
        echo "IMPORTANT: public /13080/... forwarding must be BLOCKED on KH."
    fi
    echo "Token: generate privately on IR, transfer securely to KH."
    echo "Never paste tokens, UUIDs, private keys or unfiltered configs into support logs."
    echo "The independent Sidecar is NOT a tunnel configured inside Smite UI."
}

smite_tw_backhaul_steps() {
    local role="$1"
    echo "===== Backhaul setup / safe guided checklist ====="
    echo "Step 1: Snapshot BOTH servers; take separate config and cert backups."
    echo "Step 2: Verify Nginx/SNI, TLS trust, service versions and port ownership."
    echo "Step 3: Generate a private shared token and 0600 per-role TOML files."
    if [ "$role" = ir ]; then
        echo "Step 4 (IR): Add separate Nginx /channel + /tunnel/ + XHTTP includes."
        echo "Step 5 (IR): Start named server-only Sidecar; verify loopback listeners."
    else
        echo "Step 4 (KH): Deny public /13080/ forwarding before creating bridge."
        echo "Step 5 (KH): Add loopback TLS-verifying Nginx bridge, then named client."
    fi
    echo "Step 6: Test TLS, authenticated WS and actual VLESS/XHTTP client."
    echo "Step 7: Enable Docker unless-stopped and reboot each host SEPARATELY."
    echo "Step 8: Confirm status, backups, rollback and legacy services unchanged."
    echo
    echo "INSTALLATION STATUS: REVIEW ONLY in this wizard."
    echo "Reason: existing Backhaul module generates offline candidates; it has"
    echo "not been upgraded into an audited transactional live installer."
    echo "Do NOT create a second Backhaul tunnel in Smite using these ports."
}

smite_tw_backhaul_client() {
    echo "===== v2rayN / v2rayNG sample fields (not a credential) ====="
    echo "Address: <your IR HTTPS domain> | Port: 443 | TLS: on"
    echo "SNI: <your IR HTTPS domain> | Fingerprint: chrome"
    echo "Protocol: VLESS | Network: XHTTP | Path: /56053/www/"
    echo "Mode: auto | ALPN: http/1.1 (tested IR gateway profile)"
    echo 'Extra: {"mode":"auto","xPaddingBytes":"100-1000"}'
    echo "Use the UUID/encryption parameters of the existing KH Xray inbound."
    echo "Do not copy secrets into the wizard or logs."
    echo "Host header is set by the IR XHTTP Nginx include to the KH upstream."
}

smite_tw_backhaul_menu() {
    local role="$1" choice
    while true; do
        smite_tw_header
        printf 'Protocol: Backhaul | This machine: %s\n\n' "$role"
        echo "1) How the IR/KH tunnel works"
        echo "2) Diagnose installed Sidecar (read-only)"
        echo "3) Guided safe installation checklist"
        echo "4) Show v2rayN / Android profile fields"
        echo "0) Back"
        read -rp "Choose [0-4]: " choice || return
        case "$choice" in
            1) smite_tw_backhaul_overview "$role"; smite_tw_pause ;;
            2) smite_tw_backhaul_status "$role"; smite_tw_pause ;;
            3) smite_tw_backhaul_steps "$role"; smite_tw_pause ;;
            4) smite_tw_backhaul_client; smite_tw_pause ;;
            0) return ;;
            *) echo "Invalid choice"; smite_tw_pause ;;
        esac
    done
}

smite_tw_rathole_validate_port() {
    local p="$1"
    [[ "$p" =~ ^[0-9]{4,5}$ ]] || return 1
    (( 10#$p >= 1024 && 10#$p <= 65535 )) || return 1
    case "$p" in 3080|443|7000|8000|8443|8888|13080|18476|56053) return 1 ;; esac
}

smite_tw_rathole_plan() {
    local role="$1" control="$2" data="$3"
    smite_tw_rathole_validate_port "$control" &&
        smite_tw_rathole_validate_port "$data" || {
        echo "ERROR: Invalid/reserved port; refusing plan." >&2
        return 1
    }
    [ "$control" != "$data" ] || { echo "ERROR: Ports must differ." >&2; return 1; }
    echo "===== Rathole standalone TCP plan / NO INSTALL ====="
    echo "Role: $role | Control port: $control | Forwarded service port: $data"
    echo "IR: server receives outbound connection from KH on TCP/$control."
    echo "KH: client forwards local service at 127.0.0.1:$data."
    echo "IR: forwarded service listener requires separate safety review."
    echo "Use a unique service token stored in a root-only 0600 file."
    echo "WARNING: Rathole does NOT provide Backhaul-style /channel WSS URLs."
    echo "Do not proxy Rathole TCP via an HTTP location or silently reuse :443."
    echo "A direct port requires reviewing firewall/provider exposure and TLS/noise."
    echo "No config files, firewall rules or services have been changed."
}

smite_tw_rathole_menu() {
    local role="$1" choice control data
    while true; do
        smite_tw_header
        printf 'Protocol: Rathole | This machine: %s\n\n' "$role"
        echo "1) Explain secure Rathole TCP architecture"
        echo "2) Validate port choices and preview deployment plan"
        echo "0) Back"
        read -rp "Choose [0-2]: " choice || return
        case "$choice" in
            1)
                echo "Rathole is a TCP/UDP reverse tunnel, NOT an HTTP/WebSocket proxy."
                echo "It needs an independently reviewed public TCP entry or SNI routing."
                echo "Version/pinning, authentication, process supervision, backup and"
                echo "rollback must be validated before an automatic installer is offered."
                smite_tw_pause ;;
            2)
                read -rp "Dedicated control TCP port [e.g. 23333]: " control || return
                read -rp "Target local service port [e.g. 45000]: " data || return
                smite_tw_rathole_plan "$role" "$control" "$data" || :
                smite_tw_pause ;;
            0) return ;;
            *) echo "Invalid choice"; smite_tw_pause ;;
        esac
    done
}

smite_tw_menu() {
    local role="" choice
    role="$(smite_tw_choose_role)" || return
    while true; do
        smite_tw_header
        printf 'Detected/selected host role: %s\n\n' "$role"
        echo "1) Backhaul — independent WSS/XHTTP (IR + KH)"
        echo "2) FRP — Standard Smite WSS wizard (IR + KH)"
        echo "3) Rathole — independent TCP planning (IR + KH)"
        echo "4) Backhaul read-only health snapshot"
        echo "0) Back"
        read -rp "Choose [0-4]: " choice || return
        case "$choice" in
            1) smite_tw_backhaul_menu "$role" ;;
            2)
                if declare -F smite_frp_wizard_menu >/dev/null 2>&1; then
                    smite_frp_wizard_menu
                else
                    echo "FRP wizard module missing. Update U-OPTI first."
                    smite_tw_pause
                fi ;;
            3) smite_tw_rathole_menu "$role" ;;
            4) smite_tw_backhaul_status "$role"; smite_tw_pause ;;
            0) return ;;
            *) echo "Invalid choice"; smite_tw_pause ;;
        esac
    done
}
