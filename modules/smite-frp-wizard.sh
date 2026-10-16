#!/usr/bin/env bash
# Standard FRP setup is opt-in and separate from the original Private Wizard.
smite_frp_wizard_pause() { read -rp "Press Enter to return..."; }
smite_frp_wizard_role() {
    case "$(smite_frp_std_state SMITE_ROLE)" in
        panel-iran) echo ir ;;
        foreign) echo kh ;;
        *) echo unknown ;;
    esac
}
smite_frp_wizard_port() {
    local port=""
    # Use user-confirmed port; never display FRP tunnel tokens from Smite state.
    read -rp "Forwarded FRP TCP / Sanaei inbound port [e.g. 13914]: " port
    if [[ ! "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1024 ] || [ "$port" -gt 65535 ]; then
        echo "ERROR: Invalid TCP port."; return 1
    fi
    case "$port" in 7000|8000|8443|8888) echo "ERROR: Reserved port"; return 1 ;; esac
    printf '%s' "$port"
}
smite_frp_wizard_status() {
    local role="$1" mode=""
    mode="$(smite_frp_std_state SMITE_CONNECTION_MODE)"
    echo "==== Standard FRP Health / Read-only ===="
    echo "Role: $role | Mode: $mode"
    echo "Docker Engine: $(systemctl is-active docker 2>/dev/null || echo unavailable)"
    echo "Docker Compose: $(docker compose version --short 2>/dev/null || echo unavailable)"
    echo "Smite node: $(smite_frp_std_running smite-node && echo running || echo missing)"
    if [ "$role" = ir ]; then
        echo "Smite panel: $(smite_frp_std_running smite-panel && echo running || echo missing)"
    fi
    if [ -f /opt/u-opti-smite/node/frp_gateway_config.py ]; then
        echo "Standard FRP WSS compatibility: prepared"
    else
        echo "Standard FRP WSS compatibility: NOT PREPARED"
    fi
    if [ "$role" = ir ]; then
        echo "Nginx validation: $(nginx -t >/dev/null 2>&1 && echo OK || echo FAILED)"
        if grep -Fq 'location = /~!frp {' /etc/nginx/conf.d/u-opti-smite-panel-backend.conf 2>/dev/null; then
            echo "IR WSS /~!frp: prepared"
        else
            echo "IR WSS /~!frp: missing"
        fi
        echo "XHTTP timer: $(systemctl is-active u-opti-smite-frp-xhttp.timer 2>/dev/null || echo inactive)"
        echo "FRPS: local port 7000 (must not be publicly bound)"
        ss -lntp 2>/dev/null | grep -E ':7000[[:space:]]' || true
        if [ -f /etc/nginx/u-opti-smite-frp-xhttp.conf ]; then
            echo "Current generated XHTTP locations:"
            grep -E '^[[:space:]]*location ' /etc/nginx/u-opti-smite-frp-xhttp.conf || true
        fi
    else
        echo "FRPC process:"
        ps -C frpc -o pid,stat,etime,comm || true
        echo "FRPC endpoint/transport (no secret tokens):"
        docker exec smite-node sh -c '
            for f in /etc/smite-node/frp/frpc_*.yaml; do
                [ -f "$f" ] || continue
                grep -E "^(serverAddr:|serverPort:|loginFailExit:|transport:|  protocol:)" "$f"
            done
        ' 2>/dev/null || true
    fi
    smite_frp_wizard_pause
}
# KH cannot read the IR route registry: ask for the same KH Sanaei Path.
# On IR, always use the persisted gateway path, never guess /PORT/web.
smite_frp_wizard_path() {
    local role="$1" port="$2" path=""
    if [ "$role" = ir ]; then
        smite_frp_xhttp_get_path "$port"
        return $?
    fi
    read -rp "KH Sanaei XHTTP base path [/$port/web]: " path || return 1
    path="${path:-/$port/web}"
    path="${path%/}"
    python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" check "$port" "$path" >/dev/null || return 1
    printf '%s\n' "$path"
}

smite_frp_wizard_tunnel() {
    local role="$1" panel="" answer="" port="" oldpath="" path=""
    panel="$(smite_frp_std_state SMITE_PANEL_DOMAIN)"
    echo "==== FRP TCP tunnel and XHTTP gateway Path ===="
    echo "This is a SEPARATE step from creating the FRP tunnel in Smite UI."
    echo "1. Visit https://${panel:-IR-PANEL-DOMAIN}:443"
    echo "2. Ensure IR and KH Smite nodes are online."
    echo "3. Smite UI: Tunnels -> Create -> FRP -> TCP."
    echo "4. IR node = server, KH node = client; FRPS bind port = 7000."
    echo "5. Forwarded TCP port = KH Sanaei VLESS/XHTTP inbound port."
    echo "6. KH Xray must listen on 127.0.0.1; security none; mode auto."
    echo "7. Choose ANY safe XHTTP base Path, e.g. /13914/shop."
    echo "8. Configure IDENTICAL Path in KH Sanaei and IR FRP gateway."
    echo "9. IR Nginx forwards the Path and XHTTP subpaths without rewriting."
    echo "10. Keep FRP token private; KH connects to IR DNS:443 via WSS."
    if [ "$role" = ir ]; then
        echo
        read -rp "Smite FRP TCP tunnel already created/applied? Register IR XHTTP Path now? [y/N]: " answer || answer=""
        case "$answer" in y|Y|yes|YES) ;; *) smite_frp_wizard_pause; return ;; esac
        port="$(smite_frp_wizard_port)" || { smite_frp_wizard_pause; return 1; }
        oldpath="$(smite_frp_xhttp_get_path "$port")" || { smite_frp_wizard_pause; return 1; }
        read -rp "IR XHTTP base path [$oldpath]: " path || { smite_frp_wizard_pause; return 1; }
        path="${path:-$oldpath}"
        path="${path%/}"
        echo "Registering FRP port $port with XHTTP Path $path on IR ONLY."
        if smite_frp_xhttp_register_path "$port" "$path"; then
            echo "IR GATEWAY PATH CHECK:"
            smite_frp_xhttp_verify_path "$port" "$path" &&
                echo "IR_XHTTP_NGINX_PATH_VERIFIED=$path" ||
                echo "HOLD: Nginx route publication NOT verified."
        else
            echo "HOLD: Path NOT APPLIED. Inspect FRP tunnel, path collision, and Nginx."
            smite_frp_wizard_pause
            return 1
        fi
    else
        echo "KH GUIDE ONLY: This menu has made NO changes on this server."
        echo "KH: Set your Sanaei XHTTP inbound Path manually."
        echo "IMPORTANT: Go to the IR server -> FRP Step 5 to register"
        echo "the SAME custom Path in IR Nginx after applying the Smite FRP tunnel."
        echo "KH cannot change or publish IR routes from this screen."
    fi
    smite_frp_wizard_pause
}

smite_frp_wizard_probe() {
    local role="$1" port="" path="" domain="" tmp="" url="" status=""
    port="$(smite_frp_wizard_port)" || { smite_frp_wizard_pause; return; }
    path="$(smite_frp_wizard_path "$role" "$port")" || {
        echo "HOLD: XHTTP base Path not available or invalid."
        smite_frp_wizard_pause; return 1;
    }
    tmp="$(mktemp)" || return
    if [ "$role" = ir ]; then
        domain="$(smite_frp_std_state SMITE_PANEL_DOMAIN)"
        if [ -z "$domain" ]; then echo "Missing IR Panel domain."; rm -f "$tmp"; smite_frp_wizard_pause; return; fi
        url="https://$domain$path/"
        status="$(curl -sS --noproxy '*' -m 10 --http1.1 \
            --resolve "$domain:443:127.0.0.1" -X OPTIONS \
            -D "$tmp" -o /dev/null -w '%{http_code}' "$url")" || status=network-error
    else
        url="http://127.0.0.1:$port$path/"
        status="$(curl -sS --noproxy '*' -m 10 --http1.1 -X OPTIONS \
            -D "$tmp" -o /dev/null -w '%{http_code}' "$url")" || status=network-error
    fi
    echo "Probe: $url"
    echo "HTTP status: $status"
    if [ "$status" = 200 ] && grep -iq '^X-Padding:' "$tmp"; then
        echo "PASS: XHTTP handler reached through this path."
        echo "NOTE: Only a real VLESS client confirms authenticated traffic."
    else
        echo "NOT VERIFIED: check port, configured path, tunnel, and gateway."
    fi
    rm -f "$tmp"
    smite_frp_wizard_pause
}

smite_frp_wizard_client() {
    local role="" panel="" port="" path=""
    role="$(smite_frp_wizard_role)"
    panel="$(smite_frp_std_state SMITE_PANEL_DOMAIN)"
    [ -n "$panel" ] || { echo "ERROR: Panel domain unavailable; install Smite first."; smite_frp_wizard_pause; return; }
    port="$(smite_frp_wizard_port)" || { smite_frp_wizard_pause; return; }
    path="$(smite_frp_wizard_path "$role" "$port")" || {
        echo "HOLD: XHTTP base Path not available or invalid."
        smite_frp_wizard_pause; return 1;
    }
    echo "==== v2rayN / Xray client settings (verify with real traffic) ===="
    echo "Protocol: VLESS (client UUID comes from KH Sanaei)"
    echo "Address: $panel | Port: 443"
    echo "Network: xhttp | Path: $path | Mode: auto"
    echo "TLS: tls | SNI: $panel | Fingerprint: chrome"
    echo "ALPN: http/1.1  (IMPORTANT: successful tested profile)"
    echo 'XHTTP Extra JSON: {"mode":"auto","xPaddingBytes":"100-1000"}'
    echo "Host: empty | Flow: empty"
    echo "KH Xray inbound security: none (TLS terminates at IR Nginx)"
    echo "The configured XHTTP BASE Path has no trailing /; Xray sends / and subpaths."
    echo "Do not assume default/blank ALPN will work on this gateway."
    smite_frp_wizard_pause
}
# Read-only, non-secret endpoint timing. OPTIONS is NOT a bandwidth test.
# KH tests the actual Xray loopback path; IR tests the complete local HTTPS
# gateway, including the FRP TCP forward to KH if the tunnel is connected.
smite_frp_wizard_timing() {
    local role="$1" port="" path="" url="" domain="" result="" curl_args=()
    port="$(smite_frp_wizard_port)" || { smite_frp_wizard_pause; return 1; }
    path="$(smite_frp_wizard_path "$role" "$port")" || {
        echo "HOLD: Need the selected XHTTP Path."; smite_frp_wizard_pause; return 1;
    }
    if [ "$role" = ir ]; then
        domain="$(smite_frp_std_state SMITE_PANEL_DOMAIN)"
        [ -n "$domain" ] || { echo "HOLD: IR panel hostname unavailable."; smite_frp_wizard_pause; return 1; }
        url="https://$domain$path/"
        curl_args=(--resolve "$domain:443:127.0.0.1")
    else
        url="http://127.0.0.1:$port$path/"
    fi
    echo "==== Standard FRP timing | READ-ONLY | role=$role ===="
    echo "Target: $url"
    echo "Uses one unauthenticated OPTIONS request. No credentials displayed."
    if ! curl --noproxy '*' -4 -sS --connect-timeout 5 --max-time 12 \
        --http1.1 -X OPTIONS -o /dev/null \
        -w 'HTTP=%{http_code} CONNECT=%{time_connect}s TLS=%{time_appconnect}s FIRST_BYTE=%{time_starttransfer}s TOTAL=%{time_total}s\n' \
        "${curl_args[@]}" "$url"; then
        echo "NOT VERIFIED: check Xray listener, Path, FRP connectivity and SNI."
    fi
    echo "Timing is NOT throughput. Compare KH loopback vs IR gateway,"
    echo "then measure actual VLESS client download and upload separately."
    smite_frp_wizard_pause
}
smite_frp_wizard_recovery() {
    echo "==== FRP Repair / Reboot / Rebuild ===="
    echo "1. Check IR panel, KH control, both Smite nodes and Sanaei."
    echo "2. On IR: FRPS localhost:7000, XHTTP localhost:PORT, timer active."
    echo "3. On KH: FRPC reconnects to IR domain:443 using WSS."
    echo "4. Confirm OPTIONS /CONFIGURED/PATH/ gets 200 plus X-Padding via IR."
    echo "5. Confirm actual authenticated VLESS traffic in v2rayN."
    echo "6. Reboot IR, verify. Then reboot KH, verify. Not simultaneously."
    echo "7. Preserve verified snapshots + separate off-server backups."
    echo "8. Never open public TCP/7000 or the raw Xray inbound port."
    echo "This menu does NOT reboot, rebuild or alter your firewall."
    smite_frp_wizard_pause
}
smite_frp_wizard_menu() {
    local role="${1:-}" detected="" mode="" choice=""
    mode="$(smite_frp_std_state SMITE_CONNECTION_MODE)"
    if [ -n "$mode" ] && [ "$mode" != standard ]; then
        echo "ERROR: Existing Smite mode is $mode. FRP Wizard requires Standard."
        echo "Private Network Wizard remains unchanged."
        smite_frp_wizard_pause
        return
    fi
    detected="$(smite_frp_wizard_role)"
    # The unified Tunnel Wizard has already chosen IR/KH. Never ask twice.
    # A supplied role may not override a contradictory installed Smite state.
    case "$role" in
        ir|kh)
            if [ "$detected" != unknown ] && [ "$detected" != "$role" ]; then
                echo "ERROR: Selected host role conflicts with existing Smite role."
                smite_frp_wizard_pause
                return 2
            fi ;;
        "") role="$detected" ;;
        *) echo "ERROR: Invalid host role."; return 2 ;;
    esac
    if [ "$role" = unknown ]; then
        echo "==== Select logical host role ===="
        echo "1) IR: Panel + Iran Node"
        echo "2) KH: Foreign Node"
        echo "0) Back"
        read -rp "Select [0-2]: " choice
        case "$choice" in 1) role=ir ;; 2) role=kh ;; *) return ;; esac
    fi
    while true; do
        clear
        echo "======================================"
        echo "       Standard FRP Setup Wizard"
        echo "======================================"
        echo "Role: $role | Connection mode: $(smite_frp_std_state SMITE_CONNECTION_MODE)"
        echo "Smite FRP tunnel and IR Nginx XHTTP Path are TWO different settings."
        echo "Complete setup in order; KH Step 5 is ONLY an explanation."
        echo
        echo "1) Step 1: Check prerequisites and current status"
        if [ "$role" = ir ]; then
            echo "2) Step 2: Install Smite Panel + Iran Node"
            echo "3) Step 3: Configure IR HTTPS/443 Gateway"
            echo "4) Step 4: Check FRPS WSS + automatic XHTTP routes"
            echo "5) Step 5: Register IR Nginx XHTTP Path (after Smite FRP TCP tunnel)"
            echo "6) Step 6: Probe XHTTP via IR HTTPS/443"
        else
            echo "2) Step 2: Install Foreign Smite Node"
            echo "3) Step 3: Configure KH control HTTPS/443 Gateway"
            echo "4) Step 4: Install Docker Sanaei (existing management)"
            echo "5) Step 5: KH Sanaei Path checklist (GUIDE ONLY, not applied)"
            echo "6) Step 6: Probe KH loopback XHTTP"
        fi
        echo "7) Step 7: Display configured v2rayN settings"
        echo "8) Step 8: Reboot/Repair/Rebuild checklist"
        echo "0) Back"
        read -rp "Choose [0-8]: " choice
        case "$choice" in
            1|4)
                if [ "$choice" = 4 ] && [ "$role" = kh ]; then
                    show_docker_3xui_menu
                else
                    smite_frp_wizard_status "$role"
                fi
                ;;
            2) smite_frp_std_install "$role" ;;
            3)
                if [ "$role" = ir ]; then
                    smite_gateway_configure_panel
                else
                    smite_foreign_gateway_configure
                fi
                ;;
            5) smite_frp_wizard_tunnel "$role" ;;
            6) smite_frp_wizard_probe "$role" ;;
            7) smite_frp_wizard_client ;;
            8) smite_frp_wizard_recovery ;;
            9) smite_frp_wizard_timing "$role" ;;
            0) return ;;
            *) echo "Invalid selection."; sleep 1 ;;
        esac
    done
}
# Preserve the old ten-step Private Wizard and Standard Test Guide functions.
docker_smite_management_menu() {
    local choice=""
    while true; do
        clear
        echo "======================================"
        echo "          Smite Management"
        echo "======================================"
        echo "1) Private Network Wizard (existing 10-step flow)"
        echo "2) Standard FRP Test Guide (experimental)"
        echo "3) Standard FRP Setup Wizard (IR/KH, experimental)"
        echo "0) Back"
        read -rp "Choose [0-3]: " choice
        case "$choice" in
            1) docker_smite_open_setup_wizard ;;
            2) docker_smite_frp_standard_guide ;;
            3) smite_frp_wizard_menu ;;
            0) return ;;
            *) echo "Invalid selection."; sleep 1 ;;
        esac
    done
}
