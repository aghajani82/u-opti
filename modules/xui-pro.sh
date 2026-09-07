#!/bin/bash

# U-OPTI - X-UI PRO Management
# v0.11.1

XUI_PRO_URL="https://raw.githubusercontent.com/aghajani82/x-ui-pro/master/x-ui-pro.sh"

xui_pro_install() {
    clear
    echo "======================================"
    echo "          Install X-UI PRO"
    echo "======================================"
    echo

    read -rp "Enter your domain: " DOMAIN
    echo

    if [ -z "$DOMAIN" ]; then
        echo "Error: Domain cannot be empty."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [[ ! "$DOMAIN" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$ ]]; then
        echo "Error: Invalid domain."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Domain:"
    echo "$DOMAIN"
    echo
    echo "X-UI PRO installer:"
    echo "$XUI_PRO_URL"
    echo

    read -rp "Continue with installation? [y/N]: " CONFIRM
    case "$CONFIRM" in
        y|Y|yes|YES) ;;
        *) echo; echo "Installation cancelled."; sleep 2; return ;;
    esac

    echo
    echo "Starting X-UI PRO installation..."
    echo

    bash <(curl -fsSL "$XUI_PRO_URL") -subdomain "$DOMAIN"
    local INSTALL_RESULT=$?

    echo
    echo "======================================"
    echo "       X-UI PRO installation finished"
    echo "======================================"
    echo

    if [ "$INSTALL_RESULT" -eq 0 ]; then
        echo "The installer completed successfully."
    else
        echo "The installer returned exit code: $INSTALL_RESULT"
        echo "Review the output above before continuing."
    fi

    echo
    echo "Please save any login information, panel URL,"
    echo "credentials, ports, paths, or other details shown"
    echo "above before pressing Enter."
    echo
    read -rp "Press Enter to return to X-UI PRO menu..."
}

xui_pro_uninstall() {
    clear
    echo "======================================"
    echo "         Uninstall X-UI PRO"
    echo "======================================"
    echo
    echo "This will run the X-UI PRO uninstall routine."
    echo
    read -rp "Are you sure you want to uninstall X-UI PRO? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            echo
            echo "Starting X-UI PRO uninstall..."
            echo
            bash <(curl -fsSL "$XUI_PRO_URL") -Uninstall yes
            local UNINSTALL_RESULT=$?

            echo
            echo "======================================"
            echo "       X-UI PRO uninstall finished"
            echo "======================================"
            echo

            if [ "$UNINSTALL_RESULT" -eq 0 ]; then
                echo "The uninstall routine completed."
            else
                echo "The uninstall routine returned exit code: $UNINSTALL_RESULT"
                echo "Review the output above."
            fi

            echo
            read -rp "Press Enter to return to X-UI PRO menu..."
            ;;
        *)
            echo
            echo "Uninstall cancelled."
            sleep 2
            ;;
    esac
}

show_xui_pro_menu() {
    while true; do
        clear
        echo "======================================"
        echo "         X-UI PRO Management"
        echo "======================================"
        echo
        echo "1) Install X-UI PRO"
        echo "2) Uninstall X-UI PRO"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-2]: " XUI_PRO_CHOICE
        case "$XUI_PRO_CHOICE" in
            1) xui_pro_install ;;
            2) xui_pro_uninstall ;;
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
