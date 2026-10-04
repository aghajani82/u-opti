#!/bin/bash

# U-OPTI - Smite EasyTier Private Network
# Provider-independent overlay validated with EasyTier v2.6.4.
# Transport: WSS over the existing Foreign Nginx TCP/443 vhost.
# Overlay: Iran 10.89.10.10/24 <-> Foreign 10.89.10.20/24.
# EasyTier UDP/STUN/UPnP/hole-punching/P2P are disabled.

SMITE_ET_VERSION="2.6.4"
SMITE_ET_DIR="${SMITE_ET_DIR:-/etc/u-opti/smite/easytier}"
SMITE_ET_CONFIG="$SMITE_ET_DIR/easytier.toml"
SMITE_ET_STATE="$SMITE_ET_DIR/state.env"
SMITE_ET_SECRET_FILE="$SMITE_ET_DIR/network.secret"
SMITE_ET_PATH_FILE="$SMITE_ET_DIR/nginx.path"
SMITE_ET_PAIRING_FILE="$SMITE_ET_DIR/pairing.env"
SMITE_ET_NGINX_BACKUP_DIR="$SMITE_ET_DIR/nginx-backups"
SMITE_ET_SERVICE="u-opti-smite-easytier.service"
SMITE_ET_CORE="/usr/local/bin/easytier-core"
SMITE_ET_CLI="/usr/local/bin/easytier-cli"
SMITE_ET_INTERFACE="smite-et0"
SMITE_ET_PANEL_IP="10.89.10.10"
SMITE_ET_FOREIGN_IP="10.89.10.20"
SMITE_ET_WS_PORT="19020"
SMITE_ET_RPC_PORT="15888"
SMITE_ET_NETWORK_NAME="uopti-smite"

smite_et_pause() { echo; read -rp "Press Enter to return..."; }
smite_et_require_root() { [ "$EUID" -eq 0 ] || { echo "ERROR: Root privileges are required."; return 1; }; }
smite_et_validate_domain() { [[ "$1" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]; }
smite_et_validate_path() { [[ "$1" =~ ^[A-Za-z0-9_-]{8,128}$ ]]; }
smite_et_validate_secret() { [[ "$1" =~ ^[A-Fa-f0-9]{64}$ ]]; }

smite_et_state_value() {
    [ -f "$SMITE_ET_STATE" ] || return 0
    awk -F= -v key="$1" '$1==key {print substr($0,index($0,"=")+1); exit}' "$SMITE_ET_STATE"
}

smite_et_set_state_value() {
    local key="$1" value="$2"
    install -d -m 0700 "$SMITE_ET_DIR" || return 1
    touch "$SMITE_ET_STATE" || return 1
    chmod 0600 "$SMITE_ET_STATE"
    if grep -q "^${key}=" "$SMITE_ET_STATE"; then
        sed -i "s#^${key}=.*#${key}=${value}#" "$SMITE_ET_STATE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$SMITE_ET_STATE"
    fi
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
    SMITE_ET_URL="https://github.com/EasyTier/EasyTier/releases/download/v${SMITE_ET_VERSION}/${SMITE_ET_ASSET}"
}

smite_et_install_binary() {
    local tmp archive actual
    smite_et_require_root || return 1
    smite_et_release_info || return 1

    if [ -x "$SMITE_ET_CORE" ] && "$SMITE_ET_CORE" --version 2>/dev/null | grep -q " ${SMITE_ET_VERSION}-"; then
        echo "EasyTier ${SMITE_ET_VERSION} is already installed."
        return 0
    fi

    # Freshly booted Ubuntu hosts can still be running unattended-upgrades.
    apt-get -o DPkg::Lock::Timeout=300 update || return 1
    DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 install -y \
        ca-certificates curl unzip openssl || return 1

    tmp="$(mktemp -d)" || return 1
    archive="$tmp/$SMITE_ET_ASSET"
    curl -fL --retry 3 --connect-timeout 15 "$SMITE_ET_URL" -o "$archive" || { rm -rf "$tmp"; return 1; }
    actual="$(sha256sum "$archive" | awk '{print $1}')"
    [ "$actual" = "$SMITE_ET_SHA256" ] || {
        rm -rf "$tmp"
        echo "ERROR: EasyTier checksum mismatch."
        echo "Expected: $SMITE_ET_SHA256"
        echo "Actual  : $actual"
        return 1
    }
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
ExecStart=$SMITE_ET_CORE --rpc-portal 127.0.0.1:$SMITE_ET_RPC_PORT --console-log-level warn -c $SMITE_ET_CONFIG
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF_SERVICE
    systemctl daemon-reload || return 1
    systemctl enable "$SMITE_ET_SERVICE" >/dev/null 2>&1 || return 1
}

smite_et_write_state() {
    local role="$1" domain="${2:-}" path="${3:-}"
    install -d -m 0700 "$SMITE_ET_DIR" || return 1
    umask 077
    cat > "$SMITE_ET_STATE" <<EOF_STATE
# Managed by U-OPTI. The network secret is stored separately.
SMITE_ET_ROLE=$role
SMITE_ET_TRANSPORT=wss-tcp-443
SMITE_ET_INTERFACE=$SMITE_ET_INTERFACE
SMITE_ET_PANEL_IP=$SMITE_ET_PANEL_IP
SMITE_ET_FOREIGN_IP=$SMITE_ET_FOREIGN_IP
SMITE_ET_FOREIGN_DOMAIN=$domain
SMITE_ET_HIDDEN_PATH=$path
SMITE_ET_WS_PORT=$SMITE_ET_WS_PORT
SMITE_ET_RPC_PORT=$SMITE_ET_RPC_PORT
SMITE_ET_VERSION=$SMITE_ET_VERSION
EOF_STATE
    chmod 0600 "$SMITE_ET_STATE"
}

smite_et_write_pairing() {
    local domain="$1" path="$2" secret="$3"
    umask 077
    cat > "$SMITE_ET_PAIRING_FILE" <<EOF_PAIR
# Sensitive. Copy these values only to the paired Iran server.
SMITE_ET_FOREIGN_DOMAIN=$domain
SMITE_ET_HIDDEN_PATH=$path
SMITE_ET_NETWORK_SECRET=$secret
SMITE_ET_PANEL_IP=$SMITE_ET_PANEL_IP
SMITE_ET_FOREIGN_IP=$SMITE_ET_FOREIGN_IP
EOF_PAIR
    chmod 0600 "$SMITE_ET_PAIRING_FILE"
}

smite_et_configure_foreign() {
    local domain="${1,,}" secret path
    smite_et_validate_domain "$domain" || { echo "ERROR: Invalid Foreign TLS domain."; return 1; }
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
disable_p2p = true
disable_upnp = true
disable_udp_hole_punching = true
disable_tcp_hole_punching = true
EOF_CONFIG
    chmod 0600 "$SMITE_ET_CONFIG"
    "$SMITE_ET_CORE" -c "$SMITE_ET_CONFIG" --check-config >/dev/null 2>&1 || { echo "ERROR: EasyTier config validation failed."; return 1; }
    smite_et_write_service || return 1
    smite_et_write_state foreign "$domain" "$path" || return 1
    smite_et_write_pairing "$domain" "$path" "$secret" || return 1

    echo "Foreign EasyTier config ready."
    echo "Private IP     : $SMITE_ET_FOREIGN_IP"
    echo "WS backend     : 127.0.0.1:$SMITE_ET_WS_PORT"
    echo "Foreign domain : $domain"
    echo "Hidden path    : $path"
    echo "Network secret : stored securely (not printed)"
}

smite_et_configure_panel() {
    local domain="${1,,}" path="$2" secret="$3"
    smite_et_validate_domain "$domain" || { echo "ERROR: Invalid Foreign TLS domain."; return 1; }
    smite_et_validate_path "$path" || { echo "ERROR: Invalid hidden path."; return 1; }
    smite_et_validate_secret "$secret" || { echo "ERROR: Secret must be 64 hexadecimal characters."; return 1; }
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
    "$SMITE_ET_CORE" -c "$SMITE_ET_CONFIG" --check-config >/dev/null 2>&1 || { echo "ERROR: EasyTier config validation failed."; return 1; }
    smite_et_write_service || return 1
    smite_et_write_state panel "$domain" "$path" || return 1
}

smite_et_find_nginx_vhost() {
    local domain="$1" file real
    for file in /etc/nginx/sites-enabled/* /etc/nginx/sites-available/*; do
        [ -e "$file" ] || continue
        real="$(readlink -f "$file" 2>/dev/null || printf '%s' "$file")"
        grep -Eq "^[[:space:]]*server_name[[:space:]].*\b${domain//./\\.}\b" "$real" 2>/dev/null || continue
        grep -Eq '^[[:space:]]*listen[[:space:]].*443.*ssl' "$real" 2>/dev/null || continue
        printf '%s\n' "$real"
        return 0
    done
    return 1
}

smite_et_nginx_setup() {
    local domain path vhost backup marker
    domain="${1:-$(smite_et_state_value SMITE_ET_FOREIGN_DOMAIN)}"
    path="${2:-$(smite_et_state_value SMITE_ET_HIDDEN_PATH)}"
    marker="    # Xray WebSocket / XHTTP / HTTP forwarding paths."

    smite_et_validate_domain "$domain" || { echo "ERROR: Invalid/missing Foreign domain."; return 1; }
    smite_et_validate_path "$path" || { echo "ERROR: Invalid/missing hidden path."; return 1; }
    command -v nginx >/dev/null 2>&1 || { echo "ERROR: Nginx is not installed."; return 1; }
    vhost="$(smite_et_find_nginx_vhost "$domain")" || {
        echo "ERROR: No TLS/443 Nginx vhost found for $domain."
        return 1
    }
    grep -Fq "$marker" "$vhost" || {
        echo "ERROR: U-OPTI Xray forwarding marker was not found in: $vhost"
        echo "Install/configure the Foreign 3x-UI Nginx vhost first."
        return 1
    }

    install -d -m 0700 "$SMITE_ET_NGINX_BACKUP_DIR" || return 1
    backup="$SMITE_ET_NGINX_BACKUP_DIR/$(basename "$vhost").$(date +%Y%m%d-%H%M%S).bak"
    cp -a "$vhost" "$backup" || return 1

    python3 - "$vhost" "$path" "$SMITE_ET_WS_PORT" <<'PY' || { cp -a "$backup" "$vhost"; return 1; }
from pathlib import Path
import re, sys
p=Path(sys.argv[1]); path=sys.argv[2]; port=sys.argv[3]
text=p.read_text()
marker="    # Xray WebSocket / XHTTP / HTTP forwarding paths."
text=re.sub(r'\n?\s*# BEGIN U-OPTI SMITE EASYTIER\n.*?\n\s*# END U-OPTI SMITE EASYTIER\n?', '\n', text, flags=re.S)
block=f'''\n    # BEGIN U-OPTI SMITE EASYTIER
    location = /{path} {{
        return 301 /{path}/;
    }}

    location ^~ /{path}/ {{
        proxy_pass http://127.0.0.1:{port}/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 1d;
        proxy_send_timeout 1d;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_socket_keepalive on;
        proxy_redirect off;
    }}
    # END U-OPTI SMITE EASYTIER
\n'''
if marker not in text: raise SystemExit("marker not found")
p.write_text(text.replace(marker, block+marker, 1))
PY

    if ! nginx -t; then
        echo "ERROR: Nginx validation failed; restoring backup."
        cp -a "$backup" "$vhost"
        nginx -t || true
        return 1
    fi
    systemctl reload nginx || { cp -a "$backup" "$vhost"; nginx -t && systemctl reload nginx || true; return 1; }
    smite_et_set_state_value SMITE_ET_NGINX_VHOST "$vhost"
    smite_et_set_state_value SMITE_ET_NGINX_BACKUP "$backup"
    echo "Nginx WSS path ready: https://$domain/$path/ -> 127.0.0.1:$SMITE_ET_WS_PORT"
}

smite_et_start() {
    local role expected tries=0
    [ -f "$SMITE_ET_CONFIG" ] || { echo "ERROR: EasyTier is not configured."; return 1; }
    smite_et_write_service || return 1
    systemctl restart "$SMITE_ET_SERVICE" || return 1
    role="$(smite_et_state_value SMITE_ET_ROLE)"
    case "$role" in panel) expected="$SMITE_ET_PANEL_IP" ;; foreign) expected="$SMITE_ET_FOREIGN_IP" ;; *) expected="" ;; esac
    while [ "$tries" -lt 15 ]; do
        if systemctl is-active --quiet "$SMITE_ET_SERVICE" && \
           ip -4 -o addr show dev "$SMITE_ET_INTERFACE" 2>/dev/null | grep -q " ${expected}/"; then
            echo "EasyTier active: $(ip -4 -o addr show dev "$SMITE_ET_INTERFACE" | awk '{print $4}' | head -n1)"
            return 0
        fi
        sleep 1; tries=$((tries+1))
    done
    systemctl --no-pager --full status "$SMITE_ET_SERVICE" | sed -n '1,16p'
    return 1
}

smite_et_show_pairing() {
    local confirm
    [ -f "$SMITE_ET_PAIRING_FILE" ] || { echo "ERROR: Pairing data is unavailable on this server."; return 1; }
    echo "WARNING: Pairing details contain the network secret."
    read -rp "Type SHOW to display them: " confirm
    [ "$confirm" = "SHOW" ] || { echo "Cancelled."; return 0; }
    echo
    cat "$SMITE_ET_PAIRING_FILE"
}

smite_et_connectivity_test() {
    local role peer failed=0
    role="$(smite_et_state_value SMITE_ET_ROLE)"
    case "$role" in panel) peer="$SMITE_ET_FOREIGN_IP" ;; foreign) peer="$SMITE_ET_PANEL_IP" ;; *) echo "ERROR: EasyTier role not initialized."; return 1 ;; esac
    ping -c 3 -W 2 "$peer" || failed=1
    if ss -lunp 2>/dev/null | grep -q easytier; then echo "EasyTier UDP: PRESENT (unexpected)"; failed=1; else echo "EasyTier UDP: None"; fi
    if [ "$role" = "panel" ]; then
        ss -ntp 2>/dev/null | grep easytier | grep ':443' || { echo "No EasyTier TCP/443 connection."; failed=1; }
    else
        ss -lntp 2>/dev/null | grep easytier || true
    fi
    [ "$failed" -eq 0 ] && echo "EasyTier connectivity test passed."
    return "$failed"
}

smite_et_migrate_smite_panel() {
    local env=/opt/smite-node/.env backup
    [ -f "$env" ] || { echo "ERROR: Install Smite Panel/Iran first."; return 1; }
    curl -fsS --max-time 3 "http://$SMITE_ET_PANEL_IP:8000/" >/dev/null 2>&1 || {
        echo "ERROR: Smite Panel is not reachable on $SMITE_ET_PANEL_IP:8000."
        echo "Use Smite Private Network mode after EasyTier is initialized, then retry."
        return 1
    }
    backup="${env}.before-easytier-$(date +%Y%m%d-%H%M%S).bak"; cp -a "$env" "$backup" || return 1
    if grep -q '^SMITE_BACKHAUL_ADDRESS=' "$env"; then sed -i "s/^SMITE_BACKHAUL_ADDRESS=.*/SMITE_BACKHAUL_ADDRESS=$SMITE_ET_PANEL_IP/" "$env"; else printf 'SMITE_BACKHAUL_ADDRESS=%s\n' "$SMITE_ET_PANEL_IP" >> "$env"; fi
    (cd /opt/smite-node && docker compose up -d --force-recreate smite-node) || return 1
    echo "Iran Smite node migrated. Backup: $backup"
}

smite_et_migrate_smite_foreign() {
    local env=/opt/smite-node/.env backup
    [ -f "$env" ] || { echo "ERROR: Install Smite Foreign first."; return 1; }
    curl -fsS --max-time 3 "http://$SMITE_ET_PANEL_IP:8000/" >/dev/null 2>&1 || {
        echo "ERROR: Iran Smite Panel is not reachable over EasyTier on $SMITE_ET_PANEL_IP:8000."
        return 1
    }
    backup="${env}.before-easytier-$(date +%Y%m%d-%H%M%S).bak"; cp -a "$env" "$backup" || return 1
    if grep -q '^PANEL_ADDRESS=' "$env"; then sed -i "s#^PANEL_ADDRESS=.*#PANEL_ADDRESS=$SMITE_ET_PANEL_IP:8000#" "$env"; else printf 'PANEL_ADDRESS=%s:8000\n' "$SMITE_ET_PANEL_IP" >> "$env"; fi
    if grep -q '^SMITE_CONTROL_ADDRESS=' "$env"; then sed -i "s#^SMITE_CONTROL_ADDRESS=.*#SMITE_CONTROL_ADDRESS=http://$SMITE_ET_FOREIGN_IP:8888#" "$env"; else printf 'SMITE_CONTROL_ADDRESS=http://%s:8888\n' "$SMITE_ET_FOREIGN_IP" >> "$env"; fi
    (cd /opt/smite-node && docker compose up -d --force-recreate smite-node) || return 1
    echo "Foreign Smite node migrated. Backup: $backup"
}

smite_et_reapply_active_tunnels() {
    local db=/opt/smite/panel/data/smite.db id failed=0 found=0
    command -v sqlite3 >/dev/null 2>&1 || { echo "ERROR: sqlite3 is required."; return 1; }
    [ -f "$db" ] || { echo "ERROR: Panel database not found."; return 1; }
    while IFS= read -r id; do
        [ -n "$id" ] || continue; found=1
        echo "Reapplying tunnel: $id"
        curl -fsS -X POST "http://127.0.0.1:8000/api/tunnels/$id/apply" >/dev/null || failed=$((failed+1))
    done < <(sqlite3 "$db" "SELECT id FROM tunnels WHERE status='active';")
    [ "$found" -eq 0 ] && { echo "No active tunnels found."; return 0; }
    [ "$failed" -eq 0 ] || { echo "ERROR: $failed tunnel(s) failed."; return 1; }
    echo "Active tunnels reapplied successfully."
}

smite_et_status() {
    local role peer service enabled runtime
    role="$(smite_et_state_value SMITE_ET_ROLE)"; service="$(systemctl is-active "$SMITE_ET_SERVICE" 2>/dev/null || true)"; enabled="$(systemctl is-enabled "$SMITE_ET_SERVICE" 2>/dev/null || true)"
    runtime="$(ip -4 -o addr show dev "$SMITE_ET_INTERFACE" 2>/dev/null | awk '{print $4}' | head -n1)"
    echo "Version       : $([ -x "$SMITE_ET_CORE" ] && "$SMITE_ET_CORE" --version 2>/dev/null || echo 'Not installed')"
    echo "Role          : ${role:-Not initialized}"
    echo "Transport     : WSS / TCP 443"
    echo "Runtime IP    : ${runtime:-Not assigned}"
    echo "Service       : ${service:-not-found}"
    echo "Boot enabled  : ${enabled:-not-found}"
    echo "Foreign domain: $(smite_et_state_value SMITE_ET_FOREIGN_DOMAIN)"
    if ss -lunp 2>/dev/null | grep -q easytier; then echo "EasyTier UDP  : PRESENT (unexpected)"; else echo "EasyTier UDP  : None"; fi
    echo; ss -lntp 2>/dev/null | grep easytier || true; ss -ntp 2>/dev/null | grep easytier | grep ESTAB || true
    case "$role" in panel) peer="$SMITE_ET_FOREIGN_IP" ;; foreign) peer="$SMITE_ET_PANEL_IP" ;; esac
    [ -n "${peer:-}" ] && [ "$service" = "active" ] && { echo; ping -c 2 -W 2 "$peer" || true; }
    [ -f /opt/smite-node/.env ] && { echo; grep -E '^(PANEL_ADDRESS|SMITE_CONTROL_ADDRESS|SMITE_BACKHAUL_ADDRESS)=' /opt/smite-node/.env || true; }
}

smite_et_init_foreign() {
    local domain confirm
    clear; echo "======================================"; echo "   Initialize EasyTier Foreign / KH"; echo "======================================"; echo
    echo "Requires an existing U-OPTI 3x-UI TLS/443 Nginx vhost on the Foreign domain."; echo
    read -rp "Foreign TLS domain: " domain; domain="${domain,,}"
    smite_et_validate_domain "$domain" || { echo "ERROR: Invalid domain."; smite_et_pause; return; }
    smite_et_find_nginx_vhost "$domain" >/dev/null || { echo "ERROR: TLS/443 vhost not found."; smite_et_pause; return; }
    read -rp "Initialize Foreign EasyTier? [y/N]: " confirm
    case "$confirm" in y|Y|yes|YES) ;; *) echo "Cancelled."; smite_et_pause; return ;; esac
    smite_et_configure_foreign "$domain" || { smite_et_pause; return; }
    smite_et_nginx_setup || { smite_et_pause; return; }
    smite_et_start || { smite_et_pause; return; }
    echo; echo "Foreign setup complete. Use option 3 to reveal pairing details for Iran."; smite_et_pause
}

smite_et_init_panel() {
    local domain path secret confirm
    clear; echo "======================================"; echo "    Initialize EasyTier Panel / Iran"; echo "======================================"; echo
    read -rp "Foreign TLS domain: " domain; domain="${domain,,}"
    read -rp "Hidden path: " path
    read -rsp "Network secret (input hidden): " secret; echo
    smite_et_validate_domain "$domain" && smite_et_validate_path "$path" && smite_et_validate_secret "$secret" || { echo "ERROR: Invalid pairing values."; smite_et_pause; return; }
    read -rp "Initialize Panel/Iran EasyTier? [y/N]: " confirm
    case "$confirm" in y|Y|yes|YES) ;; *) unset secret; echo "Cancelled."; smite_et_pause; return ;; esac
    smite_et_configure_panel "$domain" "$path" "$secret" || { unset secret; smite_et_pause; return; }; unset secret
    smite_et_start || { smite_et_pause; return; }
    echo; ping -c 3 -W 2 "$SMITE_ET_FOREIGN_IP" || echo "WARNING: Foreign overlay IP is not reachable yet."
    smite_et_pause
}

smite_et_migrate_role() {
    local role confirm
    role="$(smite_et_state_value SMITE_ET_ROLE)"
    echo "Existing provider/private networks are not removed. A Smite .env backup is created first."
    read -rp "Migrate detected role '${role:-unknown}' to EasyTier addresses? [y/N]: " confirm
    case "$confirm" in y|Y|yes|YES) ;; *) echo "Cancelled."; return ;; esac
    case "$role" in panel) smite_et_migrate_smite_panel ;; foreign) smite_et_migrate_smite_foreign ;; *) echo "ERROR: Initialize EasyTier first."; return 1 ;; esac
}

smite_et_repair() {
    local role
    role="$(smite_et_state_value SMITE_ET_ROLE)"
    [ -f "$SMITE_ET_CONFIG" ] || { echo "ERROR: EasyTier is not configured."; return 1; }
    if [ "$role" = "foreign" ]; then
        smite_et_nginx_setup || return 1
    fi
    smite_et_start || return 1
    smite_et_connectivity_test
}

show_smite_easytier_menu() {
    while true; do
        clear
        echo "======================================"
        echo "   Smite Private Network - EasyTier"
        echo "======================================"
        echo
        echo "WSS/TCP 443 | $SMITE_ET_PANEL_IP <-> $SMITE_ET_FOREIGN_IP"
        echo
        echo "1) Status"
        echo "2) Initialize Foreign / KH"
        echo "3) Show Pairing Details (Foreign)"
        echo "4) Initialize Panel / Iran"
        echo "5) Start / Restart EasyTier"
        echo "6) Connectivity Test"
        echo "7) Migrate Existing Smite Role"
        echo "8) Reapply Active Tunnels (Panel)"
        echo "9) Repair EasyTier / Nginx"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-9]: " choice
        case "$choice" in
            1) clear; smite_et_status; smite_et_pause ;;
            2) smite_et_init_foreign ;;
            3) clear; smite_et_show_pairing; smite_et_pause ;;
            4) smite_et_init_panel ;;
            5) clear; smite_et_start; smite_et_pause ;;
            6) clear; smite_et_connectivity_test; smite_et_pause ;;
            7) clear; smite_et_migrate_role; smite_et_pause ;;
            8) clear; smite_et_reapply_active_tunnels; smite_et_pause ;;
            9) clear; smite_et_repair; smite_et_pause ;;
            0) break ;;
            *) echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
