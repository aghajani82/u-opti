#!/bin/bash
set -euo pipefail

# U-OPTI test-branch bootstrap helper.
# This file exists only on feature/smite-gateway-first-flow so the selected
# branch survives new SSH/login shells during clean validation.

TEST_BRANCH="feature/smite-gateway-first-flow"
PROFILE_FILE="/etc/profile.d/u-opti-test-branch.sh"
INSTALLER_URL="https://raw.githubusercontent.com/aghajani82/u-opti/${TEST_BRANCH}/install.sh"

if [ "${EUID}" -ne 0 ]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "ERROR: Root privileges are required, but sudo is not installed."
        exit 1
    fi
    exec sudo -E bash "$0" "$@"
fi

cat > "$PROFILE_FILE" <<EOF_PROFILE
# Managed temporarily by the U-OPTI gateway-first test branch.
export U_OPTI_BRANCH=${TEST_BRANCH}
EOF_PROFILE
chmod 0644 "$PROFILE_FILE"

export U_OPTI_BRANCH="$TEST_BRANCH"

echo "U-OPTI test branch pinned: $U_OPTI_BRANCH"
echo "Profile marker: $PROFILE_FILE"
echo

tmp_installer="$(mktemp)"
trap 'rm -f "$tmp_installer"' EXIT

curl -fsSL --retry 3 "$INSTALLER_URL?cb=$(date +%s%N)" -o "$tmp_installer"
bash "$tmp_installer"
