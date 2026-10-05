#!/bin/bash
set -euo pipefail

# U-OPTI - Smite Private Setup Wizard installer/loader
# Installs the production Wizard modules without changing server role/state.

BRANCH="${U_OPTI_BRANCH:-main}"
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/${BRANCH}"
LIB_PATH="/usr/local/lib/u-opti"
MODULES_PATH="$LIB_PATH/modules"
WIZARD_BIN="/usr/local/bin/u-opti-smite-setup"
TMP_DIR="$(mktemp -d)"
OPEN_WIZARD=true

cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

if [ "${1:-}" = "--prepare-only" ]; then OPEN_WIZARD=false; fi

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "ERROR: Root privileges are required."
        exit 1
    fi
    exec sudo -E bash "$0" "$@"
fi

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required."; exit 1; }
mkdir -p "$MODULES_PATH"

MODULES=(
    "smite-setup-progress.sh"
    "smite-setup-progress-ui.sh"
    "smite-setup-progress-actions.sh"
    "smite-setup-progress-flow.sh"
    "smite-setup-progress-compact-ui.sh"
    "smite-gateway-acme-robust.sh"
)

for module in "${MODULES[@]}"; do
    echo "Downloading $module..."
    curl -fsSL --retry 3 "${BASE_URL}/modules/${module}?cb=$(date +%s%N)" -o "$TMP_DIR/$module"
    [ -s "$TMP_DIR/$module" ] || { echo "ERROR: Downloaded module is empty: $module"; exit 1; }
    bash -n "$TMP_DIR/$module" || { echo "ERROR: Bash syntax validation failed: $module"; exit 1; }
done

grep -q '^smite_setup_progress_collect()' "$TMP_DIR/smite-setup-progress.sh"
grep -q '^smite_setup_ui_step_reboot()' "$TMP_DIR/smite-setup-progress-ui.sh"
grep -q '^smite_setup_actions_initial_role_prompt()' "$TMP_DIR/smite-setup-progress-actions.sh"
grep -q '^smite_setup_progress_main_symbol()' "$TMP_DIR/smite-setup-progress-flow.sh"
grep -q '^show_smite_setup_progress_menu()' "$TMP_DIR/smite-setup-progress-compact-ui.sh"
grep -q '^smite_gateway_prepare_acme()' "$TMP_DIR/smite-gateway-acme-robust.sh"

for module in "${MODULES[@]}"; do install -m 0755 "$TMP_DIR/$module" "$MODULES_PATH/$module"; done

cat > "$WIZARD_BIN" <<'EOF_WIZARD'
#!/bin/bash
set -e
source /usr/local/lib/u-opti/modules/docker.sh
if declare -F docker_smite_open_setup_wizard >/dev/null 2>&1; then
    docker_smite_open_setup_wizard
    exit $?
fi
echo "ERROR: Installed Docker module does not provide the Smite Setup Wizard entry point."
exit 1
EOF_WIZARD
chmod 0755 "$WIZARD_BIN"

if [ "$OPEN_WIZARD" = "true" ]; then
    source "$MODULES_PATH/smite-gateway-acme-robust.sh"
    source "$MODULES_PATH/smite-setup-progress.sh"
    source "$MODULES_PATH/smite-setup-progress-ui.sh"
    source "$MODULES_PATH/smite-setup-progress-actions.sh"
    source "$MODULES_PATH/smite-setup-progress-flow.sh"
    source "$MODULES_PATH/smite-setup-progress-compact-ui.sh"
    smite_setup_actions_initial_role_prompt || exit 0
    show_smite_setup_progress_menu
fi
