#!/bin/bash

# U-OPTI - Fail2Ban Management Module
# v0.11.1

FAIL2BAN_DIR="/etc/u-opti/fail2ban"
FAIL2BAN_BACKUP_DIR="$FAIL2BAN_DIR/backups"
FAIL2BAN_MANAGED_JAIL="/etc/fail2ban/jail.d/u-opti-sshd.conf"

FAIL2BAN_DEFAULT_BANTIME="1h"
FAIL2BAN_DEFAULT_FINDTIME="10m"
FAIL2BAN_DEFAULT_MAXRETRY="5"

fail2ban_require_root() {
    [ "$EUID" -eq 0 ]
}

fail2ban_is_installed() {
    command -v fail2ban-client >/dev/null 2>&1
}

fail2ban_prepare_dirs() {
    mkdir -p "$FAIL2BAN_BACKUP_DIR"
}

fail2ban_get_ssh_port() {
    local PORT=""
    if command -v ssh_get_sshd_effective_port >/dev/null 2>&1; then
        PORT="$(ssh_get_sshd_effective_port 2>/dev/null || true)"
    fi
    if [ -z "$PORT" ] && command -v sshd >/dev/null 2>&1; then
        if [ ! -d /run/sshd ]; then
            mkdir -p /run/sshd 2>/dev/null || true
            chmod 0755 /run/sshd 2>/dev/null || true
        fi
        PORT="$(sshd -T 2>/dev/null | awk '$1 == "port" {print $2; exit}')"
    fi
    [ -z "$PORT" ] && PORT="22"
    printf '%s\n' "$PORT"
}

fail2ban_service_unit() {
    if systemctl cat fail2ban.service >/dev/null 2>&1; then
        printf '%s\n' "fail2ban.service"
    elif systemctl cat fail2ban >/dev/null 2>&1; then
        printf '%s\n' "fail2ban"
    else
        printf '%s\n' "fail2ban"
    fi
}

fail2ban_service_active() {
    systemctl is-active --quiet "$(fail2ban_service_unit)"
}

fail2ban_show_status() {
    clear
    echo "======================================"
    echo "           Fail2Ban Status"
    echo "======================================"
    echo

    if ! fail2ban_is_installed; then
        echo "Fail2Ban                  : not installed"
        echo
        echo "Install Fail2Ban first from the Fail2Ban menu."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Fail2Ban                  : installed"
    echo "Version                   : $(fail2ban-client --version 2>/dev/null | head -n 1 || echo unknown)"
    if fail2ban_service_active; then
        echo "Service                   : active"
    else
        echo "Service                   : inactive"
    fi
    echo "SSH Port                  : $(fail2ban_get_ssh_port)"
    if [ -f "$FAIL2BAN_MANAGED_JAIL" ]; then
        echo "U-OPTI SSH Jail           : configured"
    else
        echo "U-OPTI SSH Jail           : not configured"
    fi
    echo
    echo "Jails"
    echo "--------------------------------------"
    fail2ban-client status 2>/dev/null || echo "No active jail information is available."
    echo
    read -rp "Press Enter to return..."
}

fail2ban_install() {
    clear
    echo "======================================"
    echo "    Fail2Ban Install / Enable"
    echo "======================================"
    echo
    if fail2ban_is_installed; then
        echo "Fail2Ban is already installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi
    echo "Fail2Ban will be installed using APT."
    echo
    read -rp "Continue with installation? [y/N]: " CONFIRM
    case "$CONFIRM" in
        y|Y|yes|YES) ;;
        *) echo; echo "Installation cancelled."; sleep 1; return ;;
    esac
    echo
    echo "Updating package lists..."
    if ! apt-get update; then
        echo
        echo "Error: apt-get update failed."
        read -rp "Press Enter to return..."
        return
    fi
    echo
    echo "Installing Fail2Ban..."
    if ! apt-get install -y fail2ban; then
        echo
        echo "Error: Fail2Ban installation failed."
        read -rp "Press Enter to return..."
        return
    fi
    local SERVICE
    SERVICE="$(fail2ban_service_unit)"
    echo
    echo "Enabling Fail2Ban service..."
    systemctl enable "$SERVICE" >/dev/null 2>&1 || true
    if ! systemctl start "$SERVICE"; then
        echo
        echo "Error: Fail2Ban service failed to start."
        echo
        echo "Check with:"
        echo "systemctl status $SERVICE"
        read -rp "Press Enter to return..."
        return
    fi
    echo
    echo "======================================"
    echo "      Fail2Ban Installation Done"
    echo "======================================"
    echo
    echo "Fail2Ban is installed and the service is active."
    echo
    read -rp "Press Enter to return..."
}

fail2ban_backup_managed_jail() {
    local TIMESTAMP="$1"
    local BACKUP_DIR="$FAIL2BAN_BACKUP_DIR/$TIMESTAMP"
    mkdir -p "$BACKUP_DIR" || return 1
    if [ -f "$FAIL2BAN_MANAGED_JAIL" ]; then
        cp -a "$FAIL2BAN_MANAGED_JAIL" "$BACKUP_DIR/u-opti-sshd.conf" || {
            rm -rf "$BACKUP_DIR"
            return 1
        }
    fi
    printf '%s\n' "$BACKUP_DIR"
}

fail2ban_build_ssh_jail() {
    local SSH_PORT="$1"
    local BANTIME="$2"
    local FINDTIME="$3"
    local MAXRETRY="$4"
    local TEMP_CONFIG="$5"
    cat > "$TEMP_CONFIG" <<EOF
# U-OPTI - Fail2Ban SSH Protection
# Managed by U-OPTI
#
# SSH Port: $SSH_PORT

[sshd]
enabled = true
port = $SSH_PORT
filter = sshd
backend = systemd
bantime = $BANTIME
findtime = $FINDTIME
maxretry = $MAXRETRY
EOF
}

fail2ban_validate_time_value() {
    [[ "$1" =~ ^[0-9]+([smhdw]|mo|y)?$ ]]
}

fail2ban_validate_maxretry() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]] && [ "$1" -le 100 ]
}

fail2ban_apply_ssh_protection() {
    local BANTIME="$1"
    local FINDTIME="$2"
    local MAXRETRY="$3"

    if ! fail2ban_is_installed; then
        echo
        echo "Error: Fail2Ban is not installed."
        echo "Install it first."
        return 1
    fi
    if ! fail2ban_validate_time_value "$BANTIME"; then
        echo
        echo "Error: Invalid bantime value."
        echo "Examples: 30m, 1h, 1d"
        return 1
    fi
    if ! fail2ban_validate_time_value "$FINDTIME"; then
        echo
        echo "Error: Invalid findtime value."
        echo "Examples: 5m, 10m, 1h"
        return 1
    fi
    if ! fail2ban_validate_maxretry "$MAXRETRY"; then
        echo
        echo "Error: Invalid maxretry value."
        echo "Allowed range: 1-100."
        return 1
    fi
    mkdir -p /etc/fail2ban/jail.d || return 1
    fail2ban_prepare_dirs || return 1

    local SSH_PORT TIMESTAMP BACKUP_DIR TEMP_CONFIG SERVICE
    SSH_PORT="$(fail2ban_get_ssh_port)"
    TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
    BACKUP_DIR="$(fail2ban_backup_managed_jail "$TIMESTAMP")" || return 1
    TEMP_CONFIG="$(mktemp)" || return 1

    fail2ban_build_ssh_jail "$SSH_PORT" "$BANTIME" "$FINDTIME" "$MAXRETRY" "$TEMP_CONFIG" || {
        rm -f "$TEMP_CONFIG"
        return 1
    }

    if ! cp -f "$TEMP_CONFIG" "$FAIL2BAN_MANAGED_JAIL"; then
        rm -f "$TEMP_CONFIG"
        echo
        echo "Error: Failed to install the SSH jail configuration."
        return 1
    fi
    rm -f "$TEMP_CONFIG"

    if ! fail2ban-client -t >/dev/null 2>&1; then
        echo
        echo "ERROR: New Fail2Ban configuration failed validation."
        echo "Restoring the previous managed configuration..."
        if [ -f "$BACKUP_DIR/u-opti-sshd.conf" ]; then
            cp -f "$BACKUP_DIR/u-opti-sshd.conf" "$FAIL2BAN_MANAGED_JAIL"
        else
            rm -f "$FAIL2BAN_MANAGED_JAIL"
        fi
        systemctl restart "$(fail2ban_service_unit)" >/dev/null 2>&1 || true
        echo "Previous configuration restored."
        return 1
    fi

    SERVICE="$(fail2ban_service_unit)"
    if ! systemctl restart "$SERVICE"; then
        echo
        echo "ERROR: Fail2Ban restart failed."
        echo "Restoring the previous managed configuration..."
        if [ -f "$BACKUP_DIR/u-opti-sshd.conf" ]; then
            cp -f "$BACKUP_DIR/u-opti-sshd.conf" "$FAIL2BAN_MANAGED_JAIL"
        else
            rm -f "$FAIL2BAN_MANAGED_JAIL"
        fi
        systemctl restart "$SERVICE" >/dev/null 2>&1 || true
        echo "Previous configuration restored."
        return 1
    fi

    if ! fail2ban_service_active; then
        echo
        echo "ERROR: Fail2Ban service is not active after restart."
        return 1
    fi

    echo
    echo "======================================"
    echo "       SSH Protection Enabled"
    echo "======================================"
    echo
    echo "SSH Port   : $SSH_PORT"
    echo "Ban Time   : $BANTIME"
    echo "Find Time  : $FINDTIME"
    echo "Max Retry  : $MAXRETRY"
    echo
    echo "Fail2Ban service restarted successfully."
    echo
    echo "Backup:"
    echo "$BACKUP_DIR"
    return 0
}

fail2ban_apply_recommended() {
    clear
    echo "======================================"
    echo "    Recommended SSH Protection"
    echo "======================================"
    echo
    echo "Ban Time   : 1 hour"
    echo "Find Time  : 10 minutes"
    echo "Max Retry  : 5"
    echo
    echo "This protects the SSH service from repeated"
    echo "authentication failures."
    echo
    read -rp "Apply these settings? [y/N]: " CONFIRM
    case "$CONFIRM" in
        y|Y|yes|YES)
            fail2ban_apply_ssh_protection "$FAIL2BAN_DEFAULT_BANTIME" "$FAIL2BAN_DEFAULT_FINDTIME" "$FAIL2BAN_DEFAULT_MAXRETRY"
            ;;
        *) echo; echo "Operation cancelled." ;;
    esac
    echo
    read -rp "Press Enter to return..."
}

fail2ban_custom_ssh_protection() {
    clear
    echo "======================================"
    echo "       Custom SSH Protection"
    echo "======================================"
    echo
    echo "Examples:"
    echo "Ban Time  : 1h"
    echo "Find Time : 10m"
    echo "Max Retry : 5"
    echo
    echo "Use 'back' or '0' at any prompt to return."
    echo

    local BANTIME FINDTIME MAXRETRY

    read -rp "Ban Time  : " BANTIME
    BANTIME="${BANTIME,,}"
    if [ "$BANTIME" = "back" ] || [ "$BANTIME" = "0" ]; then return; fi

    read -rp "Find Time : " FINDTIME
    FINDTIME="${FINDTIME,,}"
    if [ "$FINDTIME" = "back" ] || [ "$FINDTIME" = "0" ]; then return; fi

    read -rp "Max Retry : " MAXRETRY
    MAXRETRY="${MAXRETRY,,}"
    if [ "$MAXRETRY" = "back" ] || [ "$MAXRETRY" = "0" ]; then return; fi

    if ! fail2ban_validate_time_value "$BANTIME"; then
        echo
        echo "Invalid ban time."
        read -rp "Press Enter to return..."
        return
    fi
    if ! fail2ban_validate_time_value "$FINDTIME"; then
        echo
        echo "Invalid find time."
        read -rp "Press Enter to return..."
        return
    fi
    if ! fail2ban_validate_maxretry "$MAXRETRY"; then
        echo
        echo "Invalid max retry value."
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "New values:"
    echo "Ban Time  : $BANTIME"
    echo "Find Time : $FINDTIME"
    echo "Max Retry : $MAXRETRY"
    echo
    read -rp "Apply these settings? [y/N]: " CONFIRM
    case "$CONFIRM" in
        y|Y|yes|YES)
            fail2ban_apply_ssh_protection "$BANTIME" "$FINDTIME" "$MAXRETRY"
            ;;
        *) echo; echo "Operation cancelled." ;;
    esac
    echo
    read -rp "Press Enter to return..."
}

fail2ban_show_jail_status() {
    clear
    echo "======================================"
    echo "          SSH Jail Status"
    echo "======================================"
    echo
    if ! fail2ban_is_installed; then
        echo "Error: Fail2Ban is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi
    if ! fail2ban_service_active; then
        echo "Fail2Ban service is not active."
        echo
        read -rp "Press Enter to return..."
        return
    fi
    echo "Fail2Ban service: active"
    echo "SSH Port        : $(fail2ban_get_ssh_port)"
    echo
    if ! fail2ban-client status sshd; then
        echo
        echo "The U-OPTI SSH jail is not active."
    fi
    echo
    read -rp "Press Enter to return..."
}

fail2ban_unban_ip() {
    clear
    echo "======================================"
    echo "            Unban IP"
    echo "======================================"
    echo
    if ! fail2ban_is_installed; then
        echo "Error: Fail2Ban is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi
    if ! fail2ban_service_active; then
        echo "Fail2Ban service is not active."
        echo
        read -rp "Press Enter to return..."
        return
    fi
    local IP_ADDRESS
    read -rp "IP address to unban (or 0 to go back): " IP_ADDRESS
    if [ "$IP_ADDRESS" = "0" ]; then return; fi
    if [[ ! "$IP_ADDRESS" =~ ^[0-9A-Fa-f:.]+$ ]]; then
        echo
        echo "Invalid IP address."
        read -rp "Press Enter to return..."
        return
    fi
    echo
    if fail2ban-client set sshd unbanip "$IP_ADDRESS"; then
        echo "IP unbanned from the SSH jail."
    else
        echo "Failed to unban IP."
    fi
    echo
    read -rp "Press Enter to return..."
}

fail2ban_disable_ssh_protection() {
    clear
    echo "======================================"
    echo "      Disable SSH Protection"
    echo "======================================"
    echo
    if ! fail2ban_is_installed; then
        echo "Fail2Ban is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi
    if [ ! -f "$FAIL2BAN_MANAGED_JAIL" ]; then
        echo "U-OPTI-managed SSH protection is not configured."
        echo
        read -rp "Press Enter to return..."
        return
    fi
    fail2ban_prepare_dirs || {
        echo
        echo "Error: Failed to prepare backup directory."
        read -rp "Press Enter to return..."
        return
    }
    local TIMESTAMP BACKUP_DIR SERVICE
    TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
    BACKUP_DIR="$(fail2ban_backup_managed_jail "$TIMESTAMP")" || {
        echo
        echo "Error: Failed to create backup."
        read -rp "Press Enter to return..."
        return
    }
    echo "This will disable the U-OPTI-managed SSH jail."
    echo
    read -rp "Continue? [y/N]: " CONFIRM
    case "$CONFIRM" in
        y|Y|yes|YES) ;;
        *) echo; echo "Operation cancelled."; read -rp "Press Enter to return..."; return ;;
    esac
    rm -f "$FAIL2BAN_MANAGED_JAIL"
    SERVICE="$(fail2ban_service_unit)"
    if ! systemctl restart "$SERVICE"; then
        echo
        echo "ERROR: Fail2Ban restart failed."
        echo "Restoring the previous SSH jail configuration..."
        cp -f "$BACKUP_DIR/u-opti-sshd.conf" "$FAIL2BAN_MANAGED_JAIL" >/dev/null 2>&1 || true
        systemctl restart "$SERVICE" >/dev/null 2>&1 || true
        echo "Previous configuration restored."
        read -rp "Press Enter to return..."
        return
    fi
    echo
    echo "U-OPTI-managed SSH protection has been disabled."
    echo
    echo "Backup:"
    echo "$BACKUP_DIR"
    echo
    read -rp "Press Enter to return..."
}

show_fail2ban_menu() {
    while true; do
        clear
        echo "======================================"
        echo "             Fail2Ban"
        echo "======================================"
        echo
        echo "1) Security Status"
        echo "2) Install / Enable"
        echo "3) Apply Recommended SSH Protection"
        echo "4) Custom SSH Protection"
        echo "5) SSH Jail Status"
        echo "6) Unban IP"
        echo "7) Disable SSH Protection"
        echo
        echo "0) Back"
        echo
        local FAIL2BAN_CHOICE
        read -rp "Please enter your selection [0-7]: " FAIL2BAN_CHOICE
        case "$FAIL2BAN_CHOICE" in
            1) fail2ban_show_status ;;
            2) fail2ban_install ;;
            3) fail2ban_apply_recommended ;;
            4) fail2ban_custom_ssh_protection ;;
            5) fail2ban_show_jail_status ;;
            6) fail2ban_unban_ip ;;
            7) fail2ban_disable_ssh_protection ;;
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
