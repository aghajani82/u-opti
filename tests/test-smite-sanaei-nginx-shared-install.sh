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
