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

BRANCH="${U_OPTI_BRANCH:-main}"
if [[ ! "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || [[ "$BRANCH" == *".."* ]] || [[ "$BRANCH" == /* ]]; then
    echo "ERROR: Invalid U-OPTI source branch/ref."
    exit 1
fi
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$BRANCH"
# BEGIN: U-OPTI immutable per-operation source pin
# Resolve once; never download a mixture of mutable branch revisions.
u_opti_resolve_source_sha() {
    local ref="$1" response
    if [[ ! "$ref" =~ ^[A-Za-z0-9._/-]+$ ]] ||
       [[ "$ref" == *".."* ]] || [[ "$ref" == /* ]]; then
        return 1
    fi
    response="$(curl -fsSL --retry 2 --connect-timeout 10 --max-time 30 \
        -H 'Accept: application/vnd.github+json' \
        -H 'X-GitHub-Api-Version: 2022-11-28' \
        "https://api.github.com/repos/aghajani82/u-opti/commits/$ref")" || return 1
    printf '%s' "$response" | python3 -c '
import json
import re
import sys
data = json.load(sys.stdin)
sha = data.get("sha") if isinstance(data, dict) else None
if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
    sys.exit("UNTRUSTED_SOURCE_SHA")
print(sha)
'
}
# END: U-OPTI immutable per-operation source pin

INSTALL_PATH="/usr/local/bin/u-opti"
LIB_PATH="/usr/local/lib/u-opti"
MODULES_PATH="$LIB_PATH/modules"

# Resume/rollback a previous interrupted install/update BEFORE new downloads
# or package operations. Bundled rescue is not sourced through new modules.
if [ -e "$LIB_PATH/.uopti-update-pending" ] || [ -L "$LIB_PATH/.uopti-update-pending" ]; then
    RESCUE="$LIB_PATH/.uopti-update-pending/rescue.py"
    if [ ! -f "$RESCUE" ] || [ -L "$RESCUE" ] ||
       ! command -v python3 >/dev/null 2>&1 ||
       ! python3 -B "$RESCUE" recover; then
        echo "HOLD: Prior interrupted U-OPTI transaction requires recovery; installer stopped." >&2
        exit 1
    fi
    echo "Previous interrupted U-OPTI transaction restored before installation."
fi

MODULES=(
    "system.sh"
    "time.sh"
    "swap.sh"
    "bbr.sh"
    "storage.sh"
    "ssh.sh"
    "ssh-access.sh"
    "firewall.sh"
    "fail2ban.sh"
    "xui-pro.sh"
    "certificate.sh"
    "backup.sh"
    "docker.sh"
    "smite.sh"
    "smite-node-local-bind.py"
    "smite-node-pairing.py"
    "smite-node-auth-candidate.py"
    "smite-node-replay-mount-admission.py"
    "smite-auth-image-overlay-audit.py"
    "smite-stage11-overlay-review.py"
    "smite-stage12-nginx-hmac-plan.py"
    "smite-stage19-pairing-443-plan.py"
    "smite-stage13-preflight.py"
    "smite-panel-auth-overlay.py"
    "smite-stage15-bundle-verify.py"
    "smite-clean-image-pair.py"
    "smite-registry-pair-admission.py"
    "smite-field-trial-candidate.json"
    "u-opti-update-transaction.py"
    "smite-foreign-gateway-signed-check.py"
    "smite-node-pairing-wizard.sh"
    "smite-digest-migrate.sh"
    "smite-install.sh"
    "smite-gateway.sh"
    "smite-frp-xhttp.sh"
    "smite-frp-xhttp-paths.py"
    "smite-frp-wizard.sh"
    "smite-profile-first.py"
    "smite-profile-first-menu.sh"
    "smite-backhaul-management.sh"
    "smite-tunnel-wizard.sh"
    "smite-tunnel-control-center.sh"
    "smite-managed-backhaul.py"
    "smite-managed-frp.py"
    "smite-managed-frp-transaction.py"
    "smite-managed-frp-control.py"
    "smite-managed-frp-menu.sh"
    "smite-managed-backhaul-control.py"
    "smite-managed-backhaul-menu.sh"
    "smite-managed-backhaul-host-gate.py"
    "smite-managed-backhaul-host-executor.py"
    "smite-managed-engine-host-admission.py"
    "smite-managed-engine-host-plan.py"
    "smite-managed-backhaul-pair-review.py"
    "smite-managed-backhaul-lifecycle.py"
    "smite-managed-backhaul-transaction.py"
    "smite-backhaul-sidecar.py"
    "smite-backhaul-sidecar-readiness.py"
    "smite-backhaul-sidecar-guided-prep.py"
    "smite-backhaul-sidecar-guided-trial.py"
    "smite-backhaul-sidecar-ssh-pair.py"
    "smite-backhaul-sidecar-paste-pair.py"
    "smite-backhaul-sidecar-admission.py"
    "smite-backhaul-sidecar-token.py"
    "smite-backhaul-sidecar-live-trial.py"
    "smite-backhaul-sidecar-reconcile.py"
    "smite-backhaul-rebuild-gate.sh"
    "smite-backhaul-sidecar-nginx-plan.py"
    "smite-backhaul-standard.sh"
    "smite-backhaul-spec.py"
    "smite-backhaul-node-patch.py"
    "smite-backhaul-panel-patch.py"
    "smite-foreign-gateway.sh"
    "smite-private-network.sh"
    "smite-easytier.sh"
    "docker-3xui.sh"
    "docker-3xui-instance.sh"
    "docker-3xui-certificate-multi.sh"
    "docker-3xui-compat.sh"
    "docker-3xui-nginx.sh"
    "docker-3xui-xhttp-guard.py"
    "fakesite.sh"
)

# Gate legacy adoption and uncertain partially installed states BEFORE
# the package-manager preflight or any download. Recheck after staging too.
if [ -L "$INSTALL_PATH" ] || [ -L "$LIB_PATH" ] || [ -L "$MODULES_PATH" ]; then
    echo "HOLD: Unsafe U-OPTI installation path (symlink)." >&2
    exit 1
fi
if [ -e "$INSTALL_PATH" ]; then
    if [ "${U_OPTI_ADOPT_EXISTING:-NO}" != "YES" ]; then
        echo "HOLD: Existing U-OPTI requires explicit migration approval." >&2
        echo "Use the normal Update menu for an already-supported version." >&2
        exit 1
    fi
elif [ -e "$LIB_PATH/common.sh" ] || [ -e "$LIB_PATH/VERSION" ]; then
    echo "HOLD: Incomplete prior install with no executable; review first." >&2
    exit 1
fi

echo "======================================"
echo "          Installing U-OPTI"
echo "======================================"
echo

if ! command -v curl >/dev/null 2>&1; then
    echo "Error: curl is required but is not installed."
    echo "Install it with: apt install curl"
    exit 1
fi

echo "Checking required system packages..."

REQUIRED_PACKAGES=(
    "sqlite3"
    "jq"
)

MISSING_PACKAGES=()

for PACKAGE in "${REQUIRED_PACKAGES[@]}"; do
    if ! dpkg -s "$PACKAGE" >/dev/null 2>&1; then
        MISSING_PACKAGES+=("$PACKAGE")
    fi
done

if [ "${#MISSING_PACKAGES[@]}" -gt 0 ]; then
    echo "Missing required packages: ${MISSING_PACKAGES[*]}"
    echo "Installing required system packages..."
    apt-get -o DPkg::Lock::Timeout=300 update
    DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 install -y "${MISSING_PACKAGES[@]}"
fi

echo "Required system packages are ready."
echo

TEMP_DIR=$(mktemp -d)
cleanup() { rm -rf "$TEMP_DIR"; }
trap cleanup EXIT

CACHE_BUST="$(date +%s%N)"

# Fail closed BEFORE downloading/committing any installation files.
if ! SOURCE_SHA="$(u_opti_resolve_source_sha "$BRANCH")"; then
    echo "HOLD: GitHub source revision could not be verified; install cancelled." >&2
    exit 1
fi
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$SOURCE_SHA"
echo "Source revision locked for this installation: $SOURCE_SHA"

echo "Downloading VERSION..."
curl -fsSL --retry 3 "$BASE_URL/VERSION?cb=$CACHE_BUST" -o "$TEMP_DIR/VERSION" || { echo "Failed to download VERSION."; exit 1; }
REMOTE_VERSION=$(tr -d '[:space:]' < "$TEMP_DIR/VERSION")
[ -n "$REMOTE_VERSION" ] || { echo "Error: Unable to determine U-OPTI version."; exit 1; }
echo "Remote Version: $REMOTE_VERSION"
echo

echo "Downloading U-OPTI..."
curl -fsSL --retry 3 "$BASE_URL/u-opti?cb=$CACHE_BUST" -o "$TEMP_DIR/u-opti" || { echo "Failed to download u-opti."; exit 1; }

echo "Downloading common library..."
curl -fsSL --retry 3 "$BASE_URL/lib/common.sh?cb=$CACHE_BUST" -o "$TEMP_DIR/common.sh" || { echo "Failed to download common.sh."; exit 1; }

for MODULE in "${MODULES[@]}"; do
    case "$MODULE" in
        system.sh) LABEL="System Information" ;;
        time.sh) LABEL="Time & Date" ;;
        swap.sh) LABEL="Swap Management" ;;
        bbr.sh) LABEL="BBR Management" ;;
        storage.sh) LABEL="Storage Management" ;;
        ssh.sh) LABEL="SSH Management" ;;
        ssh-access.sh) LABEL="SSH Access Management" ;;
        firewall.sh) LABEL="Firewall Management" ;;
        fail2ban.sh) LABEL="Fail2Ban Management" ;;
        xui-pro.sh) LABEL="X-UI PRO Management" ;;
        certificate.sh) LABEL="Certificate Management" ;;
        backup.sh) LABEL="Backup & Restore" ;;
        docker.sh) LABEL="Docker Management" ;;
        smite.sh) LABEL="Smite Compatibility Management" ;;
        smite-digest-migrate.sh) LABEL="Smite Digest Migration" ;;
        smite-install.sh) LABEL="Smite Installer / Lifecycle" ;;
        smite-gateway.sh) LABEL="Smite 443 Gateway" ;;
        smite-frp-xhttp.sh) LABEL="Smite Standard FRP XHTTP Automatic Routes" ;;
        smite-frp-xhttp-paths.py) LABEL="Smite FRP Custom XHTTP Path Registry" ;;
        smite-backhaul-management.sh) LABEL="Smite Tunnel Management & Backhaul (experimental)" ;;
        smite-tunnel-wizard.sh) LABEL="Smite Tunnel Wizard (experimental test-host install)" ;;
        smite-tunnel-control-center.sh) LABEL="Smite Tunnel Control Center (read-only dashboard)" ;;
        smite-foreign-gateway.sh) LABEL="Smite Foreign 443 Gateway" ;;
        smite-private-network.sh) LABEL="Smite Private Network Entry Point" ;;
        smite-easytier.sh) LABEL="Smite EasyTier Private Network" ;;
        docker-3xui.sh) LABEL="3x-UI Docker Management" ;;
        docker-3xui-instance.sh) LABEL="3x-UI Instance Management" ;;
        docker-3xui-certificate-multi.sh) LABEL="3x-UI Multi-Instance TLS Certificates" ;;
        docker-3xui-compat.sh) LABEL="3x-UI Compatibility Helpers" ;;
        docker-3xui-nginx.sh) LABEL="3x-UI Nginx / SSL Integration" ;;
        fakesite.sh) LABEL="Default Website / FakeSite" ;;
        *) LABEL="$MODULE" ;;
    esac
    echo "Downloading $LABEL module..."
    curl -fsSL --retry 3 "$BASE_URL/modules/$MODULE?cb=$CACHE_BUST" -o "$TEMP_DIR/$MODULE" || { echo "Failed to download $MODULE."; exit 1; }
done

echo
echo "Checking downloaded files..."
REQUIRED_FILES=("$TEMP_DIR/VERSION" "$TEMP_DIR/u-opti" "$TEMP_DIR/common.sh")
for MODULE in "${MODULES[@]}"; do
    REQUIRED_FILES+=("$TEMP_DIR/$MODULE")
done

for FILE in "${REQUIRED_FILES[@]}"; do
    if [ ! -s "$FILE" ]; then
        echo "Error: Required file is missing or empty:"
        echo "$FILE"
        exit 1
    fi
done
echo "All required files are present."

if ! grep -q 'echo "6) Hostname Management"' "$TEMP_DIR/u-opti" || \
   ! grep -q 'show_hostname_menu' "$TEMP_DIR/u-opti" || \
   ! grep -q 'show_hostname_menu()' "$TEMP_DIR/system.sh" || \
   ! grep -q 'echo "5) Smite Management"' "$TEMP_DIR/docker.sh" || \
   ! grep -q 'docker_smite_management_menu' "$TEMP_DIR/docker.sh" || \
   ! grep -q 'docker_smite_compatibility_menu' "$TEMP_DIR/docker.sh" || \
   ! grep -q 'docker_smite_ensure_digest_module' "$TEMP_DIR/docker.sh" || \
   ! grep -q 'smite_digest_migrate_existing()' "$TEMP_DIR/smite-digest-migrate.sh" || \
   ! grep -q 'show_smite_install_menu()' "$TEMP_DIR/smite-install.sh" || \
   ! grep -q 'show_smite_gateway_menu()' "$TEMP_DIR/smite-gateway.sh" || \
   ! grep -q 'smite_frp_wizard_menu()' "$TEMP_DIR/smite-frp-wizard.sh" || \
   ! grep -q 'def render(' "$TEMP_DIR/smite-frp-xhttp-paths.py" || \
   ! grep -q 'smite_bh_management_menu()' "$TEMP_DIR/smite-backhaul-management.sh" || \
   ! grep -q 'smite_tw_menu()' "$TEMP_DIR/smite-tunnel-wizard.sh" || \
   ! grep -q 'def validate(' "$TEMP_DIR/smite-profile-first.py" || \
   ! grep -q 'PROFILE FIRST' "$TEMP_DIR/smite-profile-first-menu.sh" || \
   ! grep -q 'twcc_menu()' "$TEMP_DIR/smite-tunnel-control-center.sh" || \
   ! grep -q 'show_smite_foreign_gateway_menu()' "$TEMP_DIR/smite-foreign-gateway.sh" || \
   ! grep -q 'show_smite_private_network_menu()' "$TEMP_DIR/smite-private-network.sh" || \
   ! grep -q 'show_smite_easytier_menu()' "$TEMP_DIR/smite-easytier.sh" || \
   ! grep -q 'docker_3xui_multi_certificate_menu()' "$TEMP_DIR/docker-3xui-certificate-multi.sh" || \
   ! grep -q 'show_smite_menu()' "$TEMP_DIR/smite.sh"; then
    echo
    echo "ERROR: Downloaded U-OPTI files failed feature verification."
    echo "The downloaded files are inconsistent or stale."
    echo "Installation cancelled."
    exit 1
fi

echo "Feature verification passed."

echo
echo "Checking Bash syntax..."
bash -n "$TEMP_DIR/u-opti"
bash -n "$TEMP_DIR/common.sh"
for MODULE in "${MODULES[@]}"; do
    case "$MODULE" in
        *.py) python3 -m py_compile "$TEMP_DIR/$MODULE" || exit 1 ;;
        *) bash -n "$TEMP_DIR/$MODULE" || exit 1 ;;
    esac
done
echo "Bash/Python syntax checks passed."

echo
echo "Preparing recoverable installation transaction..."
# A new installation and the first intentional migration from an old
# U-OPTI installation use the SAME durable backup+journal protocol. Do
# not overwrite a pre-existing installation without explicit consent.
if [ -e "$INSTALL_PATH" ] || [ -L "$INSTALL_PATH" ]; then
    if [ "${U_OPTI_ADOPT_EXISTING:-NO}" != "YES" ]; then
        echo "HOLD: Existing U-OPTI installation found. Use its regular Update menu." >&2
        echo "Legacy first adoption requires separate backup/review and explicit opt-in." >&2
        exit 1
    fi
    echo "Explicit legacy-adoption mode selected; original bytes will be journal-backed."
elif [ -e "$LIB_PATH/VERSION" ] || [ -L "$LIB_PATH/VERSION" ] ||
     [ -e "$LIB_PATH/common.sh" ] || [ -L "$LIB_PATH/common.sh" ]; then
    echo "HOLD: Incomplete existing installation without executable; manual review required." >&2
    exit 1
fi

if [ -L "$LIB_PATH" ] || [ -L "$MODULES_PATH" ]; then
    echo "HOLD: Unsafe U-OPTI installation directory." >&2
    exit 1
fi
mkdir -p "$LIB_PATH" "$MODULES_PATH"
# Persistent private backup, not volatile /tmp; all old-file bytes are saved
# before calling apply. Missing files are represented by explicit markers.
BACKUP_DIR="$(mktemp -d "$LIB_PATH/.uopti-backup-XXXXXXXX")"
backup_ok=true
backup_items=(u-opti common.sh VERSION INSTALL_REF "${MODULES[@]}")
for name in "${backup_items[@]}"; do
    case "$name" in
        u-opti) original="$INSTALL_PATH" ;;
        common.sh) original="$LIB_PATH/common.sh" ;;
        VERSION) original="$LIB_PATH/VERSION" ;;
        INSTALL_REF) original="$LIB_PATH/INSTALL_REF" ;;
        *) original="$MODULES_PATH/$name" ;;
    esac
    if [ -L "$original" ]; then
        backup_ok=false
        echo "HOLD: Unsafe symlink at $original" >&2
        break
    elif [ -f "$original" ]; then
        if [ ! -O "$original" ] || [ "$(stat -c %h "$original")" -ne 1 ] ||
           ! cp -- "$original" "$BACKUP_DIR/$name"; then
            backup_ok=false
            break
        fi
        chmod 0600 "$BACKUP_DIR/$name"
    elif [ ! -e "$original" ]; then
        : > "$BACKUP_DIR/.$name-was-missing"
        chmod 0600 "$BACKUP_DIR/.$name-was-missing"
    else
        backup_ok=false
        echo "HOLD: Unexpected non-file installation target: $original" >&2
        break
    fi
done

if [ "$backup_ok" != true ]; then
    echo "HOLD: Could not secure installation backup; NO live files changed." >&2
    echo "Review preserved backup: $BACKUP_DIR" >&2
    exit 1
fi
# Exact same already-downloaded, syntax-checked and SHA-pinned candidates.
# The helper records its own rescue copy before changing the first target.
echo "Applying staged, journal-backed installation..."
if ! python3 -B "$TEMP_DIR/u-opti-update-transaction.py" apply \
          "$TEMP_DIR" "$BACKUP_DIR" --source-ref "$BRANCH" "${MODULES[@]}"; then
    echo "HOLD: Transaction incomplete; attempting safely journaled rollback." >&2
    RESCUE="$LIB_PATH/.uopti-update-pending/rescue.py"
    if [ -f "$RESCUE" ] && [ ! -L "$RESCUE" ] &&
       python3 -B "$RESCUE" recover; then
        echo "Original U-OPTI files restored; backup retained at $BACKUP_DIR" >&2
    else
        echo "HOLD: Recovery needs operator review; backup retained at $BACKUP_DIR" >&2
    fi
    exit 1
fi

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
echo "Fail2Ban Module:"
echo "$MODULES_PATH/fail2ban.sh"
echo
echo "X-UI PRO Module:"
echo "$MODULES_PATH/xui-pro.sh"
echo
echo "Certificate Module:"
echo "$MODULES_PATH/certificate.sh"
echo
echo "Backup & Restore Module:"
echo "$MODULES_PATH/backup.sh"
echo

echo "Docker Module:"
echo "$MODULES_PATH/docker.sh"
echo

echo "Smite Compatibility Module:"
echo "$MODULES_PATH/smite.sh"
echo

echo "Smite Digest Migration Module:"
echo "$MODULES_PATH/smite-digest-migrate.sh"
echo

echo "Smite Installer Module:"
echo "$MODULES_PATH/smite-install.sh"
echo

echo "Smite Gateway Module:"
echo "$MODULES_PATH/smite-gateway.sh"
echo

echo "Smite Foreign Gateway Module:"
echo "$MODULES_PATH/smite-foreign-gateway.sh"
echo

echo "Smite Private Network Module:"
echo "$MODULES_PATH/smite-private-network.sh"
echo

echo "Smite EasyTier Module:"
echo "$MODULES_PATH/smite-easytier.sh"
echo

echo "3x-UI Docker Module:"
echo "$MODULES_PATH/docker-3xui.sh"
echo

echo "3x-UI Multi-Instance TLS Certificate Module:"
echo "$MODULES_PATH/docker-3xui-certificate-multi.sh"
echo

echo "3x-UI Nginx / SSL Module:"
echo "$MODULES_PATH/docker-3xui-nginx.sh"
echo

echo "Default Website / FakeSite Module:"
echo "$MODULES_PATH/fakesite.sh"
echo

"$INSTALL_PATH"
