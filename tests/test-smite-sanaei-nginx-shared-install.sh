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
