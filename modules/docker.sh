#!/bin/bash

# U-OPTI - Docker Management
# v0.13.0

DOCKER_APT_SOURCE="/etc/apt/sources.list.d/docker.sources"
DOCKER_GPG_KEY="/etc/apt/keyrings/docker.asc"

docker_is_installed() { command -v docker >/dev/null 2>&1; }
docker_service_is_active() { systemctl is-active --quiet docker 2>/dev/null; }
docker_compose_is_installed() { docker compose version >/dev/null 2>&1; }

docker_show_status() {
    clear
    echo "======================================"
    echo "           Docker Status"
    echo "======================================"
    echo
    if docker_is_installed; then
        echo "Docker        : Installed"
        echo "Docker Version: $(docker --version 2>/dev/null | sed 's/^Docker version //')"
    else
        echo "Docker        : Not Installed"
    fi
    if docker_service_is_active; then echo "Docker Service: Active"; else echo "Docker Service: Inactive"; fi
    if docker_compose_is_installed; then
        echo "Docker Compose: Installed"
        echo "Compose Version: $(docker compose version 2>/dev/null | sed 's/^Docker Compose version //')"
    else
        echo "Docker Compose: Not Installed"
    fi
    echo
    read -rp "Press Enter to return..."
}

docker_install() {
    clear
    echo "======================================"
    echo "            Install Docker"
    echo "======================================"
    echo
    if [ "$EUID" -ne 0 ]; then echo "Error: Root privileges are required."; read -rp "Press Enter to return..."; return; fi
    if [ ! -f /etc/os-release ]; then echo "Error: Unable to detect operating system."; read -rp "Press Enter to return..."; return; fi
    . /etc/os-release
    if [ "${ID:-}" != "ubuntu" ]; then
        echo "Error: This installer currently supports Ubuntu only."
        echo "Detected OS: ${PRETTY_NAME:-Unknown}"
        read -rp "Press Enter to return..."; return
    fi
    case "${VERSION_ID:-}" in 22.04|24.04|26.04) ;; *) echo "Error: Unsupported Ubuntu version: ${VERSION_ID:-Unknown}"; read -rp "Press Enter to return..."; return ;; esac
    ARCH=$(dpkg --print-architecture 2>/dev/null) || { echo "Error: Unable to detect architecture."; read -rp "Press Enter to return..."; return; }
    case "$ARCH" in amd64|arm64|armhf|s390x|ppc64el) ;; *) echo "Error: Unsupported architecture: $ARCH"; read -rp "Press Enter to return..."; return ;; esac
    echo "Operating System: $PRETTY_NAME"
    echo "Architecture    : $ARCH"
    echo
    if docker_is_installed && docker_service_is_active && docker_compose_is_installed; then
        echo "Docker is already installed and working."
        read -rp "Press Enter to return..."; return
    fi

    CONFLICTING_PACKAGES=(docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc)
    INSTALLED_CONFLICTS=()
    for PACKAGE in "${CONFLICTING_PACKAGES[@]}"; do
        dpkg-query -W -f='${Status}' "$PACKAGE" 2>/dev/null | grep -q "install ok installed" && INSTALLED_CONFLICTS+=("$PACKAGE")
    done
    if [ "${#INSTALLED_CONFLICTS[@]}" -gt 0 ]; then
        echo "Conflicting packages found:"
        printf ' - %s
' "${INSTALLED_CONFLICTS[@]}"
        echo
        read -rp "Remove these packages and continue? [y/N]: " CONFIRM
        case "$CONFIRM" in y|Y|yes|YES) apt remove -y "${INSTALLED_CONFLICTS[@]}" || { echo "Error: Failed to remove conflicting packages."; read -rp "Press Enter to return..."; return; } ;; *) echo "Installation cancelled."; read -rp "Press Enter to return..."; return ;; esac
    fi

    echo
    echo "Installing prerequisites..."
    apt update || { echo "Error: apt update failed."; read -rp "Press Enter to return..."; return; }
    apt install -y ca-certificates curl || { echo "Error: Failed to install prerequisites."; read -rp "Press Enter to return..."; return; }

    echo
    echo "Configuring Docker official repository..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$DOCKER_GPG_KEY" || { echo "Error: Failed to download Docker GPG key."; read -rp "Press Enter to return..."; return; }
    chmod a+r "$DOCKER_GPG_KEY"
    UBUNTU_CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
    [ -n "$UBUNTU_CODENAME" ] || { echo "Error: Unable to determine Ubuntu codename."; read -rp "Press Enter to return..."; return; }
    cat > "$DOCKER_APT_SOURCE" <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $UBUNTU_CODENAME
Components: stable
Architectures: $ARCH
Signed-By: $DOCKER_GPG_KEY
EOF
    apt update || { echo "Error: Docker repository could not be used."; read -rp "Press Enter to return..."; return; }

    echo
    echo "Installing Docker Engine and plugins..."
    apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin || { echo "Error: Docker installation failed."; read -rp "Press Enter to return..."; return; }
    systemctl enable docker >/dev/null 2>&1
    systemctl start docker || { echo "Error: Docker service failed to start."; read -rp "Press Enter to return..."; return; }

    echo
    echo "Verifying installation..."
    docker_is_installed && docker_service_is_active && docker_compose_is_installed || { echo "Error: Docker installation verification failed."; read -rp "Press Enter to return..."; return; }

    echo "Running Docker hello-world test..."
    docker run --rm hello-world >/tmp/u-opti-docker-hello-world.log 2>&1 || {
        echo "Error: Docker test container failed."
        cat /tmp/u-opti-docker-hello-world.log
        rm -f /tmp/u-opti-docker-hello-world.log
        read -rp "Press Enter to return..."
        return
    }
    rm -f /tmp/u-opti-docker-hello-world.log
    echo
    echo "======================================"
    echo "        Docker Installation OK"
    echo "======================================"
    echo
    echo "Docker Engine : $(docker --version 2>/dev/null | sed 's/^Docker version //')"
    echo "Docker Compose: $(docker compose version 2>/dev/null | sed 's/^Docker Compose version //')"
    echo "Docker Service: Active"
    echo "Docker Test   : Passed"
    echo
    echo "Note: No UFW ports were opened automatically."
    echo
    read -rp "Press Enter to return..."
}

docker_compose_menu() {
    clear
    echo "======================================"
    echo "          Docker Compose"
    echo "======================================"
    echo
    docker_compose_is_installed && docker compose version || echo "Docker Compose plugin is not installed."
    echo
    read -rp "Press Enter to return..."
}

docker_management_menu() {
    while true; do
        clear
        echo "======================================"
        echo "        Docker Management"
        echo "======================================"
        echo
        echo "1) Install Docker"
        echo "2) Docker Status"
        echo "3) Docker Compose"
        echo "4) 3x-UI Docker Management"
        echo "5) Container Management"
        echo "6) Image Management"
        echo "7) Volume Management"
        echo "8) Network Management"
        echo "9) Docker Cleanup"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-9]: " DOCKER_CHOICE
        case "$DOCKER_CHOICE" in
            1) docker_install ;;
            2) docker_show_status ;;
            3) docker_compose_menu ;;
            4)
                if declare -F show_docker_3xui_menu >/dev/null 2>&1; then
                    show_docker_3xui_menu
                else
                    clear
                    echo "3x-UI Docker Management is not implemented yet."
                    echo
                    read -rp "Press Enter to return..."
                fi
                ;;
            5|6|7|8|9)
                clear
                echo "This Docker management function is planned for v0.13.0."
                echo
                read -rp "Press Enter to return..."
                ;;
            0) break ;;
            *) echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
