#!/bin/bash

# U-OPTI - Smite Private Setup Progress / Wizard
# Read-only verification for the validated two-server Private Network flow.
# The only persistent user choice stored by this module is the selected
# Foreign Xray target port and reboot-validation bookkeeping. No secrets are
# read from or written to the progress state.

SMITE_SETUP_PROGRESS_DIR="${SMITE_SETUP_PROGRESS_DIR:-/etc/u-opti/smite/setup-progress}"
SMITE_SETUP_PROGRESS_STATE="$SMITE_SETUP_PROGRESS_DIR/state.env"
SMITE_SETUP_SMITE_STATE="${SMITE_SETUP_SMITE_STATE:-/etc/u-opti/smite/state.env}"
SMITE_SETUP_ET_STATE="${SMITE_SETUP_ET_STATE:-/etc/u-opti/smite/easytier/state.env}"
SMITE_SETUP_GATEWAY_STATE="${SMITE_SETUP_GATEWAY_STATE:-/etc/u-opti/smite/gateway.env}"
SMITE_SETUP_PANEL_DB="${SMITE_SETUP_PANEL_DB:-/opt/smite/panel/data/smite.db}"
SMITE_SETUP_PANEL_IP="10.89.10.10"
SMITE_SETUP_FOREIGN_IP="10.89.10.20"
SMITE_SETUP_ET_SERVICE="u-opti-smite-easytier.service"

smite_setup_progress_pause() {
    echo
    read -rp "Press Enter to return..."
}

smite_setup_progress_value() {
    local key="$1" file="$2"
    [ -f "$file" ] || return 0
    awk -F= -v key="$key" '$1 == key {print substr($0,index($0,"=")+1); exit}' "$file"
}

smite_setup_progress_set_value() {
    local key="$1" value="$2"
    install -d -m 0700 "$SMITE_SETUP_PROGRESS_DIR" || return 1
    touch "$SMITE_SETUP_PROGRESS_STATE" || return 1
    chmod 0600 "$SMITE_SETUP_PROGRESS_STATE" || return 1

    if grep -q "^${key}=" "$SMITE_SETUP_PROGRESS_STATE" 2>/dev/null; then
        sed -i "s#^${key}=.*#${key}=${value}#" "$SMITE_SETUP_PROGRESS_STATE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$SMITE_SETUP_PROGRESS_STATE"
    fi
}

smite_setup_progress_sm_state() {
    smite_setup_progress_value "$1" "$SMITE_SETUP_SMITE_STATE"
}

smite_setup_progress_et_state() {
    smite_setup_progress_value "$1" "$SMITE_SETUP_ET_STATE"
}

smite_setup_progress_host_role() {
    local role et_role
    role="$(smite_setup_progress_sm_state SMITE_ROLE)"
    if [ -n "$role" ]; then
        printf '%s' "$role"
        return 0
    fi

    et_role="$(smite_setup_progress_et_state SMITE_ET_ROLE)"
    case "$et_role" in
        panel) printf 'panel-iran' ;;
        foreign) printf 'foreign' ;;
        *) printf '' ;;
    esac
}

smite_setup_progress_mode() {
    local mode
    mode="$(smite_setup_progress_sm_state SMITE_CONNECTION_MODE)"
    [ -n "$mode" ] || mode="private"
    printf '%s' "$mode"
}

smite_setup_progress_panel_domain() {
    smite_setup_progress_sm_state SMITE_PANEL_DOMAIN
}

smite_setup_progress_foreign_domain() {
    local value
    value="$(smite_setup_progress_sm_state SMITE_FOREIGN_DOMAIN)"
    [ -n "$value" ] || value="$(smite_setup_progress_et_state SMITE_ET_FOREIGN_DOMAIN)"
    printf '%s' "$value"
}

smite_setup_progress_container_healthy() {
    local container="$1" state health
    command -v docker >/dev/null 2>&1 || return 1
    state="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || true)"
    [ "$state" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "none" ]; }
}

smite_setup_progress_docker_local() {
    command -v docker >/dev/null 2>&1 && \
    systemctl is-active --quiet docker 2>/dev/null && \
    docker compose version >/dev/null 2>&1
}

smite_setup_progress_ping() {
    ping -c 1 -W 2 "$1" >/dev/null 2>&1
}

smite_setup_progress_http_ok() {
    curl -fsS --connect-timeout 3 --max-time 6 "$1" >/dev/null 2>&1
}

smite_setup_progress_interface_has_ip() {
    local ip="$1"
    ip -4 -o addr show 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | grep -Fxq "$ip"
}

smite_setup_progress_et_local_ready() {
    local expected_role="$1" expected_ip="$2"
    [ "$(smite_setup_progress_et_state SMITE_ET_ROLE)" = "$expected_role" ] || return 1
    [ -s /etc/u-opti/smite/easytier/easytier.toml ] || return 1
    systemctl is-active --quiet "$SMITE_SETUP_ET_SERVICE" 2>/dev/null || return 1
    smite_setup_progress_interface_has_ip "$expected_ip"
}

smite_setup_progress_foreign_3xui_local() {
    local domain state_file container found=1
    domain="$(smite_setup_progress_foreign_domain)"

    for state_file in /opt/3x-ui/instances/[0-9][0-9]/state.env; do
        [ -s "$state_file" ] || continue
        if [ -n "$domain" ] && [ "$(smite_setup_progress_value DOMAIN "$state_file")" != "$domain" ]; then
            continue
        fi
        container="$(smite_setup_progress_value CONTAINER_NAME "$state_file")"
        [ -n "$container" ] || continue
        smite_setup_progress_container_healthy "$container" || continue
        found=0
        break
    done

    [ "$found" -eq 0 ] || return 1

    if [ -n "$domain" ]; then
        grep -RqsE "^[[:space:]]*server_name[[:space:]].*${domain//./\\.}" \
            /etc/nginx/sites-enabled 2>/dev/null || return 1
    fi

    return 0
}

smite_setup_progress_panel_local_ready() {
    [ "$(smite_setup_progress_sm_state SMITE_ROLE)" = "panel-iran" ] || return 1
    smite_setup_progress_container_healthy smite-panel || return 1
    smite_setup_progress_container_healthy smite-node || return 1
    smite_setup_progress_http_ok "http://127.0.0.1:8000/api/status"
}

smite_setup_progress_foreign_node_local_ready() {
    local panel_address control_address
    [ "$(smite_setup_progress_sm_state SMITE_ROLE)" = "foreign" ] || return 1
    [ "$(smite_setup_progress_sm_state SMITE_CONNECTION_MODE)" = "private" ] || return 1
    smite_setup_progress_container_healthy smite-node || return 1
    [ -s /opt/smite-node/.env ] || return 1

    panel_address="$(smite_setup_progress_value PANEL_ADDRESS /opt/smite-node/.env)"
    control_address="$(smite_setup_progress_value SMITE_CONTROL_ADDRESS /opt/smite-node/.env)"

    [ "$panel_address" = "${SMITE_SETUP_PANEL_IP}:8000" ] || return 1
    [ "$control_address" = "http://${SMITE_SETUP_FOREIGN_IP}:8888" ] || return 1
    smite_setup_progress_http_ok "http://127.0.0.1:8888/api/agent/status"
}

smite_setup_progress_panel_db_foreign_active() {
    [ -f "$SMITE_SETUP_PANEL_DB" ] || return 1
    command -v sqlite3 >/dev/null 2>&1 || return 1

    sqlite3 "$SMITE_SETUP_PANEL_DB" \
        "SELECT count(*) FROM nodes WHERE json_extract(metadata,'$.role')='foreign' AND json_extract(metadata,'$.control_address')='http://${SMITE_SETUP_FOREIGN_IP}:8888' AND status='active';" \
        2>/dev/null | grep -Eq '^[1-9][0-9]*$'
}

smite_setup_progress_panel_db_iran_active() {
    [ -f "$SMITE_SETUP_PANEL_DB" ] || return 1
    command -v sqlite3 >/dev/null 2>&1 || return 1

    sqlite3 "$SMITE_SETUP_PANEL_DB" \
        "SELECT count(*) FROM nodes WHERE json_extract(metadata,'$.role')='iran' AND status='active';" \
        2>/dev/null | grep -Eq '^[1-9][0-9]*$'
}

smite_setup_progress_panel_gateway_local_ready() {
    local domain
    domain="$(smite_setup_progress_panel_domain)"
    [ -n "$domain" ] || return 1
    [ -s "$SMITE_SETUP_GATEWAY_STATE" ] || return 1
    [ -s /etc/nginx/modules-enabled/99-u-opti-smite-stream.conf ] || return 1
    [ -s /etc/nginx/conf.d/u-opti-smite-panel-backend.conf ] || return 1
    systemctl is-active --quiet nginx 2>/dev/null || return 1
    nginx -t >/dev/null 2>&1 || return 1
    smite_setup_progress_http_ok "https://${domain}/api/status"
}

smite_setup_progress_remote_panel_gateway_ready() {
    local domain
    domain="$(smite_setup_progress_panel_domain)"
    [ -n "$domain" ] || return 1
    smite_setup_progress_http_ok "https://${domain}/api/status"
}

smite_setup_progress_xray_port() {
    smite_setup_progress_value SMITE_SETUP_XRAY_PORT "$SMITE_SETUP_PROGRESS_STATE"
}

smite_setup_progress_valid_port() {
    [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

smite_setup_progress_xray_local_ready() {
    local port
    port="$(smite_setup_progress_xray_port)"
    smite_setup_progress_valid_port "$port" || return 1

    ss -lntp 2>/dev/null | awk -v p=":${port}" '
        $1 == "LISTEN" && $4 ~ p "$" { found=1 }
        END { exit(found ? 0 : 1) }
    ' || return 1

    # The validated clean path binds the Xray target to loopback only.
    ss -lnt 2>/dev/null | awk -v p=":${port}" '
        $1 == "LISTEN" && ($4 == "127.0.0.1" p || $4 == "[::1]" p) { found=1 }
        END { exit(found ? 0 : 1) }
    '
}

smite_setup_progress_backhaul_panel_active() {
    [ -f "$SMITE_SETUP_PANEL_DB" ] || return 1
    command -v sqlite3 >/dev/null 2>&1 || return 1

    sqlite3 "$SMITE_SETUP_PANEL_DB" \
        "SELECT count(*) FROM tunnels WHERE core='backhaul' AND status='active' AND EXISTS (SELECT 1 FROM json_each(json_extract(spec,'$.ports')) WHERE CAST(value AS TEXT) LIKE '%443%');" \
        2>/dev/null | grep -Eq '^[1-9][0-9]*$'
}

smite_setup_progress_backhaul_foreign_active() {
    local json
    json="$(curl -fsS --max-time 5 http://127.0.0.1:8888/api/agent/status 2>/dev/null || true)"
    [ -n "$json" ] || return 1
    python3 - "$json" <<'PY' >/dev/null 2>&1
import json, sys
try:
    data = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(1)
count = data.get("active_tunnels", 0)
try:
    count = int(count)
except Exception:
    count = 0
raise SystemExit(0 if count > 0 else 1)
PY
}

smite_setup_progress_xray_infer_from_panel_backhaul() {
    [ -f "$SMITE_SETUP_PANEL_DB" ] || return 1
    command -v sqlite3 >/dev/null 2>&1 || return 1

    sqlite3 "$SMITE_SETUP_PANEL_DB" \
        "SELECT count(*) FROM tunnels WHERE core='backhaul' AND status='active' AND EXISTS (SELECT 1 FROM json_each(json_extract(spec,'$.ports')) WHERE CAST(value AS TEXT) GLOB '*443=127.0.0.1:[0-9]*');" \
        2>/dev/null | grep -Eq '^[1-9][0-9]*$'
}

smite_setup_progress_remote_docker_evidence() {
    local role="$1"
    case "$role" in
        panel-iran)
            smite_setup_progress_panel_db_foreign_active
            ;;
        foreign)
            smite_setup_progress_http_ok "http://${SMITE_SETUP_PANEL_IP}:8000/api/status"
            ;;
        *)
            return 1
            ;;
    esac
}

smite_setup_progress_reboot_local_complete() {
    local validated_boot current_boot
    validated_boot="$(smite_setup_progress_value SMITE_SETUP_REBOOT_VALIDATED_BOOT_ID "$SMITE_SETUP_PROGRESS_STATE")"
    [ -n "$validated_boot" ] || return 1
    current_boot="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"
    [ -n "$current_boot" ] && [ "$validated_boot" = "$current_boot" ]
}

smite_setup_progress_local_health() {
    local role
    role="$(smite_setup_progress_host_role)"
    smite_setup_progress_docker_local || return 1

    case "$role" in
        panel-iran)
            smite_setup_progress_et_local_ready panel "$SMITE_SETUP_PANEL_IP" || return 1
            smite_setup_progress_panel_local_ready || return 1
            smite_setup_progress_panel_gateway_local_ready || return 1
            ;;
        foreign)
            smite_setup_progress_foreign_3xui_local || return 1
            smite_setup_progress_et_local_ready foreign "$SMITE_SETUP_FOREIGN_IP" || return 1
            smite_setup_progress_foreign_node_local_ready || return 1
            ;;
        *)
            return 1
            ;;
    esac

    return 0
}

smite_setup_progress_collect() {
    local role
    role="$(smite_setup_progress_host_role)"

    SMITE_SETUP_STATUS=()
    SMITE_SETUP_DETAIL=()

    # 1. BOTH -> Docker
    if smite_setup_progress_docker_local; then
        if smite_setup_progress_remote_docker_evidence "$role"; then
            SMITE_SETUP_STATUS[1]="done"
            SMITE_SETUP_DETAIL[1]="Docker verified locally and peer Docker inferred from active Smite service"
        else
            SMITE_SETUP_STATUS[1]="partial"
            SMITE_SETUP_DETAIL[1]="Docker verified on this server; peer not yet independently observable"
        fi
    else
        SMITE_SETUP_STATUS[1]="todo"
        SMITE_SETUP_DETAIL[1]="Docker Engine/Compose is not ready on this server"
    fi

    # 2. KH -> 3x-UI
    if [ "$role" = "foreign" ]; then
        if smite_setup_progress_foreign_3xui_local; then
            SMITE_SETUP_STATUS[2]="done"
            SMITE_SETUP_DETAIL[2]="Foreign 3x-UI instance/container and Nginx domain verified"
        else
            SMITE_SETUP_STATUS[2]="todo"
            SMITE_SETUP_DETAIL[2]="Foreign 3x-UI is not fully verified"
        fi
    elif smite_setup_progress_ping "$SMITE_SETUP_FOREIGN_IP" && \
         [ "$(smite_setup_progress_et_state SMITE_ET_ROLE)" = "panel" ]; then
        SMITE_SETUP_STATUS[2]="done"
        SMITE_SETUP_DETAIL[2]="Inferred from the validated EasyTier Foreign dependency and reachable Foreign peer"
    else
        SMITE_SETUP_STATUS[2]="partial"
        SMITE_SETUP_DETAIL[2]="Switch to KH for direct 3x-UI verification"
    fi

    # 3. KH -> EasyTier Foreign
    if [ "$role" = "foreign" ]; then
        if smite_setup_progress_et_local_ready foreign "$SMITE_SETUP_FOREIGN_IP"; then
            SMITE_SETUP_STATUS[3]="done"
            SMITE_SETUP_DETAIL[3]="Foreign EasyTier service/state/interface verified"
        else
            SMITE_SETUP_STATUS[3]="todo"
            SMITE_SETUP_DETAIL[3]="Foreign EasyTier is not ready"
        fi
    elif [ "$(smite_setup_progress_et_state SMITE_ET_ROLE)" = "panel" ] && \
         smite_setup_progress_ping "$SMITE_SETUP_FOREIGN_IP"; then
        SMITE_SETUP_STATUS[3]="done"
        SMITE_SETUP_DETAIL[3]="Foreign EasyTier peer responds over the overlay"
    else
        SMITE_SETUP_STATUS[3]="todo"
        SMITE_SETUP_DETAIL[3]="Foreign EasyTier peer is not verified"
    fi

    # 4. IR -> EasyTier Panel
    if [ "$role" = "panel-iran" ]; then
        if smite_setup_progress_et_local_ready panel "$SMITE_SETUP_PANEL_IP" && \
           smite_setup_progress_ping "$SMITE_SETUP_FOREIGN_IP"; then
            SMITE_SETUP_STATUS[4]="done"
            SMITE_SETUP_DETAIL[4]="Iran EasyTier service/interface and Foreign peer connectivity verified"
        else
            SMITE_SETUP_STATUS[4]="todo"
            SMITE_SETUP_DETAIL[4]="Iran EasyTier is not fully ready"
        fi
    elif [ "$role" = "foreign" ] && smite_setup_progress_ping "$SMITE_SETUP_PANEL_IP"; then
        SMITE_SETUP_STATUS[4]="done"
        SMITE_SETUP_DETAIL[4]="Iran EasyTier peer responds over the overlay"
    else
        SMITE_SETUP_STATUS[4]="todo"
        SMITE_SETUP_DETAIL[4]="Iran EasyTier peer is not verified"
    fi

    # 5. IR -> Smite Panel + Iran Node
    if [ "$role" = "panel-iran" ]; then
        if smite_setup_progress_panel_local_ready && smite_setup_progress_panel_db_iran_active; then
            SMITE_SETUP_STATUS[5]="done"
            SMITE_SETUP_DETAIL[5]="Smite Panel and Iran node are healthy/active"
        else
            SMITE_SETUP_STATUS[5]="todo"
            SMITE_SETUP_DETAIL[5]="Smite Panel/Iran node is not fully verified"
        fi
    elif smite_setup_progress_http_ok "http://${SMITE_SETUP_PANEL_IP}:8000/api/status"; then
        SMITE_SETUP_STATUS[5]="done"
        SMITE_SETUP_DETAIL[5]="Iran Panel API responds over EasyTier"
    else
        SMITE_SETUP_STATUS[5]="todo"
        SMITE_SETUP_DETAIL[5]="Iran Panel API is not reachable over EasyTier"
    fi

    # 6. KH -> Smite Foreign Node
    if [ "$role" = "foreign" ]; then
        if smite_setup_progress_foreign_node_local_ready; then
            SMITE_SETUP_STATUS[6]="done"
            SMITE_SETUP_DETAIL[6]="Foreign node is healthy with Private control address"
        else
            SMITE_SETUP_STATUS[6]="todo"
            SMITE_SETUP_DETAIL[6]="Foreign Smite node is not fully verified"
        fi
    elif [ "$role" = "panel-iran" ] && smite_setup_progress_panel_db_foreign_active; then
        SMITE_SETUP_STATUS[6]="done"
        SMITE_SETUP_DETAIL[6]="Foreign node is active in the Panel with Private control address"
    else
        SMITE_SETUP_STATUS[6]="todo"
        SMITE_SETUP_DETAIL[6]="Foreign Smite node is not active in the Panel"
    fi

    # 7. IR -> Panel 443 Gateway
    if [ "$role" = "panel-iran" ]; then
        if smite_setup_progress_panel_gateway_local_ready; then
            SMITE_SETUP_STATUS[7]="done"
            SMITE_SETUP_DETAIL[7]="Panel HTTPS/443 gateway and Nginx stream configuration verified"
        else
            SMITE_SETUP_STATUS[7]="todo"
            SMITE_SETUP_DETAIL[7]="Panel HTTPS/443 gateway is not fully verified"
        fi
    elif smite_setup_progress_remote_panel_gateway_ready; then
        SMITE_SETUP_STATUS[7]="done"
        SMITE_SETUP_DETAIL[7]="Panel HTTPS endpoint responds from the Foreign server"
    else
        SMITE_SETUP_STATUS[7]="todo"
        SMITE_SETUP_DETAIL[7]="Panel HTTPS/443 endpoint is not verified"
    fi

    # 8. KH -> Xray/VLESS loopback
    if [ "$role" = "foreign" ]; then
        if smite_setup_progress_xray_local_ready; then
            SMITE_SETUP_STATUS[8]="done"
            SMITE_SETUP_DETAIL[8]="Configured Xray target port $(smite_setup_progress_xray_port) is listening on loopback"
        elif [ -n "$(smite_setup_progress_xray_port)" ]; then
            SMITE_SETUP_STATUS[8]="todo"
            SMITE_SETUP_DETAIL[8]="Saved Xray target port is not listening on loopback"
        else
            SMITE_SETUP_STATUS[8]="todo"
            SMITE_SETUP_DETAIL[8]="Create the Xray/VLESS loopback inbound, then register its port in this wizard"
        fi
    elif smite_setup_progress_xray_infer_from_panel_backhaul; then
        SMITE_SETUP_STATUS[8]="done"
        SMITE_SETUP_DETAIL[8]="Xray loopback target inferred from the active Backhaul custom mapping"
    else
        SMITE_SETUP_STATUS[8]="todo"
        SMITE_SETUP_DETAIL[8]="Switch to KH to create and verify the Xray/VLESS loopback target"
    fi

    # 9. PANEL -> Backhaul
    if [ "$role" = "panel-iran" ]; then
        if smite_setup_progress_backhaul_panel_active; then
            SMITE_SETUP_STATUS[9]="done"
            SMITE_SETUP_DETAIL[9]="Active Backhaul tunnel with logical 443 mapping found in Smite DB"
        else
            SMITE_SETUP_STATUS[9]="todo"
            SMITE_SETUP_DETAIL[9]="No active Backhaul logical-443 tunnel found"
        fi
    elif [ "$role" = "foreign" ] && smite_setup_progress_backhaul_foreign_active; then
        SMITE_SETUP_STATUS[9]="done"
        SMITE_SETUP_DETAIL[9]="Foreign Smite node reports one or more active tunnels"
    else
        SMITE_SETUP_STATUS[9]="todo"
        SMITE_SETUP_DETAIL[9]="Backhaul is not active yet"
    fi

    # 10. BOTH -> Final + reboot tests. This is intentionally local evidence only.
    if smite_setup_progress_reboot_local_complete; then
        SMITE_SETUP_STATUS[10]="partial"
        SMITE_SETUP_DETAIL[10]="This host passed post-reboot validation; repeat/confirm on the peer host"
    else
        SMITE_SETUP_STATUS[10]="todo"
        SMITE_SETUP_DETAIL[10]="Prepare and validate reboot on both hosts after end-to-end testing"
    fi
}

smite_setup_progress_symbol() {
    case "$1" in
        done) printf '[✓]' ;;
        partial) printf '[~]' ;;
        *) printf '[ ]' ;;
    esac
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
    printf '10'
}

smite_setup_progress_next_text() {
    case "$1" in
        1) echo "BOTH -> Install/verify Docker Engine + Compose on both servers" ;;
        2) echo "KH   -> Install Sanaei 3x-UI and complete its managed Nginx/SSL setup" ;;
        3) echo "KH   -> EasyTier Private Network -> Initialize Foreign / KH" ;;
        4) echo "IR   -> EasyTier Private Network -> Initialize Panel / Iran" ;;
        5) echo "IR   -> Install Smite Components -> Install Panel + Iran Node -> Private Network" ;;
        6) echo "KH   -> Install Smite Components -> Install Foreign Node -> Private Network" ;;
        7) echo "IR   -> Panel 443 Gateway (Iran) -> Configure / Repair Panel Gateway" ;;
        8) echo "KH   -> Create Xray/VLESS loopback inbound, then register/verify its port here" ;;
        9) echo "PANEL-> Create the Backhaul tunnel with logical port 443 and custom Xray target" ;;
        10) echo "BOTH -> Run end-to-end checks, then reboot KH and IR and validate again" ;;
    esac
}

smite_setup_progress_render() {
    local role mode i done_count=0 next
    role="$(smite_setup_progress_host_role)"
    mode="$(smite_setup_progress_mode)"

    smite_setup_progress_collect

    for i in 1 2 3 4 5 6 7 8 9; do
        [ "${SMITE_SETUP_STATUS[$i]}" = "done" ] && done_count=$((done_count + 1))
    done
    smite_setup_progress_reboot_local_complete && done_count=$((done_count + 1))

    next="$(smite_setup_progress_next_step)"

    clear
    echo "======================================"
    echo "     Smite Private Setup Progress"
    echo "======================================"
    echo
    echo "Host role : ${role:-not detected}"
    echo "Mode      : ${mode:-not detected}"
    echo
    printf '%s 1. BOTH  -> Docker\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[1]}")"
    printf '%s 2. KH    -> 3x-UI\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[2]}")"
    printf '%s 3. KH    -> EasyTier Foreign\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[3]}")"
    printf '%s 4. IR    -> EasyTier Panel\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[4]}")"
    printf '%s 5. IR    -> Smite Panel + Iran Node\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[5]}")"
    printf '%s 6. KH    -> Smite Foreign Node\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[6]}")"
    printf '%s 7. IR    -> Panel 443 Gateway\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[7]}")"
    printf '%s 8. KH    -> Xray/VLESS loopback\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[8]}")"
    printf '%s 9. PANEL -> Backhaul\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[9]}")"
    printf '%s 10. BOTH -> Final + Reboot tests\n' "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[10]}")"
    echo
    echo "--------------------------------------"
    echo "Verified : $done_count / 10"
    echo "Next     : $(smite_setup_progress_next_text "$next")"
    echo "--------------------------------------"
    echo
    echo "Legend: [✓] verified   [~] partial/peer evidence   [ ] not verified"
}

smite_setup_progress_details() {
    local i
    smite_setup_progress_collect
    clear
    echo "======================================"
    echo "      Smite Setup Detailed Checks"
    echo "======================================"
    echo
    for i in 1 2 3 4 5 6 7 8 9 10; do
        printf '%s Step %s: %s\n' \
            "$(smite_setup_progress_symbol "${SMITE_SETUP_STATUS[$i]}")" \
            "$i" \
            "${SMITE_SETUP_DETAIL[$i]}"
    done
    smite_setup_progress_pause
}

smite_setup_progress_show_next() {
    local next
    smite_setup_progress_collect
    next="$(smite_setup_progress_next_step)"

    clear
    echo "======================================"
    echo "         Smite Next Setup Step"
    echo "======================================"
    echo
    echo "Step $next"
    echo "$(smite_setup_progress_next_text "$next")"
    echo
    echo "Current check:"
    echo "${SMITE_SETUP_DETAIL[$next]}"
    smite_setup_progress_pause
}

smite_setup_progress_set_xray_port() {
    local role port
    role="$(smite_setup_progress_host_role)"

    clear
    echo "======================================"
    echo "       Xray Loopback Target Port"
    echo "======================================"
    echo

    if [ "$role" != "foreign" ]; then
        echo "This check must be configured on the Foreign / KH server."
        echo "Detected role: ${role:-not detected}"
        smite_setup_progress_pause
        return
    fi

    read -rp "Xray/VLESS loopback port (example: 10000): " port
    if ! smite_setup_progress_valid_port "$port"; then
        echo "ERROR: Invalid TCP port."
        smite_setup_progress_pause
        return
    fi

    if ! ss -lnt 2>/dev/null | awk -v p=":${port}" '
        $1 == "LISTEN" && ($4 == "127.0.0.1" p || $4 == "[::1]" p) { found=1 }
        END { exit(found ? 0 : 1) }
    '; then
        echo "ERROR: Nothing is listening on loopback port $port."
        echo "Create/fix the Xray inbound first; no progress state was changed."
        smite_setup_progress_pause
        return
    fi

    smite_setup_progress_set_value SMITE_SETUP_XRAY_PORT "$port" || {
        echo "ERROR: Could not save the verified target port."
        smite_setup_progress_pause
        return
    }

    echo "Xray target verified and saved: 127.0.0.1:$port"
    smite_setup_progress_pause
}

smite_setup_progress_prepare_reboot() {
    local boot_id
    boot_id="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"
    [ -n "$boot_id" ] || {
        echo "ERROR: Could not read the current boot ID."
        smite_setup_progress_pause
        return
    }

    smite_setup_progress_set_value SMITE_SETUP_REBOOT_BASELINE_BOOT_ID "$boot_id" || {
        echo "ERROR: Could not save reboot baseline."
        smite_setup_progress_pause
        return
    }
    smite_setup_progress_set_value SMITE_SETUP_REBOOT_VALIDATED_BOOT_ID "" || true

    clear
    echo "======================================"
    echo "       Reboot Baseline Recorded"
    echo "======================================"
    echo
    echo "Baseline for this host is recorded."
    echo "Reboot this host only when the end-to-end client test is already passing."
    echo "After reboot, return here and choose Validate This Host After Reboot."
    smite_setup_progress_pause
}

smite_setup_progress_validate_after_reboot() {
    local baseline current
    baseline="$(smite_setup_progress_value SMITE_SETUP_REBOOT_BASELINE_BOOT_ID "$SMITE_SETUP_PROGRESS_STATE")"
    current="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"

    clear
    echo "======================================"
    echo "       Post-Reboot Validation"
    echo "======================================"
    echo

    if [ -z "$baseline" ]; then
        echo "No reboot baseline exists on this host."
        echo "Use Prepare This Host for Reboot Validation before rebooting."
        smite_setup_progress_pause
        return
    fi

    if [ "$baseline" = "$current" ]; then
        echo "This host has not rebooted since the baseline was recorded."
        echo "No completion marker was written."
        smite_setup_progress_pause
        return
    fi

    if ! smite_setup_progress_local_health; then
        echo "ERROR: One or more required local services/checks failed after reboot."
        echo "Use Detailed Checks before marking this host complete."
        smite_setup_progress_pause
        return
    fi

    smite_setup_progress_set_value SMITE_SETUP_REBOOT_VALIDATED_BOOT_ID "$current" || {
        echo "ERROR: Could not store post-reboot validation state."
        smite_setup_progress_pause
        return
    }

    echo "This host passed its post-reboot service validation."
    echo "Repeat the reboot validation on the peer host as well."
    smite_setup_progress_pause
}

show_smite_setup_progress_menu() {
    local choice
    while true; do
        smite_setup_progress_render
        echo
        echo "1) Show Next Step"
        echo "2) Detailed Checks"
        echo "3) Set / Verify Xray Target Port (KH)"
        echo "4) Re-check Progress"
        echo "5) Prepare This Host for Reboot Validation"
        echo "6) Validate This Host After Reboot"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-6]: " choice

        case "$choice" in
            1) smite_setup_progress_show_next ;;
            2) smite_setup_progress_details ;;
            3) smite_setup_progress_set_xray_port ;;
            4) : ;;
            5) smite_setup_progress_prepare_reboot ;;
            6) smite_setup_progress_validate_after_reboot ;;
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
