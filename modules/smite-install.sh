#!/bin/bash

# U-OPTI - Smite Installer / Lifecycle Management
# Controlled installer for the Smite version validated by U-OPTI.

SMITE_UPSTREAM_VERSION="${SMITE_UPSTREAM_VERSION:-0.1.7}"
SMITE_UPSTREAM_REF="${SMITE_UPSTREAM_REF:-v${SMITE_UPSTREAM_VERSION}}"
SMITE_UPSTREAM_RAW="https://raw.githubusercontent.com/zZedix/Smite/${SMITE_UPSTREAM_REF}"
SMITE_PANEL_REPO="ghcr.io/zzedix/smite-panel"
SMITE_NODE_REPO="ghcr.io/zzedix/smite-node"
SMITE_PANEL_DIGEST="sha256:67f98cba1f49658e651779ab6142290f7eb0906b54b386939fcdb867d18cb44f"
SMITE_NODE_DIGEST="sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
SMITE_PANEL_IMAGE="${SMITE_PANEL_REPO}@${SMITE_PANEL_DIGEST}"
SMITE_NODE_IMAGE="${SMITE_NODE_REPO}@${SMITE_NODE_DIGEST}"
SMITE_STATE_DIR="${SMITE_STATE_DIR:-/etc/u-opti/smite}"
SMITE_STATE_FILE="$SMITE_STATE_DIR/state.env"

smite_install_pause() {
    echo
    read -rp "Press Enter to return..."
}

smite_install_validate_domain() {
    local domain="$1"
    [[ "$domain" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]
}

smite_install_validate_name() {
    local name="$1"
    [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]]
}

smite_install_require_tools() {
    local missing=()
    local cmd

    for cmd in curl openssl python3; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done

    if [ "${#missing[@]}" -gt 0 ]; then
        echo "ERROR: Required commands are missing: ${missing[*]}"
        echo "Install the missing packages and try again."
        return 1
    fi

    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 is required by Smite management."
        echo "Reinstall/update U-OPTI or install sqlite3 first."
        return 1
    fi

    return 0
}

smite_install_ensure_docker() {
    if command -v docker >/dev/null 2>&1 && \
       systemctl is-active --quiet docker 2>/dev/null && \
       docker compose version >/dev/null 2>&1; then
        return 0
    fi

    echo "Docker Engine / Compose is not ready."
    if declare -F docker_install >/dev/null 2>&1; then
        echo
        read -rp "Run the U-OPTI Docker installer now? [y/N]: " confirm
        case "$confirm" in
            y|Y|yes|YES)
                docker_install
                ;;
            *)
                return 1
                ;;
        esac
    else
        echo "Install Docker from U-OPTI -> Docker Management -> Install Docker."
        return 1
    fi

    command -v docker >/dev/null 2>&1 && \
    systemctl is-active --quiet docker 2>/dev/null && \
    docker compose version >/dev/null 2>&1
}

smite_download_upstream() {
    local path="$1"
    local destination="$2"
    local cache_bust
    cache_bust="$(date +%s%N)"

    mkdir -p "$(dirname "$destination")" || return 1
    curl -fsSL --retry 3 \
        "${SMITE_UPSTREAM_RAW}/${path}?cb=${cache_bust}" \
        -o "$destination"
}

smite_install_pin_compose_image() {
    local compose_file="$1"
    local expected_repo="$2"
    local pinned_image="$3"

    python3 - "$compose_file" "$expected_repo" "$pinned_image" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
expected_repo = sys.argv[2]
pinned_image = sys.argv[3]

text = path.read_text()
needle = f"    image: {expected_repo}:${{SMITE_VERSION:-latest}}"
replacement = f"    image: {pinned_image}"

count = text.count(needle)
if count != 1:
    raise SystemExit(
        f"ERROR: Expected exactly one Compose image line for {expected_repo}; found {count}. Refusing unsafe pin."
    )

path.write_text(text.replace(needle, replacement, 1))
print(f"Pinned Compose image: {pinned_image}")
PY
}

smite_install_cli_tools() {
    echo "Installing Smite CLI tools..."

    if ! smite_download_upstream "cli/smite.py" "/usr/local/bin/smite"; then
        echo "ERROR: Failed to download the Smite panel CLI."
        return 1
    fi

    if ! smite_download_upstream "cli/smite-node.py" "/usr/local/bin/smite-node"; then
        echo "ERROR: Failed to download the Smite node CLI."
        return 1
    fi

    chmod 0755 /usr/local/bin/smite /usr/local/bin/smite-node || return 1
    return 0
}

smite_write_state() {
    local role="$1"
    local panel_domain="$2"
    local node_name="$3"
    local foreign_domain="${4:-}"

    mkdir -p "$SMITE_STATE_DIR" || return 1
    chmod 0700 "$SMITE_STATE_DIR" || return 1

    cat > "$SMITE_STATE_FILE" <<EOF_STATE
# Managed by U-OPTI. No secrets are stored here.
SMITE_ROLE=$role
SMITE_PANEL_DOMAIN=$panel_domain
SMITE_NODE_NAME=$node_name
SMITE_FOREIGN_DOMAIN=$foreign_domain
SMITE_MANAGED_VERSION=$SMITE_UPSTREAM_VERSION
SMITE_UPSTREAM_REF=$SMITE_UPSTREAM_REF
EOF_STATE
    chmod 0600 "$SMITE_STATE_FILE" || return 1
}

smite_show_installation_state() {
    clear
    echo "======================================"
    echo "      Smite Installation State"
    echo "======================================"
    echo

    echo "Validated Smite version : $SMITE_UPSTREAM_VERSION"
    echo "Validated source ref    : $SMITE_UPSTREAM_REF"
    echo

    if [ -f "$SMITE_STATE_FILE" ]; then
        source "$SMITE_STATE_FILE"
        echo "Managed role            : ${SMITE_ROLE:-Unknown}"
        echo "Panel domain            : ${SMITE_PANEL_DOMAIN:-Not set}"
        echo "Node name               : ${SMITE_NODE_NAME:-Not set}"
        if [ -n "${SMITE_FOREIGN_DOMAIN:-}" ]; then
            echo "Foreign domain          : $SMITE_FOREIGN_DOMAIN"
        fi
        echo "Managed Smite version   : ${SMITE_MANAGED_VERSION:-Unknown}"
    else
        echo "Managed state           : Not created"
    fi

    echo
    if [ -f "$SMITE_PANEL_DIR/.env" ]; then
        echo "Panel configuration     : Present"
    else
        echo "Panel configuration     : Not present"
    fi
    if [ -f "$SMITE_NODE_DIR/.env" ]; then
        echo "Node configuration      : Present"
    else
        echo "Node configuration      : Not present"
    fi

    smite_install_pause
}

smite_install_panel_files() {
    local panel_domain="$1"
    local secret_key
    secret_key="$(openssl rand -hex 32)" || return 1

    mkdir -p "$SMITE_PANEL_DIR/panel/data" "$SMITE_PANEL_DIR/panel/certs" || return 1

    if ! smite_download_upstream "docker-compose.yml" "$SMITE_PANEL_COMPOSE"; then
        echo "ERROR: Failed to download the validated Smite panel Compose file."
        return 1
    fi

    if ! smite_install_pin_compose_image "$SMITE_PANEL_COMPOSE" "$SMITE_PANEL_REPO" "$SMITE_PANEL_IMAGE"; then
        echo "ERROR: Failed to pin the validated Smite panel image digest."
        return 1
    fi

    cat > "$SMITE_PANEL_DIR/.env" <<EOF_ENV
PANEL_PORT=8000
PANEL_HOST=127.0.0.1
HTTPS_ENABLED=false
PANEL_DOMAIN=$panel_domain
SMITE_HTTP_PORT=80
SMITE_HTTPS_PORT=443
SMITE_SSL_DOMAIN=$panel_domain
DOCS_ENABLED=true
SMITE_VERSION=$SMITE_UPSTREAM_VERSION

DB_TYPE=sqlite
DB_PATH=./data/smite.db

SECRET_KEY=$secret_key
EOF_ENV
    chmod 0600 "$SMITE_PANEL_DIR/.env" || return 1

    docker compose -f "$SMITE_PANEL_COMPOSE" config >/dev/null || {
        echo "ERROR: Downloaded panel Compose file failed validation."
        return 1
    }

    return 0
}

smite_install_node_files() {
    local node_name="$1"
    local node_role="$2"
    local panel_address="$3"
    local ca_source="$4"

    mkdir -p "$SMITE_NODE_DIR/certs" "$SMITE_NODE_DIR/config" || return 1

    if ! smite_download_upstream "node/docker-compose.yml" "$SMITE_NODE_COMPOSE"; then
        echo "ERROR: Failed to download the validated Smite node Compose file."
        return 1
    fi

    if ! smite_install_pin_compose_image "$SMITE_NODE_COMPOSE" "$SMITE_NODE_REPO" "$SMITE_NODE_IMAGE"; then
        echo "ERROR: Failed to pin the validated Smite node image digest."
        return 1
    fi

    if [ "$ca_source" != "$SMITE_NODE_DIR/certs/ca.crt" ]; then
        cp -f "$ca_source" "$SMITE_NODE_DIR/certs/ca.crt" || return 1
    fi
    chmod 0644 "$SMITE_NODE_DIR/certs/ca.crt" || return 1

    cat > "$SMITE_NODE_DIR/.env" <<EOF_ENV
NODE_API_PORT=8888
NODE_NAME=$node_name
NODE_ROLE=$node_role
SMITE_VERSION=$SMITE_UPSTREAM_VERSION

PANEL_CA_PATH=/etc/smite-node/certs/ca.crt
PANEL_ADDRESS=$panel_address
PANEL_API_PORT=8000
EOF_ENV
    chmod 0600 "$SMITE_NODE_DIR/.env" || return 1

    docker compose -f "$SMITE_NODE_COMPOSE" config >/dev/null || {
        echo "ERROR: Downloaded node Compose file failed validation."
        return 1
    }

    return 0
}

smite_install_pull_images() {
    local need_panel="${1:-false}"

    if [ "$need_panel" = "true" ]; then
        echo "Pulling $SMITE_PANEL_IMAGE ..."
        docker pull "$SMITE_PANEL_IMAGE" || return 1
    fi

    echo "Pulling $SMITE_NODE_IMAGE ..."
    docker pull "$SMITE_NODE_IMAGE" || return 1
}

smite_wait_panel_api() {
    local tries=0
    while [ "$tries" -lt 30 ]; do
        if curl -fsS --max-time 3 http://127.0.0.1:8000/api/status >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        tries=$((tries + 1))
    done
    return 1
}

smite_wait_node_registration_local() {
    local node_name="$1"
    local tries=0
    local escaped_name
    escaped_name="${node_name//\'/\'\'}"

    while [ "$tries" -lt 45 ]; do
        if [ -f "$SMITE_PANEL_DIR/panel/data/smite.db" ]; then
            if sqlite3 "$SMITE_PANEL_DIR/panel/data/smite.db" \
                "SELECT count(*) FROM nodes WHERE json_extract(metadata,'$.node_name')='$escaped_name' AND status='active';" 2>/dev/null | grep -q '^1$'; then
                return 0
            fi
        fi
        sleep 2
        tries=$((tries + 1))
    done
    return 1
}

smite_set_local_control_address() {
    local node_name="$1"
    local db="$SMITE_PANEL_DIR/panel/data/smite.db"
    local escaped_name
    escaped_name="${node_name//\'/\'\'}"

    [ -f "$db" ] || return 1

    sqlite3 "$db" <<SQL
UPDATE nodes
SET metadata = json_set(COALESCE(metadata, '{}'), '$.control_address', 'http://127.0.0.1:8888')
WHERE json_extract(metadata, '$.node_name') = '$escaped_name'
  AND json_extract(metadata, '$.role') = 'iran';
SQL
}

smite_recreate_with_overlays_noninteractive() {
    if smite_container_exists smite-panel && [ -f "$SMITE_PANEL_COMPOSE" ]; then
        echo "Recreating smite-panel with persistent compatibility overlays..."
        docker compose -f "$SMITE_PANEL_COMPOSE" up -d --no-build --force-recreate smite-panel || return 1
        smite_wait_healthy smite-panel 90 || return 1
    fi

    if smite_container_exists smite-node && [ -f "$SMITE_NODE_COMPOSE" ]; then
        echo "Recreating smite-node with persistent compatibility overlays..."
        docker compose -f "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node || return 1
        smite_wait_healthy smite-node 90 || return 1
    fi

    return 0
}

smite_install_apply_compatibility() {
    echo
    echo "Preparing the tested U-OPTI Smite compatibility layer..."
    smite_prepare_overlays || return 1
    smite_patch_compose_mounts || return 1
    smite_recreate_with_overlays_noninteractive || return 1
}

smite_install_panel_iran() {
    clear
    echo "======================================"
    echo "     Install Smite Panel + Iran"
    echo "======================================"
    echo
    echo "This installs the Smite version validated by U-OPTI: $SMITE_UPSTREAM_VERSION"
    echo "Panel API will initially bind only to 127.0.0.1:8000."
    echo "The Iran node will bootstrap against that local panel endpoint."
    echo "TCP/443 gateway configuration is handled as a separate step."
    echo

    smite_install_require_tools || { smite_install_pause; return; }
    smite_install_ensure_docker || { echo "Docker is required."; smite_install_pause; return; }

    if smite_container_exists smite-panel || smite_container_exists smite-node || \
       [ -f "$SMITE_PANEL_COMPOSE" ] || [ -f "$SMITE_NODE_COMPOSE" ]; then
        echo "ERROR: An existing Smite installation was detected."
        echo "Use Status/Repair instead of the fresh installer."
        smite_install_pause
        return
    fi

    local panel_domain node_name
    read -rp "Panel domain (example: ir.example.com): " panel_domain
    panel_domain="${panel_domain,,}"
    if ! smite_install_validate_domain "$panel_domain"; then
        echo "ERROR: Invalid panel domain."
        smite_install_pause
        return
    fi

    read -rp "Iran node name [node-ir]: " node_name
    node_name="${node_name:-node-ir}"
    if ! smite_install_validate_name "$node_name"; then
        echo "ERROR: Invalid node name. Use letters, numbers, dot, dash, or underscore."
        smite_install_pause
        return
    fi

    echo
    echo "Panel domain : $panel_domain"
    echo "Iran node    : $node_name"
    echo "Smite version: $SMITE_UPSTREAM_VERSION"
    echo
    read -rp "Install Smite Panel + Iran Node? [y/N]: " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *) echo "Installation cancelled."; sleep 1; return ;;
    esac

    mkdir -p "$SMITE_PANEL_DIR" "$SMITE_NODE_DIR" || {
        echo "ERROR: Failed to create Smite directories."
        smite_install_pause
        return
    }

    if ! smite_install_panel_files "$panel_domain"; then
        smite_install_pause
        return
    fi

    if ! smite_install_cli_tools; then
        smite_install_pause
        return
    fi

    if ! smite_install_pull_images true; then
        echo "ERROR: Failed to pull the validated Smite images."
        smite_install_pause
        return
    fi

    echo
    echo "Starting Smite Panel on 127.0.0.1:8000..."
    if ! docker compose -f "$SMITE_PANEL_COMPOSE" up -d --no-build smite-panel; then
        echo "ERROR: Failed to start Smite Panel."
        smite_install_pause
        return
    fi

    if ! smite_wait_healthy smite-panel 90 || ! smite_wait_panel_api; then
        echo "ERROR: Smite Panel did not become healthy."
        smite_install_pause
        return
    fi

    mkdir -p "$SMITE_NODE_DIR/certs" || {
        echo "ERROR: Failed to create the Smite node certificate directory."
        smite_install_pause
        return
    }

    echo "Downloading the Iran-node CA certificate from the local panel..."
    if ! curl -fsS --retry 5 \
        http://127.0.0.1:8000/api/panel/ca \
        -o "$SMITE_NODE_DIR/certs/ca.crt"; then
        echo "ERROR: Failed to obtain the Iran-node CA certificate."
        smite_install_pause
        return
    fi

    if ! grep -q "BEGIN CERTIFICATE" "$SMITE_NODE_DIR/certs/ca.crt"; then
        echo "ERROR: The panel returned an invalid CA certificate."
        smite_install_pause
        return
    fi

    if ! smite_install_node_files "$node_name" "iran" "127.0.0.1:8000" "$SMITE_NODE_DIR/certs/ca.crt"; then
        smite_install_pause
        return
    fi

    echo "Starting Iran Smite Node..."
    if ! docker compose -f "$SMITE_NODE_COMPOSE" up -d --no-build smite-node; then
        echo "ERROR: Failed to start Smite Node."
        smite_install_pause
        return
    fi

    if ! smite_wait_healthy smite-node 90; then
        echo "ERROR: Smite Node did not become healthy."
        smite_install_pause
        return
    fi

    if ! smite_wait_node_registration_local "$node_name"; then
        echo "ERROR: The Iran node did not register with the local panel."
        echo "Check: docker logs smite-node"
        smite_install_pause
        return
    fi

    if ! smite_install_apply_compatibility; then
        echo "ERROR: U-OPTI compatibility preparation failed."
        echo "The expected upstream source blocks may have changed."
        smite_install_pause
        return
    fi

    if ! smite_wait_node_registration_local "$node_name"; then
        echo "ERROR: Node registration was not restored after compatibility activation."
        smite_install_pause
        return
    fi

    if smite_set_local_control_address "$node_name"; then
        echo "Panel control address set to local node API (127.0.0.1:8888)."
    else
        echo "WARNING: Could not set the local panel control address automatically."
    fi

    smite_write_state "panel-iran" "$panel_domain" "$node_name" || {
        echo "WARNING: Smite installed, but U-OPTI state could not be saved."
    }

    echo
    echo "======================================"
    echo "      Smite Core Install Complete"
    echo "======================================"
    echo
    echo "Panel       : running on 127.0.0.1:8000"
    echo "Iran Node   : running on port 8888"
    echo "Panel Domain: $panel_domain"
    echo "Compatibility overlays: active"
    echo
    echo "IMPORTANT: TCP/443 gateway is not configured by this installer step yet."
    echo "Keep public ports 8000 and 8888 blocked at the firewall/provider level."
    echo
    read -rp "Create a Smite admin account now? [y/N]: " create_admin
    case "$create_admin" in
        y|Y|yes|YES)
            (cd "$SMITE_PANEL_DIR" && /usr/local/bin/smite admin create) || true
            ;;
    esac

    smite_install_pause
}

smite_install_foreign_node() {
    clear
    echo "======================================"
    echo "       Install Foreign Smite Node"
    echo "======================================"
    echo
    echo "This installs the validated Smite node image: $SMITE_UPSTREAM_VERSION"
    echo "The Panel must already be reachable over HTTPS/443."
    echo

    smite_install_require_tools || { smite_install_pause; return; }
    smite_install_ensure_docker || { echo "Docker is required."; smite_install_pause; return; }

    if smite_container_exists smite-node || [ -f "$SMITE_NODE_COMPOSE" ]; then
        echo "ERROR: An existing Smite node installation was detected."
        echo "Use Status/Repair instead of the fresh installer."
        smite_install_pause
        return
    fi

    local panel_domain foreign_domain node_name temp_ca
    read -rp "Panel domain (example: ir.example.com): " panel_domain
    panel_domain="${panel_domain,,}"
    if ! smite_install_validate_domain "$panel_domain"; then
        echo "ERROR: Invalid panel domain."
        smite_install_pause
        return
    fi

    read -rp "This foreign server domain (example: kh.example.com): " foreign_domain
    foreign_domain="${foreign_domain,,}"
    if ! smite_install_validate_domain "$foreign_domain"; then
        echo "ERROR: Invalid foreign-server domain."
        smite_install_pause
        return
    fi

    read -rp "Foreign node name [node-kh]: " node_name
    node_name="${node_name:-node-kh}"
    if ! smite_install_validate_name "$node_name"; then
        echo "ERROR: Invalid node name."
        smite_install_pause
        return
    fi

    echo
    echo "Panel domain  : $panel_domain"
    echo "Foreign domain: $foreign_domain"
    echo "Node name     : $node_name"
    echo
    read -rp "Install the Foreign Smite Node? [y/N]: " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *) echo "Installation cancelled."; sleep 1; return ;;
    esac

    mkdir -p "$SMITE_NODE_DIR/certs" "$SMITE_NODE_DIR/config" || {
        echo "ERROR: Failed to create Smite node directories."
        smite_install_pause
        return
    }

    temp_ca="$(mktemp)"
    echo "Downloading the Foreign-node CA certificate from https://$panel_domain ..."
    if ! curl -fsS --retry 5 \
        "https://${panel_domain}/api/panel/ca/server" \
        -o "$temp_ca"; then
        rm -f "$temp_ca"
        echo "ERROR: Could not reach the panel CA endpoint over HTTPS/443."
        echo "Configure the IR panel 443 gateway before installing a Foreign node."
        smite_install_pause
        return
    fi

    if ! grep -q "BEGIN CERTIFICATE" "$temp_ca"; then
        rm -f "$temp_ca"
        echo "ERROR: The panel returned an invalid Foreign-node CA certificate."
        smite_install_pause
        return
    fi

    if ! smite_install_node_files "$node_name" "foreign" "${panel_domain}:443" "$temp_ca"; then
        rm -f "$temp_ca"
        smite_install_pause
        return
    fi
    rm -f "$temp_ca"

    if ! smite_install_cli_tools; then
        smite_install_pause
        return
    fi

    if ! smite_install_pull_images false; then
        echo "ERROR: Failed to pull the validated Smite node image."
        smite_install_pause
        return
    fi

    echo "Starting Foreign Smite Node..."
    if ! docker compose -f "$SMITE_NODE_COMPOSE" up -d --no-build smite-node; then
        echo "ERROR: Failed to start the Foreign Smite Node."
        smite_install_pause
        return
    fi

    if ! smite_wait_healthy smite-node 90; then
        echo "ERROR: Foreign Smite Node did not become healthy."
        smite_install_pause
        return
    fi

    if ! smite_install_apply_compatibility; then
        echo "ERROR: U-OPTI compatibility preparation failed."
        smite_install_pause
        return
    fi

    sleep 3
    if ! docker logs --since 2m smite-node 2>&1 | grep -q 'Node registered successfully'; then
        echo "WARNING: Node registration success was not found in the recent logs."
        echo "Check: docker logs smite-node"
    else
        echo "Foreign node registration: OK"
    fi

    smite_write_state "foreign" "$panel_domain" "$node_name" "$foreign_domain" || {
        echo "WARNING: Smite installed, but U-OPTI state could not be saved."
    }

    echo
    echo "======================================"
    echo "     Foreign Node Install Complete"
    echo "======================================"
    echo
    echo "Node          : $node_name"
    echo "Panel         : https://$panel_domain:443"
    echo "Foreign domain: $foreign_domain"
    echo "Compatibility overlays: active"
    echo
    echo "IMPORTANT: Panel -> Foreign Node control over 443 is configured in the gateway step."
    echo "Keep public port 8888 blocked at the firewall/provider level."

    smite_install_pause
}

show_smite_install_menu() {
    while true; do
        clear
        echo "======================================"
        echo "      Smite Install / Lifecycle"
        echo "======================================"
        echo
        echo "1) Install Panel + Iran Node"
        echo "2) Install Foreign Node"
        echo "3) Installation State"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-3]: " smite_install_choice
        case "$smite_install_choice" in
            1) smite_install_panel_iran ;;
            2) smite_install_foreign_node ;;
            3) smite_show_installation_state ;;
            0) break ;;
            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}
