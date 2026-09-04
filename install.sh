#!/bin/bash

set -e

# U-OPTI installer requires root privileges.
if [ "$EUID" -ne 0 ]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "Error: Root privileges are required, but sudo is not installed."
        exit 1
    fi
    exec sudo -E bash "$0" "$@"
fi

BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$BRANCH"
INSTALL_PATH="/usr/local/bin/u-opti"
LIB_PATH="/usr/local/lib/u-opti"
MODULES_PATH="$LIB_PATH/modules"

MODULES=(
    "system.sh"
    "time.sh"
    "swap.sh"
    "bbr.sh"
    "storage.sh"
    "ssh.sh"
    "firewall.sh"
    "xui-pro.sh"
    "certificate.sh"
)

echo "======================================"
echo "          Installing U-OPTI"
echo "======================================"
echo

if ! command -v curl >/dev/null 2>&1; then
    echo "Error: curl is required but is not installed."
    echo "Install it with: apt install curl"
    exit 1
fi

TEMP_DIR=$(mktemp -d)
cleanup() { rm -rf "$TEMP_DIR"; }
trap cleanup EXIT

echo "Downloading VERSION..."
curl -fsSL "$BASE_URL/VERSION" -o "$TEMP_DIR/VERSION" || { echo "Failed to download VERSION."; exit 1; }
REMOTE_VERSION=$(tr -d '[:space:]' < "$TEMP_DIR/VERSION")
[ -n "$REMOTE_VERSION" ] || { echo "Error: Unable to determine U-OPTI version."; exit 1; }
echo "Remote Version: $REMOTE_VERSION"
echo

echo "Downloading U-OPTI..."
curl -fsSL "$BASE_URL/u-opti" -o "$TEMP_DIR/u-opti" || { echo "Failed to download u-opti."; exit 1; }

echo "Downloading common library..."
curl -fsSL "$BASE_URL/lib/common.sh" -o "$TEMP_DIR/common.sh" || { echo "Failed to download common.sh."; exit 1; }

for MODULE in "${MODULES[@]}"; do
    case "$MODULE" in
        system.sh) LABEL="System Information" ;;
        time.sh) LABEL="Time & Date" ;;
        swap.sh) LABEL="Swap Management" ;;
        bbr.sh) LABEL="BBR Management" ;;
        storage.sh) LABEL="Storage Management" ;;
        ssh.sh) LABEL="SSH Management" ;;
        firewall.sh) LABEL="Firewall Management" ;;
        xui-pro.sh) LABEL="X-UI PRO Management" ;;
        certificate.sh) LABEL="Certificate Management" ;;
        *) LABEL="$MODULE" ;;
    esac
    echo "Downloading $LABEL module..."
    curl -fsSL "$BASE_URL/modules/$MODULE" -o "$TEMP_DIR/$MODULE" || { echo "Failed to download $MODULE."; exit 1; }
done

echo
echo "Checking downloaded files..."
REQUIRED_FILES=("$TEMP_DIR/VERSION" "$TEMP_DIR/u-opti" "$TEMP_DIR/common.sh")
for MODULE in "${MODULES[@]}"; do REQUIRED_FILES+=("$TEMP_DIR/$MODULE"); done
for FILE in "${REQUIRED_FILES[@]}"; do
    if [ ! -s "$FILE" ]; then echo "Error: Required file is missing or empty:"; echo "$FILE"; exit 1; fi
done
echo "All required files are present."

echo
echo "Checking Bash syntax..."
bash -n "$TEMP_DIR/u-opti"
bash -n "$TEMP_DIR/common.sh"
for MODULE in "${MODULES[@]}"; do bash -n "$TEMP_DIR/$MODULE"; done
echo "Bash syntax check passed."

echo
echo "Creating directories..."
mkdir -p "$LIB_PATH" "$MODULES_PATH"

echo
echo "Installing files..."
cp "$TEMP_DIR/VERSION" "$LIB_PATH/VERSION"
cp "$TEMP_DIR/u-opti" "$INSTALL_PATH"
cp "$TEMP_DIR/common.sh" "$LIB_PATH/common.sh"
for MODULE in "${MODULES[@]}"; do cp "$TEMP_DIR/$MODULE" "$MODULES_PATH/$MODULE"; done

echo
echo "Setting permissions..."
chmod +x "$INSTALL_PATH" "$LIB_PATH/common.sh"
for MODULE in "${MODULES[@]}"; do chmod +x "$MODULES_PATH/$MODULE"; done

echo
echo "======================================"
echo "       Installation completed"
echo "======================================"
echo
echo "Installed Version: $REMOTE_VERSION"
echo
echo "Installation Path:"; echo "$INSTALL_PATH"
echo
echo "Library Path:"; echo "$LIB_PATH"
echo
echo "SSH Module:"; echo "$MODULES_PATH/ssh.sh"
echo
echo "Firewall Module:"; echo "$MODULES_PATH/firewall.sh"
echo
echo "X-UI PRO Module:"; echo "$MODULES_PATH/xui-pro.sh"
echo
echo "Certificate Module:"; echo "$MODULES_PATH/certificate.sh"
echo

"$INSTALL_PATH"
