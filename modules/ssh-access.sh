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
                echo
                echo "SSH Access Check is not implemented yet."
                read -rp "Press Enter to return..."
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
