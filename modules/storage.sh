#!/bin/bash

# U-OPTI - Storage Management Module
# v0.8.0

show_storage_menu() {
    while true; do
        clear

        echo "======================================"
        echo "        Storage Management"
        echo "======================================"
        echo

        echo "1) Disk Information"
        echo "2) Find Large Files (>500MB)"
        echo "3) Find Large Directories"
        echo "4) Clean APT Cache"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-4]: " storage_choice

        case "$storage_choice" in

            1)
                clear

                echo "======================================"
                echo "          Disk Information"
                echo "======================================"
                echo

                echo "Filesystem Usage:"
                df -h

                echo
                echo "--------------------------------------"
                echo
                read -rp "Press Enter to return..."
                ;;

            2)
                clear

                echo "======================================"
                echo "       Find Large Files (>500MB)"
                echo "======================================"
                echo

                echo "Searching for files larger than 500MB..."
                echo "This may take some time."
                echo

                find / -type f -size +500M \
                    -not -path "/proc/*" \
                    -not -path "/sys/*" \
                    -not -path "/dev/*" \
                    -not -path "/run/*" \
                    -not -path "/snap/*" \
                    -print 2>/dev/null

                echo
                echo "--------------------------------------"
                echo
                read -rp "Press Enter to return..."
                ;;

            3)
                clear

                echo "======================================"
                echo "       Find Large Directories"
                echo "======================================"
                echo

                echo "Top directories by size:"
                echo

                du -xh --max-depth=1 / \
                    --exclude=/proc \
                    --exclude=/sys \
                    --exclude=/dev \
                    --exclude=/run \
                    --exclude=/snap \
                    2>/dev/null | sort -hr | head -20

                echo
                echo "--------------------------------------"
                echo
                read -rp "Press Enter to return..."
                ;;

            4)
                clear

                echo "======================================"
                echo "           Clean APT Cache"
                echo "======================================"
                echo

                CACHE_SIZE=$(du -sh /var/cache/apt 2>/dev/null | awk '{print $1}')

                echo "Current APT cache size: ${CACHE_SIZE:-Unknown}"
                echo

                read -rp "Clean APT cache? [y/N]: " CLEAN_CONFIRM

                case "$CLEAN_CONFIRM" in
                    y|Y|yes|YES)

                        echo
                        echo "Cleaning APT cache..."
                        echo

                        if apt-get clean; then
                            echo "APT cache cleaned successfully."
                        else
                            echo "Failed to clean APT cache."
                        fi

                        echo
                        NEW_CACHE_SIZE=$(du -sh /var/cache/apt 2>/dev/null | awk '{print $1}')
                        echo "Current APT cache size: ${NEW_CACHE_SIZE:-Unknown}"
                        ;;

                    *)
                        echo
                        echo "Operation cancelled."
                        ;;
                esac

                echo
                read -rp "Press Enter to return..."
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
