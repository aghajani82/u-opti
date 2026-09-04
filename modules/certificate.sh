#!/usr/bin/env bash

# ==========================================
# U-OPTI - Certificate Management
# ==========================================

CERTBOT_BIN=""

get_certbot_path() {
    if command -v certbot >/dev/null 2>&1; then
        CERTBOT_BIN="$(command -v certbot)"
        return 0
    fi

    CERTBOT_BIN=""
    return 1
}

pause_screen() {
    echo
    read -r -p "Press Enter to return..." _
}

validate_domain() {
    local domain="$1"

    if [[ ! "$domain" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$ ]]; then
        return 1
    fi

    return 0
}

check_certbot() {
    if ! get_certbot_path; then
        echo
        echo "Error: Certbot is not installed."
        echo "Install Certbot first."
        return 1
    fi

    return 0
}

install_certbot() {
    clear

    echo "======================================"
    echo "          Install Certbot"
    echo "======================================"
    echo

    if get_certbot_path; then
        echo "Certbot is already installed."
        echo
        "$CERTBOT_BIN" --version
        pause_screen
        return 0
    fi

    echo "Installing Certbot..."
    echo
    echo "This will not stop or restart Nginx."
    echo

    if ! apt update; then
        echo
        echo "Error: Failed to update APT package lists."
        pause_screen
        return 1
    fi

    if ! apt install -y certbot python3-certbot-nginx; then
        echo
        echo "Error: Failed to install Certbot."
        pause_screen
        return 1
    fi

    if ! get_certbot_path; then
        echo
        echo "Error: Certbot installation could not be verified."
        pause_screen
        return 1
    fi

    echo
    echo "Certbot installed successfully."
    "$CERTBOT_BIN" --version

    pause_screen
    return 0
}

certificate_status() {
    clear

    echo "======================================"
    echo "       Certificate Status"
    echo "======================================"
    echo

    if ! check_certbot; then
        pause_screen
        return 1
    fi

    local live_dir="/etc/letsencrypt/live"
    local found=0

    if [[ ! -d "$live_dir" ]]; then
        echo "No Let's Encrypt certificates found."
        pause_screen
        return 0
    fi

    for cert_dir in "$live_dir"/*; do
        [[ -d "$cert_dir" ]] || continue
        [[ -f "$cert_dir/cert.pem" ]] || continue

        found=1

        local domain
        local expiry_raw
        local expiry_date
        local expiry_epoch
        local now_epoch
        local days_left
        local status

        domain="$(basename "$cert_dir")"

        expiry_raw="$(
            openssl x509 \
                -in "$cert_dir/cert.pem" \
                -noout \
                -enddate 2>/dev/null
        )"

        expiry_raw="${expiry_raw#notAfter=}"

        if [[ -z "$expiry_raw" ]]; then
            status="Unknown"
            expiry_date="Unknown"
            days_left="Unknown"
        else
            expiry_date="$(date -d "$expiry_raw" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "Unknown")"
            expiry_epoch="$(date -d "$expiry_raw" '+%s' 2>/dev/null || echo "")"
            now_epoch="$(date '+%s')"

            if [[ -n "$expiry_epoch" && "$expiry_epoch" =~ ^[0-9]+$ ]]; then
                days_left=$(( (expiry_epoch - now_epoch) / 86400 ))

                if (( days_left < 0 )); then
                    status="Expired"
                elif (( days_left <= 7 )); then
                    status="Expiring Soon"
                else
                    status="Valid"
                fi
            else
                status="Unknown"
                days_left="Unknown"
            fi
        fi

        echo "Domain    : $domain"
        echo "Status    : $status"
        echo "Expires   : $expiry_date"
        echo "Days Left : $days_left"
        echo "--------------------------------------"
    done

    if [[ "$found" -eq 0 ]]; then
        echo "No Let's Encrypt certificates found."
    fi

    pause_screen
    return 0
}

issue_certificate() {
    clear

    echo "======================================"
    echo "        Issue Certificate"
    echo "======================================"
    echo

    if ! check_certbot; then
        pause_screen
        return 1
    fi

    if ! command -v nginx >/dev/null 2>&1; then
        echo "Error: Nginx is not installed."
        echo "Install and configure Nginx first."
        pause_screen
        return 1
    fi

    if ! systemctl is-active --quiet nginx; then
        echo "Error: Nginx is not running."
        echo "Start Nginx before issuing a certificate."
        pause_screen
        return 1
    fi

    local domain

    read -r -p "Enter your domain: " domain

    if [[ -z "$domain" ]]; then
        echo
        echo "Error: Domain cannot be empty."
        pause_screen
        return 1
    fi

    if ! validate_domain "$domain"; then
        echo
        echo "Error: Invalid domain format."
        pause_screen
        return 1
    fi

    if [[ -f "/etc/letsencrypt/live/$domain/cert.pem" ]]; then
        echo
        echo "Error: A certificate for '$domain' already exists."
        echo "Use Certificate Status or Renew Certificates."
        pause_screen
        return 1
    fi

    echo
    echo "Domain:"
    echo "$domain"
    echo
    echo "Certificate method:"
    echo "Certbot + Nginx"
    echo
    echo "Nginx will remain running during the process."
    echo
    read -r -p "Continue with certificate issuance? [y/N]: " confirm

    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo
        echo "Certificate issuance cancelled."
        pause_screen
        return 0
    fi

    echo
    echo "Requesting certificate from Let's Encrypt..."
    echo

    if "$CERTBOT_BIN" --nginx \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        --redirect \
        -d "$domain"; then

        echo
        echo "Certificate issued successfully."
        echo

        if systemctl reload nginx; then
            echo "Nginx reloaded successfully."
        else
            echo "Warning: Certificate was issued, but Nginx reload failed."
        fi

        echo
        echo "Certificate:"
        echo "/etc/letsencrypt/live/$domain/"
    else
        echo
        echo "Error: Failed to issue certificate."
        echo
        echo "Make sure:"
        echo "1. DNS for the domain points to this server."
        echo "2. Ports 80 and 443 are reachable."
        echo "3. Nginx has a valid configuration."
        echo "4. The domain is not blocked by another service."

        pause_screen
        return 1
    fi

    pause_screen
    return 0
}

renew_certificates() {
    clear

    echo "======================================"
    echo "       Renew Certificates"
    echo "======================================"
    echo

    if ! check_certbot; then
        pause_screen
        return 1
    fi

    echo "Checking and renewing certificates..."
    echo

    if "$CERTBOT_BIN" renew; then
        echo
        echo "Certificate renewal process completed."

        if systemctl reload nginx; then
            echo "Nginx reloaded successfully."
        else
            echo "Warning: Nginx reload failed."
        fi
    else
        echo
        echo "Error: Certificate renewal failed."
        pause_screen
        return 1
    fi

    pause_screen
    return 0
}

remove_certificate() {
    clear

    echo "======================================"
    echo "        Remove Certificate"
    echo "======================================"
    echo

    if ! check_certbot; then
        pause_screen
        return 1
    fi

    local domain

    read -r -p "Enter domain to remove: " domain

    if [[ -z "$domain" ]]; then
        echo
        echo "Error: Domain cannot be empty."
        pause_screen
        return 1
    fi

    if ! validate_domain "$domain"; then
        echo
        echo "Error: Invalid domain format."
        pause_screen
        return 1
    fi

    if [[ ! -f "/etc/letsencrypt/live/$domain/cert.pem" ]]; then
        echo
        echo "Error: No certificate found for '$domain'."
        pause_screen
        return 1
    fi

    echo
    echo "Certificate:"
    echo "$domain"
    echo
    echo "WARNING: This will permanently remove the certificate"
    echo "from Certbot's configuration."
    echo

    read -r -p "Continue with removal? [y/N]: " confirm

    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo
        echo "Certificate removal cancelled."
        pause_screen
        return 0
    fi

    echo

    if "$CERTBOT_BIN" delete \
        --cert-name "$domain" \
        --non-interactive; then

        echo
        echo "Certificate removed successfully."

        if systemctl reload nginx; then
            echo "Nginx reloaded successfully."
        else
            echo "Warning: Nginx reload failed."
        fi
    else
        echo
        echo "Error: Failed to remove certificate."
        pause_screen
        return 1
    fi

    pause_screen
    return 0
}

show_certificate_menu() {
    while true; do
        clear

        echo "======================================"
        echo "       Certificate Management"
        echo "======================================"
        echo
        echo "1) Install Certbot"
        echo "2) Certificate Status"
        echo "3) Issue Certificate"
        echo "4) Renew Certificates"
        echo "5) Remove Certificate"
        echo
        echo "0) Back"
        echo

        read -r -p "Please enter your selection [0-5]: " choice

        case "$choice" in
            1)
                install_certbot
                ;;
            2)
                certificate_status
                ;;
            3)
                issue_certificate
                ;;
            4)
                renew_certificates
                ;;
            5)
                remove_certificate
                ;;
            0)
                return 0
                ;;
            *)
                echo
                echo "Invalid selection."
                sleep 1
                ;;
        esac
    done
}
