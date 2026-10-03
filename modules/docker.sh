#!/bin/bash

# U-OPTI - Docker Management

DOCKER_APT_SOURCE="/etc/apt/sources.list.d/docker.sources"
DOCKER_GPG_KEY="/etc/apt/keyrings/docker.asc"

# Load dedicated Docker-related modules when available.
DOCKER_MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_3XUI_MODULE="$DOCKER_MODULE_DIR/docker-3xui.sh"
DOCKER_SMITE_MODULE="$DOCKER_MODULE_DIR/smite.sh"
DOCKER_SMITE_INSTALL_MODULE="$DOCKER_MODULE_DIR/smite-install.sh"
DOCKER_SMITE_GATEWAY_MODULE="$DOCKER_MODULE_DIR/smite-gateway.sh"
DOCKER_SMITE_FOREIGN_GATEWAY_MODULE="$DOCKER_MODULE_DIR/smite-foreign-gateway.sh"
DOCKER_SMITE_DIGEST_MODULE="$DOCKER_MODULE_DIR/smite-digest-migrate.sh"

if [ -f "$DOCKER_3XUI_MODULE" ]; then
    source "$DOCKER_3XUI_MODULE"
fi

if [ -f "$DOCKER_SMITE_MODULE" ]; then
    source "$DOCKER_SMITE_MODULE"
fi

if [ -f "$DOCKER_SMITE_INSTALL_MODULE" ]; then
    source "$DOCKER_SMITE_INSTALL_MODULE"
fi

if [ -f "$DOCKER_SMITE_GATEWAY_MODULE" ]; then
    source "$DOCKER_SMITE_GATEWAY_MODULE"
fi

if [ -f "$DOCKER_SMITE_FOREIGN_GATEWAY_MODULE" ]; then
    source "$DOCKER_SMITE_FOREIGN_GATEWAY_MODULE"
fi

if [ -f "$DOCKER_SMITE_DIGEST_MODULE" ] && bash -n "$DOCKER_SMITE_DIGEST_MODULE" >/dev/null 2>&1; then
    # shellcheck disable=SC1090
    source "$DOCKER_SMITE_DIGEST_MODULE"
fi

docker_is_installed() { command -v docker >/dev/null 2>&1; }
docker_service_is_active() { systemctl is-active --quiet docker 2>/dev/null; }
docker_compose_is_installed() { docker compose version >/dev/null 2>&1; }

docker_smite_ensure_digest_module() {
    local branch="${U_OPTI_BRANCH:-main}"
    local base_url="https://raw.githubusercontent.com/aghajani82/u-opti/$branch"
    local temp_file=""

    if declare -F smite_digest_migrate_existing >/dev/null 2>&1; then
        return 0
    fi

    if [ -f "$DOCKER_SMITE_DIGEST_MODULE" ] &&
       bash -n "$DOCKER_SMITE_DIGEST_MODULE" >/dev/null 2>&1; then
        # shellcheck disable=SC1090
        source "$DOCKER_SMITE_DIGEST_MODULE"
        if declare -F smite_digest_migrate_existing >/dev/null 2>&1; then
            return 0
        fi
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "ERROR: curl is required to prepare the Smite digest migration helper."
        return 1
    fi

    echo "Smite digest migration helper is missing."
    echo "Preparing the helper from the active U-OPTI branch..."

    temp_file="$(mktemp)" || return 1

    if ! curl -fsSL --retry 3 \
        "${base_url}/modules/smite-digest-migrate.sh?cb=$(date +%s%N)" \
        -o "$temp_file"; then
        echo "ERROR: Failed to download smite-digest-migrate.sh."
        rm -f "$temp_file"
        return 1
    fi

    if [ ! -s "$temp_file" ] ||
       ! bash -n "$temp_file" ||
       ! grep -q '^smite_digest_migrate_existing()' "$temp_file"; then
        echo "ERROR: Downloaded Smite digest migration helper failed validation."
        rm -f "$temp_file"
        return 1
    fi

    if ! install -m 0755 "$temp_file" "$DOCKER_SMITE_DIGEST_MODULE"; then
        echo "ERROR: Failed to install the Smite digest migration helper."
        rm -f "$temp_file"
        return 1
    fi

    rm -f "$temp_file"

    # shellcheck disable=SC1090
    source "$DOCKER_SMITE_DIGEST_MODULE"

    if ! declare -F smite_digest_migrate_existing >/dev/null 2>&1; then
        echo "ERROR: Smite digest migration helper did not load correctly."
        return 1
    fi

    echo "Smite digest migration helper is ready."
    return 0
}

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

    if docker_service_is_active; then
        echo "Docker Service: Active"
    else
        echo "Docker Service: Inactive"
    fi

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

    if [ "$EUID" -ne 0 ]; then
        echo "Error: Root privileges are required."
        read -rp "Press Enter to return..."
        return
    fi

    if [ ! -f /etc/os-release ]; then
        echo "Error: Unable to detect operating system."
        read -rp "Press Enter to return..."
        return
    fi

    . /etc/os-release

    if [ "${ID:-}" != "ubuntu" ]; then
        echo "Error: This installer currently supports Ubuntu only."
        echo "Detected OS: ${PRETTY_NAME:-Unknown}"
        read -rp "Press Enter to return..."
        return
    fi

    case "${VERSION_ID:-}" in
        22.04|24.04|26.04)
            ;;
        *)
            echo "Error: Unsupported Ubuntu version: ${VERSION_ID:-Unknown}"
            read -rp "Press Enter to return..."
            return
            ;;
    esac

    ARCH=$(dpkg --print-architecture 2>/dev/null) || {
        echo "Error: Unable to detect architecture."
        read -rp "Press Enter to return..."
        return
    }

    case "$ARCH" in
        amd64|arm64|armhf|s390x|ppc64el)
            ;;
        *)
            echo "Error: Unsupported architecture: $ARCH"
            read -rp "Press Enter to return..."
            return
            ;;
    esac

    echo "Operating System: $PRETTY_NAME"
    echo "Architecture    : $ARCH"
    echo

    if docker_is_installed && docker_service_is_active && docker_compose_is_installed; then
        echo "Docker is already installed and working."
        read -rp "Press Enter to return..."
        return
    fi

    CONFLICTING_PACKAGES=(
        docker.io
        docker-compose
        docker-compose-v2
        docker-doc
        docker-buildx
        podman-docker
        containerd
        runc
    )

    INSTALLED_CONFLICTS=()

    for PACKAGE in "${CONFLICTING_PACKAGES[@]}"; do
        dpkg-query -W -f='${Status}' "$PACKAGE" 2>/dev/null |
            grep -q "install ok installed" &&
            INSTALLED_CONFLICTS+=("$PACKAGE")
    done

    if [ "${#INSTALLED_CONFLICTS[@]}" -gt 0 ]; then
        echo "Conflicting packages found:"
        printf ' - %s\n' "${INSTALLED_CONFLICTS[@]}"
        echo

        read -rp "Remove these packages and continue? [y/N]: " CONFIRM

        case "$CONFIRM" in
            y|Y|yes|YES)
                apt remove -y "${INSTALLED_CONFLICTS[@]}" || {
                    echo "Error: Failed to remove conflicting packages."
                    read -rp "Press Enter to return..."
                    return
                }
                ;;
            *)
                echo "Installation cancelled."
                read -rp "Press Enter to return..."
                return
                ;;
        esac
    fi

    echo
    echo "Installing prerequisites..."

    apt update || {
        echo "Error: apt update failed."
        read -rp "Press Enter to return..."
        return
    }

    apt install -y ca-certificates curl || {
        echo "Error: Failed to install prerequisites."
        read -rp "Press Enter to return..."
        return
    }

    echo
    echo "Configuring Docker official repository..."

    install -m 0755 -d /etc/apt/keyrings

    curl -fsSL \
        https://download.docker.com/linux/ubuntu/gpg \
        -o "$DOCKER_GPG_KEY" || {
        echo "Error: Failed to download Docker GPG key."
        read -rp "Press Enter to return..."
        return
    }

    chmod a+r "$DOCKER_GPG_KEY"

    UBUNTU_CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"

    [ -n "$UBUNTU_CODENAME" ] || {
        echo "Error: Unable to determine Ubuntu codename."
        read -rp "Press Enter to return..."
        return
    }

    cat > "$DOCKER_APT_SOURCE" <<EOF_DOCKER_SOURCE
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $UBUNTU_CODENAME
Components: stable
Architectures: $ARCH
Signed-By: $DOCKER_GPG_KEY
EOF_DOCKER_SOURCE

    apt update || {
        echo "Error: Docker repository could not be used."
        read -rp "Press Enter to return..."
        return
    }

    echo
    echo "Installing Docker Engine and plugins..."

    apt install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin || {
        echo "Error: Docker installation failed."
        read -rp "Press Enter to return..."
        return
    }

    systemctl enable docker >/dev/null 2>&1

    systemctl start docker || {
        echo "Error: Docker service failed to start."
        read -rp "Press Enter to return..."
        return
    }

    echo
    echo "Verifying installation..."

    docker_is_installed &&
    docker_service_is_active &&
    docker_compose_is_installed || {
        echo "Error: Docker installation verification failed."
        read -rp "Press Enter to return..."
        return
    }

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

    docker_compose_is_installed &&
        docker compose version ||
        echo "Docker Compose plugin is not installed."

    echo
    read -rp "Press Enter to return..."
}

docker_smite_compatibility_menu() {
    while true; do
        clear
        echo "======================================"
        echo "     Smite Compatibility Tools"
        echo "======================================"
        echo
        echo "1) Persistent 443 Compatibility"
        echo "2) Image Digest Migration"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-2]: " SMITE_COMPAT_CHOICE

        case "$SMITE_COMPAT_CHOICE" in
            1)
                if declare -F show_smite_menu >/dev/null 2>&1; then
                    show_smite_menu
                else
                    echo "Smite compatibility module is not available."
                    read -rp "Press Enter to return..."
                fi
                ;;
            2)
                clear
                if docker_smite_ensure_digest_module; then
                    smite_digest_migrate_existing
                fi
                echo
                read -rp "Press Enter to return..."
                ;;
            0)
                break
                ;;
            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}

docker_smite_management_menu() {
    while true; do
        clear
        echo "======================================"
        echo "        Smite Management"
        echo "======================================"
        echo
        echo "1) Install / Lifecycle"
        echo "2) 443 Gateway"
        echo "3) Compatibility Tools"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-3]: " SMITE_MANAGEMENT_CHOICE
        case "$SMITE_MANAGEMENT_CHOICE" in
            1)
                if declare -F show_smite_install_menu >/dev/null 2>&1; then
                    show_smite_install_menu
                else
                    echo "Smite installer module is not available."
                    read -rp "Press Enter to return..."
                fi
                ;;
            2)
                if declare -F smite_foreign_gateway_role >/dev/null 2>&1 && \
                   [ "$(smite_foreign_gateway_role)" = "foreign" ]; then
                    if declare -F show_smite_foreign_gateway_menu >/dev/null 2>&1; then
                        show_smite_foreign_gateway_menu
                    else
                        echo "Smite Foreign gateway module is not available."
                        read -rp "Press Enter to return..."
                    fi
                elif declare -F show_smite_gateway_menu >/dev/null 2>&1; then
                    show_smite_gateway_menu
                else
                    echo "Smite gateway module is not available."
                    read -rp "Press Enter to return..."
                fi
                ;;
            3)
                docker_smite_compatibility_menu
                ;;
            0)
                break
                ;;
            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
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
        echo "5) Smite Management"
        echo "6) Container Management"
        echo "7) Image Management"
        echo "8) Volume Management"
        echo "9) Network Management"
        echo "10) Docker Cleanup"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-10]: " DOCKER_CHOICE

        case "$DOCKER_CHOICE" in
            1)
                docker_install
                ;;
            2)
                docker_show_status
                ;;
            3)
                docker_compose_menu
                ;;
            4)
                if declare -F show_docker_3xui_menu >/dev/null 2>&1; then
                    show_docker_3xui_menu
                else
                    clear
                    echo "3x-UI Docker Management is not available."
                    echo
                    read -rp "Press Enter to return..."
                fi
                ;;
            5)
                docker_smite_management_menu
                ;;
            6|7|8|9|10)
                clear
                echo "This Docker management function is not implemented yet."
                echo
                read -rp "Press Enter to return..."
                ;;
            0)
                break
                ;;
            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}
