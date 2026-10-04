#!/bin/bash
set -euo pipefail

BRANCH="feature/smite-private-setup-progress"
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/${BRANCH}"
TMP_DIR="$(mktemp -d)"
PROFILE_FILE="/etc/profile.d/u-opti-test-branch.sh"
WIZARD_BIN="/usr/local/bin/u-opti-smite-setup"
LIB_PATH="/usr/local/lib/u-opti"
MODULES_PATH="$LIB_PATH/modules"

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "ERROR: Root privileges are required."
        exit 1
    fi
    exec sudo -E bash "$0" "$@"
fi

command -v curl >/dev/null 2>&1 || {
    echo "ERROR: curl is required."
    exit 1
}

export U_OPTI_BRANCH="$BRANCH"

cat > "$PROFILE_FILE" <<EOF_PROFILE
# U-OPTI experimental branch used for the Smite Private Setup Wizard test.
export U_OPTI_BRANCH="$BRANCH"
EOF_PROFILE
chmod 0644 "$PROFILE_FILE"

echo "======================================"
echo " U-OPTI Smite Wizard Clean Test Setup"
echo "======================================"
echo
echo "Branch: $BRANCH"
echo

echo "Downloading branch installer..."
curl -fsSL --retry 3 "${BASE_URL}/install.sh?cb=$(date +%s%N)" -o "$TMP_DIR/install.sh"

# The normal installer opens U-OPTI at the end. For this test entry point we
# suppress that final launch so the new setup wizard can become the first UI.
sed '/^"\$INSTALL_PATH"$/d' "$TMP_DIR/install.sh" > "$TMP_DIR/install-base.sh"
chmod +x "$TMP_DIR/install-base.sh"

echo "Installing U-OPTI from the test branch..."
bash "$TMP_DIR/install-base.sh"

# Keep this clean test off the v0.15.0 release-refresh path. Dynamic Smite
# helper refreshes will therefore use U_OPTI_BRANCH instead of the old tag.
printf '%s\n' '0.15.1-dev' > "$LIB_PATH/VERSION"

mkdir -p "$MODULES_PATH"

echo "Installing Smite Setup Progress core..."
curl -fsSL --retry 3 "${BASE_URL}/modules/smite-setup-progress.sh?cb=$(date +%s%N)" \
    -o "$TMP_DIR/smite-setup-progress.sh"

echo "Installing Smite Setup Progress UI..."
curl -fsSL --retry 3 "${BASE_URL}/modules/smite-setup-progress-ui.sh?cb=$(date +%s%N)" \
    -o "$TMP_DIR/smite-setup-progress-ui.sh"

bash -n "$TMP_DIR/smite-setup-progress.sh"
bash -n "$TMP_DIR/smite-setup-progress-ui.sh"

install -m 0755 "$TMP_DIR/smite-setup-progress.sh" "$MODULES_PATH/smite-setup-progress.sh"
install -m 0755 "$TMP_DIR/smite-setup-progress-ui.sh" "$MODULES_PATH/smite-setup-progress-ui.sh"

cat > "$WIZARD_BIN" <<'EOF_WIZARD'
#!/bin/bash
set -e
export U_OPTI_BRANCH="feature/smite-private-setup-progress"
source /usr/local/lib/u-opti/modules/smite-setup-progress.sh
source /usr/local/lib/u-opti/modules/smite-setup-progress-ui.sh
show_smite_setup_progress_menu
EOF_WIZARD
chmod 0755 "$WIZARD_BIN"

echo
echo "======================================"
echo "          Test Setup Ready"
echo "======================================"
echo
echo "Installed version : 0.15.1-dev"
echo "Pinned test branch: $BRANCH"
echo "Wizard command    : u-opti-smite-setup"
echo
echo "The wizard will open now."
echo "After a future SSH login, the test branch is restored automatically."
echo

exec "$WIZARD_BIN"
