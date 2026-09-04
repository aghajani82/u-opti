#!/bin/bash

# U-OPTI - SSH Management Module
# v0.9.0

SSH_CONFIG="/etc/ssh/sshd_config"
SSH_SOCKET_UNIT="ssh.socket"
SSH_SERVICE_UNIT="ssh.service"

UOPTI_SSH_DIR="/etc/u-opti/ssh"
UOPTI_SSH_PORT_FILE="$UOPTI_SSH_DIR/port"
UOPTI_SSH_BACKUP_DIR="$UOPTI_SSH_DIR/backups"

UOPTI_SSH_CONFIG="/etc/ssh/sshd_config.d/99-u-opti-port.conf"
UOPTI_SSH_SOCKET_DIR="/etc/systemd/system/$SSH_SOCKET_UNIT.d"
UOPTI_SSH_SOCKET_OVERRIDE="$UOPTI_SSH_SOCKET_DIR/override.conf"

ssh_require_root() {
    if [ "$EUID" -ne 0 ]; then
        echo
        echo "Error: This operation requires root privileges."
        return 1
    fi

    return 0
}

ssh_port_is_valid() {
    local PORT="$1"

    if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
        return 1
    fi

    if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
        return 1
    fi

    return 0
}

ssh_port_is_in_use() {
    local PORT="$1"

    if ss -lntH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${PORT}$"; then
        return 0
    fi

    return 1
}

ssh_service_is_active() {
    systemctl is-active --quiet "$SSH_SERVICE_UNIT"
}

ssh_socket_is_active() {
    systemctl is-active --quiet "$SSH_SOCKET_UNIT"
}

ssh_get_sshd_effective_port() {
    sshd -T 2>/dev/null | awk '$1 == "port" {print $2; exit}'
}

ssh_get_effective_setting() {
    local SETTING="$1"

    sshd -T 2>/dev/null |
        awk -v key="$SETTING" '$1 == key {
            $1=""
            sub(/^ /, "")
            print
            exit
        }'
}

ssh_get_socket_ports() {
    systemctl show "$SSH_SOCKET_UNIT" --property=Listen --value 2>/dev/null |
        tr ' ' '\n' |
        sed '/^$/d'
}

ssh_get_current_port() {
    local SOCKET_PORTS

    if ssh_socket_is_active; then
        SOCKET_PORTS=$(ssh_get_socket_ports)

        if [ -n "$SOCKET_PORTS" ]; then
            echo "$SOCKET_PORTS" |
                sed -E 's/^\[//; s/\]:[0-9]+$/ /' |
                awk -F: '
                    {
                        port=$NF
                        gsub(/[^0-9]/, "", port)
                        if (port != "") {
                            print port
                        }
                    }
                ' |
                head -n 1

            return
        fi
    fi

    ssh_get_sshd_effective_port
}

ssh_backup_current_state() {
    local TIMESTAMP="$1"
    local BACKUP_DIR="$UOPTI_SSH_BACKUP_DIR/$TIMESTAMP"

    mkdir -p "$BACKUP_DIR"

    if [ -f "$SSH_CONFIG" ]; then
        cp -a "$SSH_CONFIG" "$BACKUP_DIR/sshd_config"
    fi

    if [ -f "$UOPTI_SSH_CONFIG" ]; then
        cp -a "$UOPTI_SSH_CONFIG" "$BACKUP_DIR/99-u-opti-port.conf"
    fi

    if [ -f "$UOPTI_SSH_SOCKET_OVERRIDE" ]; then
        cp -a "$UOPTI_SSH_SOCKET_OVERRIDE" "$BACKUP_DIR/ssh.socket.override.conf"
    fi

    if [ -f "$UOPTI_SSH_PORT_FILE" ]; then
        cp -a "$UOPTI_SSH_PORT_FILE" "$BACKUP_DIR/port"
    fi

    echo "$BACKUP_DIR"
}

ssh_restore_state() {
    local BACKUP_DIR="$1"

    if [ -f "$BACKUP_DIR/sshd_config" ]; then
        cp -a "$BACKUP_DIR/sshd_config" "$SSH_CONFIG"
    fi

    if [ -f "$BACKUP_DIR/99-u-opti-port.conf" ]; then
        mkdir -p "$(dirname "$UOPTI_SSH_CONFIG")"
        cp -a "$BACKUP_DIR/99-u-opti-port.conf" "$UOPTI_SSH_CONFIG"
    else
        rm -f "$UOPTI_SSH_CONFIG"
    fi

    if [ -f "$BACKUP_DIR/ssh.socket.override.conf" ]; then
        mkdir -p "$UOPTI_SSH_SOCKET_DIR"
        cp -a "$BACKUP_DIR/ssh.socket.override.conf" "$UOPTI_SSH_SOCKET_OVERRIDE"
    else
        rm -f "$UOPTI_SSH_SOCKET_OVERRIDE"
        rmdir "$UOPTI_SSH_SOCKET_DIR" 2>/dev/null || true
    fi

    if [ -f "$BACKUP_DIR/port" ]; then
        mkdir -p "$UOPTI_SSH_DIR"
        cp -a "$BACKUP_DIR/port" "$UOPTI_SSH_PORT_FILE"
    else
        rm -f "$UOPTI_SSH_PORT_FILE"
    fi

    systemctl daemon-reload

    if ssh_socket_is_active; then
        systemctl restart "$SSH_SOCKET_UNIT" >/dev/null 2>&1 || true
    else
        systemctl restart "$SSH_SERVICE_UNIT" >/dev/null 2>&1 || true
    fi
}

ssh_write_sshd_config() {
    local NEW_PORT="$1"

    mkdir -p "$(dirname "$UOPTI_SSH_CONFIG")"

    cat > "$UOPTI_SSH_CONFIG" <<EOF
# U-OPTI managed SSH port
# This file is managed by U-OPTI.
Port $NEW_PORT
EOF
}

ssh_write_socket_override() {
    local NEW_PORT="$1"

    mkdir -p "$UOPTI_SSH_SOCKET_DIR"

    cat > "$UOPTI_SSH_SOCKET_OVERRIDE" <<EOF
[Socket]
ListenStream=
ListenStream=0.0.0.0:$NEW_PORT
ListenStream=[::]:$NEW_PORT
EOF
}

ssh_remove_socket_override() {
    rm -f "$UOPTI_SSH_SOCKET_OVERRIDE"
    rmdir "$UOPTI_SSH_SOCKET_DIR" 2>/dev/null || true
}

ssh_validate_configuration() {
    if ! sshd -t; then
        echo
        echo "Error: SSH configuration test failed."
        return 1
    fi

    return 0
}

ssh_port_is_listening() {
    local PORT="$1"

    if ss -lntH 2>/dev/null |
        awk '{print $4}' |
        grep -Eq "(^|:)${PORT}$"; then
        return 0
    fi

    return 1
}

ssh_show_status() {
    clear

    echo "======================================"
    echo "            SSH Status"
    echo "======================================"
    echo

    if ! command -v sshd >/dev/null 2>&1; then
        echo "Error: sshd was not found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    local EFFECTIVE_PORT
    local ROOT_LOGIN
    local PASSWORD_AUTH
    local PUBKEY_AUTH
    local SSH_SERVICE
    local SSH_SOCKET

    EFFECTIVE_PORT=$(ssh_get_current_port)
    ROOT_LOGIN=$(ssh_get_effective_setting "permitrootlogin")
    PASSWORD_AUTH=$(ssh_get_effective_setting "passwordauthentication")
    PUBKEY_AUTH=$(ssh_get_effective_setting "pubkeyauthentication")

    SSH_SERVICE=$(systemctl is-active "$SSH_SERVICE_UNIT" 2>/dev/null || true)
    SSH_SOCKET=$(systemctl is-active "$SSH_SOCKET_UNIT" 2>/dev/null || true)

    echo "SSH Configuration"
    echo
    echo "SSH Port                  : ${EFFECTIVE_PORT:-unknown}"
    echo "Root Login                : ${ROOT_LOGIN:-unknown}"
    echo "Password Authentication   : ${PASSWORD_AUTH:-unknown}"
    echo "Public Key Authentication: ${PUBKEY_AUTH:-unknown}"
    echo
    echo "Service Status            : ${SSH_SERVICE:-unknown}"
    echo "Socket Status             : ${SSH_SOCKET:-unknown}"
    echo

    echo "SSH Listening Ports"
    echo "--------------------------------------"

    if ssh_socket_is_active; then
        ssh_get_socket_ports
    else
        ss -lntH 2>/dev/null |
            awk -v port="$EFFECTIVE_PORT" '
                $4 ~ "(^|:)\"" port "\"$" {
                    print $4
                }
            ' |
            sort -u
    fi

    echo
    read -rp "Press Enter to return..."
}

ssh_change_port() {
    clear

    echo "======================================"
    echo "          Change SSH Port"
    echo "======================================"
    echo

    if ! ssh_require_root; then
        read -rp "Press Enter to return..."
        return
    fi

    if ! command -v sshd >/dev/null 2>&1; then
        echo "Error: sshd was not found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    local CURRENT_PORT
    CURRENT_PORT=$(ssh_get_current_port)

    if [ -z "$CURRENT_PORT" ]; then
        echo "Error: Unable to determine the current SSH port."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Current SSH Port: $CURRENT_PORT"
    echo

    read -rp "Enter new SSH port: " NEW_PORT

    if ! ssh_port_is_valid "$NEW_PORT"; then
        echo
        echo "Error: Invalid port."
        echo "Port must be between 1 and 65535."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ "$NEW_PORT" = "$CURRENT_PORT" ]; then
        echo
        echo "The new port is the same as the current port."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ssh_port_is_in_use "$NEW_PORT"; then
        echo
        echo "Error: Port $NEW_PORT is already in use."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "New SSH Port: $NEW_PORT"
    echo

    local TIMESTAMP
    local BACKUP_DIR

    TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
    BACKUP_DIR=$(ssh_backup_current_state "$TIMESTAMP")

    echo "Backup created:"
    echo "$BACKUP_DIR"
    echo

    echo "Preparing SSH configuration..."

    if ! ssh_write_sshd_config "$NEW_PORT"; then
        echo
        echo "Error: Failed to prepare sshd configuration."
        ssh_restore_state "$BACKUP_DIR"
        read -rp "Press Enter to return..."
        return
    fi

    if ssh_socket_is_active; then
        echo "SSH socket activation detected."
        echo "Preparing ssh.socket configuration..."

        if ! ssh_write_socket_override "$NEW_PORT"; then
            echo
            echo "Error: Failed to prepare ssh.socket configuration."
            ssh_restore_state "$BACKUP_DIR"
            read -rp "Press Enter to return..."
            return
        fi
    fi

    echo
    echo "Testing SSH configuration..."

    if ! ssh_validate_configuration; then
        echo
        echo "SSH configuration is invalid."
        echo "Restoring previous configuration..."
        ssh_restore_state "$BACKUP_DIR"
        echo "Previous configuration restored."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "SSH configuration test passed."

    echo
    echo "Reloading systemd configuration..."

    if ! systemctl daemon-reload; then
        echo
        echo "Error: systemd daemon-reload failed."
        echo "Restoring previous configuration..."
        ssh_restore_state "$BACKUP_DIR"
        echo "Previous configuration restored."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Restarting SSH..."

    local RESTART_OK=true

    if ssh_socket_is_active; then
        if ! systemctl restart "$SSH_SOCKET_UNIT"; then
            RESTART_OK=false
        fi
    else
        if ! systemctl restart "$SSH_SERVICE_UNIT"; then
            RESTART_OK=false
        fi
    fi

    if [ "$RESTART_OK" != "true" ]; then
        echo
        echo "Error: Failed to restart SSH."
        echo "Restoring previous configuration..."
        ssh_restore_state "$BACKUP_DIR"
        echo "Previous configuration restored."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    sleep 2

    echo
    echo "Verifying new SSH port..."

    if ssh_port_is_listening "$NEW_PORT"; then

        mkdir -p "$UOPTI_SSH_DIR"
        echo "$NEW_PORT" > "$UOPTI_SSH_PORT_FILE"

        echo
        echo "======================================"
        echo "      SSH Port Change Successful"
        echo "======================================"
        echo
        echo "Old Port: $CURRENT_PORT"
        echo "New Port: $NEW_PORT"
        echo
        echo "IMPORTANT:"
        echo "Open a NEW SSH connection using port $NEW_PORT"
        echo "before closing your current SSH session."
        echo
        echo "The old SSH session remains open."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "======================================"
    echo "        SSH Port Change Failed"
    echo "======================================"
    echo
    echo "Port $NEW_PORT is not listening."
    echo "Restoring previous configuration..."

    ssh_restore_state "$BACKUP_DIR"

    echo "Previous SSH configuration restored."
    echo
    read -rp "Press Enter to return..."
}

show_ssh_menu() {
    while true; do
        clear

        echo "======================================"
        echo "          SSH Management"
        echo "======================================"
        echo
        echo "1) SSH Status"
        echo "2) Change SSH Port"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-2]: " SSH_CHOICE

        case "$SSH_CHOICE" in

            1)
                ssh_show_status
                ;;

            2)
                ssh_change_port
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
