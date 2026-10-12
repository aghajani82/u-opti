#!/usr/bin/env bash
# Isolated integration-style test: shared HTTPS activation, idempotence,
# and health-check rollback; no real Nginx, Certbot or Docker is touched.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/available" "$tmp/enabled" "$tmp/backups"

export UOPTI_TEST_ENABLED="$tmp/enabled"
export UOPTI_TEST_FAIL_CURL="$tmp/fail-curl"
export UOPTI_TEST_FAIL_NGINX="$tmp/fail-nginx"

cat > "$tmp/bin/nginx" <<'MOCK'
#!/usr/bin/env bash
[ -f "$UOPTI_TEST_FAIL_NGINX" ] && exit 1
shopt -s nullglob
count=0
for site in "$UOPTI_TEST_ENABLED"/*; do
    [ -f "$site" ] || continue
    if grep -Eq '^[[:space:]]*server_name[[:space:]]+kh.example.test;' "$site"; then
        count=$((count + 1))
    fi
done
if [ "$count" -gt 1 ]; then
    echo 'nginx: conflicting server name kh.example.test on 0.0.0.0:443' >&2
    exit 1
fi
echo 'nginx: configuration file syntax is ok' >&2
MOCK
cat > "$tmp/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
[ "$1" = reload ] && [ "$2" = nginx ]
MOCK
cat > "$tmp/bin/curl" <<'MOCK'
#!/usr/bin/env bash
if [ -f "$UOPTI_TEST_FAIL_CURL" ]; then printf '404'; exit 0; fi
case "${*: -1}" in
    *'/new-panel/'|*'/smite-node/abcxyz987/api/agent/status')
        printf '200'
        ;;
    *)
        printf '404'
        ;;
esac
MOCK
cat > "$tmp/bin/sleep" <<'MOCK'
#!/usr/bin/env bash
exit 0
MOCK
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH"
source "$root/modules/docker-3xui-nginx.sh"

DOCKER_3XUI_NGINX_SITES_AVAILABLE="$tmp/available"
DOCKER_3XUI_NGINX_SITES_ENABLED="$tmp/enabled"
DOCKER_3XUI_NGINX_SHARED_BACKUP_ROOT="$tmp/backups"
DOCKER_3XUI_NGINX_DOMAIN="kh.example.test"
DOCKER_3XUI_NGINX_WEB_BASE_PATH="/new-panel/"

old="$tmp/available/kh.example.test"
target="$tmp/available/3xui-kh.example.test"
old_link="$tmp/enabled/kh.example.test"
new_link="$tmp/enabled/3xui-kh.example.test"
cat > "$old" <<'NGINX'
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
    }
    # END U-OPTI SMITE FOREIGN CONTROL
    location / { try_files $uri $uri/ =404; }
}
NGINX
ln -s "$old" "$old_link"

fresh="$tmp/generated-3xui.conf"
cat > "$fresh" <<'NGINX'
# U-OPTI-MANAGED-3XUI-NGINX
# Web Base Path: /new-panel/
server {
    listen 443 ssl;
    server_name kh.example.test;
    root /var/www/u-opti-default;
    location / { try_files $uri $uri/ =404; }
    # Sanaei Panel
    location ^~ /new-panel/ {
        proxy_pass http://127.0.0.1:2053;
    }
    location ^~ /sub/ {
        proxy_pass http://127.0.0.1:2095/sub/;
    }
    location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {
        proxy_pass http://127.0.0.1:$fwdport;
    }
}
NGINX

test "$(docker_3xui_nginx_foreign_smite_source)" = "$old"
docker_3xui_nginx_import_smite_control "$fresh" "$old"
docker_3xui_nginx_activate_shared_smite "$fresh" "$target"
test ! -L "$old_link"
test -L "$new_link"
test "$(readlink -f "$new_link")" = "$target"
test -f "$old"
grep -Fq 'allow 192.0.2.10;' "$target"
grep -Fq 'proxy_pass http://127.0.0.1:8888/;' "$target"
grep -Fq 'proxy_pass http://127.0.0.1:2053;' "$target"
grep -Fq 'proxy_pass http://127.0.0.1:2095/sub/;' "$target"
grep -Fq 'proxy_pass http://127.0.0.1:$fwdport;' "$target"
nginx -t
echo "PASS: Fresh shared HTTPS installation retires only the duplicate Smite symlink"

test "$(docker_3xui_nginx_foreign_smite_source)" = "$target"
cp "$target" "$tmp/expected"
cp "$target" "$tmp/repair-candidate"
docker_3xui_nginx_activate_shared_smite "$tmp/repair-candidate" "$target"
cmp -s "$target" "$tmp/expected"
test ! -L "$old_link"
test -L "$new_link"
echo "PASS: Repair remains idempotent and preserves other routes"

cp "$target" "$tmp/failure-candidate"
sed -i 's@root /var/www/u-opti-default;@root /var/www/changed;@' "$tmp/failure-candidate"
touch "$UOPTI_TEST_FAIL_CURL"
if docker_3xui_nginx_activate_shared_smite "$tmp/failure-candidate" "$target"; then
    echo "ERROR: Health-check failure should have rolled back" >&2
    exit 1
fi
rm -f "$UOPTI_TEST_FAIL_CURL"
cmp -s "$target" "$tmp/expected"
test -L "$new_link"
test ! -L "$old_link"
nginx -t
echo "PASS: Broken panel health check restores prior managed Nginx configuration"

cp "$target" "$tmp/failure-nginx-candidate"
touch "$UOPTI_TEST_FAIL_NGINX"
if docker_3xui_nginx_activate_shared_smite "$tmp/failure-nginx-candidate" "$target"; then
    echo "ERROR: Nginx syntax failure should have rolled back" >&2
    exit 1
fi
rm -f "$UOPTI_TEST_FAIL_NGINX"
cmp -s "$target" "$tmp/expected"
nginx -t
echo "PASS: Failed Nginx validation restores prior managed vhost"
