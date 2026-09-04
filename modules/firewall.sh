#!/bin/bash

# U-OPTI - Firewall Management Module
# v0.9.0

UOPTI_FIREWALL_DIR="/etc/u-opti/firewall"
UOPTI_FIREWALL_BACKUP_DIR="$UOPTI_FIREWALL_DIR/backups"

FIREWALL_SSH_FALLBACK_PORT="22"
FIREWALL_WEB_PORTS=("80" "443")

firewall_require_root() {
    if [ "$EUID" -ne 0 ]; then
        echo
        echo "Error: This operation requires root privileges."
        return 1
    fi

    return 0
}

firewall_require_ufw() {
    if ! command -v ufw >/dev/null 2>&1; then
        echo
        echo "Error: UFW is not installed."
        echo "Install it with: apt install ufw"
        return 1
    fi

    return 0
}

firewall_prepare_backup_dir() {
    mkdir -p "$UOPTI_FIREWALL_BACKUP_DIR"
}

firewall_get_ssh_port() {
    if command -v sshd >/dev/null 2>&1; then
        if [ ! -d /run/sshd ]; then
            mkdir -p /run/sshd || return 1
            chmod 0755 /run/sshd || return 1
        fi

        local SSH_PORT
        SSH_PORT=$(sshd -T 2>/dev/null | awk '$1 == "port" {print $2; exit}')

        if [[ "$SSH_PORT" =~ ^[0-9]+$ ]] &&
           [ "$SSH_PORT" -ge 1 ] &&
           [ "$SSH_PORT" -le 65535 ]; then
            echo "$SSH_PORT"
            return 0
        fi
    fi

    if ss -lntH 2>/dev/null | awk '{print $4}' | grep -Eq '(^|:)22$'; then
        echo "$FIREWALL_SSH_FALLBACK_PORT"
        return 0
    fi

    return 1
}

firewall_port_is_valid() {
    local PORT="$1"

    if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
        return 1
    fi

    if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
        return 1
    fi

    return 0
}

firewall_port_list_contains() {
    local SEARCH_PORT="$1"
    local PORT

    shift

    for PORT in "$@"; do
        if [ "$PORT" = "$SEARCH_PORT" ]; then
            return 0
        fi
    done

    return 1
}

firewall_collect_extra_ports() {
    local EXTRA_INPUT="$1"
    local PORT
    local UNIQUE_PORTS=()

    read -ra EXTRA_PORTS <<< "$EXTRA_INPUT"

    for PORT in "${EXTRA_PORTS[@]}"; do
        if [ -z "$PORT" ]; then
            continue
        fi

        if ! firewall_port_is_valid "$PORT"; then
            echo "Invalid port: $PORT" >&2
            return 1
        fi

        if ! firewall_port_list_contains "$PORT" "${UNIQUE_PORTS[@]}"; then
            UNIQUE_PORTS+=("$PORT")
        fi
    done

    printf '%s\n' "${UNIQUE_PORTS[@]}"
}

firewall_show_status() {
    clear

    echo "======================================"
    echo "         Firewall Status"
    echo "======================================"
    echo

    if ! firewall_require_ufw; then
        read -rp "Press Enter to return..."
        return
    fi

    local STATUS
    STATUS=$(ufw status | head -n 1)

    echo "Firewall Status : $STATUS"
    echo
    echo "Default Policies"
    echo "--------------------------------------"
    ufw status verbose | grep -E 'Default:' || echo "Unable to determine default policies."
    echo

    echo "SSH Port"
    echo "--------------------------------------"
    local SSH_PORT
    SSH_PORT=$(firewall_get_ssh_port)

    if [ -n "$SSH_PORT" ]; then
        echo "$SSH_PORT"
    else
        echo "Unable to determine SSH port."
    fi

    echo
    echo "Press Enter to return..."
    read -r
}

firewall_show_rules() {
    clear

    echo "======================================"
    echo "          Firewall Rules"
    echo "======================================"
    echo

    if ! firewall_require_ufw; then
        read -rp "Press Enter to return..."
        return
    fi

    ufw status numbered

    echo
    read -rp "Press Enter to return..."
}

firewall_configure() {
    clear

    echo "======================================"
    echo "        Configure Firewall"
    echo "======================================"
    echo

    if ! firewall_require_root || ! firewall_require_ufw; then
        read -rp "Press Enter to return..."
        return
    fi

    local SSH_PORT
    SSH_PORT=$(firewall_get_ssh_port)

    if [ -z "$SSH_PORT" ]; then
        echo "Error: Unable to determine the current SSH port."
        echo "Firewall configuration was cancelled."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "U-OPTI detected SSH port: $SSH_PORT"
    echo
    echo "Required web ports:"
    echo "  HTTP  : 80/tcp"
    echo "  HTTPS : 443/tcp"
    echo

    read -rp "Additional TCP ports (optional, space-separated): " EXTRA_INPUT

    local EXTRA_PORTS
    local EXTRA_OUTPUT

    EXTRA_OUTPUT=$(firewall_collect_extra_ports "$EXTRA_INPUT")
    if [ $? -ne 0 ]; then
        echo
        echo "Firewall configuration was cancelled."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    mapfile -t EXTRA_PORTS <<< "$EXTRA_OUTPUT"

    local PORTS_TO_ALLOW=("$SSH_PORT" "80" "443")
    local PORT

    for PORT in "${EXTRA_PORTS[@]}"; do
        if [ -n "$PORT" ] && ! firewall_port_list_contains "$PORT" "${PORTS_TO_ALLOW[@]}"; then
            PORTS_TO_ALLOW+=("$PORT")
        fi
    done

    echo
    echo "======================================"
    echo "         Firewall Summary"
    echo "======================================"
    echo
    echo "The following TCP ports will be allowed:"
    echo

    for PORT in "${PORTS_TO_ALLOW[@]}"; do
        case "$PORT" in
            "$SSH_PORT")
                echo "  $PORT/tcp  (SSH)"
                ;;
            80)
                echo "  80/tcp     (HTTP)"
                ;;
            443)
                echo "  443/tcp    (HTTPS)"
                ;;
            *)
                echo "  $PORT/tcp"
                ;;
        esac
    done

    echo
    echo "Incoming traffic not explicitly allowed by UFW"
    echo "will be denied after the firewall is enabled."
    echo

    read -rp "Apply these rules and enable UFW? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "Firewall configuration cancelled."
            echo
            read -rp "Press Enter to return..."
            return
            ;;
    esac

    firewall_prepare_backup_dir || {
        echo
        echo "Error: Unable to prepare firewall backup directory."
        echo
        read -rp "Press Enter to return..."
        return
    }

    local TIMESTAMP
    TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
    local BACKUP_DIR="$UOPTI_FIREWALL_BACKUP_DIR/$TIMESTAMP"

    if ! mkdir -p "$BACKUP_DIR"; then
        echo
        echo "Error: Unable to create firewall backup."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    cp -a /etc/ufw "$BACKUP_DIR/ufw" 2>/dev/null || true

    echo
    echo "Applying UFW configuration..."
    echo

    local APPLY_FAILED=false

    if ! ufw default deny incoming; then
        APPLY_FAILED=true
    fi

    if ! ufw default allow outgoing; then
        APPLY_FAILED=true
    fi

    for PORT in "${PORTS_TO_ALLOW[@]}"; do
        if ! ufw allow "$PORT/tcp"; then
            APPLY_FAILED=true
            break
        fi
    done

    if [ "$APPLY_FAILED" = "true" ]; then
        echo
        echo "Failed while applying firewall rules."
        echo "No firewall enable operation was performed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Checking SSH rule before enabling firewall..."

    if ! ufw status | grep -Eq "(^|[[:space:]])${SSH_PORT}/tcp([[:space:]]|$)"; then
        echo
        echo "ERROR: SSH port $SSH_PORT/tcp was not found in UFW rules."
        echo "Firewall will NOT be enabled."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "SSH rule confirmed."

    echo
    echo "Enabling firewall..."

    if ! ufw --force enable; then
        echo
        echo "ERROR: Failed to enable UFW."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "======================================"
    echo "       Firewall Configuration OK"
    echo "======================================"
    echo
    echo "Allowed TCP ports:"
    for PORT in "${PORTS_TO_ALLOW[@]}"; do
        echo "  $PORT/tcp"
    done
    echo
    echo "UFW is now enabled."
    echo
    echo "Backup:"
    echo "$BACKUP_DIR"
    echo

    read -rp "Press Enter to return..."
}

show_firewall_menu() {
    while true; do
        clear

        echo "======================================"
        echo "         Firewall Management"
        echo "======================================"
        echo

        echo "1) Firewall Status"
        echo "2) Configure Firewall"
        echo "3) Show Rules"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-3]: " FIREWALL_CHOICE

        case "$FIREWALL_CHOICE" in
            1)
                firewall_show_status
                ;;
            2)
                firewall_configure
                ;;
            3)
                firewall_show_rules
                ;;
            0)
                return
                ;;
            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}
