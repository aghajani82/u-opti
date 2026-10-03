#!/bin/bash

# U-OPTI - Smite Private Network Peer Management
# This module is sourced after smite-private-network.sh.
# It manages only WireGuard peer metadata/configuration. It does not change
# Smite, provider private networks, or provider firewall settings.

smite_private_peer_validate_public_key() {
    local key="$1"
    local decoded_size=""

    [[ "$key" =~ ^[A-Za-z0-9+/]{43}=$ ]] || return 1

    decoded_size="$(printf '%s' "$key" | base64 -d 2>/dev/null | wc -c | tr -d '[:space:]')"
    [ "$decoded_size" = "32" ]
}

smite_private_peer_ipv4_in_cidr() {
    local value="$1"
    local cidr="$2"

    python3 - "$value" "$cidr" <<'PY' >/dev/null 2>&1
import ipaddress
import sys

try:
    ip = ipaddress.ip_address(sys.argv[1])
    network = ipaddress.ip_network(sys.argv[2], strict=False)
except ValueError:
    raise SystemExit(1)

raise SystemExit(0 if ip.version == 4 and network.version == 4 and ip in network else 1)
PY
}

smite_private_peer_primary_ipv4() {
    ip -4 route get 1.1.1.1 2>/dev/null \
        | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}'
}

smite_private_peer_ready() {
    if [ ! -f "$SMITE_PRIVATE_STATE_FILE" ]; then
        echo "ERROR: Smite Private Network has not been initialized on this server."
        return 1
    fi

    if [ ! -f "$SMITE_PRIVATE_WG_CONFIG" ]; then
        echo "ERROR: WireGuard configuration is missing: $SMITE_PRIVATE_WG_CONFIG"
        return 1
    fi

    if ! smite_private_interface_exists; then
        echo "ERROR: Interface $SMITE_PRIVATE_INTERFACE is not present."
        return 1
    fi

    if ! smite_private_interface_up; then
        echo "ERROR: Interface $SMITE_PRIVATE_INTERFACE is not UP."
        return 1
    fi

    return 0
}

smite_private_peer_show_pairing_info() {
    local role=""
    local local_ip=""
    local public_key=""
    local listen_port=""
    local primary_ip=""

    clear
    echo "======================================"
    echo "     Smite WireGuard Pairing Info"
    echo "======================================"
    echo

    if ! smite_private_peer_ready; then
        smite_private_pause
        return
    fi

    role="$(smite_private_state_value SMITE_PRIVATE_ROLE)"
    local_ip="$(smite_private_state_value SMITE_PRIVATE_LOCAL_IP)"
    listen_port="$(smite_private_state_value SMITE_PRIVATE_LISTEN_PORT)"
    public_key="$(smite_private_public_key)"
    primary_ip="$(smite_private_peer_primary_ipv4)"

    echo "Role          : ${role:-Unknown}"
    echo "Interface     : $SMITE_PRIVATE_INTERFACE"
    echo "Private IP    : ${local_ip:-Unknown}"
    echo "Public key    : ${public_key:-Unavailable}"
    echo "Listen port   : UDP ${listen_port:-Unknown}"
    echo "Primary IPv4  : ${primary_ip:-Could not detect}"

    if [ "$role" = "foreign" ] && [ -n "$primary_ip" ] && [ -n "$listen_port" ]; then
        echo "Endpoint      : ${primary_ip}:${listen_port}"
        echo
        echo "Use the Endpoint above when pairing the Panel / Iran server."
        echo "The Foreign server is the preferred public WireGuard listener."
    elif [ "$role" = "panel" ]; then
        echo
        echo "The Panel / Iran side will initiate WireGuard to the Foreign endpoint."
        echo "Its public IPv4 does not need to be configured as a peer Endpoint."
    fi

    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
        echo
        echo "UFW           : Active"
        echo "Verify UDP ${listen_port:-51820} is allowed on the Foreign listener before testing."
    fi

    echo
    echo "Public keys and Endpoint values are safe to exchange."
    echo "Never share the PrivateKey from $SMITE_PRIVATE_WG_CONFIG."
    smite_private_pause
}

smite_private_peer_key_exists() {
    local key="$1"

    wg show "$SMITE_PRIVATE_INTERFACE" peers 2>/dev/null | grep -Fxq "$key"
}

smite_private_peer_ip_exists() {
    local peer_ip="$1"

    wg show "$SMITE_PRIVATE_INTERFACE" allowed-ips 2>/dev/null \
        | awk -v wanted="$peer_ip/32" '$2 == wanted {found=1} END {exit(found ? 0 : 1)}'
}

smite_private_peer_write_state() {
    local peer_name="$1"
    local peer_key="$2"
    local peer_ip="$3"
    local endpoint="$4"
    local keepalive="$5"
    local safe_name=""
    local peer_file=""

    safe_name="$(printf '%s' "$peer_name" | tr -cs 'A-Za-z0-9._-' '-')"
    safe_name="${safe_name#-}"
    safe_name="${safe_name%-}"
    [ -n "$safe_name" ] || safe_name="peer-${peer_ip//./-}"

    install -d -m 0700 "$SMITE_PRIVATE_PEERS_DIR" || return 1
    peer_file="$SMITE_PRIVATE_PEERS_DIR/${safe_name}.env"

    umask 077
    cat > "$peer_file" <<EOF_PEER
SMITE_PRIVATE_PEER_NAME=$peer_name
SMITE_PRIVATE_PEER_PUBLIC_KEY=$peer_key
SMITE_PRIVATE_PEER_IP=$peer_ip
SMITE_PRIVATE_PEER_ENDPOINT=$endpoint
SMITE_PRIVATE_PEER_KEEPALIVE=$keepalive
SMITE_PRIVATE_PEER_ADDED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF_PEER
    chmod 0600 "$peer_file"
}

smite_private_peer_add() {
    local peer_name="$1"
    local peer_key="$2"
    local peer_ip="$3"
    local endpoint="$4"
    local keepalive="$5"
    local cidr=""
    local local_ip=""
    local temp_config=""
    local allowed_ip="${peer_ip}/32"
    local -a wg_command

    if ! smite_private_peer_ready; then
        return 1
    fi

    cidr="$(smite_private_state_value SMITE_PRIVATE_CIDR)"
    local_ip="$(smite_private_state_value SMITE_PRIVATE_LOCAL_IP)"

    if ! smite_private_peer_validate_public_key "$peer_key"; then
        echo "ERROR: Invalid WireGuard public key."
        return 1
    fi

    if ! smite_private_validate_ipv4 "$peer_ip" || \
       ! smite_private_peer_ipv4_in_cidr "$peer_ip" "$cidr"; then
        echo "ERROR: Peer IP $peer_ip is not a valid address inside $cidr."
        return 1
    fi

    if [ "$peer_ip" = "$local_ip" ]; then
        echo "ERROR: Peer IP cannot be the local Private IP."
        return 1
    fi

    if smite_private_peer_key_exists "$peer_key"; then
        echo "ERROR: This WireGuard public key is already configured as a peer."
        return 1
    fi

    if smite_private_peer_ip_exists "$peer_ip"; then
        echo "ERROR: $allowed_ip is already assigned to another peer."
        return 1
    fi

    if [ -n "$endpoint" ] && [[ "$endpoint" != *:* ]]; then
        echo "ERROR: Invalid peer Endpoint: $endpoint"
        return 1
    fi

    umask 077
    # Keep the temporary basename <=15 chars so wg-quick accepts it as a
    # configuration filename during validation.
    temp_config="$(mktemp "$SMITE_PRIVATE_WG_DIR/sptXXXXXX.conf")" || {
        echo "ERROR: Could not create a temporary WireGuard config."
        return 1
    }

    if ! cp "$SMITE_PRIVATE_WG_CONFIG" "$temp_config"; then
        rm -f "$temp_config"
        echo "ERROR: Could not prepare WireGuard configuration update."
        return 1
    fi

    {
        echo
        echo "[Peer]"
        echo "# U-OPTI peer: $peer_name"
        echo "PublicKey = $peer_key"
        echo "AllowedIPs = $allowed_ip"
        if [ -n "$endpoint" ]; then
            echo "Endpoint = $endpoint"
        fi
        if [ -n "$keepalive" ] && [ "$keepalive" != "0" ]; then
            echo "PersistentKeepalive = $keepalive"
        fi
    } >> "$temp_config"
    chmod 0600 "$temp_config"

    if ! wg-quick strip "$temp_config" >/dev/null 2>&1; then
        rm -f "$temp_config"
        echo "ERROR: Updated WireGuard configuration failed validation."
        return 1
    fi

    wg_command=(wg set "$SMITE_PRIVATE_INTERFACE" peer "$peer_key" allowed-ips "$allowed_ip")
    if [ -n "$endpoint" ]; then
        wg_command+=(endpoint "$endpoint")
    fi
    if [ -n "$keepalive" ] && [ "$keepalive" != "0" ]; then
        wg_command+=(persistent-keepalive "$keepalive")
    fi

    if ! "${wg_command[@]}"; then
        rm -f "$temp_config"
        echo "ERROR: Failed to apply the WireGuard peer at runtime."
        return 1
    fi

    if ! mv "$temp_config" "$SMITE_PRIVATE_WG_CONFIG"; then
        wg set "$SMITE_PRIVATE_INTERFACE" peer "$peer_key" remove >/dev/null 2>&1 || true
        rm -f "$temp_config"
        echo "ERROR: Failed to save the WireGuard peer persistently."
        return 1
    fi
    chmod 0600 "$SMITE_PRIVATE_WG_CONFIG"

    if ! smite_private_peer_write_state "$peer_name" "$peer_key" "$peer_ip" "$endpoint" "$keepalive"; then
        echo "WARNING: Peer is active, but U-OPTI peer metadata could not be saved."
    fi

    return 0
}

smite_private_peer_pair_foreign_with_panel() {
    local role=""
    local panel_ip=""
    local panel_key=""
    local confirm=""

    clear
    echo "======================================"
    echo "   Pair Foreign Node with Panel"
    echo "======================================"
    echo

    if ! smite_private_peer_ready; then
        smite_private_pause
        return
    fi

    role="$(smite_private_state_value SMITE_PRIVATE_ROLE)"
    if [ "$role" != "foreign" ]; then
        echo "ERROR: This action must be run on a Foreign node."
        smite_private_pause
        return
    fi

    panel_ip="$(smite_private_state_value SMITE_PRIVATE_PANEL_IP)"

    echo "This Foreign server will act as the public WireGuard listener."
    echo "The Panel / Iran peer is added without a fixed public Endpoint."
    echo
    echo "Panel Private IP: $panel_ip"
    echo
    read -rp "Panel WireGuard public key: " panel_key

    if ! smite_private_peer_validate_public_key "$panel_key"; then
        echo
        echo "ERROR: Invalid Panel WireGuard public key."
        smite_private_pause
        return
    fi

    echo
    echo "Peer name      : panel-iran"
    echo "Allowed IP     : $panel_ip/32"
    echo "Endpoint       : Dynamic (learned from incoming handshake)"
    echo "Keepalive      : Not required on listener"
    echo
    read -rp "Add this peer? [y/N]: " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *)
            echo "Pairing cancelled."
            smite_private_pause
            return
            ;;
    esac

    echo
    if smite_private_peer_add "panel-iran" "$panel_key" "$panel_ip" "" "0"; then
        echo "Foreign peer configuration saved successfully."
        echo "Now configure the Panel / Iran side with this Foreign server's Endpoint."
    else
        echo "Pairing failed."
    fi

    smite_private_pause
}

smite_private_peer_pair_panel_with_foreign() {
    local role=""
    local cidr=""
    local foreign_ip="$SMITE_PRIVATE_DEFAULT_FOREIGN_IP"
    local foreign_key=""
    local endpoint_ip=""
    local endpoint_port="$SMITE_PRIVATE_DEFAULT_PORT"
    local endpoint=""
    local confirm=""
    local input_foreign_ip=""
    local input_endpoint_port=""

    clear
    echo "======================================"
    echo "   Pair Panel / Iran with Foreign"
    echo "======================================"
    echo

    if ! smite_private_peer_ready; then
        smite_private_pause
        return
    fi

    role="$(smite_private_state_value SMITE_PRIVATE_ROLE)"
    if [ "$role" != "panel" ]; then
        echo "ERROR: This action must be run on the Panel / Iran server."
        smite_private_pause
        return
    fi

    cidr="$(smite_private_state_value SMITE_PRIVATE_CIDR)"

    echo "The Panel / Iran side will initiate WireGuard to the Foreign server."
    echo "Use the Foreign server's Pairing Info for its public key and Endpoint IPv4."
    echo

    read -rp "Foreign WireGuard public key: " foreign_key
    if ! smite_private_peer_validate_public_key "$foreign_key"; then
        echo
        echo "ERROR: Invalid Foreign WireGuard public key."
        smite_private_pause
        return
    fi

    read -rp "Foreign Private IPv4 [$foreign_ip]: " input_foreign_ip
    foreign_ip="${input_foreign_ip:-$foreign_ip}"

    if ! smite_private_validate_ipv4 "$foreign_ip" || \
       ! smite_private_peer_ipv4_in_cidr "$foreign_ip" "$cidr"; then
        echo
        echo "ERROR: Invalid Foreign Private IPv4 for $cidr."
        smite_private_pause
        return
    fi

    read -rp "Foreign public Endpoint IPv4: " endpoint_ip
    if ! smite_private_validate_ipv4 "$endpoint_ip"; then
        echo
        echo "ERROR: Invalid Foreign public Endpoint IPv4."
        smite_private_pause
        return
    fi

    read -rp "Foreign WireGuard UDP port [$endpoint_port]: " input_endpoint_port
    endpoint_port="${input_endpoint_port:-$endpoint_port}"
    if ! [[ "$endpoint_port" =~ ^[0-9]+$ ]] || \
       [ "$endpoint_port" -lt 1 ] || [ "$endpoint_port" -gt 65535 ]; then
        echo
        echo "ERROR: Invalid UDP port."
        smite_private_pause
        return
    fi

    endpoint="${endpoint_ip}:${endpoint_port}"

    echo
    echo "Peer name      : foreign-${foreign_ip}"
    echo "Allowed IP     : ${foreign_ip}/32"
    echo "Endpoint       : $endpoint"
    echo "Keepalive      : 25 seconds"
    echo
    echo "The Foreign host/provider firewall must allow UDP $endpoint_port."
    echo
    read -rp "Add this peer? [y/N]: " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *)
            echo "Pairing cancelled."
            smite_private_pause
            return
            ;;
    esac

    echo
    if smite_private_peer_add "foreign-${foreign_ip}" "$foreign_key" "$foreign_ip" "$endpoint" "25"; then
        echo "Panel peer configuration saved successfully."
        echo "WireGuard should now begin handshake attempts to the Foreign endpoint."
    else
        echo "Pairing failed."
    fi

    smite_private_pause
}

smite_private_peer_show_status() {
    clear
    echo "======================================"
    echo "       WireGuard Peer Status"
    echo "======================================"
    echo

    if ! smite_private_peer_ready; then
        smite_private_pause
        return
    fi

    wg show "$SMITE_PRIVATE_INTERFACE"
    echo
    echo "Expected test topology:"
    echo "  Panel / Iran : $SMITE_PRIVATE_DEFAULT_PANEL_IP"
    echo "  Foreign Node : $SMITE_PRIVATE_DEFAULT_FOREIGN_IP"
    smite_private_pause
}

show_smite_private_peer_menu() {
    while true; do
        clear
        echo "======================================"
        echo "       WireGuard Peer Management"
        echo "======================================"
        echo
        echo "1) Show Pairing Info"
        echo "2) Pair Foreign Node with Panel"
        echo "3) Pair Panel / Iran with Foreign Node"
        echo "4) WireGuard Peer Status"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-4]: " SMITE_PRIVATE_PEER_CHOICE

        case "$SMITE_PRIVATE_PEER_CHOICE" in
            1) smite_private_peer_show_pairing_info ;;
            2) smite_private_peer_pair_foreign_with_panel ;;
            3) smite_private_peer_pair_panel_with_foreign ;;
            4) smite_private_peer_show_status ;;
            0) break ;;
            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}

# Override the stage placeholder from smite-private-network.sh without changing
# its other pending feature messages.
smite_private_foundation_pending() {
    local feature="$1"

    if [ "$feature" = "Peer Management" ]; then
        show_smite_private_peer_menu
        return
    fi

    clear
    echo "======================================"
    echo "      Smite Private Network"
    echo "======================================"
    echo
    echo "$feature is not enabled in this stage yet."
    echo
    echo "No WireGuard peer, Smite setting, or firewall rule is changed."
    smite_private_pause
}
