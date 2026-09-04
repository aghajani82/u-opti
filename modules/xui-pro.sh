#!/bin/bash

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

    echo "The X-UI PRO installer will be downloaded from:"
    echo
    echo "https://raw.githubusercontent.com/aghajani82/x-ui-pro/master/x-ui-pro.sh"
    echo

    read -rp "Continue with installation? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "Installation cancelled."
            sleep 2
            return
            ;;
    esac

    echo
    echo "Starting X-UI PRO installation..."
    echo

    bash <(curl -fsSL "https://raw.githubusercontent.com/aghajani82/x-ui-pro/master/x-ui-pro.sh") -subdomain "$DOMAIN"

    echo
    echo "======================================"
    echo "       X-UI PRO installation finished"
    echo "======================================"
    echo

    read -rp "Press Enter to return to menu..."
}


show_xui_pro_menu() {
    while true; do
        clear

        echo "======================================"
        echo "         X-UI PRO Management"
        echo "======================================"
        echo
        echo "1) Install X-UI PRO"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-1]: " XUI_PRO_CHOICE

        case "$XUI_PRO_CHOICE" in
            1)
                xui_pro_install
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
