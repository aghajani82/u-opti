#!/bin/bash
set -euo pipefail

BRANCH="feature/smite-private-setup-progress"
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/${BRANCH}"
TMP_DIR="$(mktemp -d)"
PROFILE_FILE="/etc/profile.d/u-opti-test-branch.sh"
WIZARD_BIN="/usr/local/bin/u-opti-smite-setup"
LIB_PATH="/usr/local/lib/u-opti"
MODULES_PATH="$LIB_PATH/modules"
DOCKER_MODULE="$MODULES_PATH/docker.sh"

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

echo "Installing Smite Setup Progress actions..."
curl -fsSL --retry 3 "${BASE_URL}/modules/smite-setup-progress-actions.sh?cb=$(date +%s%N)" \
    -o "$TMP_DIR/smite-setup-progress-actions.sh"

echo "Installing sequential progress flow..."
curl -fsSL --retry 3 "${BASE_URL}/modules/smite-setup-progress-flow.sh?cb=$(date +%s%N)" \
    -o "$TMP_DIR/smite-setup-progress-flow.sh"

echo "Installing compact Wizard menu..."
curl -fsSL --retry 3 "${BASE_URL}/modules/smite-setup-progress-compact-ui.sh?cb=$(date +%s%N)" \
    -o "$TMP_DIR/smite-setup-progress-compact-ui.sh"

echo "Installing hardened Gateway ACME probe..."
curl -fsSL --retry 3 "${BASE_URL}/modules/smite-gateway-acme-robust.sh?cb=$(date +%s%N)" \
    -o "$TMP_DIR/smite-gateway-acme-robust.sh"

bash -n "$TMP_DIR/smite-setup-progress.sh"
bash -n "$TMP_DIR/smite-setup-progress-ui.sh"
bash -n "$TMP_DIR/smite-setup-progress-actions.sh"
bash -n "$TMP_DIR/smite-setup-progress-flow.sh"
bash -n "$TMP_DIR/smite-setup-progress-compact-ui.sh"
bash -n "$TMP_DIR/smite-gateway-acme-robust.sh"

install -m 0755 "$TMP_DIR/smite-setup-progress.sh" "$MODULES_PATH/smite-setup-progress.sh"
install -m 0755 "$TMP_DIR/smite-setup-progress-ui.sh" "$MODULES_PATH/smite-setup-progress-ui.sh"
install -m 0755 "$TMP_DIR/smite-setup-progress-actions.sh" "$MODULES_PATH/smite-setup-progress-actions.sh"
install -m 0755 "$TMP_DIR/smite-setup-progress-flow.sh" "$MODULES_PATH/smite-setup-progress-flow.sh"
install -m 0755 "$TMP_DIR/smite-setup-progress-compact-ui.sh" "$MODULES_PATH/smite-setup-progress-compact-ui.sh"
install -m 0755 "$TMP_DIR/smite-gateway-acme-robust.sh" "$MODULES_PATH/smite-gateway-acme-robust.sh"

# For this clean-test branch, make Docker Management -> Smite Management open
# the new 10-step Wizard directly. Keep the normal Docker menu and all legacy
# Smite functions intact; only the Smite Management entry function is
# overridden after the original docker.sh definitions.
python3 - "$DOCKER_MODULE" <<'PY'
from pathlib import Path
import re, sys

path = Path(sys.argv[1])
text = path.read_text()
start = "# BEGIN U-OPTI SMITE WIZARD TEST ENTRY"
end = "# END U-OPTI SMITE WIZARD TEST ENTRY"
text = re.sub(rf"\n?{re.escape(start)}.*?{re.escape(end)}\n?", "\n", text, flags=re.S)
block = r'''

# BEGIN U-OPTI SMITE WIZARD TEST ENTRY
# Experimental clean-install UX: Docker Management -> Smite Management opens
# the private setup progress Wizard directly.
if [ -f "$DOCKER_MODULE_DIR/smite-setup-progress.sh" ] && \
   [ -f "$DOCKER_MODULE_DIR/smite-setup-progress-ui.sh" ] && \
   [ -f "$DOCKER_MODULE_DIR/smite-setup-progress-actions.sh" ] && \
   [ -f "$DOCKER_MODULE_DIR/smite-setup-progress-flow.sh" ] && \
   [ -f "$DOCKER_MODULE_DIR/smite-setup-progress-compact-ui.sh" ] && \
   [ -f "$DOCKER_MODULE_DIR/smite-gateway-acme-robust.sh" ]; then
    # The base docker module has already loaded the normal gateway functions.
    # Override only the local ACME readiness probe for this clean-install test.
    # shellcheck disable=SC1090
    source "$DOCKER_MODULE_DIR/smite-gateway-acme-robust.sh"
    # shellcheck disable=SC1090
    source "$DOCKER_MODULE_DIR/smite-setup-progress.sh"
    # shellcheck disable=SC1090
    source "$DOCKER_MODULE_DIR/smite-setup-progress-ui.sh"
    # shellcheck disable=SC1090
    source "$DOCKER_MODULE_DIR/smite-setup-progress-actions.sh"
    # shellcheck disable=SC1090
    source "$DOCKER_MODULE_DIR/smite-setup-progress-flow.sh"
    # shellcheck disable=SC1090
    source "$DOCKER_MODULE_DIR/smite-setup-progress-compact-ui.sh"

    docker_smite_management_menu() {
        smite_setup_actions_initial_role_prompt || return
        show_smite_setup_progress_menu
    }
fi
# END U-OPTI SMITE WIZARD TEST ENTRY
'''
path.write_text(text.rstrip() + block + "\n")
PY

bash -n "$DOCKER_MODULE"

cat > "$WIZARD_BIN" <<'EOF_WIZARD'
#!/bin/bash
set -e
export U_OPTI_BRANCH="feature/smite-private-setup-progress"

# docker.sh contains the experimental Smite Management -> Wizard entry block
# installed by install-smite-wizard-test.sh.
source /usr/local/lib/u-opti/modules/docker.sh

if ! declare -F show_smite_setup_progress_menu >/dev/null 2>&1; then
    echo "ERROR: Smite Setup Wizard modules are not loaded."
    exit 1
fi

smite_setup_actions_initial_role_prompt || exit 0
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
echo "Normal menu path  : U-OPTI -> Docker Management -> Smite Management"
echo "The Wizard main page now shows only the 10-step progress list."
echo "Use .1 through .10 for read-only step details."
echo "The [~] marker identifies exactly one next recommended step."
echo "Next/Then lines show which server should be used for the following work."
echo "Step checks refresh silently whenever the Wizard page is redrawn."
echo "Gateway ACME local readiness checks bypass proxy variables and retry safely."
echo
echo "The Wizard will open now."
echo "On a fresh host it first asks whether this is IR/Panel or KH/Foreign."
echo "After a future SSH login, the test branch is restored automatically."
echo

exec "$WIZARD_BIN"
