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
    SUBSCRIPTION_PORT="2096"
    WEB_BASE_PATH="/"

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

    if ! docker_3xui_is_installed; then
        echo "3x-UI Container: Not Installed"
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if docker_3xui_is_running; then
        CONTAINER_STATUS="Running"
    else
        CONTAINER_STATUS="Stopped"
    fi

    echo "Container       : $CONTAINER_STATUS"

    docker inspect "$DOCKER_3XUI_CONTAINER" \
        --format 'Image           : {{.Config.Image}}
Network         : {{.HostConfig.NetworkMode}}
Restart Policy  : {{.HostConfig.RestartPolicy.Name}}
Started At      : {{.State.StartedAt}}
Finished At     : {{.State.FinishedAt}}' 2>/dev/null || true

    echo

    if docker_3xui_is_running; then
        echo "Service Status:"
        echo

        PANEL_PORT="$DOCKER_3XUI_PANEL_PORT"
        SUBSCRIPTION_PORT="2096"

        if docker exec "$DOCKER_3XUI_CONTAINER" sh -c \
            'command -v x-ui >/dev/null 2>&1 && x-ui settings' \
            >/tmp/u-opti-3xui-settings.txt 2>/dev/null; then

            if grep -q '^port:' /tmp/u-opti-3xui-settings.txt; then
                PANEL_PORT=$(sed -n 's/^port:[[:space:]]*//p' /tmp/u-opti-3xui-settings.txt | head -n 1)
            fi

            if grep -qi 'sub.*port' /tmp/u-opti-3xui-settings.txt; then
                SUBSCRIPTION_PORT=$(grep -i 'sub.*port' /tmp/u-opti-3xui-settings.txt | \
                    sed -n 's/.*:[[:space:]]*//p' | head -n 1)
            fi
        fi

        rm -f /tmp/u-opti-3xui-settings.txt

        if docker_3xui_port_is_in_use "$PANEL_PORT"; then
            echo "Panel           : Running on $PANEL_PORT"
        else
            echo "Panel           : Not listening on $PANEL_PORT"
        fi

        if docker_3xui_port_is_in_use "$SUBSCRIPTION_PORT"; then
            echo "Subscription    : Listening on $SUBSCRIPTION_PORT"
        else
            echo "Subscription    : Not listening on $SUBSCRIPTION_PORT"
        fi

        if docker exec "$DOCKER_3XUI_CONTAINER" sh -c \
            'command -v x-ui >/dev/null 2>&1 && x-ui settings' \
            >/tmp/u-opti-3xui-settings.txt 2>/dev/null; then

            WEB_BASE_PATH=$(sed -n 's/^webBasePath:[[:space:]]*//p' /tmp/u-opti-3xui-settings.txt | head -n 1)

            DATABASE_LINE=$(grep -E '^Database:' /tmp/u-opti-3xui-settings.txt | head -n 1)

            if [ -n "$WEB_BASE_PATH" ]; then
                echo "Web Base Path   : $WEB_BASE_PATH"
            fi

            if [ -n "$DATABASE_LINE" ]; then
                echo "$DATABASE_LINE"
            fi
        fi

        rm -f /tmp/u-opti-3xui-settings.txt

        if docker exec "$DOCKER_3XUI_CONTAINER" sh -c \
            'command -v x-ui >/dev/null 2>&1 && x-ui status' \
            >/tmp/u-opti-3xui-state.txt 2>/dev/null; then

            XRAY_STATE=$(grep -i '^xray state:' /tmp/u-opti-3xui-state.txt | \
                sed 's/^[^:]*:[[:space:]]*//' | head -n 1)

            if [ -n "$XRAY_STATE" ]; then
                echo "Xray            : $XRAY_STATE"
            fi
        fi

        rm -f /tmp/u-opti-3xui-state.txt
    else
        echo "Service Status  : Container is stopped."
    fi

    echo
    echo "Data Directory  : $DOCKER_3XUI_DIR/db"
    echo "Certificate Dir : $DOCKER_3XUI_DIR/cert"
    echo "Compose File    : $DOCKER_3XUI_COMPOSE_FILE"

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
