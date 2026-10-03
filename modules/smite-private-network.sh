#!/bin/bash

# U-OPTI - Smite Provider-Independent Private Network
# Foundation for a WireGuard-based host-to-host network used by Smite.
#
# This module is intentionally read-only in its first stage: it detects the
# environment, reads managed state, and exposes the Private Network menu.
# WireGuard installation/configuration and peer changes are added in later
# stages so existing Smite deployments are not modified by merely updating
# U-OPTI.

SMITE_PRIVATE_STATE_DIR="${SMITE_PRIVATE_STATE_DIR:-/etc/u-opti/smite/private-network}"
SMITE_PRIVATE_STATE_FILE="${SMITE_PRIVATE_STATE_FILE:-$SMITE_PRIVATE_STATE_DIR/state.env}"
SMITE_PRIVATE_PEERS_DIR="${SMITE_PRIVATE_PEERS_DIR:-$SMITE_PRIVATE_STATE_DIR/peers.d}"
SMITE_PRIVATE_INTERFACE="${SMITE_PRIVATE_INTERFACE:-smite-wg0}"
SMITE_PRIVATE_WG_DIR="${SMITE_PRIVATE_WG_DIR:-/etc/wireguard}"
SMITE_PRIVATE_WG_CONFIG="${SMITE_PRIVATE_WG_CONFIG:-$SMITE_PRIVATE_WG_DIR/${SMITE_PRIVATE_INTERFACE}.conf}"
SMITE_PRIVATE_DEFAULT_CIDR="${SMITE_PRIVATE_DEFAULT_CIDR:-10.77.10.0/24}"
SMITE_PRIVATE_DEFAULT_PANEL_IP="${SMITE_PRIVATE_DEFAULT_PANEL_IP:-10.77.10.10}"
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
    echo "No network changes are made by this status screen."
    smite_private_pause
}

smite_private_foundation_pending() {
    local feature="$1"

    clear
    echo "======================================"
    echo "      Smite Private Network"
    echo "======================================"
    echo
    echo "$feature is not enabled in the foundation stage yet."
    echo
    echo "This first stage only adds safe detection, state layout,"
    echo "status reporting, and menu integration."
    echo "No WireGuard interface or firewall rule is changed."
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
                smite_private_foundation_pending "Initialize Panel / Iran"
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
