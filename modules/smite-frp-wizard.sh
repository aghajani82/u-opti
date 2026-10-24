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
    if [ "$role" = ir ] && declare -F smite_frp_xhttp_enabled >/dev/null 2>&1 &&
       smite_frp_xhttp_enabled; then
        echo "Standard FRP WSS compatibility: prepared (trusted IR gateway)"
    elif [ "$role" = kh ] &&
         [ "$(docker exec smite-node python3 -B -c 'from app.frp_gateway_config import frp_standard_wss_host; print(frp_standard_wss_host() or "OFF")' 2>/dev/null)" = "ir.kolbe1.ir" ]; then
        echo "Standard FRP WSS compatibility: prepared (Node runtime)"
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

# The actual beginner entry. Low-level procedures are retained under Advanced.
smite_frp_wizard_mode_label() {
    local mode=""
    mode="$(smite_frp_std_state SMITE_CONNECTION_MODE)"
    printf '%s' "${mode:-NOT INSTALLED (fresh host)}"
}

smite_frp_wizard_ready() {
    local role="$1"
    [ "$(smite_frp_std_state SMITE_CONNECTION_MODE)" = standard ] &&
        [ "$(smite_frp_wizard_role)" = "$role" ] &&
        smite_frp_std_running smite-node &&
        { [ "$role" = kh ] || smite_frp_std_running smite-panel; } || {
        echo "HOLD: Smite Standard role/containers not ready. Use START HERE or Status."
        echo "Do not repeat installation if an existing container is broken."
        return 2
    }
}

# Beginner installation deliberately ends after Smite Standard and HTTPS Gateway.
# Port/Path and Sanaei remain separate, explicitly selected later steps.
smite_frp_wizard_start_here() {
    local role="$1" mode="" answer=""
    echo "===== FRP START HERE | THIS HOST: $role ====="
    echo "Install/check Smite Standard, then explicitly offer HTTPS/443 gateway."
    echo "This does NOT create a Smite UI tunnel or KH Sanaei Xray inbound."
    mode="$(smite_frp_std_state SMITE_CONNECTION_MODE)"
    case "$mode" in
        standard)
            smite_frp_wizard_ready "$role" || {
                smite_frp_wizard_pause; return 2;
            }
            echo "Smite already installed and running. NO REINSTALL."
            ;;
        "")
            if command -v docker >/dev/null 2>&1 &&
               { docker container inspect smite-node >/dev/null 2>&1 ||
                 docker container inspect smite-panel >/dev/null 2>&1; }; then
                echo "HOLD: Smite containers with missing state; use recovery, NOT reinstall."
                smite_frp_wizard_pause; return 2
            fi
            if ! command -v docker >/dev/null 2>&1 ||
               ! docker compose version >/dev/null 2>&1 ||
               ! systemctl is-active --quiet docker; then
                echo "HOLD: First install Docker Engine and Compose in Docker Management."
                smite_frp_wizard_pause; return 2
            fi
            echo "Smite absent. Install this role using Standard mode."
            read -rp "Open Smite installer on THIS host now? [y/N]: " answer || return
            case "$answer" in y|Y|yes|YES) ;; *)
                echo "No changes."; smite_frp_wizard_pause; return ;;
            esac
            smite_frp_std_install "$role" || {
                echo "HOLD: Installer did not succeed."; smite_frp_wizard_pause; return 2;
            }
            smite_frp_wizard_ready "$role" || {
                echo "HOLD: Install returned but trusted state/containers not ready."
                echo "Do NOT install again without inspecting the state."
                smite_frp_wizard_pause; return 2
            }
            ;;
        *)
            echo "HOLD: Existing Smite mode '$mode'; refusing to switch mode."
            smite_frp_wizard_pause; return 2 ;;
    esac
    echo "HTTPS/443 gateway is a separate existing Nginx/Certbot installer."
    read -rp "Open gateway installer on THIS host now? [y/N]: " answer || return
    case "$answer" in
        y|Y|yes|YES)
            if [ "$role" = ir ]; then
                smite_gateway_configure_panel
            else
                smite_foreign_gateway_configure
            fi
            echo "Check gateway result, certificate and Nginx before proceeding."
            ;;
        *) echo "Gateway unchanged. Run START HERE again when ready." ;;
    esac
    if [ "$role" = ir ]; then
        echo "IR FOUNDATION COMPLETE. NEXT: Finish KH Smite Standard/Gateway."
    else
        echo "KH FOUNDATION COMPLETE. NEXT: Install KH Docker Sanaei from Docker Management."
    fi
    echo "If PROFILE FIRST was saved on IR: create/apply matching FRP TCP"
    echo "server tunnel in Smite UI; the guarded timer automatically publishes"
    echo "that saved XHTTP Path after Apply (NOT before)."
    echo "Without PROFILE FIRST: use FRP option 2 to save PORT + PATH first."
    echo "FRP option 2 also permits an explicitly confirmed manual override."
    echo "Finally, use FRP option 3 VERIFY on IR."
    echo "No FRP tunnel, Xray inbound or XHTTP route was auto-created here."
    smite_frp_wizard_pause
}

# One custom port+path input per action, without hidden legacy assumptions.
smite_frp_wizard_choose_profile() {
    local role="$1" port="" path="" default="" saved="" saved_port="" saved_path="" use_saved=""
    local helper="/usr/local/lib/u-opti/modules/smite-profile-first.py"
    if [ -s "$helper" ]; then
        saved="$(python3 -B "$helper" --show 2>/dev/null)" || saved=""
        if [ -n "$saved" ]; then
            saved_port="$(printf '%s\n' "$saved" | awk -F= '$1=="FRP_PORT" {print $2}')"
            saved_path="$(printf '%s\n' "$saved" | awk -F= '$1=="FRP_PATH" {print $2}')"
            if [ -n "$saved_port" ] && [ -n "$saved_path" ]; then
                echo "PROFILE FIRST: FRP port=$saved_port Path=$saved_path"
                read -rp "Use saved FRP profile? [Y/n]: " use_saved || return 2
                if [ "$use_saved" != n ] && [ "$use_saved" != N ]; then
                    python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" check "$saved_port" "$saved_path" >/dev/null || {
                        echo "HOLD: Saved FRP profile is invalid."; return 2;
                    }
                    SMITE_FRP_CHOSEN_PORT="$saved_port"
                    SMITE_FRP_CHOSEN_PATH="$saved_path"
                    return 0
                fi
            fi
        fi
    fi
    port="$(smite_frp_wizard_port)" || return 2
    if [ "$role" = ir ]; then
        default="$(smite_frp_xhttp_get_path "$port")" || return 2
    else
        default="/$port/web"
    fi
    read -rp "XHTTP base Path [$default], no trailing slash: " path || return 2
    path="${path:-$default}"
    path="${path%/}"
    python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" check "$port" "$path" >/dev/null || {
        echo "HOLD: Invalid/reserved/overlapping XHTTP profile."
        return 2
    }
    SMITE_FRP_CHOSEN_PORT="$port"
    SMITE_FRP_CHOSEN_PATH="$path"
}

smite_frp_wizard_easy_configure() {
    local role="$1" answer=""
    echo "===== FRP PORT + PATH | THIS HOST: $role ====="
    smite_frp_wizard_ready "$role" || { smite_frp_wizard_pause; return 2; }
    smite_frp_wizard_choose_profile "$role" || { smite_frp_wizard_pause; return 2; }
    echo "YOUR PORT: $SMITE_FRP_CHOSEN_PORT | YOUR PATH: $SMITE_FRP_CHOSEN_PATH"
    echo "KH Sanaei: VLESS/xhttp, 127.0.0.1:$SMITE_FRP_CHOSEN_PORT,"
    echo "security none, mode auto, Path $SMITE_FRP_CHOSEN_PATH"
    echo "Smite UI (AFTER saving this IR profile): Tunnels -> Create -> FRP -> TCP."
    echo "IR=server; KH=client; FRPS control=7000;"
    echo "Forwarded data port=$SMITE_FRP_CHOSEN_PORT (same as KH Sanaei)."
    if [ "$role" = kh ]; then
        echo "KH GUIDE ONLY: no inbound and no IR Nginx route was changed."
        echo "After Sanaei is ready, enter PORT + PATH on IR, then create the Smite tunnel."
        smite_frp_wizard_pause; return
    fi
    echo "IR can SAVE a safe pending profile before any Smite UI tunnel exists."
    echo "The XHTTP Nginx route activates ONLY after the corresponding FRP"
    echo "server tunnel is applied and the route sync timer publishes it."
    read -rp "Save this IR port/path (or update an applied tunnel)? [y/N]: " answer || return
    case "$answer" in y|Y|yes|YES) ;; *)
        echo "No change. IR FRP profile not saved."
        smite_frp_wizard_pause; return ;;
    esac
    if ! smite_frp_xhttp_stage_path "$SMITE_FRP_CHOSEN_PORT" "$SMITE_FRP_CHOSEN_PATH"; then
        echo "HOLD: IR FRP profile not accepted or published. Check local status."
        smite_frp_wizard_pause; return 2
    fi
    echo "NEXT: Apply FRP TCP in Smite UI, then option 3 VERIFY on IR."
    echo "Saving a pending profile is NOT proof of HTTPS/VLESS connectivity."
    smite_frp_wizard_pause
}

smite_frp_wizard_easy_verify() {
    local role="$1" domain="" url="" status="" headers="" args=()
    echo "===== FRP VERIFY | THIS HOST: $role | READ-ONLY ====="
    smite_frp_wizard_ready "$role" || { smite_frp_wizard_pause; return 2; }
    smite_frp_wizard_choose_profile "$role" || { smite_frp_wizard_pause; return 2; }
    domain="$(smite_frp_std_state SMITE_PANEL_DOMAIN)"
    # Never construct a curl URL/--resolve from malformed installed state.
    if [[ ! "$domain" =~ ^[A-Za-z0-9.-]+$ ]] || [[ "$domain" != *.* ]]; then
        echo "HOLD: Saved IR HTTPS hostname missing or unsafe."
        smite_frp_wizard_pause; return 2
    fi
    if [ "$role" = ir ]; then
        smite_frp_xhttp_verify_path "$SMITE_FRP_CHOSEN_PORT" "$SMITE_FRP_CHOSEN_PATH" || {
            echo "HOLD: IR Nginx Path not published."
            smite_frp_wizard_pause; return 2
        }
        [ -n "$domain" ] || {
            echo "HOLD: Saved IR domain missing."; smite_frp_wizard_pause; return 2;
        }
        url="https://$domain$SMITE_FRP_CHOSEN_PATH/"
        args=(--resolve "$domain:443:127.0.0.1")
    else
        url="http://127.0.0.1:$SMITE_FRP_CHOSEN_PORT$SMITE_FRP_CHOSEN_PATH/"
    fi
    headers="$(mktemp)" || return 2
    status="$(curl --noproxy '*' -4 -sS --http1.1 --connect-timeout 5 \
        --max-time 12 -X OPTIONS -D "$headers" -o /dev/null \
        -w '%{http_code}' "${args[@]}" "$url")" || status="network-error"
    echo "Endpoint: $url | HTTP: $status"
    local handler_ok=0
    if [ "$status" = 200 ] && grep -iq '^X-Padding:' "$headers"; then
        handler_ok=1
        echo "XHTTP_HANDLER_REACHED=YES"
    else
        echo "XHTTP_HANDLER_REACHED=NO (inspect Xray/FRP/Path/TLS)"
    fi
    rm -f -- "$headers"
    echo "Client: VLESS from KH Sanaei; IR hostname:443; TLS SNI=IR hostname;"
    echo "Network=xhttp; Path=$SMITE_FRP_CHOSEN_PATH; Mode=auto;"
    echo "ALPN=http/1.1; Fingerprint=chrome; Host=blank;"
    echo 'Extra: {"mode":"auto","xPaddingBytes":"100-1000"}'
    echo "An OPTIONS probe is NOT authenticated VLESS or throughput."
    echo "Test real v2rayN FRP + Backhaul traffic, then separate reboots."
    smite_frp_wizard_pause
    [ "$handler_ok" = 1 ]
}

smite_frp_wizard_advanced_menu() {
    local role="$1" choice=""
    while true; do
        clear
        echo "===== FRP ADVANCED | $role ====="
        echo "1) Read-only status"
        echo "2) Legacy Smite installer"
        echo "3) Legacy HTTPS gateway installer"
        echo "4) IR FRPS status / KH Docker Sanaei menu"
        echo "5) Legacy FRP TCP + IR Path guide"
        echo "6) Original XHTTP probe"
        echo "7) v2rayN client settings"
        echo "8) Repair and reboot checklist"
        echo "9) Response timing (read-only)"
        echo "0) Back"
        read -rp "Choose [0-9]: " choice || return
        choice="${choice#"${choice%%[![:space:]]*}"}"
        choice="${choice%"${choice##*[![:space:]]}"}"
        case "$choice" in
            1) smite_frp_wizard_status "$role" ;;
            2) smite_frp_std_install "$role" ;;
            3)
                if [ "$role" = ir ]; then
                    smite_gateway_configure_panel
                else
                    smite_foreign_gateway_configure
                fi ;;
            4)
                if [ "$role" = kh ]; then
                    show_docker_3xui_menu
                else
                    smite_frp_wizard_status "$role"
                fi ;;
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

smite_frp_wizard_menu() {
    local role="${1:-}" detected="" mode="" choice=""
    mode="$(smite_frp_std_state SMITE_CONNECTION_MODE)"
    if [ -n "$mode" ] && [ "$mode" != standard ]; then
        echo "HOLD: Existing mode $mode is not Standard; no changes."
        smite_frp_wizard_pause; return 2
    fi
    detected="$(smite_frp_wizard_role)"
    case "$role" in
        ir|kh)
            if [ "$detected" != unknown ] && [ "$detected" != "$role" ]; then
                echo "HOLD: Selected role conflicts with existing Smite role."
                smite_frp_wizard_pause; return 2
            fi ;;
        "") role="$detected" ;;
        *) echo "HOLD: Invalid logical IR/KH role."; return 2 ;;
    esac
    if [ "$role" = unknown ]; then
        echo "===== Select logical host role (once per menu) ====="
        echo "1) IR panel + Iran node | 2) KH foreign node | 0) Back"
        read -rp "Choose [0-2]: " choice || return
        choice="${choice#"${choice%%[![:space:]]*}"}"
        choice="${choice%"${choice##*[![:space:]]}"}"
        case "$choice" in 1) role=ir ;; 2) role=kh ;; *) return ;; esac
    fi
    while true; do
        clear
        echo "======================================"
        echo "      Standard FRP EASY SETUP"
        echo "======================================"
        echo "This server: $role | Smite: $(smite_frp_wizard_mode_label)"
        echo "With saved PROFILE FIRST: Smite UI FRP TCP Apply triggers auto-route sync."
        echo "Option 2 remains for explicit profile changes or recovery."
        echo "1) START HERE - Install/check Smite + HTTPS Gateway"
        echo "2) PORT + PATH - Save IR profile before Smite tunnel"
        echo "3) VERIFY - XHTTP, client settings and real-traffic checklist"
        echo "4) Advanced - Original detailed steps and recovery"
        echo "0) Back"
        read -rp "Choose [0-4]: " choice || return
        choice="${choice#"${choice%%[![:space:]]*}"}"
        choice="${choice%"${choice##*[![:space:]]}"}"
        case "$choice" in
            1) smite_frp_wizard_start_here "$role" ;;
            2) smite_frp_wizard_easy_configure "$role" ;;
            3) smite_frp_wizard_easy_verify "$role" ;;
            4) smite_frp_wizard_advanced_menu "$role" ;;
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
        choice="${choice#"${choice%%[![:space:]]*}"}"
        choice="${choice%"${choice##*[![:space:]]}"}"
        case "$choice" in
            1) docker_smite_open_setup_wizard ;;
            2) docker_smite_frp_standard_guide ;;
            3) smite_frp_wizard_menu ;;
            0) return ;;
            *) echo "Invalid selection."; sleep 1 ;;
        esac
    done
}
