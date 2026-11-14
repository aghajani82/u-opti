#!/bin/bash

# U-OPTI - Smite Foreign Node 443 Gateway
# Panel -> Foreign Node control over HTTPS/TCP 443.
# This gateway is for Standard/HTTPS mode only. Private Network mode uses EasyTier.

SMITE_NODE_DIR="${SMITE_NODE_DIR:-/opt/smite-node}"
SMITE_NODE_COMPOSE="${SMITE_NODE_COMPOSE:-$SMITE_NODE_DIR/docker-compose.yml}"
SMITE_OVERLAY_DIR="${SMITE_OVERLAY_DIR:-/opt/u-opti-smite}"
SMITE_STATE_DIR="${SMITE_STATE_DIR:-/etc/u-opti/smite}"
SMITE_STATE_FILE="${SMITE_STATE_FILE:-$SMITE_STATE_DIR/state.env}"
SMITE_FOREIGN_GATEWAY_STATE_FILE="$SMITE_STATE_DIR/foreign-gateway.env"
SMITE_FOREIGN_ACME_ROOT="${SMITE_FOREIGN_ACME_ROOT:-/var/www/u-opti-acme}"
SMITE_FOREIGN_RENEW_HOOK="/etc/letsencrypt/renewal-hooks/deploy/u-opti-nginx-reload"
SMITE_FOREIGN_3XUI_MARKER="# U-OPTI-MANAGED-3XUI-NGINX"
SMITE_FOREIGN_STANDALONE_MARKER="# Managed by U-OPTI - Smite Foreign HTTPS/443 gateway"

smite_foreign_gateway_pause() {
    # Only the explicitly selected one-choice Foreign flow may continue
    # without a separate manual menu pause. Standalone behavior unchanged.
    if [ "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:+yes}" = yes ]; then
        return 0
    fi
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

smite_foreign_gateway_connection_mode() {
    local value="standard"
    value="$(smite_foreign_gateway_state_value SMITE_CONNECTION_MODE "$SMITE_STATE_FILE")"
    [ -n "$value" ] || value="standard"
    printf '%s' "$value"
}

smite_foreign_gateway_private_ip() {
    smite_foreign_gateway_state_value SMITE_FOREIGN_PRIVATE_IP "$SMITE_STATE_FILE"
}

# Only the pinned, signed RC.1 Field Trial uses strict, paused Node semantics.
# Legacy v0.1.7 gateways must keep their original behavior.
smite_foreign_gateway_is_clean_rc() {
    # RC7 is a signed, paused/strict Node too. Never run legacy anonymous
    # registration, legacy Python overlays or /api/agent/status readiness.
    case "$(smite_foreign_gateway_state_value SMITE_MANAGED_VERSION "$SMITE_STATE_FILE")" in
        2.0.0-rc.1|2.0.0-rc.7) return 0 ;;
        *) return 1 ;;
    esac
}

smite_foreign_gateway_rc7_compose() {
    local project service files helper
    [ "$(smite_foreign_gateway_state_value SMITE_MANAGED_VERSION "$SMITE_STATE_FILE")" = "2.0.0-rc.7" ] || return 2
    project="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' smite-node 2>/dev/null)" || return 2
    service="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' smite-node 2>/dev/null)" || return 2
    files="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' smite-node 2>/dev/null)" || return 2
    if [[ ! "$project" =~ ^uopti_rc6_[0-9a-f]{32}$ ]] ||
       [ "$service" != smite-node ] || [ "$files" != "$SMITE_NODE_COMPOSE" ]; then
        echo "HOLD: RC7 Foreign Gateway Compose ownership or active files drifted." >&2
        return 2
    fi
    helper="${BASH_SOURCE[0]%/*}/smite-compose-safe.py"
    [ -f "$helper" ] && [ ! -L "$helper" ] || return 2
    COMPOSE_PROJECT_NAME="$project" python3 -B "$helper" "$SMITE_NODE_COMPOSE" "$@"
}

smite_foreign_gateway_require_rc_paused() {
    smite_foreign_gateway_is_clean_rc || return 0
    local env_file="$SMITE_NODE_DIR/.env"
    local identity="/etc/u-opti/smite/identities/node-identity.json"
    if [ -e "$identity" ] || [ -L "$identity" ]; then
        echo "HOLD: Paired RC Node requires separately reviewed signed gateway repair." >&2
        return 1
    fi
    if [ ! -f "$env_file" ] ||
       ! grep -qx 'SMITE_NODE_PANEL_AUTH_MODE=paused' "$env_file" ||
       ! grep -qx 'SMITE_AGENT_AUTH_MODE=strict' "$env_file" ||
       ! grep -qx 'SMITE_ENGINE_INVENTORY_MODE=managed' "$env_file"; then
        echo "HOLD: Foreign RC Node is not in the reviewed paused/strict/managed state." >&2
        return 1
    fi
}

smite_foreign_gateway_private_notice() {
    local private_ip=""
    private_ip="$(smite_foreign_gateway_private_ip)"

    clear
    echo "======================================"
    echo "   Foreign Gateway Not Required"
    echo "======================================"
    echo
    echo "Private Network mode is active on this Foreign node."
    echo "The Foreign HTTPS/443 gateway must NOT be configured in this mode."
    echo
    if [ -n "$private_ip" ]; then
        echo "Panel -> Foreign control : http://${private_ip}:8888"
    else
        echo "Panel -> Foreign control : EasyTier private network -> TCP/8888"
    fi
    echo "Foreign public 443       : existing 3x-UI / EasyTier Nginx entry"
    echo
    echo "Next gateway step belongs on the Iran/Panel server:"
    echo "Docker Management -> Smite Management -> 443 Gateway"
    echo "-> Configure / Repair Panel Gateway"
    echo
    echo "No Nginx, certificate, or Smite node settings were changed."
    smite_foreign_gateway_pause
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
    local domain="$1"
    local shared_site="/etc/nginx/sites-available/3xui-${domain}"

    if [ -f "$shared_site" ] && grep -Fq "$SMITE_FOREIGN_3XUI_MARKER" "$shared_site"; then
        printf '%s' "$shared_site"
        return 0
    fi

    printf '/etc/nginx/sites-available/%s' "$domain"
}

smite_foreign_gateway_enabled_path() {
    local site=""
    site="$(smite_foreign_gateway_site_path "$1")"
    printf '/etc/nginx/sites-enabled/%s' "$(basename "$site")"
}

smite_foreign_gateway_cleanup_stale_standalone() {
    local domain="$1" selected_site="$2"
    local stale_site="/etc/nginx/sites-available/${domain}"
    local stale_enabled="/etc/nginx/sites-enabled/${domain}"
    local backup=""

    [ "$selected_site" != "$stale_site" ] || return 0

    if [ ! -e "$stale_site" ] && [ ! -L "$stale_enabled" ]; then
        return 0
    fi

    if [ ! -e "$stale_site" ]; then
        echo "Removing stale Foreign gateway symlink: $stale_enabled"
        rm -f "$stale_enabled"
        return $?
    fi

    if ! grep -Fq "$SMITE_FOREIGN_STANDALONE_MARKER" "$stale_site"; then
        echo "ERROR: A conflicting non-U-OPTI standalone Nginx site exists:"
        echo "$stale_site"
        echo "Refusing to remove or overwrite it automatically."
        return 1
    fi

    backup="${stale_site}.u-opti-stale-$(date +%Y%m%d-%H%M%S).bak"
    cp -a "$stale_site" "$backup" || return 1
    rm -f "$stale_enabled" "$stale_site" || return 1

    echo "Removed stale standalone Smite Foreign vhost after backup:"
    echo "$backup"
    return 0
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
    local health_path="/api/agent/status"
    if smite_foreign_gateway_is_clean_rc; then
        # Strict Agent status requires HMAC; /healthz is loopback-only readiness.
        health_path="/healthz"
    fi
    curl --noproxy '*' -fsS --max-time 3 "http://127.0.0.1:8888${health_path}" >/dev/null 2>&1 || {
        echo "ERROR: Smite Node local readiness is unavailable at 127.0.0.1:8888."
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
    chmod 0644 "$SMITE_FOREIGN_ACME_ROOT/.well-known/acme-challenge/u-opti-smite-foreign-test" || return 1

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

smite_foreign_gateway_render_renew_hook() {
    cat <<'EOF'
#!/bin/sh
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
fi
EOF
}

smite_foreign_gateway_write_renew_hook() {
    local parent tmp=""
    parent="$(dirname -- "$SMITE_FOREIGN_RENEW_HOOK")" || return 1
    mkdir -p -- "$parent" || return 1
    # No in-place truncation of a shared renewal hook: a SIGKILL while
    # writing must leave EITHER its exact old content OR the sealed new
    # candidate that the existing Gateway stage can compensate safely.
    [ -d "$parent" ] && [ ! -L "$parent" ] &&
    [ ! -L "$SMITE_FOREIGN_RENEW_HOOK" ] &&
    { [ ! -e "$SMITE_FOREIGN_RENEW_HOOK" ] || [ -f "$SMITE_FOREIGN_RENEW_HOOK" ]; } || return 1
    tmp="$(mktemp "$parent/.u-opti-nginx-reload.XXXXXX")" || return 1
    if smite_foreign_gateway_render_renew_hook > "$tmp" &&
       chmod 0755 "$tmp" && sync -f "$tmp" &&
       mv -fT -- "$tmp" "$SMITE_FOREIGN_RENEW_HOOK" &&
       sync -f "$parent"; then
        return 0
    fi
    rm -f -- "$tmp" || true
    return 1
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
    local json="" attempt=1 health_path="/api/agent/status"
    if smite_foreign_gateway_is_clean_rc; then
        # Transport only: /healthz is loopback-only, so proxy readiness uses /.
        # Do not treat root HTTP 200 as signed Agent authorization.
        health_path="/"
    fi

    while [ "$attempt" -le 10 ]; do
        json="$(curl --noproxy '*' -fsS --max-time 10 --resolve "${domain}:443:127.0.0.1" \
            "https://${domain}${control_path}${health_path}" 2>/dev/null || true)"

        if [ -n "$json" ] && python3 - "$json" "$health_path" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if data.get("status") == "ok" and (sys.argv[2] != "/" or data.get("service") == "smite-node") else 1)
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

    # On the selected one-choice path, the exact Panel-issued control URL
    # was prebound by the existing node-files writer before its first boot.
    # Do not rewrite an unchanged env file, append a duplicate setting or
    # silently rotate the Node/Gateway scope. Independent repair unchanged.
    if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        [ "${SMITE_SELECTED_FRESH:-0}" = 1 ] &&
        [ "$(grep -c '^SMITE_CONTROL_ADDRESS=' "$env_file")" = 1 ] &&
        grep -Fxq "SMITE_CONTROL_ADDRESS=$control_url" "$env_file" || {
            echo 'HOLD: Prebound Foreign Node control URL does not match the Panel issue.' >&2
            return 2
        }
        echo 'UNIFIED_FOREIGN_CONTROL_ADDRESS=PREBOUND_UNCHANGED'
        return 0
    fi
    cp -a "$env_file" "$backup" || return 1
    if grep -q '^SMITE_CONTROL_ADDRESS=' "$env_file"; then
        sed -i "s|^SMITE_CONTROL_ADDRESS=.*|SMITE_CONTROL_ADDRESS=${control_url}|" "$env_file" || return 1
    else
        printf '\nSMITE_CONTROL_ADDRESS=%s\n' "$control_url" >> "$env_file" || return 1
    fi
}

smite_foreign_gateway_recreate_node() {
    # The one-choice fresh Foreign Node is already running with the exact
    # Panel-issued control URL. The existing Gateway need only verify the
    # running runtime (no --force-recreate and no key/identity churn).
    # An unexpected mismatch is a HOLD, never a fallback to recreation.
    if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        [ "${SMITE_SELECTED_FRESH:-0}" = 1 ] &&
        [ "$(smite_foreign_gateway_state_value SMITE_MANAGED_VERSION "$SMITE_STATE_FILE")" = "2.0.0-rc.7" ] &&
        smite_foreign_gateway_require_rc_paused &&
        smite_foreign_gateway_rc7_compose config --quiet || {
            echo 'HOLD: Existing selected Foreign Node is not owned/paused.' >&2
            return 2
        }
        local expected runtime expected_line
        expected="$(awk -F= '$1=="SMITE_CONTROL_ADDRESS" {print substr($0,index($0,"=")+1)}' "$SMITE_NODE_DIR/.env")"
        [[ "$expected" =~ ^https://[a-z0-9.-]+:443/smite-node/[a-f0-9]{32}$ ]] &&
        [ "$(grep -c '^SMITE_CONTROL_ADDRESS=' "$SMITE_NODE_DIR/.env")" = 1 ] || {
            echo 'HOLD: Foreign Node prebound control URL missing or duplicated.' >&2
            return 2
        }
        runtime="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' smite-node 2>/dev/null)" || return 2
        for expected_line in "SMITE_CONTROL_ADDRESS=$expected" \
            "SMITE_NODE_PANEL_AUTH_MODE=paused" \
            "SMITE_AGENT_AUTH_MODE=strict" \
            "SMITE_ENGINE_INVENTORY_MODE=managed"; do
            [ "$(printf '%s\n' "$runtime" | grep -Fxc "$expected_line")" = 1 ] || {
                echo 'HOLD: Running Foreign Node differs from the original paused control settings.' >&2
                return 2
            }
        done
        [ "$(printf '%s\n' "$runtime" | grep -c '^SMITE_CONTROL_ADDRESS=')" = 1 ] || return 2
        smite_foreign_gateway_wait_healthy 90 || return 2
        echo 'UNIFIED_FOREIGN_GATEWAY_NODE=RETAINED_NO_RECREATE'
        return 0
    fi
    if smite_foreign_gateway_is_clean_rc; then
        # Never install legacy panel_client.py overlay into the signed RC image.
        smite_foreign_gateway_require_rc_paused || return 1
        echo "Applying paused/strict RC Node control address (no legacy overlay)..."
        if [ "$(smite_foreign_gateway_state_value SMITE_MANAGED_VERSION "$SMITE_STATE_FILE")" = "2.0.0-rc.7" ]; then
            smite_foreign_gateway_rc7_compose up -d --no-build --force-recreate smite-node || return 1
        else
            docker compose -f "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node || return 1
        fi
        smite_foreign_gateway_wait_healthy 90
        return $?
    fi

    local env_file="$SMITE_NODE_DIR/.env"
    local overlay="$SMITE_OVERLAY_DIR/node/panel_client.py"
    local desired="" running="" mounted_source=""
    local started_iso="" started_epoch=0 overlay_mtime=0

    desired="$(awk -F= '$1 == "SMITE_CONTROL_ADDRESS" {print substr($0,index($0,"=")+1); exit}' "$env_file" 2>/dev/null)"

    running="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' smite-node 2>/dev/null \
        | awk -F= '$1 == "SMITE_CONTROL_ADDRESS" {print substr($0,index($0,"=")+1); exit}')"

    mounted_source="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/app/panel_client.py"}}{{.Source}}{{end}}{{end}}' smite-node 2>/dev/null || true)"

    started_iso="$(docker inspect -f '{{.State.StartedAt}}' smite-node 2>/dev/null || true)"
    started_epoch="$(date -d "$started_iso" +%s 2>/dev/null || printf '0')"

    if [ -f "$overlay" ]; then
        overlay_mtime="$(stat -c %Y "$overlay" 2>/dev/null || printf '0')"
    fi

    if [ -n "$desired" ] &&
       [ "$running" = "$desired" ] &&
       [ "$mounted_source" = "$overlay" ] &&
       [ -f "$overlay" ] &&
       grep -Fq 'SMITE_CONTROL_ADDRESS' "$overlay" &&
       [ "$started_epoch" -gt 0 ] &&
       [ "$overlay_mtime" -le "$started_epoch" ]; then

        echo "Foreign Smite Node configuration unchanged; recreation skipped."
        return 0
    fi

    echo "Recreating Foreign Smite Node because effective configuration changed..."
    docker compose -f "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node || return 1
    smite_foreign_gateway_wait_healthy 90
}

smite_foreign_gateway_verify_panel() {
    local panel_domain="$1" node_name="$2" control_url="$3"
    local attempt=1 tmp="" identity helper
    identity="/etc/u-opti/smite/identities/node-identity.json"
    helper="${BASH_SOURCE[0]%/*}/smite-foreign-gateway-signed-check.py"

    # An unpaired RC Node must NEVER use the legacy anonymous Panel discovery.
    if smite_foreign_gateway_is_clean_rc &&
       [ ! -e "$identity" ] && [ ! -L "$identity" ]; then
        return 1
    fi

    # After a Node identity is staged, NEVER downgrade to anonymous /api/nodes.
    # Signed verification reveals only this Node's own gateway-ready boolean.
    # In legacy installs without pairing, preserve the prior readiness probe
    # until both sides of the secure migration have been rolled out.
    if [ -e "$identity" ] || [ -L "$identity" ]; then
        [ -s "$helper" ] || return 1
        while [ "$attempt" -le 8 ]; do
            if python3 -B "$helper" \
                --panel-domain "$panel_domain" \
                --node-name "$node_name" \
                --control-url "$control_url"; then
                return 0
            fi
            [ "$attempt" -lt 8 ] && sleep 5
            attempt=$((attempt + 1))
        done
        return 1
    fi

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
    local staged
    mkdir -p "$SMITE_STATE_DIR" || return 1
    chmod 0700 "$SMITE_STATE_DIR" || return 1
    staged="$(mktemp "$SMITE_STATE_DIR/.foreign-gateway.XXXXXX")" || return 1
    if ! cat > "$staged" <<EOF
# Managed by U-OPTI. No credentials are stored here.
SMITE_FOREIGN_GATEWAY_DOMAIN=$domain
SMITE_FOREIGN_PANEL_DOMAIN=$panel_domain
SMITE_FOREIGN_PANEL_SOURCE_IPV4=$panel_ip
SMITE_FOREIGN_CONTROL_PATH=$control_path
SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443
SMITE_FOREIGN_GATEWAY_MODE=https-control-path
EOF
    then
        rm -f -- "$staged"
        return 1
    fi
    if ! sync -f "$staged" || ! mv -fT -- "$staged" "$SMITE_FOREIGN_GATEWAY_STATE_FILE"; then
        rm -f -- "$staged"
        return 1
    fi
    sync -f "$SMITE_STATE_DIR"
}

smite_foreign_gateway_status() {
    local domain panel_domain node_name site control_path control_url panel_ip

    if [ "$(smite_foreign_gateway_connection_mode)" = "private" ]; then
        smite_foreign_gateway_private_notice
        return
    fi

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
        if smite_foreign_gateway_is_clean_rc; then
            echo "Local transport: OK (root readiness only; NOT signed control)"
        else
            echo "Local control  : OK"
        fi
    else
        echo "Local control  : Not verified"
    fi

    if [ -f "$SMITE_NODE_DIR/.env" ]; then
        echo "Node control   : $(grep '^SMITE_CONTROL_ADDRESS=' "$SMITE_NODE_DIR/.env" | head -n1 | cut -d= -f2-)"
    fi

    if smite_foreign_gateway_is_clean_rc &&
       [ ! -e /etc/u-opti/smite/identities/node-identity.json ] &&
       [ ! -L /etc/u-opti/smite/identities/node-identity.json ]; then
        echo "Panel -> Node  : PENDING signed pairing (no anonymous fallback)"
    elif [ -n "$panel_domain" ] && [ -n "$node_name" ] && [ -n "$control_path" ] && \
         smite_foreign_gateway_verify_panel "$panel_domain" "$node_name" "$control_url"; then
        echo "Panel -> Node  : OK over signed HTTPS/443"
    else
        echo "Panel -> Node  : Not verified"
    fi

    echo
    echo "Security note  : Standard Node TCP/8888 must bind 127.0.0.1 and provider rules must block WAN."
    smite_foreign_gateway_pause
}

# Compensate ONLY a shared renewal hook touched by this exact Foreign
# Gateway attempt. Its candidate and preimage are retained in the same
# private stage journal, not a parallel backup/repair tool.
smite_foreign_gateway_restore_inline_hook() {
    local staged="$1" current="$SMITE_FOREIGN_RENEW_HOOK"
    [ -f "$staged/hook-candidate" ] && [ ! -L "$staged/hook-candidate" ] ||
        return 1
    [ ! -L "$current" ] && { [ ! -e "$current" ] || [ -f "$current" ]; } ||
        return 1
    if [ -e "$current" ] && ! cmp -s "$staged/hook-candidate" "$current"; then
        # Never erase edits from another service/admin after the snapshot.
        [ -f "$staged/hook" ] &&
        cmp -s "$staged/hook" "$current" || return 1
    fi
    if [ -f "$staged/hook-absent" ]; then
        [ ! -e "$staged/hook" ] || return 1
        rm -f -- "$current" || return 1
        [ ! -e "$current" ] && [ ! -L "$current" ]
    elif [ -f "$staged/hook" ] && [ ! -L "$staged/hook" ]; then
        [ ! -e "$staged/hook-absent" ] || return 1
        cp -a -- "$staged/hook" "$current" &&
        cmp -s -- "$staged/hook" "$current"
    else
        return 1
    fi
}

smite_foreign_gateway_restore_inline_site() {
    local site="$1" enabled="$2" backup="$3" original_link="$4" failed=0
    if [ -n "$backup" ]; then
        cp -a -- "$backup" "$site" && cmp -s -- "$backup" "$site" || failed=1
    else
        rm -f -- "$site" || failed=1
    fi
    if [ -n "$original_link" ]; then
        ln -sfnT -- "$original_link" "$enabled" && [ "$(readlink -- "$enabled")" = "$original_link" ] || failed=1
    else
        rm -f -- "$enabled" || failed=1
    fi
    [ "$failed" = 0 ] && nginx -t && systemctl reload nginx
}

# Keep the rendered site and original bytes together so a retry can prove
# which changes belonged to this stage, even after the shell was killed.
smite_foreign_gateway_inline_stage() (
    local domain="$1" panel_domain="$2" panel_ip="$3" control_path="$4"
    local control_url="$5" site="$6" enabled="$7" lock staging work="" scratch="" backup="" original_link=""
    staging="$SMITE_STATE_DIR/foreign-gateway.pending"
    [ -d "$SMITE_STATE_DIR" ] && [ ! -L "$SMITE_STATE_DIR" ] &&
    [ "$(stat -c '%u:%a' "$SMITE_STATE_DIR")" = "${EUID}:700" ] || return 2
    [ ! -L "$SMITE_STATE_DIR/foreign-gateway.lock" ] || return 2
    umask 077
    exec {lock}>> "$SMITE_STATE_DIR/foreign-gateway.lock" || return 2
    flock -n "$lock" || return 2
    [ ! -e "$SMITE_FOREIGN_GATEWAY_STATE_FILE" ] && [ ! -L "$SMITE_FOREIGN_GATEWAY_STATE_FILE" ] || return 2
    # The renew hook is shared with other services. Reject an unrelated,
    # changed or symlinked hook BEFORE modifying the Foreign vhost.
    [ ! -L "$SMITE_FOREIGN_RENEW_HOOK" ] &&
    { [ ! -e "$SMITE_FOREIGN_RENEW_HOOK" ] || [ -f "$SMITE_FOREIGN_RENEW_HOOK" ]; } || return 2

    if [ -e "$staging" ] || [ -L "$staging" ]; then
        [ -d "$staging" ] && [ ! -L "$staging" ] &&
        [ "$(stat -c '%u:%a' "$staging")" = "${EUID}:700" ] &&
        [ -f "$staging/scope" ] && [ ! -L "$staging/scope" ] &&
        cmp -s "$staging/scope" <(printf '%s\n' "$control_url" "$site" "$enabled") &&
        [ -f "$staging/candidate" ] && [ ! -L "$staging/candidate" ] &&
        [ -f "$staging/link" ] && [ ! -L "$staging/link" ] || return 2
        [ ! -L "$staging/site" ] &&
        [ -f "$staging/hook-candidate" ] && [ ! -L "$staging/hook-candidate" ] &&
        { [ -f "$staging/hook-absent" ] || [ -f "$staging/hook" ]; } || return 2
        if [ -e "$staging/site" ]; then
            [ -f "$staging/site" ] || return 2
            backup="$staging/site"
        fi
        original_link="$(cat "$staging/link")" || return 2
        if [ -L "$site" ] || { [ -e "$site" ] && [ ! -f "$site" ]; } ||
           { [ -e "$enabled" ] && [ ! -L "$enabled" ]; }; then
            return 2
        fi
        if [ -f "$site" ] && ! cmp -s "$staging/candidate" "$site" &&
            { [ -z "$backup" ] || ! cmp -s "$backup" "$site"; }; then
            echo 'HOLD: Foreign Gateway site changed outside the interrupted stage.' >&2
            return 2
        fi
        if [ -L "$enabled" ]; then
            local current_link
            current_link="$(readlink -- "$enabled")" || return 2
            [ "$current_link" = "$site" ] || [ "$current_link" = "$original_link" ] || return 2
        fi
        # Preflight both compensations before restoring ANY target:
        # an externally edited hook must not cause a partial site restore.
        if [ -e "$SMITE_FOREIGN_RENEW_HOOK" ] &&
            ! cmp -s "$staging/hook-candidate" "$SMITE_FOREIGN_RENEW_HOOK" &&
            { [ ! -f "$staging/hook" ] || ! cmp -s "$staging/hook" "$SMITE_FOREIGN_RENEW_HOOK"; }; then
            echo 'HOLD: Shared renewal hook changed outside the Foreign stage.' >&2
            return 2
        fi
        smite_foreign_gateway_restore_inline_site "$site" "$enabled" "$backup" "$original_link" &&
        smite_foreign_gateway_restore_inline_hook "$staging" || return 2
        rm -rf -- "$staging" || return 2
        echo 'FOREIGN_GATEWAY_SITE=ROLLED_BACK_AFTER_INTERRUPTION'
        backup=""
    fi

    [ ! -L "$site" ] && { [ ! -e "$site" ] || [ -f "$site" ]; } &&
    { [ ! -e "$enabled" ] || [ -L "$enabled" ]; } || return 2
    scratch="$(mktemp -d "$SMITE_STATE_DIR/.foreign-gateway-stage.XXXXXX")" || return 2
    trap 'if [ -n "$scratch" ]; then rm -rf -- "$scratch"; fi; if [ -n "$scratch" ]; then rm -f -- "$scratch"; fi' EXIT
    if [ -L "$enabled" ]; then
        readlink -- "$enabled" > "$scratch/link" || return 2
    else
        : > "$scratch/link" || return 2
    fi
    original_link="$(cat "$scratch/link")" || return 2
    smite_foreign_gateway_render_renew_hook > "$scratch/hook-candidate" || return 2
    if [ -e "$SMITE_FOREIGN_RENEW_HOOK" ]; then
        # Only the canonical U-OPTI Nginx reload hook may be shared.
        # Never replace or silently roll back an independent hook.
        cmp -s "$scratch/hook-candidate" "$SMITE_FOREIGN_RENEW_HOOK" || {
            echo 'HOLD: Existing independent certificate renewal hook must be preserved.' >&2
            return 2
        }
        cp -a -- "$SMITE_FOREIGN_RENEW_HOOK" "$scratch/hook" || return 2
    else
        : > "$scratch/hook-absent" || return 2
    fi
    if [ -f "$site" ]; then
        cp -a -- "$site" "$scratch/site" && cp -a -- "$site" "$scratch/candidate" || return 2
        backup="$staging/site"
    fi
    smite_foreign_gateway_write_site "$domain" "$panel_ip" "$control_path" "$scratch/candidate" || return 2
    printf '%s\n' "$control_url" "$site" "$enabled" > "$scratch/scope" || return 2
    sync -f "$scratch" && mv -T -- "$scratch" "$staging" && sync -f "$SMITE_STATE_DIR" || return 2

    # Rename a complete file on the destination filesystem. A crash can
    # leave only the preimage or the exact staged candidate at the site.
    work="$(mktemp "${site}.u-opti-write.XXXXXX")" || return 2
    if cp -a -- "$staging/candidate" "$work" &&
       cmp -s "$staging/candidate" "$work" && sync -f "$work" &&
       mv -fT -- "$work" "$site" && ln -sfnT -- "$site" "$enabled" &&
       sync -f "$(dirname "$site")" && sync -f "$(dirname "$enabled")" &&
       nginx -t && systemctl reload nginx &&
       smite_foreign_gateway_verify_local "$domain" "$control_path" &&
       smite_foreign_gateway_set_node_control_address "$control_url" "" &&
       smite_foreign_gateway_recreate_node &&
       smite_foreign_gateway_write_renew_hook &&
       [ -f "$SMITE_FOREIGN_RENEW_HOOK" ] &&
       cmp -s "$staging/hook-candidate" "$SMITE_FOREIGN_RENEW_HOOK" &&
       smite_foreign_gateway_write_state "$domain" "$panel_domain" "$panel_ip" "$control_path"; then
        rm -rf -- "$staging" || return 2
        echo 'FOREIGN_RC_GATEWAY_TRANSPORT=READY_ROOT_ONLY'
        echo 'FOREIGN_RC_NODE_RUNTIME=PAUSED_STRICT'
        echo 'FOREIGN_RC_SIGNED_CONTROL=HOLD_PENDING_PAIRING'
        return 0
    fi
    if [ -e "$SMITE_FOREIGN_GATEWAY_STATE_FILE" ] || [ -L "$SMITE_FOREIGN_GATEWAY_STATE_FILE" ]; then
        echo 'HOLD: Foreign Gateway receipt exists but durability was not confirmed; verify on retry.' >&2
        return 2
    fi
    if smite_foreign_gateway_restore_inline_site "$site" "$enabled" "$backup" "$original_link" &&
        smite_foreign_gateway_restore_inline_hook "$staging" &&
        rm -rf -- "$staging"; then
        echo 'FOREIGN_GATEWAY_SITE=ROLLED_BACK' >&2
    else
        echo 'CRITICAL: Foreign Gateway site rollback could not be verified.' >&2
    fi
    return 2
)

smite_foreign_gateway_configure() {
    local role domain panel_domain node_name site enabled control_path control_url
    local detected_ip stored_ip panel_ip panel_ip_input confirm
    local site_backup="" env_backup="" module_dir=""

    # Never use an untrusted environment path to authorize the Gateway.
    # This branch is opt-in for an owned FRESH RC7 install; it validates
    # the private exact signed Panel packet before editing Nginx/Compose.
    if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        [ "${SMITE_SELECTED_FRESH:-0}" = 1 ] &&
        [ "$(smite_foreign_gateway_state_value SMITE_MANAGED_VERSION "$SMITE_STATE_FILE")" = "2.0.0-rc.7" ] || {
            echo 'HOLD: Unified Foreign Gateway requires a fresh signed RC7 Node.' >&2
            return 2
        }
    fi

    # Keep prior Sanaei/Node progress visible in the same approved
    # option-2 installation. Independent Gateway repair keeps its UI.
    if [ -z "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        clear
    fi
    echo "======================================"
    echo "   Configure Smite Foreign Gateway"
    echo "======================================"
    echo

    [ "$(id -u)" -eq 0 ] || { echo "ERROR: Run U-OPTI as root."; smite_foreign_gateway_pause; return 2; }

    role="$(smite_foreign_gateway_role)"
    if [ "$role" != "foreign" ]; then
        echo "ERROR: This server is not registered in U-OPTI state as a Foreign Smite node."
        echo "Detected role: ${role:-Not set}"
        smite_foreign_gateway_pause
        return 2
    fi

    if [ "$(smite_foreign_gateway_connection_mode)" = "private" ]; then
        if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
            echo 'HOLD: Unified signed Foreign enrollment requires Standard HTTPS/443.' >&2
            return 2
        fi
        smite_foreign_gateway_private_notice
        return
    fi

    smite_foreign_gateway_require_node || { smite_foreign_gateway_pause; return 2; }
    smite_foreign_gateway_require_rc_paused || { smite_foreign_gateway_pause; return 2; }

    domain="$(smite_foreign_gateway_domain)"
    panel_domain="$(smite_foreign_gateway_panel_domain)"
    node_name="$(smite_foreign_gateway_node_name)"

    smite_foreign_gateway_validate_domain "$domain" || { echo "ERROR: Valid Foreign domain not detected."; smite_foreign_gateway_pause; return 2; }
    smite_foreign_gateway_validate_domain "$panel_domain" || { echo "ERROR: Valid Panel domain not detected."; smite_foreign_gateway_pause; return 2; }
    [ -n "$node_name" ] || { echo "ERROR: Foreign node name not detected."; smite_foreign_gateway_pause; return 2; }

    site="$(smite_foreign_gateway_site_path "$domain")"
    enabled="$(smite_foreign_gateway_enabled_path "$domain")"
    if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        module_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || return 2
        [ -f "$module_dir/smite-unified-foreign-gateway-plan.py" ] &&
        [ ! -L "$module_dir/smite-unified-foreign-gateway-plan.py" ] || return 2
        control_path="$(python3 -B "$module_dir/smite-unified-foreign-gateway-plan.py" \
            --packet-file "$UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE" \
            --state-file "$SMITE_STATE_FILE" \
            --gateway-state-file "$SMITE_FOREIGN_GATEWAY_STATE_FILE" \
            --site-file "$site")" || {
                echo 'HOLD: Gateway path does not match the Panel-issued one-use grant.' >&2
                return 2
            }
        [[ "$control_path" =~ ^/smite-node/[a-f0-9]{32}$ ]] || return 2
        echo 'UNIFIED_FOREIGN_GATEWAY_PATH=VERIFIED_PANEL_SCOPE'
    else
        control_path="$(smite_foreign_gateway_control_path "$site")"
    fi
    # The exact, already-validated Panel grant uses an explicit :443.
    # Preserve it byte-for-byte in the one-choice path. Standalone
    # Gateway repair keeps its historic unqualified spelling.
    if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        control_url="https://${domain}:443${control_path}"
    else
        control_url="https://${domain}${control_path}"
    fi

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
    smite_foreign_gateway_validate_ipv4 "$panel_ip" || { echo "ERROR: A valid Panel source IPv4 is required."; smite_foreign_gateway_pause; return 2; }

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
    if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        # The fresh one-choice selection was already explicitly approved.
        # The exact private Panel grant, role, paused Node and source IPv4
        # were validated above. Do not ask for a SECOND menu confirmation.
        # Independent option-6 Gateway repair keeps its original prompt.
        echo 'UNIFIED_FOREIGN_GATEWAY=CONTINUING_APPROVED_FRESH_INSTALL'
    else
        read -rp "Configure / repair the Foreign 443 gateway? [y/N]: " confirm
        case "$confirm" in y|Y|yes|YES) ;; *) echo "Foreign gateway configuration cancelled."; sleep 1; return 2 ;; esac
    fi

    echo
    smite_foreign_gateway_ensure_packages || { echo "ERROR: Could not prepare Nginx/Certbot."; smite_foreign_gateway_pause; return 2; }
    smite_foreign_gateway_ensure_certificate "$domain" || { echo "ERROR: Certificate preparation failed."; smite_foreign_gateway_pause; return 2; }

    mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled || { echo "ERROR: Could not prepare Nginx directories."; smite_foreign_gateway_pause; return 2; }

    if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        smite_foreign_gateway_inline_stage "$domain" "$panel_domain" "$panel_ip" "$control_path" "$control_url" "$site" "$enabled"
        return $?
    fi

    smite_foreign_gateway_cleanup_stale_standalone "$domain" "$site" || { smite_foreign_gateway_pause; return 2; }
    if [ -f "$site" ]; then
        site_backup="${site}.u-opti-$(date +%Y%m%d-%H%M%S).bak"
        cp -a "$site" "$site_backup" || { echo "ERROR: Could not back up existing Foreign site."; smite_foreign_gateway_pause; return 2; }
    fi

    smite_foreign_gateway_write_site "$domain" "$panel_ip" "$control_path" "$site" || { echo "ERROR: Failed to update Foreign Nginx site without replacing existing content."; smite_foreign_gateway_pause; return 2; }
    ln -sfn "$site" "$enabled" || { echo "ERROR: Failed to enable Foreign Nginx site."; smite_foreign_gateway_pause; return 2; }

    if ! nginx -t || ! systemctl reload nginx; then
        echo "ERROR: Nginx validation/reload failed. Restoring previous Foreign site..."
        if [ -n "$site_backup" ]; then cp -a "$site_backup" "$site"; else rm -f "$site" "$enabled"; fi
        nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
        smite_foreign_gateway_pause
        return 2
    fi

    if ! smite_foreign_gateway_write_renew_hook; then
        echo 'WARNING: Could not install Nginx certificate renewal hook.'
    fi
    smite_foreign_gateway_verify_local "$domain" "$control_path" || { echo "ERROR: Local Foreign HTTPS/443 control verification failed."; smite_foreign_gateway_pause; return 2; }
    echo "Foreign local HTTPS/443 control: OK"

    if smite_foreign_gateway_is_clean_rc; then
        echo "FOREIGN_RC_LEGACY_METADATA_OVERLAY=SKIPPED"
    else
        smite_foreign_gateway_patch_control_metadata || { echo "ERROR: Could not prepare control-address overlay."; smite_foreign_gateway_pause; return 2; }
    fi

    env_backup="${SMITE_NODE_DIR}/.env.u-opti-before-foreign-gateway-$(date +%Y%m%d-%H%M%S).bak"
    smite_foreign_gateway_set_node_control_address "$control_url" "$env_backup" || { echo "ERROR: Could not update node control address."; smite_foreign_gateway_pause; return 2; }

    echo "Applying Foreign Smite Node control metadata..."
    if ! smite_foreign_gateway_recreate_node; then
        echo "ERROR: Foreign node control application failed; restoring previous node environment."
        cp -a "$env_backup" "$SMITE_NODE_DIR/.env" || return 2
        if [ "$(smite_foreign_gateway_state_value SMITE_MANAGED_VERSION "$SMITE_STATE_FILE")" = "2.0.0-rc.7" ]; then
            smite_foreign_gateway_rc7_compose up -d --no-build --force-recreate smite-node >/dev/null 2>&1 ||
                echo "CRITICAL: RC7 foreign gateway Node rollback could not be verified." >&2
        else
            docker compose -f "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node >/dev/null 2>&1 || true
        fi
        smite_foreign_gateway_pause
        return 2
    fi

    if ! smite_foreign_gateway_write_state "$domain" "$panel_domain" "$panel_ip" "$control_path"; then
        echo 'WARNING: Foreign gateway state could not be saved.'
    fi

    if smite_foreign_gateway_is_clean_rc; then
        echo
        echo "FOREIGN_RC_GATEWAY_TRANSPORT=READY_ROOT_ONLY"
        echo "FOREIGN_RC_NODE_RUNTIME=PAUSED_STRICT"
        echo "FOREIGN_RC_SIGNED_CONTROL=HOLD_PENDING_PAIRING"
        echo "No signed HMAC or Panel registration has been claimed."
        smite_foreign_gateway_pause
        return 0
    fi

    echo "Waiting for Panel registration and Panel -> Foreign control verification..."
    if ! smite_foreign_gateway_verify_panel "$panel_domain" "$node_name" "$control_url"; then
        echo "ERROR: Panel could not verify the Foreign node through HTTPS/443."
        echo "Nginx and node configuration were kept for inspection/repair."
        smite_foreign_gateway_pause
        return 2
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
    return 0
}

# Opt-in sharing of the *existing* managed Sanaei panel location.
# Subscription and Xray forwarding stay on their original vhost.
smite_foreign_gateway_prepare_shared_sanaei_site() {
    python3 - "$1" "$2" <<'PY_SHARED_SANAEI'
from pathlib import Path
import os, re, sys, tempfile

target, source = map(Path, sys.argv[1:])
if not target.is_file() or not source.is_file() or target.resolve() == source.resolve():
    raise SystemExit("ERROR: Expected separate existing Nginx sites")
old, original = target.read_text(), source.read_text()
if not old.startswith("# Managed by U-OPTI - Smite Foreign HTTPS/443 gateway"):
    raise SystemExit("ERROR: Target is not a managed Foreign gateway")
if "# U-OPTI-MANAGED-3XUI-NGINX" not in original.splitlines()[:5]:
    raise SystemExit("ERROR: Sanaei source is not U-OPTI-managed")
bases = re.findall(r'(?m)^# Web Base Path:\s*(/[A-Za-z0-9_-]{6,80}/)\s*$', original)
if len(bases) != 1:
    raise SystemExit("ERROR: Expected exactly one managed Sanaei panel base path")
base = bases[0]

def block(kind, path):
    lines = original.splitlines(keepends=True)
    wanted = re.compile(r'^\s*location\s+' + re.escape(kind) + r'\s+' + re.escape(path) + r'\s*\{\s*$')
    starts = [i for i, line in enumerate(lines) if wanted.fullmatch(line.rstrip("\n"))]
    if len(starts) != 1:
        raise SystemExit("ERROR: Unique Sanaei location not found: " + path)
    depth, start = 0, starts[0]
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0:
            return "".join(lines[start:i+1])
    raise SystemExit("ERROR: Unterminated Sanaei location")

redirect = block("=", base.rstrip("/"))
panel = block("^~", base)
if not re.search(r'(?m)^\s*return\s+301\s+' + re.escape(base) + r';\s*$', redirect):
    raise SystemExit("ERROR: Unexpected Sanaei redirect")
upstreams = re.findall(r'(?m)^\s*proxy_pass\s+http://127\.0\.0\.1:(\d{1,5});\s*$', panel)
if len(upstreams) != 1 or not 1 <= int(upstreams[0]) <= 65535:
    raise SystemExit("ERROR: Sanaei panel upstream must be local TCP")
begin = "    # BEGIN U-OPTI SHARED SANAEI PANEL"
end = "    # END U-OPTI SHARED SANAEI PANEL"
managed = begin + "\n" + redirect + "\n" + panel + "\n" + end
if old.count(begin) != old.count(end) or old.count(begin) > 1:
    raise SystemExit("ERROR: Invalid existing shared panel markers")
if begin in old:
    start = old.index(begin)
    finish = old.index(end, start) + len(end)
    updated = old[:start] + managed + old[finish:]
else:
    if re.search(
        r'(?m)^\s*location\s+(?:=|\^~)\s+' + re.escape(base.rstrip('/')) + r'/?\s*\{',
        old
    ):
        raise SystemExit("ERROR: An unmanaged Sanaei panel route already exists")
    anchor = "    location / { try_files $uri $uri/ =404; }"
    if old.count(anchor) != 1:
        raise SystemExit("ERROR: Unexpected Foreign gateway layout")
    updated = old.replace(anchor, managed + "\n\n" + anchor, 1)

if updated != old:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent,
        prefix=".shared-sanaei-", delete=False
    ) as tmp:
        tmp.write(updated)
        staged = Path(tmp.name)
    os.chmod(staged, target.stat().st_mode & 0o777)
    os.replace(staged, target)
    print("Sanaei management route shared; other proxy paths preserved")
else:
    print("Shared Sanaei management route already up to date")
PY_SHARED_SANAEI
}

smite_foreign_gateway_share_sanaei() {
    local domain target source="" detected="" count=0 choice route backup smite_path status attempt ok=0
    if [ "$(id -u)" -ne 0 ] || [ "$(smite_foreign_gateway_role)" != "foreign" ]; then
        echo "ERROR: Run on a Foreign Smite server as root."
        smite_foreign_gateway_pause
        return
    fi

    domain="$(smite_foreign_gateway_domain)"
    target="$(smite_foreign_gateway_site_path "$domain")"
    if ! smite_foreign_gateway_validate_domain "$domain" || [ ! -f "$target" ]; then
        echo "ERROR: Foreign HTTPS/443 gateway not ready."
        smite_foreign_gateway_pause
        return
    fi

    echo "===== Existing managed Sanaei Nginx sites ====="
    for source in /etc/nginx/sites-enabled/3xui-*; do
        if [ -f "$source" ] && grep -Fq '# U-OPTI-MANAGED-3XUI-NGINX' "$source"; then
            echo "$source"
            detected="$source"
            count=$((count + 1))
        fi
    done
    if [ "$count" -eq 0 ]; then
        echo "ERROR: No managed Sanaei site found."
        smite_foreign_gateway_pause
        return
    fi
    echo
    read -rp "Source site path [auto if only one]: " choice
    source="$choice"
    if [ -z "$source" ] && [ "$count" -eq 1 ]; then source="$detected"; fi
    if [[ "$source" != /etc/nginx/sites-enabled/3xui-* ]] || [ ! -f "$source" ]; then
        echo "ERROR: Select a listed Sanaei Nginx site."
        smite_foreign_gateway_pause
        return
    fi
    route="$(sed -nE 's@^# Web Base Path: (/[A-Za-z0-9_-]+/)$@\1@p' "$source" | head -n 1)"
    if [ -z "$route" ]; then
        echo "ERROR: Cannot identify Sanaei panel base path."
        smite_foreign_gateway_pause
        return
    fi
    echo "Proposed shared panel: https://$domain$route"
    echo "Only the management route will be added. Subscription and Xray paths remain untouched."
    read -rp "Confirm sharing this Sanaei panel? [y/N]: " choice
    case "$choice" in y|Y|yes|YES) ;; *) echo "Cancelled."; smite_foreign_gateway_pause; return ;; esac

    backup="$target.before-shared-sanaei-$(date -u +%Y%m%d-%H%M%S).bak"
    cp -a "$target" "$backup" || { smite_foreign_gateway_pause; return; }
    if ! smite_foreign_gateway_prepare_shared_sanaei_site "$target" "$source" ||
       ! nginx -t || ! systemctl reload nginx; then
        cp -a "$backup" "$target"
        nginx -t && systemctl reload nginx || true
        echo "ERROR: Shared panel preparation failed; original Nginx site restored."
        smite_foreign_gateway_pause
        return
    fi

    smite_path="$(smite_foreign_gateway_control_path "$target")"
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        status="$(curl --noproxy '*' -sS --max-time 10 \
            --resolve "$domain:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
            "https://$domain$route" 2>/dev/null || true)"
        if [ "$status" = "200" ] &&
           smite_foreign_gateway_verify_local "$domain" "$smite_path" >/dev/null 2>&1; then
            ok=1
            break
        fi
        sleep 2
    done
    if [ "$ok" -ne 1 ]; then
        cp -a "$backup" "$target"
        nginx -t && systemctl reload nginx || true
        echo "ERROR: Validation failed; previous Nginx site restored."
    else
        echo "SUCCESS: Sanaei and Smite share https://$domain:443"
        echo "Old Sanaei domain, subscriptions, FRP and Xray remain unchanged."
    fi
    smite_foreign_gateway_pause
}

show_smite_foreign_gateway_menu() {
    if [ "$(smite_foreign_gateway_connection_mode)" = "private" ]; then
        smite_foreign_gateway_private_notice
        return
    fi

    while true; do
        clear
        echo "======================================"
        echo "  Smite Foreign 443 Gateway (Standard)"
        echo "======================================"
        echo
        echo "1) Configure / Repair Foreign Gateway"
        echo "2) Foreign Gateway Status"
        echo "3) Share Existing Sanaei Panel"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-3]: " choice
        case "$choice" in
            1) smite_foreign_gateway_configure ;;
            2) smite_foreign_gateway_status ;;
            3) smite_foreign_gateway_share_sanaei ;;
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
