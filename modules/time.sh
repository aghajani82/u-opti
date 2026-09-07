#!/bin/bash

# U-OPTI - Time & Date Module
# v0.11.1

time_pause() {
    echo
    read -rp "Press Enter to return..."
}

time_wait_for_sync() {
    local ATTEMPT
    local STATUS

    for ATTEMPT in 1 2 3 4 5 6 7 8 9 10; do
        STATUS="$(timedatectl show --property=NTPSynchronized --value 2>/dev/null || echo no)"

        if [ "$STATUS" = "yes" ]; then
            echo "Synchronization: yes"
            return 0
        fi

        echo "Synchronization: pending (check $ATTEMPT/10)..."
        sleep 2
    done

    STATUS="$(timedatectl show --property=NTPSynchronized --value 2>/dev/null || echo no)"
    echo "Synchronization: $STATUS"
    return 1
}

show_time_menu() {
    while true; do
        clear

        echo "======================================"
        echo "            Time & Date"
        echo "======================================"
        echo
        echo "1) Current Date & Time"
        echo "2) Change Timezone"
        echo "3) NTP Status"
        echo "4) Enable Time Synchronization"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-4]: " time_choice

        case "$time_choice" in
            1)
                clear
                echo "======================================"
                echo "        Current Date & Time"
                echo "======================================"
                echo
                echo "Current Date & Time:"
                date
                echo
                echo "Timezone:"
                timedatectl show --property=Timezone --value
                echo
                echo "--------------------------------------"
                time_pause
                ;;
            2)
                clear
                echo "======================================"
                echo "           Change Timezone"
                echo "======================================"
                echo
                CURRENT_TIMEZONE=$(timedatectl show --property=Timezone --value)
                echo "Current Timezone: $CURRENT_TIMEZONE"
                echo
                echo "Examples:"
                echo "  Asia/Tehran"
                echo "  Europe/Berlin"
                echo "  America/New_York"
                echo "  UTC"
                echo
                read -rp "Enter new timezone (or 0 to go back): " NEW_TIMEZONE

                if [ "$NEW_TIMEZONE" = "0" ]; then
                    continue
                fi

                if timedatectl list-timezones | grep -Fxq "$NEW_TIMEZONE"; then
                    if timedatectl set-timezone "$NEW_TIMEZONE"; then
                        echo
                        echo "Timezone changed successfully."
                        echo "New Timezone: $(timedatectl show --property=Timezone --value)"
                    else
                        echo
                        echo "Failed to change timezone."
                    fi
                else
                    echo
                    echo "Invalid timezone."
                    echo "No changes were made."
                fi
                time_pause
                ;;
            3)
                clear
                echo "======================================"
                echo "             NTP Status"
                echo "======================================"
                echo
                timedatectl status
                echo
                echo "--------------------------------------"
                time_pause
                ;;
            4)
                clear
                echo "======================================"
                echo "      Time Synchronization"
                echo "======================================"
                echo
                echo "Press 0 to return without changing time synchronization."
                echo
                read -rp "Continue with NTP synchronization? [y/N]: " NTP_CONFIRM

                case "$NTP_CONFIRM" in
                    y|Y|yes|YES)
                        ;;
                    0|n|N|no|NO|"")
                        continue
                        ;;
                    *)
                        echo
                        echo "Operation cancelled."
                        sleep 1
                        continue
                        ;;
                esac

                echo
                echo "Enabling NTP time synchronization..."
                echo

                if timedatectl set-ntp true; then
                    echo "Time synchronization service has been enabled."
                    echo
                    echo "Waiting for the system to synchronize..."
                    echo
                    time_wait_for_sync
                    echo
                    echo "Current NTP Status:"
                    timedatectl show --property=NTPSynchronized --value
                    echo
                    echo "NTP service:"
                    timedatectl show --property=NTP --value
                else
                    echo "Failed to enable time synchronization."
                fi

                echo
                time_pause
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
