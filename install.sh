#!/bin/bash

set -e

BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$BRANCH"

INSTALL_PATH="/usr/local/bin/u-opti"
LIB_PATH="/usr/local/lib/u-opti"
MODULES_PATH="$LIB_PATH/modules"

echo "======================================"
echo "          Installing U-OPTI"
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

TEMP_DIR=$(mktemp -d)

cleanup() {
    rm -rf "$TEMP_DIR"
}

trap cleanup EXIT

echo "Downloading VERSION..."

if ! curl -fsSL "$BASE_URL/VERSION" -o "$TEMP_DIR/VERSION"; then
    echo
    echo "Failed to download VERSION."
    exit 1
fi

REMOTE_VERSION=$(tr -d '[:space:]' < "$TEMP_DIR/VERSION")

if [ -z "$REMOTE_VERSION" ]; then
    echo
    echo "Error: Unable to determine U-OPTI version."
    exit 1
fi

echo "Remote Version: $REMOTE_VERSION"
echo
echo "Downloading U-OPTI..."

if ! curl -fsSL "$BASE_URL/u-opti" -o "$TEMP_DIR/u-opti"; then
    echo "Failed to download u-opti."
    exit 1
fi

echo "Downloading common library..."

if ! curl -fsSL "$BASE_URL/lib/common.sh" -o "$TEMP_DIR/common.sh"; then
    echo "Failed to download common.sh."
    exit 1
fi

echo "Downloading System Information module..."

if ! curl -fsSL "$BASE_URL/modules/system.sh" -o "$TEMP_DIR/system.sh"; then
    echo "Failed to download system.sh."
    exit 1
fi

echo "Downloading Time & Date module..."

if ! curl -fsSL "$BASE_URL/modules/time.sh" -o "$TEMP_DIR/time.sh"; then
    echo "Failed to download time.sh."
    exit 1
fi

echo "Downloading Swap Management module..."

if ! curl -fsSL "$BASE_URL/modules/swap.sh" -o "$TEMP_DIR/swap.sh"; then
    echo "Failed to download swap.sh."
    exit 1
fi

echo "Downloading BBR Management module..."

if ! curl -fsSL "$BASE_URL/modules/bbr.sh" -o "$TEMP_DIR/bbr.sh"; then
    echo "Failed to download bbr.sh."
    exit 1
fi

echo "Downloading Storage Management module..."

if ! curl -fsSL "$BASE_URL/modules/storage.sh" -o "$TEMP_DIR/storage.sh"; then
    echo "Failed to download storage.sh."
    exit 1
fi

echo "Downloading SSH Management module..."

if ! curl -fsSL "$BASE_URL/modules/ssh.sh" -o "$TEMP_DIR/ssh.sh"; then
    echo "Failed to download ssh.sh."
    exit 1
fi

echo "Downloading Firewall Management module..."

if ! curl -fsSL "$BASE_URL/modules/firewall.sh" -o "$TEMP_DIR/firewall.sh"; then
    echo "Failed to download firewall.sh."
    exit 1
fi

echo "Downloading X-UI PRO Management module..."

if ! curl -fsSL "$BASE_URL/modules/xui-pro.sh" -o "$TEMP_DIR/xui-pro.sh"; then
    echo "Failed to download xui-pro.sh."
    exit 1
fi

echo
echo "Checking downloaded files..."

REQUIRED_FILES=(
    "$TEMP_DIR/VERSION"
    "$TEMP_DIR/u-opti"
    "$TEMP_DIR/common.sh"
    "$TEMP_DIR/system.sh"
    "$TEMP_DIR/time.sh"
    "$TEMP_DIR/swap.sh"
    "$TEMP_DIR/bbr.sh"
    "$TEMP_DIR/storage.sh"
    "$TEMP_DIR/ssh.sh"
    "$TEMP_DIR/firewall.sh"
    "$TEMP_DIR/xui-pro.sh"
)

for FILE in "${REQUIRED_FILES[@]}"; do
    if [ ! -s "$FILE" ]; then
        echo
        echo "Error: Required file is missing or empty:"
        echo "$FILE"
        exit 1
    fi
done

echo "All required files are present."

echo
echo "Checking Bash syntax..."

bash -n "$TEMP_DIR/u-opti"
bash -n "$TEMP_DIR/common.sh"
bash -n "$TEMP_DIR/system.sh"
bash -n "$TEMP_DIR/time.sh"
bash -n "$TEMP_DIR/swap.sh"
bash -n "$TEMP_DIR/bbr.sh"
bash -n "$TEMP_DIR/storage.sh"
bash -n "$TEMP_DIR/ssh.sh"
bash -n "$TEMP_DIR/firewall.sh"
bash -n "$TEMP_DIR/xui-pro.sh"

echo "Bash syntax check passed."

echo
echo "Creating directories..."

mkdir -p "$LIB_PATH"
mkdir -p "$MODULES_PATH"

echo
echo "Installing files..."

cp "$TEMP_DIR/VERSION" "$LIB_PATH/VERSION"
cp "$TEMP_DIR/u-opti" "$INSTALL_PATH"
cp "$TEMP_DIR/common.sh" "$LIB_PATH/common.sh"

cp "$TEMP_DIR/system.sh" "$MODULES_PATH/system.sh"
cp "$TEMP_DIR/time.sh" "$MODULES_PATH/time.sh"
cp "$TEMP_DIR/swap.sh" "$MODULES_PATH/swap.sh"
cp "$TEMP_DIR/bbr.sh" "$MODULES_PATH/bbr.sh"
cp "$TEMP_DIR/storage.sh" "$MODULES_PATH/storage.sh"
cp "$TEMP_DIR/ssh.sh" "$MODULES_PATH/ssh.sh"
cp "$TEMP_DIR/firewall.sh" "$MODULES_PATH/firewall.sh"
cp "$TEMP_DIR/xui-pro.sh" "$MODULES_PATH/xui-pro.sh"

echo
echo "Setting permissions..."

chmod +x "$INSTALL_PATH"
chmod +x "$LIB_PATH/common.sh"

chmod +x "$MODULES_PATH/system.sh"
chmod +x "$MODULES_PATH/time.sh"
chmod +x "$MODULES_PATH/swap.sh"
chmod +x "$MODULES_PATH/bbr.sh"
chmod +x "$MODULES_PATH/storage.sh"
chmod +x "$MODULES_PATH/ssh.sh"
chmod +x "$MODULES_PATH/firewall.sh"
chmod +x "$MODULES_PATH/xui-pro.sh"

echo
echo "======================================"
echo "       Installation completed"
echo "======================================"
echo
echo "Installed Version: $REMOTE_VERSION"
echo
echo "Installation Path:"
echo "$INSTALL_PATH"
echo
echo "Library Path:"
echo "$LIB_PATH"
echo
echo "SSH Module:"
echo "$MODULES_PATH/ssh.sh"
echo
echo "Firewall Module:"
echo "$MODULES_PATH/firewall.sh"
echo
echo "X-UI PRO Module:"
echo "$MODULES_PATH/xui-pro.sh"
echo

"$INSTALL_PATH"
