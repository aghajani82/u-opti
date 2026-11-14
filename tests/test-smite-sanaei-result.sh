#!/usr/bin/env bash
# Isolated return-code regression: no network, Docker, host configuration or DB.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
source "$ROOT/modules/smite-install.sh"
clear() { :; }
smite_install_pause() { :; }
SMITE_STATE_DIR="$TMP"
SMITE_STATE_FILE="$TMP/state.env"
SMITE_NODE_DIR="$TMP/node"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
mkdir -p "$SMITE_NODE_DIR" "$TMP/db"
printf 'fixture\n' > "$SMITE_NODE_COMPOSE"
printf 'fixture\n' > "$TMP/db/x-ui.db"
printf 'SMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_AGENT_AUTH_MODE=strict\n' > "$SMITE_NODE_DIR/.env"
cp "$SMITE_NODE_DIR/.env" "$TMP/original.env"
CASE=normal
docker() {
    case "$*" in
      *Config.Env*) printf 'SMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_AGENT_AUTH_MODE=strict\n' ;;
      'exec '*) [ "$CASE" != schema_failure ] ;;
      *) return 99 ;;
    esac
}
docker_3xui_install() { [ "$CASE" != install_failure ]; }
docker_3xui_load_instance() { [ "$CASE" != registry_failure ]; }
docker_3xui_instance_registered_ids() {
    case "$CASE" in empty|install_failure) ;; *) echo 01 ;; esac
}
docker_3xui_instance_load_state() { DOCKER_3XUI_INSTANCE_DIR="$TMP"; }
python3() {
    case "$*" in
      *smite-rc5-xhttp-sanaei-mount.py*) [ "$CASE" != mount_failure ] ;;
      *smite-compose-safe.py*) return 0 ;;
      *) return 99 ;;
    esac
}
smite_wait_healthy() { [ "$CASE" != health_failure ]; }
expect_result() {
    local expected="$1" result=0
    smite_install_sanaei_foreign > "$TMP/output" 2>&1 || result=$?
    if [ "$result" != "$expected" ]; then
        cat "$TMP/output"
        echo "FAIL: $CASE expected $expected, got $result"
        exit 1
    fi
    if [ "$expected" != 0 ]; then
        ! grep -q 'KH_SANAEI_INVENTORY=PASS_READ_ONLY_SCHEMA' "$TMP/output"
    fi
}
CASE=missing_state
expect_result 2
printf 'SMITE_ROLE=panel-iran\nSMITE_MANAGED_VERSION=2.0.0-rc.1\n' > "$SMITE_STATE_FILE"
CASE=wrong_role
expect_result 2
printf 'SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.1\n' > "$SMITE_STATE_FILE"
for CASE in registry_failure mount_failure schema_failure health_failure install_failure; do
    expect_result 2
    cmp "$SMITE_NODE_DIR/.env" "$TMP/original.env"
done
CASE=empty
expect_result 3
CASE=normal
expect_result 0
grep -qx 'KH_SANAEI_INVENTORY=PASS_READ_ONLY_SCHEMA' "$TMP/output"
# RC7 unowned Compose must fail before any attachment attempt.
printf 'SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.7\n' > "$SMITE_STATE_FILE"
CASE=unowned_rc7
expect_result 2
echo 'SANAEI_RESULT_CONTRACT=PASS (10 scenarios)'

# Exercise the retained inventory check with all paths inside the fixture.
sed "s@\^/opt/3x-ui/instances/@^$TMP/instances/@" "$ROOT/modules/smite-install.sh" > "$TMP/fixture-installer.sh"
source "$TMP/fixture-installer.sh"
mkdir -p "$TMP/instances/07/db"
printf 'fixture\n' > "$TMP/instances/07/db/x-ui.db"
source_db="$TMP/instances/07/db"
runtime_flag=true
mount_mode=false
docker() {
    case "$*" in
        *Config.Env*) printf 'SMITE_SANAEI_INVENTORY_ENABLED=%s\n' "$runtime_flag" ;;
        *Mounts*) printf 'bind %s %s\n' "$source_db" "$mount_mode" ;;
        'exec '*) [ "$CASE" != schema_failure ] ;;
        *) return 99 ;;
    esac
}
printf 'SMITE_SANAEI_INVENTORY_ENABLED=true\nSMITE_SANAEI_DB_HOST_PATH=%s\n' "$source_db" > "$SMITE_NODE_DIR/.env"
CASE=normal
smite_install_sanaei_retained
for CASE in schema_failure writable_mount; do
    if [ "$CASE" = writable_mount ]; then mount_mode=true; fi
    result=0
    smite_install_sanaei_retained || result=$?
    [ "$result" = 2 ]
done
mount_mode=false
runtime_flag=false
source_db="$SMITE_NODE_DIR/.sanaei-empty"
printf 'SMITE_SANAEI_INVENTORY_ENABLED=false\nSMITE_SANAEI_DB_HOST_PATH=%s\n' "$source_db" > "$SMITE_NODE_DIR/.env"
result=0
smite_install_sanaei_retained || result=$?
[ "$result" = 3 ]
echo 'SANAEI_RETAINED_READ_ONLY_ATTACHMENT=PASS'

project=uopti_rc6_0123456789abcdef0123456789abcdef
chmod 0600 "$SMITE_NODE_DIR/.env"
pending="$SMITE_NODE_DIR/.sanaei-attachment.pending"
cp "$SMITE_NODE_DIR/.env" "$TMP/baseline"
smite_install_sanaei_retained() {
    if grep -qx 'SMITE_SANAEI_INVENTORY_ENABLED=false' "$SMITE_NODE_DIR/.env"; then
        return 3
    fi
    [ "$CASE" = applied ]
}
python3() {
    case "$*" in
        *smite-rc5-xhttp-sanaei-mount.py*)
            sed -i 's/INVENTORY_ENABLED=false/INVENTORY_ENABLED=true/' "$6"
            ;;
        *smite-compose-safe.py*)
            if [ "$CASE" = interrupted ]; then exit 77; fi
            ;;
        *) return 99 ;;
    esac
}
CASE=interrupted
result=0
smite_install_sanaei_attachment_stage "$project" 07 || result=$?
[ "$result" = 77 ]
[ -f "$pending/before" ]
grep -qx 'SMITE_SANAEI_INVENTORY_ENABLED=true' "$SMITE_NODE_DIR/.env"
printf 'INDEPENDENT_EDIT=true\n' >> "$SMITE_NODE_DIR/.env"
CASE=rollback
result=0
smite_install_sanaei_attachment_stage "$project" || result=$?
[ "$result" = 2 ]
grep -qx 'INDEPENDENT_EDIT=true' "$SMITE_NODE_DIR/.env"
cp -a "$pending/after" "$SMITE_NODE_DIR/.env"
result=0
smite_install_sanaei_attachment_stage "$project" || result=$?
[ "$result" = 3 ]
cmp "$TMP/baseline" "$SMITE_NODE_DIR/.env"
[ ! -e "$pending" ]
CASE=applied
smite_install_sanaei_attachment_stage "$project" 07
[ ! -e "$pending" ]
grep -qx 'SMITE_SANAEI_INVENTORY_ENABLED=true' "$SMITE_NODE_DIR/.env"
echo 'SANAEI_ATTACHMENT_RECOVERY_AND_RETRY=PASS'
