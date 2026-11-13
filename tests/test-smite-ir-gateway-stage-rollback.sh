#!/usr/bin/env bash
# Disposable, root-only fault injection. NEVER touches host Nginx/Docker.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
source "$ROOT/modules/smite-install.sh"
source "$ROOT/modules/smite-gateway.sh"

PROJECT="uopti_rc6_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DOMAIN="panel.example.org"
SMITE_GATEWAY_IR_STAGE_ROOT="$TMP/journal"
SMITE_GATEWAY_ACME_CONF_DIR="$TMP/etc/nginx/conf.d"
SMITE_PANEL_DIR="$TMP/opt/smite"
SMITE_NODE_DIR="$TMP/opt/smite-node"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
SMITE_GATEWAY_BACKEND_CONF="$TMP/etc/nginx/backend.conf"
SMITE_GATEWAY_STREAM_CONF="$TMP/etc/nginx/stream.conf"
SMITE_GATEWAY_MAP_FILE="$TMP/etc/nginx/map.conf"
SMITE_GATEWAY_FRP_SNI_MAP_FILE="$TMP/etc/nginx/frp-sni.conf"
SMITE_GATEWAY_STATE_FILE="$TMP/etc/u-opti/smite/gateway.env"
SMITE_GATEWAY_RENEW_HOOK="$TMP/etc/renew/deploy/reload"
mkdir -p "$SMITE_GATEWAY_IR_STAGE_ROOT" \
    "$(dirname "$SMITE_GATEWAY_BACKEND_CONF")" \
    "$SMITE_GATEWAY_ACME_CONF_DIR" \
    "$(dirname "$SMITE_GATEWAY_RENEW_HOOK")" \
    "$(dirname "$SMITE_GATEWAY_STATE_FILE")" "$SMITE_NODE_DIR"
chmod 0700 "$SMITE_GATEWAY_IR_STAGE_ROOT"
printf 'COMPOSE=original\n' > "$SMITE_NODE_COMPOSE"
printf 'backend=original\n' > "$SMITE_GATEWAY_BACKEND_CONF"
printf 'frp-preserve=original\n' > "$SMITE_GATEWAY_FRP_SNI_MAP_FILE"
printf 'PANEL_ADDRESS=panel.example.org:8000\nSMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_AGENT_AUTH_MODE=strict\n' > "$SMITE_NODE_DIR/.env"
chmod 0600 "$SMITE_NODE_DIR/.env"
BACKUP_BACKEND="$(cat "$SMITE_GATEWAY_BACKEND_CONF")"
BACKUP_FRP="$(cat "$SMITE_GATEWAY_FRP_SNI_MAP_FILE")"
BACKUP_ENV="$(cat "$SMITE_NODE_DIR/.env")"
NODE_RUNTIME_ADDRESS="panel.example.org:8000"
NODE_AUTH="paused"
NODE_RUNNING=1
FAIL_RELOAD=0
FAIL_STAGE=""
IR_PHASE="CORE_COMMITTED"
SMITE_IR_RESUMABLE=1
COMPOSE_PROJECT_NAME="$PROJECT"
EVENTS="$TMP/events"
: > "$EVENTS"

# These mocks make it impossible to call real Docker/Nginx/systemctl.
smite_gateway_node_compose_project() { printf '%s\n' "$PROJECT"; }
smite_gateway_container_healthy() { [ "$NODE_RUNNING" = 1 ]; }
smite_gateway_wait_healthy() { [ "$NODE_RUNNING" = 1 ]; }
smite_gateway_panel_domain() { printf '%s\n' "$DOMAIN"; }
docker() {
    if [ "$1" = inspect ]; then
        printf '%s\n' "SMITE_NODE_PANEL_AUTH_MODE=$NODE_AUTH" \
            'SMITE_AGENT_AUTH_MODE=strict' \
            "PANEL_ADDRESS=$NODE_RUNTIME_ADDRESS"
    elif [ "$1" = compose ]; then
        printf '%s\n' 'docker-compose-same-project' >> "$EVENTS"
        [ "$NODE_AUTH" = paused ] || return 1
        NODE_RUNTIME_ADDRESS="$(sed -n 's/^PANEL_ADDRESS=//p' "$SMITE_NODE_DIR/.env")"
        NODE_RUNNING=1
    else
        return 1
    fi
}
nginx() { echo nginx-check >> "$EVENTS"; [ "$FAIL_RELOAD" = 0 ]; }
systemctl() { echo nginx-reload >> "$EVENTS"; [ "$FAIL_RELOAD" = 0 ]; }

SNAPSHOT="$SMITE_GATEWAY_IR_STAGE_ROOT/gateway-$PROJECT"
reset_baseline() {
    printf 'backend=original\n' > "$SMITE_GATEWAY_BACKEND_CONF"
    printf 'frp-preserve=original\n' > "$SMITE_GATEWAY_FRP_SNI_MAP_FILE"
    printf 'PANEL_ADDRESS=panel.example.org:8000\nSMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_AGENT_AUTH_MODE=strict\n' > "$SMITE_NODE_DIR/.env"
    chmod 0600 "$SMITE_NODE_DIR/.env"
    rm -f "$SMITE_GATEWAY_STREAM_CONF" "$SMITE_GATEWAY_MAP_FILE" \
        "$SMITE_GATEWAY_STATE_FILE" "$SMITE_GATEWAY_RENEW_HOOK" \
        "$SMITE_GATEWAY_ACME_CONF_DIR/u-opti-acme-$DOMAIN.conf"
    NODE_RUNTIME_ADDRESS="panel.example.org:8000"
    NODE_AUTH=paused
    NODE_RUNNING=1
    IR_PHASE=CORE_COMMITTED
}
verify_baseline() {
    [ "$(cat "$SMITE_GATEWAY_BACKEND_CONF")" = "$BACKUP_BACKEND" ]
    [ "$(cat "$SMITE_GATEWAY_FRP_SNI_MAP_FILE")" = "$BACKUP_FRP" ]
    [ "$(cat "$SMITE_NODE_DIR/.env")" = "$BACKUP_ENV" ]
    [ "$(stat -c %a "$SMITE_NODE_DIR/.env")" = 600 ]
    [ "$NODE_RUNTIME_ADDRESS" = "panel.example.org:8000" ]
    for path in "$SMITE_GATEWAY_STREAM_CONF" "$SMITE_GATEWAY_MAP_FILE" \
         "$SMITE_GATEWAY_STATE_FILE" "$SMITE_GATEWAY_RENEW_HOOK" \
         "$SMITE_GATEWAY_ACME_CONF_DIR/u-opti-acme-$DOMAIN.conf"; do
        [ ! -e "$path" ]
    done
}
inject_partial_gateway() {
    printf 'backend=partial\n' > "$SMITE_GATEWAY_BACKEND_CONF"
    printf 'frp-preserve=partial\n' > "$SMITE_GATEWAY_FRP_SNI_MAP_FILE"
    printf 'partial\n' > "$SMITE_GATEWAY_STREAM_CONF"
    printf 'partial\n' > "$SMITE_GATEWAY_MAP_FILE"
    printf 'partial\n' > "$SMITE_GATEWAY_STATE_FILE"
    printf 'partial\n' > "$SMITE_GATEWAY_RENEW_HOOK"
    printf 'partial\n' > "$SMITE_GATEWAY_ACME_CONF_DIR/u-opti-acme-$DOMAIN.conf"
    printf 'PANEL_ADDRESS=panel.example.org:443\nSMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_AGENT_AUTH_MODE=strict\n' > "$SMITE_NODE_DIR/.env"
    chmod 0600 "$SMITE_NODE_DIR/.env"
    NODE_RUNTIME_ADDRESS="panel.example.org:443"
}

# The ENTIRE stage snapshot survives an error and restores original bytes,
# file presence, modes, Nginx and paused original Compose owner.
smite_gateway_ir_stage_snapshot "$SNAPSHOT" "$PROJECT" "$DOMAIN" > "$TMP/start"
[ -d "$SNAPSHOT" ]
inject_partial_gateway
smite_gateway_ir_stage_restore "$SNAPSHOT" "$PROJECT" "$DOMAIN" > "$TMP/restore"
grep -qx 'IR_GATEWAY_STAGE=ROLLED_BACK_VERIFIED' "$TMP/restore"
verify_baseline
grep -qx 'docker-compose-same-project' "$EVENTS"
smite_gateway_ir_stage_discard "$SNAPSHOT" "$PROJECT" "$DOMAIN"
[ ! -e "$SNAPSHOT" ]

# If signed enrollment occurred out of band, rollback must REFUSE before
# any file can be overwritten and must leave the snapshot for review.
smite_gateway_ir_stage_snapshot "$SNAPSHOT" "$PROJECT" "$DOMAIN" >/dev/null
inject_partial_gateway
NODE_AUTH=signed
if smite_gateway_ir_stage_restore "$SNAPSHOT" "$PROJECT" "$DOMAIN"; then
    echo 'FAIL: signed Node state was overwritten by Gateway rollback'; exit 1
fi
[ "$(cat "$SMITE_GATEWAY_BACKEND_CONF")" = backend=partial ]
[ -d "$SNAPSHOT" ]
NODE_AUTH=paused
smite_gateway_ir_stage_restore "$SNAPSHOT" "$PROJECT" "$DOMAIN" >/dev/null
smite_gateway_ir_stage_discard "$SNAPSHOT" "$PROJECT" "$DOMAIN"
verify_baseline

# Failed Nginx reload is NEVER called a successful rollback. Retain same
# snapshot; second attempt with recovered Nginx completes without new menu.
smite_gateway_ir_stage_snapshot "$SNAPSHOT" "$PROJECT" "$DOMAIN" >/dev/null
inject_partial_gateway
FAIL_RELOAD=1
if smite_gateway_ir_stage_restore "$SNAPSHOT" "$PROJECT" "$DOMAIN"; then
    echo 'FAIL: failed Nginx reload was accepted'; exit 1
fi
[ -d "$SNAPSHOT" ]
FAIL_RELOAD=0
smite_gateway_ir_stage_restore "$SNAPSHOT" "$PROJECT" "$DOMAIN" >/dev/null
smite_gateway_ir_stage_discard "$SNAPSHOT" "$PROJECT" "$DOMAIN"
verify_baseline

# Tampered snapshot ownership/identity must HOLD with NO overwrite.
smite_gateway_ir_stage_snapshot "$SNAPSHOT" "$PROJECT" "$DOMAIN" >/dev/null
inject_partial_gateway
if smite_gateway_ir_stage_restore "$SNAPSHOT" "uopti_rc6_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" "$DOMAIN"; then
    echo 'FAIL: foreign project adopted Gateway snapshot'; exit 1
fi
[ "$(cat "$SMITE_GATEWAY_BACKEND_CONF")" = backend=partial ]
smite_gateway_ir_stage_restore "$SNAPSHOT" "$PROJECT" "$DOMAIN" >/dev/null
smite_gateway_ir_stage_discard "$SNAPSHOT" "$PROJECT" "$DOMAIN"

# Exercise real option-1 Gateway stage wrapper with errors in the middle,
# at the final verification and at the journal advance boundary.
smite_gateway_configure_panel() {
    echo gateway >> "$EVENTS"
    inject_partial_gateway
    [ "$FAIL_STAGE" != middle ]
}
smite_gateway_verify_443() {
    echo tls >> "$EVENTS"
    [ "$FAIL_STAGE" != final ]
}
smite_install_ir_advance() {
    echo checkpoint >> "$EVENTS"
    [ "$FAIL_STAGE" != checkpoint ] || return 2
    IR_PHASE="$1"
}
for FAIL_STAGE in middle final checkpoint; do
    reset_baseline
    : > "$EVENTS"
    if smite_install_ir_gateway_stage > "$TMP/stage-$FAIL_STAGE" 2>&1; then
        echo "FAIL: Gateway step accepted injected $FAIL_STAGE failure"; exit 1
    fi
    grep -qx 'IR_GATEWAY=ROLLED_BACK_RETRY_OPTION_1' "$TMP/stage-$FAIL_STAGE"
    verify_baseline
    [ "$IR_PHASE" = CORE_COMMITTED ]
    [ ! -e "$SNAPSHOT" ]
done

# If the rollback ITSELF fails, keep the private snapshot + stage cursor.
# The same option 1 recovers it before starting a clean Gateway attempt.
reset_baseline
FAIL_STAGE=middle
FAIL_RELOAD=1
if smite_install_ir_gateway_stage > "$TMP/critical" 2>&1; then
    echo 'FAIL: unrecoverable Gateway rollback wrongly succeeded'; exit 1
fi
[ -d "$SNAPSHOT" ]
[ "$IR_PHASE" = CORE_COMMITTED ]
grep -q 'CRITICAL: Iran Gateway could not be restored' "$TMP/critical"
FAIL_RELOAD=0
FAIL_STAGE=""
smite_install_ir_gateway_stage > "$TMP/recovered"
grep -qx 'IR_GATEWAY=COMPLETE' "$TMP/recovered"
[ "$IR_PHASE" = GATEWAY_VERIFIED ]
[ ! -e "$SNAPSHOT" ]
[ "$(cat "$SMITE_GATEWAY_BACKEND_CONF")" = backend=partial ]
echo 'IR_GATEWAY_STAGE_ROLLBACK_AND_SAME_OPTION_RETRY=PASS'
