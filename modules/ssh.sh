#!/bin/bash

# U-OPTI - SSH Management Module
# v0.9.0

SSH_CONFIG="/etc/ssh/sshd_config"
SSH_SERVICE_UNIT="ssh.service"
SSH_SOCKET_UNIT="ssh.socket"

UOPTI_SSH_DIR="/etc/u-opti/ssh"
UOPTI_SSH_PORT_FILE="$UOPTI_SSH_DIR/port"
UOPTI_SSH_BACKUP_DIR="$UOPTI_SSH_DIR/backups"

# U-OPTI managed section inside sshd_config
UOPTI_SSH_MARKER_BEGIN="# BEGIN U-OPTI MANAGED SSH PORT"
UOPTI_SSH_MARKER_END="# END U-OPTI MANAGED SSH PORT"

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

ssh_prepare_runtime_dir() {
    if [ ! -d /run/sshd ]; then
        mkdir -p /run/sshd || return 1
        chmod 0755 /run/sshd || return 1
    fi

    return 0
}

ssh_get_sshd_effective_port() {
    ssh_prepare_runtime_dir || return 1

    sshd -T 2>/dev/null |
        awk '$1 == "port" {print $2; exit}'
}

ssh_get_effective_setting() {
    local SETTING="$1"

    ssh_prepare_runtime_dir || return 1

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

ssh_get_listening_ssh_ports() {
    local CURRENT_PORT="$1"

    if [ -z "$CURRENT_PORT" ]; then
        return 1
    fi

    ss -lntH 2>/dev/null |
        awk -v port="$CURRENT_PORT" '
            $4 ~ ("(^|:)" port "$") {
                print $4
            }
        ' |
        sort -u
}

ssh_get_uopti_marker_state() {
    if [ ! -f "$SSH_CONFIG" ]; then
        echo "missing-config"
        return 0
    fi

    awk -v begin="$UOPTI_SSH_MARKER_BEGIN" -v end="$UOPTI_SSH_MARKER_END" '
        $0 == begin { begins++; if (inside) broken=1; inside=1; next }
        $0 == end { ends++; if (!inside) broken=1; inside=0; next }
        END {
            if (inside) broken=1
            if (begins == 0 && ends == 0) {
                print "none"
            } else if (begins == 1 && ends == 1 && !broken) {
                print "valid"
            } else {
                print "broken"
            }
        }
    ' "$SSH_CONFIG"
}

ssh_has_uopti_marker() {
    [ "$(ssh_get_uopti_marker_state)" = "valid" ]
}

ssh_has_manual_port_directive() {
    awk '
        /^[[:space:]]*#/ {
            next
        }

        /^[[:space:]]*Port[[:space:]]+[0-9]+([[:space:]]|$)/ {
            found=1
        }

        END {
            exit(found ? 0 : 1)
        }
    ' "$SSH_CONFIG"
}

ssh_build_uopti_config() {
    local NEW_PORT="$1"
    local TEMP_CONFIG="$2"
    local MARKER_STATE

    MARKER_STATE=$(ssh_get_uopti_marker_state)

    if [ "$MARKER_STATE" = "broken" ]; then
        echo "Error: U-OPTI managed SSH marker is incomplete or invalid." >&2
        return 1
    fi

    if ! awk \
        -v begin="$UOPTI_SSH_MARKER_BEGIN" \
        -v end="$UOPTI_SSH_MARKER_END" '
            $0 == begin {
                inside=1
                next
            }

            $0 == end {
                inside=0
                next
            }

            !inside {
                print
            }
        ' "$SSH_CONFIG" > "$TEMP_CONFIG"; then

        return 1
    fi

    {
        echo
        echo "$UOPTI_SSH_MARKER_BEGIN"
        echo "Port $NEW_PORT"
        echo "$UOPTI_SSH_MARKER_END"
    } >> "$TEMP_CONFIG"
}

ssh_write_uopti_port() {
    local NEW_PORT="$1"
    local TEMP_CONFIG

    TEMP_CONFIG=$(mktemp) || return 1

    if ! ssh_build_uopti_config "$NEW_PORT" "$TEMP_CONFIG"; then
        rm -f "$TEMP_CONFIG"
        return 1
    fi

    if ! chown --reference="$SSH_CONFIG" "$TEMP_CONFIG"; then
        rm -f "$TEMP_CONFIG"
        return 1
    fi

    if ! chmod --reference="$SSH_CONFIG" "$TEMP_CONFIG"; then
        rm -f "$TEMP_CONFIG"
        return 1
    fi

    if ! mv -f "$TEMP_CONFIG" "$SSH_CONFIG"; then
        rm -f "$TEMP_CONFIG"
        return 1
    fi

    return 0
}

ssh_save_port() {
    local PORT="$1"
    local TEMP_PORT

    mkdir -p "$UOPTI_SSH_DIR" || return 1

    TEMP_PORT=$(mktemp "$UOPTI_SSH_DIR/.port.XXXXXX") || return 1

    printf '%s\n' "$PORT" > "$TEMP_PORT" || {
        rm -f "$TEMP_PORT"
        return 1
    }

    if [ -f "$UOPTI_SSH_PORT_FILE" ]; then
        if ! chown --reference="$UOPTI_SSH_PORT_FILE" "$TEMP_PORT" || \
           ! chmod --reference="$UOPTI_SSH_PORT_FILE" "$TEMP_PORT"; then
            rm -f "$TEMP_PORT"
            return 1
        fi
    fi

    if ! mv -f "$TEMP_PORT" "$UOPTI_SSH_PORT_FILE"; then
        rm -f "$TEMP_PORT"
        return 1
    fi

    return 0
}

ssh_backup_current_state() {
    local TIMESTAMP="$1"
    local BACKUP_DIR="$UOPTI_SSH_BACKUP_DIR/$TIMESTAMP"

    if ! mkdir -p "$BACKUP_DIR"; then
        return 1
    fi

    if [ ! -f "$SSH_CONFIG" ]; then
        rm -rf "$BACKUP_DIR"
        return 1
    fi

    if ! cp -a "$SSH_CONFIG" "$BACKUP_DIR/sshd_config"; then
        rm -rf "$BACKUP_DIR"
        return 1
    fi

    if [ -f "$UOPTI_SSH_PORT_FILE" ]; then
        if ! cp -a "$UOPTI_SSH_PORT_FILE" "$BACKUP_DIR/port"; then
            rm -rf "$BACKUP_DIR"
            return 1
        fi
    fi

    echo "$BACKUP_DIR"
}

ssh_restore_state() {
    local BACKUP_DIR="$1"
    local RESTORE_OK=1

    if [ ! -d "$BACKUP_DIR" ]; then
        echo "Error: Backup directory was not found: $BACKUP_DIR" >&2
        return 1
    fi

    if [ ! -f "$BACKUP_DIR/sshd_config" ]; then
        echo "Error: SSH configuration backup was not found." >&2
        return 1
    fi

    if ! cp -a "$BACKUP_DIR/sshd_config" "$SSH_CONFIG"; then
        RESTORE_OK=0
    fi

    if [ -f "$BACKUP_DIR/port" ]; then
        if ! mkdir -p "$UOPTI_SSH_DIR" || ! cp -a "$BACKUP_DIR/port" "$UOPTI_SSH_PORT_FILE"; then
            RESTORE_OK=0
        fi
    else
        if ! rm -f "$UOPTI_SSH_PORT_FILE"; then
            RESTORE_OK=0
        fi
    fi

    if [ "$RESTORE_OK" -eq 0 ]; then
        echo "Error: Failed to restore SSH state from backup." >&2
        return 1
    fi

    if ! systemctl daemon-reload >/dev/null 2>&1; then
        echo "Error: Failed to reload systemd after SSH restore." >&2
        return 1
    fi

    if ssh_socket_is_active || ssh_socket_is_enabled; then
        if ! systemctl restart "$SSH_SOCKET_UNIT" >/dev/null 2>&1; then
            echo "Error: Failed to restart SSH socket after restore." >&2
            return 1
        fi
    else
        if ! systemctl restart "$SSH_SERVICE_UNIT" >/dev/null 2>&1; then
            echo "Error: Failed to restart SSH service after restore." >&2
            return 1
        fi
    fi

    return 0
}

ssh_validate_configuration() {
    if ! ssh_prepare_runtime_dir; then
        echo
        echo "Error: Failed to prepare SSH runtime directory."
        return 1
    fi

    if ! sshd -t; then
        echo
        echo "Error: SSH configuration test failed."
        return 1
    fi

    return 0
}

ssh_port_is_listening() {
    local PORT="$1"

    if [ -z "$PORT" ]; then
        return 1
    fi

    ss -lntH 2>/dev/null |
        awk -v port="$PORT" '
            $4 ~ ("(^|:)" port "$") {
                found=1
            }

            END {
                exit(found ? 0 : 1)
            }
        '
}

ssh_restart_backend() {
    if ssh_socket_is_active || ssh_socket_is_enabled; then

        if ! systemctl daemon-reload; then
            return 1
        fi

        if ! systemctl restart "$SSH_SOCKET_UNIT"; then
            return 1
        fi

    else

        if ! systemctl restart "$SSH_SERVICE_UNIT"; then
            return 1
        fi

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
    local UOPTI_MODE

    EFFECTIVE_PORT=$(ssh_get_sshd_effective_port)

    if [ -z "$EFFECTIVE_PORT" ]; then
        EFFECTIVE_PORT="unknown"
    fi

    ROOT_LOGIN=$(ssh_get_effective_setting "permitrootlogin")
    PASSWORD_AUTH=$(ssh_get_effective_setting "passwordauthentication")
    PUBKEY_AUTH=$(ssh_get_effective_setting "pubkeyauthentication")

    [ -z "$ROOT_LOGIN" ] && ROOT_LOGIN="unknown"
    [ -z "$PASSWORD_AUTH" ] && PASSWORD_AUTH="unknown"
    [ -z "$PUBKEY_AUTH" ] && PUBKEY_AUTH="unknown"

    SSH_SERVICE=$(systemctl is-active "$SSH_SERVICE_UNIT" 2>/dev/null)
    [ -z "$SSH_SERVICE" ] && SSH_SERVICE="unknown"

    SSH_SOCKET=$(systemctl is-active "$SSH_SOCKET_UNIT" 2>/dev/null)
    [ -z "$SSH_SOCKET" ] && SSH_SOCKET="unknown"

    if ssh_socket_is_active || ssh_socket_is_enabled; then
        SOCKET_MODE="enabled"
    else
        SOCKET_MODE="disabled"
    fi

    if [ "$EFFECTIVE_PORT" != "unknown" ]; then
        LISTENING_PORTS=$(ssh_get_listening_ssh_ports "$EFFECTIVE_PORT")
    fi

    UOPTI_MODE=$(ssh_get_uopti_marker_state)
    case "$UOPTI_MODE" in
        valid)
            UOPTI_MODE="managed"
            ;;
        none)
            UOPTI_MODE="system/default"
            ;;
        broken)
            UOPTI_MODE="BROKEN"
            ;;
    esac

    echo "SSH Configuration"
    echo
    echo "SSH Port                  : $EFFECTIVE_PORT"
    echo "Root Login                : $ROOT_LOGIN"
    echo "Password Authentication   : $PASSWORD_AUTH"
    echo "Public Key Authentication: $PUBKEY_AUTH"
    echo
    echo "Service Status            : $SSH_SERVICE"
    echo "Socket Status             : $SSH_SOCKET"
    echo "Socket Activation         : $SOCKET_MODE"
    echo

    echo "SSH Listening Ports"
    echo "--------------------------------------"

    if [ -n "$LISTENING_PORTS" ]; then
        echo "$LISTENING_PORTS"
    else
        echo "No SSH listener detected."
    fi

    echo
    echo "U-OPTI Port Config         : $UOPTI_MODE"
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

    local MARKER_STATE
    MARKER_STATE=$(ssh_get_uopti_marker_state)

    if [ "$MARKER_STATE" = "broken" ]; then
        echo
        echo "Error: U-OPTI managed SSH marker is incomplete or invalid."
        echo "No changes were made."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ssh_has_manual_port_directive && [ "$MARKER_STATE" != "valid" ]; then
        echo
        echo "Error: A manual SSH Port directive was found in:"
        echo "$SSH_CONFIG"
        echo
        echo "U-OPTI will not overwrite an existing manual Port"
        echo "configuration automatically."
        echo
        echo "Please review the SSH configuration first."
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
    local RESTORE_OK=0

    TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
    BACKUP_DIR=$(ssh_backup_current_state "$TIMESTAMP")

    if [ -z "$BACKUP_DIR" ]; then
        echo "Error: Failed to create a complete SSH backup."
        echo "No changes were made."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Backup created:"
    echo "$BACKUP_DIR"
    echo

    echo "Writing U-OPTI managed SSH port..."

    if ! ssh_write_uopti_port "$NEW_PORT"; then
        echo
        echo "Error: Failed to update sshd_config."
        echo "Restoring previous configuration..."

        if ssh_restore_state "$BACKUP_DIR"; then
            echo "Previous configuration restored."
        else
            echo "WARNING: Automatic restore failed."
        fi

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

        if ssh_restore_state "$BACKUP_DIR"; then
            echo "Previous configuration restored."
        else
            echo "WARNING: Automatic restore failed."
        fi

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

        if ssh_restore_state "$BACKUP_DIR"; then
            echo "Previous configuration restored."
        else
            echo "WARNING: Automatic restore failed."
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    sleep 2

    echo
    echo "Verifying new SSH port..."

    if ssh_port_is_listening "$NEW_PORT"; then

        if ! ssh_save_port "$NEW_PORT"; then
            echo
            echo "Error: SSH changed successfully, but U-OPTI failed to save the new port."
            echo "Restoring previous SSH configuration..."

            if ssh_restore_state "$BACKUP_DIR"; then
                echo "Previous configuration restored."
            else
                echo "WARNING: Automatic restore failed."
            fi

            echo
            read -rp "Press Enter to return..."
            return
        fi

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

    if ssh_restore_state "$BACKUP_DIR"; then
        RESTORE_OK=1
        echo "Previous SSH configuration restored."
    else
        echo "WARNING: Automatic restore failed."
    fi

    echo

    if ssh_port_is_listening "$CURRENT_PORT"; then
        echo "Old SSH port $CURRENT_PORT is still listening."
    else
        echo "WARNING: Old SSH port could not be verified."
    fi

    if [ "$RESTORE_OK" -eq 0 ]; then
        echo "WARNING: SSH state requires manual verification."
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
        echo "3) SSH Access Management"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-3]: " SSH_CHOICE

        case "$SSH_CHOICE" in
            1)
                ssh_show_status
                ;;
            2)
                ssh_change_port
                ;;
            3)
                show_ssh_access_menu
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
