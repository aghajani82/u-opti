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
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-2]: " swap_choice

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
                    echo "No changes were made."
                    echo
                    read -rp "Press Enter to return..."
                else
                    read -rp "Enter Swap size (e.g. 1G, 2G, 4G): " SWAP_SIZE

                    if [[ ! "$SWAP_SIZE" =~ ^[0-9]+[MG]$ ]]; then
                        echo
                        echo "Invalid size."
                        echo "Use formats such as: 1G, 2G, 512M"
                        echo
                        read -rp "Press Enter to return..."
                        continue
                    fi

                    echo
                    echo "Creating ${SWAP_SIZE} swap file..."
                    echo

                    if [ -e /swapfile ]; then
                        echo "A /swapfile already exists."
                        echo
                        echo "No changes were made."
                        echo
                        read -rp "Press Enter to return..."
                        continue
                    fi

                    if fallocate -l "$SWAP_SIZE" /swapfile 2>/dev/null; then
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
                    else
                        echo "Failed to create swap."
                        rm -f /swapfile
                    fi

                    echo
                    read -rp "Press Enter to return..."
                fi
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
