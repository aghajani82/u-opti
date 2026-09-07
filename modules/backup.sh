#!/bin/bash

# U-OPTI - Backup & Restore Module
# v0.12.0

BACKUP_ROOT="/etc/u-opti/backups"

backup_pause() {
    echo
    read -rp "Press Enter to return..."
}

backup_require_root() {
    [ "$EUID" -eq 0 ]
}

backup_create() {
    clear
    echo "======================================"
    echo "          Create U-OPTI Backup"
    echo "======================================"
    echo
    echo "This backup contains U-OPTI managed configuration only."
    echo
    echo "Included:"
    echo "  - /etc/u-opti"
    echo "  - /etc/ssh/sshd_config"
    echo "  - /etc/ufw"
    echo "  - /etc/fail2ban/jail.d/u-opti-sshd.local"
    echo
    echo "Not included:"
    echo "  - Nginx"
    echo "  - 3x-UI / Xray"
    echo "  - Docker"
    echo "  - Certificates"
    echo
    read -rp "Create this backup? [y/N]: " CONFIRM
    case "$CONFIRM" in
        y|Y|yes|YES) ;;
        0|n|N|no|NO|"") echo; echo "Backup cancelled."; sleep 1; return ;;
        *) echo; echo "Invalid choice. Backup cancelled."; sleep 1; return ;;
    esac

    if ! backup_require_root; then
        echo; echo "Error: Root privileges are required."; backup_pause; return
    fi

    mkdir -p "$BACKUP_ROOT" || { echo; echo "Error: Could not prepare backup directory."; backup_pause; return; }

    local BACKUP_DIR="$BACKUP_ROOT/$(date '+%Y%m%d-%H%M%S-%N')-u-opti"
    local ARCHIVE="$BACKUP_DIR/backup.tar.gz"
    local MANIFEST="$BACKUP_DIR/manifest.txt"
    mkdir -p "$BACKUP_DIR" || { echo; echo "Error: Could not create backup directory."; backup_pause; return; }

    local INCLUDED=()
    local ITEM
    for ITEM in /etc/u-opti /etc/ssh/sshd_config /etc/ufw /etc/fail2ban/jail.d/u-opti-sshd.local; do
        [ -e "$ITEM" ] && INCLUDED+=("${ITEM#/}")
    done

    if [ "${#INCLUDED[@]}" -eq 0 ]; then
        echo; echo "Error: No managed configuration sources were found."; rm -rf "$BACKUP_DIR"; backup_pause; return
    fi

    {
        echo "U-OPTI Backup"
        echo "Created: $(date '+%Y-%m-%d %H:%M:%S %z')"
        echo
        echo "Included paths:"
        printf '  /%s\n' "${INCLUDED[@]}"
        echo
        echo "Excluded:"
        echo "  Nginx"
        echo "  3x-UI / Xray"
        echo "  Docker"
        echo "  Certificates"
    } > "$MANIFEST"

    if ! tar -C / --exclude="etc/u-opti/backups" -czf "$ARCHIVE" "${INCLUDED[@]}"; then
        echo; echo "Error: Failed to create backup archive."; rm -rf "$BACKUP_DIR"; backup_pause; return
    fi

    if ! tar -tzf "$ARCHIVE" >/dev/null 2>&1; then
        echo; echo "Error: Backup archive validation failed."; rm -rf "$BACKUP_DIR"; backup_pause; return
    fi

    chmod 700 "$BACKUP_DIR"
    chmod 600 "$ARCHIVE" "$MANIFEST"

    echo
    echo "======================================"
    echo "        Backup Created"
    echo "======================================"
    echo
    echo "Backup location: $BACKUP_DIR"
    echo "Archive: $ARCHIVE"
    echo "Backup archive validation: OK"
    backup_pause
}

backup_list() {
    clear
    echo "======================================"
    echo "           List Backups"
    echo "======================================"
    echo

    if [ ! -d "$BACKUP_ROOT" ]; then
        echo "No backups found."
        backup_pause
        return
    fi

    local FOUND=false
    local DIR
    while IFS= read -r DIR; do
        [ -n "$DIR" ] || continue
        FOUND=true
        echo "$(basename "$DIR")"
        [ -f "$DIR/manifest.txt" ] && grep -m1 '^Created:' "$DIR/manifest.txt" || true
        [ -f "$DIR/backup.tar.gz" ] && echo "  Archive: $(du -h "$DIR/backup.tar.gz" | awk '{print $1}')"
        echo
    done < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '*-u-opti' -printf '%p\n' | sort -r)

    [ "$FOUND" = "true" ] || echo "No backups found."
    backup_pause
}

backup_restore() {
    clear
    echo "======================================"
    echo "          Restore U-OPTI Backup"
    echo "======================================"
    echo

    if ! backup_require_root; then
        echo "Error: Root privileges are required."
        backup_pause
        return
    fi

    [ -d "$BACKUP_ROOT" ] || { echo "No backups found."; backup_pause; return; }

    local BACKUPS=()
    local DIR
    local INDEX=1
    while IFS= read -r DIR; do
        [ -n "$DIR" ] || continue
        BACKUPS+=("$DIR")
        echo "$INDEX) $(basename "$DIR")"
        INDEX=$((INDEX + 1))
    done < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '*-u-opti' -printf '%p\n' | sort -r)

    if [ "${#BACKUPS[@]}" -eq 0 ]; then
        echo "No backups found."
        backup_pause
        return
    fi

    echo
    echo "0) Back"
    echo
    read -rp "Select backup [0-${#BACKUPS[@]}]: " BACKUP_CHOICE
    [ "$BACKUP_CHOICE" = "0" ] && return

    if ! [[ "$BACKUP_CHOICE" =~ ^[0-9]+$ ]] || [ "$BACKUP_CHOICE" -lt 1 ] || [ "$BACKUP_CHOICE" -gt "${#BACKUPS[@]}" ]; then
        echo; echo "Invalid selection."; backup_pause; return
    fi

    DIR="${BACKUPS[$((BACKUP_CHOICE - 1))]}"
    local ARCHIVE="$DIR/backup.tar.gz"

    if ! tar -tzf "$ARCHIVE" >/dev/null 2>&1; then
        echo; echo "Error: Backup archive is missing or invalid."; backup_pause; return
    fi

    echo
    echo "Selected backup: $(basename "$DIR")"
    echo
    echo "IMPORTANT: This will replace the currently managed U-OPTI configuration."
    echo
    read -rp "Continue? [y/N]: " CONFIRM
    case "$CONFIRM" in
        y|Y|yes|YES) ;;
        0|n|N|no|NO|"") echo; echo "Restore cancelled."; sleep 1; return ;;
        *) echo; echo "Invalid choice. Restore cancelled."; sleep 1; return ;;
    esac

    local SAFETY_DIR="$BACKUP_ROOT/$(date '+%Y%m%d-%H%M%S-%N')-pre-restore"
    mkdir -p "$SAFETY_DIR" || { echo; echo "Error: Could not create pre-restore backup."; backup_pause; return; }

    local CURRENT_PATHS=()
    local ITEM
    for ITEM in /etc/u-opti /etc/ssh/sshd_config /etc/ufw /etc/fail2ban/jail.d/u-opti-sshd.local; do
        [ -e "$ITEM" ] && CURRENT_PATHS+=("${ITEM#/}")
    done

    if [ "${#CURRENT_PATHS[@]}" -gt 0 ] && ! tar -C / --exclude="etc/u-opti/backups" -czf "$SAFETY_DIR/backup.tar.gz" "${CURRENT_PATHS[@]}"; then
        echo; echo "Error: Pre-restore safety backup failed."; rm -rf "$SAFETY_DIR"; backup_pause; return
    fi

    echo
    echo "Restoring backup..."
    if ! tar -C / -xzf "$ARCHIVE" --same-owner --preserve-permissions; then
        echo; echo "ERROR: Restore failed."
        echo "Safety backup retained at: $SAFETY_DIR"
        backup_pause
        return
    fi

    echo
    echo "Restore completed successfully."
    echo "Safety backup retained at: $SAFETY_DIR"
    backup_pause
}

show_backup_menu() {
    while true; do
        clear
        echo "======================================"
        echo "         Backup & Restore"
        echo "======================================"
        echo
        echo "1) Create Backup"
        echo "2) List Backups"
        echo "3) Restore Backup"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-3]: " BACKUP_CHOICE
        case "$BACKUP_CHOICE" in
            1) backup_create ;;
            2) backup_list ;;
            3) backup_restore ;;
            0) return ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
