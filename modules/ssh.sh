#!/bin/bash

# U-OPTI - SSH Management Module
# v0.9.0

SSH_CONFIG="/etc/ssh/sshd_config"
SSH_SOCKET_UNIT="ssh.socket"
SSH_SERVICE_UNIT="ssh.service"
UOPTI_SSH_DIR="/etc/u-opti/ssh"
UOPTI_SSH_PORT_FILE="$UOPTI_SSH_DIR/port"
UOPTI_SSH_BACKUP_DIR="$UOPTI_SSH_DIR/backups"

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

    if ss -lntH | awk '{print $4}' | grep -Eq "(^|:)${PORT}$"; then
        return 0
    fi

    return 1
}

ssh_get_effective_port() {
    sshd -T 2>/dev/null | awk '$1 == "port" {print $2; exit}'
}

ssh_get_effective_setting() {
    local SETTING="$1"

    sshd -T 2>/dev/null | awk -v key="$SETTING" '$1 == key {$1=""; sub(/^ /, ""); print; exit}'
}

ssh_socket_is_active() {
    systemctl is-active --quiet "$SSH_SOCKET_UNIT"
}

ssh_service_is_active() {
    systemctl is-active --quiet "$SSH_SERVICE_UNIT"
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

    EFFECTIVE_PORT=$(ssh_get_effective_port)
    ROOT_LOGIN=$(ssh_get_effective_setting "permitrootlogin")
    PASSWORD_AUTH=$(ssh_get_effective_setting "passwordauthentication")
    PUBKEY_AUTH=$(ssh_get_effective_setting "pubkeyauthentication")

    SSH_SERVICE=$(systemctl is-active "$SSH_SERVICE_UNIT" 2>/dev/null || true)
    SSH_SOCKET=$(systemctl is-active "$SSH_SOCKET_UNIT" 2>/dev/null || true)

    echo "Effective SSH Configuration"
    echo
    echo "SSH Port                : ${EFFECTIVE_PORT:-unknown}"
    echo "Root Login              : ${ROOT_LOGIN:-unknown}"
    echo "Password Authentication : ${PASSWORD_AUTH:-unknown}"
    echo "Public Key Authentication: ${PUBKEY_AUTH:-unknown}"
    echo
    echo "Service Status          : ${SSH_SERVICE:-unknown}"
    echo "Socket Status           : ${SSH_SOCKET:-unknown}"
    echo

    echo "Listening SSH Ports"
    echo "--------------------------------------"

    ss -lntH 2>/dev/null | awk '
        $4 ~ /(^|:)22$/ ||
        $4 ~ /(^|:)([0-9]{1,5})$/ {
            if ($4 ~ /:/) {
                print $4
            }
        }
    ' | sort -u

    echo
    read -rp "Press Enter to return..."
}

ssh_backup_current_config() {
    local TIMESTAMP
    TIMESTAMP=$(date '+%Y%m%d-%H%M%S')

    mkdir -p "$UOPTI_SSH_BACKUP_DIR"

    if ! cp -a "$SSH_CONFIG" "$UOPTI_SSH_BACKUP_DIR/sshd_config.$TIMESTAMP"; then
        echo
        echo "Error: Failed to backup $SSH_CONFIG"
        return 1
    fi

    if [ -f "/etc/systemd/system/$SSH_SOCKET_UNIT.d/override.conf" ]; then
        mkdir -p "$UOPTI_SSH_BACKUP_DIR/socket-$TIMESTAMP"

        if ! cp -a \
            "/etc/systemd/system/$SSH_SOCKET_UNIT.d/override.conf" \
            "$UOPTI_SSH_BACKUP_DIR/socket-$TIMESTAMP/override.conf"; then

            echo
            echo "Error: Failed to backup SSH socket override."
            return 1
        fi
    fi

    echo "$TIMESTAMP"
    return 0
}

ssh_remove_uopti_port_config() {
    if [ -f "$UOPTI_SSH_PORT_FILE" ]; then
        rm -f "$UOPTI_SSH_PORT_FILE"
    fi
}

ssh_apply_sshd_port() {
    local NEW_PORT="$1"
    local TEMP_CONFIG

    TEMP_CONFIG=$(mktemp)

    awk '
        BEGIN { in_block=0 }

        /# BEGIN U-OPTI MANAGED SSH PORT/ {
            in_block=1
            next
        }

        /# END U-OPTI MANAGED SSH PORT/ {
            in_block=0
            next
        }

        !in_block {
            print
        }
    ' "$SSH_CONFIG" > "$TEMP_CONFIG"

    cat >> "$TEMP_CONFIG" <<EOF

# BEGIN U-OPTI MANAGED SSH PORT
Port $NEW_PORT
# END U-OPTI MANAGED SSH PORT
EOF

    if ! cat "$TEMP_CONFIG" > "$SSH_CONFIG"; then
        rm -f "$TEMP_CONFIG"
        return 1
    fi

    rm -f "$TEMP_CONFIG"

    echo "$NEW_PORT" > "$UOPTI_SSH_PORT_FILE"

    return 0
}

ssh_apply_socket_port() {
    local NEW_PORT="$1"
    local SOCKET_DROPIN_DIR="/etc/systemd/system/$SSH_SOCKET_UNIT.d"
    local SOCKET_DROPIN_FILE="$SOCKET_DROPIN_DIR/override.conf"

    mkdir -p "$SOCKET_DROPIN_DIR"

    cat > "$SOCKET_DROPIN_FILE" <<EOF
[Socket]
ListenStream=
ListenStream=0.0.0.0:$NEW_PORT
ListenStream=[::]:$NEW_PORT
EOF

    return $?
}

ssh_remove_socket_override() {
    local SOCKET_DROPIN_FILE="/etc/systemd/system/$SSH_SOCKET_UNIT.d/override.conf"

    if [ -f "$SOCKET_DROPIN_FILE" ]; then
        rm -f "$SOCKET_DROPIN_FILE"
    fi

    rmdir /etc/systemd/system/$SSH_SOCKET_UNIT.d 2>/dev/null || true
}

ssh_verify_configuration() {
    if ! sshd -t; then
        echo
        echo "Error: SSH configuration test failed."
        return 1
    fi

    return 0
}

ssh_verify_port_listening() {
    local PORT="$1"

    if ss -lntH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${PORT}$"; then
        return 0
    fi

    return 1
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
    CURRENT_PORT=$(ssh_get_effective_port)

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
        echo "Choose another port."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "New SSH Port: $NEW_PORT"
    echo
    echo "A backup will be created before changing SSH."
    echo

    local BACKUP_TIMESTAMP
    BACKUP_TIMESTAMP=$(ssh_backup_current_config)

    if [ -z "$BACKUP_TIMESTAMP" ]; then
        echo
        echo "SSH port change cancelled."
        read -rp "Press Enter to return..."
        return
    fi

    echo "Backup created: $BACKUP_TIMESTAMP"
    echo

    if ! ssh_apply_sshd_port "$NEW_PORT"; then
        echo
        echo "Error: Failed to update SSH configuration."
        read -rp "Press Enter to return..."
        return
    fi

    if ssh_socket_is_active; then
        echo "SSH socket activation detected."
        echo "Updating ssh.socket configuration..."

        if ! ssh_apply_socket_port "$NEW_PORT"; then
            echo
            echo "Error: Failed to update ssh.socket configuration."
            echo
            read -rp "Press Enter to return..."
            return
        fi
    fi

    echo
    echo "Testing SSH configuration..."

    if ! ssh_verify_configuration; then
        echo
        echo "SSH configuration is invalid."
        echo "The SSH service was not restarted."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "SSH configuration test passed."

    echo
    echo "Reloading systemd configuration..."

    systemctl daemon-reload

    if ssh_socket_is_active; then
        echo
        echo "Restarting SSH socket..."

        if ! systemctl restart "$SSH_SOCKET_UNIT"; then
            echo
            echo "Error: Failed to restart ssh.socket."
            read -rp "Press Enter to return..."
            return
        fi
    else
        echo
        echo "Restarting SSH service..."

        if ! systemctl restart "$SSH_SERVICE_UNIT"; then
            echo
            echo "Error: Failed to restart ssh.service."
            read -rp "Press Enter to return..."
            return
        fi
    fi

    sleep 2

    echo
    echo "Verifying new SSH port..."

    if ssh_verify_port_listening "$NEW_PORT"; then
        echo
        echo "======================================"
        echo "      SSH Port Change Successful"
        echo "======================================"
        echo
        echo "Old Port: $CURRENT_PORT"
        echo "New Port: $NEW_PORT"
        echo
        echo "Important:"
        echo "Open a NEW SSH connection using port $NEW_PORT"
        echo "before closing your current SSH session."
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
    echo
    echo "Your current SSH session was not intentionally closed."
    echo "The configuration backup is available under:"
    echo "$UOPTI_SSH_BACKUP_DIR"
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
