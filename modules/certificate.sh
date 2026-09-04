#!/usr/bin/env bash

# ==========================================
# U-OPTI - Certificate Management
# ==========================================

CERTBOT_BIN=""
ACME_WEBROOT="/var/www/u-opti-acme"
ACME_CONF_DIR="/etc/nginx/conf.d"
ACME_CONF_PREFIX="u-opti-acme"

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

    if ! apt update; then
        echo
        echo "Error: Failed to update APT package lists."
        pause_screen
        return 1
    fi

    if ! apt install -y certbot; then
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

validate_nginx() {
    if ! command -v nginx >/dev/null 2>&1; then
        echo "Error: Nginx is not installed."
        echo "Install Nginx first."
        return 1
    fi

    if ! systemctl is-active --quiet nginx; then
        echo "Error: Nginx is not running."
        echo "Start Nginx before issuing a certificate."
        return 1
    fi

    if ! nginx -t >/dev/null 2>&1; then
        echo "Error: Existing Nginx configuration is invalid."
        echo "Fix the Nginx configuration before continuing."
        return 1
    fi

    return 0
}

domain_exists_in_nginx() {
    local domain="$1"

    nginx -T 2>/dev/null |
        grep -Eq \
        "server_name[[:space:]]+[^;]*(^|[[:space:]])${domain}([[:space:]]|;)"
}

get_acme_conf_path() {
    local domain="$1"

    echo "$ACME_CONF_DIR/${ACME_CONF_PREFIX}-${domain}.conf"
}

prepare_acme_webroot() {
    local domain="$1"
    local conf_path="$2"
    local previous_content=""
    local had_previous=0

    if [[ -f "$conf_path" ]]; then
        had_previous=1
        previous_content="$(cat "$conf_path")"
    fi

    if ! mkdir -p "$ACME_WEBROOT/.well-known/acme-challenge"; then
        echo "Error: Failed to create ACME webroot."
        return 1
    fi

    chmod 755 "$ACME_WEBROOT"
    chmod 755 "$ACME_WEBROOT/.well-known"
    chmod 755 "$ACME_WEBROOT/.well-known/acme-challenge"

    cat > "$conf_path" <<EOF
# ==========================================
# U-OPTI - Let's Encrypt ACME Challenge
# Domain: $domain
# ==========================================

server {
    listen 80;
    listen [::]:80;

    server_name $domain;

    location ^~ /.well-known/acme-challenge/ {
        root $ACME_WEBROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 404;
    }
}
EOF

    if ! nginx -t >/dev/null 2>&1; then
        echo "Error: Failed to validate ACME Nginx configuration."

        if [[ "$had_previous" -eq 1 ]]; then
            printf '%s\n' "$previous_content" > "$conf_path"
        else
            rm -f "$conf_path"
        fi

        nginx -t >/dev/null 2>&1 || true

        return 1
    fi

    if ! systemctl reload nginx; then
        echo "Error: Failed to reload Nginx after ACME configuration."

        if [[ "$had_previous" -eq 1 ]]; then
            printf '%s\n' "$previous_content" > "$conf_path"
        else
            rm -f "$conf_path"
        fi

        nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true

        return 1
    fi

    return 0
}

test_acme_webroot() {
    local domain="$1"
    local test_file="$ACME_WEBROOT/.well-known/acme-challenge/u-opti-test"
    local response=""

    echo "Testing ACME challenge path..."
    echo

    if ! printf '%s\n' "u-opti-test" > "$test_file"; then
        echo "Error: Failed to create ACME test file."
        return 1
    fi

    response="$(
        curl -fsS \
            --max-time 10 \
            -H "Host: $domain" \
            "http://127.0.0.1/.well-known/acme-challenge/u-opti-test" \
            2>/dev/null || true
    )"

    rm -f "$test_file"

    if [[ "$response" != "u-opti-test" ]]; then
        echo
        echo "Error: ACME challenge path is not reachable from Nginx."
        echo
        echo "Expected response:"
        echo "u-opti-test"
        echo
        echo "Received:"
        echo "${response:-<no response>}"

        return 1
    fi

    echo "ACME challenge path is reachable."
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
    local cert_dir

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
            expiry_date="$(
                date -d "$expiry_raw" '+%Y-%m-%d %H:%M:%S' 2>/dev/null \
                || echo "Unknown"
            )"

            expiry_epoch="$(
                date -d "$expiry_raw" '+%s' 2>/dev/null \
                || echo ""
            )"

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

    if ! validate_nginx; then
        pause_screen
        return 1
    fi

    local domain
    local conf_path

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

    if domain_exists_in_nginx "$domain"; then
        echo
        echo "Error: The domain '$domain' is already configured in Nginx."
        echo
        echo "U-OPTI will not modify an existing Nginx site configuration."
        echo "Use that site's existing ACME/webroot configuration instead."
        pause_screen
        return 1
    fi

    conf_path="$(get_acme_conf_path "$domain")"

    echo
    echo "Domain:"
    echo "$domain"
    echo
    echo "Certificate method:"
    echo "Certbot + ACME Webroot"
    echo
    echo "Nginx site configuration will not be modified by Certbot."
    echo
    echo "U-OPTI will create a dedicated ACME server"
    echo "for this domain on port 80."
    echo

    read -r -p "Continue with certificate issuance? [y/N]: " confirm

    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo
        echo "Certificate issuance cancelled."
        pause_screen
        return 0
    fi

    if ! prepare_acme_webroot "$domain" "$conf_path"; then
        pause_screen
        return 1
    fi

    echo

    if ! test_acme_webroot "$domain"; then
        echo
        echo "Make sure the Nginx ACME configuration is active."
        echo
        echo "ACME configuration:"
        echo "$conf_path"

        pause_screen
        return 1
    fi

    echo
    echo "Requesting certificate from Let's Encrypt..."
    echo

    if "$CERTBOT_BIN" certonly \
        --webroot \
        -w "$ACME_WEBROOT" \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        --cert-name "$domain" \
        -d "$domain"; then

        echo
        echo "Certificate issued successfully."
        echo
        echo "Certificate:"
        echo "/etc/letsencrypt/live/$domain/fullchain.pem"
        echo
        echo "Private Key:"
        echo "/etc/letsencrypt/live/$domain/privkey.pem"
        echo
        echo "Nginx site configuration was not modified by Certbot."
        echo "ACME configuration remains available for future renewal."
    else
        echo
        echo "Error: Failed to issue certificate."
        echo
        echo "The ACME Nginx configuration has been kept"
        echo "so the certificate can be retried without rebuilding it."
        echo
        echo "ACME configuration:"
        echo "$conf_path"

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
        echo "U-OPTI did not modify Nginx site configuration."
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
    local conf_path

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
    echo "Nginx site configuration will not be modified."
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

        conf_path="$(get_acme_conf_path "$domain")"

        if [[ -f "$conf_path" ]]; then
            rm -f "$conf_path"

            if nginx -t >/dev/null 2>&1; then
                systemctl reload nginx >/dev/null 2>&1
            else
                echo
                echo "Warning: Nginx configuration test failed after"
                echo "removing the U-OPTI ACME configuration."
            fi
        fi

        echo "U-OPTI ACME configuration removed."
        echo "Nginx site configuration was not modified."
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
