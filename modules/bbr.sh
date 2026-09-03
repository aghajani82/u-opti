#!/bin/bash

# U-OPTI - BBR Management Module
# v0.8.0

BBR_BACKUP_DIR="/etc/u-opti"
BBR_BACKUP_FILE="$BBR_BACKUP_DIR/bbr-backup.conf"

show_bbr_menu() {
    while true; do
        clear

        KERNEL=$(uname -r)

        CURRENT_CC=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || echo "unknown")
        AVAILABLE_CC=$(sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null || echo "unknown")
        DEFAULT_QDISC=$(sysctl -n net.core.default_qdisc 2>/dev/null || echo "unknown")

        if modinfo tcp_bbr >/dev/null 2>&1; then
            BBR_MODULE="Available"
        else
            BBR_MODULE="Not Available"
        fi

        if lsmod | grep -qw tcp_bbr; then
            BBR_LOADED="Loaded"
        else
            BBR_LOADED="Not Loaded"
        fi

        if echo "$AVAILABLE_CC" | grep -qw "bbr"; then
            BBR_AVAILABLE="Yes"
        else
            BBR_AVAILABLE="No"
        fi

        if [ "$CURRENT_CC" = "bbr" ]; then
            BBR_STATUS="Enabled"
        else
            BBR_STATUS="Disabled"
        fi

        echo "======================================"
        echo "           BBR Management"
        echo "======================================"
        echo
        echo "Kernel                  : $KERNEL"
        echo "Current Congestion      : $CURRENT_CC"
        echo "Available Algorithms    : $AVAILABLE_CC"
        echo "Default Qdisc           : $DEFAULT_QDISC"
        echo "BBR Module              : $BBR_MODULE"
        echo "BBR Module Status       : $BBR_LOADED"
        echo "BBR Available           : $BBR_AVAILABLE"
        echo "BBR Status              : $BBR_STATUS"
        echo
        echo "Actual Interface Qdiscs:"
        tc qdisc show 2>/dev/null | grep "dev " || echo "Unable to read qdisc information."

        echo
        echo "--------------------------------------"
        echo
        echo "1) BBR Status"
        echo "2) Check BBR Compatibility"
        echo "3) Enable BBR"
        echo "4) Disable BBR"
        echo "5) Load BBR Module"
        echo "6) Configure Qdisc"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-6]: " bbr_choice

        case "$bbr_choice" in

            1)
                clear

                echo "======================================"
                echo "             BBR Status"
                echo "======================================"
                echo

                echo "Kernel:"
                echo "$KERNEL"

                echo
                echo "Current Congestion Control:"
                echo "$CURRENT_CC"

                echo
                echo "Available Congestion Controls:"
                echo "$AVAILABLE_CC"

                echo
                echo "Default Qdisc:"
                echo "$DEFAULT_QDISC"

                echo
                echo "BBR Module:"
                echo "$BBR_MODULE"

                echo
                echo "BBR Module Status:"
                echo "$BBR_LOADED"

                echo
                echo "BBR Available:"
                echo "$BBR_AVAILABLE"

                echo
                echo "BBR Status:"
                echo "$BBR_STATUS"

                echo
                echo "Actual Interface Qdiscs:"
                tc qdisc show 2>/dev/null | grep "dev " || echo "Unable to read qdisc information."

                echo
                echo "--------------------------------------"
                echo
                read -rp "Press Enter to return..."
                ;;

            2)
                clear

                echo "======================================"
                echo "      BBR Compatibility Check"
                echo "======================================"
                echo

                echo "Kernel:"
                echo "$KERNEL"

                echo
                echo "Current Congestion Control:"
                echo "$CURRENT_CC"

                echo
                echo "Available Algorithms:"
                echo "$AVAILABLE_CC"

                echo
                echo "Default Qdisc:"
                echo "$DEFAULT_QDISC"

                echo
                echo "BBR Module:"
                echo "$BBR_MODULE"

                echo
                echo "BBR Module Status:"
                echo "$BBR_LOADED"

                echo
                echo "--------------------------------------"
                echo

                if [ "$BBR_MODULE" = "Available" ]; then

                    echo "BBR kernel module      : YES"

                    if [ "$BBR_LOADED" = "Loaded" ]; then
                        echo "BBR module loaded      : YES"
                    else
                        echo "BBR module loaded      : NO"
                    fi

                    if echo "$AVAILABLE_CC" | grep -qw "bbr"; then
                        echo "BBR registered         : YES"
                    else
                        echo "BBR registered         : NO"
                    fi

                    if [ "$CURRENT_CC" = "bbr" ]; then
                        echo "BBR active             : YES"
                    else
                        echo "BBR active             : NO"
                    fi

                    echo
                    echo "Recommendation:"

                    if ! echo "$AVAILABLE_CC" | grep -qw "bbr"; then
                        echo "The BBR module exists but is not loaded."
                        echo "Load the module first."
                    elif [ "$CURRENT_CC" != "bbr" ]; then
                        echo "BBR is available and can be enabled."
                    else
                        echo "BBR is already active."
                    fi

                else

                    echo "BBR kernel module      : NO"
                    echo
                    echo "Recommendation:"
                    echo "BBR is not provided by the current kernel."

                fi

                echo
                echo "Actual Interface Qdiscs:"
                tc qdisc show 2>/dev/null | grep "dev " || echo "Unable to read qdisc information."

                echo
                echo "--------------------------------------"
                echo
                read -rp "Press Enter to return..."
                ;;

            3)
                clear

                echo "======================================"
                echo "             Enable BBR"
                echo "======================================"
                echo

                if ! modinfo tcp_bbr >/dev/null 2>&1; then
                    echo "BBR module is not available on this kernel."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                if ! lsmod | grep -qw tcp_bbr; then
                    echo "BBR module is not loaded."
                    echo
                    echo "Loading tcp_bbr..."
                    echo

                    if ! modprobe tcp_bbr; then
                        echo "Failed to load tcp_bbr."
                        echo
                        read -rp "Press Enter to return..."
                        continue
                    fi
                fi

                AVAILABLE_CC=$(sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null || echo "")

                if ! echo "$AVAILABLE_CC" | grep -qw "bbr"; then
                    echo "BBR is still not available after loading the module."
                    echo
                    echo "No changes were made."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                CURRENT_CC=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || echo "")
                CURRENT_QDISC=$(sysctl -n net.core.default_qdisc 2>/dev/null || echo "")

                echo "Current Congestion Control : $CURRENT_CC"
                echo "Current Default Qdisc      : $CURRENT_QDISC"
                echo

                echo "This will:"
                echo "  - Enable BBR"
                echo "  - Keep the current default qdisc"
                echo "  - Save a backup of current settings"
                echo "  - Make BBR module loading persistent"
                echo

                read -rp "Continue? [y/N]: " ENABLE_CONFIRM

                case "$ENABLE_CONFIRM" in

                    y|Y|yes|YES)

                        mkdir -p "$BBR_BACKUP_DIR"

                        cat > "$BBR_BACKUP_FILE" <<EOF
CURRENT_CC=$CURRENT_CC
CURRENT_QDISC=$CURRENT_QDISC
EOF

                        echo
                        echo "Backup saved to:"
                        echo "$BBR_BACKUP_FILE"

                        if ! sysctl -w net.ipv4.tcp_congestion_control=bbr; then
                            echo
                            echo "Failed to enable BBR."
                            echo
                            read -rp "Press Enter to return..."
                            continue
                        fi

                        if grep -q "^net.ipv4.tcp_congestion_control=" /etc/sysctl.conf; then
                            sed -i \
                                's/^net.ipv4.tcp_congestion_control=.*/net.ipv4.tcp_congestion_control=bbr/' \
                                /etc/sysctl.conf
                        else
                            echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
                        fi

                        mkdir -p /etc/modules-load.d
                        echo "tcp_bbr" > /etc/modules-load.d/tcp_bbr.conf

                        echo
                        echo "BBR has been enabled successfully."
                        echo "BBR module loading is now persistent."
                        echo
                        echo "Current Congestion Control:"
                        sysctl -n net.ipv4.tcp_congestion_control

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
                echo "             Disable BBR"
                echo "======================================"
                echo

                CURRENT_CC=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || echo "")
                CURRENT_QDISC=$(sysctl -n net.core.default_qdisc 2>/dev/null || echo "")

                if [ "$CURRENT_CC" != "bbr" ]; then
                    echo "BBR is not currently active."
                    echo
                    echo "Current Congestion Control: $CURRENT_CC"
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                echo "Current Congestion Control : $CURRENT_CC"
                echo "Current Default Qdisc      : $CURRENT_QDISC"
                echo

                echo "This will:"
                echo "  - Disable BBR"
                echo "  - Restore the previous congestion control if backup exists"
                echo "  - Remove persistent BBR module loading"
                echo

                read -rp "Continue? [y/N]: " DISABLE_CONFIRM

                case "$DISABLE_CONFIRM" in

                    y|Y|yes|YES)

                        RESTORE_CC="cubic"

                        if [ -f "$BBR_BACKUP_FILE" ]; then
                            BACKUP_CC=$(grep "^CURRENT_CC=" "$BBR_BACKUP_FILE" 2>/dev/null | cut -d= -f2-)

                            if [ -n "$BACKUP_CC" ]; then
                                RESTORE_CC="$BACKUP_CC"
                            fi
                        fi

                        if ! sysctl -w "net.ipv4.tcp_congestion_control=$RESTORE_CC"; then
                            echo
                            echo "Failed to restore congestion control."
                            echo
                            read -rp "Press Enter to return..."
                            continue
                        fi

                        if grep -q "^net.ipv4.tcp_congestion_control=" /etc/sysctl.conf; then
                            sed -i \
                                "s/^net.ipv4.tcp_congestion_control=.*/net.ipv4.tcp_congestion_control=$RESTORE_CC/" \
                                /etc/sysctl.conf
                        fi

                        rm -f /etc/modules-load.d/tcp_bbr.conf

                        echo
                        echo "BBR has been disabled."
                        echo "Restored Congestion Control: $RESTORE_CC"
                        echo "Persistent BBR module loading removed."
                        echo

                        if [ -f "$BBR_BACKUP_FILE" ]; then
                            echo "Backup retained at:"
                            echo "$BBR_BACKUP_FILE"
                        fi

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

            5)
                clear

                echo "======================================"
                echo "          Load BBR Module"
                echo "======================================"
                echo

                if ! modinfo tcp_bbr >/dev/null 2>&1; then
                    echo "BBR module is not available on this kernel."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                if lsmod | grep -qw tcp_bbr; then
                    echo "BBR module is already loaded."
                else
                    echo "Loading tcp_bbr..."
                    echo

                    if modprobe tcp_bbr; then
                        echo "BBR module loaded successfully."
                    else
                        echo "Failed to load BBR module."
                    fi
                fi

                echo
                echo "Available Congestion Controls:"
                sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null || echo "Unable to read available algorithms."

                echo
                read -rp "Press Enter to return..."
                ;;

            6)
                clear

                echo "======================================"
                echo "           Configure Qdisc"
                echo "======================================"
                echo

                CURRENT_QDISC=$(sysctl -n net.core.default_qdisc 2>/dev/null || echo "unknown")

                echo "Current Default Qdisc: $CURRENT_QDISC"
                echo
                echo "Actual Interface Qdiscs:"
                tc qdisc show 2>/dev/null | grep "dev " || echo "Unable to read qdisc information."

                echo
                echo "Available Qdisc options:"
                echo "  fq"
                echo "  fq_codel"
                echo "  pfifo_fast"
                echo
                echo "Use the value 'keep' to keep the current qdisc."
                echo

                read -rp "Enter new default qdisc: " NEW_QDISC

                if [ "$NEW_QDISC" = "keep" ]; then
                    echo
                    echo "No changes were made."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                if [ -z "$NEW_QDISC" ]; then
                    echo
                    echo "Invalid qdisc."
                    echo
                    read -rp "Press Enter to return..."
                    continue
                fi

                case "$NEW_QDISC" in
                    fq|fq_codel|pfifo_fast)
                        ;;
                    *)
                        echo
                        echo "Unsupported qdisc."
                        echo "Allowed values: fq, fq_codel, pfifo_fast"
                        echo
                        read -rp "Press Enter to return..."
                        continue
                        ;;
                esac

                echo
                echo "Changing default qdisc to: $NEW_QDISC"

                if sysctl -w "net.core.default_qdisc=$NEW_QDISC"; then

                    if grep -q "^net.core.default_qdisc=" /etc/sysctl.conf; then
                        sed -i \
                            "s/^net.core.default_qdisc=.*/net.core.default_qdisc=$NEW_QDISC/" \
                            /etc/sysctl.conf
                    else
                        echo "net.core.default_qdisc=$NEW_QDISC" >> /etc/sysctl.conf
                    fi

                    echo
                    echo "Default qdisc changed successfully."
                    echo "Current Default Qdisc:"
                    sysctl -n net.core.default_qdisc

                else

                    echo
                    echo "Failed to change default qdisc."

                fi

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
