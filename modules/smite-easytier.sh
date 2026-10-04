#!/bin/bash

# U-OPTI - Smite EasyTier Private Network
# Validated topology:
#   Panel / Iran : 10.89.10.10/24
#   Foreign      : 10.89.10.20/24
#   Transport    : WSS over existing Nginx TCP 443
#   Foreign WS   : 127.0.0.1:19020
# EasyTier UDP listeners, STUN, UPnP and hole punching are disabled.
# Existing WireGuard/provider networks are never removed automatically.

SMITE_ET_VERSION="2.6.4"
SMITE_ET_DIR="${SMITE_ET_DIR:-/etc/u-opti/smite/easytier}"
SMITE_ET_CONFIG="${SMITE_ET_CONFIG:-$SMITE_ET_DIR/easytier.toml}"
SMITE_ET_STATE="${SMITE_ET_STATE:-$SMITE_ET_DIR/state.env}"
SMITE_ET_SECRET_FILE="${SMITE_ET_SECRET_FILE:-$SMITE_ET_DIR/network.secret}"
SMITE_ET_PATH_FILE="${SMITE_ET_PATH_FILE:-$SMITE_ET_DIR/nginx.path}"
SMITE_ET_SERVICE="${SMITE_ET_SERVICE:-u-opti-smite-easytier.service}"
SMITE_ET_CORE="${SMITE_ET_CORE:-/usr/local/bin/easytier-core}"
SMITE_ET_CLI="${SMITE_ET_CLI:-/usr/local/bin/easytier-cli}"
SMITE_ET_INTERFACE="${SMITE_ET_INTERFACE:-smite-et0}"
SMITE_ET_PANEL_IP="${SMITE_ET_PANEL_IP:-10.89.10.10}"
SMITE_ET_FOREIGN_IP="${SMITE_ET_FOREIGN_IP:-10.89.10.20}"
SMITE_ET_WS_PORT="${SMITE_ET_WS_PORT:-19020}"
SMITE_ET_RPC_PORT="${SMITE_ET_RPC_PORT:-15888}"
SMITE_ET_NETWORK_NAME="${SMITE_ET_NETWORK_NAME:-uopti-smite}"

smite_et_pause() { echo; read -rp "Press Enter to return..."; }

smite_et_state_value() {
    local key="$1"
    [ -f "$SMITE_ET_STATE" ] || return 0
    awk -F= -v key="$key" '$1 == key {print substr($0,index($0,"=")+1); exit}' "$SMITE_ET_STATE"
}

smite_et_release_info() {
    case "$(uname -m)" in
        x86_64)
            SMITE_ET_ASSET="easytier-linux-x86_64-v2.6.4.zip"
            SMITE_ET_ASSET_DIR="easytier-linux-x86_64"
            SMITE_ET_SHA256="61b659eaedba658fa66fe47d17e1426cdd77e5d02fa15fed447bb4357c09dfd6"
            ;;
        aarch64|arm64)
            SMITE_ET_ASSET="easytier-linux-aarch64-v2.6.4.zip"
            SMITE_ET_ASSET_DIR="easytier-linux-aarch64"
            SMITE_ET_SHA256="f533ec25a7ea714e09f645615012200278058525795cc3bb690ff011aec1a70f"
            ;;
        *) echo "ERROR: Unsupported architecture: $(uname -m)"; return 1 ;;
    esac
    SMITE_ET_URL="https://github.com/EasyTier/EasyTier/releases/download/v2.6.4/$SMITE_ET_ASSET"
}

smite_et_install_binary() {
    local tmp archive actual
    [ "$EUID" -eq 0 ] || { echo "ERROR: Root privileges are required."; return 1; }
    smite_et_release_info || return 1

    if [ -x "$SMITE_ET_CORE" ] && "$SMITE_ET_CORE" --version 2>/dev/null | grep -q ' 2.6.4-'; then
        return 0
    fi

    apt-get -o DPkg::Lock::Timeout=300 update || return 1
    DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 install -y ca-certificates curl unzip || return 1
    tmp="$(mktemp -d)" || return 1
    archive="$tmp/$SMITE_ET_ASSET"
    curl -fL --retry 3 "$SMITE_ET_URL" -o "$archive" || { rm -rf "$tmp"; return 1; }
    actual="$(sha256sum "$archive" | awk '{print $1}')"
    [ "$actual" = "$SMITE_ET_SHA256" ] || { rm -rf "$tmp"; echo "ERROR: EasyTier checksum mismatch."; return 1; }
    unzip -q "$archive" -d "$tmp/unpack" || { rm -rf "$tmp"; return 1; }
    install -m 0755 "$tmp/unpack/$SMITE_ET_ASSET_DIR/easytier-core" "$SMITE_ET_CORE" || { rm -rf "$tmp"; return 1; }
    install -m 0755 "$tmp/unpack/$SMITE_ET_ASSET_DIR/easytier-cli" "$SMITE_ET_CLI" || { rm -rf "$tmp"; return 1; }
    rm -rf "$tmp"
    "$SMITE_ET_CORE" --version
}

smite_et_write_service() {
    cat > "/etc/systemd/system/$SMITE_ET_SERVICE" <<EOF_SERVICE
[Unit]
Description=U-OPTI Smite EasyTier Private Network
Wants=network-online.target
After=network-online.target
ConditionPathExists=$SMITE_ET_CONFIG

[Service]
Type=simple
ExecStart=$SMITE_ET_CORE --rpc-portal 127.0.0.1:$SMITE_ET_RPC_PORT -c $SMITE_ET_CONFIG
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF_SERVICE
    systemctl daemon-reload
    systemctl enable "$SMITE_ET_SERVICE" >/dev/null 2>&1
}

smite_et_write_state() {
    local role="$1" domain="${2:-}" path="${3:-}"
    install -d -m 0700 "$SMITE_ET_DIR" || return 1
    umask 077
    cat > "$SMITE_ET_STATE" <<EOF_STATE
SMITE_ET_ROLE=$role
SMITE_ET_TRANSPORT=wss-tcp-443
SMITE_ET_INTERFACE=$SMITE_ET_INTERFACE
SMITE_ET_PANEL_IP=$SMITE_ET_PANEL_IP
SMITE_ET_FOREIGN_IP=$SMITE_ET_FOREIGN_IP
SMITE_ET_FOREIGN_DOMAIN=$domain
SMITE_ET_HIDDEN_PATH=$path
SMITE_ET_WS_PORT=$SMITE_ET_WS_PORT
EOF_STATE
    chmod 0600 "$SMITE_ET_STATE"
}

smite_et_configure_foreign() {
    local domain="$1" secret path
    [ -n "$domain" ] || { echo "Usage: smite_et_configure_foreign <tls-domain>"; return 1; }
    smite_et_install_binary || return 1
    install -d -m 0700 "$SMITE_ET_DIR" || return 1
    secret="$(openssl rand -hex 32)" || return 1
    path="$(openssl rand -hex 16)" || return 1
    printf '%s\n' "$secret" > "$SMITE_ET_SECRET_FILE"
    printf '%s\n' "$path" > "$SMITE_ET_PATH_FILE"
    chmod 0600 "$SMITE_ET_SECRET_FILE" "$SMITE_ET_PATH_FILE"

    cat > "$SMITE_ET_CONFIG" <<EOF_CONFIG
instance_name = "uopti-smite-easytier-foreign"
hostname = "$(hostname -s)"
ipv4 = "$SMITE_ET_FOREIGN_IP/24"
listeners = ["ws://127.0.0.1:$SMITE_ET_WS_PORT/"]
rpc_portal = "127.0.0.1:$SMITE_ET_RPC_PORT"
stun_servers = []
tcp_stun_servers = []
stun_servers_v6 = []

[network_identity]
network_name = "$SMITE_ET_NETWORK_NAME"
network_secret = "$secret"

[flags]
default_protocol = "ws"
enable_encryption = true
enable_ipv6 = false
dev_name = "$SMITE_ET_INTERFACE"
mtu = 1360
no_tun = false
private_mode = true
disable_upnp = true
disable_udp_hole_punching = true
disable_tcp_hole_punching = true
EOF_CONFIG
    chmod 0600 "$SMITE_ET_CONFIG"
    "$SMITE_ET_CORE" -c "$SMITE_ET_CONFIG" --check-config || return 1
    smite_et_write_service || return 1
    smite_et_write_state foreign "$domain" "$path"

    echo "Foreign EasyTier config ready."
    echo "Private IP     : $SMITE_ET_FOREIGN_IP"
    echo "WS backend     : 127.0.0.1:$SMITE_ET_WS_PORT"
    echo "Foreign domain : $domain"
    echo "Hidden path    : $path"
    echo "Network secret : $secret"
    echo "Next: proxy /$path/ in the existing Nginx TLS vhost to http://127.0.0.1:$SMITE_ET_WS_PORT/."
}

smite_et_configure_panel() {
    local domain="$1" path="$2" secret="$3"
    [ -n "$domain" ] && [ -n "$path" ] && [ -n "$secret" ] || {
        echo "Usage: smite_et_configure_panel <foreign-domain> <hidden-path> <network-secret>"
        return 1
    }
    smite_et_install_binary || return 1
    install -d -m 0700 "$SMITE_ET_DIR" || return 1
    printf '%s\n' "$secret" > "$SMITE_ET_SECRET_FILE"
    printf '%s\n' "$path" > "$SMITE_ET_PATH_FILE"
    chmod 0600 "$SMITE_ET_SECRET_FILE" "$SMITE_ET_PATH_FILE"

    cat > "$SMITE_ET_CONFIG" <<EOF_CONFIG
instance_name = "uopti-smite-easytier-panel"
hostname = "$(hostname -s)"
ipv4 = "$SMITE_ET_PANEL_IP/24"
listeners = []
rpc_portal = "127.0.0.1:$SMITE_ET_RPC_PORT"
stun_servers = []
tcp_stun_servers = []
stun_servers_v6 = []

[[peer]]
uri = "wss://$domain/$path/"

[network_identity]
network_name = "$SMITE_ET_NETWORK_NAME"
network_secret = "$secret"

[flags]
default_protocol = "wss"
enable_encryption = true
enable_ipv6 = false
dev_name = "$SMITE_ET_INTERFACE"
mtu = 1360
no_tun = false
private_mode = true
disable_p2p = true
disable_upnp = true
disable_udp_hole_punching = true
disable_tcp_hole_punching = true
EOF_CONFIG
    chmod 0600 "$SMITE_ET_CONFIG"
    "$SMITE_ET_CORE" -c "$SMITE_ET_CONFIG" --check-config || return 1
    smite_et_write_service || return 1
    smite_et_write_state panel "$domain" "$path"
}

smite_et_start() {
    systemctl restart "$SMITE_ET_SERVICE" || return 1
    sleep 2
    systemctl --no-pager --full status "$SMITE_ET_SERVICE" | sed -n '1,12p'
}

smite_et_migrate_smite_panel() {
    local env=/opt/smite-node/.env backup
    [ -f "$env" ] || { echo "ERROR: $env not found."; return 1; }
    backup="${env}.before-easytier-$(date +%Y%m%d-%H%M%S).bak"
    cp -a "$env" "$backup" || return 1
    if grep -q '^SMITE_BACKHAUL_ADDRESS=' "$env"; then
        sed -i "s/^SMITE_BACKHAUL_ADDRESS=.*/SMITE_BACKHAUL_ADDRESS=$SMITE_ET_PANEL_IP/" "$env"
    else
        printf 'SMITE_BACKHAUL_ADDRESS=%s\n' "$SMITE_ET_PANEL_IP" >> "$env"
    fi
    (cd /opt/smite-node && docker compose up -d --force-recreate smite-node)
}

smite_et_migrate_smite_foreign() {
    local env=/opt/smite-node/.env backup
    [ -f "$env" ] || { echo "ERROR: $env not found."; return 1; }
    backup="${env}.before-easytier-$(date +%Y%m%d-%H%M%S).bak"
    cp -a "$env" "$backup" || return 1
    if grep -q '^PANEL_ADDRESS=' "$env"; then
        sed -i "s#^PANEL_ADDRESS=.*#PANEL_ADDRESS=$SMITE_ET_PANEL_IP:8000#" "$env"
    else
        printf 'PANEL_ADDRESS=%s:8000\n' "$SMITE_ET_PANEL_IP" >> "$env"
    fi
    if grep -q '^SMITE_CONTROL_ADDRESS=' "$env"; then
        sed -i "s#^SMITE_CONTROL_ADDRESS=.*#SMITE_CONTROL_ADDRESS=http://$SMITE_ET_FOREIGN_IP:8888#" "$env"
    else
        printf 'SMITE_CONTROL_ADDRESS=http://%s:8888\n' "$SMITE_ET_FOREIGN_IP" >> "$env"
    fi
    (cd /opt/smite-node && docker compose up -d --force-recreate smite-node)
}

smite_et_reapply_active_tunnels() {
    local db=/opt/smite/panel/data/smite.db id failed=0
    [ -f "$db" ] || { echo "ERROR: Panel database not found."; return 1; }
    while IFS= read -r id; do
        [ -n "$id" ] || continue
        echo "Reapplying tunnel: $id"
        curl -fsS -X POST "http://127.0.0.1:8000/api/tunnels/$id/apply" >/dev/null || failed=$((failed+1))
    done < <(sqlite3 "$db" "SELECT id FROM tunnels WHERE status='active';")
    [ "$failed" -eq 0 ] || { echo "ERROR: $failed tunnel(s) failed."; return 1; }
    echo "Active tunnels reapplied successfully."
}

smite_et_status() {
    local role peer
    role="$(smite_et_state_value SMITE_ET_ROLE)"
    case "$role" in panel) peer="$SMITE_ET_FOREIGN_IP" ;; foreign) peer="$SMITE_ET_PANEL_IP" ;; *) peer="" ;; esac
    echo "Role          : ${role:-Not initialized}"
    echo "Transport     : WSS / TCP 443"
    echo "Service       : $(systemctl is-active "$SMITE_ET_SERVICE" 2>/dev/null || true)"
    echo "Boot enabled  : $(systemctl is-enabled "$SMITE_ET_SERVICE" 2>/dev/null || true)"
    echo "Runtime IP    : $(ip -4 -o addr show dev "$SMITE_ET_INTERFACE" 2>/dev/null | awk '{print $4}' | head -n1)"
    if ss -lunp 2>/dev/null | grep -q easytier; then
        echo "EasyTier UDP  : PRESENT (unexpected)"
    else
        echo "EasyTier UDP  : None"
    fi
    ss -lntup 2>/dev/null | grep easytier || true
    [ -z "$peer" ] || ping -c 2 -W 2 "$peer"
}

show_smite_easytier_menu() {
    while true; do
        clear
        echo "======================================"
        echo "   Smite EasyTier Private Network"
        echo "======================================"
        echo
        echo "1) Status"
        echo "2) Install / Verify EasyTier Binary"
        echo "3) Start / Restart EasyTier Service"
        echo "4) Migrate Smite Panel / Iran"
        echo "5) Migrate Smite Foreign Node"
        echo "6) Reapply Active Tunnels (Panel)"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-6]: " choice
        case "$choice" in
            1) clear; smite_et_status; smite_et_pause ;;
            2) clear; smite_et_install_binary; smite_et_pause ;;
            3) clear; smite_et_start; smite_et_pause ;;
            4) clear; smite_et_migrate_smite_panel; smite_et_pause ;;
            5) clear; smite_et_migrate_smite_foreign; smite_et_pause ;;
            6) clear; smite_et_reapply_active_tunnels; smite_et_pause ;;
            0) break ;;
            *) echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
