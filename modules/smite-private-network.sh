#!/bin/bash

# U-OPTI - Smite Provider-Independent Private Network entry point
#
# The supported provider-independent transport is EasyTier over WSS/TCP 443.
# Keep this compatibility entry point so Docker -> Smite -> Private Network
# remains stable for clean installs and upgrades from older U-OPTI releases.

SMITE_PRIVATE_MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMITE_PRIVATE_EASYTIER_MODULE="$SMITE_PRIVATE_MODULE_DIR/smite-easytier.sh"

if [ ! -f "$SMITE_PRIVATE_EASYTIER_MODULE" ]; then
    SMITE_PRIVATE_EASYTIER_ERROR="EasyTier Private Network module is missing: $SMITE_PRIVATE_EASYTIER_MODULE"
elif ! bash -n "$SMITE_PRIVATE_EASYTIER_MODULE" >/dev/null 2>&1; then
    SMITE_PRIVATE_EASYTIER_ERROR="EasyTier Private Network module failed Bash syntax validation."
else
    # shellcheck disable=SC1090
    source "$SMITE_PRIVATE_EASYTIER_MODULE"
fi

show_smite_private_network_menu() {
    local previous_umask
    previous_umask="$(umask)"

    if declare -F show_smite_easytier_menu >/dev/null 2>&1; then
        show_smite_easytier_menu
        umask "$previous_umask"
        return
    fi

    clear
    echo "======================================"
    echo "      Smite Private Network"
    echo "======================================"
    echo
    echo "EasyTier Private Network is not available."
    if [ -n "${SMITE_PRIVATE_EASYTIER_ERROR:-}" ]; then
        echo "$SMITE_PRIVATE_EASYTIER_ERROR"
    fi
    echo
    read -rp "Press Enter to return..."
    umask "$previous_umask"
}
