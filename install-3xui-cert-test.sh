#!/usr/bin/env bash
set -euo pipefail

BRANCH="${U_OPTI_BRANCH:-feature/3xui-multi-instance-cert-sync}"
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/${BRANCH}"
MODULES_DIR="/usr/local/lib/u-opti/modules"
INSTANCE_MODULE="$MODULES_DIR/docker-3xui-instance.sh"
CERT_MODULE="$MODULES_DIR/certificate.sh"
FEATURE_MODULE="$MODULES_DIR/docker-3xui-certificate-multi.sh"
DIRECT_BIN="/usr/local/bin/u-opti-3xui-cert"
BACKUP_DIR="/etc/u-opti/test-overlays/3xui-cert"
BACKUP_FILE="$BACKUP_DIR/docker-3xui-instance.sh.original"
MARKER="# U-OPTI-TEST-3XUI-MULTI-CERT"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "ERROR: Run this installer as root."
    exit 1
fi

if [[ ! -f "$CERT_MODULE" || ! -f "$INSTANCE_MODULE" ]]; then
    echo "ERROR: U-OPTI certificate / 3x-UI Instance modules were not found."
    echo "Install or update U-OPTI first."
    exit 1
fi

command -v curl >/dev/null 2>&1 || {
    echo "ERROR: curl is required."
    exit 1
}

mkdir -p "$MODULES_DIR" "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

curl -fsSL --retry 3 \
    "${BASE_URL}/modules/docker-3xui-certificate-multi.sh?cb=$(date +%s%N)" \
    -o "$TMP_FILE"

[[ -s "$TMP_FILE" ]] || {
    echo "ERROR: Downloaded feature module is empty."
    exit 1
}

bash -n "$TMP_FILE"
grep -q '^docker_3xui_multi_certificate_menu()' "$TMP_FILE"
grep -q '^show_certificate_menu()' "$TMP_FILE"

install -m 0755 "$TMP_FILE" "$FEATURE_MODULE"

if [[ ! -f "$BACKUP_FILE" ]]; then
    cp -a "$INSTANCE_MODULE" "$BACKUP_FILE"
fi

if ! grep -Fq "$MARKER" "$INSTANCE_MODULE"; then
    cat >> "$INSTANCE_MODULE" <<'EOF_PATCH'

# U-OPTI-TEST-3XUI-MULTI-CERT
# Temporary clean-test loader. Production integration will package/load this
# module without patching the installed Instance registry file.
if [ -f "/usr/local/lib/u-opti/modules/docker-3xui-certificate-multi.sh" ]; then
    # shellcheck disable=SC1091
    source "/usr/local/lib/u-opti/modules/docker-3xui-certificate-multi.sh"
fi
EOF_PATCH
fi

bash -n "$INSTANCE_MODULE"

cat > "$DIRECT_BIN" <<'EOF_DIRECT'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    exec sudo -E "$0" "$@"
fi

MODULES_DIR="/usr/local/lib/u-opti/modules"
source "$MODULES_DIR/certificate.sh"
source "$MODULES_DIR/docker-3xui-instance.sh"
source "$MODULES_DIR/docker-3xui-certificate-multi.sh"

docker_3xui_multi_certificate_menu
EOF_DIRECT
chmod 0755 "$DIRECT_BIN"

cat <<EOF_DONE
======================================
  3x-UI TLS Certificate Test Ready
======================================

Branch : $BRANCH
Module : $FEATURE_MODULE

Test from the normal U-OPTI path:
  u-opti
  -> Certificate Management
  -> 6) 3x-UI Docker TLS Certificate

Or open the feature directly:
  u-opti-3xui-cert

The production U-OPTI files were not changed in GitHub main.
A local backup of docker-3xui-instance.sh is stored at:
  $BACKUP_FILE
EOF_DONE
