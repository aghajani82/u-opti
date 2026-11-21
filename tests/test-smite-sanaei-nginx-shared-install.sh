#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
source "$root/modules/docker-3xui-nginx.sh"

smite="$tmp/smite.conf"
generated="$tmp/generated.conf"
cat > "$smite" <<'EOF'
# Managed by U-OPTI - Smite Foreign HTTPS/443 gateway
server {
    listen 443 ssl;
    server_name kh.example.test;
    # BEGIN U-OPTI SMITE FOREIGN CONTROL
    location ^~ /smite-node/abcxyz987/ {
        allow 127.0.0.1;
        allow ::1;
        allow 192.0.2.10;
        deny all;
        proxy_pass http://127.0.0.1:8888/;
        proxy_http_version 1.1;
    }
    # END U-OPTI SMITE FOREIGN CONTROL
    location / { try_files $uri $uri/ =404; }
}
EOF
cat > "$generated" <<'EOF'
# U-OPTI-MANAGED-3XUI-NGINX
# Web Base Path: /new-3xui-panel/
server {
    listen 443 ssl;
    server_name kh.example.test;
    # Sanaei Panel
    location ^~ /new-3xui-panel/ {
        proxy_pass http://127.0.0.1:2053;
    }
    location ^~ /sub/ {
        proxy_pass http://127.0.0.1:2095/sub/;
    }
    location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {
        proxy_pass http://127.0.0.1:$fwdport;
    }
}
EOF

docker_3xui_nginx_import_smite_control "$generated" "$smite"
grep -Fq 'allow 192.0.2.10;' "$generated"
grep -Fq 'deny all;' "$generated"
grep -Fq 'proxy_pass http://127.0.0.1:8888/;' "$generated"
grep -Fq 'proxy_pass http://127.0.0.1:2053;' "$generated"
grep -Fq 'proxy_pass http://127.0.0.1:2095/sub/;' "$generated"
grep -Fq 'proxy_pass http://127.0.0.1:$fwdport;' "$generated"
test "$(grep -Fc '# BEGIN U-OPTI SMITE FOREIGN CONTROL' "$generated")" -eq 1
cp "$generated" "$tmp/original-generated"
if docker_3xui_nginx_import_smite_control "$generated" "$smite"; then
    echo "ERROR: Repeated injection should fail closed" >&2
    exit 1
fi
cmp -s "$generated" "$tmp/original-generated"

sed '/deny all;/d' "$smite" > "$tmp/unsafe.conf"
cp "$tmp/original-generated" "$tmp/unsafe-generated.conf"
# Strip existing imported block before testing a fresh candidate.
python3 - "$tmp/unsafe-generated.conf" <<'PY'
import re,sys
p=sys.argv[1]
s=open(p).read()
s=re.sub(r'(?ms)^\s*# BEGIN U-OPTI SMITE FOREIGN CONTROL.*?^\s*# END U-OPTI SMITE FOREIGN CONTROL[^\n]*\n', '', s)
open(p,'w').write(s)
PY
cp "$tmp/unsafe-generated.conf" "$tmp/unsafe-original"
if docker_3xui_nginx_import_smite_control "$tmp/unsafe-generated.conf" "$tmp/unsafe.conf"; then
    echo "ERROR: Missing deny-all control must fail closed" >&2
    exit 1
fi
cmp -s "$tmp/unsafe-generated.conf" "$tmp/unsafe-original"

# Static regression guards for the single-vhost, single-ACME deployment path.
grep -Fq 'docker_3xui_nginx_activate_shared_smite "$temp_path" "$site_path"' "$root/modules/docker-3xui-nginx.sh"
grep -Fq 'Reusing existing Smite ACME HTTP/80 vhost' "$root/modules/docker-3xui-nginx.sh"
grep -Fq 'conflicting server name .*on .*:443' "$root/modules/docker-3xui-nginx.sh"
echo "PASS: Imported Smite control remains restricted while preserving Sanaei routes; fails closed on invalid source"

# Exercise the standard Sanaei HTTPS flow with a separate www hostname.
(
    DOCKER_3XUI_NGINX_DOMAIN="example.test"
    DOCKER_3XUI_NGINX_ACME_ROOT="$tmp/webroot"
    DOCKER_3XUI_NGINX_ACME_CONF_DIR="$tmp/conf.d"
    DOCKER_3XUI_NGINX_SITES_AVAILABLE="$tmp/sites-available"
    DOCKER_3XUI_NGINX_SITES_ENABLED="$tmp/sites-enabled"
    DOCKER_3XUI_NGINX_WEB_BASE_PATH="/panel/"
    DOCKER_3XUI_NGINX_PANEL_PORT=2053
    DOCKER_3XUI_NGINX_SUB_PORT=2095
    DOCKER_3XUI_NGINX_CERTBOT_BIN=mock_certbot

    mkdir -p "$DOCKER_3XUI_NGINX_ACME_CONF_DIR" \
        "$DOCKER_3XUI_NGINX_SITES_AVAILABLE" "$DOCKER_3XUI_NGINX_SITES_ENABLED"
    nginx() { return 0; }
    systemctl() { return 0; }
    curl() {
        printf '%s\n' "$@" >> "$tmp/acme-args"
        printf '%s\n' "u-opti-test"
    }
    mock_certbot() {
        printf '%s\n' "$@" > "$tmp/certbot-args"
        return 1
    }

    docker_3xui_nginx_prepare_acme
    docker_3xui_nginx_write_site
    if docker_3xui_nginx_issue_certificate > "$tmp/issue-output"; then
        echo "ERROR: Sanaei accepted a failed certificate request" >&2
        exit 1
    fi

    grep -Fq 'server_name example.test;' "$(docker_3xui_nginx_acme_conf_path)"
    grep -Fq 'server_name example.test;' "$(docker_3xui_nginx_site_path)"
    grep -Fxq 'Host: example.test' "$tmp/acme-args"
    test "$(sed -n '/^-d$/{n;p;}' "$tmp/certbot-args")" = 'example.test'
    test "$(docker_3xui_nginx_build_server_names example.test)" = 'example.test www.example.test'
)
echo "PASS: Sanaei uses only the configured hostname for Nginx and ACME"

# SSH wrappers and redirected stdin still need to see the menu prompts.
(
    source "$root/modules/docker-3xui.sh"

    clear() { return 0; }
    sleep() { return 0; }
    docker_3xui_load_nginx() { return 0; }
    docker_3xui_select_instance() { DOCKER_3XUI_INSTANCE_ID=01; }
    docker_3xui_nginx_setup() { printf '%s\n' "SSL setup called"; }

    printf '1\ny\n0\n' | docker_3xui_nginx_ssl_management > "$tmp/ssl-menu"
    grep -Fxq 'Please enter your selection [0-3]:' "$tmp/ssl-menu"
    grep -Fxq 'Continue with Nginx / SSL setup? [y/N]:' "$tmp/ssl-menu"
    grep -Fxq 'SSL setup called' "$tmp/ssl-menu"

    printf '1\n\n0\n' | docker_3xui_nginx_ssl_management > "$tmp/ssl-cancel"
    grep -Fxq 'Nginx / SSL setup cancelled.' "$tmp/ssl-cancel"
    if grep -Fxq 'SSL setup called' "$tmp/ssl-cancel"; then
        echo "ERROR: Blank confirmation accepted" >&2
        exit 1
    fi

    printf '\n' | docker_3xui_nginx_pause > "$tmp/ssl-pause"
    grep -Fxq 'Press Enter to return...' "$tmp/ssl-pause"
)
echo "PASS: Sanaei SSL prompts are visible with redirected stdin"

# The guarded route menu must show what to enter when stdin is redirected.
(
    source "$root/modules/docker-3xui.sh"

    clear() { return 0; }
    docker_3xui_select_instance() { DOCKER_3XUI_SELECTED_INSTANCE_ID=01; }
    python3() {
        case "${!#}" in
            --check) printf '%s\n' "XHTTP_REVIEW=PASS ROUTES=2 LEGACY_ROUTE=NO" ;;
            --apply)
                if [[ "${fail_apply:-no}" == yes ]]; then
                    printf '%s\n' "HOLD: Mock apply failure"
                    return 2
                fi
                printf '%s\n' "XHTTP_SYNC=PASS ROUTES=2 UNKNOWN_NUMERIC_PORTS=DENIED"
                ;;
            *) return 1 ;;
        esac
    }

    printf '16\ny\n\n0\n' | show_docker_3xui_menu > "$tmp/xhttp-menu"
    grep -Fxq 'Please enter your selection [0-17]:' "$tmp/xhttp-menu"
    grep -Fxq 'Apply these XHTTP routes now? [y/N] (Enter cancels):' "$tmp/xhttp-menu"
    grep -Fxq 'XHTTP_SYNC=PASS ROUTES=2 UNKNOWN_NUMERIC_PORTS=DENIED' "$tmp/xhttp-menu"
    grep -Fxq 'XHTTP route sync complete. You can test the published routes now.' "$tmp/xhttp-menu"
    grep -Fxq 'Press Enter to return to 3x-UI Docker Management...' "$tmp/xhttp-menu"

    printf '\n\n' | docker_3xui_xhttp_guard_menu > "$tmp/xhttp-cancel"
    grep -Fxq 'Cancelled without changes.' "$tmp/xhttp-cancel"
    if grep -Fq 'XHTTP_SYNC=' "$tmp/xhttp-cancel"; then
        echo "ERROR: Blank XHTTP confirmation applied routes" >&2
        exit 1
    fi

    fail_apply=yes
    printf 'y\n\n' | docker_3xui_xhttp_guard_menu > "$tmp/xhttp-failure"
    grep -Fxq 'XHTTP route sync failed. See the diagnostic above.' "$tmp/xhttp-failure"
)
echo "PASS: Guarded XHTTP route sync shows prompts and reports outcomes"

# Exercise menu dispatch, path changes, and rollback without a running instance.
(
    source "$root/modules/docker-3xui.sh"
    clear() { return 0; }
    docker_3xui_change_panel_path() { echo "Panel path menu selected"; }
    docker_3xui_change_subscription_url() { echo "Subscription menu selected"; }
    printf '5\n6\n0\n' | show_docker_3xui_menu > "$tmp/path-menu"
    grep -Fxq 'Panel path menu selected' "$tmp/path-menu"
    grep -Fxq 'Subscription menu selected' "$tmp/path-menu"
)
(
    source "$root/modules/docker-3xui.sh"
    compat="$tmp/path-compat.env"
    site="$tmp/path-site.conf"
    printf '%s\n' 'WEB_BASE_PATH=/original/' 'SUBSCRIPTION_PORT=2095' > "$compat"
    cat > "$site" <<'EOF'
# Web Base Path: /original/
    location = /original {
        return 301 /original/;
    }
    location ^~ /original/ {
        proxy_pass http://127.0.0.1:2053;
    }
    location ^~ /sub/ {
        proxy_pass http://127.0.0.1:2095;
    }
EOF
    mktemp() { command mktemp -d "$tmp/path-backup.XXXXXX"; }
    nginx() { test "$1" = -t; }
    docker() { test "$*" = "restart 3xui-01"; }
    systemctl() { test "$*" = "reload nginx"; }
    curl() { printf '302'; }
    docker_3xui_compat_configure_web_base_path() {
        test "$1" = 3xui-01 || return 1
        printf '%s\n' "$2" > "$tmp/path-current"
        test "$2" != /fail/
    }

    docker_3xui_apply_panel_path 3xui-01 example.test "$compat" "$site" /original/ /custom/panel/
    grep -Fxq 'WEB_BASE_PATH=/custom/panel/' "$compat"
    grep -Fxq '    location = /custom/panel {' "$site"
    grep -Fxq '        return 301 /custom/panel/;' "$site"
    grep -Fxq '    location ^~ /custom/panel/ {' "$site"
    grep -Fxq '    location ^~ /sub/ {' "$site"
    cp "$compat" "$tmp/path-expected-compat"
    cp "$site" "$tmp/path-expected-site"

    if docker_3xui_apply_panel_path 3xui-01 example.test "$compat" "$site" /custom/panel/ /fail/; then
        echo "ERROR: Failed panel path change succeeded" >&2
        exit 1
    fi
    cmp -s "$compat" "$tmp/path-expected-compat"
    cmp -s "$site" "$tmp/path-expected-site"
    grep -Fxq '/custom/panel/' "$tmp/path-current"
)
echo "PASS: Panel URI path changes preserve subscriptions and roll back on failure"

# Public subscription aliases retain the original /sub/ backend and old links.
(
    source "$root/modules/docker-3xui.sh"
    db="$tmp/subscription-state"
    site="$tmp/subscription-site.conf"
    aliases="$tmp/subscription-routes"
    old_uri=https://example.test/2095/sub/
    printf '%s\n' "$old_uri" > "$db"
    printf '%s\n' '    # Sanaei Subscription' '    location ^~ /sub/ {' '    }' > "$site"
    mktemp() { command mktemp -d "$tmp/subscription-backup.XXXXXX"; }
    sqlite3() {
        if [[ "$1" == -readonly ]]; then
            cat "$db"
        else
            local value="${!#}"
            value="${value#*value=\'}"
            printf '%s\n' "${value%%\'*}" > "$db"
        fi
    }
    nginx() { test "$1" = -t; }
    docker() { test "$*" = 'restart 3xui-01'; }
    systemctl() {
        if grep -Fq '/bad/' "$aliases/public-url.conf"; then
            return 1
        fi
        test "$*" = 'reload nginx'
    }

    docker_3xui_apply_subscription_url 3xui-01 example.test "$db" "$site" "$aliases" /feed/ "$old_uri"
    grep -Fxq "    include $aliases/*.conf;" "$site"
    grep -Fxq '    location ^~ /sub/ {' "$site"
    grep -Fxq '        rewrite ^/feed/(.*)$ /sub/$1 last;' "$aliases/public-url.conf"
    grep -Fxq 'https://example.test/feed/' "$db"

    if docker_3xui_apply_subscription_url 3xui-01 example.test "$db" "$site" "$aliases" /bad/ https://example.test/feed/; then
        echo "ERROR: Subscription rollback was not triggered" >&2
        exit 1
    fi
    grep -Fxq '    location ^~ /feed/ {' "$aliases/public-url.conf"
    grep -Fxq 'https://example.test/feed/' "$db"

    docker_3xui_apply_subscription_url 3xui-01 example.test "$db" "$site" "$aliases" /sub/ https://example.test/feed/
    test ! -s "$aliases/public-url.conf"
    grep -Fxq 'https://example.test/sub/' "$db"
)
echo "PASS: Public subscription URL changes preserve the backend and roll back on failure"

# Verify explicit version selection and recovery of the database after a failed switch.
(
    source "$root/modules/docker-3xui.sh"
    clear() { return 0; }
    docker_3xui_select_instance() { return 0; }
    docker_3xui_apply_version_switch() { printf 'Selected %s\n' "$1"; }
    printf '17\n1\n3.10.0\ny\n\n0\n' | show_docker_3xui_menu > "$tmp/version-menu"
    grep -Fxq 'Selected ghcr.io/mhsanaei/3x-ui:v3.10.0' "$tmp/version-menu"
)
(
    source "$root/modules/docker-3xui.sh"
    DOCKER_3XUI_CONTAINER=3xui-01
    DOCKER_3XUI_DIR="$tmp/version-instance"
    DOCKER_3XUI_COMPOSE_FILE="$DOCKER_3XUI_DIR/docker-compose.yml"
    DOCKER_3XUI_COMPAT_ENV="$DOCKER_3XUI_DIR/compat.env"
    DOCKER_3XUI_PANEL_PORT=2053
    mkdir -p "$DOCKER_3XUI_DIR/db" "$DOCKER_3XUI_DIR/cert"
    printf '%s\n' '    image: ghcr.io/aghajani82/3x-ui:main' > "$DOCKER_3XUI_COMPOSE_FILE"
    cp "$DOCKER_3XUI_COMPOSE_FILE" "$tmp/version-original-compose"
    printf '%s\n' 'WEB_BASE_PATH=/panel/' > "$DOCKER_3XUI_COMPAT_ENV"
    printf '%s\n' 'original database' > "$DOCKER_3XUI_DIR/db/x-ui.db"
    docker_3xui_is_running() { return 0; }
    docker() {
        case "$1 $2" in
            'inspect --format') echo sha256:original ;;
            'image inspect') echo sha256:candidate ;;
            'pull unavailable') return 1 ;;
            'compose -f')
                if [[ "$4" == up ]] && grep -Fq 'image: candidate' "$DOCKER_3XUI_COMPOSE_FILE"; then
                    printf '%s\n' 'candidate database' > "$DOCKER_3XUI_DIR/db/x-ui.db"
                    touch "$DOCKER_3XUI_DIR/db/x-ui.db-wal"
                fi
                ;;
            'stop 3xui-01') touch "$tmp/version-stopped" ;;
        esac
        return 0
    }
    docker_3xui_verify_version_switch() { [[ "$2" == sha256:original ]]; }

    if docker_3xui_apply_version_switch unavailable; then exit 1; fi
    test ! -e "$tmp/version-stopped"
    if docker_3xui_apply_version_switch candidate; then exit 1; fi
    cmp -s "$tmp/version-original-compose" "$DOCKER_3XUI_COMPOSE_FILE"
    grep -Fxq 'original database' "$DOCKER_3XUI_DIR/db/x-ui.db"
    test ! -e "$DOCKER_3XUI_DIR/db/x-ui.db-wal"
)
echo "PASS: Version selection downloads first and restores the previous image and database on failure"
