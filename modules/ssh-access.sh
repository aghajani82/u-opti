#!/bin/bash

# U-OPTI - SSH Access Management Module
# v0.11.0

SSH_ACCESS_DIR="/etc/u-opti/ssh"
SSH_AUTHORIZED_KEYS_BACKUP_DIR="$SSH_ACCESS_DIR/authorized_keys-backups"

ssh_access_require_root() {
    if [ "$EUID" -ne 0 ]; then
        echo
        echo "Error: This operation requires root privileges."
        return 1
    fi

    return 0
}

ssh_access_get_target_user() {
    local TARGET_USER

    TARGET_USER="${SUDO_USER:-$(id -un)}"

    if [ -z "$TARGET_USER" ] || ! id "$TARGET_USER" >/dev/null 2>&1; then
        TARGET_USER="root"
    fi

    printf '%s\n' "$TARGET_USER"
}

ssh_access_get_user_home() {
    local USER_NAME="$1"

    getent passwd "$USER_NAME" 2>/dev/null | cut -d: -f6
}

ssh_access_expand_authorized_keys_path() {
    local USER_NAME="$1"
    local HOME_DIR="$2"
    local PATH_VALUE="$3"

    PATH_VALUE="${PATH_VALUE//%h/$HOME_DIR}"
    PATH_VALUE="${PATH_VALUE//%u/$USER_NAME}"

    case "$PATH_VALUE" in
        /*)
            printf '%s\n' "$PATH_VALUE"
            ;;
        *)
            printf '%s\n' "$HOME_DIR/$PATH_VALUE"
            ;;
    esac
}

ssh_access_count_keys_in_file() {
    local KEY_FILE="$1"

    if [ ! -f "$KEY_FILE" ]; then
        echo 0
        return 0
    fi

    awk '
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*$/ { next }
        {
            for (i = 1; i <= NF; i++) {
                if ($i ~ /^(sk-)?(ssh-ed25519|ssh-rsa|ssh-dss|ecdsa-[^[:space:]]+)@?/ ||
                    $i ~ /^sk-(ssh-ed25519|ecdsa-[^[:space:]]+)@/) {
                    count++
                    break
                }
            }
        }
        END { print count + 0 }
    ' "$KEY_FILE"
}

ssh_access_show_check() {
    clear

    echo "======================================"
    echo "          SSH Access Check"
    echo "======================================"
    echo

    if ! ssh_access_require_root; then
        read -rp "Press Enter to return..."
        return
    fi

    local SSHD_PATH
    local SSH_CONFIG_STATUS
    local EFFECTIVE_PORT
    local PASSWORD_AUTH
    local PUBKEY_AUTH
    local ROOT_LOGIN
    local SERVICE_STATUS
    local SOCKET_STATUS
    local TARGET_USER
    local HOME_DIR
    local AUTHORIZED_KEYS_SETTING
    local KEY_FILES
    local KEY_FILE
    local KEY_COUNT=0
    local KEY_FILE_COUNT=0
    local SSH_SESSION_STATUS

    SSHD_PATH=$(command -v sshd 2>/dev/null || true)

    echo "System"
    echo "--------------------------------------"

    if [ -n "$SSHD_PATH" ]; then
        echo "✓ OpenSSH Server             : installed"
    else
        echo "✗ OpenSSH Server             : not found"
    fi

    if [ -n "$SSHD_PATH" ]; then
        if sshd -t >/dev/null 2>&1; then
            SSH_CONFIG_STATUS="valid"
            echo "✓ SSH Configuration          : valid"
        else
            SSH_CONFIG_STATUS="invalid"
            echo "✗ SSH Configuration          : INVALID"
        fi

        EFFECTIVE_PORT=$(ssh_get_sshd_effective_port 2>/dev/null || true)
        PASSWORD_AUTH=$(ssh_get_effective_setting "passwordauthentication" 2>/dev/null || true)
        PUBKEY_AUTH=$(ssh_get_effective_setting "pubkeyauthentication" 2>/dev/null || true)
        ROOT_LOGIN=$(ssh_get_effective_setting "permitrootlogin" 2>/dev/null || true)
        SERVICE_STATUS=$(systemctl is-active "$SSH_SERVICE_UNIT" 2>/dev/null || true)
        SOCKET_STATUS=$(systemctl is-active "$SSH_SOCKET_UNIT" 2>/dev/null || true)
    else
        SSH_CONFIG_STATUS="unknown"
        EFFECTIVE_PORT="unknown"
        PASSWORD_AUTH="unknown"
        PUBKEY_AUTH="unknown"
        ROOT_LOGIN="unknown"
        SERVICE_STATUS="unknown"
        SOCKET_STATUS="unknown"
    fi

    [ -z "$EFFECTIVE_PORT" ] && EFFECTIVE_PORT="unknown"
    [ -z "$PASSWORD_AUTH" ] && PASSWORD_AUTH="unknown"
    [ -z "$PUBKEY_AUTH" ] && PUBKEY_AUTH="unknown"
    [ -z "$ROOT_LOGIN" ] && ROOT_LOGIN="unknown"
    [ -z "$SERVICE_STATUS" ] && SERVICE_STATUS="inactive/unknown"
    [ -z "$SOCKET_STATUS" ] && SOCKET_STATUS="inactive/unknown"

    echo
    echo "SSH Service"
    echo "--------------------------------------"
    echo "SSH Port                    : $EFFECTIVE_PORT"
    echo "Service                    : $SERVICE_STATUS"
    echo "Socket                     : $SOCKET_STATUS"
    echo "Password Authentication    : $PASSWORD_AUTH"
    echo "Public Key Authentication  : $PUBKEY_AUTH"
    echo "Root Login                 : $ROOT_LOGIN"

    if [ "$EFFECTIVE_PORT" != "unknown" ] && ssh_port_is_listening "$EFFECTIVE_PORT"; then
        echo "✓ SSH Listener              : listening"
    else
        echo "✗ SSH Listener              : not verified"
    fi

    TARGET_USER=$(ssh_access_get_target_user)
    HOME_DIR=$(ssh_access_get_user_home "$TARGET_USER")

    echo
    echo "Current U-OPTI User"
    echo "--------------------------------------"
    echo "User                       : $TARGET_USER"
    echo "Home                       : ${HOME_DIR:-unknown}"

    if [ -n "$SSH_CONNECTION" ]; then
        SSH_SESSION_STATUS="detected"
    else
        SSH_SESSION_STATUS="not detected"
    fi

    echo "SSH Session Environment     : $SSH_SESSION_STATUS"

    echo
    echo "Public Key Access"
    echo "--------------------------------------"

    if [ "$PUBKEY_AUTH" = "yes" ]; then
        echo "✓ Public key authentication is enabled."
    else
        echo "⚠ Public key authentication is not enabled."
    fi

    AUTHORIZED_KEYS_SETTING=$(ssh_get_effective_setting "authorizedkeysfile" 2>/dev/null || true)

    if [ -z "$AUTHORIZED_KEYS_SETTING" ]; then
        AUTHORIZED_KEYS_SETTING="unknown"
    fi

    echo "AuthorizedKeysFile          : $AUTHORIZED_KEYS_SETTING"

    if [ "$AUTHORIZED_KEYS_SETTING" != "unknown" ] &&
       [ -n "$HOME_DIR" ] &&
       [ "$AUTHORIZED_KEYS_SETTING" != "none" ]; then

        for KEY_FILE in $AUTHORIZED_KEYS_SETTING; do
            local EXPANDED_KEY_FILE

            EXPANDED_KEY_FILE=$(
                ssh_access_expand_authorized_keys_path \
                    "$TARGET_USER" \
                    "$HOME_DIR" \
                    "$KEY_FILE"
            )

            KEY_FILES="${KEY_FILES}${EXPANDED_KEY_FILE}"$'\n'
        done

        while IFS= read -r KEY_FILE; do
            [ -z "$KEY_FILE" ] && continue

            KEY_FILE_COUNT=$((KEY_FILE_COUNT + 1))

            local FILE_KEYS
            FILE_KEYS=$(ssh_access_count_keys_in_file "$KEY_FILE")
            KEY_COUNT=$((KEY_COUNT + FILE_KEYS))

            if [ -f "$KEY_FILE" ]; then
                echo "✓ Key file                  : $KEY_FILE"
                echo "  Keys detected             : $FILE_KEYS"
            else
                echo "- Key file                  : $KEY_FILE"
                echo "  Status                    : not present"
            fi
        done <<< "$KEY_FILES"
    else
        echo "⚠ Unable to resolve authorized key files for this user."
    fi

    if [ "$KEY_COUNT" -gt 0 ]; then
        echo "✓ Installed public keys      : $KEY_COUNT"
    else
        echo "⚠ Installed public keys      : none detected"
    fi

    echo
    echo "Access Safety Summary"
    echo "--------------------------------------"

    if [ "$SSH_CONFIG_STATUS" = "valid" ]; then
        echo "✓ SSH configuration is valid"
    else
        echo "✗ SSH configuration requires attention"
    fi

    if [ "$SERVICE_STATUS" = "active" ] ||
       [ "$SOCKET_STATUS" = "active" ]; then
        echo "✓ SSH backend is active"
    else
        echo "⚠ SSH backend is not confirmed active"
    fi

    if [ "$PUBKEY_AUTH" = "yes" ] &&
       [ "$KEY_COUNT" -gt 0 ]; then
        echo "✓ Public key recovery path detected"
    else
        echo "⚠ Public key recovery path is not confirmed"
    fi

    if [ "$SSH_SESSION_STATUS" = "detected" ]; then
        echo "✓ SSH session environment detected"
    else
        echo "- SSH session environment not detected"
    fi

    echo
    echo "No SSH configuration or access settings were changed."
    echo

    read -rp "Press Enter to return..."
}

show_ssh_access_menu() {
    while true; do
        clear

        echo "======================================"
        echo "        SSH Access Management"
        echo "======================================"
        echo
        echo "1) SSH Access Check"
        echo "2) Generate SSH Key Pair"
        echo "3) Add Public Key"
        echo "4) List Public Keys"
        echo "5) Remove Public Key"
        echo "6) Backup & Restore SSH Access"
        echo "7) Change User Password"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-7]: " SSH_ACCESS_CHOICE

        case "$SSH_ACCESS_CHOICE" in
            1)
                ssh_access_show_check
                ;;
            2)
                echo
                echo "SSH Key Generation is not implemented yet."
                read -rp "Press Enter to return..."
                ;;
            3)
                echo
                echo "Add Public Key is not implemented yet."
                read -rp "Press Enter to return..."
                ;;
            4)
                echo
                echo "List Public Keys is not implemented yet."
                read -rp "Press Enter to return..."
                ;;
            5)
                echo
                echo "Remove Public Key is not implemented yet."
                read -rp "Press Enter to return..."
                ;;
            6)
                echo
                echo "Backup & Restore is not implemented yet."
                read -rp "Press Enter to return..."
                ;;
            7)
                echo
                echo "Change User Password is not implemented yet."
                read -rp "Press Enter to return..."
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
