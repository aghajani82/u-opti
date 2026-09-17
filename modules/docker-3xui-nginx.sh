#!/usr/bin/env bash

# U-OPTI - 3x-UI Docker Nginx / SSL Integration
# v0.13.1
#
# This module configures public HTTPS access for a Sanaei 3x-UI Docker
# instance managed by docker-3xui.sh.
#
# v0.13.1 changes:
#   - Automatic www / non-www alias for apex domains.
#   - Certificate requests now include both apex and www names.
#   - ACME challenge config serves all server names.
#   - Custom Domain and SSL-only modes follow the same alias rules.

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
DOCKER_3XUI_NGINX_WEB_BASE_PATH="/"

DOCKER_3XUI_NGINX_MARKER="# U-OPTI-MANAGED-3XUI-NGINX"
DOCKER_3XUI_NGINX_CUSTOM_MARKER="# U-OPTI-MANAGED-CUSTOM-NGINX"

DOCKER_3XUI_NGINX_AUTO_MODE=0

DOCKER_3XUI_CUSTOM_DOMAIN=""
DOCKER_3XUI_CUSTOM_MODE=""
DOCKER_3XUI_CUSTOM_TARGET_PORT=""
DOCKER_3XUI_CUSTOM_SUB_PORT=""
DOCKER_3XUI_CUSTOM_WEB_BASE_PATH="/"
DOCKER_3XUI_CUSTOM_PROXY_PATH="/app/"


# ---------------------------------------------------------------------------
# Server name alias builder
# ---------------------------------------------------------------------------
# Given a domain entered by the user, produce the list of server_name
# values that Nginx should answer to, and that Certbot should request
# a certificate for.
#
# Rules:
#   apex.example.com   -> "apex.example.com www.apex.example.com"
#   www.example.com    -> "www.example.com example.com"
#   sub.example.com    -> "sub.example.com" (no www alias)
#   example.co.uk      -> "example.co.uk"   (treated as subdomain-like)
# ---------------------------------------------------------------------------
docker_3xui_nginx_build_server_names() {
    local domain="${1:-}"

    if [[ -z "$domain" ]]; then
        printf '\n'
        return 0
    fi

    case "$domain" in
        www.*)
            # www.example.com -> www.example.com example.com
            printf '%s %s\n' "$domain" "${domain#www.}"
            ;;
        *.*.*)
            # Contains three or more labels. Treated as a subdomain
            # (or a two-part public suffix like example.co.uk).
            # No automatic www alias is added.
            printf '%s\n' "$domain"
            ;;
        *.*)
            # Simple apex domain (example.com).
            printf '%s www.%s\n' "$domain" "$domain"
            ;;
        *)
            # Single label. Return as-is.
            printf '%s\n' "$domain"
            ;;
    esac
}


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
    local web_base_path="/"
    local compat_env="${DOCKER_3XUI_COMPAT_ENV:-${DOCKER_3XUI_NGINX_COMPAT_ENV:-}}"

    if [[ -z "$compat_env" ]]; then
        compat_env="/opt/3x-ui/compat.env"
    fi

    if [[ ! -f "$compat_env" ]]; then
        echo "Error: 3x-UI compatibility state was not found:"
        echo "$compat_env"
        echo
        echo "Install Sanaei 3x-UI through U-OPTI first."
        return 1
    fi

    DOCKER_3XUI_NGINX_COMPAT_ENV="$compat_env"

    # shellcheck disable=SC1090
    source "$DOCKER_3XUI_NGINX_COMPAT_ENV"

    domain="${DOMAIN:-}"
    panel_port="${PANEL_PORT:-2053}"
    sub_port="${SUBSCRIPTION_PORT:-}"
    metrics_port="${METRICS_PORT:-}"
    web_base_path="${WEB_BASE_PATH:-/}"

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

    if [ "$web_base_path" = "/" ]; then
        echo "Error: Web Base Path '/' is incompatible with the central FakeSite."
        echo "A dedicated Web Base Path is required."
        return 1
    fi

    if [[ ! "$web_base_path" =~ ^/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*/$ ]]; then
        echo "Error: Invalid Web Base Path in compatibility state: $web_base_path"
        return 1
    fi

    DOCKER_3XUI_NGINX_DOMAIN="$domain"
    DOCKER_3XUI_NGINX_PANEL_PORT="$panel_port"
    DOCKER_3XUI_NGINX_SUB_PORT="$sub_port"
    DOCKER_3XUI_NGINX_METRICS_PORT="$metrics_port"
    DOCKER_3XUI_NGINX_WEB_BASE_PATH="$web_base_path"

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
    local missing_packages=()

    command -v nginx >/dev/null 2>&1 || missing_packages+=("nginx")
    command -v certbot >/dev/null 2>&1 || missing_packages+=("certbot")
    command -v curl >/dev/null 2>&1 || missing_packages+=("curl")
    command -v openssl >/dev/null 2>&1 || missing_packages+=("openssl")

    if [[ "${#missing_packages[@]}" -eq 0 ]]; then
        DOCKER_3XUI_NGINX_CERTBOT_BIN="$(command -v certbot)"
        return 0
    fi

    echo "Installing required packages..."
    echo
    echo "Missing: ${missing_packages[*]}"
    echo

    if ! apt update; then
        echo "Error: Failed to update APT package lists."
        return 1
    fi

    if ! apt install -y "${missing_packages[@]}"; then
        echo "Error: Failed to install required packages."
        return 1
    fi

    if ! docker_3xui_nginx_get_certbot; then
        echo "Error: Certbot installation could not be verified."
        return 1
    fi

    if ! command -v nginx >/dev/null 2>&1; then
        echo "Error: Nginx is required but was not found."
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
    local server_names
    local site_path
    local output=""
    local name

    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_NGINX_DOMAIN")"

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

    for name in $server_names; do
        if grep -Eq \
            "server_name[[:space:]]+[^;]*(^|[[:space:]])${name}([[:space:]]|;)" \
            <<< "$output"; then

            if [[ ! -f "$site_path" ]] ||
               ! docker_3xui_nginx_site_is_managed "$site_path"; then

                echo "Error: The domain '$name' is already configured in Nginx."
                echo
                echo "U-OPTI will not overwrite an existing non-U-OPTI site."
                return 1
            fi
        fi
    done

    return 0
}


docker_3xui_nginx_prepare_acme() {
    local conf_path
    local previous=""
    local had_previous=0
    local server_names

    conf_path="$(docker_3xui_nginx_acme_conf_path)"
    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_NGINX_DOMAIN")"

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
# Server Names: $server_names

server {
    listen 80;
    listen [::]:80;

    server_name $server_names;

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
    local curl_status=0
    local attempt
    local name

    test_file="$DOCKER_3XUI_NGINX_ACME_ROOT/.well-known/acme-challenge/u-opti-test"

    printf '%s\n' "u-opti-test" > "$test_file" || return 1

    # Test every server name; each must resolve to the same ACME webroot.
    for name in $(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_NGINX_DOMAIN"); do
        local ok=0

        for attempt in {1..20}; do
            response="$(
                curl -fsS \
                    --max-time 10 \
                    -H "Host: $name" \
                    "http://127.0.0.1/.well-known/acme-challenge/u-opti-test" \
                    2>/dev/null
            )"
            curl_status=$?

            if [[ "$curl_status" -eq 0 && "$response" == "u-opti-test" ]]; then
                ok=1
                break
            fi

            sleep 0.5
        done

        if [[ "$ok" -ne 1 ]]; then
            rm -f "$test_file"

            echo "Error: ACME challenge path did not become reachable for:"
            echo "$name"
            echo "Last curl status: $curl_status"
            echo "Last response: ${response:-<empty>}"

            return 1
        fi
    done

    rm -f "$test_file"
    return 0
}


docker_3xui_nginx_issue_certificate() {
    local cert_file
    local server_names
    local -a server_names_arr
    local -a cert_domains
    local name

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

    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_NGINX_DOMAIN")"
    read -ra server_names_arr <<< "$server_names"

    cert_domains=()
    for name in "${server_names_arr[@]}"; do
        cert_domains+=("-d" "$name")
    done

    echo
    echo "Requesting Let's Encrypt certificate..."
    echo "Domains: $server_names"
    echo

    if ! "$DOCKER_3XUI_NGINX_CERTBOT_BIN" certonly \
        --webroot \
        -w "$DOCKER_3XUI_NGINX_ACME_ROOT" \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        --cert-name "$DOCKER_3XUI_NGINX_DOMAIN" \
        "${cert_domains[@]}"; then

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
    local server_names

    site_path="$(docker_3xui_nginx_site_path)"
    temp_path="${site_path}.u-opti-new"
    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_NGINX_DOMAIN")"

    cat > "$temp_path" <<EOF_CONF
$DOCKER_3XUI_NGINX_MARKER
# U-OPTI - Sanaei 3x-UI Docker Public Access
# Domain: $DOCKER_3XUI_NGINX_DOMAIN
# Server Names: $server_names
# Panel: $DOCKER_3XUI_NGINX_PANEL_PORT
# Subscription: $DOCKER_3XUI_NGINX_SUB_PORT
# Web Base Path: $DOCKER_3XUI_NGINX_WEB_BASE_PATH

server {
    server_tokens off;

    listen 443 ssl http2;
    listen [::]:443 ssl http2;

    server_name $server_names;

    ssl_certificate /etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
EOF_CONF

    if [ "$DOCKER_3XUI_NGINX_WEB_BASE_PATH" = "/" ]; then
        echo "Error: Web Base Path '/' is incompatible with the central FakeSite."
        echo "A dedicated Web Base Path is required."
        rm -f "$temp_path"
        return 1
    fi

    cat >> "$temp_path" <<EOF_PANEL_PATH

    # U-OPTI Central FakeSite
    root /var/www/u-opti-default;
    index index.html;

    location / {
        try_files \$uri \$uri/ =404;
    }

    # Sanaei Panel
    location = ${DOCKER_3XUI_NGINX_WEB_BASE_PATH%/} {
        return 301 $DOCKER_3XUI_NGINX_WEB_BASE_PATH;
    }

    location ^~ $DOCKER_3XUI_NGINX_WEB_BASE_PATH {
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
EOF_PANEL_PATH

    cat >> "$temp_path" <<EOF_CONF

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
    local server_names
    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_NGINX_DOMAIN")"

    echo
    echo "======================================"
    echo "     Sanaei Nginx / SSL Completed"
    echo "======================================"
    echo

    echo "Domain       : $DOCKER_3XUI_NGINX_DOMAIN"
    echo "Server Names : $server_names"
    echo
    if [[ "$DOCKER_3XUI_NGINX_WEB_BASE_PATH" = "/" ]]; then
        echo "Panel        : https://$DOCKER_3XUI_NGINX_DOMAIN/"
    else
        echo "Panel        : https://$DOCKER_3XUI_NGINX_DOMAIN$DOCKER_3XUI_NGINX_WEB_BASE_PATH"
    fi
    echo "Web Base Path: $DOCKER_3XUI_NGINX_WEB_BASE_PATH"
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
    echo "Server Names : $(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_NGINX_DOMAIN")"
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
    local server_names

    site_path="$(docker_3xui_nginx_site_path)"
    cert_dir="/etc/letsencrypt/live/$DOCKER_3XUI_NGINX_DOMAIN"
    acme_conf="$(docker_3xui_nginx_acme_conf_path)"
    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_NGINX_DOMAIN")"

    echo "Domain       : $DOCKER_3XUI_NGINX_DOMAIN"
    echo "Server Names : $server_names"
    echo "Panel Port   : $DOCKER_3XUI_NGINX_PANEL_PORT"
    echo "Sub Port     : $DOCKER_3XUI_NGINX_SUB_PORT"
    echo "Web Base Path: $DOCKER_3XUI_NGINX_WEB_BASE_PATH"

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

# ---------------------------------------------------------------------------
# U-OPTI Custom Domain / Nginx / SSL
# ---------------------------------------------------------------------------

docker_3xui_nginx_custom_domain_valid() {
    docker_3xui_nginx_valid_domain "$1"
}

docker_3xui_nginx_custom_domain_site_path() {
    echo "$DOCKER_3XUI_NGINX_SITES_AVAILABLE/u-opti-custom-${DOCKER_3XUI_CUSTOM_DOMAIN}"
}

docker_3xui_nginx_custom_domain_acme_path() {
    echo "$DOCKER_3XUI_NGINX_ACME_CONF_DIR/u-opti-custom-acme-${DOCKER_3XUI_CUSTOM_DOMAIN}.conf"
}

docker_3xui_nginx_custom_domain_conflict() {
    local server_names
    local site_path
    local output=""
    local name

    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN")"
    site_path="$(docker_3xui_nginx_custom_domain_site_path)"

    if [[ -f "$site_path" ]] &&
       ! grep -Fq "$DOCKER_3XUI_NGINX_CUSTOM_MARKER" "$site_path"; then
        echo "Error: A non-U-OPTI custom Nginx site already exists:"
        echo "$site_path"
        return 1
    fi

    output="$(nginx -T 2>/dev/null || true)"

    for name in $server_names; do
        if grep -Eq \
            "server_name[[:space:]]+[^;]*(^|[[:space:]])${name}([[:space:]]|;)" \
            <<< "$output"; then

            if [[ ! -f "$site_path" ]] ||
               ! grep -Fq "$DOCKER_3XUI_NGINX_CUSTOM_MARKER" "$site_path"; then
                echo "Error: The domain '$name' is already configured in Nginx."
                echo
                echo "U-OPTI will not overwrite an existing non-U-OPTI site."
                return 1
            fi
        fi
    done

    return 0
}

docker_3xui_nginx_custom_domain_prepare_acme() {
    local conf_path
    local previous=""
    local had_previous=0
    local server_names

    conf_path="$(docker_3xui_nginx_custom_domain_acme_path)"
    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN")"

    if [[ -f "$conf_path" ]]; then
        had_previous=1
        previous="$(cat "$conf_path")"
    fi

    mkdir -p "$DOCKER_3XUI_NGINX_ACME_ROOT/.well-known/acme-challenge" || return 1

    cat > "$conf_path" <<EOF_CONF
# U-OPTI - Let's Encrypt ACME Challenge
# Custom Domain: $DOCKER_3XUI_CUSTOM_DOMAIN
# Server Names: $server_names

server {
    listen 80;
    listen [::]:80;

    server_name $server_names;

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

    systemctl reload nginx || {
        if [[ "$had_previous" -eq 1 ]]; then
            printf '%s\n' "$previous" > "$conf_path"
        else
            rm -f "$conf_path"
        fi
        nginx -t >/dev/null 2>&1 &&
            systemctl reload nginx >/dev/null 2>&1 || true
        return 1
    }

    return 0
}

docker_3xui_nginx_custom_domain_test_acme() {
    local test_file
    local response=""
    local curl_status=0
    local attempt
    local name

    test_file="$DOCKER_3XUI_NGINX_ACME_ROOT/.well-known/acme-challenge/u-opti-custom-test"

    printf '%s\n' "u-opti-custom-test" > "$test_file" || return 1

    for name in $(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN"); do
        local ok=0

        for attempt in {1..20}; do
            response="$(
                curl -fsS \
                    --max-time 10 \
                    -H "Host: $name" \
                    "http://127.0.0.1/.well-known/acme-challenge/u-opti-custom-test" \
                    2>/dev/null
            )"
            curl_status=$?

            if [[ "$curl_status" -eq 0 && "$response" == "u-opti-custom-test" ]]; then
                ok=1
                break
            fi

            sleep 0.5
        done

        if [[ "$ok" -ne 1 ]]; then
            rm -f "$test_file"

            echo "Error: Custom domain ACME challenge path is not reachable for:"
            echo "$name"
            echo "Last curl status: $curl_status"
            echo "Last response: ${response:-<empty>}"

            return 1
        fi
    done

    rm -f "$test_file"
    return 0
}

docker_3xui_nginx_custom_domain_issue_certificate() {
    local cert_file
    local server_names
    local -a server_names_arr
    local -a cert_domains
    local name

    cert_file="/etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/fullchain.pem"

    if [[ -f "$cert_file" ]]; then
        echo "Certificate already exists for:"
        echo "$DOCKER_3XUI_CUSTOM_DOMAIN"
        return 0
    fi

    echo "Testing ACME challenge path..."

    if ! docker_3xui_nginx_custom_domain_test_acme; then
        return 1
    fi

    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN")"
    read -ra server_names_arr <<< "$server_names"

    cert_domains=()
    for name in "${server_names_arr[@]}"; do
        cert_domains+=("-d" "$name")
    done

    echo
    echo "Requesting Let's Encrypt certificate..."
    echo "Domains: $server_names"
    echo

    if ! "$DOCKER_3XUI_NGINX_CERTBOT_BIN" certonly \
        --webroot \
        -w "$DOCKER_3XUI_NGINX_ACME_ROOT" \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        --cert-name "$DOCKER_3XUI_CUSTOM_DOMAIN" \
        "${cert_domains[@]}"; then

        echo "Error: Let's Encrypt certificate issuance failed."
        return 1
    fi

    [[ -f "/etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/fullchain.pem" ]] &&
    [[ -f "/etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/privkey.pem" ]]
}

docker_3xui_nginx_custom_domain_write_hook() {
    local hook_path

    hook_path="/etc/letsencrypt/renewal-hooks/deploy/u-opti-custom-nginx-${DOCKER_3XUI_CUSTOM_DOMAIN}.sh"

    mkdir -p "/etc/letsencrypt/renewal-hooks/deploy" || return 1

    cat > "$hook_path" <<EOF_HOOK
#!/usr/bin/env bash
set -u

DOMAIN="$DOCKER_3XUI_CUSTOM_DOMAIN"

if [[ ! -f "/etc/letsencrypt/live/\$DOMAIN/fullchain.pem" ||
      ! -f "/etc/letsencrypt/live/\$DOMAIN/privkey.pem" ]]; then
    exit 1
fi

if ! nginx -t >/dev/null 2>&1; then
    exit 1
fi

systemctl reload nginx >/dev/null 2>&1
EOF_HOOK

    chmod 700 "$hook_path"
}

docker_3xui_nginx_custom_domain_write_site() {
    local site_path
    local temp_path
    local server_names

    site_path="$(docker_3xui_nginx_custom_domain_site_path)"
    temp_path="${site_path}.u-opti-new"
    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN")"

    case "$DOCKER_3XUI_CUSTOM_MODE" in
        proxy_instance)
            cat > "$temp_path" <<EOF_CONF
$DOCKER_3XUI_NGINX_CUSTOM_MARKER
# Custom Domain: $DOCKER_3XUI_CUSTOM_DOMAIN
# Server Names: $server_names
# Target Instance: $DOCKER_3XUI_INSTANCE_ID

server {
    server_tokens off;

    listen 443 ssl http2;
    listen [::]:443 ssl http2;

    server_name $server_names;

    ssl_certificate /etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    root /var/www/u-opti-default;
    index index.html;

    location / {
        try_files \$uri \$uri/ =404;
    }

    location = ${DOCKER_3XUI_CUSTOM_WEB_BASE_PATH%/} {
        return 301 $DOCKER_3XUI_CUSTOM_WEB_BASE_PATH;
    }

    location ^~ $DOCKER_3XUI_CUSTOM_WEB_BASE_PATH {
        proxy_pass http://127.0.0.1:$DOCKER_3XUI_CUSTOM_TARGET_PORT;

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

    location ^~ /sub/ {
        proxy_pass http://127.0.0.1:$DOCKER_3XUI_CUSTOM_SUB_PORT/sub/;

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
            ;;
        custom_port)
            cat > "$temp_path" <<EOF_CONF
$DOCKER_3XUI_NGINX_CUSTOM_MARKER
# Custom Domain: $DOCKER_3XUI_CUSTOM_DOMAIN
# Server Names: $server_names
# Local Target: 127.0.0.1:$DOCKER_3XUI_CUSTOM_TARGET_PORT
# Proxy Path: $DOCKER_3XUI_CUSTOM_PROXY_PATH

server {
    server_tokens off;

    listen 443 ssl http2;
    listen [::]:443 ssl http2;

    server_name $server_names;

    ssl_certificate /etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    root /var/www/u-opti-default;
    index index.html;

    location / {
        try_files \$uri \$uri/ =404;
    }

    location ^~ $DOCKER_3XUI_CUSTOM_PROXY_PATH {
        proxy_pass http://127.0.0.1:$DOCKER_3XUI_CUSTOM_TARGET_PORT/;

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
}
EOF_CONF
            ;;
        *)
            echo "Error: Unsupported custom domain mode."
            return 1
            ;;
    esac

    if ! nginx -t >/dev/null 2>&1; then
        rm -f "$temp_path"
        nginx -t 2>&1 || true
        return 1
    fi

    mkdir -p "$DOCKER_3XUI_NGINX_SITES_AVAILABLE" || {
        rm -f "$temp_path"
        return 1
    }

    mv -f "$temp_path" "$site_path" || return 1

    ln -sfn \
        "$site_path" \
        "$DOCKER_3XUI_NGINX_SITES_ENABLED/$(basename "$site_path")" || return 1

    nginx -t || return 1
    systemctl reload nginx || return 1

    return 0
}

docker_3xui_nginx_custom_domain_show_result() {
    local server_names
    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN")"

    echo
    echo "======================================"
    echo "   Custom Domain / SSL Completed"
    echo "======================================"
    echo
    echo "Domain       : $DOCKER_3XUI_CUSTOM_DOMAIN"
    echo "Server Names : $server_names"

    case "$DOCKER_3XUI_CUSTOM_MODE" in
        proxy_instance)
            echo "Target       : 3x-UI Instance $DOCKER_3XUI_INSTANCE_ID"
            echo "Panel Port   : $DOCKER_3XUI_CUSTOM_TARGET_PORT"
            echo "Sub Port     : $DOCKER_3XUI_CUSTOM_SUB_PORT"
            echo "Panel        : https://$DOCKER_3XUI_CUSTOM_DOMAIN$DOCKER_3XUI_CUSTOM_WEB_BASE_PATH"
            echo "Subscription : https://$DOCKER_3XUI_CUSTOM_DOMAIN/sub/"
            ;;
        custom_port)
            echo "Target       : 127.0.0.1:$DOCKER_3XUI_CUSTOM_TARGET_PORT"
            echo "Proxy        : https://$DOCKER_3XUI_CUSTOM_DOMAIN$DOCKER_3XUI_CUSTOM_PROXY_PATH"
            ;;
        ssl_only)
            echo "Mode         : SSL Certificate Only"
            echo "Certificate  : /etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/"
            ;;
    esac

    echo
    echo "Nginx Site   : $(docker_3xui_nginx_custom_domain_site_path)"
    echo "Certificate  : /etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/"
    echo "Renew Hook   : /etc/letsencrypt/renewal-hooks/deploy/u-opti-custom-nginx-${DOCKER_3XUI_CUSTOM_DOMAIN}.sh"
}

docker_3xui_nginx_custom_domain_ssl_only() {
    local default_root="/var/www/u-opti-default"
    local site_path
    local temp_path
    local server_names

    site_path="$(docker_3xui_nginx_custom_domain_site_path)"
    temp_path="${site_path}.u-opti-new"
    server_names="$(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN")"

    echo
    echo "Preparing default website root..."

    mkdir -p "$default_root" || return 1

    if [[ ! -f "$default_root/index.html" ]]; then
        cat > "$default_root/index.html" <<'EOF_HTML'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome</title>
</head>
<body>
</body>
</html>
EOF_HTML
    fi

    docker_3xui_nginx_custom_domain_prepare_acme || return 1

    docker_3xui_nginx_custom_domain_issue_certificate || return 1

    echo
    echo "Writing HTTPS Nginx configuration..."

    cat > "$temp_path" <<EOF_CONF
$DOCKER_3XUI_NGINX_CUSTOM_MARKER
# Custom Domain: $DOCKER_3XUI_CUSTOM_DOMAIN
# Server Names: $server_names
# Mode: SSL Certificate Only

server {
    server_tokens off;

    listen 443 ssl http2;
    listen [::]:443 ssl http2;

    server_name $server_names;

    ssl_certificate /etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOCKER_3XUI_CUSTOM_DOMAIN/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    root $default_root;
    index index.html;

    location / {
        try_files \$uri \$uri/ =404;
    }
}
EOF_CONF

    if ! nginx -t >/dev/null 2>&1; then
        rm -f "$temp_path"
        echo "ERROR: Generated Nginx configuration failed validation."
        nginx -t 2>&1 || true
        return 1
    fi

    mkdir -p "$DOCKER_3XUI_NGINX_SITES_AVAILABLE" || {
        rm -f "$temp_path"
        return 1
    }

    mv -f "$temp_path" "$site_path" || return 1

    ln -sfn \
        "$site_path" \
        "$DOCKER_3XUI_NGINX_SITES_ENABLED/$(basename "$site_path")" || return 1

    if ! nginx -t; then
        return 1
    fi

    if ! systemctl reload nginx; then
        return 1
    fi

    docker_3xui_nginx_custom_domain_write_hook || return 1

    echo
    echo "SSL certificate and HTTPS site successfully configured."
}

docker_3xui_nginx_custom_domain_menu() {
    while true; do
        clear

        echo "======================================"
        echo "      Custom Domain / Nginx / SSL"
        echo "======================================"
        echo
        echo "1) Attach Custom Domain to 3x-UI"
        echo "2) Domain + Custom Local Port"
        echo "3) SSL Certificate Only"
        echo
        echo "0) Back"
        echo

        read -r -p "Please enter your selection [0-3]: " choice

        case "$choice" in
            1)
                if ! docker_3xui_load_nginx; then
                    echo
                    echo "ERROR: Sanaei Nginx / SSL module could not be loaded."
                    read -r -p "Press Enter to return..."
                    continue
                fi

                if ! docker_3xui_select_instance; then
                    continue
                fi

                local compat_env="/opt/3x-ui/instances/${DOCKER_3XUI_INSTANCE_ID}/compat.env"

                if [[ ! -f "$compat_env" ]]; then
                    echo
                    echo "ERROR: Instance compatibility state not found:"
                    echo "$compat_env"
                    read -r -p "Press Enter to return..."
                    continue
                fi

                local target_domain=""
                local panel_port=""
                local sub_port=""
                local web_base_path="/"

                target_domain="$(
                    sed -n 's/^DOMAIN=//p' "$compat_env" | head -n1
                )"

                panel_port="$(
                    sed -n 's/^PANEL_PORT=//p' "$compat_env" | head -n1
                )"

                sub_port="$(
                    sed -n 's/^SUBSCRIPTION_PORT=//p' "$compat_env" | head -n1
                )"

                web_base_path="$(
                    sed -n 's/^WEB_BASE_PATH=//p' "$compat_env" | head -n1
                )"

                [[ -n "$web_base_path" ]] || web_base_path="/"

                if [[ "$web_base_path" == "/" ]]; then
                    echo
                    echo "ERROR: This 3x-UI instance uses Web Base Path '/'."
                    echo "A dedicated Web Base Path is required when the root URL is reserved for FakeSite."
                    echo "Change the instance Web Base Path first, then attach the custom domain."
                    read -r -p "Press Enter to return..."
                    continue
                fi

                echo
                echo "Selected Instance:"
                echo "  Instance        : $DOCKER_3XUI_INSTANCE_ID"
                echo "  Original Domain : ${target_domain:-Unknown}"
                echo "  Panel Port      : ${panel_port:-Unknown}"
                echo "  Subscription    : ${sub_port:-Unknown}"
                echo "  Web Base Path   : $web_base_path"
                echo

                read -r -p "Enter custom domain: " DOCKER_3XUI_CUSTOM_DOMAIN

                if ! docker_3xui_nginx_custom_domain_valid "$DOCKER_3XUI_CUSTOM_DOMAIN"; then
                    echo
                    echo "ERROR: Invalid domain."
                    read -r -p "Press Enter to return..."
                    continue
                fi

                if [[ "$DOCKER_3XUI_CUSTOM_DOMAIN" == "$target_domain" ]]; then
                    echo
                    echo "ERROR: This is already the Instance's primary domain."
                    read -r -p "Press Enter to return..."
                    continue
                fi

                DOCKER_3XUI_CUSTOM_MODE="proxy_instance"
                DOCKER_3XUI_CUSTOM_TARGET_PORT="$panel_port"
                DOCKER_3XUI_CUSTOM_SUB_PORT="$sub_port"
                DOCKER_3XUI_CUSTOM_WEB_BASE_PATH="$web_base_path"

                if ! docker_3xui_nginx_check_prerequisites ||
                   ! docker_3xui_nginx_install_packages ||
                   ! docker_3xui_nginx_ensure_service ||
                   ! docker_3xui_nginx_custom_domain_conflict; then
                    read -r -p "Press Enter to return..."
                    continue
                fi

                echo
                echo "Custom Domain : $DOCKER_3XUI_CUSTOM_DOMAIN"
                echo "Server Names  : $(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN")"
                echo "Target        : Instance $DOCKER_3XUI_INSTANCE_ID"
                echo "Panel Port    : $DOCKER_3XUI_CUSTOM_TARGET_PORT"
                echo "Sub Port      : $DOCKER_3XUI_CUSTOM_SUB_PORT"
                echo "Web Base Path : $DOCKER_3XUI_CUSTOM_WEB_BASE_PATH"
                echo

                read -r -p "Continue? [y/N]: " confirm

                case "$confirm" in
                    y|Y|yes|YES)
                        if docker_3xui_nginx_custom_domain_prepare_acme &&
                           docker_3xui_nginx_custom_domain_issue_certificate &&
                           docker_3xui_nginx_custom_domain_write_site &&
                           docker_3xui_nginx_custom_domain_write_hook; then

                            docker_3xui_nginx_custom_domain_show_result
                        else
                            echo
                            echo "ERROR: Custom Domain / Nginx / SSL setup failed."
                        fi

                        read -r -p "Press Enter to return..."
                        ;;

                    *)
                        echo
                        echo "Custom Domain setup cancelled."
                        sleep 1
                        ;;
                esac
                ;;

            2)
                if ! docker_3xui_load_nginx; then
                    echo
                    echo "ERROR: Sanaei Nginx / SSL module could not be loaded."
                    read -r -p "Press Enter to return..."
                    continue
                fi

                echo
                echo "Custom Domain / Local Port"
                echo

                read -r -p "Enter custom domain: " DOCKER_3XUI_CUSTOM_DOMAIN

                if ! docker_3xui_nginx_custom_domain_valid "$DOCKER_3XUI_CUSTOM_DOMAIN"; then
                    echo
                    echo "ERROR: Invalid domain."
                    read -r -p "Press Enter to return..."
                    continue
                fi

                read -r -p "Enter local port [127.0.0.1]: " DOCKER_3XUI_CUSTOM_TARGET_PORT

                if [[ ! "$DOCKER_3XUI_CUSTOM_TARGET_PORT" =~ ^[0-9]+$ ]] ||
                   (( DOCKER_3XUI_CUSTOM_TARGET_PORT < 1 ||
                      DOCKER_3XUI_CUSTOM_TARGET_PORT > 65535 )); then
                    echo
                    echo "ERROR: Invalid local port."
                    read -r -p "Press Enter to return..."
                    continue
                fi

                read -r -p "Enter proxy path [/app/]: " DOCKER_3XUI_CUSTOM_PROXY_PATH
                [[ -n "$DOCKER_3XUI_CUSTOM_PROXY_PATH" ]] || DOCKER_3XUI_CUSTOM_PROXY_PATH="/app/"

                if [[ "$DOCKER_3XUI_CUSTOM_PROXY_PATH" != /* ]]; then
                    DOCKER_3XUI_CUSTOM_PROXY_PATH="/$DOCKER_3XUI_CUSTOM_PROXY_PATH"
                fi
                [[ "$DOCKER_3XUI_CUSTOM_PROXY_PATH" == */ ]] ||
                    DOCKER_3XUI_CUSTOM_PROXY_PATH="${DOCKER_3XUI_CUSTOM_PROXY_PATH}/"

                case "$DOCKER_3XUI_CUSTOM_PROXY_PATH" in
                    /|/sub/|/$DOCKER_3XUI_CUSTOM_TARGET_PORT/*)
                        echo
                        echo "ERROR: Reserved proxy path."
                        read -r -p "Press Enter to return..."
                        continue
                        ;;
                esac

                DOCKER_3XUI_CUSTOM_MODE="custom_port"

                if ! docker_3xui_nginx_check_prerequisites ||
                   ! docker_3xui_nginx_install_packages ||
                   ! docker_3xui_nginx_ensure_service ||
                   ! docker_3xui_nginx_custom_domain_conflict; then
                    read -r -p "Press Enter to return..."
                    continue
                fi

                echo
                echo "Custom Domain : $DOCKER_3XUI_CUSTOM_DOMAIN"
                echo "Server Names  : $(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN")"
                echo "Local Target  : 127.0.0.1:$DOCKER_3XUI_CUSTOM_TARGET_PORT"
                echo "Proxy Path    : $DOCKER_3XUI_CUSTOM_PROXY_PATH"
                echo

                read -r -p "Continue? [y/N]: " confirm

                case "$confirm" in
                    y|Y|yes|YES)
                        if docker_3xui_nginx_custom_domain_prepare_acme &&
                           docker_3xui_nginx_custom_domain_issue_certificate &&
                           docker_3xui_nginx_custom_domain_write_site &&
                           docker_3xui_nginx_custom_domain_write_hook; then

                            docker_3xui_nginx_custom_domain_show_result
                        else
                            echo
                            echo "ERROR: Custom Domain / Nginx / SSL setup failed."
                        fi

                        read -r -p "Press Enter to return..."
                        ;;

                    *)
                        echo
                        echo "Custom Domain setup cancelled."
                        sleep 1
                        ;;
                esac
                ;;

            3)
                if ! docker_3xui_load_nginx; then
                    echo
                    echo "ERROR: Sanaei Nginx / SSL module could not be loaded."
                    read -r -p "Press Enter to return..."
                    continue
                fi

                echo
                echo "SSL Certificate Only"
                echo

                read -r -p "Enter domain for SSL certificate: " DOCKER_3XUI_CUSTOM_DOMAIN

                if ! docker_3xui_nginx_custom_domain_valid "$DOCKER_3XUI_CUSTOM_DOMAIN"; then
                    echo
                    echo "ERROR: Invalid domain."
                    read -r -p "Press Enter to return..."
                    continue
                fi

                DOCKER_3XUI_CUSTOM_MODE="ssl_only"

                if ! docker_3xui_nginx_check_prerequisites ||
                   ! docker_3xui_nginx_install_packages ||
                   ! docker_3xui_nginx_ensure_service; then
                    read -r -p "Press Enter to return..."
                    continue
                fi

                echo
                echo "Domain       : $DOCKER_3XUI_CUSTOM_DOMAIN"
                echo "Server Names : $(docker_3xui_nginx_build_server_names "$DOCKER_3XUI_CUSTOM_DOMAIN")"
                echo "Mode         : SSL Certificate Only"
                echo

                read -r -p "Continue? [y/N]: " confirm

                case "$confirm" in
                    y|Y|yes|YES)
                        if docker_3xui_nginx_custom_domain_ssl_only; then
                            docker_3xui_nginx_custom_domain_show_result
                        else
                            echo
                            echo "ERROR: SSL certificate and HTTPS site setup failed."
                        fi

                        read -r -p "Press Enter to return..."
                        ;;

                    *)
                        echo
                        echo "SSL setup cancelled."
                        sleep 1
                        ;;
                esac
                ;;

            0)
                return
                ;;

            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}
# ---------------------------------------------------------------------------
# Repair existing Nginx sites
# ---------------------------------------------------------------------------
# Scans U-OPTI-managed Nginx sites and ensures each one answers on the
# correct www / non-www variants using the same rules as
# docker_3xui_nginx_build_server_names.
# ---------------------------------------------------------------------------

docker_3xui_nginx_extract_site_domain() {
    local site_path="$1"
    local filename

    filename="$(basename "$site_path")"

    case "$filename" in
        3xui-*)          printf '%s\n' "${filename#3xui-}" ;;
        u-opti-custom-*) printf '%s\n' "${filename#u-opti-custom-}" ;;
        *)               return 1 ;;
    esac
}


docker_3xui_nginx_is_managed_site() {
    local site_path="$1"

    [[ -f "$site_path" ]] || return 1

    grep -Fq "$DOCKER_3XUI_NGINX_MARKER" "$site_path" 2>/dev/null && return 0
    grep -Fq "$DOCKER_3XUI_NGINX_CUSTOM_MARKER" "$site_path" 2>/dev/null && return 0

    return 1
}


docker_3xui_nginx_cert_exists() {
    local cert_name="$1"

    [[ -f "/etc/letsencrypt/live/$cert_name/cert.pem" ]]
}


docker_3xui_nginx_cert_covers_name() {
    local cert_name="$1"
    local check_name="$2"
    local cert_file

    cert_file="/etc/letsencrypt/live/$cert_name/cert.pem"
    [[ -f "$cert_file" ]] || return 1

    openssl x509 -in "$cert_file" -noout -text 2>/dev/null |
        grep -oE 'DNS:[^,[:space:]]+' |
        sed 's/^DNS://' |
        grep -Fxq "$check_name"
}


docker_3xui_nginx_repair_single_site() {
    local site_link="$1"
    local domain="$2"
    local cert_name="$3"

    local site_path
    local site_name
    local available_path
    local current_server_names
    local expected_server_names
    local -a expected_arr=()
    local name
    local needs_cert_expand=0
    local backup

    # Prefer the file under sites-available as the source of truth.
    # This keeps symlinks intact and ensures backups are never placed
    # inside sites-enabled, where Nginx would try to load them.
    site_name="$(basename "$site_link")"
    available_path="$DOCKER_3XUI_NGINX_SITES_AVAILABLE/$site_name"

    if [[ -f "$available_path" ]]; then
        site_path="$available_path"
    elif [[ -L "$site_link" ]]; then
        site_path="$(readlink -f "$site_link" 2>/dev/null || echo "$site_link")"
    else
        site_path="$site_link"
    fi

    echo
    echo "======================================"
    echo "      Repairing Site"
    echo "======================================"
    echo
    echo "Site   : $(basename "$site_path")"
    echo "Domain : $domain"
    echo

    # 1. Current server_name line.
    current_server_names="$(
        sed -n 's/^[[:space:]]*server_name[[:space:]]\+\([^;]*\);.*/\1/p' \
            "$site_path" | head -n1
    )"

    # 2. Expected server names.
    expected_server_names="$(docker_3xui_nginx_build_server_names "$domain")"

    echo "Current  server_name: ${current_server_names:-<none>}"
    echo "Expected server_name: $expected_server_names"
    echo

    if [[ "$current_server_names" == "$expected_server_names" ]]; then
        echo "server_name already matches. No change needed."

        # Still verify certificate coverage.
        read -ra expected_arr <<< "$expected_server_names"
        for name in "${expected_arr[@]}"; do
            if ! docker_3xui_nginx_cert_covers_name "$cert_name" "$name"; then
                echo "WARNING: Certificate does not cover: $name"
                echo "You may want to reissue the certificate manually."
            fi
        done

        return 0
    fi

    read -ra expected_arr <<< "$expected_server_names"

    # 3. Certificate coverage check.
    for name in "${expected_arr[@]}"; do
        if ! docker_3xui_nginx_cert_covers_name "$cert_name" "$name"; then
            needs_cert_expand=1
            echo "Certificate is missing: $name"
        fi
    done

    # 4. Expand or issue certificate.
    if [[ "$needs_cert_expand" -eq 1 ]]; then
        local -a cert_domains=()
        for name in "${expected_arr[@]}"; do
            cert_domains+=("-d" "$name")
        done

        echo
        echo "Updating certificate to cover all server names..."
        echo "Domains: $expected_server_names"
        echo

        if docker_3xui_nginx_cert_exists "$cert_name"; then
            if ! "$DOCKER_3XUI_NGINX_CERTBOT_BIN" certonly \
                --webroot \
                -w "$DOCKER_3XUI_NGINX_ACME_ROOT" \
                --non-interactive \
                --agree-tos \
                --register-unsafely-without-email \
                --cert-name "$cert_name" \
                "${cert_domains[@]}" \
                --expand; then

                echo
                echo "ERROR: Certificate expansion failed."
                echo "The site configuration was NOT modified."
                return 1
            fi
        else
            if ! "$DOCKER_3XUI_NGINX_CERTBOT_BIN" certonly \
                --webroot \
                -w "$DOCKER_3XUI_NGINX_ACME_ROOT" \
                --non-interactive \
                --agree-tos \
                --register-unsafely-without-email \
                --cert-name "$cert_name" \
                "${cert_domains[@]}"; then

                echo
                echo "ERROR: Certificate issuance failed."
                echo "The site configuration was NOT modified."
                return 1
            fi
        fi

        echo "Certificate updated successfully."
    else
        echo "Certificate already covers all required names."
    fi

    # 5. Backup and update server_name.
    backup="${site_path}.bak-$(date +%Y%m%d-%H%M%S)"
    cp -f "$site_path" "$backup" || {
        echo "ERROR: Failed to create site backup."
        return 1
    }

    echo
    echo "Updating server_name in site configuration..."
    echo "Backup: $backup"

    if ! sed -i \
        "s|^\([[:space:]]*server_name[[:space:]]\+\)[^;]*;|\1${expected_server_names};|" \
        "$site_path"; then

        echo "ERROR: Failed to update server_name."
        cp -f "$backup" "$site_path"
        return 1
    fi

    # 6. Test and reload.
    if ! nginx -t >/dev/null 2>&1; then
        echo "ERROR: Nginx configuration test failed. Restoring backup."
        nginx -t 2>&1 || true
        cp -f "$backup" "$site_path"
        return 1
    fi

    if ! systemctl reload nginx; then
        echo "ERROR: Failed to reload Nginx. Restoring backup."
        cp -f "$backup" "$site_path"
        systemctl reload nginx >/dev/null 2>&1 || true
        return 1
    fi

    echo
    echo "Site repaired successfully."
    echo "New server_name: $expected_server_names"
    echo "Backup: $backup"

    return 0
}


docker_3xui_nginx_repair_all_sites() {
    local repaired=0
    local failed=0
    local skipped=0
    local site_path
    local domain
    local cert_name

    echo
    echo "Scanning U-OPTI-managed Nginx sites..."
    echo

    shopt -s nullglob
    for site_path in \
        "$DOCKER_3XUI_NGINX_SITES_ENABLED"/3xui-* \
        "$DOCKER_3XUI_NGINX_SITES_ENABLED"/u-opti-custom-*; do

        [[ -f "$site_path" ]] || continue

        if ! docker_3xui_nginx_is_managed_site "$site_path"; then
            echo "Skipping non-U-OPTI site: $(basename "$site_path")"
            skipped=$((skipped + 1))
            continue
        fi

        if ! domain="$(docker_3xui_nginx_extract_site_domain "$site_path")"; then
            echo "Skipping unparseable site: $(basename "$site_path")"
            skipped=$((skipped + 1))
            continue
        fi

        # In U-OPTI, the certificate name is the primary domain used
        # when the site was created. This is true for both 3xui-* and
        # u-opti-custom-* sites.
        cert_name="$domain"

        if docker_3xui_nginx_repair_single_site "$site_path" "$domain" "$cert_name"; then
            repaired=$((repaired + 1))
        else
            failed=$((failed + 1))
        fi
    done
    shopt -u nullglob

    echo
    echo "======================================"
    echo "         Repair Summary"
    echo "======================================"
    echo
    echo "Repaired : $repaired"
    echo "Failed   : $failed"
    echo "Skipped  : $skipped"
    echo
}


docker_3xui_nginx_repair_menu() {
    while true; do
        clear

        echo "======================================"
        echo "    Repair Existing Nginx Sites"
        echo "======================================"
        echo
        echo "This will scan U-OPTI-managed Nginx sites and ensure each"
        echo "domain works with and without the www prefix, using the"
        echo "same rules as the latest Nginx / SSL module."
        echo
        echo "For each site, U-OPTI will:"
        echo "  1. Read the current server_name line."
        echo "  2. Compute the expected www / non-www aliases."
        echo "  3. Expand or issue the Let's Encrypt certificate."
        echo "  4. Update the site configuration."
        echo "  5. Test and reload Nginx."
        echo
        echo "A timestamped backup is created before any site is changed."
        echo
        echo "1) Repair all U-OPTI-managed sites"
        echo "2) Repair a specific site"
        echo
        echo "0) Back"
        echo

        read -r -p "Please enter your selection [0-2]: " repair_choice

        case "$repair_choice" in
            1)
                if ! docker_3xui_nginx_check_prerequisites ||
                   ! docker_3xui_nginx_install_packages ||
                   ! docker_3xui_nginx_ensure_service; then
                    echo
                    read -r -p "Press Enter to return..." _
                    continue
                fi

                docker_3xui_nginx_repair_all_sites
                read -r -p "Press Enter to return..." _
                ;;

            2)
                if ! docker_3xui_nginx_check_prerequisites ||
                   ! docker_3xui_nginx_install_packages ||
                   ! docker_3xui_nginx_ensure_service; then
                    echo
                    read -r -p "Press Enter to return..." _
                    continue
                fi

                local -a sites=()
                local site_path
                local domain
                local i=1
                local pick

                shopt -s nullglob
                for site_path in \
                    "$DOCKER_3XUI_NGINX_SITES_ENABLED"/3xui-* \
                    "$DOCKER_3XUI_NGINX_SITES_ENABLED"/u-opti-custom-*; do

                    [[ -f "$site_path" ]] || continue
                    docker_3xui_nginx_is_managed_site "$site_path" || continue
                    sites+=("$site_path")
                done
                shopt -u nullglob

                if [[ "${#sites[@]}" -eq 0 ]]; then
                    echo
                    echo "No U-OPTI-managed Nginx sites were found."
                    read -r -p "Press Enter to return..." _
                    continue
                fi

                echo
                echo "Available U-OPTI-managed sites:"
                echo
                for site_path in "${sites[@]}"; do
                    echo "  $i) $(basename "$site_path")"
                    i=$((i + 1))
                done
                echo "  0) Cancel"
                echo

                read -r -p "Select site [0-${#sites[@]}]: " pick

                if [[ "$pick" == "0" ]]; then
                    continue
                fi

                if ! [[ "$pick" =~ ^[0-9]+$ ]] ||
                   (( pick < 1 || pick > ${#sites[@]} )); then
                    echo
                    echo "Invalid selection."
                    sleep 1
                    continue
                fi

                site_path="${sites[$((pick - 1))]}"
                domain="$(docker_3xui_nginx_extract_site_domain "$site_path")"

                echo
                echo "Selected: $(basename "$site_path")"
                echo "Domain  : $domain"
                echo
                read -r -p "Continue with repair? [y/N]: " confirm

                case "$confirm" in
                    y|Y|yes|YES)
                        if docker_3xui_nginx_repair_single_site \
                            "$site_path" "$domain" "$domain"; then
                            echo
                            echo "Repair completed."
                        else
                            echo
                            echo "Repair failed."
                        fi
                        ;;

                    *)
                        echo
                        echo "Repair cancelled."
                        sleep 1
                        ;;
                esac

                read -r -p "Press Enter to return..." _
                ;;

            0)
                return 0
                ;;

            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}
