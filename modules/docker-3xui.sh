#!/bin/bash

# U-OPTI - 3x-UI Docker Management
# v0.13.0

DOCKER_3XUI_IMAGE="ghcr.io/mhsanaei/3x-ui:latest"
DOCKER_3XUI_CONTAINER="3xui"
DOCKER_3XUI_DIR="/opt/3x-ui"
DOCKER_3XUI_COMPOSE_FILE="$DOCKER_3XUI_DIR/docker-compose.yml"
DOCKER_3XUI_PANEL_PORT="2053"

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

    if docker_3xui_is_installed; then
        echo "3x-UI Docker is already installed."
        echo
        echo "Container: $DOCKER_3XUI_CONTAINER"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Checking panel port $DOCKER_3XUI_PANEL_PORT/tcp..."

    if docker_3xui_port_is_in_use "$DOCKER_3XUI_PANEL_PORT"; then
        echo
        echo "ERROR: Port $DOCKER_3XUI_PANEL_PORT/tcp is already in use."
        echo
        echo "3x-UI uses Host Network, so this port must be available."
        echo
        echo "Current listener:"
        ss -lntp 2>/dev/null | grep ":$DOCKER_3XUI_PANEL_PORT " || true
        echo
        echo "Installation cancelled."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo "Port $DOCKER_3XUI_PANEL_PORT/tcp is available."
    echo

    if [ -e "$DOCKER_3XUI_DIR" ]; then
        if [ -n "$(find "$DOCKER_3XUI_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
            echo "Directory already exists and contains data:"
            echo "$DOCKER_3XUI_DIR"
            echo
            echo "U-OPTI will not overwrite existing data."
            echo "Installation cancelled."
            echo
            read -rp "Press Enter to return..."
            return
        fi
    fi

    echo "3x-UI installation plan:"
    echo
    echo "Image       : $DOCKER_3XUI_IMAGE"
    echo "Container   : $DOCKER_3XUI_CONTAINER"
    echo "Network     : host"
    echo "Panel Port  : $DOCKER_3XUI_PANEL_PORT"
    echo "Data Dir    : $DOCKER_3XUI_DIR"
    echo "Database    : $DOCKER_3XUI_DIR/db"
    echo "Certificates: $DOCKER_3XUI_DIR/cert"
    echo

    read -rp "Continue with installation? [y/N]: " CONFIRM

    case "$CONFIRM" in
        y|Y|yes|YES)
            ;;
        *)
            echo
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
    echo "Checking panel port..."

    if ! docker_3xui_port_is_in_use "$DOCKER_3XUI_PANEL_PORT"; then
        echo
        echo "WARNING: 3x-UI container is running, but panel port"
        echo "$DOCKER_3XUI_PANEL_PORT is not listening yet."
        echo
        echo "The container may still be initializing."
        echo
        echo "Container status:"
        docker inspect "$DOCKER_3XUI_CONTAINER" \
            --format 'Status: {{.State.Status}}
Started: {{.State.StartedAt}}' 2>/dev/null || true
        echo
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "======================================"
    echo "      3x-UI Installation OK"
    echo "======================================"
    echo
    echo "Container    : $DOCKER_3XUI_CONTAINER"
    echo "Status       : Running"
    echo "Image        : $DOCKER_3XUI_IMAGE"
    echo "Network      : host"
    echo "Panel Port   : $DOCKER_3XUI_PANEL_PORT"
    echo "Data Dir     : $DOCKER_3XUI_DIR/db"
    echo "Cert Dir     : $DOCKER_3XUI_DIR/cert"
    echo
    echo "Panel URL:"
    echo "http://<SERVER-IP>:$DOCKER_3XUI_PANEL_PORT"
    echo
    echo "Important:"
    echo "Log in to the panel and immediately change"
    echo "the default/generated administrator credentials."
    echo
    echo "Docker Compose:"
    echo "$DOCKER_3XUI_COMPOSE_FILE"
    echo

    read -rp "Press Enter to return..."
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

    echo "Update 3x-UI is not implemented yet."
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_backup() {
    clear

    echo "======================================"
    echo "           Backup 3x-UI"
    echo "======================================"
    echo

    echo "Backup 3x-UI is not implemented yet."
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_restore() {
    clear

    echo "======================================"
    echo "          Restore 3x-UI"
    echo "======================================"
    echo

    echo "Restore 3x-UI is not implemented yet."
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_uninstall() {
    clear

    echo "======================================"
    echo "          Uninstall 3x-UI"
    echo "======================================"
    echo

    echo "Uninstall 3x-UI is not implemented yet."
    echo

    read -rp "Press Enter to return..."
}

docker_3xui_status() {
    clear

    echo "======================================"
    echo "            3x-UI Status"
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

    if docker_3xui_is_running; then
        echo "3x-UI Container: Running"
    elif docker_3xui_is_installed; then
        echo "3x-UI Container: Stopped"
    else
        echo "3x-UI Container: Not Installed"
    fi

    if docker_3xui_is_installed; then
        echo
        docker inspect "$DOCKER_3XUI_CONTAINER" \
            --format 'Image : {{.Config.Image}}
Network: {{.HostConfig.NetworkMode}}
Status : {{.State.Status}}' 2>/dev/null || true
    fi

    echo
    read -rp "Press Enter to return..."
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
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
