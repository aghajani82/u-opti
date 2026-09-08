#!/bin/bash

# U-OPTI - Firewall Management Module
# v0.12.0

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

firewall_is_active() {
    command -v ufw >/dev/null 2>&1 &&
        [ "$(ufw status 2>/dev/null | head -n 1)" = "Status: active" ]
}

firewall_get_status() {
    if ! command -v ufw >/dev/null 2>&1; then
        echo "not-installed"
        return 0
    fi

    local STATUS
    STATUS=$(ufw status 2>/dev/null | head -n 1)

    if [ "$STATUS" = "Status: active" ]; then
        echo "active"
    elif [ "$STATUS" = "Status: inactive" ]; then
        echo "inactive"
    else
        echo "unknown"
    fi
}

firewall_allow_tcp_port() {
    local PORT="$1"

    if ! firewall_port_is_valid "$PORT"; then
        echo "Error: Invalid TCP port: $PORT" >&2
        return 1
    fi

    if ! command -v ufw >/dev/null 2>&1; then
        echo "Error: UFW is not installed." >&2
        return 1
    fi

    if firewall_rule_exists "$PORT"; then
        return 0
    fi

    ufw allow "$PORT/tcp"
}

firewall_remove_tcp_port() {
    local PORT="$1"

    if ! command -v ufw >/dev/null 2>&1; then
        return 1
    fi

    firewall_rule_exists "$PORT" || return 0
    ufw delete allow "$PORT/tcp"
}

firewall_prepare_backup_dir() {
    mkdir -p "$UOPTI_FIREWALL_BACKUP_DIR"
}

firewall_install_ufw() {
    clear

    echo "======================================"
    echo "       UFW Install / Enable"
    echo "======================================"
    echo

    if ! firewall_require_root; then
        read -rp "Press Enter to return..."
        return
    fi

    if ! command -v apt-get >/dev/null 2>&1; then
        echo "Error: apt-get was not found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if command -v ufw >/dev/null 2>&1; then
        echo "UFW is installed."
    else
        echo "UFW is not installed."
        echo
        read -rp "Install UFW now? [y/N]: " INSTALL_CONFIRM

        case "$INSTALL_CONFIRM" in
            y|Y|yes|YES)
                echo
                echo "Installing UFW..."
                echo

                if ! apt-get update; then
                    echo
                    echo "Error: apt package index update failed."
                    echo
                    read -rp "Press Enter to return..."
                    return
                fi

                if ! apt-get install -y ufw; then
                    echo
                    echo "Error: UFW installation failed."
                    echo
                    read -rp "Press Enter to return..."
                    return
                fi

                echo
                echo "UFW installed successfully."
                ;;
            *)
                echo
                echo "UFW installation cancelled."
                echo
                read -rp "Press Enter to return..."
                return
                ;;
        esac
    fi

    local UFW_STATUS
    local SSH_PORT

    UFW_STATUS=$(ufw status | head -n 1)
    SSH_PORT=$(firewall_get_ssh_port)

    echo
    echo "Current UFW status:"
    echo "$UFW_STATUS"
    echo

    if [[ "$UFW_STATUS" == "Status: active" ]]; then
        echo "UFW is already active."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ -z "$SSH_PORT" ]; then
        echo "Error: Unable to determine the current SSH port."
        echo "UFW will NOT be enabled."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Current SSH port: $SSH_PORT/tcp"
    echo
    echo "Before enabling UFW, U-OPTI will:"
    echo "  - Back up the current UFW configuration"
    echo "  - Set default incoming policy to deny"
    echo "  - Set default outgoing policy to allow"
    echo "  - Ensure the current SSH port is allowed"
    echo "  - Allow HTTP 80/tcp and HTTPS 443/tcp"
    echo
    echo "This is a safety operation to reduce the risk of SSH lockout."
    echo

    read -rp "Enable UFW with these base rules? [y/N]: " ENABLE_CONFIRM

    case "$ENABLE_CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "UFW enable operation cancelled."
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
    local BACKUP_DIR

    TIMESTAMP=$(date '+%Y%m%d-%H%M%S-%N')
    BACKUP_DIR="$UOPTI_FIREWALL_BACKUP_DIR/$TIMESTAMP"

    echo
    echo "Creating firewall backup..."

    if ! firewall_backup_state "$BACKUP_DIR"; then
        echo
        echo "Error: Firewall backup failed."
        echo "UFW will NOT be enabled."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Backup created:"
    echo "$BACKUP_DIR"

    echo
    echo "Preparing safe UFW rules..."

    local APPLY_FAILED=false

    if ! ufw default deny incoming; then
        APPLY_FAILED=true
    fi

    if ! ufw default allow outgoing; then
        APPLY_FAILED=true
    fi

    if [ "$APPLY_FAILED" = "false" ] && ! firewall_rule_exists "$SSH_PORT"; then
        if ! ufw allow "$SSH_PORT/tcp"; then
            APPLY_FAILED=true
        fi
    fi

    if [ "$APPLY_FAILED" = "false" ] && ! firewall_rule_exists "80"; then
        if ! ufw allow "80/tcp"; then
            APPLY_FAILED=true
        fi
    fi

    if [ "$APPLY_FAILED" = "false" ] && ! firewall_rule_exists "443"; then
        if ! ufw allow "443/tcp"; then
            APPLY_FAILED=true
        fi
    fi

    if [ "$APPLY_FAILED" = "true" ]; then
        echo
        echo "Failed while preparing UFW rules."
        echo "Restoring previous firewall configuration..."

        if firewall_restore_state "$BACKUP_DIR"; then
            echo "Previous firewall configuration restored."
        else
            echo "ERROR: Previous firewall configuration could not be fully restored."
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Checking required SSH rule..."

    if ! firewall_rule_exists "$SSH_PORT"; then
        echo
        echo "ERROR: SSH port $SSH_PORT/tcp was not found in UFW rules."
        echo "UFW will NOT be enabled."
        echo "Restoring previous firewall configuration..."

        if firewall_restore_state "$BACKUP_DIR"; then
            echo "Previous firewall configuration restored."
        else
            echo "ERROR: Previous firewall configuration could not be fully restored."
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "SSH rule confirmed."

    echo
    echo "Enabling UFW..."

    if ! ufw --force enable; then
        echo
        echo "ERROR: Failed to enable UFW."
        echo "Restoring previous firewall configuration..."

        if firewall_restore_state "$BACKUP_DIR"; then
            echo "Previous firewall configuration restored."
        else
            echo "ERROR: Previous firewall configuration could not be fully restored."
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    UFW_STATUS=$(ufw status | head -n 1)

    if [[ "$UFW_STATUS" != "Status: active" ]]; then
        echo
        echo "ERROR: UFW did not report an active status after enabling."
        echo "Restoring previous firewall configuration..."

        if firewall_restore_state "$BACKUP_DIR"; then
            echo "Previous firewall configuration restored."
        else
            echo "ERROR: Previous firewall configuration could not be fully restored."
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "======================================"
    echo "          UFW Enabled"
    echo "======================================"
    echo
    echo "Status : active"
    echo "SSH    : $SSH_PORT/tcp"
    echo "HTTP   : 80/tcp"
    echo "HTTPS  : 443/tcp"
    echo
    echo "Backup:"
    echo "$BACKUP_DIR"
    echo

    read -rp "Press Enter to return..."
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

    local STATUS
    STATUS=$(ufw status | head -n 1)

    echo "Firewall Status : $STATUS"
    echo

    echo "Configured TCP Rules"
    echo "--------------------------------------"

    local RULES
    RULES=$(ufw show added 2>/dev/null | sed -n 's/^ufw allow \([0-9][0-9]*\)\/tcp.*$/\1\/tcp/p' | awk '!seen[$0]++')

    if [ -n "$RULES" ]; then
        while IFS= read -r RULE; do
            echo "  $RULE"
        done <<< "$RULES"
    else
        echo "  No TCP allow rules configured."
    fi

    echo

    local SSH_PORT
    SSH_PORT=$(firewall_get_ssh_port)

    echo "SSH Port"
    echo "--------------------------------------"

    if [ -n "$SSH_PORT" ]; then
        echo "  $SSH_PORT/tcp"
    else
        echo "  Unable to determine SSH port."
    fi

    echo

    if [[ "$STATUS" == "Status: active" ]]; then
        echo "Active UFW Rules"
        echo "--------------------------------------"
        ufw status numbered
        echo
    fi

    read -rp "Press Enter to return..."
}

firewall_backup_state() {
    local BACKUP_DIR="$1"

    if ! mkdir -p "$BACKUP_DIR"; then
        return 1
    fi

    if [ ! -d /etc/ufw ]; then
        echo "Error: /etc/ufw was not found." >&2
        return 1
    fi

    if ! cp -a /etc/ufw "$BACKUP_DIR/ufw"; then
        return 1
    fi

    return 0
}

firewall_restore_state() {
    local BACKUP_DIR="$1"

    if [ ! -d "$BACKUP_DIR/ufw" ]; then
        echo "Error: Firewall backup was not found." >&2
        return 1
    fi

    ufw disable >/dev/null 2>&1 || true

    if ! rm -rf /etc/ufw; then
        return 1
    fi

    if ! cp -a "$BACKUP_DIR/ufw" /etc/ufw; then
        return 1
    fi

    ufw reload >/dev/null 2>&1 || true

    return 0
}

firewall_rule_exists() {
    local PORT="$1"

    if ! ufw show added 2>/dev/null | grep -Eq "ufw allow ${PORT}/tcp([[:space:]]|$)"; then
        return 1
    fi

    return 0
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

    read -rp "Additional TCP ports (optional, space-separated; or 0 to go back): " EXTRA_INPUT

    if [ "$EXTRA_INPUT" = "0" ]; then
        return
    fi

    local EXTRA_PORTS
    local EXTRA_OUTPUT

    if ! EXTRA_OUTPUT=$(firewall_collect_extra_ports "$EXTRA_INPUT"); then
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
    TIMESTAMP=$(date '+%Y%m%d-%H%M%S-%N')
    local BACKUP_DIR="$UOPTI_FIREWALL_BACKUP_DIR/$TIMESTAMP"

    echo
    echo "Creating firewall backup..."

    if ! firewall_backup_state "$BACKUP_DIR"; then
        echo
        echo "Error: Firewall backup failed."
        echo "No firewall changes were made."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Backup created:"
    echo "$BACKUP_DIR"

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

    if [ "$APPLY_FAILED" = "false" ]; then
        for PORT in "${PORTS_TO_ALLOW[@]}"; do
            if ! ufw allow "$PORT/tcp"; then
                APPLY_FAILED=true
                break
            fi
        done
    fi

    if [ "$APPLY_FAILED" = "true" ]; then
        echo
        echo "Failed while applying firewall rules."
        echo "Restoring previous firewall configuration..."

        if firewall_restore_state "$BACKUP_DIR"; then
            echo "Previous firewall configuration restored."
        else
            echo "ERROR: Previous firewall configuration could not be fully restored."
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Checking SSH rule before enabling firewall..."

    if ! firewall_rule_exists "$SSH_PORT"; then
        echo
        echo "ERROR: SSH port $SSH_PORT/tcp was not found in UFW rules."
        echo "Firewall will NOT be enabled."
        echo "Restoring previous firewall configuration..."

        if firewall_restore_state "$BACKUP_DIR"; then
            echo "Previous firewall configuration restored."
        else
            echo "ERROR: Previous firewall configuration could not be fully restored."
        fi

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
        echo "Restoring previous firewall configuration..."

        if firewall_restore_state "$BACKUP_DIR"; then
            echo "Previous firewall configuration restored."
        else
            echo "ERROR: Previous firewall configuration could not be fully restored."
        fi

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


firewall_add_ports() {
    clear

    echo "======================================"
    echo "            Add Port"
    echo "======================================"
    echo

    if ! firewall_require_root || ! firewall_require_ufw; then
        read -rp "Press Enter to return..."
        return
    fi

    read -rp "TCP ports (space-separated): " PORT_INPUT

    if [ -z "$PORT_INPUT" ]; then
        echo
        echo "No ports entered."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    local PORT
    local ADD_PORTS=()
    local DUPLICATE_PORTS=()
    local INVALID_FOUND=false

    read -ra INPUT_PORTS <<< "$PORT_INPUT"

    for PORT in "${INPUT_PORTS[@]}"; do
        if ! firewall_port_is_valid "$PORT"; then
            echo "Invalid port: $PORT"
            INVALID_FOUND=true
            continue
        fi

        if firewall_port_list_contains "$PORT" "${ADD_PORTS[@]}"; then
            continue
        fi

        if firewall_rule_exists "$PORT"; then
            DUPLICATE_PORTS+=("$PORT")
            continue
        fi

        ADD_PORTS+=("$PORT")
    done

    if [ "$INVALID_FOUND" = "true" ]; then
        echo
        echo "Invalid port input detected."
        echo "No changes were made."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ "${#ADD_PORTS[@]}" -eq 0 ]; then
        echo
        echo "No new ports to add."
        if [ "${#DUPLICATE_PORTS[@]}" -gt 0 ]; then
            echo
            echo "Already allowed:"
            for PORT in "${DUPLICATE_PORTS[@]}"; do
                echo "  $PORT/tcp"
            done
        fi
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "The following TCP ports will be added:"
    for PORT in "${ADD_PORTS[@]}"; do
        echo "  $PORT/tcp"
    done

    if [ "${#DUPLICATE_PORTS[@]}" -gt 0 ]; then
        echo
        echo "Already allowed (will be skipped):"
        for PORT in "${DUPLICATE_PORTS[@]}"; do
            echo "  $PORT/tcp"
        done
    fi

    echo
    read -rp "Add these ports? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "Add port operation cancelled."
            echo
            read -rp "Press Enter to return..."
            return
            ;;
    esac

    for PORT in "${ADD_PORTS[@]}"; do
        if ! ufw allow "$PORT/tcp"; then
            echo
            echo "Failed to add port $PORT/tcp."
            echo "Stopping further changes."
            echo
            read -rp "Press Enter to return..."
            return
        fi
    done

    echo
    echo "Ports added successfully."
    echo

    for PORT in "${ADD_PORTS[@]}"; do
        echo "  $PORT/tcp"
    done

    echo
    read -rp "Press Enter to return..."
}

firewall_remove_ports() {
    clear

    echo "======================================"
    echo "           Remove Port"
    echo "======================================"
    echo

    if ! firewall_require_root || ! firewall_require_ufw; then
        read -rp "Press Enter to return..."
        return
    fi

    local SSH_PORT
    SSH_PORT=$(firewall_get_ssh_port)

    read -rp "TCP ports to remove (space-separated; or 0 to go back): " PORT_INPUT

    if [ "$PORT_INPUT" = "0" ]; then
        return
    fi

    if [ -z "$PORT_INPUT" ]; then
        echo
        echo "No ports entered."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    local PORT
    local REMOVE_PORTS=()
    local NOT_FOUND_PORTS=()
    local SSH_BLOCKED=()
    local INVALID_FOUND=false

    read -ra INPUT_PORTS <<< "$PORT_INPUT"

    for PORT in "${INPUT_PORTS[@]}"; do
        if ! firewall_port_is_valid "$PORT"; then
            echo "Invalid port: $PORT"
            INVALID_FOUND=true
            continue
        fi

        if firewall_port_list_contains "$PORT" "${REMOVE_PORTS[@]}" ||
           firewall_port_list_contains "$PORT" "${NOT_FOUND_PORTS[@]}" ||
           firewall_port_list_contains "$PORT" "${SSH_BLOCKED[@]}"; then
            continue
        fi

        if [ "$PORT" = "$SSH_PORT" ]; then
            SSH_BLOCKED+=("$PORT")
            continue
        fi

        if firewall_rule_exists "$PORT"; then
            REMOVE_PORTS+=("$PORT")
        else
            NOT_FOUND_PORTS+=("$PORT")
        fi
    done

    if [ "$INVALID_FOUND" = "true" ]; then
        echo
        echo "Invalid port input detected."
        echo "No changes were made."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo

    if [ "${#SSH_BLOCKED[@]}" -gt 0 ]; then
        echo "SSH protection:"
        for PORT in "${SSH_BLOCKED[@]}"; do
            echo "  $PORT/tcp cannot be removed because it is the current SSH port."
        done
        echo
    fi

    if [ "${#NOT_FOUND_PORTS[@]}" -gt 0 ]; then
        echo "Not currently allowed (will be skipped):"
        for PORT in "${NOT_FOUND_PORTS[@]}"; do
            echo "  $PORT/tcp"
        done
        echo
    fi

    if [ "${#REMOVE_PORTS[@]}" -eq 0 ]; then
        echo "No ports can be removed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "The following TCP ports will be removed:"
    for PORT in "${REMOVE_PORTS[@]}"; do
        echo "  $PORT/tcp"
    done

    echo
    read -rp "Remove these ports? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "Remove port operation cancelled."
            echo
            read -rp "Press Enter to return..."
            return
            ;;
    esac

    for PORT in "${REMOVE_PORTS[@]}"; do
        if ! ufw delete allow "$PORT/tcp"; then
            echo
            echo "Failed to remove port $PORT/tcp."
            echo "Stopping further changes."
            echo
            read -rp "Press Enter to return..."
            return
        fi
    done

    echo
    echo "Ports removed successfully."
    echo

    for PORT in "${REMOVE_PORTS[@]}"; do
        echo "  $PORT/tcp"
    done

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

        echo "1) UFW Install / Enable"
        echo "2) Firewall Status"
        echo "3) Configure Firewall"
        echo "4) Show Rules"
        echo "5) Add Port"
        echo "6) Remove Port"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-6]: " FIREWALL_CHOICE

        case "$FIREWALL_CHOICE" in
            1)
                firewall_install_ufw
                ;;
            2)
                firewall_show_status
                ;;
            3)
                firewall_configure
                ;;
            4)
                firewall_show_rules
                ;;
            5)
                firewall_add_ports
                ;;
            6)
                firewall_remove_ports
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
