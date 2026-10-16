#!/usr/bin/env bash
# U-OPTI Tunnel Wizard — role-aware navigation; read-only by default.
# The original FRP setup wizard and the separately gated TEST-VPS Backhaul
# install/rollback are delegated unchanged. Other protocol tools are offline
# or read-only. Production Backhaul deployment is NOT approved.

# Optional local-only dashboard, separate from all live deployment flows.
SMITE_TW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -s "$SMITE_TW_DIR/smite-tunnel-control-center.sh" ]; then
    source "$SMITE_TW_DIR/smite-tunnel-control-center.sh"
fi

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
    # A new host chooses a role exactly once, BEFORE protocol options.
    # This remains a session-only selection, not deployment authorization.
    printf '%s\n' "============================================" >&2
    printf '%s\n' "       STEP 0 - SELECT THIS SERVER" >&2
    printf '%s\n' "============================================" >&2
    printf '%s\n' "1) IR - Iran entry / HTTPS gateway" >&2
    printf '%s\n' "2) KH - Foreign exit / service endpoint" >&2
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

smite_tw_backhaul_profile() {
    local role="$1" module
    case "$role" in ir|kh) ;; *) return 2 ;; esac
    module="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-readiness.py"
    [ -s "$module" ] || return 2
    python3 -B "$module" --role "$role" --print-profile 2>/dev/null
}

smite_tw_backhaul_status() {
    local role="$1" profile port path
    profile="$(smite_tw_backhaul_profile "$role")" || profile=""
    read -r port path <<< "$profile"
    if ! [[ "$port" =~ ^[0-9]{4,5}$ && "$path" == /* && "$path" != */ ]]; then
        port=""
        path=""
    fi
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
        if [ -n "$port" ]; then
            echo "Data $port: $(smite_tw_listener "$port")"
        else
            echo "Sidecar XHTTP data listener: not installed / unverified"
        fi
        if [ -f /etc/nginx/u-opti-backhaul-sidecar-control.inc ] &&
           [ -f /etc/nginx/u-opti-backhaul-sidecar-xhttp.inc ]; then
            echo "Nginx Sidecar files: present (contents not disclosed)"
        else
            echo "Nginx Sidecar files: incomplete"
        fi
        echo "Local channel: $(smite_tw_http http://127.0.0.1:3080/channel)"
        if [ -n "$port" ]; then
            echo "Local XHTTP request endpoint: $(smite_tw_http "http://127.0.0.1:$port$path/")"
        fi
    else
        echo "KH Sidecar: $(smite_tw_container_state uopti-backhaul-sidecar-kh)"
        echo "Nginx bridge 13080: $(smite_tw_listener 13080)"
        if [ -n "$port" ]; then
            echo "KH Xray $port: $(smite_tw_listener "$port")"
        else
            echo "KH Xray data port: not installed / unverified"
        fi
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
        echo "Public client: IR-DOMAIN:443 | TLS SNI=IR-DOMAIN | legacy example path=/56053/www."
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

smite_tw_backhaul_prepare() {
    local role="$1" choice module token ir_domain kh_host data_port xhttp_path
    module="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar.py"
    token="/etc/u-opti/backhaul-sidecar/shared.token"
    echo "===== Private Backhaul candidate / PREPARE ONLY ====="
    echo "This creates private 0600 files under a new /tmp directory."
    echo "No Nginx, Docker, Smite, firewall, restart, or port will change."
    echo "The candidate contains a token: NEVER share or publish the directory."
    echo "Custom port/path are OFFLINE PREVIEW ONLY, not used by the current live installer."
    if [ "$(id -u)" -ne 0 ] || [ ! -f "$module" ] || [ ! -f "$token" ] || [ -L "$token" ]; then
        echo "NOT READY: root, candidate generator and existing private token required."
        echo "Prepare the secure token on IR first and transfer it to KH privately."
        return 1
    fi
    read -rp "Create private OFFLINE candidate for $role? Type PREPARE: " choice || return 1
    [ "$choice" = PREPARE ] || { echo "Cancelled; nothing written."; return 0; }
    read -rp "IR HTTPS domain (required): " ir_domain || return 1
    read -rp "KH upstream/Xray Host domain (required): " kh_host || return 1
    if [ -z "$ir_domain" ] || [ -z "$kh_host" ]; then
        echo "ERROR: Both hostnames are required. Nothing generated."
        return 1
    fi
    read -rp "KH XHTTP data port [56053] (OFFLINE ONLY): " data_port || return 1
    data_port="${data_port:-56053}"
    read -rp "XHTTP path [/$data_port/www] (OFFLINE ONLY): " xhttp_path || return 1
    xhttp_path="${xhttp_path:-/$data_port/www}"
    python3 "$module" --role "$role" --token-file "$token" \
        --ir-domain "$ir_domain" --kh-host "$kh_host" \
        --data-port "$data_port" --xhttp-path "$xhttp_path"
}

smite_tw_backhaul_readiness() {
    local role="$1" mode="$2" module
    module="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-readiness.py"
    echo "===== Non-destructive Sidecar readiness / $role / $mode ====="
    if [ ! -s "$module" ]; then
        echo "READINESS MODULE MISSING: update the preview U-OPTI branch."
        return 1
    fi
    python3 -B "$module" --role "$role" --mode "$mode"
}

smite_tw_backhaul_nginx_plan() {
    local role="$1" module source ir_domain kh_host consent
    module="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-nginx-plan.py"
    case "$role" in
        ir) source="/etc/nginx/conf.d/u-opti-smite-panel-backend.conf" ;;
        kh) source="/etc/nginx/sites-available/3xui-kh.kolbe1.ir" ;;
        *) echo "Unknown host role; no action."; return 1 ;;
    esac
    echo "===== Private Nginx integration plan (OFFLINE ONLY) ====="
    echo "Reads the existing Nginx vhost and writes only a PRIVATE /tmp proposal."
    echo "Never reloads Nginx, never edits /etc, never starts a container."
    echo "A host with Sidecar already installed will be REFUSED to prevent overlap."
    echo "IMPORTANT: this plan copies the original vhost, which may be sensitive."
    if [ ! -s "$module" ]; then
        echo "Nginx planner missing; update U-OPTI on the TEST branch."
        return 1
    fi
    read -rp "Type PLAN to prepare private proposal: " consent || return 1
    [ "$consent" = PLAN ] || { echo "Cancelled; no proposal created."; return 0; }
    read -rp "IR HTTPS domain: " ir_domain || return 1
    read -rp "KH Host/domain: " kh_host || return 1
    python3 -B "$module" --role "$role" --input "$source" \
        --ir-domain "$ir_domain" --kh-host "$kh_host"
}

smite_tw_backhaul_admission() {
    local role="$1" module sidecar_stage nginx_stage confirm
    module="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-admission.py"
    echo "===== Fresh-host deployment admission / READ ONLY ====="
    echo "Checks both PRIVATE candidate folders, real local file ownership, Nginx,"
    echo "Docker and reserved port baseline. It never installs or reloads anything."
    echo "A passing check is NOT approval to apply files or activate a Sidecar."
    [ -s "$module" ] || { echo "Admission module missing"; return 1; }
    read -rp "Sidecar candidate directory (/tmp/uopti-backhaul-sidecar-*): " sidecar_stage || return 1
    read -rp "Nginx proposal directory (/tmp/uopti-bh-nginx-plan-*): " nginx_stage || return 1
    read -rp "Run READ-ONLY checks for role $role? Type CHECK: " confirm || return 1
    [ "$confirm" = CHECK ] || { echo "Cancelled."; return 0; }
    python3 -B "$module" --role "$role" \
        --sidecar-dir "$sidecar_stage" --nginx-dir "$nginx_stage"
}

smite_tw_backhaul_live_trial() {
    local role="$1" module choice confirm stage_sidecar stage_nginx gate
    module="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-live-trial.py"
    if [ ! -s "$module" ]; then
        echo "Experimental trial module missing. Update the test branch first."
        return 1
    fi
    while true; do
        echo "===== BACKHAUL REBUILT-TEST-HOST TRIAL ONLY ====="
        echo "WARNING: Not approved for a live production server."
        echo "1) Show trial journal status (read-only)"
        echo "2) Install test Sidecar (modifies THIS test server)"
        echo "3) Roll back only this trial (modifies THIS test server)"
        echo "0) Back"
        read -rp "Choose [0-3]: " choice || return
        case "$choice" in
            1) python3 -B "$module" --role "$role" --status; smite_tw_pause ;;
            2)
                if [ "$(id -u)" -ne 0 ]; then
                    echo "Root required on REBUILT test server."; smite_tw_pause; continue
                fi
                echo "CAUTION: This changes Nginx and Docker on THIS SERVER."
                echo "Do not use the successful current IR/KH installation."
                echo "Verify Hetzner snapshot+console and actual server role first."
                read -rp "Type REBUILT-TEST-VPS to continue: " gate || return
                if [ "$gate" != REBUILT-TEST-VPS ]; then echo "Cancelled."; smite_tw_pause; continue; fi
                read -rp "Private Sidecar candidate directory: " stage_sidecar || return
                read -rp "Private Nginx proposal directory: " stage_nginx || return
                confirm="INSTALL-${role^^}"
                read -rp "Type $confirm to explicitly authorize this installation: " gate || return
                if [ "$gate" != "$confirm" ]; then echo "Cancelled."; smite_tw_pause; continue; fi
                UOPTI_BH_TEST_HOST=I_ACCEPT_REBUILD_TEST_HOST python3 -B "$module" \
                    --role "$role" --install-test --sidecar-dir "$stage_sidecar" \
                    --nginx-dir "$stage_nginx" --confirm "$confirm" || :
                smite_tw_pause ;;
            3)
                echo "CAUTION: Restore only installer-owned trial files/Sidecar."
                echo "Do NOT touch this option if foreign changes occurred."
                confirm="ROLLBACK-${role^^}"
                read -rp "Type $confirm to explicitly authorize rollback: " gate || return
                if [ "$gate" != "$confirm" ]; then echo "Cancelled."; smite_tw_pause; continue; fi
                UOPTI_BH_TEST_HOST=I_ACCEPT_REBUILD_TEST_HOST python3 -B "$module" \
                    --role "$role" --rollback-test --confirm "$confirm" || :
                smite_tw_pause ;;
            0) return ;;
            *) echo "Invalid selection."; smite_tw_pause ;;
        esac
    done
}

smite_tw_backhaul_client() {
    local role="${1:-}" profile port path
    profile="$(smite_tw_backhaul_profile "$role")" || profile=""
    read -r port path <<< "$profile"
    echo "===== v2rayN / v2rayNG sample fields (not a credential) ====="
    echo "Address: <your IR HTTPS domain> | Port: 443 | TLS: on"
    echo "SNI: <your IR HTTPS domain> | Fingerprint: chrome"
    echo "Protocol: VLESS | Network: XHTTP"
    if [[ "$port" =~ ^[0-9]{4,5}$ && "$path" == /* && "$path" != */ ]]; then
        echo "Installed KH Xray inbound port: $port"
        echo "Path: $path"
    else
        echo "Path: <your chosen KH inbound XHTTP path> (not yet verified)"
        echo "Legacy example ONLY: /56053/www"
    fi
    echo "Mode: auto | ALPN: http/1.1 (tested IR gateway profile)"
    echo 'Extra: {"mode":"auto","xPaddingBytes":"100-1000"}'
    echo "Use the UUID/encryption parameters of the existing KH Xray inbound."
    echo "Do not copy secrets into the wizard or logs."
    echo "Xray may append / and a session subpath in actual HTTP requests." \
    echo "Host header is set by the IR XHTTP Nginx include to the KH upstream."
}

smite_tw_backhaul_paste_pair() {
    local role="$1" tool confirm mode answer
    tool="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-paste-pair.py"
    echo "===== Backhaul two Bitvise terminals (FRESH TEST HOSTS) ====="
    echo "NO server-to-server SSH needed. Protect the pairing code as a secret."
    echo "NEVER use this for the already working IR/KH Sidecars."
    [ -s "$tool" ] || { echo "Two-terminal pairing helper missing; update test branch."; return 1; }
    case "$role" in
        ir)
            echo "IR: show the private Backhaul code and copy it DIRECTLY to KH."
            echo "WARNING: It is a long-lived secret, not a temporary login OTP."
            mode="--show-ir"
            confirm="DISPLAY-IR-PRIVATE-CODE"
            ;;
        kh)
            echo "KH: paste the IR code into a hidden (no-echo) terminal prompt."
            echo "The file is created privately or matched without overwrite."
            mode="--paste-kh"
            confirm="PASTE-KH-PRIVATE-CODE"
            ;;
        *) echo "Unsupported role; cancelled."; return 1 ;;
    esac
    read -rp "Type $confirm to continue: " answer || return 1
    [ "$answer" = "$confirm" ] || { echo "Cancelled. No pairing change."; return 0; }
    python3 -B "$tool" "$mode" --confirm "$confirm"
}

smite_tw_backhaul_secure_pair() {
    local role="$1" tool kh_host ssh_port confirm
    tool="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-ssh-pair.py"
    echo "===== Private Backhaul pairing / trusted SSH ONLY ====="
    echo "For FRESH TEST hosts only. Never prints or copies token into shell arguments."
    echo "SSH public-key login + an already verified KH host key are required."
    echo "No password login, automatic host-key acceptance or SSH config changes."
    [ -s "$tool" ] || { echo "Pairing helper missing on this host."; return 1; }
    if [ "$role" = kh ]; then
        python3 -B "$(dirname "$tool")/smite-backhaul-sidecar-token.py" --verify
        return
    fi
    [ "$role" = ir ] || { echo "Unknown role; no pairing."; return 1; }
    read -rp "KH SSH hostname (DNS; must already be trusted): " kh_host || return
    read -rp "KH SSH port [22]: " ssh_port || return
    ssh_port="${ssh_port:-22}"
    read -rp "Type PAIR-KH-TEST-HOST to securely pair TEST servers: " confirm || return
    [ "$confirm" = PAIR-KH-TEST-HOST ] || { echo "Cancelled; no pairing."; return 0; }
    python3 -B "$tool" --send-ir --kh-host "$kh_host" \
        --ssh-port "$ssh_port" --confirm PAIR-KH-TEST-HOST
}

smite_tw_backhaul_guided_prepare() {
    local role="$1" module ir_domain kh_host confirm
    module="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-guided-prep.py"
    echo "===== Guided PRIVATE/OFFLINE Backhaul preparation ====="
    echo "FRESH TEST HOSTS ONLY. Existing Sidecar hosts will be REFUSED."
    echo "Runs local preflight, prepares BOTH private bundles, then checks admission."
    echo "Never installs, changes Nginx, starts Docker or touches FRP/Smite/Xray."
    echo "Requires the existing, safely paired token on this host."
    [ -s "$module" ] || { echo "Guided preparation module missing; update preview branch."; return 1; }
    read -rp "IR HTTPS domain: " ir_domain || return
    read -rp "KH upstream/Xray Host domain: " kh_host || return
    read -rp "Type PREPARE-PRIVATE-OFFLINE to generate BOTH private proposals: " confirm || return
    [ "$confirm" = PREPARE-PRIVATE-OFFLINE ] || { echo "Cancelled, nothing prepared."; return 0; }
    python3 -B "$module" --role "$role" --ir-domain "$ir_domain" \
        --kh-host "$kh_host" --prepare-only --confirm PREPARE-PRIVATE-OFFLINE
}

smite_tw_backhaul_manual_menu() {
    local role="$1" choice
    while true; do
        smite_tw_header
        printf 'Backhaul legacy/manual tools | This machine: %s\n' "$role"
        echo "1) Explain architecture"
        echo "2) Installation safety checklist"
        echo "3) Preview custom data port & XHTTP path (OFFLINE; no install)"
        echo "4) Prepare only Nginx proposal (OFFLINE)"
        echo "5) Check two existing private candidates (read-only)"
        echo "0) Back"
        read -rp "Choose [0-5]: " choice || return
        case "$choice" in
            1) smite_tw_backhaul_overview "$role"; smite_tw_pause ;;
            2) smite_tw_backhaul_steps "$role"; smite_tw_pause ;;
            3) smite_tw_backhaul_prepare "$role" || :; smite_tw_pause ;;
            4) smite_tw_backhaul_nginx_plan "$role" || :; smite_tw_pause ;;
            5) smite_tw_backhaul_admission "$role" || :; smite_tw_pause ;;
            0) return ;;
            *) echo "Invalid choice"; smite_tw_pause ;;
        esac
    done
}

smite_tw_backhaul_install_badge() {
    local role="$1" trialroot="/var/lib/u-opti/backhaul-trial/$1" container=""
    container="uopti-backhaul-sidecar-$role"
    if [ -e "$trialroot" ] || [ -L "$trialroot" ]; then
        echo "Sidecar: TRIAL JOURNAL PRESENT - use Step 3. Do NOT reinstall."
    elif docker container inspect "$container" >/dev/null 2>&1; then
        echo "Sidecar: CONTAINER FOUND BUT NO JOURNAL - STOP, inspect Step 3."
    elif [ -e "/etc/u-opti/backhaul-sidecar/$role.toml" ]; then
        echo "Sidecar: PROFILE FOUND BUT NO JOURNAL - STOP, inspect Step 3."
    else
        echo "Sidecar: NOT INSTALLED (pairing alone does not install it)."
    fi
}

smite_tw_backhaul_guided_trial_install() {
    local role="$1" module ir_domain kh_host data_port xhttp_path gate confirm
    module="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-guided-trial.py"
    echo "===== ONE-FLOW BACKHAUL: FRESH REBUILT TEST VPS ONLY ====="
    echo "REQUIRES: Smite/FRP/Nginx/Xray baseline, private token, snapshot+console."
    echo "MUTATES THIS TEST VPS: Nginx files/reload and the owned Sidecar container."
    echo "Does not install Smite, 3x-UI, certificates or Xray inbounds."
    echo "Do NOT run on the already working IR/KH trial hosts."
    echo "All journal, ownership, host approval and rollback gates stay enabled."
    echo "IMPORTANT: Pairing is ONLY a token exchange, NOT a Sidecar installation."
    echo "This Step 2 MUST finish separately on BOTH IR and KH."
    [ -s "$module" ] || { echo "Guided trial module missing; update test branch."; return 1; }
    [ "$(id -u)" -eq 0 ] || { echo "Root required."; return 1; }
    read -rp "IR HTTPS domain: " ir_domain || return 1
    read -rp "KH upstream / Xray Host domain: " kh_host || return 1
    echo "Choose the SAME Xray port and XHTTP path on BOTH IR and KH."
    echo "KH Xray inbound must already exist on 127.0.0.1 at this port/path."
    read -rp "KH Xray inbound port [56053]: " data_port || return 1
    data_port="${data_port:-56053}"
    read -rp "XHTTP base path [/$data_port/www] (e.g. /45561/web): " xhttp_path || return 1
    xhttp_path="${xhttp_path:-/$data_port/www}"
    # Accept the common trailing-slash notation, normalize before safe validation.
    xhttp_path="${xhttp_path%/}"
    echo "Selected KH Xray port: $data_port | XHTTP base path: $xhttp_path"
    echo "Do not reuse FRP paths or a port already occupied on IR."
    echo
    echo "===== PHASE A: READ-ONLY LOCAL PREFLIGHT ====="
    if ! python3 -B "$module" --diagnose --role "$role" \
         --ir-domain "$ir_domain" --kh-host "$kh_host" \
         --data-port "$data_port" --xhttp-path "$xhttp_path"; then
        echo "INSTALLATION NOT STARTED. Resolve the HOLD shown above."
        echo "No automatic retries. Use Step 3 to check existing state."
        return 1
    fi
    echo
    echo "LOCAL CHECK PASSED; NOT YET INSTALLED."
    echo "===== PHASE B: EXPLICIT TEST-HOST APPROVAL ====="
    read -rp "Type REBUILT-TEST-VPS if snapshot AND console are available: " gate || return 1
    [ "$gate" = REBUILT-TEST-VPS ] || { echo "Cancelled; nothing installed."; return 0; }
    confirm="INSTALL-${role^^}"
    read -rp "Type $confirm to approve changes ONLY to this $role test host: " gate || return 1
    [ "$gate" = "$confirm" ] || { echo "Cancelled; nothing installed."; return 0; }
    if UOPTI_BH_TEST_HOST=I_ACCEPT_REBUILD_TEST_HOST python3 -B "$module" \
        --role "$role" --ir-domain "$ir_domain" --kh-host "$kh_host" \
        --data-port "$data_port" --xhttp-path "$xhttp_path" \
        --install-test --test-host-approval REBUILT-TEST-VPS --confirm "$confirm"; then
        echo
        echo "===== PHASE C: CHECK LOCAL INSTALLATION ====="
        python3 -B "$(dirname "$module")/smite-backhaul-sidecar-live-trial.py" \
          --role "$role" --status || :
        python3 -B "$(dirname "$module")/smite-backhaul-sidecar-readiness.py" \
          --role "$role" --mode existing || :
        echo "Next: Repeat Step 2 on OTHER host. Test authenticated VLESS AFTER both."
    else
        echo
        echo "INSTALLATION NOT CONFIRMED. Do not rerun Step 2 blindly."
        echo "Open Step 3 (read-only) and send non-secret output."
        return 1
    fi
}

# Everyday navigation follows the human workflow. All test-host mutation
# remains behind the original explicit consent and journal gates.
smite_tw_backhaul_diagnostics_menu() {
    local role="$1" choice module
    module="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-live-trial.py"
    while true; do
        smite_tw_header
        printf 'Backhaul | Diagnostics | This machine: %s\n' "$role"
        echo "1) Current Sidecar status (read-only)"
        echo "2) Full installed Sidecar audit (read-only; fails if not installed)"
        echo "3) Trial journal status (read-only)"
        echo "4) Diagnose fresh Sidecar installation (read-only)"
        echo "0) Back"
        read -rp "Choose [0-4]: " choice || return
        case "$choice" in
            1) smite_tw_backhaul_status "$role"; smite_tw_pause ;;
            2) smite_tw_backhaul_readiness "$role" existing || :; smite_tw_pause ;;
            3) if [ -s "$module" ]; then python3 -B "$module" --role "$role" --status || :;
               else echo "Trial module missing."; fi; smite_tw_pause ;;
            4)
                local guided=""
                guided="${SMITE_BH_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/smite-backhaul-sidecar-guided-trial.py"
                if [ -s "$guided" ]; then
                    echo "Default 56053/www profile ONLY. For a CUSTOM port/path,"
                    echo "use INSTALL option 2 and its exact read-only preflight."
                    python3 -B "$guided" --role "$role" --diagnose || :
                else
                    echo "Guided diagnostics unavailable; update U-OPTI."
                fi
                smite_tw_pause ;;
            0) return ;;
            *) echo "Invalid choice"; smite_tw_pause ;;
        esac
    done
}

smite_tw_backhaul_expert_menu() {
    local role="$1" choice
    while true; do
        smite_tw_header
        printf 'Backhaul | Recovery & Advanced | This machine: %s\n' "$role"
        echo "TEST VPS ONLY. Existing Sidecars must not be installed over."
        echo "1) Check FRESH test host before installation (read-only)"
        echo "2) Prepare private OFFLINE installation plan"
        echo "3) Trial journal / guarded rollback / legacy install"
        echo "4) Trusted SSH pairing (optional advanced method)"
        echo "5) Manual planning / legacy tools"
        echo "0) Back"
        read -rp "Choose [0-5]: " choice || return
        case "$choice" in
            1) smite_tw_backhaul_readiness "$role" new || :; smite_tw_pause ;;
            2) smite_tw_backhaul_guided_prepare "$role" || :; smite_tw_pause ;;
            3) smite_tw_backhaul_live_trial "$role" || :; smite_tw_pause ;;
            4) smite_tw_backhaul_secure_pair "$role" || :; smite_tw_pause ;;
            5) smite_tw_backhaul_manual_menu "$role" ;;
            0) return ;;
            *) echo "Invalid choice"; smite_tw_pause ;;
        esac
    done
}

smite_tw_backhaul_menu() {
    local role="$1" choice
    while true; do
        smite_tw_header
        printf 'Protocol: Backhaul | This machine: %s\n\n' "$role"
        echo "Fresh TEST VPS: 1=PAIR TOKEN (not an install) -> 2=INSTALL -> 3=VERIFY."
        smite_tw_backhaul_install_badge "$role"
        echo
        echo "1) Pair token only (do ON BOTH hosts; does NOT install)"
        echo "2) INSTALL Sidecar on THIS host (fresh TEST VPS ONLY)"
        echo "3) VERIFY installation and diagnose (read-only)"
        echo "4) Client configuration (VLESS/XHTTP)"
        echo "5) Recovery, preflight & advanced tools"
        echo "0) Back"
        read -rp "Choose [0-5]: " choice || return
        case "$choice" in
            1) smite_tw_backhaul_paste_pair "$role" || :; smite_tw_pause ;;
            2) smite_tw_backhaul_guided_trial_install "$role" || :; smite_tw_pause ;;
            3) smite_tw_backhaul_diagnostics_menu "$role" ;;
            4) smite_tw_backhaul_client "$role"; smite_tw_pause ;;
            5) smite_tw_backhaul_expert_menu "$role" ;;
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
    echo "Rathole may use a WebSocket transport in a suitably built/pinned version."
    echo "Do not assume Rathole uses Backhaul /channel or /tunnel/ endpoints."
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
        echo "2) Validate dedicated TCP ports and preview deployment plan"
        echo "3) WebSocket/TLS/443 compatibility checklist (NO activation)"
        echo "0) Back"
        read -rp "Choose [0-3]: " choice || return
        case "$choice" in
            1)
                echo "Rathole forwards TCP/UDP services; transport can be TCP, TLS, Noise"
                echo "or WebSocket in versions/builds that include WS support."
                echo "It is not a general-purpose HTTP reverse proxy and does NOT"
                echo "reuse Backhaul /channel and /tunnel/ control endpoints."
                echo "It needs an independently reviewed public TCP entry or SNI routing."
                echo "Version/pinning, authentication, process supervision, backup and"
                echo "rollback must be validated before an automatic installer is offered."
                smite_tw_pause ;;
            2)
                read -rp "Dedicated control TCP port [e.g. 23333]: " control || return
                read -rp "Target local service port [e.g. 45000]: " data || return
                smite_tw_rathole_plan "$role" "$control" "$data" || :
                smite_tw_pause ;;
            3)
                echo "===== Rathole WSS feasibility (REVIEW ONLY) ====="
                echo "1. Pin a Rathole release WITH WebSocket support and verify it."
                echo "2. Validate the exact WS path/handshake with the pinned binary."
                echo "3. Choose a separate safe HTTP Nginx route or SNI/vhost."
                echo "4. Keep IR website, FRP /~!frp, Backhaul /channel and"
                echo "   /tunnel/ paths UNCHANGED. No global root-location takeover."
                echo "5. Terminate TLS at the reviewed gateway and verify peer TLS."
                echo "6. Test public exposure, auth and clean rollback offline first."
                echo "NO RATHOLE INSTALLER OR NGINX MUTATION IN THIS WIZARD."
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
        echo "1) Backhaul — independent Sidecar management"
        echo "2) FRP — existing Standard Smite wizard"
        echo "3) Rathole — safe plan only (no installer)"
        echo "4) Tunnel Control Center — read-only status and routes"
        echo "0) Back"
        read -rp "Choose [0-4]: " choice || return
        case "$choice" in
            1) smite_tw_backhaul_menu "$role" ;;
            2)
                if declare -F smite_frp_wizard_menu >/dev/null 2>&1; then
                    smite_frp_wizard_menu "$role"
                else
                    echo "FRP wizard missing; update U-OPTI first."
                    smite_tw_pause
                fi ;;
            3) smite_tw_rathole_menu "$role" ;;
            4) if declare -F twcc_menu >/dev/null 2>&1; then
                   twcc_menu "$role"
               else
                   echo "Tunnel Control Center missing; update the test branch."
                   smite_tw_pause
               fi ;;
            0) return ;;
            *) echo "Invalid choice"; smite_tw_pause ;;
        esac
    done
}
