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
ORIGINAL_SANAEI_FOREIGN="$(declare -f smite_install_sanaei_foreign)"

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

# Scoped exact RC9 Foreign takes the same existing Sanaei return paths.
# No additional menu, installer, or release/activation behavior is introduced.
SMITE_INSTALL_PROFILE=clean-rc
printf 'SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.9\nSMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06\n' > "$SMITE_STATE_FILE"
CALLS=0; MODE=already; check 0 1
CALLS=0; MODE=new; check 0 2
CALLS=0; MODE=not_attached; check 2 2
for bad in "SMITE_UPSTREAM_REF=$(printf '0%.0s' {1..40})" "SMITE_MANAGED_VERSION=2.0.0-rc.8"; do
    cp "$SMITE_STATE_FILE" "$TMP/good-rc9-state"
    if [[ "$bad" = SMITE_UPSTREAM_REF=* ]]; then
        sed -i "s/^SMITE_UPSTREAM_REF=.*/$bad/" "$SMITE_STATE_FILE"
    else
        sed -i "s/^SMITE_MANAGED_VERSION=.*/$bad/" "$SMITE_STATE_FILE"
    fi
    CALLS=0; MODE=already; check 2 0
    mv "$TMP/good-rc9-state" "$SMITE_STATE_FILE"
done
sed -i '/^SMITE_UPSTREAM_REF=/d' "$SMITE_STATE_FILE"
CALLS=0; MODE=already; check 2 0
printf 'SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.9\nSMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06\n' > "$SMITE_STATE_FILE"

# Exercise the REAL existing Sanaei installer with a mocked fresh,
# paused, Compose-owned RC9 Node. The existing attachment stage has
# already been verified and may return without Docker recreate.
eval "$ORIGINAL_SANAEI_FOREIGN"
SMITE_SELECTED_FRESH=1
SMITE_INSTALL_PROFILE=clean-rc
UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER=1
SMITE_NODE_DIR="$TMP/rc9-node"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
mkdir -p "$SMITE_NODE_DIR"
printf 'services:\n  smite-node: {}\n' > "$SMITE_NODE_COMPOSE"
printf 'SMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_AGENT_AUTH_MODE=strict\n' > "$SMITE_NODE_DIR/.env"
OWNED_PROJECT="uopti_rc6_$(printf 'a%.0s' {1..32})"
DOCKER_CALLS=0
DOCKER_BAD_OWNER=0
docker() {
    DOCKER_CALLS=$((DOCKER_CALLS + 1))
    case "$*" in
        *com.docker.compose.project*) [ "$DOCKER_BAD_OWNER" != 1 ] && echo "$OWNED_PROJECT" || echo other ;;
        *com.docker.compose.service*) echo smite-node ;;
        *com.docker.compose.project.config_files*) printf '%s\n' "$SMITE_NODE_COMPOSE" ;;
        *'range .Config.Env'*) printf '%s\n' SMITE_NODE_PANEL_AUTH_MODE=paused SMITE_AGENT_AUTH_MODE=strict ;;
        *) echo "Unexpected Docker command" >&2; return 89 ;;
    esac
}
INSTANCE_INSTALLS=0
docker_3xui_install() { INSTANCE_INSTALLS=$((INSTANCE_INSTALLS + 1)); return 99; }
smite_install_sanaei_retained() { return 0; }
status=0
smite_install_sanaei_foreign > "$TMP/rc9-owned-result" 2>&1 || status=$?
[ "$status" -eq 0 ] && [ "$DOCKER_CALLS" -eq 3 ] &&
[ "$INSTANCE_INSTALLS" -eq 0 ] &&
grep -qx 'KH_SANAEI_INVENTORY=ALREADY_ATTACHED_VERIFIED' "$TMP/rc9-owned-result" || {
    cat "$TMP/rc9-owned-result"; echo "FAIL: exact RC9 original Sanaei stage not retained"; exit 1;
}
for unsafe in wrong_source missing_source missing_role wrong_compose standalone wrong_profile; do
    case "$unsafe" in
        wrong_source) sed -i 's/^SMITE_UPSTREAM_REF=.*/SMITE_UPSTREAM_REF=0000000000000000000000000000000000000000/' "$SMITE_STATE_FILE" ;;
        missing_source) sed -i '/^SMITE_UPSTREAM_REF=/d' "$SMITE_STATE_FILE" ;;
        missing_role) sed -i 's/^SMITE_ROLE=foreign/SMITE_ROLE=panel-iran/' "$SMITE_STATE_FILE" ;;
        wrong_compose) DOCKER_BAD_OWNER=1 ;;
        standalone) SMITE_SELECTED_FRESH=0 ;;
        wrong_profile) SMITE_INSTALL_PROFILE=stable ;;
    esac
    DOCKER_CALLS=0
    status=0
    smite_install_sanaei_foreign > "$TMP/rc9-hold" 2>&1 || status=$?
    [ "$status" -ne 0 ] && [ "$INSTANCE_INSTALLS" -eq 0 ] || {
        echo "FAIL: unsafe RC9 Sanaei $unsafe admitted original installer"; exit 1;
    }
    case "$unsafe" in
        wrong_source|missing_source) [ "$DOCKER_CALLS" -eq 0 ] || { echo "FAIL: RC9 $unsafe touched Docker"; exit 1; } ;;
    esac
    printf 'SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.9\nSMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06\n' > "$SMITE_STATE_FILE"
    DOCKER_BAD_OWNER=0
    SMITE_SELECTED_FRESH=1
    SMITE_INSTALL_PROFILE=clean-rc
done
echo 'FOREIGN_RC9_ORIGINAL_SANAEI_SCOPED_SOURCE_AND_OWNERSHIP=PASS'

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
