#!/bin/bash

# U-OPTI - 3x-UI Docker Management
# v0.13.0

DOCKER_3XUI_IMAGE="ghcr.io/mhsanaei/3x-ui:latest"
DOCKER_3XUI_CONTAINER="3xui"
DOCKER_3XUI_DIR="/opt/3x-ui"
DOCKER_3XUI_COMPOSE_FILE="$DOCKER_3XUI_DIR/docker-compose.yml"
DOCKER_3XUI_PANEL_PORT="2053"

DOCKER_3XUI_COMPAT_ENV="$DOCKER_3XUI_DIR/compat.env"
DOCKER_3XUI_COMPAT_HELPER=""
DOCKER_3XUI_NGINX_MODULE=""
DOCKER_3XUI_INSTANCE_MODULE=""

docker_3xui_load_instance() {
    local SCRIPT_DIR

    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || return 1

    DOCKER_3XUI_INSTANCE_MODULE="$SCRIPT_DIR/docker-3xui-instance.sh"

    if [ ! -f "$DOCKER_3XUI_INSTANCE_MODULE" ]; then
        echo
        echo "ERROR: 3x-UI Instance module was not found:"
        echo "$DOCKER_3XUI_INSTANCE_MODULE"
        return 1
    fi

    # shellcheck disable=SC1090
    source "$DOCKER_3XUI_INSTANCE_MODULE"
}

docker_3xui_load_nginx() {
    local SCRIPT_DIR

    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || return 1

    DOCKER_3XUI_NGINX_MODULE="$SCRIPT_DIR/docker-3xui-nginx.sh"

    if [ ! -f "$DOCKER_3XUI_NGINX_MODULE" ]; then
        echo
        echo "ERROR: 3x-UI Nginx module was not found:"
        echo "$DOCKER_3XUI_NGINX_MODULE"
        return 1
    fi

    # shellcheck disable=SC1090
    source "$DOCKER_3XUI_NGINX_MODULE"
}

docker_3xui_load_compat() {
    local SCRIPT_DIR

    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || return 1
    DOCKER_3XUI_COMPAT_HELPER="$SCRIPT_DIR/docker-3xui-compat.sh"

    if [ ! -f "$DOCKER_3XUI_COMPAT_HELPER" ]; then
        echo
        echo "ERROR: 3x-UI compatibility helper was not found:"
        echo "$DOCKER_3XUI_COMPAT_HELPER"
        return 1
    fi

    # shellcheck disable=SC1090
    source "$DOCKER_3XUI_COMPAT_HELPER"
}

docker_3xui_valid_domain() {
    [[ "$1" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$ ]]
}

docker_3xui_generate_random_web_base_path() {
    local random_part=""

    if ! command -v openssl >/dev/null 2>&1; then
        echo "ERROR: openssl is required to generate a random Web Base Path."
        return 1
    fi

    while [ "${#random_part}" -lt 18 ]; do
        random_part="$(
            openssl rand -base64 36 2>/dev/null |
                tr -dc 'a-zA-Z0-9' |
                head -c 18
        )"
    done

    printf '/%s/\n' "$random_part"
}


docker_3xui_normalize_web_base_path() {
    local INPUT_PATH="$1"
    local NORMALIZED_PATH="$INPUT_PATH"
    local FIRST_SEGMENT=""

    if [ "$NORMALIZED_PATH" = "/" ]; then
        printf '/\n'
        return 0
    fi

    NORMALIZED_PATH="${NORMALIZED_PATH#/}"
    NORMALIZED_PATH="${NORMALIZED_PATH%/}"

    if [ -z "$NORMALIZED_PATH" ]; then
        printf '/\n'
        return 0
    fi

    if [[ ! "$NORMALIZED_PATH" =~ ^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$ ]]; then
        echo "ERROR: Invalid Web Base Path."
        echo "Allowed characters: A-Z, a-z, 0-9, _ and -."
        echo "Examples: /panel/ or /secret/panel/"
        return 1
    fi

    FIRST_SEGMENT="${NORMALIZED_PATH%%/*}"

    if [ "$FIRST_SEGMENT" = "sub" ] || [[ "$FIRST_SEGMENT" =~ ^[0-9]+$ ]]; then
        echo "ERROR: This Web Base Path conflicts with a reserved U-OPTI path."
        echo "Do not use a path whose first segment is 'sub' or only digits."
        return 1
    fi

    printf '/%s/\n' "$NORMALIZED_PATH"
}


docker_3xui_select_web_base_path() {
    local CHOICE=""
    local CUSTOM_PATH=""

    while true; do
        echo
        echo "======================================"
        echo "        Web Base Path"
        echo "======================================"
        echo
        echo "1) Random (Recommended)"
        echo "2) Root (/)"
        echo "3) Custom"
        echo "0) Cancel installation"
        echo

        echo "Select Web Base Path option [0-3]:"
        read -r CHOICE

        case "$CHOICE" in
            1)
                DOCKER_3XUI_WEB_BASE_PATH="$(
                    docker_3xui_generate_random_web_base_path
                )" || return 1
                echo
                echo "Selected Web Base Path:"
                echo "$DOCKER_3XUI_WEB_BASE_PATH"
                return 0
                ;;
            2)
                DOCKER_3XUI_WEB_BASE_PATH="/"
                echo
                echo "Selected Web Base Path:"
                echo "/"
                return 0
                ;;
            3)
                echo
                echo "Enter custom Web Base Path (example: /panel/):"
                read -r CUSTOM_PATH

                if DOCKER_3XUI_WEB_BASE_PATH="$(
                    docker_3xui_normalize_web_base_path "$CUSTOM_PATH"
                )"; then
                    echo
                    echo "Selected Web Base Path:"
                    echo "$DOCKER_3XUI_WEB_BASE_PATH"
                    return 0
                fi
                ;;
            0)
                return 1
                ;;
            *)
                echo
                echo "Invalid selection."
                ;;
        esac
    done
}


docker_3xui_save_compat_state() {
    local DOMAIN="$1"
    local SUB_PORT="$2"
    local METRICS_PORT="$3"
    local API_PORT="${4:-$DOCKER_3XUI_API_PORT}"
    local WEB_BASE_PATH="${5:-${DOCKER_3XUI_WEB_BASE_PATH:-/}}"

    if [ -z "$DOMAIN" ] || [ -z "$SUB_PORT" ] ||
       [ -z "$METRICS_PORT" ] || [ -z "$API_PORT" ] ||
       [ -z "$WEB_BASE_PATH" ]; then
        echo "ERROR: Missing compatibility state information."
        return 1
    fi

    mkdir -p "$DOCKER_3XUI_DIR" || return 1

    cat > "$DOCKER_3XUI_COMPAT_ENV" <<EOF
DOMAIN=$DOMAIN
PANEL_PORT=$DOCKER_3XUI_PANEL_PORT
API_PORT=$API_PORT
SUBSCRIPTION_PORT=$SUB_PORT
METRICS_PORT=$METRICS_PORT
WEB_BASE_PATH=$WEB_BASE_PATH
EOF

    chmod 600 "$DOCKER_3XUI_COMPAT_ENV"
}

docker_3xui_load_compat_state() {
    if [ ! -f "$DOCKER_3XUI_COMPAT_ENV" ]; then
        return 1
    fi

    # shellcheck disable=SC1090
    source "$DOCKER_3XUI_COMPAT_ENV"
}

docker_3xui_is_installed() {
    docker ps -a --format '{{.Names}}' 2>/dev/null |
        grep -Fxq "$DOCKER_3XUI_CONTAINER"
}

docker_3xui_is_running() {
    docker ps --format '{{.Names}}' 2>/dev/null |
        grep -Fxq "$DOCKER_3XUI_CONTAINER"
}

docker_3xui_port_is_in_use() {
    local PORT="$1"

    ss -lntp 2>/dev/null |
        awk -v port=":$PORT" '
            NR > 1 && $4 ~ port"$" {
                found=1
            }
            END {
                exit(found ? 0 : 1)
            }
        '
}

docker_3xui_install() {
    clear

    echo "======================================"
    echo "       Install 3x-UI in Docker"
    echo "======================================"
    echo

    if [ "$EUID" -ne 0 ]; then
        echo "Error: Root privileges are required."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is not installed."
        echo
        echo "Please install Docker first from:"
        echo "Docker Management > Install Docker"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! systemctl is-active --quiet docker 2>/dev/null; then
        echo "Error: Docker service is not active."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker compose version >/dev/null 2>&1; then
        echo "Error: Docker Compose plugin is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    local INSTANCE_ID=""
    local INSTANCE_DOMAIN=""
    local DOCKER_3XUI_WEB_BASE_PATH="/"

    echo
    echo "Enter 3x-UI Instance ID [01-99]:"
    read -r INSTANCE_ID

    if [ "$INSTANCE_ID" = "0" ]; then
        return
    fi

    if ! docker_3xui_load_instance; then
        echo
        echo "Installation cancelled because the Instance module"
        echo "could not be loaded."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_instance_validate_id "$INSTANCE_ID"; then
        echo
        echo "Error: Invalid Instance ID."
        echo "Expected format: 01, 02, 03 ..."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Enter the domain for this Sanaei 3x-UI instance (or 0 to go back):"
    read -r INSTANCE_DOMAIN

    if [ "$INSTANCE_DOMAIN" = "0" ]; then
        return
    fi

    if ! docker_3xui_valid_domain "$INSTANCE_DOMAIN"; then
        echo
        echo "Error: Invalid domain format."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_select_web_base_path; then
        echo
        echo "Installation cancelled because Web Base Path configuration was cancelled."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Preparing Instance $INSTANCE_ID..."

    if ! docker_3xui_instance_prepare_for_install         "$INSTANCE_ID"         "$INSTANCE_DOMAIN"; then

        echo
        echo "Installation cancelled because the Instance could not be prepared."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Instance $INSTANCE_ID is ready."
    echo "Domain : $DOCKER_3XUI_DOMAIN"
    echo "Panel  : $DOCKER_3XUI_PANEL_PORT"
    echo "API    : $DOCKER_3XUI_API_PORT"
    echo "Sub    : $DOCKER_3XUI_SUBSCRIPTION_PORT"
    echo "Metrics: $DOCKER_3XUI_METRICS_PORT"
    echo "Web Base Path: $DOCKER_3XUI_WEB_BASE_PATH"
    echo

    # Re-apply the Instance runtime context explicitly before any
    # installation-state checks. This prevents the legacy "3xui"
    # container name from being used for a new Instance.
    if ! docker_3xui_instance_apply_runtime_context "$INSTANCE_ID"; then
        echo
        echo "ERROR: Failed to restore Instance $INSTANCE_ID runtime context."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if docker_3xui_is_installed; then
        echo "3x-UI Docker is already installed."
        echo
        echo "Container: $DOCKER_3XUI_CONTAINER"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_load_compat; then
        echo
        echo "Installation cancelled because the compatibility helper"
        echo "could not be loaded."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    # Instance context was prepared above.
    # Port allocation and domain validation are handled by the instance layer.
    if ! docker_3xui_instance_load_state "$INSTANCE_ID"; then
        echo
        echo "Error: Failed to load Instance $INSTANCE_ID state."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_instance_apply_runtime_context "$INSTANCE_ID"; then
        echo
        echo "Error: Failed to apply Instance $INSTANCE_ID runtime context."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Using Instance $DOCKER_3XUI_INSTANCE_ID:"
    echo "  Domain        : $DOCKER_3XUI_DOMAIN"
    echo "  Container     : $DOCKER_3XUI_CONTAINER"
    echo "  Panel Port    : $DOCKER_3XUI_PANEL_PORT"
    echo "  API Port      : $DOCKER_3XUI_API_PORT"
    echo "  Subscription  : $DOCKER_3XUI_SUBSCRIPTION_PORT"
    echo "  Metrics       : $DOCKER_3XUI_METRICS_PORT"
    echo "  Data Dir      : $DOCKER_3XUI_DIR"
    echo

    echo
    echo "3x-UI installation plan:"
    echo
    echo "Image        : $DOCKER_3XUI_IMAGE"
    echo "Container    : $DOCKER_3XUI_CONTAINER"
    echo "Network      : host"
    echo "Panel Port   : $DOCKER_3XUI_PANEL_PORT"
    echo "Subscription: $DOCKER_3XUI_SUBSCRIPTION_PORT"
    echo "Metrics      : $DOCKER_3XUI_METRICS_PORT"
    echo "Web Base Path: $DOCKER_3XUI_WEB_BASE_PATH"
    echo "Domain       : $DOCKER_3XUI_DOMAIN"
    echo "Data Dir     : $DOCKER_3XUI_DIR"
    echo "Database     : $DOCKER_3XUI_DIR/db"
    echo "Certificates : $DOCKER_3XUI_DIR/cert"
    echo
    echo "Note:"
    echo "  - Existing X-UI/PRO ports are not changed."
    echo "  - Subscription and Metrics are kept on localhost."
    echo "  - Nginx and SSL are configured automatically after installation."
    echo

    echo
    echo "======================================"
    echo "   Continue with installation?"
    echo "======================================"
    echo
    echo "Press Enter or type y to continue."
    echo "Type n to cancel."
    echo

    echo "Continue [Y/n]:"
    read -r CONFIRM

    case "$CONFIRM" in
        ""|y|Y|yes|YES)
            ;;
        n|N|no|NO)
            echo
            echo "Installation cancelled."
            sleep 1
            return
            ;;
        *)
            echo
            echo "Invalid selection."
            echo "Installation cancelled."
            sleep 1
            return
            ;;
    esac

    echo
    echo "Creating 3x-UI directories..."

    mkdir -p \
        "$DOCKER_3XUI_DIR/db" \
        "$DOCKER_3XUI_DIR/cert" || {
        echo "Error: Failed to create 3x-UI directories."
        read -rp "Press Enter to return..."
        return
    }

    echo "Creating Docker Compose file..."

    cat > "$DOCKER_3XUI_COMPOSE_FILE" <<EOF
services:
  3xui:
    image: $DOCKER_3XUI_IMAGE
    container_name: $DOCKER_3XUI_CONTAINER

    cap_add:
      - NET_ADMIN
      - NET_RAW

    volumes:
      - $DOCKER_3XUI_DIR/db:/etc/x-ui/
      - $DOCKER_3XUI_DIR/cert:/root/cert/

    environment:
      XRAY_VMESS_AEAD_FORCED: "false"
      XUI_ENABLE_FAIL2BAN: "true"

    tty: true
    network_mode: host
    restart: unless-stopped
EOF

    if [ ! -s "$DOCKER_3XUI_COMPOSE_FILE" ]; then
        echo "Error: Docker Compose file was not created."
        echo "Installation cancelled."
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Pulling 3x-UI Docker image..."

    if ! docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" pull; then
        echo
        echo "Error: Failed to pull 3x-UI image."
        echo "Installation was not completed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Starting 3x-UI container..."

    if ! docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d; then
        echo
        echo "Error: Failed to start 3x-UI container."
        echo
        echo "Docker Compose status:"
        docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" ps || true
        echo
        echo "Container logs:"
        docker logs "$DOCKER_3XUI_CONTAINER" 2>&1 | tail -n 50 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Verifying 3x-UI container..."
    sleep 3

    if ! docker_3xui_is_running; then
        echo
        echo "ERROR: 3x-UI container is not running."
        echo
        docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" ps || true
        echo
        docker logs "$DOCKER_3XUI_CONTAINER" 2>&1 | tail -n 50 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    DB_FILE="$DOCKER_3XUI_DIR/db/x-ui.db"

    echo
    echo "Waiting for 3x-UI database..."

    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if [ -s "$DB_FILE" ]; then
            break
        fi
        sleep 1
    done

    if [ ! -s "$DB_FILE" ]; then
        echo "ERROR: 3x-UI database was not created:"
        echo "$DB_FILE"
        echo
        docker logs "$DOCKER_3XUI_CONTAINER" 2>&1 | tail -n 50 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Applying Sanaei compatibility settings..."
    echo

    # Ensure the compatibility layer uses the ports reserved for this instance.
    if ! docker_3xui_instance_apply_compat_context "$INSTANCE_ID"; then
        echo
        echo "ERROR: Failed to apply Instance $INSTANCE_ID compatibility context."
        echo "The container will be stopped to avoid leaving a partial configuration."
        docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null 2>&1 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Instance compatibility ports:"
    echo "  Panel        : $DOCKER_3XUI_COMPAT_PANEL_PORT"
    echo "  API          : $DOCKER_3XUI_COMPAT_API_PORT"
    echo "  Subscription : $DOCKER_3XUI_COMPAT_SUB_PORT"
    echo "  Metrics      : $DOCKER_3XUI_COMPAT_METRICS_PORT"
    echo

    if ! docker_3xui_compat_configure \
        "$DB_FILE" \
        "$DOCKER_3XUI_DOMAIN" \
        "$DOCKER_3XUI_WEB_BASE_PATH" \
        "$DOCKER_3XUI_CONTAINER"; then

        echo
        echo "ERROR: Compatibility configuration failed."
        echo "The container will be stopped to avoid leaving a partial configuration."
        docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null 2>&1 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_save_compat_state \
        "$DOCKER_3XUI_DOMAIN" \
        "$DOCKER_3XUI_COMPAT_SUB_PORT" \
        "$DOCKER_3XUI_COMPAT_METRICS_PORT" \
        "$DOCKER_3XUI_COMPAT_API_PORT" \
        "$DOCKER_3XUI_WEB_BASE_PATH"; then

        echo
        echo "ERROR: Failed to save 3x-UI compatibility state."
        docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null 2>&1 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Restarting 3x-UI to apply Panel and Xray settings..."

    if ! docker restart "$DOCKER_3XUI_CONTAINER" >/dev/null; then
        echo
        echo "ERROR: Failed to restart 3x-UI after compatibility configuration."
        echo
        docker logs "$DOCKER_3XUI_CONTAINER" 2>&1 | tail -n 50 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    sleep 3

    echo
    echo "Verifying final 3x-UI listeners..."

    if ! docker_3xui_port_is_in_use "$DOCKER_3XUI_PANEL_PORT"; then
        echo "ERROR: Panel port $DOCKER_3XUI_PANEL_PORT is not listening."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_port_is_in_use "$DOCKER_3XUI_COMPAT_API_PORT"; then
        echo "ERROR: Xray API port $DOCKER_3XUI_COMPAT_API_PORT is not listening."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_compat_verify_api \
        "$DB_FILE" \
        "$DOCKER_3XUI_COMPAT_API_PORT"; then

        echo "ERROR: Xray API configuration verification failed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_port_is_in_use "$DOCKER_3XUI_COMPAT_SUB_PORT"; then
        echo "ERROR: Subscription port $DOCKER_3XUI_COMPAT_SUB_PORT is not listening."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    METRICS_CHECK_PORT="$(docker_3xui_compat_get_metrics_port "$DB_FILE" || true)"

    if [ "$METRICS_CHECK_PORT" != "$DOCKER_3XUI_COMPAT_METRICS_PORT" ]; then
        echo "ERROR: Metrics configuration verification failed."
        echo "Expected: 127.0.0.1:$DOCKER_3XUI_COMPAT_METRICS_PORT"
        echo "Detected : ${METRICS_CHECK_PORT:-Not detected}"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "All Instance $INSTANCE_ID listeners verified successfully."
    echo "  Panel        : $DOCKER_3XUI_PANEL_PORT"
    echo "  API          : $DOCKER_3XUI_COMPAT_API_PORT"
    echo "  Subscription : $DOCKER_3XUI_COMPAT_SUB_PORT"
    echo "  Metrics      : $DOCKER_3XUI_COMPAT_METRICS_PORT"
    echo
    echo
    echo "Configuring Nginx / SSL public access..."
    echo

    if ! docker_3xui_load_nginx; then
        echo
        echo "WARNING: Sanaei Nginx / SSL module could not be loaded."
        echo "3x-UI installation completed, but public HTTPS access was not configured."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_nginx_setup 1; then
        echo
        echo "WARNING: Sanaei Nginx / SSL configuration failed."
        echo "3x-UI installation completed, but public HTTPS access was not configured."
        echo
        echo "You can retry it later from:"
        echo "3x-UI Docker Management > 11) Nginx / SSL Configuration"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "======================================"
    echo "      3x-UI Installation OK"
    echo "======================================"
    echo
    echo "Container     : $DOCKER_3XUI_CONTAINER"
    echo "Status        : Running"
    echo "Image         : $DOCKER_3XUI_IMAGE"
    echo "Network       : host"
    echo "Panel Port    : $DOCKER_3XUI_PANEL_PORT"
    echo "Subscription  : $DOCKER_3XUI_COMPAT_SUB_PORT"
    echo "Metrics       : $DOCKER_3XUI_COMPAT_METRICS_PORT"
    echo "Web Base Path : $DOCKER_3XUI_WEB_BASE_PATH"
    echo "Domain        : $DOMAIN"
    echo "Data Dir      : $DOCKER_3XUI_DIR/db"
    echo "Cert Dir      : $DOCKER_3XUI_DIR/cert"
    echo
    echo "Panel URL:"
    if [ "$DOCKER_3XUI_WEB_BASE_PATH" = "/" ]; then
        echo "https://$DOMAIN/"
    else
        echo "https://$DOMAIN$DOCKER_3XUI_WEB_BASE_PATH"
    fi
    echo
    echo "Subscription URI:"
    echo "https://$DOMAIN/sub/"
    echo
    echo "Nginx:"
    echo "Configured automatically."
    echo "SSL: Let's Encrypt"
    echo
    echo "Docker Compose:"
    echo "$DOCKER_3XUI_COMPOSE_FILE"
    echo
    echo "Compatibility state:"
    echo "$DOCKER_3XUI_COMPAT_ENV"
    echo
    echo "Installation completed successfully."
    echo "Press Enter to return to the Docker 3x-UI menu..."
    read -r
}

docker_3xui_start() {
    clear

    echo "======================================"
    echo "            Start 3x-UI"
    echo "======================================"
    echo

    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_is_installed; then
        echo "Error: 3x-UI container is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! systemctl is-active --quiet docker 2>/dev/null; then
        echo "Error: Docker service is not active."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if docker_3xui_is_running; then
        echo "3x-UI is already running."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Starting 3x-UI container..."
    echo

    if ! docker start "$DOCKER_3XUI_CONTAINER" >/dev/null; then
        echo "Error: Failed to start 3x-UI container."
        echo
        docker logs "$DOCKER_3XUI_CONTAINER" 2>&1 | tail -n 50 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    sleep 2

    if ! docker_3xui_is_running; then
        echo
        echo "ERROR: 3x-UI container did not remain running."
        echo
        docker inspect "$DOCKER_3XUI_CONTAINER" \
            --format 'Status: {{.State.Status}}\nStarted: {{.State.StartedAt}}' 2>/dev/null || true
        echo
        docker logs "$DOCKER_3XUI_CONTAINER" 2>&1 | tail -n 50 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "3x-UI started successfully."
    echo "Status: Running"
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_stop() {
    clear

    echo "======================================"
    echo "             Stop 3x-UI"
    echo "======================================"
    echo

    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_is_installed; then
        echo "Error: 3x-UI container is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! systemctl is-active --quiet docker 2>/dev/null; then
        echo "Error: Docker service is not active."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_is_running; then
        echo "3x-UI is already stopped."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Stopping 3x-UI container..."
    echo

    if ! docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null; then
        echo "Error: Failed to stop 3x-UI container."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    sleep 1

    if docker_3xui_is_running; then
        echo "ERROR: 3x-UI container is still running."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "3x-UI stopped successfully."
    echo "Status: Stopped"
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_restart() {
    clear

    echo "======================================"
    echo "           Restart 3x-UI"
    echo "======================================"
    echo

    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_is_installed; then
        echo "Error: 3x-UI container is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! systemctl is-active --quiet docker 2>/dev/null; then
        echo "Error: Docker service is not active."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Restarting 3x-UI container..."
    echo

    if ! docker restart "$DOCKER_3XUI_CONTAINER" >/dev/null; then
        echo "Error: Failed to restart 3x-UI container."
        echo
        docker logs "$DOCKER_3XUI_CONTAINER" 2>&1 | tail -n 50 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    sleep 2

    if ! docker_3xui_is_running; then
        echo
        echo "ERROR: 3x-UI container did not remain running after restart."
        echo
        docker inspect "$DOCKER_3XUI_CONTAINER" \
            --format 'Status: {{.State.Status}}\nStarted: {{.State.StartedAt}}' 2>/dev/null || true
        echo
        docker logs "$DOCKER_3XUI_CONTAINER" 2>&1 | tail -n 50 || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "3x-UI restarted successfully."
    echo "Status: Running"
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_update() {
    clear

    echo "======================================"
    echo "            Update 3x-UI"
    echo "======================================"
    echo

    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_is_installed; then
        echo "Error: 3x-UI container is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! systemctl is-active --quiet docker 2>/dev/null; then
        echo "Error: Docker service is not active."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker compose version >/dev/null 2>&1; then
        echo "Error: Docker Compose plugin is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ ! -f "$DOCKER_3XUI_COMPOSE_FILE" ]; then
        echo "Error: Docker Compose file was not found:"
        echo "$DOCKER_3XUI_COMPOSE_FILE"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    CURRENT_IMAGE=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.Config.Image}}' 2>/dev/null || true)

    CURRENT_IMAGE_ID=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.Image}}' 2>/dev/null || true)

    CURRENT_STATUS=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.State.Status}}' 2>/dev/null || true)

    if [ -z "$CURRENT_IMAGE" ] || [ -z "$CURRENT_IMAGE_ID" ]; then
        echo "Error: Unable to determine the current 3x-UI image."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Current Image : $CURRENT_IMAGE"
    echo "Container     : $DOCKER_3XUI_CONTAINER"
    echo "Status        : ${CURRENT_STATUS:-Unknown}"
    echo

    echo "3x-UI Docker update will:"
    echo "  1. Create a backup of the current 3x-UI data and Compose file."
    echo "  2. Pull the latest Docker image."
    echo "  3. Recreate the container using the existing persistent data."
    echo "  4. Verify the new container and panel port."
    echo "  5. Restore the previous image automatically if the update fails."
    echo

    read -rp "Continue with 3x-UI update? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "Update cancelled."
            sleep 1
            return
            ;;
    esac

    TIMESTAMP=$(date '+%Y%m%d-%H%M%S-%N')
    UPDATE_BACKUP_DIR="$DOCKER_3XUI_DIR/backups/$TIMESTAMP-pre-update"
    ROLLBACK_IMAGE="u-opti/3x-ui-rollback:$TIMESTAMP"

    echo
    echo "Creating update backup..."

    if ! mkdir -p "$UPDATE_BACKUP_DIR"; then
        echo "Error: Failed to create update backup directory."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ -f "$DOCKER_3XUI_COMPOSE_FILE" ]; then
        if ! cp -f "$DOCKER_3XUI_COMPOSE_FILE" "$UPDATE_BACKUP_DIR/docker-compose.yml"; then
            echo "Error: Failed to back up Docker Compose file."
            rm -rf "$UPDATE_BACKUP_DIR"
            echo
            read -rp "Press Enter to return..."
            return
        fi
    fi

    echo "Backing up database..."

    if ! tar -C "$DOCKER_3XUI_DIR" \
        -czf "$UPDATE_BACKUP_DIR/db.tar.gz" \
        db; then
        echo "Error: Failed to back up the 3x-UI database."
        rm -rf "$UPDATE_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Backing up certificates..."

    if ! tar -C "$DOCKER_3XUI_DIR" \
        -czf "$UPDATE_BACKUP_DIR/cert.tar.gz" \
        cert; then
        echo "Error: Failed to back up the 3x-UI certificate directory."
        rm -rf "$UPDATE_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    cat > "$UPDATE_BACKUP_DIR/update-info.txt" <<EOF
3x-UI Container: $DOCKER_3XUI_CONTAINER
Previous Image: $CURRENT_IMAGE
Previous Image ID: $CURRENT_IMAGE_ID
Previous Status: $CURRENT_STATUS
Backup Time: $(date --iso-8601=seconds)
EOF

    chmod 700 "$UPDATE_BACKUP_DIR"
    chmod 600 "$UPDATE_BACKUP_DIR"/*

    echo
    echo "Update backup created:"
    echo "$UPDATE_BACKUP_DIR"

    echo
    echo "Preparing rollback image..."

    if ! docker tag "$CURRENT_IMAGE_ID" "$ROLLBACK_IMAGE"; then
        echo "Error: Failed to prepare rollback image."
        echo "The current container was not changed."
        rm -rf "$UPDATE_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Pulling latest 3x-UI image..."

    if ! docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" pull; then
        echo
        echo "ERROR: Failed to pull the latest 3x-UI image."
        echo "The running container was not changed."
        docker image rm "$ROLLBACK_IMAGE" >/dev/null 2>&1 || true
        echo
        echo "Backup retained at:"
        echo "$UPDATE_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    NEW_IMAGE_ID=$(docker image inspect "$DOCKER_3XUI_IMAGE" \
        --format '{{.Id}}' 2>/dev/null || true)

    echo
    echo "Image pull completed."

    if [ -n "$NEW_IMAGE_ID" ] && [ "$NEW_IMAGE_ID" = "$CURRENT_IMAGE_ID" ]; then
        echo "3x-UI image is already up to date."
        echo "No container recreation was required."
        docker image rm "$ROLLBACK_IMAGE" >/dev/null 2>&1 || true
        rm -rf "$UPDATE_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Stopping current 3x-UI container..."

    if docker_3xui_is_running; then
        if ! docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null; then
            echo "ERROR: Failed to stop the current 3x-UI container."
            docker image rm "$ROLLBACK_IMAGE" >/dev/null 2>&1 || true
            echo
            read -rp "Press Enter to return..."
            return
        fi
    fi

    echo
    echo "Recreating 3x-UI container..."

    if ! docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d --force-recreate; then
        echo
        echo "ERROR: Failed to start the new 3x-UI container."
        echo "Starting automatic rollback..."

        sed -i "s|^[[:space:]]*image:.*|    image: $ROLLBACK_IMAGE|" "$DOCKER_3XUI_COMPOSE_FILE"

        if docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d --force-recreate; then
            echo "Rollback container started successfully."
            cp -f "$UPDATE_BACKUP_DIR/docker-compose.yml" "$DOCKER_3XUI_COMPOSE_FILE"
        else
            echo "WARNING: Automatic rollback could not start the container."
            echo "Previous Compose file retained at:"
            echo "$UPDATE_BACKUP_DIR/docker-compose.yml"
        fi

        docker image rm "$ROLLBACK_IMAGE" >/dev/null 2>&1 || true

        echo
        echo "Update failed."
        echo "Backup retained at:"
        echo "$UPDATE_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Verifying updated container..."

    sleep 3

    if ! docker_3xui_is_running; then
        echo "ERROR: Updated 3x-UI container is not running."
        echo "Starting automatic rollback..."

        docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null 2>&1 || true
        sed -i "s|^[[:space:]]*image:.*|    image: $ROLLBACK_IMAGE|" "$DOCKER_3XUI_COMPOSE_FILE"

        if docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d --force-recreate; then
            echo "Rollback container started successfully."
            cp -f "$UPDATE_BACKUP_DIR/docker-compose.yml" "$DOCKER_3XUI_COMPOSE_FILE"
        else
            echo "WARNING: Automatic rollback could not start the container."
            echo "Previous Compose file retained at:"
            echo "$UPDATE_BACKUP_DIR/docker-compose.yml"
        fi

        docker image rm "$ROLLBACK_IMAGE" >/dev/null 2>&1 || true

        echo
        echo "Update failed."
        echo "Backup retained at:"
        echo "$UPDATE_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    PANEL_PORT="$DOCKER_3XUI_PANEL_PORT"

    if docker exec "$DOCKER_3XUI_CONTAINER" sh -c \
        'command -v x-ui >/dev/null 2>&1 && x-ui settings' \
        >/tmp/u-opti-3xui-update-settings.txt 2>/dev/null; then

        DETECTED_PANEL_PORT=$(sed -n 's/^port:[[:space:]]*//p' \
            /tmp/u-opti-3xui-update-settings.txt | head -n 1)

        if [ -n "$DETECTED_PANEL_PORT" ]; then
            PANEL_PORT="$DETECTED_PANEL_PORT"
        fi
    fi

    rm -f /tmp/u-opti-3xui-update-settings.txt

    if ! docker_3xui_port_is_in_use "$PANEL_PORT"; then
        echo
        echo "ERROR: Updated 3x-UI container is running, but panel port"
        echo "$PANEL_PORT is not listening."
        echo "Starting automatic rollback..."

        docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null 2>&1 || true
        sed -i "s|^[[:space:]]*image:.*|    image: $ROLLBACK_IMAGE|" "$DOCKER_3XUI_COMPOSE_FILE"

        if docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d --force-recreate; then
            echo "Rollback container started successfully."
            cp -f "$UPDATE_BACKUP_DIR/docker-compose.yml" "$DOCKER_3XUI_COMPOSE_FILE"
        else
            echo "WARNING: Automatic rollback could not start the container."
            echo "Previous Compose file retained at:"
            echo "$UPDATE_BACKUP_DIR/docker-compose.yml"
        fi

        docker image rm "$ROLLBACK_IMAGE" >/dev/null 2>&1 || true

        echo
        echo "Update failed."
        echo "Backup retained at:"
        echo "$UPDATE_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    NEW_IMAGE=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.Config.Image}}' 2>/dev/null || true)

    NEW_IMAGE_ID=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.Image}}' 2>/dev/null || true)

    echo
    echo "======================================"
    echo "         3x-UI Update OK"
    echo "======================================"
    echo
    echo "Previous Image : $CURRENT_IMAGE"
    echo "New Image      : $NEW_IMAGE"
    echo "Container      : $DOCKER_3XUI_CONTAINER"
    echo "Status         : Running"
    echo "Panel Port     : $PANEL_PORT"
    echo
    echo "Persistent data was preserved."
    echo "Database backup:"
    echo "$UPDATE_BACKUP_DIR/db.tar.gz"
    echo
    echo "Update backup:"
    echo "$UPDATE_BACKUP_DIR"

    cat > "$UPDATE_BACKUP_DIR/update-info.txt" <<EOF
3x-UI Container: $DOCKER_3XUI_CONTAINER
Previous Image: $CURRENT_IMAGE
Previous Image ID: $CURRENT_IMAGE_ID
New Image: $NEW_IMAGE
New Image ID: $NEW_IMAGE_ID
Update Time: $(date --iso-8601=seconds)
Panel Port: $PANEL_PORT
EOF

    chmod 600 "$UPDATE_BACKUP_DIR/update-info.txt"

    docker image rm "$ROLLBACK_IMAGE" >/dev/null 2>&1 || true

    echo
    echo "Note: The previous Docker image is retained by Docker until it is"
    echo "manually removed or cleaned up."
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_backup() {
    clear

    echo "======================================"
    echo "           Backup 3x-UI"
    echo "======================================"
    echo

    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_is_installed; then
        echo "Error: 3x-UI container is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker compose version >/dev/null 2>&1; then
        echo "Error: Docker Compose plugin is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ ! -d "$DOCKER_3XUI_DIR" ]; then
        echo "Error: 3x-UI data directory was not found:"
        echo "$DOCKER_3XUI_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    TIMESTAMP=$(date '+%Y%m%d-%H%M%S-%N')
    BACKUP_DIR="$DOCKER_3XUI_DIR/backups/$TIMESTAMP"

    echo "Preparing backup..."
    echo
    echo "Backup Directory:"
    echo "$BACKUP_DIR"
    echo

    if ! mkdir -p "$BACKUP_DIR"; then
        echo "Error: Failed to create backup directory."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    BACKUP_FAILED=false

    echo "Backing up Docker Compose file..."

    if [ -f "$DOCKER_3XUI_COMPOSE_FILE" ]; then
        if ! cp -f "$DOCKER_3XUI_COMPOSE_FILE" "$BACKUP_DIR/docker-compose.yml"; then
            echo "ERROR: Failed to back up Docker Compose file."
            BACKUP_FAILED=true
        fi
    else
        echo "WARNING: Docker Compose file was not found."
    fi

    echo "Backing up database..."

    if [ -d "$DOCKER_3XUI_DIR/db" ]; then
        if ! tar -C "$DOCKER_3XUI_DIR" \
            -czf "$BACKUP_DIR/db.tar.gz" \
            db; then
            echo "ERROR: Failed to back up database."
            BACKUP_FAILED=true
        fi
    else
        echo "WARNING: Database directory was not found."
        BACKUP_FAILED=true
    fi

    echo "Backing up certificates..."

    if [ -d "$DOCKER_3XUI_DIR/cert" ]; then
        if ! tar -C "$DOCKER_3XUI_DIR" \
            -czf "$BACKUP_DIR/cert.tar.gz" \
            cert; then
            echo "ERROR: Failed to back up certificate directory."
            BACKUP_FAILED=true
        fi
    else
        echo "WARNING: Certificate directory was not found."
        BACKUP_FAILED=true
    fi

    IMAGE_NAME=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.Config.Image}}' 2>/dev/null || true)

    IMAGE_ID=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.Image}}' 2>/dev/null || true)

    CONTAINER_STATUS=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.State.Status}}' 2>/dev/null || true)

    PANEL_PORT="$DOCKER_3XUI_PANEL_PORT"
    SUBSCRIPTION_PORT=""
    METRICS_PORT=""
    WEB_BASE_PATH="/"

    if docker_3xui_load_compat_state; then
        SUBSCRIPTION_PORT="${SUBSCRIPTION_PORT:-}"
        METRICS_PORT="${METRICS_PORT:-}"
    fi

    SUBSCRIPTION_PORT="${SUBSCRIPTION_PORT:-2096}"

    TEMP_SETTINGS_FILE=$(mktemp)

    if docker_3xui_is_running; then
        if docker exec "$DOCKER_3XUI_CONTAINER" sh -c \
            'command -v x-ui >/dev/null 2>&1 && x-ui settings' \
            >"$TEMP_SETTINGS_FILE" 2>/dev/null; then

            DETECTED_PANEL_PORT=$(sed -n 's/^port:[[:space:]]*//p' \
                "$TEMP_SETTINGS_FILE" | head -n 1)

            if [ -n "$DETECTED_PANEL_PORT" ]; then
                PANEL_PORT="$DETECTED_PANEL_PORT"
            fi

            DETECTED_BASE_PATH=$(sed -n 's/^webBasePath:[[:space:]]*//p' \
                "$TEMP_SETTINGS_FILE" | head -n 1)

            if [ -n "$DETECTED_BASE_PATH" ]; then
                WEB_BASE_PATH="$DETECTED_BASE_PATH"
            fi
        fi
    fi

    rm -f "$TEMP_SETTINGS_FILE"

    cat > "$BACKUP_DIR/backup-info.txt" <<EOF
3x-UI Container: $DOCKER_3XUI_CONTAINER
Image: $IMAGE_NAME
Image ID: $IMAGE_ID
Container Status: $CONTAINER_STATUS
Panel Port: $PANEL_PORT
Subscription Port: $SUBSCRIPTION_PORT
Web Base Path: $WEB_BASE_PATH
Backup Time: $(date --iso-8601=seconds)
Compose File: $DOCKER_3XUI_COMPOSE_FILE
Data Directory: $DOCKER_3XUI_DIR/db
Certificate Directory: $DOCKER_3XUI_DIR/cert
EOF

    if [ "$BACKUP_FAILED" = "true" ]; then
        echo
        echo "======================================"
        echo "           Backup Failed"
        echo "======================================"
        echo
        echo "The backup could not be completed successfully."
        echo "Incomplete backup retained at:"
        echo "$BACKUP_DIR"
        echo
        chmod 700 "$BACKUP_DIR"
        find "$BACKUP_DIR" -type f -exec chmod 600 {} \;
        read -rp "Press Enter to return..."
        return
    fi

    chmod 700 "$BACKUP_DIR"
    find "$BACKUP_DIR" -type f -exec chmod 600 {} \;

    echo
    echo "Validating backup..."

    BACKUP_OK=true

    for FILE in \
        "$BACKUP_DIR/docker-compose.yml" \
        "$BACKUP_DIR/db.tar.gz" \
        "$BACKUP_DIR/cert.tar.gz" \
        "$BACKUP_DIR/backup-info.txt"; do

        if [ ! -s "$FILE" ]; then
            echo "Missing or empty backup file:"
            echo "$FILE"
            BACKUP_OK=false
        fi
    done

    if [ "$BACKUP_OK" != "true" ]; then
        echo
        echo "ERROR: Backup validation failed."
        echo "Backup retained at:"
        echo "$BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "======================================"
    echo "          3x-UI Backup OK"
    echo "======================================"
    echo
    echo "Backup Directory:"
    echo "$BACKUP_DIR"
    echo
    echo "Files:"
    echo "  - docker-compose.yml"
    echo "  - db.tar.gz"
    echo "  - cert.tar.gz"
    echo "  - backup-info.txt"
    echo

    read -rp "Press Enter to return..."
}
docker_3xui_backup_validate() {
    local BACKUP_DIR="$1"
    local BACKUP_OK=true

    if [ ! -d "$BACKUP_DIR" ]; then
        echo "ERROR: Backup directory does not exist:"
        echo "$BACKUP_DIR"
        return 1
    fi

    for FILE in \
        "$BACKUP_DIR/docker-compose.yml" \
        "$BACKUP_DIR/db.tar.gz" \
        "$BACKUP_DIR/cert.tar.gz" \
        "$BACKUP_DIR/backup-info.txt"; do

        if [ ! -s "$FILE" ]; then
            echo "ERROR: Missing or empty backup file:"
            echo "$FILE"
            BACKUP_OK=false
        fi
    done

    if [ "$BACKUP_OK" != "true" ]; then
        return 1
    fi

    if ! tar -tzf "$BACKUP_DIR/db.tar.gz" >/dev/null 2>&1; then
        echo "ERROR: Database backup archive is invalid."
        return 1
    fi

    if ! tar -tzf "$BACKUP_DIR/cert.tar.gz" >/dev/null 2>&1; then
        echo "ERROR: Certificate backup archive is invalid."
        return 1
    fi

    if ! grep -q '^services:' "$BACKUP_DIR/docker-compose.yml"; then
        echo "ERROR: Docker Compose file does not appear to be valid."
        return 1
    fi

    return 0
}

docker_3xui_restore() {
    clear

    echo "======================================"
    echo "          Restore 3x-UI"
    echo "======================================"
    echo

    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is not installed."
        echo
        echo "Please install Docker first."
        read -rp "Press Enter to return..."
        return
    fi

    if ! systemctl is-active --quiet docker 2>/dev/null; then
        echo "Error: Docker service is not active."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker compose version >/dev/null 2>&1; then
        echo "Error: Docker Compose plugin is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ ! -d "$DOCKER_3XUI_DIR/backups" ]; then
        echo "No 3x-UI backups were found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    mapfile -t BACKUP_DIRS < <(
        find "$DOCKER_3XUI_DIR/backups" \
            -mindepth 1 \
            -maxdepth 1 \
            -type d \
            -printf '%T@ %p\n' 2>/dev/null |
        sort -nr |
        cut -d' ' -f2-
    )

    if [ "${#BACKUP_DIRS[@]}" -eq 0 ]; then
        echo "No 3x-UI backups were found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Available 3x-UI backups:"
    echo

    VALID_BACKUPS=()

    for BACKUP_DIR in "${BACKUP_DIRS[@]}"; do
        if docker_3xui_backup_validate "$BACKUP_DIR" >/dev/null 2>&1; then
            VALID_BACKUPS+=("$BACKUP_DIR")
        fi
    done

    if [ "${#VALID_BACKUPS[@]}" -eq 0 ]; then
        echo "No valid 3x-UI backups were found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    INDEX=1

    for BACKUP_DIR in "${VALID_BACKUPS[@]}"; do
        BACKUP_NAME="$(basename "$BACKUP_DIR")"
        BACKUP_TIME=""

        if [ -f "$BACKUP_DIR/backup-info.txt" ]; then
            BACKUP_TIME=$(sed -n 's/^Backup Time:[[:space:]]*//p' \
                "$BACKUP_DIR/backup-info.txt" | head -n 1)
        fi

        echo "$INDEX) $BACKUP_NAME"

        if [ -n "$BACKUP_TIME" ]; then
            echo "   Backup Time: $BACKUP_TIME"
        fi

        INDEX=$((INDEX + 1))
    done

    echo
    echo "0) Cancel"
    echo

    read -rp "Please select a backup [0-${#VALID_BACKUPS[@]}]: " RESTORE_CHOICE

    if [ "$RESTORE_CHOICE" = "0" ]; then
        echo
        echo "Restore cancelled."
        sleep 1
        return
    fi

    if ! [[ "$RESTORE_CHOICE" =~ ^[0-9]+$ ]] || \
       [ "$RESTORE_CHOICE" -lt 1 ] || \
       [ "$RESTORE_CHOICE" -gt "${#VALID_BACKUPS[@]}" ]; then

        echo
        echo "Invalid backup selection."
        sleep 2
        return
    fi

    SELECTED_BACKUP="${VALID_BACKUPS[$((RESTORE_CHOICE - 1))]}"

    echo
    echo "Selected Backup:"
    echo "$SELECTED_BACKUP"
    echo

    if ! docker_3xui_backup_validate "$SELECTED_BACKUP"; then
        echo
        echo "Restore cancelled because the selected backup is invalid."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ -f "$SELECTED_BACKUP/backup-info.txt" ]; then
        echo "Backup Information:"
        sed -n '1,20p' "$SELECTED_BACKUP/backup-info.txt"
        echo
    fi

    echo "WARNING:"
    echo "Restoring this backup will replace the current 3x-UI"
    echo "database, certificates, and Docker Compose configuration."
    echo
    echo "Current data will first be backed up as a safety copy."
    echo

    read -rp "Continue with restore? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
            echo "Restore cancelled."
            sleep 1
            return
            ;;
    esac

    SAFETY_BACKUP_DIR="$DOCKER_3XUI_DIR/backups/$(date '+%Y%m%d-%H%M%S-%N')-pre-restore"

    echo
    echo "Creating pre-restore safety backup..."
    echo "$SAFETY_BACKUP_DIR"

    mkdir -p "$SAFETY_BACKUP_DIR" || {
        echo "ERROR: Failed to create pre-restore safety backup directory."
        echo
        read -rp "Press Enter to return..."
        return
    }

    SAFETY_BACKUP_OK=true

    if [ -f "$DOCKER_3XUI_COMPOSE_FILE" ]; then
        cp -f "$DOCKER_3XUI_COMPOSE_FILE" \
            "$SAFETY_BACKUP_DIR/docker-compose.yml" ||
            SAFETY_BACKUP_OK=false
    fi

    if [ -d "$DOCKER_3XUI_DIR/db" ]; then
        tar -C "$DOCKER_3XUI_DIR" \
            -czf "$SAFETY_BACKUP_DIR/db.tar.gz" \
            db || SAFETY_BACKUP_OK=false
    else
        SAFETY_BACKUP_OK=false
    fi

    if [ -d "$DOCKER_3XUI_DIR/cert" ]; then
        tar -C "$DOCKER_3XUI_DIR" \
            -czf "$SAFETY_BACKUP_DIR/cert.tar.gz" \
            cert || SAFETY_BACKUP_OK=false
    else
        SAFETY_BACKUP_OK=false
    fi

    cat > "$SAFETY_BACKUP_DIR/backup-info.txt" <<EOF
Backup Type: Pre-Restore Safety Backup
Backup Time: $(date --iso-8601=seconds)
Source Backup: $SELECTED_BACKUP
EOF

    if [ "$SAFETY_BACKUP_OK" != "true" ]; then
        echo
        echo "ERROR: Pre-restore safety backup could not be completed."
        echo "Restore was NOT performed."
        echo
        echo "Safety backup directory:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    chmod 700 "$SAFETY_BACKUP_DIR"
    find "$SAFETY_BACKUP_DIR" -type f -exec chmod 600 {} \;

    echo "Pre-restore safety backup created successfully."

    CONTAINER_WAS_RUNNING=false

    if docker_3xui_is_running; then
        CONTAINER_WAS_RUNNING=true
        echo
        echo "Stopping current 3x-UI container..."

        if ! docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null; then
            echo "ERROR: Failed to stop the current 3x-UI container."
            echo "Restore was NOT performed."
            echo
            read -rp "Press Enter to return..."
            return
        fi
    fi

    echo
    echo "Restoring Docker Compose file..."

    if ! cp -f "$SELECTED_BACKUP/docker-compose.yml" "$DOCKER_3XUI_COMPOSE_FILE"; then
        echo "ERROR: Failed to restore Docker Compose file."
        echo "Attempting to restore the safety backup..."

        cp -f "$SAFETY_BACKUP_DIR/docker-compose.yml" "$DOCKER_3XUI_COMPOSE_FILE" 2>/dev/null || true

        if [ "$CONTAINER_WAS_RUNNING" = "true" ]; then
            docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d >/dev/null 2>&1 || true
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Restoring database..."

    rm -rf "$DOCKER_3XUI_DIR/db"

    if ! tar -C "$DOCKER_3XUI_DIR" \
        -xzf "$SELECTED_BACKUP/db.tar.gz"; then

        echo "ERROR: Failed to restore database."
        echo "Attempting automatic rollback..."

        rm -rf "$DOCKER_3XUI_DIR/db"
        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/db.tar.gz" >/dev/null 2>&1 || true

        cp -f "$SAFETY_BACKUP_DIR/docker-compose.yml" \
            "$DOCKER_3XUI_COMPOSE_FILE" 2>/dev/null || true

        if [ "$CONTAINER_WAS_RUNNING" = "true" ]; then
            docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d >/dev/null 2>&1 || true
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Restoring certificates..."

    rm -rf "$DOCKER_3XUI_DIR/cert"

    if ! tar -C "$DOCKER_3XUI_DIR" \
        -xzf "$SELECTED_BACKUP/cert.tar.gz"; then

        echo "ERROR: Failed to restore certificates."
        echo "Attempting automatic rollback..."

        rm -rf "$DOCKER_3XUI_DIR/db"
        rm -rf "$DOCKER_3XUI_DIR/cert"

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/db.tar.gz" >/dev/null 2>&1 || true

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/cert.tar.gz" >/dev/null 2>&1 || true

        cp -f "$SAFETY_BACKUP_DIR/docker-compose.yml" \
            "$DOCKER_3XUI_COMPOSE_FILE" 2>/dev/null || true

        if [ "$CONTAINER_WAS_RUNNING" = "true" ]; then
            docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d >/dev/null 2>&1 || true
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Validating restored Docker Compose file..."

    if ! grep -q '^services:' "$DOCKER_3XUI_COMPOSE_FILE"; then
        echo "ERROR: Restored Docker Compose file appears to be invalid."
        echo "Attempting automatic rollback..."

        cp -f "$SAFETY_BACKUP_DIR/docker-compose.yml" \
            "$DOCKER_3XUI_COMPOSE_FILE" 2>/dev/null || true

        rm -rf "$DOCKER_3XUI_DIR/db"
        rm -rf "$DOCKER_3XUI_DIR/cert"

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/db.tar.gz" >/dev/null 2>&1 || true

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/cert.tar.gz" >/dev/null 2>&1 || true

        if [ "$CONTAINER_WAS_RUNNING" = "true" ]; then
            docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d >/dev/null 2>&1 || true
        fi

        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Starting restored 3x-UI container..."

    if ! docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d; then
        echo
        echo "ERROR: Failed to start restored 3x-UI container."
        echo "Attempting automatic rollback..."

        docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null 2>&1 || true

        cp -f "$SAFETY_BACKUP_DIR/docker-compose.yml" \
            "$DOCKER_3XUI_COMPOSE_FILE" 2>/dev/null || true

        rm -rf "$DOCKER_3XUI_DIR/db"
        rm -rf "$DOCKER_3XUI_DIR/cert"

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/db.tar.gz" >/dev/null 2>&1 || true

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/cert.tar.gz" >/dev/null 2>&1 || true

        docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d >/dev/null 2>&1 || true

        echo
        echo "Safety backup retained at:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Verifying restored 3x-UI container..."

    sleep 3

    if ! docker_3xui_is_running; then
        echo "ERROR: Restored 3x-UI container is not running."
        echo "Attempting automatic rollback..."

        docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null 2>&1 || true

        cp -f "$SAFETY_BACKUP_DIR/docker-compose.yml" \
            "$DOCKER_3XUI_COMPOSE_FILE" 2>/dev/null || true

        rm -rf "$DOCKER_3XUI_DIR/db"
        rm -rf "$DOCKER_3XUI_DIR/cert"

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/db.tar.gz" >/dev/null 2>&1 || true

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/cert.tar.gz" >/dev/null 2>&1 || true

        docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d >/dev/null 2>&1 || true

        echo
        echo "Safety backup retained at:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    PANEL_PORT="$DOCKER_3XUI_PANEL_PORT"
    SUBSCRIPTION_PORT=""

    if docker_3xui_load_compat_state; then
        SUBSCRIPTION_PORT="${SUBSCRIPTION_PORT:-}"
    fi

    SUBSCRIPTION_PORT="${SUBSCRIPTION_PORT:-2096}"

    TEMP_SETTINGS_FILE=$(mktemp)

    if docker exec "$DOCKER_3XUI_CONTAINER" sh -c \
        'command -v x-ui >/dev/null 2>&1 && x-ui settings' \
        >"$TEMP_SETTINGS_FILE" 2>/dev/null; then

        DETECTED_PANEL_PORT=$(sed -n 's/^port:[[:space:]]*//p' \
            "$TEMP_SETTINGS_FILE" | head -n 1)

        if [ -n "$DETECTED_PANEL_PORT" ]; then
            PANEL_PORT="$DETECTED_PANEL_PORT"
        fi

        DETECTED_SUB_PORT=$(grep -i 'sub.*port' \
            "$TEMP_SETTINGS_FILE" | \
            sed -n 's/.*:[[:space:]]*//p' | head -n 1)

        if [ -n "$DETECTED_SUB_PORT" ]; then
            SUBSCRIPTION_PORT="$DETECTED_SUB_PORT"
        fi
    fi

    rm -f "$TEMP_SETTINGS_FILE"

    echo
    echo "Checking restored panel port..."

    if ! docker_3xui_port_is_in_use "$PANEL_PORT"; then
        echo "ERROR: Restored panel port $PANEL_PORT is not listening."
        echo "Attempting automatic rollback..."

        docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null 2>&1 || true

        cp -f "$SAFETY_BACKUP_DIR/docker-compose.yml" \
            "$DOCKER_3XUI_COMPOSE_FILE" 2>/dev/null || true

        rm -rf "$DOCKER_3XUI_DIR/db"
        rm -rf "$DOCKER_3XUI_DIR/cert"

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/db.tar.gz" >/dev/null 2>&1 || true

        tar -C "$DOCKER_3XUI_DIR" \
            -xzf "$SAFETY_BACKUP_DIR/cert.tar.gz" >/dev/null 2>&1 || true

        docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" up -d >/dev/null 2>&1 || true

        echo
        echo "Safety backup retained at:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "======================================"
    echo "         3x-UI Restore OK"
    echo "======================================"
    echo
    echo "Backup Restored : $SELECTED_BACKUP"
    echo "Container       : $DOCKER_3XUI_CONTAINER"
    echo "Status          : Running"
    echo "Panel Port      : $PANEL_PORT"
    echo "Subscription    : $SUBSCRIPTION_PORT"
    echo
    echo "Database restored successfully."
    echo "Certificates restored successfully."
    echo "Docker Compose restored successfully."
    echo
    echo "Pre-restore safety backup retained at:"
    echo "$SAFETY_BACKUP_DIR"
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_uninstall() {
    clear

    echo "======================================"
    echo "          Uninstall 3x-UI"
    echo "======================================"
    echo

    if [ "$EUID" -ne 0 ]; then
        echo "Error: Root privileges are required."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_is_installed; then
        echo "3x-UI container is not installed."
        echo
        if [ -d "$DOCKER_3XUI_DIR" ]; then
            echo "Data directory still exists:"
            echo "$DOCKER_3XUI_DIR"
            echo
            echo "No changes were made."
        fi
        echo
        read -rp "Press Enter to return..."
        return
    fi

    IMAGE_NAME=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.Config.Image}}' 2>/dev/null || true)

    CONTAINER_STATUS=$(docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format '{{.State.Status}}' 2>/dev/null || true)

    echo "Container : $DOCKER_3XUI_CONTAINER"
    echo "Image     : ${IMAGE_NAME:-Unknown}"
    echo "Status    : ${CONTAINER_STATUS:-Unknown}"
    echo "Data Dir  : $DOCKER_3XUI_DIR"
    echo

    echo "What should be removed?"
    echo
    echo "1) Remove 3x-UI container + Compose file"
    echo "   Keep database, certificates, and backups"
    echo
    echo "2) Complete uninstall"
    echo "   Remove container + Compose file + 3x-UI data"
    echo "   A final safety backup will be kept outside /opt/3x-ui"
    echo
    echo "0) Cancel"
    echo

    read -rp "Please enter your selection [0-2]: " UNINSTALL_CHOICE

    case "$UNINSTALL_CHOICE" in
        1|2)
            ;;
        0|*)
            echo
            echo "Uninstall cancelled."
            sleep 1
            return
            ;;
    esac

    echo
    echo "Safety policy:"
    echo "A final backup of the current 3x-UI data will be created before removal."
    echo "Docker itself will NOT be removed."
    echo "Other containers, images, volumes, networks, and U-OPTI will NOT be removed."
    echo

    read -rp "Type UNINSTALL to continue: " CONFIRM

    if [ "$CONFIRM" != "UNINSTALL" ]; then
        echo
        echo "Uninstall cancelled."
        sleep 1
        return
    fi

    TIMESTAMP=$(date '+%Y%m%d-%H%M%S-%N')
    SAFETY_ROOT="/root/u-opti-backups/3x-ui"
    SAFETY_BACKUP_DIR="$SAFETY_ROOT/$TIMESTAMP-pre-uninstall"

    echo
    echo "Creating final safety backup..."
    echo "Backup Directory:"
    echo "$SAFETY_BACKUP_DIR"
    echo

    if ! mkdir -p "$SAFETY_BACKUP_DIR"; then
        echo "ERROR: Failed to create safety backup directory."
        echo "Nothing was removed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    BACKUP_FAILED=false

    if [ -f "$DOCKER_3XUI_COMPOSE_FILE" ]; then
        if ! cp -f "$DOCKER_3XUI_COMPOSE_FILE" \
            "$SAFETY_BACKUP_DIR/docker-compose.yml"; then
            echo "ERROR: Failed to back up Docker Compose file."
            BACKUP_FAILED=true
        fi
    else
        echo "WARNING: Docker Compose file was not found."
    fi

    if [ -d "$DOCKER_3XUI_DIR/db" ]; then
        if ! tar -C "$DOCKER_3XUI_DIR" \
            -czf "$SAFETY_BACKUP_DIR/db.tar.gz" \
            db; then
            echo "ERROR: Failed to back up 3x-UI database."
            BACKUP_FAILED=true
        fi
    else
        echo "WARNING: Database directory was not found."
        BACKUP_FAILED=true
    fi

    if [ -d "$DOCKER_3XUI_DIR/cert" ]; then
        if ! tar -C "$DOCKER_3XUI_DIR" \
            -czf "$SAFETY_BACKUP_DIR/cert.tar.gz" \
            cert; then
            echo "ERROR: Failed to back up 3x-UI certificate directory."
            BACKUP_FAILED=true
        fi
    else
        echo "WARNING: Certificate directory was not found."
        BACKUP_FAILED=true
    fi

    cat > "$SAFETY_BACKUP_DIR/backup-info.txt" <<EOF
3x-UI Container: $DOCKER_3XUI_CONTAINER
Image: $IMAGE_NAME
Container Status: $CONTAINER_STATUS
Backup Time: $(date --iso-8601=seconds)
Compose File: $DOCKER_3XUI_COMPOSE_FILE
Data Directory: $DOCKER_3XUI_DIR/db
Certificate Directory: $DOCKER_3XUI_DIR/cert
Uninstall Choice: $UNINSTALL_CHOICE
EOF

    chmod 700 "$SAFETY_BACKUP_DIR"
    find "$SAFETY_BACKUP_DIR" -type f -exec chmod 600 {} \;

    if [ "$BACKUP_FAILED" = "true" ]; then
        echo
        echo "ERROR: Final safety backup failed."
        echo "Nothing was removed."
        echo "Incomplete backup retained at:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Validating final safety backup..."

    BACKUP_OK=true

    for FILE in \
        "$SAFETY_BACKUP_DIR/docker-compose.yml" \
        "$SAFETY_BACKUP_DIR/db.tar.gz" \
        "$SAFETY_BACKUP_DIR/cert.tar.gz" \
        "$SAFETY_BACKUP_DIR/backup-info.txt"; do

        if [ ! -s "$FILE" ]; then
            echo "Missing or empty safety backup file:"
            echo "$FILE"
            BACKUP_OK=false
        fi
    done

    if [ "$BACKUP_OK" = "true" ]; then
        if ! tar -tzf "$SAFETY_BACKUP_DIR/db.tar.gz" >/dev/null 2>&1; then
            echo "Invalid database archive:"
            echo "$SAFETY_BACKUP_DIR/db.tar.gz"
            BACKUP_OK=false
        fi

        if ! tar -tzf "$SAFETY_BACKUP_DIR/cert.tar.gz" >/dev/null 2>&1; then
            echo "Invalid certificate archive:"
            echo "$SAFETY_BACKUP_DIR/cert.tar.gz"
            BACKUP_OK=false
        fi

        if ! grep -q '^services:' "$SAFETY_BACKUP_DIR/docker-compose.yml"; then
            echo "Invalid Docker Compose file:"
            echo "$SAFETY_BACKUP_DIR/docker-compose.yml"
            BACKUP_OK=false
        fi
    fi

    if [ "$BACKUP_OK" != "true" ]; then
        echo
        echo "ERROR: Safety backup validation failed."
        echo "Nothing was removed."
        echo "Backup retained at:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Safety backup validated successfully."
    echo
    echo "Stopping 3x-UI container..."

    if docker_3xui_is_running; then
        if ! docker stop "$DOCKER_3XUI_CONTAINER" >/dev/null; then
            echo "ERROR: Failed to stop 3x-UI container."
            echo "Nothing else was removed."
            echo "Safety backup retained at:"
            echo "$SAFETY_BACKUP_DIR"
            echo
            read -rp "Press Enter to return..."
            return
        fi
    fi

    echo "Removing 3x-UI container..."

    if ! docker rm "$DOCKER_3XUI_CONTAINER" >/dev/null; then
        echo "ERROR: Failed to remove 3x-UI container."
        echo "The container may still exist."
        echo "Safety backup retained at:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ -f "$DOCKER_3XUI_COMPOSE_FILE" ]; then
        echo "Removing Docker Compose file..."
        rm -f "$DOCKER_3XUI_COMPOSE_FILE"
    fi

    echo "Removing 3x-UI Docker image tag..."

    if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
        if docker image rm "$IMAGE_NAME" >/dev/null 2>&1; then
            IMAGE_REMOVED=true
        else
            IMAGE_REMOVED=false
            echo "WARNING: The image tag could not be removed."
            echo "It may still be referenced by another Docker resource."
        fi
    else
        IMAGE_REMOVED=true
    fi

    if [ "$UNINSTALL_CHOICE" = "2" ]; then
        echo "Removing 3x-UI data directory..."
        rm -rf "$DOCKER_3XUI_DIR"
    fi

    echo
    echo "Verifying uninstall..."

    if docker_3xui_is_installed; then
        echo "ERROR: 3x-UI container still exists."
        echo "Safety backup retained at:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ -f "$DOCKER_3XUI_COMPOSE_FILE" ]; then
        echo "ERROR: Docker Compose file still exists:"
        echo "$DOCKER_3XUI_COMPOSE_FILE"
        echo "Safety backup retained at:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if [ "$UNINSTALL_CHOICE" = "2" ] && [ -e "$DOCKER_3XUI_DIR" ]; then
        echo "ERROR: 3x-UI data directory still exists:"
        echo "$DOCKER_3XUI_DIR"
        echo "Safety backup retained at:"
        echo "$SAFETY_BACKUP_DIR"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "======================================"
    echo "       3x-UI Uninstall OK"
    echo "======================================"
    echo
    echo "Container removed   : Yes"
    echo "Compose file removed: Yes"
    echo "Image tag removed   : $([ "$IMAGE_REMOVED" = "true" ] && echo "Yes" || echo "No")"

    if [ "$UNINSTALL_CHOICE" = "1" ]; then
        echo "Data removed       : No"
        echo "Data retained at   : $DOCKER_3XUI_DIR"
    else
        echo "Data removed       : Yes"
    fi

    echo "Docker removed     : No"
    echo "U-OPTI removed     : No"
    echo
    echo "Final safety backup:"
    echo "$SAFETY_BACKUP_DIR"
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_status() {
    clear

    echo "======================================"
    echo "       3x-UI Instance Status"
    echo "======================================"
    echo

    if ! command -v docker >/dev/null 2>&1; then
        echo "Docker : Not Installed"
        echo
        echo "3x-UI Docker cannot be checked because Docker is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_load_instance >/dev/null 2>&1; then
        echo "ERROR: 3x-UI Instance module could not be loaded."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    mapfile -t INSTANCE_IDS < <(docker_3xui_instance_registered_ids 2>/dev/null || true)

    if [ "${#INSTANCE_IDS[@]}" -eq 0 ]; then
        echo "No registered Docker 3x-UI Instances were found."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    for INSTANCE_ID in "${INSTANCE_IDS[@]}"; do
        echo "--------------------------------------"

        if ! docker_3xui_instance_apply_runtime_context "$INSTANCE_ID" >/dev/null 2>&1; then
            echo "Instance $INSTANCE_ID"
            echo "  State       : ERROR"
            echo "  Reason      : Failed to load Instance state."
            echo
            continue
        fi

        local_container="$DOCKER_3XUI_INSTANCE_CONTAINER"
        domain="$DOCKER_3XUI_INSTANCE_DOMAIN"
        panel_port="$DOCKER_3XUI_INSTANCE_PANEL_PORT"
        api_port="$DOCKER_3XUI_INSTANCE_API_PORT"
        sub_port="$DOCKER_3XUI_INSTANCE_SUB_PORT"
        metrics_port="$DOCKER_3XUI_INSTANCE_METRICS_PORT"
        data_dir="$DOCKER_3XUI_INSTANCE_DIR"
        web_base_path="/"

        if [ -f "$DOCKER_3XUI_INSTANCE_COMPAT_ENV" ]; then
            # shellcheck disable=SC1090
            source "$DOCKER_3XUI_INSTANCE_COMPAT_ENV" 2>/dev/null || true
            web_base_path="${WEB_BASE_PATH:-/}"
        fi

        echo "Instance       : $INSTANCE_ID"
        echo "Domain         : ${domain:-Unknown}"
        echo "Container      : ${local_container:-Unknown}"
        echo "Panel Port     : ${panel_port:-Unknown}"
        echo "API Port       : ${api_port:-Unknown}"
        echo "Subscription   : ${sub_port:-Unknown}"
        echo "Metrics        : ${metrics_port:-Unknown}"
        echo "Web Base Path  : $web_base_path"

        if ! docker ps -a --format '{{.Names}}' 2>/dev/null |
            grep -Fxq "$local_container"; then
            echo "Container      : Not Installed"
            echo "Xray           : Unknown"
            echo
            continue
        fi

        container_status="$(
            docker inspect "$local_container" \
                --format '{{.State.Status}}' 2>/dev/null || true
        )"

        case "$container_status" in
            running) echo "Container      : Running" ;;
            *)       echo "Container      : ${container_status:-Unknown}" ;;
        esac

        if [ "$container_status" = "running" ]; then
            if docker_3xui_instance_port_listening "$panel_port" 2>/dev/null; then
                echo "Panel          : Listening on $panel_port"
            else
                echo "Panel          : NOT listening on $panel_port"
            fi

            if docker_3xui_instance_port_listening "$sub_port" 2>/dev/null; then
                echo "Subscription   : Listening on $sub_port"
            else
                echo "Subscription   : NOT listening on $sub_port"
            fi

            if [ -n "$metrics_port" ]; then
                if docker_3xui_instance_port_listening "$metrics_port" 2>/dev/null; then
                    echo "Metrics        : Listening on $metrics_port"
                else
                    echo "Metrics        : NOT listening on $metrics_port"
                fi
            fi

            xray_state="$(
                docker exec "$local_container" sh -c \
                    'command -v x-ui >/dev/null 2>&1 && x-ui status' \
                    2>/dev/null |
                    sed -n 's/^Xray State:[[:space:]]*//Ip' |
                    head -n 1
            )"

            if [ -n "$xray_state" ]; then
                echo "Xray           : $xray_state"
            else
                echo "Xray           : Not detected"
            fi
        else
            echo "Service        : Container is stopped."
        fi

        echo "Data Directory : $data_dir"
        echo
    done

    echo "======================================"
    echo
    read -rp "Press Enter to return..."
}

docker_3xui_sanaei_management() {

    clear

    echo "======================================"
    echo "       Sanaei 3x-UI Management"
    echo "======================================"
    echo

    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_is_installed; then
        echo "Error: 3x-UI container is not installed."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! docker_3xui_is_running; then
        echo "Error: 3x-UI container is not running."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Opening Sanaei 3x-UI management menu..."
    echo
    docker exec -it "$DOCKER_3XUI_CONTAINER" x-ui
}

show_docker_3xui_menu() {
    while true; do
        clear

        echo "======================================"
        echo "       3x-UI Docker Management"
        echo "======================================"
        echo
        echo "1) Install 3x-UI in Docker"
        echo "2) Start 3x-UI"
        echo "3) Stop 3x-UI"
        echo "4) Restart 3x-UI"
        echo "5) Update 3x-UI"
        echo "6) Backup 3x-UI"
        echo "7) Restore 3x-UI"
        echo "8) Uninstall 3x-UI"
        echo "9) Show Status"
        echo "10) Sanaei 3x-UI Management"
        echo "11) Nginx / SSL Configuration"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-9]: " DOCKER_3XUI_CHOICE

        case "$DOCKER_3XUI_CHOICE" in
            1) docker_3xui_install ;;
            2) docker_3xui_start ;;
            3) docker_3xui_stop ;;
            4) docker_3xui_restart ;;
            5) docker_3xui_update ;;
            6) docker_3xui_backup ;;
            7) docker_3xui_restore ;;
            8) docker_3xui_uninstall ;;
            9) docker_3xui_status ;;
            10) docker_3xui_sanaei_management ;;
            11)
                if docker_3xui_load_nginx; then
                    docker_3xui_nginx_setup
                else
                    echo
                    read -rp "Press Enter to return..."
                fi
                ;;
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
