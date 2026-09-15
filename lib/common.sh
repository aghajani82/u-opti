#!/bin/bash

# U-OPTI - Common Functions
# v0.13.0

UOPTI_BACKUP_ROOT="/etc/u-opti/backups"

# ---------------------------------------------------------------------------
# Global TTY safety net
# ---------------------------------------------------------------------------

uopti_tty_reset() {
    stty sane 2>/dev/null || true

    if command -v tput >/dev/null 2>&1; then
        tput sgr0  2>/dev/null || true
        tput cnorm 2>/dev/null || true
        tput rmcup 2>/dev/null || true
        tput rmkx  2>/dev/null || true
    fi

    printf '\033[0m'                            2>/dev/null || true
    printf '\033[?25h'                          2>/dev/null || true
    printf '\033[?1049l'                        2>/dev/null || true
    printf '\033[?47l'                          2>/dev/null || true
    printf '\033[?1000l\033[?1002l\033[?1003l'  2>/dev/null || true
    printf '\033[?1006l\033[?1015l'             2>/dev/null || true
    printf '\033[?2004l'                        2>/dev/null || true
    printf '\033[?1l\033>'                      2>/dev/null || true
    printf '\033[r'                             2>/dev/null || true
}

clear() {
    uopti_tty_reset
    command clear
}

uopti_tty_hard_reset() {
    uopti_tty_reset

    case "${TERM:-}" in
        xterm*|screen*|tmux*|rxvt*|vt100*|vt220*|linux|alacritty*|kitty*)
            printf '\033c' 2>/dev/null || true
            ;;
    esac
}

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

    if ! tar -C / --exclude="etc/u-opti/backups" -czf "$ARCHIVE" "${@#/}"; then
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
