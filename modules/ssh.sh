#!/bin/bash

# U-OPTI - SSH Management Module
# v0.9.0

SSH_CONFIG="/etc/ssh/sshd_config"
SSH_SERVICE_UNIT="ssh.service"
SSH_SOCKET_UNIT="ssh.socket"

UOPTI_SSH_DIR="/etc/u-opti/ssh"
UOPTI_SSH_PORT_FILE="$UOPTI_SSH_DIR/port"
UOPTI_SSH_BACKUP_DIR="$UOPTI_SSH_DIR/backups"

UOPTI_SSH_CONFIG="/etc/ssh/sshd_config.d/99-u-opti-port.conf"

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

    ss -lntH 2>/dev/null |
        awk '{print $4}' |
        grep -Eq "(^|:)${PORT}$"
}

ssh_socket_is_enabled() {
    systemctl is-enabled --quiet "$SSH_SOCKET_UNIT" 2>/dev/null
}

ssh_socket_is_active() {
    systemctl is-active --quiet "$SSH_SOCKET_UNIT" 2>/dev/null
}

ssh_service_is_active() {
    systemctl is-active --quiet "$SSH_SERVICE_UNIT" 2>/dev/null
}

ssh_get_sshd_effective_port() {
    sshd -T 2>/dev/null |
        awk '$1 == "port" {print $2; exit}'
}

ssh_get_effective_setting() {
    local SETTING="$1"

    sshd -T 2>/dev/null |
        awk -v key="$SETTING" '
            $1 == key {
                $1=""
                sub(/^ /, "")
                print
                exit
            }
        '
}

ssh_has_include_directive() {
    grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf[[:space:]]*$' "$SSH_CONFIG"
}

ssh_has_existing_port_directive() {
    grep -Eq '^[[:space:]]*Port[[:space:]]+[0-9]+([[:space:]]|$)' "$SSH_CONFIG"
}

ssh_get_listening_ssh_ports() {
    local CURRENT_PORT="$1"

    ss -lntH 2>/dev/null |
        awk -v port="$CURRENT_PORT" '
            $4 ~ ("(^|:)" port "$") {
                print $4
            }
        ' |
        sort -u
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

    if [ -f "$BACKUP_DIR/port" ]; then
        mkdir -p "$UOPTI_SSH_DIR"
        cp -a "$BACKUP_DIR/port" "$UOPTI_SSH_PORT_FILE"
    else
        rm -f "$UOPTI_SSH_PORT_FILE"
    fi

    systemctl daemon-reload >/dev/null 2>&1 || true

    if ssh_socket_is_active || ssh_socket_is_enabled; then
        systemctl restart "$SSH_SOCKET_UNIT" >/dev/null 2>&1 || true
    else
        systemctl restart "$SSH_SERVICE_UNIT" >/dev/null 2>&1 || true
    fi
}

ssh_add_include_directive() {
    local TEMP_CONFIG

    TEMP_CONFIG=$(mktemp)

    {
        echo "Include /etc/ssh/sshd_config.d/*.conf"
        cat "$SSH_CONFIG"
    } > "$TEMP_CONFIG"

    if ! cp -a "$TEMP_CONFIG" "$SSH_CONFIG"; then
        rm -f "$TEMP_CONFIG"
        return 1
    fi

    rm -f "$TEMP_CONFIG"

    return 0
}

ssh_write_port_config() {
    local NEW_PORT="$1"

    mkdir -p "$(dirname "$UOPTI_SSH_CONFIG")"

    cat > "$UOPTI_SSH_CONFIG" <<EOF
# U-OPTI managed SSH port
# This file is managed by U-OPTI.
Port $NEW_PORT
EOF
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

    ss -lntH 2>/dev/null |
        awk '{print $4}' |
        grep -Eq "(^|:)${PORT}$"
}

ssh_restart_backend() {
    if ssh_socket_is_active || ssh_socket_is_enabled; then
        systemctl daemon-reload || return 1
        systemctl restart "$SSH_SOCKET_UNIT" || return 1
    else
        systemctl restart "$SSH_SERVICE_UNIT" || return 1
    fi

    return 0
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
    local SOCKET_MODE
    local LISTENING_PORTS
    local INCLUDE_STATUS

    EFFECTIVE_PORT=$(ssh_get_sshd_effective_port)
    ROOT_LOGIN=$(ssh_get_effective_setting "permitrootlogin")
    PASSWORD_AUTH=$(ssh_get_effective_setting "passwordauthentication")
    PUBKEY_AUTH=$(ssh_get_effective_setting "pubkeyauthentication")

    SSH_SERVICE=$(systemctl is-active "$SSH_SERVICE_UNIT" 2>/dev/null || echo "unknown")
    SSH_SOCKET=$(systemctl is-active "$SSH_SOCKET_UNIT" 2>/dev/null || echo "inactive")

    if ssh_socket_is_active || ssh_socket_is_enabled; then
        SOCKET_MODE="enabled"
    else
        SOCKET_MODE="disabled"
    fi

    if ssh_has_include_directive; then
        INCLUDE_STATUS="enabled"
    else
        INCLUDE_STATUS="not found"
    fi

    LISTENING_PORTS=$(ssh_get_listening_ssh_ports "$EFFECTIVE_PORT")

    echo "SSH Configuration"
    echo
    echo "SSH Port                  : ${EFFECTIVE_PORT:-unknown}"
    echo "Root Login                : ${ROOT_LOGIN:-unknown}"
    echo "Password Authentication   : ${PASSWORD_AUTH:-unknown}"
    echo "Public Key Authentication: ${PUBKEY_AUTH:-unknown}"
    echo
    echo "Service Status            : ${SSH_SERVICE:-unknown}"
    echo "Socket Status             : ${SSH_SOCKET:-unknown}"
    echo "Socket Activation         : $SOCKET_MODE"
    echo "Config Include            : $INCLUDE_STATUS"
    echo

    echo "SSH Listening Ports"
    echo "--------------------------------------"

    if [ -n "$LISTENING_PORTS" ]; then
        echo "$LISTENING_PORTS"
    else
        echo "No SSH listener detected on port $EFFECTIVE_PORT."
    fi

    echo

    if [ -f "$UOPTI_SSH_CONFIG" ]; then
        echo "U-OPTI Port Config         : managed"
    else
        echo "U-OPTI Port Config         : system/default"
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
    CURRENT_PORT=$(ssh_get_sshd_effective_port)

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

    if ssh_has_existing_port_directive && [ ! -f "$UOPTI_SSH_CONFIG" ]; then
        echo
        echo "Error: An existing SSH Port directive was found in"
        echo "$SSH_CONFIG"
        echo
        echo "U-OPTI will not modify an existing manual SSH Port"
        echo "configuration automatically."
        echo
        echo "Please review the SSH configuration manually first."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Current SSH Port: $CURRENT_PORT"
    echo "New SSH Port    : $NEW_PORT"
    echo

    local TIMESTAMP
    local BACKUP_DIR

    TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
    BACKUP_DIR=$(ssh_backup_current_state "$TIMESTAMP")

    echo "Backup created:"
    echo "$BACKUP_DIR"
    echo

    if ! ssh_has_include_directive; then
        echo "SSH Include directive was not found."
        echo "Adding the standard sshd_config.d Include..."

        if ! ssh_add_include_directive; then
            echo
            echo "Error: Failed to add SSH Include directive."
            echo "Restoring previous configuration..."

            ssh_restore_state "$BACKUP_DIR"

            echo "Previous configuration restored."
            echo
            read -rp "Press Enter to return..."
            return
        fi

        echo "Include directive added."
        echo
    fi

    echo "Writing U-OPTI SSH port configuration..."

    if ! ssh_write_port_config "$NEW_PORT"; then
        echo
        echo "Error: Failed to write U-OPTI SSH configuration."
        echo "Restoring previous configuration..."

        ssh_restore_state "$BACKUP_DIR"

        echo "Previous configuration restored."
        echo
        read -rp "Press Enter to return..."
        return
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
    echo "Restarting SSH..."

    if ! ssh_restart_backend; then
        echo
        echo "Error: SSH restart failed."
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
        echo "Your current SSH session remains open."
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

    if ssh_port_is_listening "$CURRENT_PORT"; then
        echo "Old SSH port $CURRENT_PORT is still listening."
    else
        echo "WARNING: Old SSH port could not be verified."
    fi

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
