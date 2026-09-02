#!/bin/bash

set -e

REPO_URL="https://raw.githubusercontent.com/aghajani82/u-opti/main/u-opti"
INSTALL_PATH="/usr/local/bin/u-opti"

echo "======================================"
echo "          Installing U-OPTI"
echo "======================================"
echo

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run this installer as root."
    exit 1
fi

echo "Downloading U-OPTI..."

curl -fsSL "$REPO_URL" -o "$INSTALL_PATH"

chmod +x "$INSTALL_PATH"

echo
echo "Installation completed successfully."
echo

"$INSTALL_PATH"
