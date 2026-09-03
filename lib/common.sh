#!/bin/bash

# U-OPTI - Common Functions
# v0.8.0

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
