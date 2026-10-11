#!/usr/bin/env bash
# Regression: Foreign Gateway repair must never discard other managed services
# on the same HTTPS vhost, including Sanaei panel and static website.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
source "$root/modules/smite-foreign-gateway.sh"

site="$tmp/foreign.conf"
cat > "$site" <<'EOF_SITE'
# Managed by U-OPTI - Smite Foreign HTTPS/443 gateway
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name kh.example.test;
    ssl_certificate /etc/letsencrypt/live/kh.example.test/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kh.example.test/privkey.pem;
    root /var/www/html;

    # BEGIN U-OPTI SMITE FOREIGN CONTROL
    location ^~ /smite-node/test-control/ {
        allow 127.0.0.1;
        allow 192.0.2.1;
        deny all;
        proxy_pass http://127.0.0.1:8888/;
    }
    # END U-OPTI SMITE FOREIGN CONTROL

    # BEGIN U-OPTI SHARED SANAEI PANEL
    location = /test-panel-base {
        return 301 /test-panel-base/;
    }
    location ^~ /test-panel-base/ {
        proxy_pass http://127.0.0.1:2053;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
    # END U-OPTI SHARED SANAEI PANEL

    location / { try_files $uri $uri/ =404; }
}
EOF_SITE

smite_foreign_gateway_write_site "kh.example.test" "192.0.2.10" "/smite-node/test-control" "$site"
grep -Fq 'allow 192.0.2.10;' "$site"
! grep -Fq 'allow 192.0.2.1;' "$site"
grep -Fq 'location ^~ /test-panel-base/ {' "$site"
grep -Fq 'proxy_pass http://127.0.0.1:2053;' "$site"
test "$(grep -Fc '# BEGIN U-OPTI SHARED SANAEI PANEL' "$site")" -eq 1
test "$(grep -Fc '# BEGIN U-OPTI SMITE FOREIGN CONTROL' "$site")" -eq 1
cp "$site" "$tmp/expected"

smite_foreign_gateway_write_site "kh.example.test" "192.0.2.10" "/smite-node/test-control" "$site"
cmp -s "$site" "$tmp/expected"
echo "PASS: Foreign Gateway Repair preserves shared Sanaei panel and is idempotent"
