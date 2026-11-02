#!/bin/bash
# U-OPTI - System Optimization > Security Monitoring
# Opt-in; reads host and existing Xray logs, never changes active services.
u_opti_security_monitor_menu() {
    local helper="${MODULES_PATH}/security-monitor.py" choice answer report
    while true; do
        clear
        echo "======================================"
        echo "         Security Monitoring"
        echo "======================================"
        echo
        echo "1) Install / Enable Daily Monitoring"
        echo "2) Run Security Check Now"
        echo "3) View Latest Report"
        echo "4) List Saved Reports"
        echo "5) Open Report by Filename"
        echo "6) Show Last 10 Days (Redacted Indicators)"
        echo "7) Monitoring Status"
        echo
        echo "0) Back"
        echo
        IFS= read -r -p "Please enter your selection [0-7]: " choice || return
        case "$choice" in
            0) return ;;
            1|2|3|4|5|6|7)
                if [ ! -f "$helper" ] || [ -L "$helper" ]; then
                    echo "HOLD: Security monitor module is missing or unsafe."
                    echo "Use Update U-OPTI to restore the complete module set."
                elif ! command -v python3 >/dev/null 2>&1; then
                    echo "HOLD: Python3 is required."
                else
                    case "$choice" in
                        1)
                            echo
                            echo "Installs a local DAILY security report and 10-day Xray archive retention."
                            echo "Existing Xray access logging must already be enabled in 3x-ui."
                            echo "No firewall, Nginx, Docker, or Xray settings will be changed."
                            IFS= read -r -p "Install / enable? [y/N]: " answer
                            case "$answer" in
                                y|Y|yes|YES) python3 -B "$helper" install ;;
                                *) echo "Cancelled. No changes made." ;;
                            esac
                            ;;
                        2) python3 -B "$helper" run ;;
                        3) python3 -B "$helper" latest ;;
                        4) python3 -B "$helper" list ;;
                        5)
                            IFS= read -r -p "Report filename (YYYYMMDDTHHMMSSZ.txt): " report
                            python3 -B "$helper" show "$report"
                            ;;
                        6) python3 -B "$helper" history ;;
                        7) python3 -B "$helper" status ;;
                    esac
                fi
                echo
                IFS= read -r -p "Press Enter to return..." answer
                ;;
            *) echo "Invalid selection."; sleep 1 ;;
        esac
    done
}
