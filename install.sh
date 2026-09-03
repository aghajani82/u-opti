#!/bin/bash

set -e

VERSION="0.8.0"

BRANCH="refactor/v0.8.0"
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$BRANCH"

INSTALL_PATH="/usr/local/bin/u-opti"
LIB_PATH="/usr/local/lib/u-opti"

echo "======================================"
echo "          Installing U-OPTI"
echo "              v$VERSION"
echo "======================================"
echo

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run this installer as root."
    exit 1
fi

echo "Creating directories..."

mkdir -p "$LIB_PATH"
mkdir -p "$LIB_PATH/modules"

echo
echo "Downloading U-OPTI..."

curl -fsSL "$BASE_URL/u-opti" -o "$INSTALL_PATH"

echo "Downloading common library..."

curl -fsSL "$BASE_URL/lib/common.sh" -o "$LIB_PATH/common.sh"

echo "Downloading System Information module..."

curl -fsSL "$BASE_URL/modules/system.sh" -o "$LIB_PATH/modules/system.sh"

chmod +x "$INSTALL_PATH"
chmod +x "$LIB_PATH/common.sh"
chmod +x "$LIB_PATH/modules/system.sh"

echo
echo "======================================"
echo "       Installation completed"
echo "======================================"
echo

"$INSTALL_PATH"
