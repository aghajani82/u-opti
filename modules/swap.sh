#!/bin/bash

# U-OPTI - Swap Management Module
# v0.8.0

show_swap_menu() {
    while true; do
        clear

        SWAP_TOTAL=$(free -h | awk '/^Swap:/ {print $2}')
        SWAP_USED=$(free -h | awk '/^Swap:/ {print $3}')

        echo "======================================"
        echo "          Swap Management"
        echo "======================================"
        echo

        echo "Current Swap:"
        echo "Size        : $SWAP_TOTAL"
        echo "Used        : $SWAP_USED"

        echo
        echo "--------------------------------------"
        echo
        echo "1) Show Swap Information"
        echo "2) Create Swap"
        echo "3) Resize Swap"
        echo "4) Disable Swap"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-4]: " swap_choice

        case "$swap_choice" in

            1)
                clear

                echo "======================================"
                echo "        Swap Information"
                echo "======================================"
                echo

                free -h

                echo
                echo "Active Swap Devices:"
                swapon --show

                echo
                echo "Swap File:"
                if [ -f /swapfile ]; then
                    ls -lh /swapfile
                else
                    echo "No /swapfile found."
                fi

                echo
                echo "--------------------------------------"
                echo
                read -rp "Press Enter to return..."
                ;;

            2)
                clear

                echo "======================================"
                echo "            Create Swap"
                echo "======================================"
                echo

                if swapon --show | grep -q .; then
                    echo "Swap is already enabled."
                    echo
                    echo "Use 'Resize Swap' to change its size."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                read -rp "Enter Swap size (e.g. 1G, 2G, 4G): " SWAP_SIZE

                if [[ ! "$SWAP_SIZE" =~ ^[0-9]+[MG]$ ]]; then
                    echo
                    echo "Invalid size."
                    echo "Use formats such as: 1G, 2G, 512M"
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                if [ -e /swapfile ]; then
                    echo
                    echo "/swapfile already exists."
                    echo "No changes were made."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                echo
                echo "Creating ${SWAP_SIZE} swap file..."
                echo

                if ! fallocate -l "$SWAP_SIZE" /swapfile 2>/dev/null; then
                    echo "Failed to allocate swap file."
                    rm -f /swapfile
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                chmod 600 /swapfile

                if ! mkswap /swapfile >/dev/null 2>&1; then
                    echo "Failed to initialize swap."
                    rm -f /swapfile
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                if ! swapon /swapfile >/dev/null 2>&1; then
                    echo "Failed to enable swap."
                    rm -f /swapfile
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                if ! grep -q "^/swapfile " /etc/fstab; then
                    echo "/swapfile none swap sw 0 0" >> /etc/fstab
                fi

                echo "Swap created successfully."
                echo
                free -h

                echo
                read -rp "Press Enter to return..."
                ;;

            3)
                clear

                echo "======================================"
                echo "             Resize Swap"
                echo "======================================"
                echo

                if ! swapon --show | grep -q .; then
                    echo "Swap is not currently enabled."
                    echo
                    echo "Use 'Create Swap' first."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                CURRENT_SWAP=$(free -h | awk '/^Swap:/ {print $2}')

                echo "Current Swap Size: $CURRENT_SWAP"
                echo

                read -rp "Enter new Swap size (e.g. 1G, 2G, 4G): " NEW_SWAP_SIZE

                if [[ ! "$NEW_SWAP_SIZE" =~ ^[0-9]+[MG]$ ]]; then
                    echo
                    echo "Invalid size."
                    echo "Use formats such as: 1G, 2G, 4G"
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                if [ ! -f /swapfile ]; then
                    echo
                    echo "The active Swap is not /swapfile."
                    echo "Resize operation cancelled."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                if swapon --show | awk 'NR>1 {print $1}' | grep -vxq "/swapfile"; then
                    echo
                    echo "Multiple Swap devices are active."
                    echo "Resize operation cancelled for safety."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                if grep -q "^/swapfile " /etc/fstab; then
                    FSTAB_SWAP_FOUND="yes"
                else
                    FSTAB_SWAP_FOUND="no"
                fi

                echo
                echo "This will:"
                echo "  - Disable the current /swapfile"
                echo "  - Replace it with a ${NEW_SWAP_SIZE} swap file"
                echo "  - Enable the new Swap"
                echo "  - Keep /etc/fstab configured"
                echo
                read -rp "Continue? [y/N]: " RESIZE_CONFIRM

                case "$RESIZE_CONFIRM" in
                    y|Y|yes|YES)

                        echo
                        echo "Disabling current Swap..."

                        if ! swapoff /swapfile; then
                            echo
                            echo "Failed to disable current Swap."
                            echo
                            read -rp "Press Enter to return..."
                            continue
                        fi

                        echo "Removing old Swap file..."

                        rm -f /swapfile

                        echo "Creating new ${NEW_SWAP_SIZE} Swap file..."

                        if ! fallocate -l "$NEW_SWAP_SIZE" /swapfile 2>/dev/null; then
                            echo
                            echo "Failed to create the new Swap file."
                            echo "Attempting to restore the previous Swap is not possible automatically."
                            rm -f /swapfile
                            echo
                            read -rp "Press Enter to return..."
                            continue
                        fi

                        chmod 600 /swapfile

                        if ! mkswap /swapfile >/dev/null 2>&1; then
                            echo
                            echo "Failed to initialize the new Swap."
                            rm -f /swapfile
                            echo
                            read -rp "Press Enter to return..."
                            continue
                        fi

                        if ! swapon /swapfile >/dev/null 2>&1; then
                            echo
                            echo "Failed to enable the new Swap."
                            rm -f /swapfile
                            echo
                            read -rp "Press Enter to return..."
                            continue
                        fi

                        if [ "$FSTAB_SWAP_FOUND" != "yes" ]; then
                            echo "/swapfile none swap sw 0 0" >> /etc/fstab
                        fi

                        echo
                        echo "Swap resized successfully."
                        echo
                        free -h

                        echo
                        read -rp "Press Enter to return..."
                        ;;

                    *)
                        echo
                        echo "Operation cancelled."
                        sleep 2
                        ;;
                esac
                ;;

            4)
                clear

                echo "======================================"
                echo "             Disable Swap"
                echo "======================================"
                echo

                if ! swapon --show | grep -q .; then
                    echo "Swap is already disabled."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                echo "Current Swap:"
                free -h

                echo
                echo "Active Swap Devices:"
                swapon --show

                echo
                read -rp "Disable Swap and remove /swapfile? [y/N]: " DISABLE_CONFIRM

                case "$DISABLE_CONFIRM" in
                    y|Y|yes|YES)

                        echo
                        echo "Disabling Swap..."

                        if ! swapoff -a; then
                            echo
                            echo "Failed to disable Swap."
                            echo
                            read -rp "Press Enter to return..."
                            continue
                        fi

                        echo "Removing Swap entries from /etc/fstab..."

                        sed -i '\|^/swapfile none swap sw|d' /etc/fstab

                        if [ -f /swapfile ]; then
                            rm -f /swapfile
                        fi

                        echo
                        echo "Swap has been disabled successfully."
                        echo
                        free -h

                        echo
                        read -rp "Press Enter to return..."
                        ;;

                    *)
                        echo
                        echo "Operation cancelled."
                        sleep 2
                        ;;
                esac
                ;;

            0)
                break
                ;;

            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}
