#!/usr/bin/env bash
# Isolated one-choice Smite Foreign Sanaei continuation contract.
# No services, Docker, Nginx, certificates or host paths are changed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

bash -n "$ROOT/modules/docker-3xui.sh"
bash -n "$ROOT/modules/smite-install.sh"
source "$ROOT/modules/smite-install.sh"

# Exercise the ACTUAL pre-existing Sanaei menu/pause functions before
# replacing the slow installer with isolated mocks. An owned option-2 call
# must not clear the progress log or ask to return to a menu mid-install.
CLEARS=0 READS=0
clear() { CLEARS=$((CLEARS + 1)); }
read() { READS=$((READS + 1)); return 0; }
SMITE_STATE_FILE="$TMP/not-installed-yet.env"
SMITE_SELECTED_FRESH=1
UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER=1
status=0
smite_install_sanaei_foreign > "$TMP/scoped-pause.log" 2>&1 || status=$?
[ "$status" -eq 2 ] && [ "$CLEARS" -eq 0 ] && [ "$READS" -eq 0 ] || {
    echo "FAIL: scoped Sanaei failure must HOLD without clearing/prompting"; exit 1;
}
smite_install_pause
[ "$READS" -eq 0 ] || { echo "FAIL: scoped option-2 paused unexpectedly"; exit 1; }

# Standalone option 4 keeps the original clear and return prompt.
unset UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER
status=0
smite_install_sanaei_foreign > "$TMP/standalone-pause.log" 2>&1 || status=$?
[ "$status" -eq 2 ] && [ "$CLEARS" -eq 1 ] && [ "$READS" -eq 1 ] || {
    echo "FAIL: ordinary Sanaei menu interaction changed"; exit 1;
}
# A flag alone on a NONFRESH transaction must not suppress the menu.
SMITE_SELECTED_FRESH=0 UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER=1 smite_install_pause
[ "$READS" -eq 2 ] || { echo "FAIL: nonfresh menu pause suppressed"; exit 1; }
unset -f read clear

SMITE_STATE_FILE="$TMP/state.env"
SMITE_SELECTED_FRESH=1
printf 'SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.7\n' > "$SMITE_STATE_FILE"
smite_install_pause() { :; }

CALLS=0
MODE="already"
smite_install_sanaei_foreign() {
    CALLS=$((CALLS + 1))
    [ "${UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER:-0}" = 1 ] || return 98
    case "$MODE:$CALLS" in
        already:1|new:2) return 0 ;;
        new:1|not_attached:1) return 3 ;;
        not_attached:2|failed:1) return 2 ;;
        unknown:1) return 17 ;;
        *) return 99 ;;
    esac
}
check() {
    local expected="$1" calls="$2" result=0
    smite_install_unified_foreign_sanaei > "$TMP/result.log" 2>&1 || result=$?
    if [ "$result" -ne "$expected" ] || [ "$CALLS" -ne "$calls" ]; then
        cat "$TMP/result.log"
        echo "FAIL: $MODE result=$result calls=$CALLS expected=$expected/$calls"
        exit 1
    fi
    if [ "$result" -eq 0 ]; then
        grep -qx 'UNIFIED_FOREIGN_SANAEI=PASS_ATTACHED_READ_ONLY' "$TMP/result.log"
    else
        ! grep -q 'UNIFIED_FOREIGN_SANAEI=PASS_ATTACHED_READ_ONLY' "$TMP/result.log"
    fi
}
CALLS=0; MODE=already; check 0 1
CALLS=0; MODE=new; check 0 2
CALLS=0; MODE=not_attached; check 2 2
CALLS=0; MODE=failed; check 2 1
CALLS=0; MODE=unknown; check 2 1

SMITE_SELECTED_FRESH=0
CALLS=0; MODE=already; check 2 0
SMITE_SELECTED_FRESH=1
printf 'SMITE_ROLE=panel-iran\nSMITE_MANAGED_VERSION=2.0.0-rc.7\n' > "$SMITE_STATE_FILE"
CALLS=0; MODE=already; check 2 0
printf 'SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.6\n' > "$SMITE_STATE_FILE"
CALLS=0; MODE=already; check 2 0

# Verify the existing standalone Sanaei installer still ends with PTY reload,
# but the scoped unified path RETURNS before exec and before read/prompt.
python3 - "$ROOT/modules/docker-3xui.sh" <<'PY'
from pathlib import Path
import sys
code = Path(sys.argv[1]).read_text()
start = code.index('docker_3xui_install() {')
end = code.index('\ndocker_3xui_start() {', start)
body = code[start:end]
guard = 'if [ "${UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER:-0}" = 1 ]; then'
complete = 'SANAEI_INSTALL=COMPLETE_RETURN_TO_SMITE'
legacy = 'exec script -qefc "/usr/local/bin/u-opti --menu docker" /dev/null'
assert body.count(guard) == 1
assert body.count(complete) == 1
assert body.count(legacy) == 1
assert body.index(guard) < body.index('return 0', body.index(guard)) < body.index(legacy)
assert body.index(guard) > body.index('Installation completed successfully.')
PY

echo 'UNIFIED_SANAEI_RETURN_AND_ATTACHMENT=PASS (11 scenarios)'
