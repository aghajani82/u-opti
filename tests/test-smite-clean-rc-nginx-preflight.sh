#!/usr/bin/env bash
# Offline test for Clean-RC Nginx package preparation; no host packages touched.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/modules/smite-install.sh"

SMITE_INSTALL_PROFILE=clean-rc
called=0
smite_gateway_ensure_packages() {
    called=$((called + 1))
    return 0
}
smite_install_clean_rc_nginx_paths_ready() { return 0; }
smite_install_pause() { :; }

read() {
    local variable="${!#}"
    printf -v "$variable" '%s' "${TEST_ANSWER:-y}"
    return 0
}

TEST_ANSWER=y
smite_install_clean_rc_prepare_gateway_packages
[ "$called" -eq 1 ]

TEST_ANSWER=n
if smite_install_clean_rc_prepare_gateway_packages; then
    echo "Expected explicit decline to hold." >&2
    exit 1
fi
[ "$called" -eq 1 ]

SMITE_INSTALL_PROFILE=stable
TEST_ANSWER=y
smite_install_clean_rc_prepare_gateway_packages
[ "$called" -eq 1 ]

echo 'SMITE_CLEAN_RC_NGINX_PREREQUISITE_TESTS=PASS'
