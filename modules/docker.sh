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
DOCKER_SMITE_PRIVATE_NETWORK_MODULE="$DOCKER_MODULE_DIR/smite-private-network.sh"
DOCKER_SMITE_EASYTIER_MODULE="$DOCKER_MODULE_DIR/smite-easytier.sh"
DOCKER_SMITE_DIGEST_MODULE="$DOCKER_MODULE_DIR/smite-digest-migrate.sh"
DOCKER_SMITE_PRIVATE_NETWORK_ERROR=""

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

if [ -f "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE" ] && [ -f "$DOCKER_SMITE_EASYTIER_MODULE" ]; then
    if bash -n "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE" >/dev/null 2>&1 && \
       bash -n "$DOCKER_SMITE_EASYTIER_MODULE" >/dev/null 2>&1; then
        # shellcheck disable=SC1090
        source "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE"
    else
        DOCKER_SMITE_PRIVATE_NETWORK_ERROR="Smite EasyTier Private Network modules failed syntax validation."
    fi
elif [ -f "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE" ] || [ -f "$DOCKER_SMITE_EASYTIER_MODULE" ]; then
    DOCKER_SMITE_PRIVATE_NETWORK_ERROR="Smite EasyTier Private Network module pair is incomplete."
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
    local branch_url="https://raw.githubusercontent.com/aghajani82/u-opti/$branch/modules/smite-digest-migrate.sh"
    local installed_version="${VERSION:-}"
    local version_url=""
    local temp_file=""
    local local_helper_ok=false
    local downloaded=false

    if [ -z "$installed_version" ] && [ -f "/usr/local/lib/u-opti/VERSION" ]; then
        installed_version="$(tr -d '[:space:]' < /usr/local/lib/u-opti/VERSION)"
    fi

    if [ -f "$DOCKER_SMITE_DIGEST_MODULE" ] &&
       bash -n "$DOCKER_SMITE_DIGEST_MODULE" >/dev/null 2>&1 &&
       grep -q '^smite_digest_migrate_existing()' "$DOCKER_SMITE_DIGEST_MODULE"; then
        local_helper_ok=true
    fi

    if ! command -v curl >/dev/null 2>&1; then
        if [ "$local_helper_ok" = "true" ]; then
            # shellcheck disable=SC1090
            source "$DOCKER_SMITE_DIGEST_MODULE"
            return 0
        fi
        echo "ERROR: curl is required to prepare the Smite digest migration helper."
        return 1
    fi

    temp_file="$(mktemp)" || return 1

    if [[ "$installed_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        version_url="https://raw.githubusercontent.com/aghajani82/u-opti/v${installed_version}/modules/smite-digest-migrate.sh"
        if curl -fsSL --retry 2 \
            "${version_url}?cb=$(date +%s%N)" \
            -o "$temp_file"; then
            downloaded=true
        fi
    fi

    if [ "$downloaded" != "true" ]; then
        if curl -fsSL --retry 3 \
            "${branch_url}?cb=$(date +%s%N)" \
            -o "$temp_file"; then
            downloaded=true
        fi
    fi

    if [ "$downloaded" = "true" ]; then
        if [ ! -s "$temp_file" ] ||
           ! bash -n "$temp_file" ||
           ! grep -q '^smite_digest_migrate_existing()' "$temp_file"; then
            echo "ERROR: Downloaded Smite digest migration helper failed validation."
            rm -f "$temp_file"
            if [ "$local_helper_ok" = "true" ]; then
                echo "Using the existing validated local helper instead."
                # shellcheck disable=SC1090
                source "$DOCKER_SMITE_DIGEST_MODULE"
                return 0
            fi
            return 1
        fi

        if [ "$local_helper_ok" != "true" ] || ! cmp -s "$temp_file" "$DOCKER_SMITE_DIGEST_MODULE"; then
            echo "Synchronizing Smite digest migration helper..."
            if ! install -m 0755 "$temp_file" "$DOCKER_SMITE_DIGEST_MODULE"; then
                echo "ERROR: Failed to install the Smite digest migration helper."
                rm -f "$temp_file"
                if [ "$local_helper_ok" = "true" ]; then
                    echo "Using the existing validated local helper instead."
                    # shellcheck disable=SC1090
                    source "$DOCKER_SMITE_DIGEST_MODULE"
                    return 0
                fi
                return 1
            fi
        fi
    elif [ "$local_helper_ok" != "true" ]; then
        echo "ERROR: Smite digest migration helper is missing and could not be downloaded."
        rm -f "$temp_file"
        return 1
    else
        echo "WARNING: Could not refresh the Smite digest migration helper."
        echo "Using the existing validated local helper."
    fi

    rm -f "$temp_file"

    # shellcheck disable=SC1090
    source "$DOCKER_SMITE_DIGEST_MODULE"

    if ! declare -F smite_digest_migrate_existing >/dev/null 2>&1; then
        echo "ERROR: Smite digest migration helper did not load correctly."
        return 1
    fi

    return 0
}

docker_smite_private_network_modules_valid() {
    local wrapper="${1:-$DOCKER_SMITE_PRIVATE_NETWORK_MODULE}"
    local easytier="${2:-$DOCKER_SMITE_EASYTIER_MODULE}"

    [ -s "$wrapper" ] &&
    [ -s "$easytier" ] &&
    bash -n "$wrapper" >/dev/null 2>&1 &&
    bash -n "$easytier" >/dev/null 2>&1 &&
    grep -q '^show_smite_private_network_menu()' "$wrapper" &&
    grep -q '^show_smite_easytier_menu()' "$easytier"
}

docker_smite_ensure_private_network_modules() {
    local branch="${U_OPTI_BRANCH:-main}"
    local installed_version="${VERSION:-}"
    local release_base=""
    local branch_base="https://raw.githubusercontent.com/aghajani82/u-opti/$branch"
    local temp_dir=""
    local temp_wrapper=""
    local temp_easytier=""
    local local_pair_ok=false
    local downloaded=false
    local cache_bust=""

    if [ -z "$installed_version" ] && [ -f "/usr/local/lib/u-opti/VERSION" ]; then
        installed_version="$(tr -d '[:space:]' < /usr/local/lib/u-opti/VERSION)"
    fi

    if docker_smite_private_network_modules_valid; then
        local_pair_ok=true
    fi

    if ! command -v curl >/dev/null 2>&1; then
        if [ "$local_pair_ok" = "true" ]; then
            # shellcheck disable=SC1090
            source "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE"
            return 0
        fi
        DOCKER_SMITE_PRIVATE_NETWORK_ERROR="curl is required to prepare the Smite EasyTier Private Network modules."
        echo "ERROR: $DOCKER_SMITE_PRIVATE_NETWORK_ERROR"
        return 1
    fi

    temp_dir="$(mktemp -d)" || return 1
    temp_wrapper="$temp_dir/smite-private-network.sh"
    temp_easytier="$temp_dir/smite-easytier.sh"

    docker_smite_download_private_pair() {
        local base="$1"
        cache_bust="$(date +%s%N)"
        rm -f "$temp_wrapper" "$temp_easytier"
        curl -fsSL --retry 2 \
            "$base/modules/smite-private-network.sh?cb=$cache_bust" \
            -o "$temp_wrapper" || return 1
        curl -fsSL --retry 2 \
            "$base/modules/smite-easytier.sh?cb=$cache_bust" \
            -o "$temp_easytier" || return 1
        docker_smite_private_network_modules_valid "$temp_wrapper" "$temp_easytier"
    }

    if [[ "$installed_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        release_base="https://raw.githubusercontent.com/aghajani82/u-opti/v${installed_version}"
        if docker_smite_download_private_pair "$release_base"; then
            downloaded=true
        fi
    fi

    if [ "$downloaded" != "true" ]; then
        if docker_smite_download_private_pair "$branch_base"; then
            downloaded=true
        fi
    fi

    if [ "$downloaded" != "true" ]; then
        rm -rf "$temp_dir"
        unset -f docker_smite_download_private_pair
        if [ "$local_pair_ok" = "true" ]; then
            echo "WARNING: Could not refresh the Smite EasyTier Private Network modules."
            echo "Using the existing validated local module pair."
            # shellcheck disable=SC1090
            source "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE"
            return 0
        fi
        DOCKER_SMITE_PRIVATE_NETWORK_ERROR="Smite EasyTier Private Network modules are missing and could not be downloaded."
        echo "ERROR: $DOCKER_SMITE_PRIVATE_NETWORK_ERROR"
        return 1
    fi

    if [ "$local_pair_ok" != "true" ] || \
       ! cmp -s "$temp_wrapper" "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE" || \
       ! cmp -s "$temp_easytier" "$DOCKER_SMITE_EASYTIER_MODULE"; then
        echo "Synchronizing Smite EasyTier Private Network modules..."

        if ! install -m 0755 "$temp_wrapper" "${DOCKER_SMITE_PRIVATE_NETWORK_MODULE}.new" || \
           ! install -m 0755 "$temp_easytier" "${DOCKER_SMITE_EASYTIER_MODULE}.new"; then
            rm -f "${DOCKER_SMITE_PRIVATE_NETWORK_MODULE}.new" "${DOCKER_SMITE_EASYTIER_MODULE}.new"
            rm -rf "$temp_dir"
            unset -f docker_smite_download_private_pair
            if [ "$local_pair_ok" = "true" ]; then
                echo "WARNING: Module staging failed; using the existing validated local pair."
                # shellcheck disable=SC1090
                source "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE"
                return 0
            fi
            DOCKER_SMITE_PRIVATE_NETWORK_ERROR="Failed to stage the Smite EasyTier Private Network modules."
            echo "ERROR: $DOCKER_SMITE_PRIVATE_NETWORK_ERROR"
            return 1
        fi

        if ! mv -f "${DOCKER_SMITE_EASYTIER_MODULE}.new" "$DOCKER_SMITE_EASYTIER_MODULE" || \
           ! mv -f "${DOCKER_SMITE_PRIVATE_NETWORK_MODULE}.new" "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE"; then
            rm -f "${DOCKER_SMITE_PRIVATE_NETWORK_MODULE}.new" "${DOCKER_SMITE_EASYTIER_MODULE}.new"
            rm -rf "$temp_dir"
            unset -f docker_smite_download_private_pair
            DOCKER_SMITE_PRIVATE_NETWORK_ERROR="Failed to activate the Smite EasyTier Private Network modules."
            echo "ERROR: $DOCKER_SMITE_PRIVATE_NETWORK_ERROR"
            return 1
        fi
    fi

    rm -rf "$temp_dir"
    unset -f docker_smite_download_private_pair

    if ! docker_smite_private_network_modules_valid; then
        DOCKER_SMITE_PRIVATE_NETWORK_ERROR="Installed Smite EasyTier Private Network modules failed validation."
        echo "ERROR: $DOCKER_SMITE_PRIVATE_NETWORK_ERROR"
        return 1
    fi

    DOCKER_SMITE_PRIVATE_NETWORK_ERROR=""
    # shellcheck disable=SC1090
    source "$DOCKER_SMITE_PRIVATE_NETWORK_MODULE"

    if ! declare -F show_smite_private_network_menu >/dev/null 2>&1; then
        DOCKER_SMITE_PRIVATE_NETWORK_ERROR="Smite EasyTier Private Network entry point did not load correctly."
        echo "ERROR: $DOCKER_SMITE_PRIVATE_NETWORK_ERROR"
        return 1
    fi

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
        echo "2) Private Network"
        echo "3) 443 Gateway"
        echo "4) Compatibility Tools"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-4]: " SMITE_MANAGEMENT_CHOICE
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
                if docker_smite_ensure_private_network_modules && \
                   declare -F show_smite_private_network_menu >/dev/null 2>&1; then
                    show_smite_private_network_menu
                else
                    clear
                    echo "Smite Private Network module is not available."
                    if [ -n "$DOCKER_SMITE_PRIVATE_NETWORK_ERROR" ]; then
                        echo "$DOCKER_SMITE_PRIVATE_NETWORK_ERROR"
                    fi
                    echo
                    read -rp "Press Enter to return..."
                fi
                ;;
            3)
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
            4)
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
