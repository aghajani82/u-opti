#!/bin/bash

# U-OPTI - SSH Access Management Module
# v0.12.0

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
    local KBD_INTERACTIVE_AUTH
    local AUTHORIZED_KEYS_SETTING
    local SERVICE_STATUS
    local SOCKET_STATUS
    local TARGET_USER
    local HOME_DIR
    local KEY_FILES
    local KEY_FILE
    local KEY_COUNT=0
    local SSH_SESSION_STATUS
    local SSH_HOST

    SSHD_PATH="$(command -v sshd 2>/dev/null || true)"
    SSH_HOST="localhost"

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

        EFFECTIVE_PORT="$(ssh_get_sshd_effective_port 2>/dev/null || true)"

        PASSWORD_AUTH="$(
            "$SSHD_PATH" -T \
                -C "user=root,host=$SSH_HOST,addr=127.0.0.1" 2>/dev/null |
                awk '$1 == "passwordauthentication" {print $2; exit}'
        )"

        PUBKEY_AUTH="$(
            "$SSHD_PATH" -T \
                -C "user=root,host=$SSH_HOST,addr=127.0.0.1" 2>/dev/null |
                awk '$1 == "pubkeyauthentication" {print $2; exit}'
        )"

        ROOT_LOGIN="$(
            "$SSHD_PATH" -T \
                -C "user=root,host=$SSH_HOST,addr=127.0.0.1" 2>/dev/null |
                awk '$1 == "permitrootlogin" {print $2; exit}'
        )"

        KBD_INTERACTIVE_AUTH="$(
            "$SSHD_PATH" -T \
                -C "user=root,host=$SSH_HOST,addr=127.0.0.1" 2>/dev/null |
                awk '$1 == "kbdinteractiveauthentication" {print $2; exit}'
        )"

        SERVICE_STATUS="$(systemctl is-active "$SSH_SERVICE_UNIT" 2>/dev/null || true)"
        SOCKET_STATUS="$(systemctl is-active "$SSH_SOCKET_UNIT" 2>/dev/null || true)"
    else
        SSH_CONFIG_STATUS="unknown"
        EFFECTIVE_PORT="unknown"
        PASSWORD_AUTH="unknown"
        PUBKEY_AUTH="unknown"
        ROOT_LOGIN="unknown"
        KBD_INTERACTIVE_AUTH="unknown"
        SERVICE_STATUS="unknown"
        SOCKET_STATUS="unknown"
    fi

    [ -z "$EFFECTIVE_PORT" ] && EFFECTIVE_PORT="unknown"
    [ -z "$PASSWORD_AUTH" ] && PASSWORD_AUTH="unknown"
    [ -z "$PUBKEY_AUTH" ] && PUBKEY_AUTH="unknown"
    [ -z "$ROOT_LOGIN" ] && ROOT_LOGIN="unknown"
    [ -z "$KBD_INTERACTIVE_AUTH" ] && KBD_INTERACTIVE_AUTH="unknown"
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
    echo "Keyboard-Interactive       : $KBD_INTERACTIVE_AUTH"
    echo "Root Login                 : $ROOT_LOGIN"

    if [ "$EFFECTIVE_PORT" != "unknown" ] &&
       ssh_port_is_listening "$EFFECTIVE_PORT"; then
        echo "✓ SSH Listener              : listening"
    else
        echo "✗ SSH Listener              : not verified"
    fi

    TARGET_USER="$(ssh_access_get_target_user)"
    HOME_DIR="$(ssh_access_get_user_home "$TARGET_USER")"

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

    AUTHORIZED_KEYS_SETTING="$(
        "$SSHD_PATH" -T \
            -C "user=root,host=$SSH_HOST,addr=127.0.0.1" 2>/dev/null |
            awk '
                $1 == "authorizedkeysfile" {
                    $1=""
                    sub(/^ /, "")
                    print
                    exit
                }
            '
    )"

    if [ -z "$AUTHORIZED_KEYS_SETTING" ]; then
        AUTHORIZED_KEYS_SETTING="unknown"
    fi

    echo "AuthorizedKeysFile          : $AUTHORIZED_KEYS_SETTING"

    if [ "$AUTHORIZED_KEYS_SETTING" != "unknown" ] &&
       [ "$AUTHORIZED_KEYS_SETTING" != "none" ] &&
       [ -n "$HOME_DIR" ]; then

        for KEY_FILE in $AUTHORIZED_KEYS_SETTING; do
            local EXPANDED_KEY_FILE

            EXPANDED_KEY_FILE="$(
                ssh_access_expand_authorized_keys_path \
                    "$TARGET_USER" \
                    "$HOME_DIR" \
                    "$KEY_FILE"
            )"

            KEY_FILES="${KEY_FILES}${EXPANDED_KEY_FILE}"$'\n'
        done

        while IFS= read -r KEY_FILE; do
            [ -z "$KEY_FILE" ] && continue

            local FILE_KEYS

            FILE_KEYS="$(ssh_access_count_keys_in_file "$KEY_FILE")"
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
        echo "⚠ Unable to resolve authorized key files for root."
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

    if [ "$PASSWORD_AUTH" = "no" ] &&
       [ "$KBD_INTERACTIVE_AUTH" = "no" ] &&
       [ "$PUBKEY_AUTH" = "yes" ] &&
       [ "$ROOT_LOGIN" = "yes" ]; then
        echo "✓ Root is configured for key-only SSH access"
    else
        echo "⚠ Root is not fully configured for key-only SSH access"
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
    echo "0) Back"
    echo

    while true; do
        read -rp "Key name: " KEY_NAME

        if [ "$KEY_NAME" = "0" ]; then
            rm -rf "$KEY_DIR"
            return
        fi

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
    echo "Passphrase is optional."
    echo "Press Enter twice to create the key without a passphrase."
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
                rm -rf "$KEY_DIR"
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

    TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')
    BACKUP_DIR="$SSH_AUTHORIZED_KEYS_BACKUP_DIR/backup-$TIMESTAMP"

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
    local GROUP_NAME

    TARGET_USER=$(ssh_access_get_target_user)
    HOME_DIR=$(ssh_access_get_user_home "$TARGET_USER")
    GROUP_NAME=$(id -gn "$TARGET_USER" 2>/dev/null || true)

    if [ -z "$HOME_DIR" ] || [ ! -d "$HOME_DIR" ] || [ -z "$GROUP_NAME" ]; then
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
    echo "0) Back"
    echo

    read -r PUBLIC_KEY

    if [ "$PUBLIC_KEY" = "0" ]; then
        return
    fi

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
        chown "$TARGET_USER:$GROUP_NAME" "$SSH_DIR"
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
        chown "$TARGET_USER:$GROUP_NAME" "$AUTHORIZED_KEYS_FILE"
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
    chown "$TARGET_USER:$GROUP_NAME" "$AUTHORIZED_KEYS_FILE"

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





ssh_access_restore() {
    ssh_access_require_root || return 1

    local target_user
    local user_home
    local ssh_dir
    local authorized_keys
    local backups=()
    local backup
    local selected
    local backup_path
    local current_backup
    local timestamp
    local confirm
    local group_name
    local restore_failed=0

    target_user="$(ssh_access_get_target_user)"
    user_home="$(ssh_access_get_user_home "$target_user")"

    if [[ -z "$user_home" || ! -d "$user_home" ]]; then
        echo "✗ Could not determine home directory for user: $target_user"
        read -rp "Press Enter to return..."
        return 1
    fi

    ssh_dir="$user_home/.ssh"
    authorized_keys="$ssh_dir/authorized_keys"
    group_name="$(id -gn "$target_user")"

    if [[ ! -d "$SSH_AUTHORIZED_KEYS_BACKUP_DIR" ]]; then
        echo
        echo "No SSH access backups were found."
        read -rp "Press Enter to return..."
        return 0
    fi

    while IFS= read -r backup; do
        [[ -n "$backup" ]] && backups+=("$backup")
    done < <(
        ls -dt \
            "$SSH_AUTHORIZED_KEYS_BACKUP_DIR"/backup-* \
            "$SSH_AUTHORIZED_KEYS_BACKUP_DIR"/????????-?????? \
            2>/dev/null
    )

    if [[ ${#backups[@]} -eq 0 ]]; then
        echo
        echo "No SSH access backups were found."
        read -rp "Press Enter to return..."
        return 0
    fi

    echo
    echo "======================================"
    echo "          SSH Access Restore"
    echo "======================================"
    echo
    echo "Available Backups"
    echo "--------------------------------------"

    local i=1

    for backup in "${backups[@]}"; do
        echo "$i) $(basename "$backup")"
        ((i++))
    done

    echo
	
	
	
	
    echo
    echo "0) Back"
    echo
    read -rp "Select backup [0-${#backups[@]}]: " selected

    if ! [[ "$selected" =~ ^[0-9]+$ ]] ||
   (( selected < 0 || selected > ${#backups[@]} )); then
    echo "✗ Invalid selection."
    read -rp "Press Enter to return..."
    return 1
    fi

    if (( selected == 0 )); then
    return 0
    fi
	
	
	
	

    backup_path="${backups[$((selected - 1))]}"

    echo
    echo "Selected Backup"
    echo "--------------------------------------"
    echo "Path        : $backup_path"

    [[ -f "$backup_path/authorized_keys" ]] \
        && echo "✓ authorized_keys found" \
        || echo "- authorized_keys not found"

    [[ -f "$backup_path/sshd_config" ]] \
        && echo "✓ sshd_config found" \
        || echo "- sshd_config not found"

    [[ -d "$backup_path/sshd_config.d" ]] \
        && echo "✓ sshd_config.d found" \
        || echo "- sshd_config.d not found"

    echo
    echo "WARNING"
    echo "This will restore SSH access files from the selected backup."
    echo "Your current SSH access configuration will be replaced."
    echo
    read -rp "Continue with restore? [y/N]: " confirm

    [[ "$confirm" =~ ^[Yy]$ ]] || {
        echo
        echo "Restore cancelled."
        read -rp "Press Enter to return..."
        return 0
    }

    timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
    current_backup="$SSH_AUTHORIZED_KEYS_BACKUP_DIR/pre-restore-$timestamp"

    mkdir -p "$current_backup" || {
        echo "✗ Failed to create pre-restore backup."
        read -rp "Press Enter to return..."
        return 1
    }

    chmod 700 "$current_backup"

    echo
    echo "Creating safety backup of current SSH configuration..."

    if [[ -f "$authorized_keys" ]]; then
        cp -a "$authorized_keys" "$current_backup/authorized_keys" || restore_failed=1
    fi

    if [[ -f /etc/ssh/sshd_config ]]; then
        cp -a /etc/ssh/sshd_config "$current_backup/sshd_config" || restore_failed=1
    fi

    if [[ -d /etc/ssh/sshd_config.d ]]; then
        cp -a /etc/ssh/sshd_config.d "$current_backup/sshd_config.d" || restore_failed=1
    fi

    if (( restore_failed != 0 )); then
        echo "✗ Failed to create safety backup."
        echo "Restore aborted."
        read -rp "Press Enter to return..."
        return 1
    fi

    echo "✓ Safety backup created:"
    echo "  $current_backup"

    echo
    echo "Restoring SSH access files..."

    if [[ -f "$backup_path/authorized_keys" ]]; then
        mkdir -p "$ssh_dir"

        if ! chmod 700 "$ssh_dir"; then
            restore_failed=1
        fi

        if ! chown "$target_user:$group_name" "$ssh_dir"; then
            restore_failed=1
        fi

        if (( restore_failed == 0 )); then
            if ! cp -a "$backup_path/authorized_keys" "$authorized_keys"; then
                restore_failed=1
            else
                chmod 600 "$authorized_keys"
                chown "$target_user:$group_name" "$authorized_keys"
            fi
        fi
    fi

    if [[ -f "$backup_path/sshd_config" ]]; then
        if ! cp -a "$backup_path/sshd_config" /etc/ssh/sshd_config; then
            restore_failed=1
        fi
    fi

    if [[ -d "$backup_path/sshd_config.d" ]]; then
        if ! rm -rf /etc/ssh/sshd_config.d; then
            restore_failed=1
        elif ! cp -a "$backup_path/sshd_config.d" /etc/ssh/sshd_config.d; then
            restore_failed=1
        fi
    fi

    if (( restore_failed != 0 )); then
        echo
        echo "✗ Restore failed."
        echo "Attempting automatic rollback..."

        if [[ -f "$current_backup/authorized_keys" ]]; then
            cp -a "$current_backup/authorized_keys" "$authorized_keys"
            chmod 600 "$authorized_keys"
            chown "$target_user:$group_name" "$authorized_keys"
        fi

        if [[ -f "$current_backup/sshd_config" ]]; then
            cp -a "$current_backup/sshd_config" /etc/ssh/sshd_config
        fi

        if [[ -d "$current_backup/sshd_config.d" ]]; then
            rm -rf /etc/ssh/sshd_config.d
            cp -a "$current_backup/sshd_config.d" /etc/ssh/sshd_config.d
        fi

        echo "✓ Rollback completed."
        read -rp "Press Enter to return..."
        return 1
    fi

    echo
    echo "Validating restored SSH configuration..."

    if [[ -x /usr/sbin/sshd ]]; then
        if ! /usr/sbin/sshd -t >/dev/null 2>&1; then
            echo
            echo "✗ Restored SSH configuration is invalid."
            echo "Attempting automatic rollback..."

            if [[ -f "$current_backup/authorized_keys" ]]; then
                cp -a "$current_backup/authorized_keys" "$authorized_keys"
                chmod 600 "$authorized_keys"
                chown "$target_user:$group_name" "$authorized_keys"
            fi

            if [[ -f "$current_backup/sshd_config" ]]; then
                cp -a "$current_backup/sshd_config" /etc/ssh/sshd_config
            fi

            if [[ -d "$current_backup/sshd_config.d" ]]; then
                rm -rf /etc/ssh/sshd_config.d
                cp -a "$current_backup/sshd_config.d" /etc/ssh/sshd_config.d
            fi

            echo "✓ Rollback completed."
            echo
            echo "Your previous SSH configuration has been restored."
            echo
            echo "Safety Backup:"
            echo "$current_backup"

            read -rp "Press Enter to return..."
            return 1
        fi
    fi

    echo
    echo "======================================"
    echo "       SSH Access Restored"
    echo "======================================"
    echo
    echo "Restored From : $(basename "$backup_path")"
    echo "Safety Backup : $(basename "$current_backup")"
    echo
    echo "✓ SSH access files restored."
    echo "✓ SSH configuration validation passed."
    echo
    echo "No SSH service restart was performed."
    echo

    read -rp "Press Enter to return..."
}







ssh_access_backup_restore() {
    ssh_access_require_root || return 1

    local target_user
    local user_home
    local ssh_dir
    local authorized_keys
    local backup_dir
    local timestamp
    local backup_path

    target_user="$(ssh_access_get_target_user)"
    user_home="$(ssh_access_get_user_home "$target_user")"

    if [[ -z "$user_home" || ! -d "$user_home" ]]; then
        echo "✗ Could not determine home directory for user: $target_user"
        read -rp "Press Enter to return..."
        return 1
    fi

    ssh_dir="$user_home/.ssh"
    authorized_keys="$ssh_dir/authorized_keys"

    timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
    backup_path="$SSH_AUTHORIZED_KEYS_BACKUP_DIR/backup-$timestamp"

    mkdir -p "$backup_path" || {
        echo "✗ Failed to create backup directory."
        read -rp "Press Enter to return..."
        return 1
    }

    chmod 700 "$backup_path"

    if [[ -f "$authorized_keys" ]]; then
        cp -a "$authorized_keys" "$backup_path/authorized_keys" || {
            echo "✗ Failed to back up authorized_keys."
            rm -rf "$backup_path"
            read -rp "Press Enter to return..."
            return 1
        }
    fi

    if [[ -f /etc/ssh/sshd_config ]]; then
        cp -a /etc/ssh/sshd_config "$backup_path/sshd_config"
    fi

    if [[ -d /etc/ssh/sshd_config.d ]]; then
        cp -a /etc/ssh/sshd_config.d "$backup_path/sshd_config.d"
    fi

    cat <<EOF

======================================
       SSH Access Backup Created
======================================

User        : $target_user
Backup Path : $backup_path

Included:
  - authorized_keys
  - sshd_config
  - sshd_config.d/

EOF

    if [[ -f "$authorized_keys" ]]; then
        echo "✓ Public key access backed up."
    else
        echo "- No authorized_keys file found."
    fi

    echo
    echo "Keep this backup in a secure location."
    echo
    read -rp "Press Enter to return..."
}




ssh_access_change_user_password() {
    clear

    echo "======================================"
    echo "         Change User Password"
    echo "======================================"
    echo

    ssh_access_require_root || {
        read -rp "Press Enter to return..."
        return 1
    }

    local TARGET_USER
    local PASSWORD
    local CONFIRM_PASSWORD
    local CONFIRM

    TARGET_USER="$(ssh_access_get_target_user)"

    if [ -z "$TARGET_USER" ] || ! id "$TARGET_USER" >/dev/null 2>&1; then
        echo "✗ Unable to determine target user."
        echo
        read -rp "Press Enter to return..."
        return 1
    fi

    echo "Target User : $TARGET_USER"
    echo
    echo "This will change the password for the selected user."
    echo
    echo "0) Back"
    echo

    read -rp "Continue? [0-1]: " CONFIRM

    case "$CONFIRM" in
        0)
            return 0
            ;;
        1)
            ;;
        *)
            echo
            echo "Invalid selection."
            read -rp "Press Enter to return..."
            return 1
            ;;
    esac

    echo
    echo "Enter a new password for this user."
    echo "The password will not be displayed while typing."
    echo

    while true; do
        read -rsp "New password: " PASSWORD
        echo

        if [ -z "$PASSWORD" ]; then
            echo
            echo "✗ Password cannot be empty."
            echo
            continue
        fi

        read -rsp "Confirm password: " CONFIRM_PASSWORD
        echo

        if [ "$PASSWORD" != "$CONFIRM_PASSWORD" ]; then
            echo
            echo "✗ Passwords do not match."
            echo
            continue
        fi

        break
    done

    echo
    echo "WARNING"
    echo "The password for user '$TARGET_USER' will be changed."
    echo

    read -rp "Confirm password change? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "Operation cancelled."
            unset PASSWORD
            unset CONFIRM_PASSWORD
            read -rp "Press Enter to return..."
            return 0
            ;;
    esac

    if printf '%s:%s\n' "$TARGET_USER" "$PASSWORD" | chpasswd; then
        echo
        echo "======================================"
        echo "     Password Changed Successfully"
        echo "======================================"
        echo
        echo "User : $TARGET_USER"
        echo
        echo "The new password is now active."
    else
        echo
        echo "======================================"
        echo "        Password Change Failed"
        echo "======================================"
        echo
        echo "No password change was completed."
    fi

    unset PASSWORD
    unset CONFIRM_PASSWORD

    echo
    read -rp "Press Enter to return..."
}







ssh_access_authentication_settings() {
    clear

    echo "======================================"
    echo "     SSH Authentication Settings"
    echo "======================================"
    echo

    if ! ssh_access_require_root; then
        read -rp "Press Enter to return..."
        return 1
    fi

    local TARGET_USER
    local HOME_DIR
    local AUTHORIZED_KEYS_FILE
    local PASSWORD_AUTH
    local KBD_INTERACTIVE_AUTH
    local PUBKEY_AUTH
    local ROOT_LOGIN
    local AUTH_METHODS
    local KEY_COUNT
    local AUTH_MODE
    local CHOICE
    local SSHD_PATH
    local SSH_BACKUP_DIR
    local BACKUP_PATH
    local CONFIG_FILE
    local TEMP_CONFIG
    local VERIFY_PASSWORD_AUTH
    local VERIFY_KBD_AUTH
    local VERIFY_PUBKEY_AUTH
    local CONFIRM
    local MARKER_BEGIN
    local MARKER_END
    local SSH_HOST

    TARGET_USER="$(ssh_access_get_target_user)"
    HOME_DIR="$(ssh_access_get_user_home "$TARGET_USER")"
    AUTHORIZED_KEYS_FILE="$HOME_DIR/.ssh/authorized_keys"
    SSH_BACKUP_DIR="$SSH_AUTHORIZED_KEYS_BACKUP_DIR"
    CONFIG_FILE="/etc/ssh/sshd_config"
    MARKER_BEGIN="# BEGIN U-OPTI MANAGED ROOT SSH AUTH"
    MARKER_END="# END U-OPTI MANAGED ROOT SSH AUTH"
    SSH_HOST="localhost"

    SSHD_PATH="$(command -v sshd 2>/dev/null || true)"

    if [ -z "$SSHD_PATH" ]; then
        echo "✗ OpenSSH server was not found."
        echo
        read -rp "Press Enter to return..."
        return 1
    fi

    ssh_root_effective_setting() {
        local SETTING="$1"

        ssh_prepare_runtime_dir >/dev/null 2>&1 || return 1

        "$SSHD_PATH" -T \
            -C "user=root,host=$SSH_HOST,addr=127.0.0.1" 2>/dev/null |
            awk -v key="$SETTING" '
                $1 == key {
                    $1=""
                    sub(/^ /, "")
                    print
                    exit
                }
            '
    }

    ssh_auth_remove_managed_block() {
        local INPUT_FILE="$1"
        local OUTPUT_FILE="$2"

        awk -v begin="$MARKER_BEGIN" -v end="$MARKER_END" '
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
        ' "$INPUT_FILE" > "$OUTPUT_FILE"
    }

    ssh_auth_build_key_only_config() {
        local INPUT_FILE="$1"
        local OUTPUT_FILE="$2"

        if ! ssh_auth_remove_managed_block "$INPUT_FILE" "$OUTPUT_FILE"; then
            return 1
        fi

        local INSERTED=0
        local TEMP_INSERT

        TEMP_INSERT="$(mktemp)" || return 1

        awk \
            -v begin="$MARKER_BEGIN" \
            -v end="$MARKER_END" '
            function print_block() {
                print begin
                print "Match User root"
                print "    PasswordAuthentication no"
                print "    KbdInteractiveAuthentication no"
                print "    PubkeyAuthentication yes"
                print "Match All"
                print end
            }

            !inserted &&
            $0 ~ /^[[:space:]]*PermitRootLogin[[:space:]]+/ {
                print_block()
                inserted=1
            }

            {
                print
            }

            END {
                if (!inserted) {
                    print ""
                    print_block()
                }
            }
        ' "$OUTPUT_FILE" > "$TEMP_INSERT"

        mv -f "$TEMP_INSERT" "$OUTPUT_FILE"
    }

    ssh_auth_create_backup() {
        local BACKUP_TIMESTAMP
        local BACKUP_TARGET

        BACKUP_TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
        BACKUP_TARGET="$SSH_BACKUP_DIR/backup-$BACKUP_TIMESTAMP"

        if ! mkdir -p "$BACKUP_TARGET"; then
            return 1
        fi

        chmod 700 "$BACKUP_TARGET"

        if [ -f "$CONFIG_FILE" ]; then
            if ! cp -a "$CONFIG_FILE" "$BACKUP_TARGET/sshd_config"; then
                rm -rf "$BACKUP_TARGET"
                return 1
            fi
        fi

        if [ -d /etc/ssh/sshd_config.d ]; then
            if ! cp -a /etc/ssh/sshd_config.d "$BACKUP_TARGET/sshd_config.d"; then
                rm -rf "$BACKUP_TARGET"
                return 1
            fi
        fi

        if [ -f "$AUTHORIZED_KEYS_FILE" ]; then
            if ! cp -a "$AUTHORIZED_KEYS_FILE" "$BACKUP_TARGET/authorized_keys"; then
                rm -rf "$BACKUP_TARGET"
                return 1
            fi
        fi

        printf '%s\n' "$BACKUP_TARGET"
    }

    PASSWORD_AUTH="$(ssh_root_effective_setting "passwordauthentication" || true)"
    KBD_INTERACTIVE_AUTH="$(ssh_root_effective_setting "kbdinteractiveauthentication" || true)"
    PUBKEY_AUTH="$(ssh_root_effective_setting "pubkeyauthentication" || true)"
    ROOT_LOGIN="$(ssh_root_effective_setting "permitrootlogin" || true)"
    AUTH_METHODS="$(ssh_root_effective_setting "authenticationmethods" || true)"

    KEY_COUNT=0

    if [ "$TARGET_USER" = "root" ] &&
       [ -f "$AUTHORIZED_KEYS_FILE" ]; then
        KEY_COUNT="$(ssh_access_count_keys_in_file "$AUTHORIZED_KEYS_FILE")"
    fi

    if [ "$PASSWORD_AUTH" = "yes" ] &&
       [ "$PUBKEY_AUTH" = "yes" ]; then
        AUTH_MODE="Password + Public Key"
    elif [ "$PASSWORD_AUTH" = "no" ] &&
         [ "$PUBKEY_AUTH" = "yes" ]; then
        AUTH_MODE="Public Key Only"
    elif [ "$PASSWORD_AUTH" = "yes" ] &&
         [ "$PUBKEY_AUTH" != "yes" ]; then
        AUTH_MODE="Password Only"
    else
        AUTH_MODE="Custom / Restricted"
    fi

    echo "Current Status"
    echo "--------------------------------------"
    echo "User                      : $TARGET_USER"
    echo "Root SSH Login            : $ROOT_LOGIN"
    echo "Public Key Authentication : $PUBKEY_AUTH"
    echo "Password Authentication   : $PASSWORD_AUTH"
    echo "Keyboard-Interactive      : $KBD_INTERACTIVE_AUTH"
    echo "Installed Public Keys     : $KEY_COUNT"
    echo
    echo "Authentication Methods    : ${AUTH_METHODS:-unknown}"
    echo
    echo "SSH Access Mode           : $AUTH_MODE"

    echo
    echo "--------------------------------------"
    echo
    echo "1) Enable Key-Only Login"
    echo "2) Enable Password Login"
    echo "0) Back"
    echo

    read -rp "Please enter your selection [0-2]: " CHOICE

    case "$CHOICE" in
        1)
            clear

            echo "======================================"
            echo "        Enable Key-Only Login"
            echo "======================================"
            echo

            local CHECK_FAILED=0
            local CURRENT_CONFIG
            local BACKUP_RESULT
            local CURRENT_SESSION

            echo "Security Checks"
            echo "--------------------------------------"

            if [ "$TARGET_USER" = "root" ]; then
                echo "✓ Target User                : root"
            else
                echo "✗ Target User                : $TARGET_USER"
                echo "  Key-Only Login is restricted to root."
                CHECK_FAILED=1
            fi

            if [ "$ROOT_LOGIN" = "yes" ] ||
               [ "$ROOT_LOGIN" = "prohibit-password" ]; then
                echo "✓ Root SSH Login             : $ROOT_LOGIN"
            else
                echo "✗ Root SSH Login             : $ROOT_LOGIN"
                CHECK_FAILED=1
            fi

            if [ "$PUBKEY_AUTH" = "yes" ]; then
                echo "✓ Public Key Authentication  : enabled"
            else
                echo "✗ Public Key Authentication  : $PUBKEY_AUTH"
                CHECK_FAILED=1
            fi

            if [ "$KEY_COUNT" -gt 0 ]; then
                echo "✓ Root Public Keys           : $KEY_COUNT found"
            else
                echo "✗ Root Public Keys           : none found"
                CHECK_FAILED=1
            fi

            if [ -n "$SSH_CONNECTION" ]; then
                CURRENT_SESSION="detected"
                echo "✓ Current SSH Session        : detected"
            else
                CURRENT_SESSION="not detected"
                echo "✗ Current SSH Session        : not detected"
                CHECK_FAILED=1
            fi

            if "$SSHD_PATH" -t >/dev/null 2>&1; then
                echo "✓ SSH Configuration          : valid"
            else
                echo "✗ SSH Configuration          : invalid"
                CHECK_FAILED=1
            fi

            if [ -z "$AUTH_METHODS" ] ||
               [ "$AUTH_METHODS" = "any" ]; then
                echo "✓ Authentication Methods     : compatible"
            elif [[ "$AUTH_METHODS" == *password* ]] ||
                 [[ "$AUTH_METHODS" == *keyboard-interactive* ]]; then
                echo "✗ Authentication Methods     : password-based method required"
                echo "  Current value: $AUTH_METHODS"
                CHECK_FAILED=1
            else
                echo "⚠ Authentication Methods     : custom"
                echo "  Current value: $AUTH_METHODS"
            fi

            echo
            echo "--------------------------------------"

            if [ "$CHECK_FAILED" -ne 0 ]; then
                echo
                echo "✗ Key-Only Login cannot be enabled."
                echo
                echo "No SSH settings were changed."
                echo
                read -rp "Press Enter to return..."
                return 1
            fi

            echo
            echo "✓ All safety checks passed."
            echo
            echo "This operation will:"
            echo "  - Create a full SSH safety backup"
            echo "  - Add a U-OPTI managed root authentication policy"
            echo "  - Disable password authentication for root"
            echo "  - Disable keyboard-interactive authentication for root"
            echo "  - Keep public key authentication enabled"
            echo "  - Keep UsePAM unchanged"
            echo "  - Validate the new configuration before applying it"
            echo "  - Reload SSH"
            echo "  - Verify the effective root authentication settings"
            echo "  - Roll back automatically on failure"
            echo
            echo "Your current SSH session will remain open."
            echo
            read -rp "Enable Key-Only Login now? [y/N]: " CONFIRM

            case "$CONFIRM" in
                y|Y|yes|YES)
                    ;;
                *)
                    echo
                    echo "Operation cancelled."
                    read -rp "Press Enter to return..."
                    return 0
                    ;;
            esac

            BACKUP_RESULT="$(ssh_auth_create_backup)"

            if [ -z "$BACKUP_RESULT" ]; then
                echo
                echo "✗ Failed to create SSH safety backup."
                echo "No SSH settings were changed."
                echo
                read -rp "Press Enter to return..."
                return 1
            fi

            BACKUP_PATH="$BACKUP_RESULT"

            echo
            echo "Creating SSH safety backup..."
            echo "✓ Safety backup created:"
            echo "  $BACKUP_PATH"

            TEMP_CONFIG="$(mktemp)" || {
                echo
                echo "✗ Failed to create temporary SSH configuration."
                read -rp "Press Enter to return..."
                return 1
            }

            if ! ssh_auth_build_key_only_config "$CONFIG_FILE" "$TEMP_CONFIG"; then
                rm -f "$TEMP_CONFIG"
                echo
                echo "✗ Failed to build new SSH configuration."
                echo "No SSH settings were changed."
                read -rp "Press Enter to return..."
                return 1
            fi

            if ! chown --reference="$CONFIG_FILE" "$TEMP_CONFIG" ||
               ! chmod --reference="$CONFIG_FILE" "$TEMP_CONFIG"; then
                rm -f "$TEMP_CONFIG"
                echo
                echo "✗ Failed to preserve SSH configuration permissions."
                read -rp "Press Enter to return..."
                return 1
            fi

            echo
            echo "Validating new SSH configuration..."

            if ! "$SSHD_PATH" -t -f "$TEMP_CONFIG" >/dev/null 2>&1; then
                rm -f "$TEMP_CONFIG"
                echo
                echo "✗ New SSH configuration is invalid."
                echo "No SSH settings were changed."
                read -rp "Press Enter to return..."
                return 1
            fi

            VERIFY_PASSWORD_AUTH="$(
                "$SSHD_PATH" -T -f "$TEMP_CONFIG" \
                    -C "user=root,host=$SSH_HOST,addr=127.0.0.1" 2>/dev/null |
                    awk '$1 == "passwordauthentication" {print $2; exit}'
            )"

            VERIFY_KBD_AUTH="$(
                "$SSHD_PATH" -T -f "$TEMP_CONFIG" \
                    -C "user=root,host=$SSH_HOST,addr=127.0.0.1" 2>/dev/null |
                    awk '$1 == "kbdinteractiveauthentication" {print $2; exit}'
            )"

            VERIFY_PUBKEY_AUTH="$(
                "$SSHD_PATH" -T -f "$TEMP_CONFIG" \
                    -C "user=root,host=$SSH_HOST,addr=127.0.0.1" 2>/dev/null |
                    awk '$1 == "pubkeyauthentication" {print $2; exit}'
            )"

            if [ "$VERIFY_PASSWORD_AUTH" != "no" ] ||
               [ "$VERIFY_KBD_AUTH" != "no" ] ||
               [ "$VERIFY_PUBKEY_AUTH" != "yes" ]; then
                rm -f "$TEMP_CONFIG"
                echo
                echo "✗ Pre-apply authentication verification failed."
                echo
                echo "Expected:"
                echo "  passwordauthentication no"
                echo "  kbdinteractiveauthentication no"
                echo "  pubkeyauthentication yes"
                echo
                echo "No SSH settings were changed."
                read -rp "Press Enter to return..."
                return 1
            fi

            if ! mv -f "$TEMP_CONFIG" "$CONFIG_FILE"; then
                rm -f "$TEMP_CONFIG"
                echo
                echo "✗ Failed to apply SSH configuration."
                echo "No SSH reload was performed."
                read -rp "Press Enter to return..."
                return 1
            fi

            echo "✓ New SSH configuration applied."

            echo
            echo "Reloading SSH service..."

            if ! systemctl reload "$SSH_SERVICE_UNIT" >/dev/null 2>&1; then
                echo "✗ SSH service reload failed."
                echo "Rolling back automatically..."

                cp -a "$BACKUP_PATH/sshd_config" "$CONFIG_FILE"
                systemctl reload "$SSH_SERVICE_UNIT" >/dev/null 2>&1 || true

                echo "✓ Previous SSH configuration restored."
                read -rp "Press Enter to return..."
                return 1
            fi

            VERIFY_PASSWORD_AUTH="$(ssh_root_effective_setting "passwordauthentication" || true)"
            VERIFY_KBD_AUTH="$(ssh_root_effective_setting "kbdinteractiveauthentication" || true)"
            VERIFY_PUBKEY_AUTH="$(ssh_root_effective_setting "pubkeyauthentication" || true)"

            echo
            echo "Verifying effective root SSH settings..."
            echo

            if [ "$VERIFY_PASSWORD_AUTH" = "no" ]; then
                echo "✓ Root Password Authentication : disabled"
            else
                echo "✗ Root Password Authentication : $VERIFY_PASSWORD_AUTH"
                CHECK_FAILED=1
            fi

            if [ "$VERIFY_KBD_AUTH" = "no" ]; then
                echo "✓ Root Keyboard-Interactive    : disabled"
            else
                echo "✗ Root Keyboard-Interactive    : $VERIFY_KBD_AUTH"
                CHECK_FAILED=1
            fi

            if [ "$VERIFY_PUBKEY_AUTH" = "yes" ]; then
                echo "✓ Root Public Key              : enabled"
            else
                echo "✗ Root Public Key              : $VERIFY_PUBKEY_AUTH"
                CHECK_FAILED=1
            fi

            if [ "$CHECK_FAILED" -ne 0 ]; then
                echo
                echo "✗ Effective SSH authentication verification failed."
                echo "Rolling back automatically..."

                if [ -f "$BACKUP_PATH/sshd_config" ]; then
                    cp -a "$BACKUP_PATH/sshd_config" "$CONFIG_FILE"
                fi

                systemctl reload "$SSH_SERVICE_UNIT" >/dev/null 2>&1 || true

                echo "✓ Rollback completed."
                read -rp "Press Enter to return..."
                return 1
            fi

            echo
            echo "======================================"
            echo "       Key-Only Mode Enabled"
            echo "======================================"
            echo
            echo "Backup:"
            echo "  $BACKUP_PATH"
            echo
            echo "Your current SSH session is still active."
            echo
            echo "NOW TEST A SECOND SSH SESSION"
            echo "using your private key (kolbe)."
            echo
            echo "Do NOT close this current session."
            echo
            echo "Test the second connection and return here."
            echo

            read -rp "Did key-based SSH login succeed? [y/N]: " CONFIRM

            case "$CONFIRM" in
                y|Y|yes|YES)
                    echo
                    echo "✓ Key-based SSH login confirmed."
                    echo
                    echo "Root is now configured for key-only SSH access."
                    ;;

                *)
                    echo
                    echo "Key-based SSH login was not confirmed."
                    echo "Rolling back SSH authentication settings..."

                    if [ -f "$BACKUP_PATH/sshd_config" ]; then
                        cp -a "$BACKUP_PATH/sshd_config" "$CONFIG_FILE"
                    fi

                    if systemctl reload "$SSH_SERVICE_UNIT" >/dev/null 2>&1; then
                        echo "✓ Rollback completed."
                    else
                        echo "⚠ Configuration rollback completed on disk, but SSH reload failed."
                        echo "Keep this session open."
                    fi

                    echo
                    echo "Previous SSH authentication settings have been restored."
                    ;;
            esac

            read -rp "Press Enter to return..."
            ;;

        2)
            clear

            echo "======================================"
            echo "        Enable Password Login"
            echo "======================================"
            echo

            if [ "$TARGET_USER" != "root" ]; then
                echo "✗ Target user is not root."
                echo "This setting is restricted to root."
                echo
                read -rp "Press Enter to return..."
                return 1
            fi

            CURRENT_AUTH="$(grep -nF "$MARKER_BEGIN" "$CONFIG_FILE" 2>/dev/null || true)"

            if [ -z "$CURRENT_AUTH" ]; then
                echo "Password authentication is not disabled by U-OPTI."
                echo "No changes were made."
                echo
                read -rp "Press Enter to return..."
                return 0
            fi

            echo "This will remove the U-OPTI root key-only policy."
            echo "The previous global SSH authentication settings will remain unchanged."
            echo
            echo "Your current SSH session will remain open."
            echo

            read -rp "Restore Password Login? [y/N]: " CONFIRM

            case "$CONFIRM" in
                y|Y|yes|YES)
                    ;;
                *)
                    echo
                    echo "Operation cancelled."
                    read -rp "Press Enter to return..."
                    return 0
                    ;;
            esac

            TEMP_CONFIG="$(mktemp)" || {
                echo
                echo "✗ Failed to create temporary SSH configuration."
                read -rp "Press Enter to return..."
                return 1
            }

            if ! ssh_auth_remove_managed_block "$CONFIG_FILE" "$TEMP_CONFIG"; then
                rm -f "$TEMP_CONFIG"
                echo
                echo "✗ Failed to prepare SSH configuration."
                read -rp "Press Enter to return..."
                return 1
            fi

            if ! chown --reference="$CONFIG_FILE" "$TEMP_CONFIG" ||
               ! chmod --reference="$CONFIG_FILE" "$TEMP_CONFIG"; then
                rm -f "$TEMP_CONFIG"
                echo
                echo "✗ Failed to preserve SSH configuration permissions."
                read -rp "Press Enter to return..."
                return 1
            fi

            if ! "$SSHD_PATH" -t -f "$TEMP_CONFIG" >/dev/null 2>&1; then
                rm -f "$TEMP_CONFIG"
                echo
                echo "✗ Resulting SSH configuration is invalid."
                echo "No changes were made."
                read -rp "Press Enter to return..."
                return 1
            fi

            if ! mv -f "$TEMP_CONFIG" "$CONFIG_FILE"; then
                rm -f "$TEMP_CONFIG"
                echo
                echo "✗ Failed to apply SSH configuration."
                read -rp "Press Enter to return..."
                return 1
            fi

            echo "✓ U-OPTI root authentication policy removed."

            if ! systemctl reload "$SSH_SERVICE_UNIT" >/dev/null 2>&1; then
                echo
                echo "✗ SSH service reload failed."
                echo "Keep this session open and inspect the SSH configuration."
                read -rp "Press Enter to return..."
                return 1
            fi

            PASSWORD_AUTH="$(ssh_root_effective_setting "passwordauthentication" || true)"
            PUBKEY_AUTH="$(ssh_root_effective_setting "pubkeyauthentication" || true)"

            echo
            echo "======================================"
            echo "        Password Login Restored"
            echo "======================================"
            echo
            echo "Root Password Authentication : $PASSWORD_AUTH"
            echo "Root Public Key              : $PUBKEY_AUTH"
            echo
            read -rp "Press Enter to return..."
            ;;

        0)
            return 0
            ;;

        *)
            echo
            echo "Invalid selection."
            read -rp "Press Enter to return..."
            ;;
    esac
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
        echo "8) SSH Authentication Settings"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-8]: " SSH_ACCESS_CHOICE

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
                echo "1) Create Backup"
                echo "2) Restore Backup"
                echo "0) Back"
                echo
                read -rp "Please enter your selection [0-2]: " backup_choice

                case "$backup_choice" in
                    1)
                        ssh_access_backup_restore
                        ;;
                    2)
                        ssh_access_restore
                        ;;
                    0)
                        ;;
                    *)
                        echo "Invalid selection."
                        read -rp "Press Enter to return..."
                        ;;
                esac
                ;;
            7)
                ssh_access_change_user_password
                ;;
            8)
                ssh_access_authentication_settings
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
