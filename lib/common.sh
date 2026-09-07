#!/bin/bash

# U-OPTI - Common Functions
# v0.12.0

UOPTI_BACKUP_ROOT="/etc/u-opti/backups"

pause_return() {
    echo
    read -rp "Press Enter to return..."
}

is_root() {
    [ "$EUID" -eq 0 ]
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

print_header() {
    clear

    echo "======================================"
    echo "              $1"
    echo "======================================"
    echo
}

backup_prepare_dir() {
    mkdir -p "$UOPTI_BACKUP_ROOT"
}

backup_create() {
    local BACKUP_NAME="$1"
    shift

    if [ -z "$BACKUP_NAME" ] || [ "$#" -eq 0 ]; then
        echo "Error: Backup name and at least one source path are required." >&2
        return 1
    fi

    backup_prepare_dir || return 1

    local TIMESTAMP
    local BACKUP_DIR
    local ARCHIVE
    local MANIFEST

    TIMESTAMP="$(date '+%Y%m%d-%H%M%S-%N')"
    BACKUP_DIR="$UOPTI_BACKUP_ROOT/${TIMESTAMP}-${BACKUP_NAME}"
    ARCHIVE="$BACKUP_DIR/backup.tar.gz"
    MANIFEST="$BACKUP_DIR/manifest.txt"

    mkdir -p "$BACKUP_DIR" || return 1

    printf 'Backup: %s\n' "$BACKUP_NAME" > "$MANIFEST"
    printf 'Created: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" >> "$MANIFEST"
    printf 'Sources:\n' >> "$MANIFEST"

    local PATH_ITEM
    for PATH_ITEM in "$@"; do
        if [ ! -e "$PATH_ITEM" ]; then
            echo "Error: Backup source not found: $PATH_ITEM" >&2
            rm -rf "$BACKUP_DIR"
            return 1
        fi

        printf '  %s\n' "$PATH_ITEM" >> "$MANIFEST"
    done

    if ! tar -C / -czf "$ARCHIVE" "${@#/}"; then
        echo "Error: Failed to create backup archive." >&2
        rm -rf "$BACKUP_DIR"
        return 1
    fi

    printf 'Archive: %s\n' "$ARCHIVE" >> "$MANIFEST"
    echo "$BACKUP_DIR"
}

backup_validate_archive() {
    local ARCHIVE="$1"

    [ -f "$ARCHIVE" ] || return 1
    tar -tzf "$ARCHIVE" >/dev/null 2>&1
}

backup_restore_archive() {
    local ARCHIVE="$1"

    if ! backup_validate_archive "$ARCHIVE"; then
        echo "Error: Backup archive is missing or invalid." >&2
        return 1
    fi

    if ! tar -C / -xzf "$ARCHIVE" --same-owner --preserve-permissions; then
        echo "Error: Backup restore failed." >&2
        return 1
    fi

    return 0
}
