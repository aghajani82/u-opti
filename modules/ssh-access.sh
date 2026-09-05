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
    if "$SSHD_PATH" -t >/dev/null 2>&1; then
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








ssh_access_generate_key_pair() {
    clear

    echo "======================================"
    echo "        Generate SSH Key Pair"
    echo "======================================"
    echo

    if ! ssh_access_require_root; then
        read -rp "Press Enter to return..."
        return
    fi

    if ! command -v ssh-keygen >/dev/null 2>&1; then
        echo "Error: ssh-keygen was not found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    local KEY_NAME
    local KEY_DIR
    local KEY_PATH
    local PUBLIC_KEY_PATH
    local PASSPHRASE
    local CONFIRM_PASSPHRASE
    local FINGERPRINT

    KEY_DIR=$(mktemp -d /tmp/u-opti-ssh-key.XXXXXX)

    if [ ! -d "$KEY_DIR" ]; then
        echo "Error: Failed to create temporary key directory."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    chmod 700 "$KEY_DIR"

    echo "Enter a name for the key."
    echo "Example: my-server"
    echo

    while true; do
        read -rp "Key name: " KEY_NAME

        if [ -z "$KEY_NAME" ]; then
            echo
            echo "Error: Key name cannot be empty."
            echo
            continue
        fi

        if [[ ! "$KEY_NAME" =~ ^[a-zA-Z0-9._-]+$ ]]; then
            echo
            echo "Error: Use only letters, numbers, dot, dash or underscore."
            echo
            continue
        fi

        break
    done

    KEY_PATH="$KEY_DIR/$KEY_NAME"
    PUBLIC_KEY_PATH="$KEY_PATH.pub"

    echo
    echo "Choose a passphrase for the private key."
    echo "Leave it empty only if you intentionally want no passphrase."
    echo

    while true; do
        read -rsp "Passphrase: " PASSPHRASE
        echo
        read -rsp "Confirm passphrase: " CONFIRM_PASSPHRASE
        echo

        if [ "$PASSPHRASE" != "$CONFIRM_PASSPHRASE" ]; then
            echo
            echo "Error: Passphrases do not match."
            echo
            continue
        fi

        break
    done

    echo
    echo "Generating Ed25519 SSH key pair..."
    echo

    if ! ssh-keygen \
        -t ed25519 \
        -f "$KEY_PATH" \
        -N "$PASSPHRASE" \
        -C "$KEY_NAME"; then

        echo
        echo "Error: SSH key generation failed."
        rm -rf "$KEY_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    chmod 600 "$KEY_PATH"
    chmod 644 "$PUBLIC_KEY_PATH"

    FINGERPRINT=$(ssh-keygen -lf "$PUBLIC_KEY_PATH" 2>/dev/null || true)

    echo
    echo "======================================"
    echo "      SSH Key Pair Generated"
    echo "======================================"
    echo

    echo "Key Type   : Ed25519"
    echo "Private Key: $KEY_PATH"
    echo "Public Key : $PUBLIC_KEY_PATH"
    echo

    if [ -n "$PASSPHRASE" ]; then
        echo "Passphrase : protected"
    else
        echo "Passphrase : none"
    fi

    echo
    echo "Fingerprint"
    echo "--------------------------------------"
    echo "$FINGERPRINT"

    echo
    echo "Public Key"
    echo "--------------------------------------"
    cat "$PUBLIC_KEY_PATH"

    echo
    echo "Private Key must be copied to your own computer."
    echo "Do NOT add it to GitHub or share it with anyone."
    echo
    echo "Example SCP command from your computer:"
    echo
    echo "scp root@SERVER_IP:$KEY_PATH ~/.ssh/"
    echo

    while true; do
        echo "What would you like to do?"
        echo
        echo "1) Keep temporary key files"
        echo "2) Delete temporary key files"
        echo "0) Return"
        echo

        local ACTION
        read -rp "Please enter your selection [0-2]: " ACTION

        case "$ACTION" in
            1)
                echo
                echo "Temporary key files are still stored here:"
                echo "$KEY_DIR"
                echo
                echo "Delete them after copying the private key."
                read -rp "Press Enter to return..."
                return
                ;;
            2)
                rm -rf "$KEY_DIR"

                if [ ! -e "$KEY_DIR" ]; then
                    echo
                    echo "Temporary key files deleted."
                else
                    echo
                    echo "WARNING: Failed to completely delete temporary key files."
                fi

                echo
                read -rp "Press Enter to return..."
                return
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




ssh_access_backup_authorized_keys() {
    local KEY_FILE="$1"
    local TIMESTAMP
    local BACKUP_DIR

    TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
    BACKUP_DIR="$SSH_AUTHORIZED_KEYS_BACKUP_DIR/$TIMESTAMP"

    mkdir -p "$BACKUP_DIR" || return 1

    if [ -f "$KEY_FILE" ]; then
        cp -a "$KEY_FILE" "$BACKUP_DIR/authorized_keys" || {
            rm -rf "$BACKUP_DIR"
            return 1
        }
    else
        printf '%s\n' "absent" > "$BACKUP_DIR/state" || {
            rm -rf "$BACKUP_DIR"
            return 1
        }
    fi

    echo "$BACKUP_DIR"
}

ssh_access_add_public_key() {
    clear

    echo "======================================"
    echo "            Add Public Key"
    echo "======================================"
    echo

    if ! ssh_access_require_root; then
        read -rp "Press Enter to return..."
        return
    fi

    if ! command -v ssh-keygen >/dev/null 2>&1; then
        echo "Error: ssh-keygen was not found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    local TARGET_USER
    local HOME_DIR
    local AUTHORIZED_KEYS_FILE
    local PUBLIC_KEY
    local TEMP_KEY_FILE
    local BACKUP_DIR
    local SSH_DIR

    TARGET_USER=$(ssh_access_get_target_user)
    HOME_DIR=$(ssh_access_get_user_home "$TARGET_USER")

    if [ -z "$HOME_DIR" ] || [ ! -d "$HOME_DIR" ]; then
        echo "Error: Unable to determine the user's home directory."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    AUTHORIZED_KEYS_FILE="$HOME_DIR/.ssh/authorized_keys"
    SSH_DIR="$HOME_DIR/.ssh"

    echo "Target User: $TARGET_USER"
    echo "Authorized Keys: $AUTHORIZED_KEYS_FILE"
    echo
    echo "Paste the PUBLIC key below."
    echo "Example: ssh-ed25519 AAAA... comment"
    echo

    read -r PUBLIC_KEY

    if [ -z "$PUBLIC_KEY" ]; then
        echo
        echo "Error: Public key cannot be empty."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    TEMP_KEY_FILE=$(mktemp) || {
        echo
        echo "Error: Failed to create temporary file."
        read -rp "Press Enter to return..."
        return
    }

    printf '%s\n' "$PUBLIC_KEY" > "$TEMP_KEY_FILE"
    chmod 600 "$TEMP_KEY_FILE"

    if ! ssh-keygen -lf "$TEMP_KEY_FILE" >/dev/null 2>&1; then
        rm -f "$TEMP_KEY_FILE"
        echo
        echo "Error: Invalid SSH public key."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ -f "$AUTHORIZED_KEYS_FILE" ] &&
       grep -Fqx "$PUBLIC_KEY" "$AUTHORIZED_KEYS_FILE"; then
        rm -f "$TEMP_KEY_FILE"
        echo
        echo "This public key is already installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    BACKUP_DIR=$(ssh_access_backup_authorized_keys "$AUTHORIZED_KEYS_FILE")

    if [ -z "$BACKUP_DIR" ]; then
        rm -f "$TEMP_KEY_FILE"
        echo
        echo "Error: Failed to create SSH key backup."
        echo "No changes were made."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Backup created:"
    echo "$BACKUP_DIR"
    echo

    if [ ! -d "$SSH_DIR" ]; then
        if ! mkdir -p "$SSH_DIR"; then
            rm -f "$TEMP_KEY_FILE"
            echo
            echo "Error: Failed to create SSH directory."
            read -rp "Press Enter to return..."
            return
        fi

        chmod 700 "$SSH_DIR"
        chown "$TARGET_USER:$TARGET_USER" "$SSH_DIR"
    fi

    if [ ! -f "$AUTHORIZED_KEYS_FILE" ]; then
        touch "$AUTHORIZED_KEYS_FILE" || {
            rm -f "$TEMP_KEY_FILE"
            echo
            echo "Error: Failed to create authorized_keys."
            read -rp "Press Enter to return..."
            return
        }

        chmod 600 "$AUTHORIZED_KEYS_FILE"
        chown "$TARGET_USER:$TARGET_USER" "$AUTHORIZED_KEYS_FILE"
    fi

    if ! cat "$TEMP_KEY_FILE" >> "$AUTHORIZED_KEYS_FILE"; then
        rm -f "$TEMP_KEY_FILE"
        echo
        echo "Error: Failed to install public key."
        echo "The previous state is preserved in the backup."
        read -rp "Press Enter to return..."
        return
    fi

    rm -f "$TEMP_KEY_FILE"

    chmod 600 "$AUTHORIZED_KEYS_FILE"
    chown "$TARGET_USER:$TARGET_USER" "$AUTHORIZED_KEYS_FILE"

    echo
    echo "======================================"
    echo "      Public Key Added Successfully"
    echo "======================================"
    echo
    echo "User       : $TARGET_USER"
    echo "Key File   : $AUTHORIZED_KEYS_FILE"
    echo "Backup     : $BACKUP_DIR"
    echo
    echo "The public key is now installed."
    echo
    read -rp "Press Enter to return..."
}




ssh_access_list_public_keys() {
    clear

    echo "======================================"
    echo "            Installed SSH Keys"
    echo "======================================"
    echo

    if ! ssh_access_require_root; then
        read -rp "Press Enter to return..."
        return
    fi

    local TARGET_USER
    local HOME_DIR
    local AUTHORIZED_KEYS_FILE
    local KEY_COUNT=0
    local LINE
    local KEY_TYPE
    local KEY_DATA
    local KEY_COMMENT
    local FINGERPRINT
    local NUMBER=0

    TARGET_USER=$(ssh_access_get_target_user)
    HOME_DIR=$(ssh_access_get_user_home "$TARGET_USER")

    if [ -z "$HOME_DIR" ] || [ ! -d "$HOME_DIR" ]; then
        echo "Error: Unable to determine the user's home directory."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    AUTHORIZED_KEYS_FILE="$HOME_DIR/.ssh/authorized_keys"

    echo "User        : $TARGET_USER"
    echo "Key File    : $AUTHORIZED_KEYS_FILE"
    echo

    if [ ! -f "$AUTHORIZED_KEYS_FILE" ]; then
        echo "No authorized_keys file was found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Installed Public Keys"
    echo "--------------------------------------"

    while IFS= read -r LINE || [ -n "$LINE" ]; do
        [[ "$LINE" =~ ^[[:space:]]*$ ]] && continue
        [[ "$LINE" =~ ^[[:space:]]*# ]] && continue

        KEY_TYPE=$(printf '%s\n' "$LINE" | awk '{print $1}')
        KEY_DATA=$(printf '%s\n' "$LINE" | awk '{print $2}')

        if [ -z "$KEY_TYPE" ] || [ -z "$KEY_DATA" ]; then
            continue
        fi

        if ! printf '%s\n' "$KEY_DATA" | base64 -d >/dev/null 2>&1; then
            continue
        fi

        NUMBER=$((NUMBER + 1))
        KEY_COMMENT=$(printf '%s\n' "$LINE" | cut -d' ' -f3-)

        FINGERPRINT=$(
            printf '%s\n' "$LINE" |
                ssh-keygen -lf - 2>/dev/null ||
                true
        )

        echo
        echo "Key #$NUMBER"
        echo "Type        : $KEY_TYPE"

        if [ -n "$KEY_COMMENT" ] && [ "$KEY_COMMENT" != "$LINE" ]; then
            echo "Comment     : $KEY_COMMENT"
        fi

        if [ -n "$FINGERPRINT" ]; then
            echo "Fingerprint : $FINGERPRINT"
        else
            echo "Fingerprint : unavailable"
        fi

        KEY_COUNT=$NUMBER
    done < "$AUTHORIZED_KEYS_FILE"

    echo
    echo "--------------------------------------"

    if [ "$KEY_COUNT" -eq 0 ]; then
        echo "No valid public keys were detected."
    else
        echo "Total installed keys: $KEY_COUNT"
    fi

    echo
    read -rp "Press Enter to return..."
}






ssh_access_remove_public_key() {
    clear

    echo "======================================"
    echo "            Remove Public Key"
    echo "======================================"
    echo

    if ! ssh_access_require_root; then
        read -rp "Press Enter to return..."
        return
    fi

    local TARGET_USER
    local HOME_DIR
    local AUTHORIZED_KEYS_FILE
    local KEY_NUMBER
    local KEY_INDEX=0
    local SELECTED_LINE
    local LINE
    local KEY_TYPE
    local KEY_DATA
    local TEMP_KEY_FILE
    local FINGERPRINT
    local BACKUP_DIR
    local TEMP_AUTHORIZED_KEYS

    TARGET_USER=$(ssh_access_get_target_user)
    HOME_DIR=$(ssh_access_get_user_home "$TARGET_USER")

    if [ -z "$HOME_DIR" ] || [ ! -d "$HOME_DIR" ]; then
        echo "Error: Unable to determine the user's home directory."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    AUTHORIZED_KEYS_FILE="$HOME_DIR/.ssh/authorized_keys"

    if [ ! -f "$AUTHORIZED_KEYS_FILE" ]; then
        echo "No authorized_keys file was found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "User     : $TARGET_USER"
    echo "Key File : $AUTHORIZED_KEYS_FILE"
    echo
    echo "Installed Public Keys"
    echo "--------------------------------------"

    while IFS= read -r LINE || [ -n "$LINE" ]; do
        [[ "$LINE" =~ ^[[:space:]]*$ ]] && continue
        [[ "$LINE" =~ ^[[:space:]]*# ]] && continue

        KEY_TYPE=""
        KEY_DATA=""

        for TOKEN in $LINE; do
            case "$TOKEN" in
                ssh-rsa|ssh-ed25519|ecdsa-*)
                    KEY_TYPE="$TOKEN"
                    ;;
                sk-ssh-ed25519@openssh.com|sk-ecdsa-*)
                    KEY_TYPE="$TOKEN"
                    ;;
            esac

            if [ -n "$KEY_TYPE" ]; then
                # Next token after key type is the base64 key data.
                KEY_DATA=$(printf '%s\n' "$LINE" | awk -v type="$KEY_TYPE" '
                    {
                        for (i = 1; i < NF; i++) {
                            if ($i == type) {
                                print $(i+1)
                                exit
                            }
                        }
                    }
                ')
                break
            fi
        done

        if [ -z "$KEY_TYPE" ] || [ -z "$KEY_DATA" ]; then
            continue
        fi

        TEMP_KEY_FILE=$(mktemp) || {
            echo "Error: Failed to create temporary file."
            echo
            read -rp "Press Enter to return..."
            return
        }

        printf '%s %s\n' "$KEY_TYPE" "$KEY_DATA" > "$TEMP_KEY_FILE"

        FINGERPRINT=$(ssh-keygen -lf "$TEMP_KEY_FILE" 2>/dev/null || true)
        rm -f "$TEMP_KEY_FILE"

        KEY_INDEX=$((KEY_INDEX + 1))

        echo
        echo "Key #$KEY_INDEX"
        echo "Type        : $KEY_TYPE"
        echo "Fingerprint : ${FINGERPRINT:-unavailable}"
    done < "$AUTHORIZED_KEYS_FILE"

    echo
    echo "--------------------------------------"

    if [ "$KEY_INDEX" -eq 0 ]; then
        echo "No valid public keys were detected."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Enter the number of the key you want to remove."
    echo "Enter 0 to cancel."
    echo

    while true; do
        read -rp "Key number [0-$KEY_INDEX]: " KEY_NUMBER

        if ! [[ "$KEY_NUMBER" =~ ^[0-9]+$ ]] ||
           [ "$KEY_NUMBER" -gt "$KEY_INDEX" ]; then
            echo
            echo "Invalid selection."
            echo
            continue
        fi

        if [ "$KEY_NUMBER" -eq 0 ]; then
            return
        fi

        break
    done

    KEY_INDEX=0

    while IFS= read -r LINE || [ -n "$LINE" ]; do
        [[ "$LINE" =~ ^[[:space:]]*$ ]] && continue
        [[ "$LINE" =~ ^[[:space:]]*# ]] && continue

        KEY_TYPE=""
        KEY_DATA=""

        for TOKEN in $LINE; do
            case "$TOKEN" in
                ssh-rsa|ssh-ed25519|ecdsa-*)
                    KEY_TYPE="$TOKEN"
                    ;;
                sk-ssh-ed25519@openssh.com|sk-ecdsa-*)
                    KEY_TYPE="$TOKEN"
                    ;;
            esac

            if [ -n "$KEY_TYPE" ]; then
                KEY_DATA=$(printf '%s\n' "$LINE" | awk -v type="$KEY_TYPE" '
                    {
                        for (i = 1; i < NF; i++) {
                            if ($i == type) {
                                print $(i+1)
                                exit
                            }
                        }
                    }
                ')
                break
            fi
        done

        if [ -z "$KEY_TYPE" ] || [ -z "$KEY_DATA" ]; then
            continue
        fi

        KEY_INDEX=$((KEY_INDEX + 1))

        if [ "$KEY_INDEX" -eq "$KEY_NUMBER" ]; then
            SELECTED_LINE="$LINE"
            break
        fi
    done < "$AUTHORIZED_KEYS_FILE"

    if [ -z "$SELECTED_LINE" ]; then
        echo
        echo "Error: Selected key could not be found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Selected Key"
    echo "--------------------------------------"
    echo "$SELECTED_LINE"
    echo

    read -rp "Remove this public key? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "Operation cancelled."
            echo
            read -rp "Press Enter to return..."
            return
            ;;
    esac

    BACKUP_DIR=$(ssh_access_backup_authorized_keys "$AUTHORIZED_KEYS_FILE")

    if [ -z "$BACKUP_DIR" ]; then
        echo
        echo "Error: Failed to create SSH key backup."
        echo "No changes were made."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    TEMP_AUTHORIZED_KEYS=$(mktemp) || {
        echo
        echo "Error: Failed to create temporary file."
        echo
        read -rp "Press Enter to return..."
        return
    }

    local REMOVED=0

    while IFS= read -r LINE || [ -n "$LINE" ]; do
        if [ "$REMOVED" -eq 0 ] && [ "$LINE" = "$SELECTED_LINE" ]; then
            REMOVED=1
            continue
        fi

        printf '%s\n' "$LINE" >> "$TEMP_AUTHORIZED_KEYS"
    done < "$AUTHORIZED_KEYS_FILE"

    if [ "$REMOVED" -ne 1 ]; then
        rm -f "$TEMP_AUTHORIZED_KEYS"
        echo
        echo "Error: Selected key could not be removed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! chown --reference="$AUTHORIZED_KEYS_FILE" "$TEMP_AUTHORIZED_KEYS" ||
       ! chmod --reference="$AUTHORIZED_KEYS_FILE" "$TEMP_AUTHORIZED_KEYS"; then
        rm -f "$TEMP_AUTHORIZED_KEYS"
        echo
        echo "Error: Failed to preserve authorized_keys permissions."
        echo "No changes were made."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! mv -f "$TEMP_AUTHORIZED_KEYS" "$AUTHORIZED_KEYS_FILE"; then
        rm -f "$TEMP_AUTHORIZED_KEYS"
        echo
        echo "Error: Failed to update authorized_keys."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "======================================"
    echo "     Public Key Removed Successfully"
    echo "======================================"
    echo
    echo "User   : $TARGET_USER"
    echo "Backup : $BACKUP_DIR"
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
                ssh_access_generate_key_pair
                ;;
            3)
                ssh_access_add_public_key
                ;;
            4)
                ssh_access_list_public_keys
                ;;
            5)
                ssh_access_remove_public_key
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
