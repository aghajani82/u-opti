#!/bin/bash

# U-OPTI - Smite Provider-Independent Private Network
# WireGuard-based host-to-host network used by Smite.
#
# Development/migration default:
#   10.88.10.0/24
# This intentionally stays separate from an existing provider network such as
# 10.77.10.0/24 until the new transport has been fully validated.

SMITE_PRIVATE_STATE_DIR="${SMITE_PRIVATE_STATE_DIR:-/etc/u-opti/smite/private-network}"
SMITE_PRIVATE_STATE_FILE="${SMITE_PRIVATE_STATE_FILE:-$SMITE_PRIVATE_STATE_DIR/state.env}"
SMITE_PRIVATE_PEERS_DIR="${SMITE_PRIVATE_PEERS_DIR:-$SMITE_PRIVATE_STATE_DIR/peers.d}"
SMITE_PRIVATE_INTERFACE="${SMITE_PRIVATE_INTERFACE:-smite-wg0}"
SMITE_PRIVATE_WG_DIR="${SMITE_PRIVATE_WG_DIR:-/etc/wireguard}"
SMITE_PRIVATE_WG_CONFIG="${SMITE_PRIVATE_WG_CONFIG:-$SMITE_PRIVATE_WG_DIR/${SMITE_PRIVATE_INTERFACE}.conf}"
SMITE_PRIVATE_DEFAULT_CIDR="${SMITE_PRIVATE_DEFAULT_CIDR:-10.88.10.0/24}"
SMITE_PRIVATE_DEFAULT_PANEL_IP="${SMITE_PRIVATE_DEFAULT_PANEL_IP:-10.88.10.10}"
SMITE_PRIVATE_DEFAULT_PORT="${SMITE_PRIVATE_DEFAULT_PORT:-51820}"

smite_private_pause() {
    echo
    read -rp "Press Enter to return..."
}

smite_private_state_value() {
    local key="$1"

    [ -f "$SMITE_PRIVATE_STATE_FILE" ] || return 0

    awk -F= -v key="$key" '
        $1 == key {
            print substr($0, index($0, "=") + 1)
            exit
        }
    ' "$SMITE_PRIVATE_STATE_FILE"
}

smite_private_validate_ipv4() {
    local value="$1"

    python3 - "$value" <<'PY' >/dev/null 2>&1
import ipaddress
import sys

try:
    ip = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(1)

raise SystemExit(0 if ip.version == 4 else 1)
PY
}

smite_private_validate_cidr() {
    local value="$1"

    python3 - "$value" <<'PY' >/dev/null 2>&1
import ipaddress
import sys

try:
    network = ipaddress.ip_network(sys.argv[1], strict=False)
except ValueError:
    raise SystemExit(1)

raise SystemExit(0 if network.version == 4 else 1)
PY
}

smite_private_wireguard_installed() {
    command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1
}

smite_private_interface_exists() {
    ip link show dev "$SMITE_PRIVATE_INTERFACE" >/dev/null 2>&1
}

smite_private_interface_up() {
    ip -o link show dev "$SMITE_PRIVATE_INTERFACE" 2>/dev/null \
        | grep -q '<[^>]*UP[^>]*>'
}

smite_private_local_ipv4() {
    ip -4 -o addr show dev "$SMITE_PRIVATE_INTERFACE" 2>/dev/null \
        | awk '{print $4}' \
        | cut -d/ -f1 \
        | head -n1
}

smite_private_public_key() {
    if smite_private_interface_exists && command -v wg >/dev/null 2>&1; then
        wg show "$SMITE_PRIVATE_INTERFACE" public-key 2>/dev/null || true
    fi
}

smite_private_peer_count() {
    if smite_private_interface_exists && command -v wg >/dev/null 2>&1; then
        wg show "$SMITE_PRIVATE_INTERFACE" peers 2>/dev/null \
            | awk 'NF {count++} END {print count+0}'
    else
        printf '0'
    fi
}

smite_private_latest_handshake() {
    local latest="0"

    if smite_private_interface_exists && command -v wg >/dev/null 2>&1; then
        latest="$(wg show "$SMITE_PRIVATE_INTERFACE" latest-handshakes 2>/dev/null \
            | awk '$2 > max {max=$2} END {print max+0}')"
    fi

    printf '%s' "${latest:-0}"
}

smite_private_format_handshake() {
    local epoch="$1"
    local now age

    if ! [[ "$epoch" =~ ^[0-9]+$ ]] || [ "$epoch" -eq 0 ]; then
        printf 'Never'
        return
    fi

    now="$(date +%s)"
    age=$((now - epoch))

    if [ "$age" -lt 0 ]; then
        printf 'Clock mismatch'
    elif [ "$age" -lt 60 ]; then
        printf '%ss ago' "$age"
    elif [ "$age" -lt 3600 ]; then
        printf '%sm ago' "$((age / 60))"
    elif [ "$age" -lt 86400 ]; then
        printf '%sh ago' "$((age / 3600))"
    else
        printf '%sd ago' "$((age / 86400))"
    fi
}

smite_private_ipv4_owner() {
    local ip="$1"

    ip -4 -o addr show 2>/dev/null \
        | awk -v ip="$ip" '
            {
                split($4, address, "/")
                if (address[1] == ip) {
                    print $2
                    exit
                }
            }
        '
}

smite_private_route_for_cidr() {
    local cidr="$1"

    ip -4 route show "$cidr" 2>/dev/null | head -n1
}

smite_private_install_wireguard() {
    if smite_private_wireguard_installed; then
        return 0
    fi

    echo "Installing WireGuard..."
    if ! apt-get update; then
        echo "ERROR: apt update failed."
        return 1
    fi

    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y wireguard; then
        echo "ERROR: WireGuard installation failed."
        return 1
    fi

    if ! smite_private_wireguard_installed; then
        echo "ERROR: WireGuard tools are still unavailable after installation."
        return 1
    fi

    return 0
}

smite_private_write_state() {
    local role="$1"
    local cidr="$2"
    local local_ip="$3"
    local panel_ip="$4"
    local listen_port="$5"
    local public_key="$6"

    install -d -m 0700 "$SMITE_PRIVATE_STATE_DIR" "$SMITE_PRIVATE_PEERS_DIR" || return 1

    umask 077
    cat > "$SMITE_PRIVATE_STATE_FILE" <<EOF_STATE
SMITE_PRIVATE_ROLE=$role
SMITE_PRIVATE_TRANSPORT=wireguard
SMITE_PRIVATE_INTERFACE=$SMITE_PRIVATE_INTERFACE
SMITE_PRIVATE_CIDR=$cidr
SMITE_PRIVATE_LOCAL_IP=$local_ip
SMITE_PRIVATE_PANEL_IP=$panel_ip
SMITE_PRIVATE_LISTEN_PORT=$listen_port
SMITE_PRIVATE_PUBLIC_KEY=$public_key
SMITE_PRIVATE_CREATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF_STATE

    chmod 0600 "$SMITE_PRIVATE_STATE_FILE"
}

smite_private_initialize_panel() {
    local cidr="$SMITE_PRIVATE_DEFAULT_CIDR"
    local panel_ip="$SMITE_PRIVATE_DEFAULT_PANEL_IP"
    local listen_port="$SMITE_PRIVATE_DEFAULT_PORT"
    local prefix=""
    local ip_owner=""
    local route=""
    local private_key=""
    local public_key=""
    local created_config=false
    local enabled_service=false
    local started_interface=false
    local confirm=""

    clear
    echo "======================================"
    echo "   Initialize Smite Panel / Iran"
    echo "======================================"
    echo

    if [ "$EUID" -ne 0 ]; then
        echo "ERROR: Root privileges are required."
        smite_private_pause
        return
    fi

    if ! smite_private_validate_cidr "$cidr" || ! smite_private_validate_ipv4 "$panel_ip"; then
        echo "ERROR: Default Private Network addressing is invalid."
        smite_private_pause
        return
    fi

    if ! [[ "$listen_port" =~ ^[0-9]+$ ]] || \
       [ "$listen_port" -lt 1 ] || [ "$listen_port" -gt 65535 ]; then
        echo "ERROR: Invalid WireGuard listen port: $listen_port"
        smite_private_pause
        return
    fi

    if [ -f "$SMITE_PRIVATE_STATE_FILE" ] || [ -f "$SMITE_PRIVATE_WG_CONFIG" ]; then
        echo "A managed Smite Private Network configuration already exists."
        echo
        echo "State file : $SMITE_PRIVATE_STATE_FILE"
        echo "WG config  : $SMITE_PRIVATE_WG_CONFIG"
        echo
        echo "Nothing was overwritten."
        smite_private_pause
        return
    fi

    if smite_private_interface_exists; then
        echo "ERROR: Interface $SMITE_PRIVATE_INTERFACE already exists."
        echo "Nothing was changed."
        smite_private_pause
        return
    fi

    ip_owner="$(smite_private_ipv4_owner "$panel_ip")"
    if [ -n "$ip_owner" ] && [ "$ip_owner" != "$SMITE_PRIVATE_INTERFACE" ]; then
        echo "ERROR: $panel_ip is already assigned to interface $ip_owner."
        echo "Nothing was changed."
        smite_private_pause
        return
    fi

    route="$(smite_private_route_for_cidr "$cidr")"
    if [ -n "$route" ] && [[ "$route" != *"dev $SMITE_PRIVATE_INTERFACE"* ]]; then
        echo "ERROR: A route already exists for $cidr:"
        echo "$route"
        echo
        echo "Choose a different Private Network range before continuing."
        smite_private_pause
        return
    fi

    prefix="${cidr#*/}"

    echo "This will create an independent WireGuard network on this server."
    echo
    echo "Role          : Panel / Iran"
    echo "Interface     : $SMITE_PRIVATE_INTERFACE"
    echo "Private CIDR  : $cidr"
    echo "Local IP      : $panel_ip/$prefix"
    echo "Listen port   : UDP $listen_port"
    echo
    echo "Important:"
    echo " - Existing Hetzner/private interfaces are NOT changed."
    echo " - Existing Smite configuration is NOT changed."
    echo " - UFW/firewall rules are NOT changed."
    echo " - The WireGuard private key stays only in $SMITE_PRIVATE_WG_CONFIG."
    echo

    read -rp "Initialize this Private Network interface? [y/N]: " confirm
    case "$confirm" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "Initialization cancelled."
            smite_private_pause
            return
            ;;
    esac

    echo
    if ! smite_private_install_wireguard; then
        smite_private_pause
        return
    fi

    if ! install -d -m 0700 "$SMITE_PRIVATE_WG_DIR"; then
        echo "ERROR: Failed to prepare $SMITE_PRIVATE_WG_DIR."
        smite_private_pause
        return
    fi

    umask 077
    private_key="$(wg genkey)" || {
        echo "ERROR: Failed to generate WireGuard private key."
        smite_private_pause
        return
    }

    public_key="$(printf '%s\n' "$private_key" | wg pubkey)" || {
        private_key=""
        echo "ERROR: Failed to derive WireGuard public key."
        smite_private_pause
        return
    }

    if ! cat > "$SMITE_PRIVATE_WG_CONFIG" <<EOF_WG
[Interface]
Address = $panel_ip/$prefix
ListenPort = $listen_port
PrivateKey = $private_key
EOF_WG
    then
        private_key=""
        echo "ERROR: Failed to write WireGuard configuration."
        smite_private_pause
        return
    fi
    private_key=""
    chmod 0600 "$SMITE_PRIVATE_WG_CONFIG"
    created_config=true

    if ! systemctl enable "wg-quick@${SMITE_PRIVATE_INTERFACE}.service" >/dev/null 2>&1; then
        echo "ERROR: Failed to enable WireGuard at boot."
        rm -f "$SMITE_PRIVATE_WG_CONFIG"
        smite_private_pause
        return
    fi
    enabled_service=true

    if ! wg-quick up "$SMITE_PRIVATE_INTERFACE"; then
        echo
        echo "ERROR: Failed to start $SMITE_PRIVATE_INTERFACE."
        systemctl disable "wg-quick@${SMITE_PRIVATE_INTERFACE}.service" >/dev/null 2>&1 || true
        rm -f "$SMITE_PRIVATE_WG_CONFIG"
        smite_private_pause
        return
    fi
    started_interface=true

    if [ "$(smite_private_local_ipv4)" != "$panel_ip" ]; then
        echo "ERROR: Interface started but the expected IP was not assigned."
        wg-quick down "$SMITE_PRIVATE_INTERFACE" >/dev/null 2>&1 || true
        systemctl disable "wg-quick@${SMITE_PRIVATE_INTERFACE}.service" >/dev/null 2>&1 || true
        rm -f "$SMITE_PRIVATE_WG_CONFIG"
        smite_private_pause
        return
    fi

    if ! smite_private_write_state \
        "panel" \
        "$cidr" \
        "$panel_ip" \
        "$panel_ip" \
        "$listen_port" \
        "$public_key"; then
        echo "ERROR: Failed to save U-OPTI Private Network state."
        if [ "$started_interface" = true ]; then
            wg-quick down "$SMITE_PRIVATE_INTERFACE" >/dev/null 2>&1 || true
        fi
        if [ "$enabled_service" = true ]; then
            systemctl disable "wg-quick@${SMITE_PRIVATE_INTERFACE}.service" >/dev/null 2>&1 || true
        fi
        if [ "$created_config" = true ]; then
            rm -f "$SMITE_PRIVATE_WG_CONFIG"
        fi
        smite_private_pause
        return
    fi

    echo
    echo "======================================"
    echo "  Smite Private Network Initialized"
    echo "======================================"
    echo
    echo "Role          : Panel / Iran"
    echo "Interface     : $SMITE_PRIVATE_INTERFACE"
    echo "Private IP    : $panel_ip/$prefix"
    echo "Listen port   : UDP $listen_port"
    echo "Public key    : $public_key"
    echo
    echo "Existing provider network: Unchanged"
    echo "Smite configuration       : Unchanged"
    echo "Firewall                  : Unchanged"
    echo
    echo "The interface has no peer yet, so Handshake will remain Never."
    echo "Next step: initialize the Foreign node and pair the two servers."
    smite_private_pause
}

smite_private_show_status() {
    local managed_role=""
    local managed_local_ip=""
    local managed_panel_ip=""
    local managed_cidr=""
    local managed_port=""
    local runtime_ip=""
    local public_key=""
    local peers="0"
    local handshake="0"

    managed_role="$(smite_private_state_value SMITE_PRIVATE_ROLE)"
    managed_local_ip="$(smite_private_state_value SMITE_PRIVATE_LOCAL_IP)"
    managed_panel_ip="$(smite_private_state_value SMITE_PRIVATE_PANEL_IP)"
    managed_cidr="$(smite_private_state_value SMITE_PRIVATE_CIDR)"
    managed_port="$(smite_private_state_value SMITE_PRIVATE_LISTEN_PORT)"

    runtime_ip="$(smite_private_local_ipv4)"
    public_key="$(smite_private_public_key)"
    peers="$(smite_private_peer_count)"
    handshake="$(smite_private_latest_handshake)"

    clear
    echo "======================================"
    echo "     Smite Private Network Status"
    echo "======================================"
    echo
    echo "Provider      : Independent"
    echo "Transport     : WireGuard"
    echo "Interface     : $SMITE_PRIVATE_INTERFACE"
    echo "Default CIDR  : $SMITE_PRIVATE_DEFAULT_CIDR"
    echo

    if smite_private_wireguard_installed; then
        echo "WireGuard     : Installed"
    else
        echo "WireGuard     : Not installed"
    fi

    if [ -f "$SMITE_PRIVATE_WG_CONFIG" ]; then
        echo "WG config     : Present"
    else
        echo "WG config     : Not configured"
    fi

    if smite_private_interface_exists; then
        if smite_private_interface_up; then
            echo "Interface     : UP"
        else
            echo "Interface     : Present / DOWN"
        fi
    else
        echo "Interface     : Not created"
    fi

    echo "Runtime IPv4  : ${runtime_ip:-Not assigned}"
    echo "Peers         : $peers"
    echo "Handshake     : $(smite_private_format_handshake "$handshake")"

    if [ -n "$public_key" ]; then
        echo "Public key    : $public_key"
    fi

    echo
    if [ -f "$SMITE_PRIVATE_STATE_FILE" ]; then
        echo "Managed state : Present"
        echo "Role          : ${managed_role:-Unknown}"
        echo "Local IP      : ${managed_local_ip:-Not set}"
        echo "Panel IP      : ${managed_panel_ip:-Not set}"
        echo "Network CIDR  : ${managed_cidr:-Not set}"
        echo "Listen port   : ${managed_port:-Not set}"
        echo "State file    : $SMITE_PRIVATE_STATE_FILE"
    else
        echo "Managed state : Not initialized"
    fi

    echo
    echo "Status reporting does not change network configuration."
    smite_private_pause
}

smite_private_foundation_pending() {
    local feature="$1"

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

show_smite_private_network_menu() {
    while true; do
        clear
        echo "======================================"
        echo "      Smite Private Network"
        echo "======================================"
        echo
        echo "1) Private Network Status"
        echo "2) Initialize Panel / Iran"
        echo "3) Initialize Foreign Node"
        echo "4) Peer Management"
        echo "5) Connectivity Test"
        echo "6) Repair / Restart"
        echo "7) Remove Private Network"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-7]: " SMITE_PRIVATE_CHOICE

        case "$SMITE_PRIVATE_CHOICE" in
            1)
                smite_private_show_status
                ;;
            2)
                smite_private_initialize_panel
                ;;
            3)
                smite_private_foundation_pending "Initialize Foreign Node"
                ;;
            4)
                smite_private_foundation_pending "Peer Management"
                ;;
            5)
                smite_private_foundation_pending "Connectivity Test"
                ;;
            6)
                smite_private_foundation_pending "Repair / Restart"
                ;;
            7)
                smite_private_foundation_pending "Remove Private Network"
                ;;
            0)
                break
                ;;
            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}
