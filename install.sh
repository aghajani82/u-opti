#!/bin/bash

set -e

VERSION="0.8.0"

BRANCH="refactor/v0.8.0"
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$BRANCH"

INSTALL_PATH="/usr/local/bin/u-opti"
LIB_PATH="/usr/local/lib/u-opti"
MODULES_PATH="$LIB_PATH/modules"

echo "======================================"
echo "          Installing U-OPTI"
echo "              v$VERSION"
echo "======================================"
echo

if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run this installer as root."
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "Error: curl is required but is not installed."
    echo "Install it with: apt install curl"
    exit 1
fi

echo "Creating directories..."

mkdir -p "$LIB_PATH"
mkdir -p "$MODULES_PATH"

echo
echo "Downloading U-OPTI..."

curl -fsSL "$BASE_URL/u-opti" -o "$INSTALL_PATH"

echo "Downloading common library..."

curl -fsSL "$BASE_URL/lib/common.sh" -o "$LIB_PATH/common.sh"

echo "Downloading System Information module..."

curl -fsSL "$BASE_URL/modules/system.sh" -o "$MODULES_PATH/system.sh"

echo "Downloading Time & Date module..."

curl -fsSL "$BASE_URL/modules/time.sh" -o "$MODULES_PATH/time.sh"

echo "Downloading Swap Management module..."

curl -fsSL "$BASE_URL/modules/swap.sh" -o "$MODULES_PATH/swap.sh"

echo "Downloading BBR Management module..."

curl -fsSL "$BASE_URL/modules/bbr.sh" -o "$MODULES_PATH/bbr.sh"

echo "Downloading Storage Management module..."

curl -fsSL "$BASE_URL/modules/storage.sh" -o "$MODULES_PATH/storage.sh"

echo
echo "Checking downloaded files..."

REQUIRED_FILES=(
    "$INSTALL_PATH"
    "$LIB_PATH/common.sh"
    "$MODULES_PATH/system.sh"
    "$MODULES_PATH/time.sh"
    "$MODULES_PATH/swap.sh"
    "$MODULES_PATH/bbr.sh"
    "$MODULES_PATH/storage.sh"
)

for FILE in "${REQUIRED_FILES[@]}"; do
    if [ ! -s "$FILE" ]; then
        echo "Error: Required file is missing or empty:"
        echo "$FILE"
        exit 1
    fi
done

echo "All required files are present."

echo
echo "Checking Bash syntax..."

bash -n "$INSTALL_PATH"
bash -n "$LIB_PATH/common.sh"
bash -n "$MODULES_PATH/system.sh"
bash -n "$MODULES_PATH/time.sh"
bash -n "$MODULES_PATH/swap.sh"
bash -n "$MODULES_PATH/bbr.sh"
bash -n "$MODULES_PATH/storage.sh"

echo "Bash syntax check passed."

echo
echo "Setting permissions..."

chmod +x "$INSTALL_PATH"
chmod +x "$LIB_PATH/common.sh"

chmod +x "$MODULES_PATH/system.sh"
chmod +x "$MODULES_PATH/time.sh"
chmod +x "$MODULES_PATH/swap.sh"
chmod +x "$MODULES_PATH/bbr.sh"
chmod +x "$MODULES_PATH/storage.sh"

echo
echo "======================================"
echo "       Installation completed"
echo "======================================"
echo
echo "Installed files:"
echo
echo "$INSTALL_PATH"
echo "$LIB_PATH/common.sh"
echo "$MODULES_PATH/system.sh"
echo "$MODULES_PATH/time.sh"
echo "$MODULES_PATH/swap.sh"
echo "$MODULES_PATH/bbr.sh"
echo "$MODULES_PATH/storage.sh"
echo

"$INSTALL_PATH"
