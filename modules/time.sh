#!/bin/bash

# U-OPTI - Time & Date Module
# v0.8.0

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
                echo
                read -rp "Press Enter to return..."
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

                read -rp "Enter new timezone: " NEW_TIMEZONE

                if timedatectl list-timezones | grep -Fxq "$NEW_TIMEZONE"; then
                    timedatectl set-timezone "$NEW_TIMEZONE"

                    echo
                    echo "Timezone changed successfully."
                    echo "New Timezone: $(timedatectl show --property=Timezone --value)"
                else
                    echo
                    echo "Invalid timezone."
                    echo "No changes were made."
                fi

                echo
                read -rp "Press Enter to return..."
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
                echo
                read -rp "Press Enter to return..."
                ;;

            4)
                clear

                echo "======================================"
                echo "      Time Synchronization"
                echo "======================================"
                echo

                echo "Enabling NTP time synchronization..."

                if timedatectl set-ntp true; then
                    echo
                    echo "Time synchronization has been enabled."
                else
                    echo
                    echo "Failed to enable time synchronization."
                fi

                echo
                echo "Current NTP Status:"
                timedatectl show --property=NTPSynchronized --value

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
