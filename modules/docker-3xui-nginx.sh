#!/usr/bin/env bash

# U-OPTI - 3x-UI Docker Nginx / SSL Integration
# v0.13.0
#
# This module configures public HTTPS access for a Sanaei 3x-UI Docker
# instance managed by docker-3xui.sh.
#
# It creates:
#   - Let's Encrypt certificate
#   - Nginx HTTPS site
#   - Panel proxy
#   - Subscription proxy
#   - Xray path forwarding
#
# Runtime state used by this module is stored in:
#   /opt/3x-ui/compat.env

DOCKER_3XUI_NGINX_CONTAINER="3xui"
DOCKER_3XUI_NGINX_DIR="/opt/3x-ui"
DOCKER_3XUI_NGINX_COMPAT_ENV="$DOCKER_3XUI_NGINX_DIR/compat.env"

DOCKER_3XUI_NGINX_SITES_AVAILABLE="/etc/nginx/sites-available"
DOCKER_3XUI_NGINX_SITES_ENABLED="/etc/nginx/sites-enabled"

DOCKER_3XUI_NGINX_ACME_ROOT="/var/www/u-opti-acme"
DOCKER_3XUI_NGINX_ACME_CONF_DIR="/etc/nginx/conf.d"

DOCKER_3XUI_NGINX_CERTBOT_BIN=""
DOCKER_3XUI_NGINX_DOMAIN=""
DOCKER_3XUI_NGINX_PANEL_PORT=""
DOCKER_3XUI_NGINX_SUB_PORT=""
DOCKER_3XUI_NGINX_METRICS_PORT=""

DOCKER_3XUI_NGINX_MARKER="# U-OPTI-MANAGED-3XUI-NGINX"

DOCKER_3XUI_NGINX_AUTO_MODE=0


docker_3xui_nginx_pause() {
    echo
    read -r -p "Press Enter to return..." _
}


docker_3xui_nginx_valid_domain() {
    [[ "$1" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$ ]]
}


docker_3xui_nginx_get_certbot() {
    if command -v certbot >/dev/null 2>&1; then
        DOCKER_3XUI_NGINX_CERTBOT_BIN="$(command -v certbot)"
        return 0
    fi

    DOCKER_3XUI_NGINX_CERTBOT_BIN=""
    return 1
}


docker_3xui_nginx_load_compat() {
    local domain=""
    local panel_port=""
    local sub_port=""
    local metrics_port=""

    if [[ ! -f "$DOCKER_3XUI_NGINX_COMPAT_ENV" ]]; then
        echo "Error: 3x-UI compatibility state was not found:"
        echo "$DOCKER_3XUI_NGINX_COMPAT_ENV"
        echo
        echo "Install Sanaei 3x-UI through U-OPTI first."
        return 1
    fi

    # shellcheck disable=SC1090
    source "$DOCKER_3XUI_NGINX_COMPAT_ENV"

    domain="${DOMAIN:-}"
    panel_port="${PANEL_PORT:-2053}"
    sub_port="${SUBSCRIPTION_PORT:-}"
    metrics_port="${METRICS_PORT:-}"

    if ! docker_3xui_nginx_valid_domain "$domain"; then
        echo "Error: Invalid or missing domain in compatibility state."
        return 1
    fi

    if [[ ! "$panel_port" =~ ^[0-9]+$ ]] ||
       (( panel_port < 1 || panel_port > 65535 )); then
        echo "Error: Invalid panel port in compatibility state: $panel_port"
        return 1
    fi

    if [[ -z "$sub_port" || ! "$sub_port" =~ ^[0-9]+$ ]] ||
       (( sub_port < 1 || sub_port > 65535 )); then
        echo "Error: Invalid subscription port in compatibility state: ${sub_port:-missing}"
        return 1
    fi

    DOCKER_3XUI_NGINX_DOMAIN="$domain"
    DOCKER_3XUI_NGINX_PANEL_PORT="$panel_port"
    DOCKER_3XUI_NGINX_SUB_PORT="$sub_port"
    DOCKER_3XUI_NGINX_METRICS_PORT="$metrics_port"

    return 0
}


docker_3xui_nginx_check_prerequisites() {
    if [[ "$EUID" -ne 0 ]]; then
        echo "Error: Root privileges are required."
        return 1
    fi

    if ! command -v systemctl >/dev/null 2>&1; then
        echo "Error: systemd/systemctl is required."
        return 1
    fi

    return 0
}


docker_3xui_nginx_install_packages() {
    local need_install=0

    command -v nginx >/dev/null 2>&1 || need_install=1
    docker_3xui_nginx_get_certbot || need_install=1

    if [[ "$need_install" -eq 0 ]]; then
        return 0
    fi

    echo "Installing required packages..."
    echo

    if ! apt update; then
        echo "Error: Failed to update APT package lists."
        return 1
    fi

    if ! apt install -y nginx certbot curl openssl; then
        echo "Error: Failed to install required packages."
        return 1
    fi

    if ! docker_3xui_nginx_get_certbot; then
        echo "Error: Certbot installation could not be verified."
        return 1
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "Error: curl is required but was not found."
        return 1
    fi

    if ! command -v openssl >/dev/null 2>&1; then
        echo "Error: openssl is required but was not found."
        return 1
    fi

    return 0
}


docker_3xui_nginx_ensure_service() {
    if ! systemctl enable --now nginx >/dev/null 2>&1; then
        echo "Error: Failed to start/enable Nginx."
        return 1
    fi

    if ! systemctl is-active --quiet nginx; then
        echo "Error: Nginx is not running."
        return 1
    fi

    return 0
}


docker_3xui_nginx_acme_conf_path() {
    echo "$DOCKER_3XUI_NGINX_ACME_CONF_DIR/u-opti-3xui-acme-${DOCKER_3XUI_NGINX_DOMAIN}.conf"
}


docker_3xui_nginx_site_path() {
    echo "$DOCKER_3XUI_NGINX_SITES_AVAILABLE/3xui-${DOCKER_3XUI_NGINX_DOMAIN}"
}


docker_3xui_nginx_enable_site() {
    local site_path="$1"
    local site_name

    site_name="$(basename "$site_path")"

    mkdir -p "$DOCKER_3XUI_NGINX_SITES_ENABLED" || return 1

    ln -sfn \
        "$site_path" \
        "$DOCKER_3XUI_NGINX_SITES_ENABLED/$site_name" || return 1

    return 0
}


docker_3xui_nginx_site_is_managed() {
    local site_path="$1"

    [[ -f "$site_path" ]] &&
        grep -Fq "$DOCKER_3XUI_NGINX_MARKER" "$site_path"
}


docker_3xui_nginx_existing_domain_conflict() {
    local domain="$DOCKER_3XUI_NGINX_DOMAIN"
    local site_path
    local output=""

    site_path="$(docker_3xui_nginx_site_path)"

    if [[ -f "$site_path" ]] &&
       ! docker_3xui_nginx_site_is_managed "$site_path"; then

        echo "Error: A non-U-OPTI Nginx site already exists:"
        echo "$site_path"
        echo
        echo "U-OPTI will not overwrite an existing configuration."
        return 1
    fi

    output="$(nginx -T 2>/dev/null || true)"

    if grep -Eq \
        "server_name[[:space:]]+[^;]*(^|[[:space:]])${domain}([[:space:]]|;)" \
        <<< "$output"; then

        if [[ ! -f "$site_path" ]] ||
           ! docker_3xui_nginx_site_is_managed "$site_path"; then

            echo "Error: The domain '$domain' is already configured in Nginx."
            echo
            echo "U-OPTI will not overwrite an existing non-U-OPTI site."
            return 1
        fi
    fi

    return 0
}


docker_3xui_nginx_prepare_acme() {
    local conf_path
    local previous=""
    local had_previous=0

    conf_path="$(docker_3xui_nginx_acme_conf_path)"

    mkdir -p \
        "$DOCKER_3XUI_NGINX_ACME_ROOT/.well-known/acme-challenge" ||
        return 1

    chmod 755 \
        "$DOCKER_3XUI_NGINX_ACME_ROOT" \
        "$DOCKER_3XUI_NGINX_ACME_ROOT/.well-known" \
        "$DOCKER_3XUI_NGINX_ACME_ROOT/.well-known/acme-challenge" ||
        return 1

    if [[ -f "$conf_path" ]]; then
        had_previous=1
        previous="$(cat "$conf_path")"
    fi

    cat > "$conf_path" <<EOF_CONF
# U-OPTI - Let's Encrypt ACME Challenge
# Domain: $DOCKER_3XUI_NGINX_DOMAIN

server {
    listen 80;
    listen [::]:80;

    server_name $DOCKER_3XUI_NGINX_DOMAIN;

    location ^~ /.well-known/acme-challenge/ {
        root $DOCKER_3XUI_NGINX_ACME_ROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}
EOF_CONF

    if ! nginx -t >/dev/null 2>&1; then
        if [[ "$had_previous" -eq 1 ]]; then
            printf '%s\n' "$previous" > "$conf_path"
        else
            rm -f "$conf_path"
        fi

        return 1
    fi

    if ! systemctl reload nginx; then
        if [[ "$had_previous" -eq 1 ]]; then
            printf '%s\n' "$previous" > "$conf_path"
        else
            rm -f "$conf_path"
        fi

        nginx -t >/dev/null 2>&1 &&
            systemctl reload nginx >/dev/null 2>&1 || true

        return 1
    fi

    return 0
}


docker_3xui_nginx_test_acme() {
    local test_file
    local response=""

    test_file="$DOCKER_3XUI_NGINX_ACME_ROOT/.well-known/acme-challenge/u-opti-test"

    printf '%s\n' "u-opti-test" > "$test_file" || return 1

    response="$(
        curl -fsS \
            --max-time 10 \
            -H "Host: $DOCKER_3XUI_NGINX_DOMAIN" \
            "http://127.0.0.1/.well-known/acme-challenge/u-opti-test" \
            2>/dev/null || true
    )"

    rm -f "$test_file"

    [[ "$response" == "u-opti-test" ]]
}


docker_3xui_nginx_issue_certificate() {
    local cert_file

    cert_file="/etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN/fullchain.pem"

    if [[ -f "$cert_file" ]]; then
        echo "Certificate already exists for:"
        echo "$DOCKER_3XUI_NGINX_DOMAIN"
        return 0
    fi

    echo "Testing ACME challenge path..."

    if ! docker_3xui_nginx_test_acme; then
        echo "Error: ACME challenge path is not reachable through Nginx."
        return 1
    fi

    echo
    echo "Requesting Let's Encrypt certificate..."
    echo

    if ! "$DOCKER_3XUI_NGINX_CERTBOT_BIN" certonly \
        --webroot \
        -w "$DOCKER_3XUI_NGINX_ACME_ROOT" \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        --cert-name "$DOCKER_3XUI_NGINX_DOMAIN" \
        -d "$DOCKER_3XUI_NGINX_DOMAIN"; then

        echo "Error: Let's Encrypt certificate issuance failed."
        return 1
    fi

    if [[ ! -f "/etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN/fullchain.pem" ]]; then
        echo "Error: Certificate was not found after issuance."
        return 1
    fi

    if [[ ! -f "/etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN/privkey.pem" ]]; then
        echo "Error: Private key was not found after issuance."
        return 1
    fi

    return 0
}


docker_3xui_nginx_write_site() {
    local site_path
    local temp_path

    site_path="$(docker_3xui_nginx_site_path)"
    temp_path="${site_path}.u-opti-new"

    cat > "$temp_path" <<EOF_CONF
$DOCKER_3XUI_NGINX_MARKER
# U-OPTI - Sanaei 3x-UI Docker Public Access
# Domain: $DOCKER_3XUI_NGINX_DOMAIN
# Panel: $DOCKER_3XUI_NGINX_PANEL_PORT
# Subscription: $DOCKER_3XUI_NGINX_SUB_PORT

server {
    server_tokens off;

    listen 443 ssl http2;
    listen [::]:443 ssl http2;

    server_name $DOCKER_3XUI_NGINX_DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Sanaei Panel
    location / {
        proxy_pass http://127.0.0.1:$DOCKER_3XUI_NGINX_PANEL_PORT;

        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_read_timeout 1d;
        proxy_send_timeout 1d;

        proxy_buffering off;
        proxy_redirect off;
    }

    # Sanaei Subscription
    location ^~ /sub/ {
        proxy_pass http://127.0.0.1:$DOCKER_3XUI_NGINX_SUB_PORT/sub/;

        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_read_timeout 1d;
        proxy_send_timeout 1d;

        proxy_buffering off;
        proxy_request_buffering off;

        proxy_redirect off;
    }

    # Subscription path using the selected subscription port.
    location ~ ^/$DOCKER_3XUI_NGINX_SUB_PORT/sub/(?<subpath>.*)$ {
        proxy_pass http://127.0.0.1:$DOCKER_3XUI_NGINX_SUB_PORT/sub/\$subpath\$is_args\$args;

        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_read_timeout 1d;
        proxy_send_timeout 1d;

        proxy_buffering off;
        proxy_request_buffering off;

        proxy_redirect off;
    }

    # Xray WebSocket / XHTTP / HTTP forwarding paths.
    #
    # Path format:
    #   /PORT/PATH
    #
    # gRPC traffic is forwarded directly with grpc_pass.
    location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {
        client_max_body_size 0;

        client_body_timeout 1d;
        proxy_read_timeout 1d;
        proxy_send_timeout 1d;

        proxy_http_version 1.1;

        proxy_buffering off;
        proxy_request_buffering off;

        proxy_socket_keepalive on;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_redirect off;

        if (\$content_type ~* "^application/grpc") {
            grpc_pass grpc://127.0.0.1:\$fwdport;
            break;
        }

        proxy_pass http://127.0.0.1:\$fwdport\$is_args\$args;
    }
}
EOF_CONF

    if ! nginx -t >/dev/null 2>&1; then
        rm -f "$temp_path"

        echo "Error: Generated Nginx configuration failed validation."
        nginx -t 2>&1 || true

        return 1
    fi

    mkdir -p "$DOCKER_3XUI_NGINX_SITES_AVAILABLE" || {
        rm -f "$temp_path"
        return 1
    }

    mv -f "$temp_path" "$site_path" || return 1

    if ! docker_3xui_nginx_enable_site "$site_path"; then
        echo "Error: Failed to enable Nginx site."
        return 1
    fi

    if ! nginx -t >/dev/null 2>&1; then
        echo "Error: Nginx configuration failed after enabling the site."
        nginx -t 2>&1 || true
        return 1
    fi

    if ! systemctl reload nginx; then
        echo "Error: Failed to reload Nginx."
        return 1
    fi

    return 0
}


docker_3xui_nginx_install_renewal_hook() {
    local hook_dir="/etc/letsencrypt/renewal-hooks/deploy"
    local hook_path

    hook_path="$hook_dir/u-opti-3xui-nginx-${DOCKER_3XUI_NGINX_DOMAIN}.sh"

    mkdir -p "$hook_dir" || return 1

    cat > "$hook_path" <<EOF_HOOK
#!/usr/bin/env bash
set -u

DOMAIN="$DOCKER_3XUI_NGINX_DOMAIN"

if [[ ! -f "/etc/letsencrypt/live/\$DOMAIN/fullchain.pem" ||
      ! -f "/etc/letsencrypt/live/\$DOMAIN/privkey.pem" ]]; then
    exit 1
fi

if ! nginx -t >/dev/null 2>&1; then
    exit 1
fi

systemctl reload nginx >/dev/null 2>&1
EOF_HOOK

    chmod 700 "$hook_path" || return 1

    return 0
}


docker_3xui_nginx_show_result() {
    echo
    echo "======================================"
    echo "     Sanaei Nginx / SSL Completed"
    echo "======================================"
    echo

    echo "Domain       : $DOCKER_3XUI_NGINX_DOMAIN"
    echo
    echo "Panel        : https://$DOCKER_3XUI_NGINX_DOMAIN/"
    echo "Subscription : https://$DOCKER_3XUI_NGINX_DOMAIN/sub/"
    echo

    echo "Panel Port   : $DOCKER_3XUI_NGINX_PANEL_PORT"
    echo "Sub Port     : $DOCKER_3XUI_NGINX_SUB_PORT"

    if [[ -n "${DOCKER_3XUI_NGINX_METRICS_PORT:-}" ]]; then
        echo "Metrics      : 127.0.0.1:$DOCKER_3XUI_NGINX_METRICS_PORT"
    fi

    echo
    echo "Nginx Site   : $(docker_3xui_nginx_site_path)"
    echo "Certificate  : /etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN/"
    echo "ACME Config  : $(docker_3xui_nginx_acme_conf_path)"
    echo "Renew Hook   : /etc/letsencrypt/renewal-hooks/deploy/u-opti-3xui-nginx-${DOCKER_3XUI_NGINX_DOMAIN}.sh"
    echo
    echo "Xray paths   : /PORT/PATH"
}


docker_3xui_nginx_pause_if_needed() {
    if [[ "${DOCKER_3XUI_NGINX_AUTO_MODE:-0}" == "1" ]]; then
        return 0
    fi

    docker_3xui_nginx_pause
}


docker_3xui_nginx_setup() {
    local auto_mode="${1:-0}"

    if [[ "$auto_mode" == "1" ]]; then
        DOCKER_3XUI_NGINX_AUTO_MODE=1
    else
        DOCKER_3XUI_NGINX_AUTO_MODE=0
    fi

    clear

    echo "======================================"
    echo "   Sanaei Nginx / SSL Configuration"
    echo "======================================"
    echo

    if ! docker_3xui_nginx_check_prerequisites; then
        docker_3xui_nginx_pause_if_needed
        return 1
    fi

    if ! docker_3xui_nginx_load_compat; then
        docker_3xui_nginx_pause_if_needed
        return 1
    fi

    echo "Domain       : $DOCKER_3XUI_NGINX_DOMAIN"
    echo "Panel        : 127.0.0.1:$DOCKER_3XUI_NGINX_PANEL_PORT"
    echo "Subscription : 127.0.0.1:$DOCKER_3XUI_NGINX_SUB_PORT"

    if [[ -n "${DOCKER_3XUI_NGINX_METRICS_PORT:-}" ]]; then
        echo "Metrics      : 127.0.0.1:$DOCKER_3XUI_NGINX_METRICS_PORT"
    fi

    echo

    if ! docker_3xui_nginx_install_packages; then
        docker_3xui_nginx_pause_if_needed
        return 1
    fi

    if ! docker_3xui_nginx_ensure_service; then
        docker_3xui_nginx_pause_if_needed
        return 1
    fi

    if ! docker_3xui_nginx_existing_domain_conflict; then
        docker_3xui_nginx_pause_if_needed
        return 1
    fi

    echo "Preparing Let's Encrypt challenge..."

    if ! docker_3xui_nginx_prepare_acme; then
        echo "Error: Failed to prepare Nginx ACME configuration."
        docker_3xui_nginx_pause_if_needed
        return 1
    fi

    if ! docker_3xui_nginx_issue_certificate; then
        docker_3xui_nginx_pause_if_needed
        return 1
    fi

    echo
    echo "Writing HTTPS Nginx configuration..."

    if ! docker_3xui_nginx_write_site; then
        docker_3xui_nginx_pause_if_needed
        return 1
    fi

    echo "Installing automatic certificate renewal hook..."

    if ! docker_3xui_nginx_install_renewal_hook; then
        echo "Error: Failed to install certificate renewal hook."
        docker_3xui_nginx_pause_if_needed
        return 1
    fi

    # Keep the ACME configuration permanently so Certbot renew can
    # use the same webroot in the future.
    if ! nginx -t >/dev/null 2>&1; then
        echo "Warning: Nginx configuration test failed after setup."
    else
        systemctl reload nginx >/dev/null 2>&1 || true
    fi

    docker_3xui_nginx_show_result
    docker_3xui_nginx_pause_if_needed
}


docker_3xui_nginx_status() {
    clear

    echo "======================================"
    echo "    Sanaei Nginx / SSL Status"
    echo "======================================"
    echo

    if ! docker_3xui_nginx_load_compat; then
        docker_3xui_nginx_pause
        return 1
    fi

    local site_path
    local cert_dir
    local acme_conf
    local cert_expiry=""

    site_path="$(docker_3xui_nginx_site_path)"
    cert_dir="/etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN"
    acme_conf="$(docker_3xui_nginx_acme_conf_path)"

    echo "Domain       : $DOCKER_3XUI_NGINX_DOMAIN"
    echo "Panel Port   : $DOCKER_3XUI_NGINX_PANEL_PORT"
    echo "Sub Port     : $DOCKER_3XUI_NGINX_SUB_PORT"

    if [[ -n "${DOCKER_3XUI_NGINX_METRICS_PORT:-}" ]]; then
        echo "Metrics      : 127.0.0.1:$DOCKER_3XUI_NGINX_METRICS_PORT"
    fi

    echo

    if systemctl is-active --quiet nginx; then
        echo "Nginx        : Active"
    else
        echo "Nginx        : Inactive"
    fi

    if [[ -f "$site_path" ]] &&
       docker_3xui_nginx_site_is_managed "$site_path"; then
        echo "Nginx Site   : Configured"
    else
        echo "Nginx Site   : Not configured"
    fi

    if [[ -f "$acme_conf" ]]; then
        echo "ACME         : Configured"
    else
        echo "ACME         : Not configured"
    fi

    if [[ -f "$cert_dir/cert.pem" ]]; then
        cert_expiry="$(
            openssl x509 \
                -in "$cert_dir/cert.pem" \
                -noout \
                -enddate 2>/dev/null |
            sed 's/^notAfter=//'
        )"

        echo "SSL          : Installed"
        echo "Expires      : ${cert_expiry:-Unknown}"
    else
        echo "SSL          : Not installed"
    fi

    echo

    docker_3xui_nginx_pause
}
