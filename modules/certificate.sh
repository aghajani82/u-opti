#!/bin/bash

certificate_validate_domain() {
    local domain="$1"
    [[ "$domain" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$ ]]
}

certificate_require_certbot() {
    if ! command -v certbot >/dev/null 2>&1; then
        echo "Error: Certbot is not installed."
        echo "Install Certbot first or use X-UI PRO installation."
        return 1
    fi
    return 0
}

certificate_show_status() {
    clear
    echo "======================================"
    echo "       Certificate Status"
    echo "======================================"
    echo

    certificate_require_certbot || { echo; read -rp "Press Enter to return..."; return; }

    local found=false cert_dir domain expiry expiry_epoch now_epoch days_left status expiry_date
    shopt -s nullglob
    for cert_dir in /etc/letsencrypt/live/*; do
        [ -d "$cert_dir" ] || continue
        [ -f "$cert_dir/cert.pem" ] || continue
        found=true
        domain=$(basename "$cert_dir")
        expiry=$(openssl x509 -enddate -noout -in "$cert_dir/cert.pem" 2>/dev/null | cut -d= -f2-)
        if [ -z "$expiry" ]; then
            echo "Domain: $domain"
            echo "Status: Unable to read certificate"
            echo
            continue
        fi
        expiry_epoch=$(date -d "$expiry" +%s 2>/dev/null || echo 0)
        now_epoch=$(date +%s)
        if [ "$expiry_epoch" -gt 0 ]; then
            days_left=$(( (expiry_epoch - now_epoch) / 86400 ))
            if [ "$days_left" -lt 0 ]; then status="EXPIRED"; else status="VALID"; fi
            expiry_date=$(date -d "$expiry" '+%Y-%m-%d %H:%M:%S')
            echo "Domain:    $domain"
            echo "Status:    $status"
            echo "Expires:   $expiry_date"
            echo "Days Left: $days_left"
        else
            echo "Domain:    $domain"
            echo "Status:    Unable to determine expiry"
        fi
        echo
    done
    shopt -u nullglob

    [ "$found" = "false" ] && echo "No Let's Encrypt certificates were found." && echo
    read -rp "Press Enter to return..."
}

certificate_issue() {
    clear
    echo "======================================"
    echo "        Issue Certificate"
    echo "======================================"
    echo

    certificate_require_certbot || { echo; read -rp "Press Enter to return..."; return; }

    read -rp "Enter your domain: " DOMAIN
    echo
    if [ -z "$DOMAIN" ]; then echo "Error: Domain cannot be empty."; echo; read -rp "Press Enter to return..."; return; fi
    if ! certificate_validate_domain "$DOMAIN"; then echo "Error: Invalid domain."; echo; read -rp "Press Enter to return..."; return; fi

    if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
        echo "A certificate already exists for this domain."
        echo
        echo "Use Certificate Status to inspect it or Renew Certificates to renew it."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    local nginx_was_active=false port80_owner cert_status=0
    port80_owner=$(ss -ltnp 'sport = :80' 2>/dev/null || true)
    if echo "$port80_owner" | grep -q 'users:(.*nginx'; then
        nginx_was_active=true
        echo "Nginx is using port 80."
        echo "Nginx will be stopped temporarily for certificate issuance."
        echo
    elif echo "$port80_owner" | grep -q 'LISTEN'; then
        echo "Error: Port 80 is already in use by another service."
        echo
        echo "$port80_owner"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    read -rp "Issue a Let's Encrypt certificate for $DOMAIN? [y/N]: " CONFIRM
    case "$CONFIRM" in y|Y|yes|YES) ;; *) echo; echo "Certificate issuance cancelled."; sleep 2; return ;; esac

    if [ "$nginx_was_active" = "true" ]; then
        echo
        echo "Stopping Nginx..."
        if ! systemctl stop nginx; then
            echo "Error: Failed to stop Nginx."
            echo
            read -rp "Press Enter to return..."
            return
        fi
    fi

    echo
    echo "Requesting Let's Encrypt certificate..."
    echo

    certbot certonly \
        --standalone \
        --preferred-challenges http \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        --cert-name "$DOMAIN" \
        -d "$DOMAIN" || cert_status=$?

    if [ "$nginx_was_active" = "true" ]; then
        echo
        echo "Starting Nginx..."
        if ! systemctl start nginx; then
            echo "Warning: Nginx could not be started automatically."
            echo "Check the Nginx service manually."
        fi
    fi

    echo
    if [ "$cert_status" -eq 0 ] && [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
        echo "Certificate issued successfully."
        echo
        echo "Certificate:"
        echo "/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
        echo
        echo "Private Key:"
        echo "/etc/letsencrypt/live/$DOMAIN/privkey.pem"
    else
        echo "Certificate issuance failed."
        echo "Certbot exit code: $cert_status"
    fi
    echo
    read -rp "Press Enter to return..."
}

certificate_renew() {
    clear
    echo "======================================"
    echo "        Renew Certificates"
    echo "======================================"
    echo
    certificate_require_certbot || { echo; read -rp "Press Enter to return..."; return; }
    echo "Running Certbot renewal..."
    echo
    if certbot renew; then
        echo
        echo "Certificate renewal process completed successfully."
    else
        echo
        echo "Certificate renewal process reported an error."
    fi
    echo
    read -rp "Press Enter to return..."
}

certificate_remove() {
    clear
    echo "======================================"
    echo "         Remove Certificate"
    echo "======================================"
    echo
    certificate_require_certbot || { echo; read -rp "Press Enter to return..."; return; }
    read -rp "Enter the certificate domain: " DOMAIN
    echo
    if [ -z "$DOMAIN" ]; then echo "Error: Domain cannot be empty."; echo; read -rp "Press Enter to return..."; return; fi
    if ! certificate_validate_domain "$DOMAIN"; then echo "Error: Invalid domain."; echo; read -rp "Press Enter to return..."; return; fi
    if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
        echo "No Let's Encrypt certificate directory was found for:"
        echo "$DOMAIN"
        echo
        read -rp "Press Enter to return..."
        return
    fi
    echo "Certificate:"
    echo "$DOMAIN"
    echo
    read -rp "Are you sure you want to remove this certificate? [y/N]: " CONFIRM
    case "$CONFIRM" in y|Y|yes|YES) ;; *) echo; echo "Certificate removal cancelled."; sleep 2; return ;; esac
    echo
    echo "Removing certificate..."
    if certbot delete --cert-name "$DOMAIN"; then
        echo
        echo "Certificate removed successfully."
    else
        echo
        echo "Certificate removal failed."
    fi
    echo
    read -rp "Press Enter to return..."
}

show_certificate_menu() {
    while true; do
        clear
        echo "======================================"
        echo "       Certificate Management"
        echo "======================================"
        echo
        echo "1) Certificate Status"
        echo "2) Issue Certificate"
        echo "3) Renew Certificates"
        echo "4) Remove Certificate"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-4]: " CERT_CHOICE
        case "$CERT_CHOICE" in
            1) certificate_show_status ;;
            2) certificate_issue ;;
            3) certificate_renew ;;
            4) certificate_remove ;;
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
