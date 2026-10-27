#!/usr/bin/env bash
# Offline test for Clean-RC Nginx package preparation; no host packages touched.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/modules/smite-clean-rc-preflight.sh"

SMITE_INSTALL_PROFILE=clean-rc
called=0
smite_gateway_ensure_packages() {
    called=$((called + 1))
    return 0
}
smite_clean_rc_broker_code_ready() { return 0; }
smite_clean_rc_nginx_paths_ready() { return 0; }
smite_install_pause() { :; }

read() {
    local variable="${!#}"
    printf -v "$variable" '%s' "${TEST_ANSWER:-y}"
    return 0
}

TEST_ANSWER=y
smite_clean_rc_prepare_gateway_packages
[ "$called" -eq 1 ]

TEST_ANSWER=n
if smite_clean_rc_prepare_gateway_packages; then
    echo "Expected explicit decline to hold." >&2
    exit 1
fi
[ "$called" -eq 1 ]

SMITE_INSTALL_PROFILE=stable
TEST_ANSWER=y
smite_clean_rc_prepare_gateway_packages
[ "$called" -eq 1 ]

# The official fresh Clean-RC IR entry must prepare Nginx/Certbot before
# exposing any Panel + Iran Node installation action. No host operations here.
python3 - "$ROOT" <<'PY_FRESH_ENTRY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
source = (root / "u-opti").read_text(encoding="utf-8")
start = source.index('if [ "${1:-}" = "--smite-clean-rc" ]; then')
end = source.index("\nwhile true; do", start)
entry = source[start:end]
for expected in (
    'SMITE_RC_PREFLIGHT_MODULE="$MODULES_PATH/smite-clean-rc-preflight.sh"',
    'source "$SMITE_RC_PREFLIGHT_MODULE"',
    'smite_clean_rc_prepare_gateway_packages || {',
    'show_smite_install_menu',
):
    assert expected in entry, f"Missing fresh Clean-RC gate: {expected}"
assert entry.index('smite_clean_rc_prepare_gateway_packages || {') < entry.index('show_smite_install_menu')
installer = (root / "install.sh").read_text(encoding="utf-8")
assert '"smite-clean-rc-preflight.sh"' in installer
assert "smite_clean_rc_prepare_gateway_packages()" in installer
print("SMITE_CLEAN_RC_FRESH_INSTALL_GATE=PASS")
PY_FRESH_ENTRY

echo 'SMITE_CLEAN_RC_NGINX_PREREQUISITE_TESTS=PASS'
