#!/bin/bash

# U-OPTI - Smite 443 Gateway Management
# Host Nginx + Let's Encrypt webroot + stream/SNI gateway for Smite Panel.

SMITE_PANEL_DIR="${SMITE_PANEL_DIR:-/opt/smite}"
SMITE_NODE_DIR="${SMITE_NODE_DIR:-/opt/smite-node}"
SMITE_PANEL_COMPOSE="${SMITE_PANEL_COMPOSE:-$SMITE_PANEL_DIR/docker-compose.yml}"
SMITE_NODE_COMPOSE="${SMITE_NODE_COMPOSE:-$SMITE_NODE_DIR/docker-compose.yml}"
SMITE_STATE_DIR="${SMITE_STATE_DIR:-/etc/u-opti/smite}"
SMITE_STATE_FILE="${SMITE_STATE_FILE:-$SMITE_STATE_DIR/state.env}"
SMITE_GATEWAY_STATE_FILE="$SMITE_STATE_DIR/gateway.env"
SMITE_GATEWAY_BACKEND_CONF="/etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
SMITE_GATEWAY_STREAM_CONF="/etc/nginx/modules-enabled/99-u-opti-smite-stream.conf"
SMITE_GATEWAY_MAP_FILE="/etc/nginx/u-opti-smite-stream-map.conf"
SMITE_GATEWAY_ACME_ROOT="/var/www/u-opti-acme"
SMITE_GATEWAY_RENEW_HOOK="/etc/letsencrypt/renewal-hooks/deploy/u-opti-nginx-reload"
SMITE_GATEWAY_DB="${SMITE_GATEWAY_DB:-$SMITE_PANEL_DIR/panel/data/smite.db}"
SMITE_GATEWAY_PRIVATE_DATA_PORT="${SMITE_GATEWAY_PRIVATE_DATA_PORT:-9443}"

# Runtime transaction state. These are intentionally not persisted.
SMITE_GATEWAY_PRIVATE_DB_BACKUP=""
SMITE_GATEWAY_PRIVATE_BACKHAUL_CHANGED=0

smite_gateway_pause() {
    echo
    read -rp "Press Enter to return..."
}

smite_gateway_validate_domain() {
    [[ "$1" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]
}

smite_gateway_panel_domain() {
    local value=""

    if [ -f "$SMITE_STATE_FILE" ]; then
        value="$(awk -F= '$1 == "SMITE_PANEL_DOMAIN" {print substr($0, index($0,"=")+1); exit}' "$SMITE_STATE_FILE")"
    fi

    if [ -z "$value" ] && [ -f "$SMITE_PANEL_DIR/.env" ]; then
        value="$(awk -F= '$1 == "PANEL_DOMAIN" {print substr($0, index($0,"=")+1); exit}' "$SMITE_PANEL_DIR/.env")"
    fi

    printf '%s' "$value"
}

smite_gateway_connection_mode() {
    local value="standard"

    if [ -f "$SMITE_STATE_FILE" ]; then
        value="$(awk -F= '$1 == "SMITE_CONNECTION_MODE" {print substr($0, index($0,"=")+1); exit}' "$SMITE_STATE_FILE")"
    fi

    [ -n "$value" ] || value="standard"
    printf '%s' "$value"
}

smite_gateway_node_name() {
    local value=""

    if [ -f "$SMITE_STATE_FILE" ]; then
        value="$(awk -F= '$1 == "SMITE_NODE_NAME" {print substr($0, index($0,"=")+1); exit}' "$SMITE_STATE_FILE")"
    fi

    if [ -z "$value" ] && [ -f "$SMITE_NODE_DIR/.env" ]; then
        value="$(awk -F= '$1 == "NODE_NAME" {print substr($0, index($0,"=")+1); exit}' "$SMITE_NODE_DIR/.env")"
    fi

    printf '%s' "$value"
}

smite_gateway_container_healthy() {
    local container="$1"
    local state health

    state="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || true)"

    [ "$state" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "none" ]; }
}

smite_gateway_wait_healthy() {
    local container="$1"
    local timeout="${2:-90}"
    local elapsed=0

    while [ "$elapsed" -lt "$timeout" ]; do
        if smite_gateway_container_healthy "$container"; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    return 1
}

smite_gateway_require_panel() {
    command -v docker >/dev/null 2>&1 || {
        echo "ERROR: Docker is not installed."
        return 1
    }

    [ -f "$SMITE_PANEL_COMPOSE" ] || {
        echo "ERROR: Smite Panel compose file was not found:"
        echo "$SMITE_PANEL_COMPOSE"
        return 1
    }

    smite_gateway_container_healthy smite-panel || {
        echo "ERROR: smite-panel is not healthy."
        return 1
    }

    curl -fsS --max-time 3 http://127.0.0.1:8000/api/status >/dev/null 2>&1 || {
        echo "ERROR: Smite Panel API is not reachable at 127.0.0.1:8000."
        return 1
    }
}

smite_gateway_ensure_packages() {
    local packages=()

    command -v nginx >/dev/null 2>&1 || packages+=(nginx)
    command -v certbot >/dev/null 2>&1 || packages+=(certbot)
    dpkg-query -W -f='${Status}' libnginx-mod-stream 2>/dev/null | grep -q 'install ok installed' || packages+=(libnginx-mod-stream)

    if [ "${#packages[@]}" -gt 0 ]; then
        echo "Installing gateway packages: ${packages[*]}"
        apt update || return 1
        DEBIAN_FRONTEND=noninteractive apt install -y "${packages[@]}" || return 1
    fi

    systemctl enable --now nginx >/dev/null 2>&1 || return 1

    [ -f /etc/nginx/modules-enabled/50-mod-stream.conf ] || {
        echo "ERROR: Nginx stream module is installed but not enabled."
        return 1
    }

    nginx -t >/dev/null 2>&1 || {
        echo "ERROR: Existing Nginx configuration is invalid."
        nginx -t 2>&1 || true
        return 1
    }
}

smite_gateway_prepare_acme() {
    local domain="$1"
    local acme_conf="/etc/nginx/conf.d/u-opti-acme-${domain}.conf"
    local acme_test_file="$SMITE_GATEWAY_ACME_ROOT/.well-known/acme-challenge/u-opti-smite-test"
    local attempt
    local validated=false

    mkdir -p "$SMITE_GATEWAY_ACME_ROOT/.well-known/acme-challenge" || return 1
    chmod 0755 "$SMITE_GATEWAY_ACME_ROOT" \
        "$SMITE_GATEWAY_ACME_ROOT/.well-known" \
        "$SMITE_GATEWAY_ACME_ROOT/.well-known/acme-challenge" || return 1

    cat > "$acme_conf" <<EOF_ACME
# U-OPTI Smite ACME webroot
server {
    listen 80;
    listen [::]:80;
    server_name $domain;

    location ^~ /.well-known/acme-challenge/ {
        root $SMITE_GATEWAY_ACME_ROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 404;
    }
}
EOF_ACME

    nginx -t || return 1
    systemctl reload nginx || return 1

    printf '%s\n' 'u-opti-smite-acme-test' > "$acme_test_file" || return 1

    # A fresh Nginx install/reload may briefly keep serving the old worker
    # configuration. Retry the local ACME probe instead of treating that
    # short reload window as a permanent webroot failure.
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        if curl -fsS --connect-timeout 2 --max-time 5 \
            -H "Host: $domain" \
            http://127.0.0.1/.well-known/acme-challenge/u-opti-smite-test \
            2>/dev/null | grep -qx 'u-opti-smite-acme-test'; then
            validated=true
            break
        fi
        sleep 1
    done

    rm -f "$acme_test_file"

    if [ "$validated" != "true" ]; then
        echo "ERROR: Local ACME webroot validation failed after retries."
        return 1
    fi
}

smite_gateway_ensure_certificate() {
    local domain="$1"
    local cert_dir="/etc/letsencrypt/live/$domain"

    if [ -s "$cert_dir/fullchain.pem" ] && [ -s "$cert_dir/privkey.pem" ]; then
        echo "Certificate: existing certificate will be used."
        return 0
    fi

    echo "Preparing Let's Encrypt webroot..."
    smite_gateway_prepare_acme "$domain" || return 1

    echo "Requesting Let's Encrypt certificate for $domain ..."
    certbot certonly \
        --webroot \
        -w "$SMITE_GATEWAY_ACME_ROOT" \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        --cert-name "$domain" \
        -d "$domain" || return 1

    [ -s "$cert_dir/fullchain.pem" ] && [ -s "$cert_dir/privkey.pem" ]
}

smite_gateway_backup_file() {
    local path="$1"
    local backup=""

    if [ -f "$path" ]; then
        backup="${path}.u-opti-$(date +%Y%m%d-%H%M%S).bak"
        cp -a "$path" "$backup" || return 1
        printf '%s' "$backup"
    fi
}

smite_gateway_remove_unchanged_backup() {
    local backup="$1"
    local current="$2"

    [ -n "$backup" ] || return 0
    [ -f "$backup" ] || return 0
    [ -f "$current" ] || return 0

    if cmp -s "$backup" "$current"; then
        rm -f "$backup"
    fi
}

smite_gateway_private_backhaul_listener_ready() {
    ss -lntp 2>/dev/null \
        | grep -Eq "127\.0\.0\.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT}[[:space:]].*backhaul"
}

smite_gateway_prepare_private_backhaul() {
    local inspection=""
    local action=""
    local tunnel_id=""
    local tunnel_name=""
    local port_index=""
    local old_mapping=""
    local backup=""
    local attempt=""

    SMITE_GATEWAY_PRIVATE_DB_BACKUP=""
    SMITE_GATEWAY_PRIVATE_BACKHAUL_CHANGED=0

    [ "$(smite_gateway_connection_mode)" = "private" ] || return 0

    [ -f "$SMITE_GATEWAY_DB" ] || {
        echo "ERROR: Smite database was not found:"
        echo "$SMITE_GATEWAY_DB"
        return 1
    }

    inspection="$(python3 - "$SMITE_GATEWAY_DB" "$SMITE_GATEWAY_PRIVATE_DATA_PORT" <<'PYDB'
import json
import sqlite3
import sys

db = sys.argv[1]
data_port = str(sys.argv[2])

con = sqlite3.connect(db)
cur = con.cursor()

rows = cur.execute(
    """
    SELECT id, name, spec
    FROM tunnels
    WHERE core='backhaul'
      AND status='active'
    """
).fetchall()

matches = []

for tunnel_id, name, raw_spec in rows:
    try:
        spec = json.loads(raw_spec)
    except Exception:
        continue

    ports = spec.get("ports")
    if not isinstance(ports, list):
        continue

    for index, item in enumerate(ports):
        entry = str(item)
        if "=" not in entry:
            continue

        left, _right = entry.split("=", 1)

        if left == f"127.0.0.1:{data_port}":
            kind = "prepared"
        else:
            listen_port = left.rsplit(":", 1)[-1] if ":" in left else left
            if listen_port != "443":
                continue
            kind = "public443"

        matches.append((tunnel_id, name, spec, index, entry, kind))

if len(matches) != 1:
    print(
        "ERROR: Expected exactly one active Backhaul mapping for public 443 "
        f"or private 127.0.0.1:{data_port}; found {len(matches)}.",
        file=sys.stderr,
    )
    sys.exit(2)

tunnel_id, name, spec, index, entry, kind = matches[0]

if kind == "prepared":
    public_port = str(spec.get("public_port", ""))
    listen_port = str(spec.get("listen_port", ""))
    action = "already" if public_port == data_port and listen_port == data_port else "repair"
else:
    action = "migrate"

print("\t".join([action, str(tunnel_id), str(name), str(index), entry]))
con.close()
PYDB
)" || return 1

    IFS=$'\t' read -r action tunnel_id tunnel_name port_index old_mapping <<< "$inspection"

    case "$action" in
        already)
            if smite_gateway_private_backhaul_listener_ready; then
                echo "Private Mode Backhaul: already prepared on 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT}"
                return 0
            fi

            echo "Private Mode Backhaul mapping is already prepared, but the listener is missing."
            echo "Restarting Smite Panel to reapply the tunnel..."
            ;;

        migrate)
            # During the normal first conversion Backhaul itself must own :443.
            if ! ss -lntp 2>/dev/null \
                | grep -E ':443[[:space:]]' \
                | grep -q 'backhaul'; then
                echo "ERROR: Backhaul does not currently own public TCP/443."
                echo "Refusing to migrate an ambiguous gateway state."
                return 1
            fi

            echo "Private Mode: moving Backhaul data listener from public :443"
            echo "              to 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT}"
            ;;

        repair)
            echo "Private Mode: repairing Backhaul gateway metadata for 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT}"
            ;;

        *)
            echo "ERROR: Unexpected Backhaul inspection result: $action"
            return 1
            ;;
    esac

    backup="${SMITE_GATEWAY_DB}.u-opti-before-private-gateway-$(date +%Y%m%d-%H%M%S).bak"

    cp -a "$SMITE_GATEWAY_DB" "$backup" || {
        echo "ERROR: Could not back up the Smite database."
        return 1
    }

    if ! python3 - \
        "$SMITE_GATEWAY_DB" \
        "$SMITE_GATEWAY_PRIVATE_DATA_PORT" \
        "$tunnel_id" \
        "$port_index" \
        "$action" <<'PYDB'
import json
import sqlite3
import sys

db = sys.argv[1]
data_port = int(sys.argv[2])
tunnel_id = sys.argv[3]
port_index = int(sys.argv[4])
action = sys.argv[5]

con = sqlite3.connect(db)
cur = con.cursor()

row = cur.execute(
    """
    SELECT spec
    FROM tunnels
    WHERE id=?
      AND core='backhaul'
      AND status='active'
    """,
    (tunnel_id,),
).fetchone()

if not row:
    print("ERROR: Backhaul tunnel disappeared during migration.", file=sys.stderr)
    sys.exit(2)

spec = json.loads(row[0])
ports = spec.get("ports")

if not isinstance(ports, list) or port_index >= len(ports):
    print("ERROR: Backhaul ports changed during migration.", file=sys.stderr)
    sys.exit(3)

entry = str(ports[port_index])
if "=" not in entry:
    print("ERROR: Invalid Backhaul port mapping.", file=sys.stderr)
    sys.exit(4)

left, right = entry.split("=", 1)

if action == "migrate":
    listen_port = left.rsplit(":", 1)[-1] if ":" in left else left
    if listen_port != "443":
        print(f"ERROR: Expected Backhaul public port 443, found {left}.", file=sys.stderr)
        sys.exit(5)
    ports[port_index] = f"127.0.0.1:{data_port}={right}"

elif action in ("repair", "already"):
    expected = f"127.0.0.1:{data_port}"
    if left != expected:
        print(f"ERROR: Expected prepared Backhaul listener {expected}, found {left}.", file=sys.stderr)
        sys.exit(6)

else:
    print(f"ERROR: Unsupported migration action: {action}", file=sys.stderr)
    sys.exit(7)

# Keep listen_ip untouched. It is also used by Backhaul's control listener
# and must remain reachable through the private network.
spec["ports"] = ports
spec["public_port"] = data_port
spec["listen_port"] = data_port

cur.execute(
    "UPDATE tunnels SET spec=? WHERE id=?",
    (json.dumps(spec), tunnel_id),
)

con.commit()
con.close()
PYDB
    then
        rm -f "$backup"
        echo "ERROR: Failed to update the Backhaul tunnel."
        return 1
    fi

    echo "Reapplying Backhaul tunnel..."

    if ! docker restart smite-panel >/dev/null; then
        echo "ERROR: Could not restart smite-panel."
        cp -a "$backup" "$SMITE_GATEWAY_DB"
        docker restart smite-panel >/dev/null 2>&1 || true
        return 1
    fi

    if ! smite_gateway_wait_healthy smite-panel 90; then
        echo "ERROR: smite-panel did not become healthy after Backhaul migration."
        cp -a "$backup" "$SMITE_GATEWAY_DB"
        docker restart smite-panel >/dev/null 2>&1 || true
        smite_gateway_wait_healthy smite-panel 90 >/dev/null 2>&1 || true
        return 1
    fi

    for attempt in $(seq 1 30); do
        if smite_gateway_private_backhaul_listener_ready; then
            SMITE_GATEWAY_PRIVATE_DB_BACKUP="$backup"
            SMITE_GATEWAY_PRIVATE_BACKHAUL_CHANGED=1

            echo "Private Mode Backhaul listener: 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT} OK"
            echo "Smite database backup: $backup"
            return 0
        fi

        sleep 1
    done

    echo "ERROR: Backhaul did not start on 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT}."
    echo "Restoring the previous Smite database..."

    cp -a "$backup" "$SMITE_GATEWAY_DB"
    docker restart smite-panel >/dev/null 2>&1 || true
    smite_gateway_wait_healthy smite-panel 90 >/dev/null 2>&1 || true

    return 1
}

smite_gateway_restore_nginx_files() {
    local backend_backup="$1"
    local stream_backup="$2"
    local map_backup="$3"

    if [ -n "$backend_backup" ]; then
        cp -a "$backend_backup" "$SMITE_GATEWAY_BACKEND_CONF"
    else
        rm -f "$SMITE_GATEWAY_BACKEND_CONF"
    fi

    if [ -n "$stream_backup" ]; then
        cp -a "$stream_backup" "$SMITE_GATEWAY_STREAM_CONF"
    else
        rm -f "$SMITE_GATEWAY_STREAM_CONF"
    fi

    if [ -n "$map_backup" ]; then
        cp -a "$map_backup" "$SMITE_GATEWAY_MAP_FILE"
    else
        rm -f "$SMITE_GATEWAY_MAP_FILE"
    fi

    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx >/dev/null 2>&1 || \
            echo "WARNING: Nginx rollback configuration is valid, but reload failed."
    else
        echo "WARNING: Previous Nginx gateway files were restored, but nginx -t failed."
    fi
}

smite_gateway_rollback_private_backhaul() {
    local backup="$1"
    local changed="$2"

    [ "$changed" = "1" ] || return 0
    [ -n "$backup" ] || return 0
    [ -f "$backup" ] || {
        echo "WARNING: Private Backhaul rollback backup was not found:"
        echo "$backup"
        return 1
    }

    echo "Restoring previous Backhaul tunnel configuration..."

    cp -a "$backup" "$SMITE_GATEWAY_DB" || return 1

    docker restart smite-panel >/dev/null 2>&1 || {
        echo "WARNING: Database was restored, but smite-panel restart failed."
        return 1
    }

    if ! smite_gateway_wait_healthy smite-panel 90; then
        echo "WARNING: Database was restored, but smite-panel did not become healthy."
        return 1
    fi

    echo "Backhaul database rollback: OK"
}

smite_gateway_rollback_transaction() {
    local backend_backup="$1"
    local stream_backup="$2"
    local map_backup="$3"
    local private_db_backup="$4"
    local private_backhaul_changed="$5"

    # Free public :443 first by restoring the previous Nginx state.
    smite_gateway_restore_nginx_files \
        "$backend_backup" \
        "$stream_backup" \
        "$map_backup"

    # Only then restore Backhaul :443.
    smite_gateway_rollback_private_backhaul \
        "$private_db_backup" \
        "$private_backhaul_changed"
}

smite_gateway_write_backend() {
    local domain="$1"

    cat > "$SMITE_GATEWAY_BACKEND_CONF" <<EOF_BACKEND
# Managed by U-OPTI - Smite Panel TLS backend
server {
    listen 127.0.0.1:8443 ssl;
    server_name $domain;

    ssl_certificate     /etc/letsencrypt/live/$domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$domain/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
EOF_BACKEND
}

smite_gateway_write_stream() {
    local domain="$1"
    local map_tmp=""
    local connection_mode=""
    local default_backend="127.0.0.1:8443"

    connection_mode="$(smite_gateway_connection_mode)"

    if [ "$connection_mode" = "private" ]; then
        default_backend="127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT}"

        if ! smite_gateway_private_backhaul_listener_ready; then
            echo "ERROR: Private Mode Backhaul listener is not available at $default_backend."
            echo "Refusing to place Nginx on public TCP/443."
            return 1
        fi

        echo "Private Mode default TCP/443 backend: $default_backend"
    fi

    map_tmp="$(mktemp)" || return 1

    printf '%s\n' \
        '# Managed by U-OPTI. Additional Foreign SNI routes are appended here.' \
        > "$map_tmp" || {
        rm -f "$map_tmp"
        return 1
    }

    if [ -f "$SMITE_GATEWAY_MAP_FILE" ]; then
        awk -v panel_domain="$domain" '
            $0 == "# Managed by U-OPTI. Additional Foreign SNI routes are appended here." {
                next
            }

            $1 == panel_domain {
                next
            }

            $2 == "127.0.0.1:8443;" {
                next
            }

            {
                print
            }
        ' "$SMITE_GATEWAY_MAP_FILE" >> "$map_tmp" || {
            rm -f "$map_tmp"
            return 1
        }
    fi

    printf '%s    127.0.0.1:8443;\n' "$domain" >> "$map_tmp" || {
        rm -f "$map_tmp"
        return 1
    }

    install -m 0644 "$map_tmp" "$SMITE_GATEWAY_MAP_FILE" || {
        rm -f "$map_tmp"
        return 1
    }

    rm -f "$map_tmp"

    cat > "$SMITE_GATEWAY_STREAM_CONF" <<EOF_STREAM
# Managed by U-OPTI - Smite TCP/443 SNI gateway
stream {
    map \$ssl_preread_server_name \$uopti_smite_backend {
        include $SMITE_GATEWAY_MAP_FILE;
        default $default_backend;
    }

    server {
        listen 443;
        listen [::]:443;

        ssl_preread on;
        proxy_pass \$uopti_smite_backend;

        proxy_connect_timeout 10s;
        proxy_timeout 1h;
    }
}
EOF_STREAM
}

smite_gateway_write_renew_hook() {
    mkdir -p "$(dirname "$SMITE_GATEWAY_RENEW_HOOK")" || return 1

    cat > "$SMITE_GATEWAY_RENEW_HOOK" <<'EOF_HOOK'
#!/bin/sh
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
fi
EOF_HOOK
    chmod 0755 "$SMITE_GATEWAY_RENEW_HOOK"
}

smite_gateway_verify_443() {
    local domain="$1"

    curl -fsS --max-time 10 \
        --resolve "${domain}:443:127.0.0.1" \
        "https://${domain}/api/status" >/dev/null
}

smite_gateway_switch_local_node_to_443() {
    local domain="$1"
    local env_file="$SMITE_NODE_DIR/.env"
    local compose_file="$SMITE_NODE_COMPOSE"
    local backup=""
    local current_panel_address=""

    if [ "$(smite_gateway_connection_mode)" = "private" ]; then
        if [ -f "$env_file" ]; then
            current_panel_address="$(awk -F= '$1 == "PANEL_ADDRESS" {print substr($0, index($0,"=")+1); exit}' "$env_file")"
        fi

        echo "Private Mode: keeping Iran node PANEL_ADDRESS=${current_panel_address:-unchanged}"
        return 0
    fi

    [ -f "$env_file" ] || {
        echo "WARNING: Local Smite node configuration was not found; skipping PANEL_ADDRESS switch."
        return 0
    }

    [ -f "$compose_file" ] || {
        echo "ERROR: Local Smite node compose file was not found."
        return 1
    }

    if grep -qx "PANEL_ADDRESS=${domain}:443" "$env_file"; then
        echo "Iran node panel address: already using ${domain}:443"
        return 0
    fi

    backup="${env_file}.u-opti-before-gateway-$(date +%Y%m%d-%H%M%S).bak"
    cp -a "$env_file" "$backup" || return 1

    if grep -q '^PANEL_ADDRESS=' "$env_file"; then
        sed -i "s|^PANEL_ADDRESS=.*|PANEL_ADDRESS=${domain}:443|" "$env_file" || return 1
    else
        printf '\nPANEL_ADDRESS=%s:443\n' "$domain" >> "$env_file" || return 1
    fi

    echo "Recreating Iran Smite Node with PANEL_ADDRESS=${domain}:443 ..."
    if ! docker compose -f "$compose_file" up -d --no-build --force-recreate smite-node; then
        cp -a "$backup" "$env_file"
        docker compose -f "$compose_file" up -d --no-build --force-recreate smite-node >/dev/null 2>&1 || true
        echo "ERROR: Failed to recreate smite-node; node configuration was rolled back."
        return 1
    fi

    if ! smite_gateway_wait_healthy smite-node 90; then
        cp -a "$backup" "$env_file"
        docker compose -f "$compose_file" up -d --no-build --force-recreate smite-node >/dev/null 2>&1 || true
        echo "ERROR: smite-node did not become healthy; node configuration was rolled back."
        return 1
    fi

    sleep 2
    if ! docker logs --since 2m smite-node 2>&1 | grep -q 'Node registered successfully'; then
        echo "WARNING: Registration success was not found in recent node logs."
        echo "The node is healthy; verify Panel node status after gateway setup."
    else
        echo "Iran node registration through HTTPS/443: OK"
    fi
}

smite_gateway_write_state() {
    local domain="$1"

    mkdir -p "$SMITE_STATE_DIR" || return 1
    chmod 0700 "$SMITE_STATE_DIR" || return 1

    cat > "$SMITE_GATEWAY_STATE_FILE" <<EOF_STATE
# Managed by U-OPTI. No secrets are stored here.
SMITE_GATEWAY_DOMAIN=$domain
SMITE_GATEWAY_BACKEND=127.0.0.1:8443
SMITE_GATEWAY_PUBLIC_PORT=443
SMITE_GATEWAY_MODE=stream-sni
EOF_STATE
    chmod 0600 "$SMITE_GATEWAY_STATE_FILE"
}

smite_gateway_status() {
    local domain
    domain="$(smite_gateway_panel_domain)"

    clear
    echo "======================================"
    echo "        Smite 443 Gateway Status"
    echo "======================================"
    echo
    echo "Panel domain : ${domain:-Not detected}"
    echo "Mode         : $(smite_gateway_connection_mode)"
    echo

    if command -v nginx >/dev/null 2>&1; then
        echo "Nginx        : $(nginx -v 2>&1)"
        if nginx -t >/dev/null 2>&1; then
            echo "Nginx config : Valid"
        else
            echo "Nginx config : INVALID"
        fi
    else
        echo "Nginx        : Not installed"
    fi

    command -v certbot >/dev/null 2>&1 && echo "Certbot      : $(certbot --version 2>/dev/null)" || echo "Certbot      : Not installed"

    if [ -n "$domain" ] && [ -s "/etc/letsencrypt/live/$domain/fullchain.pem" ]; then
        echo "Certificate  : Present"
    else
        echo "Certificate  : Not present"
    fi

    [ -f "$SMITE_GATEWAY_BACKEND_CONF" ] && echo "TLS backend  : Present (127.0.0.1:8443)" || echo "TLS backend  : Not configured"
    [ -f "$SMITE_GATEWAY_STREAM_CONF" ] && echo "TCP/443 SNI  : Present" || echo "TCP/443 SNI  : Not configured"

    if ss -lnt 2>/dev/null | grep -Eq '[[:space:]]127\.0\.0\.1:8443[[:space:]]'; then
        echo "Port 8443    : Listening on loopback"
    else
        echo "Port 8443    : Not listening"
    fi

    if [ "$(smite_gateway_connection_mode)" = "private" ]; then
        if smite_gateway_private_backhaul_listener_ready; then
            echo "RAW backend  : 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT} (Backhaul)"
        else
            echo "RAW backend  : Not listening"
        fi
    fi

    if ss -lnt 2>/dev/null | grep -Eq '[[:space:]][^[:space:]]*:443[[:space:]]'; then
        echo "Port 443     : Listening"
    else
        echo "Port 443     : Not listening"
    fi

    if [ -n "$domain" ] && smite_gateway_verify_443 "$domain" 2>/dev/null; then
        echo "Panel /443   : OK"
    else
        echo "Panel /443   : Not verified"
    fi

    if [ -f "$SMITE_NODE_DIR/.env" ]; then
        echo "Node panel   : $(grep '^PANEL_ADDRESS=' "$SMITE_NODE_DIR/.env" | head -n1 | cut -d= -f2-)"
    fi

    smite_gateway_pause
}

smite_gateway_configure_panel() {
    local domain confirm
    local backend_backup="" stream_backup="" map_backup=""
    local private_db_backup="" private_backhaul_changed=0

    clear
    echo "======================================"
    echo "       Configure Smite 443 Gateway"
    echo "======================================"
    echo

    [ "$(id -u)" -eq 0 ] || {
        echo "ERROR: Run U-OPTI as root."
        smite_gateway_pause
        return
    }

    smite_gateway_require_panel || {
        smite_gateway_pause
        return
    }

    domain="$(smite_gateway_panel_domain)"
    if ! smite_gateway_validate_domain "$domain"; then
        echo "ERROR: A valid Smite Panel domain could not be detected."
        echo "Expected PANEL_DOMAIN in $SMITE_PANEL_DIR/.env or SMITE_PANEL_DOMAIN in U-OPTI state."
        smite_gateway_pause
        return
    fi

    echo "Panel domain : $domain"
    echo "Panel API    : 127.0.0.1:8000"
    echo "TLS backend  : 127.0.0.1:8443"
    echo "Public entry : TCP/443 (Nginx stream + SNI)"
    echo
    echo "This operation does not open firewall/provider ports."
    echo "Public 8000 and 8888 should remain blocked."
    echo
    read -rp "Configure the Smite 443 gateway? [y/N]: " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *) echo "Gateway configuration cancelled."; sleep 1; return ;;
    esac

    echo
    smite_gateway_ensure_packages || {
        echo "ERROR: Could not prepare Nginx/Certbot/stream module."
        smite_gateway_pause
        return
    }

    smite_gateway_ensure_certificate "$domain" || {
        echo "ERROR: Certificate preparation failed."
        smite_gateway_pause
        return
    }

    backend_backup="$(smite_gateway_backup_file "$SMITE_GATEWAY_BACKEND_CONF")" || {
        echo "ERROR: Could not back up the current TLS backend configuration."
        smite_gateway_pause
        return
    }
    stream_backup="$(smite_gateway_backup_file "$SMITE_GATEWAY_STREAM_CONF")" || {
        echo "ERROR: Could not back up the current stream configuration."
        smite_gateway_pause
        return
    }
    map_backup="$(smite_gateway_backup_file "$SMITE_GATEWAY_MAP_FILE")" || {
        echo "ERROR: Could not back up the current stream map."
        smite_gateway_pause
        return
    }

    if ! smite_gateway_prepare_private_backhaul; then
        echo "ERROR: Private Mode Backhaul preparation failed."
        smite_gateway_pause
        return
    fi

    private_db_backup="$SMITE_GATEWAY_PRIVATE_DB_BACKUP"
    private_backhaul_changed="$SMITE_GATEWAY_PRIVATE_BACKHAUL_CHANGED"

    smite_gateway_write_backend "$domain" || {
        echo "ERROR: Failed to write the Smite TLS backend configuration."
        smite_gateway_rollback_transaction \
            "$backend_backup" "$stream_backup" "$map_backup" \
            "$private_db_backup" "$private_backhaul_changed"
        smite_gateway_pause
        return
    }

    smite_gateway_write_stream "$domain" || {
        echo "ERROR: Failed to write the Smite stream configuration."
        smite_gateway_rollback_transaction \
            "$backend_backup" "$stream_backup" "$map_backup" \
            "$private_db_backup" "$private_backhaul_changed"
        smite_gateway_pause
        return
    }

    if ! nginx -t; then
        echo "ERROR: Nginx validation failed. Restoring previous gateway configuration..."
        smite_gateway_rollback_transaction \
            "$backend_backup" "$stream_backup" "$map_backup" \
            "$private_db_backup" "$private_backhaul_changed"
        smite_gateway_pause
        return
    fi

    if ! systemctl reload nginx; then
        echo "ERROR: Nginx reload failed. Restoring previous gateway configuration..."
        smite_gateway_rollback_transaction \
            "$backend_backup" "$stream_backup" "$map_backup" \
            "$private_db_backup" "$private_backhaul_changed"
        smite_gateway_pause
        return
    fi

    if ! smite_gateway_verify_443 "$domain"; then
        echo "ERROR: Panel HTTPS/443 verification failed."
        echo "Nginx configuration is valid, but the panel path did not answer successfully."
        smite_gateway_rollback_transaction \
            "$backend_backup" "$stream_backup" "$map_backup" \
            "$private_db_backup" "$private_backhaul_changed"
        smite_gateway_pause
        return
    fi

    echo "Panel HTTPS/443: OK"

    if ! smite_gateway_switch_local_node_to_443 "$domain"; then
        echo "ERROR: Gateway is online, but the Iran node could not be switched to HTTPS/443."
        smite_gateway_rollback_transaction \
            "$backend_backup" "$stream_backup" "$map_backup" \
            "$private_db_backup" "$private_backhaul_changed"
        smite_gateway_pause
        return
    fi

    if ! smite_gateway_verify_443 "$domain"; then
        echo "ERROR: Final Panel HTTPS/443 verification failed after node recreation."
        smite_gateway_rollback_transaction \
            "$backend_backup" "$stream_backup" "$map_backup" \
            "$private_db_backup" "$private_backhaul_changed"
        smite_gateway_pause
        return
    fi

    smite_gateway_write_renew_hook || echo "WARNING: Could not install the Nginx certificate renewal hook."
    smite_gateway_write_state "$domain" || echo "WARNING: Gateway state could not be saved."

    smite_gateway_remove_unchanged_backup "$backend_backup" "$SMITE_GATEWAY_BACKEND_CONF"
    smite_gateway_remove_unchanged_backup "$stream_backup" "$SMITE_GATEWAY_STREAM_CONF"
    smite_gateway_remove_unchanged_backup "$map_backup" "$SMITE_GATEWAY_MAP_FILE"

    echo
    echo "======================================"
    echo "       Smite 443 Gateway Ready"
    echo "======================================"
    echo
    echo "Panel URL    : https://$domain"
    echo "Public TCP   : 443"
    echo "Panel API    : 127.0.0.1:8000"
    echo "TLS backend  : 127.0.0.1:8443"
    if [ "$(smite_gateway_connection_mode)" = "private" ]; then
        echo "Iran Node    : 127.0.0.1:8000 (Private Mode)"
        echo "RAW backend  : 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT}"
    else
        echo "Iran Node    : ${domain}:443"
    fi
    echo "Renewal hook : installed"
    echo
    echo "Keep public ports 8000 and 8888 blocked."

    smite_gateway_pause
}

show_smite_gateway_menu() {
    while true; do
        clear
        echo "======================================"
        echo "        Smite 443 Gateway"
        echo "======================================"
        echo
        echo "1) Configure / Repair Panel Gateway"
        echo "2) Gateway Status"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-2]: " choice
        case "$choice" in
            1) smite_gateway_configure_panel ;;
            2) smite_gateway_status ;;
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
