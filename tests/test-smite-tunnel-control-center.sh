#!/usr/bin/env bash
# Hermetic tests. All Docker/ss commands are mocked; no real hosts contacted.
set -euo pipefail
cd "$(dirname "$0")/.."

bash -n modules/smite-tunnel-control-center.sh
grep -Fq '"smite-tunnel-control-center.sh"' install.sh
grep -Fq '"smite-tunnel-control-center.sh"' u-opti
grep -Fq '["smite-tunnel-control-center.sh"]="$BASE_URL/modules/smite-tunnel-control-center.sh"' u-opti
grep -Fq '["smite-tunnel-control-center.sh"]="$TEMP_DIR/smite-tunnel-control-center.sh"' u-opti
grep -Fq "source \"\$SMITE_TW_DIR/smite-tunnel-control-center.sh\"" modules/smite-tunnel-wizard.sh
grep -Fq "4) Tunnel Control Center" modules/smite-tunnel-wizard.sh

# Standalone demo must not need Docker, ss or root; never leak real status.
preview="$(bash modules/smite-tunnel-control-center.sh --demo ir)"
grep -Fq 'SAMPLE DISPLAY ONLY' <<< "$preview"
grep -Fq 'BACKHAUL  [LOCAL-READY]' <<< "$preview"
grep -Fq 'NOTE: A real two-host client test' <<< "$preview"
preview="$(bash modules/smite-tunnel-control-center.sh --demo kh)"
grep -Fq 'KH Bridge' <<< "$preview"
if bash modules/smite-tunnel-control-center.sh --demo unknown >/dev/null 2>&1; then
    echo 'ERROR: invalid demo role accepted' >&2
    exit 1
fi

source modules/smite-tunnel-control-center.sh
TWCC_MODE=normal

docker() {
    [ "$1" = inspect ] || { echo "Unexpected mock Docker command" >&2; return 4; }
    if [ "$TWCC_MODE" = absent ] && [[ "$*" == *uopti-backhaul-sidecar-* ]]; then
        return 1
    fi
    if [ "$TWCC_MODE" = manual ] && [[ "$*" == *uopti-backhaul-sidecar-* ]]; then
        printf 'true|no\n'
    else
        printf 'true|unless-stopped\n'
    fi
}

ss() {
    local port
    case "$*" in
        *:7000*) port=7000 ;;
        *:3080*) port=3080 ;;
        *:56053*) port=56053 ;;
        *:13080*) port=13080 ;;
        *) echo "Unexpected mock listener request" >&2; return 3 ;;
    esac
    if [ "$TWCC_MODE" = absent ] && [ "$port" != 56053 ] && [ "$port" != 7000 ]; then
        return 0
    fi
    if [ "$TWCC_MODE" = unavailable ]; then
        return 1
    fi
    if [ "$TWCC_MODE" = public ] && [ "$port" = 13080 ]; then
        printf 'LISTEN 0 511 0.0.0.0:%s 0.0.0.0:*\n' "$port"
    else
        printf 'LISTEN 0 511 127.0.0.1:%s 0.0.0.0:*\n' "$port"
    fi
}

test "$(twcc_backhaul ir)" = LOCAL-READY
test "$(twcc_backhaul kh)" = LOCAL-READY
test "$(twcc_frp ir)" = IR-CONTROLLER-SEEN
test "$(twcc_frp kh)" = SMITE-NODE-SEEN
out="$(twcc_dashboard ir live)"
grep -Fq 'Snapshot of LOCAL metadata only' <<< "$out"
grep -Fq 'BACKHAUL  [LOCAL-READY]' <<< "$out"
grep -Fq 'FRP       [IR-CONTROLLER-SEEN]' <<< "$out"
grep -Fq 'RATHOLE   [PLAN-ONLY]' <<< "$out"
grep -Fq 'HTTP 401/400 is NOT proof' <<< "$out"

TWCC_MODE=public
test "$(twcc_backhaul kh)" = REVIEW-BINDING
out="$(twcc_dashboard kh live)"
grep -Fq 'HOLD: Unexpected listener exposure' <<< "$out"
grep -Fq 'Keep public /13080 forwarding blocked' <<< "$out"

TWCC_MODE=manual
test "$(twcc_backhaul ir)" = NEEDS-REVIEW

TWCC_MODE=absent
test "$(twcc_backhaul ir)" = NOT-INSTALLED
test "$(twcc_backhaul kh)" = NOT-INSTALLED

TWCC_MODE=unavailable
test "$(twcc_backhaul ir)" = UNVERIFIED

TWCC_MODE=normal
twcc_open_backhaul() { echo "BACKHAUL_MENU:$1"; }
twcc_open_frp() { echo "FRP_WIZARD"; }
twcc_open_rathole() { echo "RATHOLE_MENU:$1"; }
out="$(printf '1\n2\n3\n4\n0\n' | twcc_menu kh)"
grep -Fq 'BACKHAUL_MENU:kh' <<< "$out"
grep -Fq FRP_WIZARD <<< "$out"
grep -Fq 'RATHOLE_MENU:kh' <<< "$out"
if twcc_menu bogus <<< '0' >/dev/null 2>&1; then
    echo 'ERROR: invalid center role accepted' >&2
    exit 1
fi

# This module must not install, change firewall, reload Nginx, or read secrets.
if grep -Eq 'docker (run|update|stop|rm)|systemctl (reload|restart|stop)|nginx -s reload|cat .*\.token|cat .*\.toml|curl .*--insecure' modules/smite-tunnel-control-center.sh; then
    echo 'ERROR: control-center source contains destructive command' >&2
    exit 1
fi
echo 'PASS: read-only Tunnel Control Center local status, safe recommendations, demo and navigation'
