#!/bin/bash

# U-OPTI - Smite Foreign Node 443 Gateway
# Panel -> Foreign Node control over HTTPS/TCP 443.

SMITE_NODE_DIR="${SMITE_NODE_DIR:-/opt/smite-node}"
SMITE_NODE_COMPOSE="${SMITE_NODE_COMPOSE:-$SMITE_NODE_DIR/docker-compose.yml}"
SMITE_OVERLAY_DIR="${SMITE_OVERLAY_DIR:-/opt/u-opti-smite}"
SMITE_STATE_DIR="${SMITE_STATE_DIR:-/etc/u-opti/smite}"
SMITE_STATE_FILE="${SMITE_STATE_FILE:-$SMITE_STATE_DIR/state.env}"
SMITE_FOREIGN_GATEWAY_STATE_FILE="$SMITE_STATE_DIR/foreign-gateway.env"
SMITE_FOREIGN_ACME_ROOT="${SMITE_FOREIGN_ACME_ROOT:-/var/www/u-opti-acme}"
SMITE_FOREIGN_RENEW_HOOK="/etc/letsencrypt/renewal-hooks/deploy/u-opti-nginx-reload"

smite_foreign_gateway_pause() {
    echo
    read -rp "Press Enter to return..."
}

smite_foreign_gateway_state_value() {
    local key="$1" file="$2"
    [ -f "$file" ] || return 0
    awk -F= -v key="$key" '$1 == key {print substr($0, index($0,"=")+1); exit}' "$file"
}

smite_foreign_gateway_validate_domain() {
    [[ "$1" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]
}

smite_foreign_gateway_validate_ipv4() {
    python3 - "$1" <<'PY' >/dev/null 2>&1
import ipaddress, sys
try:
    ip = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if ip.version == 4 else 1)
PY
}

smite_foreign_gateway_role() {
    smite_foreign_gateway_state_value SMITE_ROLE "$SMITE_STATE_FILE"
}

smite_foreign_gateway_panel_domain() {
    local value=""
    value="$(smite_foreign_gateway_state_value SMITE_PANEL_DOMAIN "$SMITE_STATE_FILE")"
    if [ -z "$value" ] && [ -f "$SMITE_NODE_DIR/.env" ]; then
        value="$(awk -F= '$1 == "PANEL_ADDRESS" {print substr($0,index($0,"=")+1); exit}' "$SMITE_NODE_DIR/.env")"
        value="${value#http://}"
        value="${value#https://}"
        value="${value%%:*}"
    fi
    printf '%s' "$value"
}

smite_foreign_gateway_domain() {
    smite_foreign_gateway_state_value SMITE_FOREIGN_DOMAIN "$SMITE_STATE_FILE"
}

smite_foreign_gateway_node_name() {
    local value=""
    value="$(smite_foreign_gateway_state_value SMITE_NODE_NAME "$SMITE_STATE_FILE")"
    if [ -z "$value" ] && [ -f "$SMITE_NODE_DIR/.env" ]; then
        value="$(awk -F= '$1 == "NODE_NAME" {print substr($0,index($0,"=")+1); exit}' "$SMITE_NODE_DIR/.env")"
    fi
    printf '%s' "$value"
}

smite_foreign_gateway_site_path() {
    printf '/etc/nginx/sites-available/%s' "$1"
}

smite_foreign_gateway_enabled_path() {
    printf '/etc/nginx/sites-enabled/%s' "$1"
}

smite_foreign_gateway_container_healthy() {
    local state health
    state="$(docker inspect -f '{{.State.Status}}' smite-node 2>/dev/null || true)"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' smite-node 2>/dev/null || true)"
    [ "$state" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "none" ]; }
}

smite_foreign_gateway_wait_healthy() {
    local timeout="${1:-90}" elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        smite_foreign_gateway_container_healthy && return 0
        sleep 2
        elapsed=$((elapsed + 2))
    done
    return 1
}

smite_foreign_gateway_require_node() {
    command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker is not installed."; return 1; }
    [ -f "$SMITE_NODE_COMPOSE" ] || { echo "ERROR: Smite Node compose file was not found: $SMITE_NODE_COMPOSE"; return 1; }
    smite_foreign_gateway_container_healthy || { echo "ERROR: smite-node is not healthy."; return 1; }
    curl -fsS --max-time 3 http://127.0.0.1:8888/api/agent/status >/dev/null 2>&1 || {
        echo "ERROR: Smite Node API is not reachable at 127.0.0.1:8888."
        return 1
    }
}

smite_foreign_gateway_ensure_packages() {
    local packages=()
    command -v nginx >/dev/null 2>&1 || packages+=(nginx)
    command -v certbot >/dev/null 2>&1 || packages+=(certbot)
    command -v curl >/dev/null 2>&1 || packages+=(curl)
    command -v python3 >/dev/null 2>&1 || packages+=(python3)
    command -v openssl >/dev/null 2>&1 || packages+=(openssl)

    if [ "${#packages[@]}" -gt 0 ]; then
        echo "Installing Foreign gateway packages: ${packages[*]}"
        apt update || return 1
        DEBIAN_FRONTEND=noninteractive apt install -y "${packages[@]}" || return 1
    fi

    systemctl enable --now nginx >/dev/null 2>&1 || return 1
    nginx -t >/dev/null 2>&1 || {
        echo "ERROR: Existing Nginx configuration is invalid."
        nginx -t 2>&1 || true
        return 1
    }
}

smite_foreign_gateway_prepare_acme() {
    local domain="$1" acme_conf="/etc/nginx/conf.d/u-opti-acme-${1}.conf"
    local attempt=1

    mkdir -p "$SMITE_FOREIGN_ACME_ROOT/.well-known/acme-challenge" || return 1
    chmod 0755 "$SMITE_FOREIGN_ACME_ROOT" "$SMITE_FOREIGN_ACME_ROOT/.well-known" \
        "$SMITE_FOREIGN_ACME_ROOT/.well-known/acme-challenge" || return 1

    cat > "$acme_conf" <<EOF
# U-OPTI Smite Foreign ACME webroot
server {
    listen 80;
    listen [::]:80;
    server_name $domain;

    location ^~ /.well-known/acme-challenge/ {
        root $SMITE_FOREIGN_ACME_ROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / { return 404; }
}
EOF

    nginx -t || return 1
    systemctl reload nginx || return 1

    printf '%s\n' 'u-opti-smite-foreign-acme-test' > \
        "$SMITE_FOREIGN_ACME_ROOT/.well-known/acme-challenge/u-opti-smite-foreign-test" || return 1

    while [ "$attempt" -le 10 ]; do
        if curl -fsS --connect-timeout 2 --max-time 5 -H "Host: $domain" \
            http://127.0.0.1/.well-known/acme-challenge/u-opti-smite-foreign-test 2>/dev/null \
            | grep -qx 'u-opti-smite-foreign-acme-test'; then
            rm -f "$SMITE_FOREIGN_ACME_ROOT/.well-known/acme-challenge/u-opti-smite-foreign-test"
            return 0
        fi
        [ "$attempt" -lt 10 ] && sleep 1
        attempt=$((attempt + 1))
    done

    rm -f "$SMITE_FOREIGN_ACME_ROOT/.well-known/acme-challenge/u-opti-smite-foreign-test"
    echo "ERROR: Local ACME webroot validation failed."
    return 1
}

smite_foreign_gateway_ensure_certificate() {
    local domain="$1" cert_dir="/etc/letsencrypt/live/$1"
    if [ -s "$cert_dir/fullchain.pem" ] && [ -s "$cert_dir/privkey.pem" ]; then
        echo "Certificate: existing certificate will be used."
        return 0
    fi

    smite_foreign_gateway_prepare_acme "$domain" || return 1
    echo "Requesting Let's Encrypt certificate for $domain ..."
    certbot certonly --webroot -w "$SMITE_FOREIGN_ACME_ROOT" --non-interactive --agree-tos \
        --register-unsafely-without-email --cert-name "$domain" -d "$domain" || return 1
    [ -s "$cert_dir/fullchain.pem" ] && [ -s "$cert_dir/privkey.pem" ]
}

smite_foreign_gateway_write_renew_hook() {
    mkdir -p "$(dirname "$SMITE_FOREIGN_RENEW_HOOK")" || return 1
    cat > "$SMITE_FOREIGN_RENEW_HOOK" <<'EOF'
#!/bin/sh
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
fi
EOF
    chmod 0755 "$SMITE_FOREIGN_RENEW_HOOK"
}

smite_foreign_gateway_resolve_panel_ipv4() {
    getent ahostsv4 "$1" 2>/dev/null | awk '$2 == "STREAM" {print $1; exit}'
}

smite_foreign_gateway_existing_control_path() {
    local site="$1"
    [ -f "$site" ] || return 0
    sed -nE 's@^[[:space:]]*location[[:space:]]+\^~[[:space:]]+(/smite-node/[A-Za-z0-9_-]+)/[[:space:]]*\{.*@\1@p' "$site" | head -n1
}

smite_foreign_gateway_control_path() {
    local site="$1" value=""
    value="$(smite_foreign_gateway_state_value SMITE_FOREIGN_CONTROL_PATH "$SMITE_FOREIGN_GATEWAY_STATE_FILE")"
    [ -n "$value" ] || value="$(smite_foreign_gateway_existing_control_path "$site")"
    [ -n "$value" ] || value="/smite-node/$(openssl rand -hex 8)"
    printf '%s' "${value%/}"
}

smite_foreign_gateway_write_site() {
    local domain="$1" panel_ip="$2" control_path="$3" site="$4"

    if [ ! -f "$site" ]; then
        cat > "$site" <<EOF
# Managed by U-OPTI - Smite Foreign HTTPS/443 gateway
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name $domain;

    ssl_certificate /etc/letsencrypt/live/$domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$domain/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    root /var/www/html;
    index index.html index.htm index.nginx-debian.html;

    # BEGIN U-OPTI SMITE FOREIGN CONTROL
    location ^~ ${control_path}/ {
        allow 127.0.0.1;
        allow ::1;
        allow $panel_ip;
        deny all;

        proxy_pass http://127.0.0.1:8888/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
    # END U-OPTI SMITE FOREIGN CONTROL

    location / { try_files \$uri \$uri/ =404; }
}
EOF
        return 0
    fi

    python3 - "$site" "$domain" "$panel_ip" "$control_path" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
domain = sys.argv[2]
panel_ip = sys.argv[3]
control_path = sys.argv[4].rstrip('/')
text = path.read_text()
lines = text.splitlines(keepends=True)

begin_marker = '# BEGIN U-OPTI SMITE FOREIGN CONTROL'
end_marker = '# END U-OPTI SMITE FOREIGN CONTROL'

block = f'''    {begin_marker}\n    location ^~ {control_path}/ {{\n        allow 127.0.0.1;\n        allow ::1;\n        allow {panel_ip};\n        deny all;\n\n        proxy_pass http://127.0.0.1:8888/;\n        proxy_http_version 1.1;\n        proxy_set_header Host $host;\n        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_set_header X-Forwarded-Proto https;\n        proxy_connect_timeout 10s;\n        proxy_read_timeout 60s;\n        proxy_send_timeout 60s;\n    }}\n    {end_marker}\n'''


def brace_delta(line):
    body = line.split('#', 1)[0]
    return body.count('{') - body.count('}')


def server_blocks(items):
    result = []
    i = 0
    while i < len(items):
        if re.match(r'^\s*server\s*\{', items[i]):
            depth = 0
            for j in range(i, len(items)):
                depth += brace_delta(items[j])
                if depth == 0:
                    result.append((i, j))
                    i = j
                    break
            else:
                raise SystemExit('ERROR: Unterminated Nginx server block; refusing unsafe edit')
        i += 1
    return result


def target_server(items):
    matches = []
    for start, end in server_blocks(items):
        body = ''.join(items[start:end + 1])
        names = []
        for match in re.finditer(r'(?m)^\s*server_name\s+([^;]+);', body):
            names.extend(match.group(1).split())
        listens_443 = re.search(r'(?m)^\s*listen\s+[^;]*\b443\b[^;]*;', body) is not None
        if domain in names and listens_443:
            matches.append((start, end))
    if len(matches) != 1:
        raise SystemExit(
            f'ERROR: Expected exactly one HTTPS server block for {domain}; found {len(matches)}. No change made.'
        )
    return matches[0]


start, end = target_server(lines)

marker_starts = [i for i in range(start, end + 1) if begin_marker in lines[i]]
marker_ends = [i for i in range(start, end + 1) if end_marker in lines[i]]
if marker_starts or marker_ends:
    if len(marker_starts) != 1 or len(marker_ends) != 1 or marker_starts[0] >= marker_ends[0]:
        raise SystemExit('ERROR: Invalid U-OPTI Foreign control markers; no change made')
    a, b = marker_starts[0], marker_ends[0]
    lines[a:b + 1] = [block]
    path.write_text(''.join(lines))
    print('Existing Nginx site preserved; managed Smite control block updated.')
    raise SystemExit(0)

location_re = re.compile(
    r'^\s*location\s+\^~\s+' + re.escape(control_path + '/') + r'\s*\{'
)
legacy_start = None
for i in range(start, end + 1):
    if location_re.match(lines[i]):
        legacy_start = i
        break

if legacy_start is not None:
    depth = 0
    legacy_end = None
    for j in range(legacy_start, end + 1):
        depth += brace_delta(lines[j])
        if depth == 0:
            legacy_end = j
            break
    if legacy_end is None:
        raise SystemExit('ERROR: Unterminated legacy Smite control location; no change made')
    lines[legacy_start:legacy_end + 1] = [block]
    path.write_text(''.join(lines))
    print('Existing Nginx site preserved; legacy Smite control location migrated.')
    raise SystemExit(0)

# Re-evaluate the target after no replacements; insert before its closing brace.
start, end = target_server(lines)
lines[end:end] = ['\n' + block]
path.write_text(''.join(lines))
print('Existing Nginx site preserved; Smite control location added.')
PY
}

smite_foreign_gateway_verify_local() {
    local domain="$1" control_path="$2"
    local json="" attempt=1

    while [ "$attempt" -le 10 ]; do
        json="$(curl -fsS --max-time 10 --resolve "${domain}:443:127.0.0.1" \
            "https://${domain}${control_path}/api/agent/status" 2>/dev/null || true)"

        if [ -n "$json" ] && python3 - "$json" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if data.get('status') == 'ok' else 1)
PY
        then
            return 0
        fi

        [ "$attempt" -lt 10 ] && sleep 1
        attempt=$((attempt + 1))
    done

    return 1
}

smite_foreign_gateway_patch_control_metadata() {
    local overlay="$SMITE_OVERLAY_DIR/node/panel_client.py"

    if [ ! -f "$overlay" ]; then
        if declare -F smite_prepare_overlays >/dev/null 2>&1; then
            echo "Preparing Smite compatibility overlay first..."
            smite_prepare_overlays || return 1
        else
            echo "ERROR: Node compatibility overlay was not found: $overlay"
            return 1
        fi
    fi

    python3 - "$overlay" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
s = path.read_text()
if 'SMITE_CONTROL_ADDRESS' in s:
    print('Foreign control metadata overlay: already patched')
    raise SystemExit(0)

old = '''                "role": settings.node_role  # "iran" or "foreign"
            }
        }
        
        try:
'''
new = '''                "role": settings.node_role  # "iran" or "foreign"
            }
        }

        control_address = __import__("os").environ.get("SMITE_CONTROL_ADDRESS", "").strip()
        if control_address:
            registration_data["metadata"]["control_address"] = control_address.rstrip("/")
        
        try:
'''
if old not in s:
    raise SystemExit('ERROR: Expected Smite registration metadata block was not found; refusing unsafe patch')
path.write_text(s.replace(old, new, 1))
print('Foreign control metadata overlay: patched')
PY

    python3 -m py_compile "$overlay" || return 1

    if ! grep -Fq "$SMITE_OVERLAY_DIR/node/panel_client.py:/app/app/panel_client.py:ro" "$SMITE_NODE_COMPOSE"; then
        if declare -F smite_patch_compose_mounts >/dev/null 2>&1; then
            smite_patch_compose_mounts || return 1
        else
            echo "ERROR: Node overlay exists but is not mounted in Compose."
            return 1
        fi
    fi
}

smite_foreign_gateway_set_node_control_address() {
    local control_url="$1" backup="$2" env_file="$SMITE_NODE_DIR/.env"
    [ -f "$env_file" ] || { echo "ERROR: Smite Node environment file was not found: $env_file"; return 1; }

    cp -a "$env_file" "$backup" || return 1
    if grep -q '^SMITE_CONTROL_ADDRESS=' "$env_file"; then
        sed -i "s|^SMITE_CONTROL_ADDRESS=.*|SMITE_CONTROL_ADDRESS=${control_url}|" "$env_file" || return 1
    else
        printf '\nSMITE_CONTROL_ADDRESS=%s\n' "$control_url" >> "$env_file" || return 1
    fi
}

smite_foreign_gateway_recreate_node() {
    docker compose -f "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node || return 1
    smite_foreign_gateway_wait_healthy 90
}

smite_foreign_gateway_verify_panel() {
    local panel_domain="$1" node_name="$2" control_url="$3"
    local attempt=1 tmp=""

    tmp="$(mktemp)" || return 1
    while [ "$attempt" -le 8 ]; do
        if curl -fsS --max-time 15 "https://${panel_domain}/api/nodes" -o "$tmp" 2>/dev/null; then
            if python3 - "$tmp" "$node_name" "$control_url" <<'PY'
import json, sys
path, node_name, control_url = sys.argv[1], sys.argv[2], sys.argv[3].rstrip('/')
try:
    with open(path, 'r', encoding='utf-8') as f:
        nodes = json.load(f)
except Exception:
    raise SystemExit(1)
for node in nodes:
    metadata = node.get('metadata') or {}
    if metadata.get('node_name') != node_name:
        continue
    actual = (metadata.get('control_address') or '').rstrip('/')
    connection = metadata.get('connection_status')
    raise SystemExit(0 if actual == control_url and connection == 'connected' else 1)
raise SystemExit(1)
PY
            then
                rm -f "$tmp"
                return 0
            fi
        fi
        [ "$attempt" -lt 8 ] && sleep 5
        attempt=$((attempt + 1))
    done

    rm -f "$tmp"
    return 1
}

smite_foreign_gateway_write_state() {
    local domain="$1" panel_domain="$2" panel_ip="$3" control_path="$4"
    mkdir -p "$SMITE_STATE_DIR" || return 1
    chmod 0700 "$SMITE_STATE_DIR" || return 1
    cat > "$SMITE_FOREIGN_GATEWAY_STATE_FILE" <<EOF
# Managed by U-OPTI. No credentials are stored here.
SMITE_FOREIGN_GATEWAY_DOMAIN=$domain
SMITE_FOREIGN_PANEL_DOMAIN=$panel_domain
SMITE_FOREIGN_PANEL_SOURCE_IPV4=$panel_ip
SMITE_FOREIGN_CONTROL_PATH=$control_path
SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443
SMITE_FOREIGN_GATEWAY_MODE=https-control-path
EOF
    chmod 0600 "$SMITE_FOREIGN_GATEWAY_STATE_FILE"
}

smite_foreign_gateway_status() {
    local domain panel_domain node_name site control_path control_url panel_ip
    domain="$(smite_foreign_gateway_domain)"
    panel_domain="$(smite_foreign_gateway_panel_domain)"
    node_name="$(smite_foreign_gateway_node_name)"
    site="$(smite_foreign_gateway_site_path "$domain")"
    control_path="$(smite_foreign_gateway_state_value SMITE_FOREIGN_CONTROL_PATH "$SMITE_FOREIGN_GATEWAY_STATE_FILE")"
    panel_ip="$(smite_foreign_gateway_state_value SMITE_FOREIGN_PANEL_SOURCE_IPV4 "$SMITE_FOREIGN_GATEWAY_STATE_FILE")"
    control_url="https://${domain}${control_path}"

    clear
    echo "======================================"
    echo "     Smite Foreign Gateway Status"
    echo "======================================"
    echo
    echo "Foreign domain : ${domain:-Not detected}"
    echo "Panel domain   : ${panel_domain:-Not detected}"
    echo "Node name      : ${node_name:-Not detected}"
    echo "Panel source IP: ${panel_ip:-Not configured}"
    echo "Control path   : ${control_path:-Not configured}"
    echo

    command -v nginx >/dev/null 2>&1 && nginx -t >/dev/null 2>&1 \
        && echo "Nginx config   : Valid" || echo "Nginx config   : Not valid/installed"
    [ -n "$domain" ] && [ -s "/etc/letsencrypt/live/$domain/fullchain.pem" ] \
        && echo "Certificate    : Present" || echo "Certificate    : Not present"
    [ -n "$domain" ] && [ -f "$site" ] \
        && echo "HTTPS site     : Present" || echo "HTTPS site     : Not configured"
    ss -lnt 2>/dev/null | grep -Eq '[[:space:]][^[:space:]]*:443[[:space:]]' \
        && echo "Port 443       : Listening" || echo "Port 443       : Not listening"

    if [ -n "$domain" ] && [ -n "$control_path" ] && smite_foreign_gateway_verify_local "$domain" "$control_path" 2>/dev/null; then
        echo "Local control  : OK"
    else
        echo "Local control  : Not verified"
    fi

    if [ -f "$SMITE_NODE_DIR/.env" ]; then
        echo "Node control   : $(grep '^SMITE_CONTROL_ADDRESS=' "$SMITE_NODE_DIR/.env" | head -n1 | cut -d= -f2-)"
    fi

    if [ -n "$panel_domain" ] && [ -n "$node_name" ] && [ -n "$control_path" ] && \
       smite_foreign_gateway_verify_panel "$panel_domain" "$node_name" "$control_url"; then
        echo "Panel -> Node  : OK over HTTPS/443"
    else
        echo "Panel -> Node  : Not verified"
    fi

    echo
    echo "Security note  : Public TCP/8888 should be blocked by provider firewall or UFW."
    smite_foreign_gateway_pause
}

smite_foreign_gateway_configure() {
    local role domain panel_domain node_name site enabled control_path control_url
    local detected_ip stored_ip panel_ip panel_ip_input confirm
    local site_backup="" env_backup=""

    clear
    echo "======================================"
    echo "   Configure Smite Foreign Gateway"
    echo "======================================"
    echo

    [ "$(id -u)" -eq 0 ] || { echo "ERROR: Run U-OPTI as root."; smite_foreign_gateway_pause; return; }

    role="$(smite_foreign_gateway_role)"
    if [ "$role" != "foreign" ]; then
        echo "ERROR: This server is not registered in U-OPTI state as a Foreign Smite node."
        echo "Detected role: ${role:-Not set}"
        smite_foreign_gateway_pause
        return
    fi

    smite_foreign_gateway_require_node || { smite_foreign_gateway_pause; return; }

    domain="$(smite_foreign_gateway_domain)"
    panel_domain="$(smite_foreign_gateway_panel_domain)"
    node_name="$(smite_foreign_gateway_node_name)"

    smite_foreign_gateway_validate_domain "$domain" || { echo "ERROR: Valid Foreign domain not detected."; smite_foreign_gateway_pause; return; }
    smite_foreign_gateway_validate_domain "$panel_domain" || { echo "ERROR: Valid Panel domain not detected."; smite_foreign_gateway_pause; return; }
    [ -n "$node_name" ] || { echo "ERROR: Foreign node name not detected."; smite_foreign_gateway_pause; return; }

    site="$(smite_foreign_gateway_site_path "$domain")"
    enabled="$(smite_foreign_gateway_enabled_path "$domain")"
    control_path="$(smite_foreign_gateway_control_path "$site")"
    control_url="https://${domain}${control_path}"

    stored_ip="$(smite_foreign_gateway_state_value SMITE_FOREIGN_PANEL_SOURCE_IPV4 "$SMITE_FOREIGN_GATEWAY_STATE_FILE")"
    detected_ip="$(smite_foreign_gateway_resolve_panel_ipv4 "$panel_domain")"
    panel_ip="${stored_ip:-$detected_ip}"

    echo "Foreign domain : $domain"
    echo "Panel domain   : $panel_domain"
    echo "Node name      : $node_name"
    echo "Control path   : $control_path"
    echo
    echo "Panel source IPv4 is used only for the Nginx allow-list."
    echo "If the Panel domain is behind a CDN/proxy, enter the real Panel server IPv4 instead."
    echo
    read -rp "Panel source IPv4 [${panel_ip:-none}]: " panel_ip_input
    panel_ip="${panel_ip_input:-$panel_ip}"
    smite_foreign_gateway_validate_ipv4 "$panel_ip" || { echo "ERROR: A valid Panel source IPv4 is required."; smite_foreign_gateway_pause; return; }

    if [ -f "$site" ]; then
        echo
        echo "Existing Nginx site detected: $site"
        echo "U-OPTI will preserve the existing server content and only add/repair its managed Smite control location."
        echo "A timestamped backup is created before any edit."
    fi

    echo
    echo "Public entry   : HTTPS/TCP 443"
    echo "Node backend   : 127.0.0.1:8888"
    echo "Panel allow IP : $panel_ip"
    echo "Control URL    : $control_url"
    echo
    echo "U-OPTI does not enable or modify UFW automatically."
    echo "Public TCP/8888 must remain blocked after verification."
    echo
    read -rp "Configure / repair the Foreign 443 gateway? [y/N]: " confirm
    case "$confirm" in y|Y|yes|YES) ;; *) echo "Foreign gateway configuration cancelled."; sleep 1; return ;; esac

    echo
    smite_foreign_gateway_ensure_packages || { echo "ERROR: Could not prepare Nginx/Certbot."; smite_foreign_gateway_pause; return; }
    smite_foreign_gateway_ensure_certificate "$domain" || { echo "ERROR: Certificate preparation failed."; smite_foreign_gateway_pause; return; }

    mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled || { echo "ERROR: Could not prepare Nginx directories."; smite_foreign_gateway_pause; return; }

    if [ -f "$site" ]; then
        site_backup="${site}.u-opti-$(date +%Y%m%d-%H%M%S).bak"
        cp -a "$site" "$site_backup" || { echo "ERROR: Could not back up existing Foreign site."; smite_foreign_gateway_pause; return; }
    fi

    smite_foreign_gateway_write_site "$domain" "$panel_ip" "$control_path" "$site" || { echo "ERROR: Failed to update Foreign Nginx site without replacing existing content."; smite_foreign_gateway_pause; return; }
    ln -sfn "$site" "$enabled" || { echo "ERROR: Failed to enable Foreign Nginx site."; smite_foreign_gateway_pause; return; }

    if ! nginx -t || ! systemctl reload nginx; then
        echo "ERROR: Nginx validation/reload failed. Restoring previous Foreign site..."
        if [ -n "$site_backup" ]; then cp -a "$site_backup" "$site"; else rm -f "$site" "$enabled"; fi
        nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
        smite_foreign_gateway_pause
        return
    fi

    smite_foreign_gateway_write_renew_hook || echo "WARNING: Could not install Nginx certificate renewal hook."
    smite_foreign_gateway_verify_local "$domain" "$control_path" || { echo "ERROR: Local Foreign HTTPS/443 control verification failed."; smite_foreign_gateway_pause; return; }
    echo "Foreign local HTTPS/443 control: OK"

    smite_foreign_gateway_patch_control_metadata || { echo "ERROR: Could not prepare control-address overlay."; smite_foreign_gateway_pause; return; }

    env_backup="${SMITE_NODE_DIR}/.env.u-opti-before-foreign-gateway-$(date +%Y%m%d-%H%M%S).bak"
    smite_foreign_gateway_set_node_control_address "$control_url" "$env_backup" || { echo "ERROR: Could not update node control address."; smite_foreign_gateway_pause; return; }

    echo "Recreating Foreign Smite Node with persistent control_address metadata..."
    if ! smite_foreign_gateway_recreate_node; then
        echo "ERROR: Foreign node recreation failed; restoring previous node environment."
        cp -a "$env_backup" "$SMITE_NODE_DIR/.env"
        docker compose -f "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node >/dev/null 2>&1 || true
        smite_foreign_gateway_pause
        return
    fi

    smite_foreign_gateway_write_state "$domain" "$panel_domain" "$panel_ip" "$control_path" || echo "WARNING: Foreign gateway state could not be saved."

    echo "Waiting for Panel registration and Panel -> Foreign control verification..."
    if ! smite_foreign_gateway_verify_panel "$panel_domain" "$node_name" "$control_url"; then
        echo "ERROR: Panel could not verify the Foreign node through HTTPS/443."
        echo "Nginx and node configuration were kept for inspection/repair."
        smite_foreign_gateway_pause
        return
    fi

    [ -n "$site_backup" ] && cmp -s "$site_backup" "$site" && rm -f "$site_backup"
    [ -f "$env_backup" ] && cmp -s "$env_backup" "$SMITE_NODE_DIR/.env" && rm -f "$env_backup"

    echo
    echo "======================================"
    echo "     Smite Foreign Gateway Ready"
    echo "======================================"
    echo
    echo "Foreign URL   : https://$domain"
    echo "Public TCP    : 443"
    echo "Node backend  : 127.0.0.1:8888"
    echo "Panel control : $control_url"
    echo "Panel -> Node : OK over HTTPS/443"
    echo "Renewal hook  : installed"
    echo
    echo "Keep public TCP/8888 blocked by provider firewall or UFW."
    smite_foreign_gateway_pause
}

show_smite_foreign_gateway_menu() {
    while true; do
        clear
        echo "======================================"
        echo "      Smite Foreign 443 Gateway"
        echo "======================================"
        echo
        echo "1) Configure / Repair Foreign Gateway"
        echo "2) Foreign Gateway Status"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-2]: " choice
        case "$choice" in
            1) smite_foreign_gateway_configure ;;
            2) smite_foreign_gateway_status ;;
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
