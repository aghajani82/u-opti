#!/usr/bin/env bash
# Exercise the REAL option-1 schema stage against a mock Docker command.
# Zero container/DB/Gateway/FRP/network changes; no secret contents read.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
source "$ROOT/modules/smite-install.sh"
SMITE_STATE_FILE="$TMP/state.env"
SMITE_IR_RESUMABLE=1
cat > "$SMITE_STATE_FILE" <<'STATE'
SMITE_ROLE=panel-iran
SMITE_CONNECTION_MODE=standard
SMITE_MANAGED_VERSION=2.0.0-rc.9
SMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06
STATE
chmod 0600 "$SMITE_STATE_FILE"
docker() {
    printf '%s\n' "$*" >> "$TMP/calls"
    case "$*" in
        'exec smite-panel python3 -B -m app.foreign_install_migration --review')
            if [ "${BAD_REVIEW:-0}" = 1 ]; then
                printf 'FOREIGN_INSTALL_SCHEMA=HOLD\nFOREIGN_INSTALL_FLAGS=UNCHANGED\nRUNTIME_AND_GATEWAY=UNCHANGED\n'
            elif [ -f "$TMP/ready" ]; then
                printf 'FOREIGN_INSTALL_SCHEMA=READY\nFOREIGN_INSTALL_FLAGS=UNCHANGED\nRUNTIME_AND_GATEWAY=UNCHANGED\n'
            else
                printf 'FOREIGN_INSTALL_SCHEMA=MISSING\nFOREIGN_INSTALL_FLAGS=UNCHANGED\nRUNTIME_AND_GATEWAY=UNCHANGED\n'
            fi ;;
        'exec smite-panel python3 -B -m app.foreign_install_migration --migrate --confirm PREPARE-FOREIGN-INSTALL-TRIAL-SCHEMA')
            [ "${FAIL_MIGRATE:-0}" != 1 ] || return 2
            touch "$TMP/ready"
            if [ "${BAD_RECEIPT:-0}" = 1 ]; then
                echo 'INVALID_RECEIPT'
            else
                printf 'FOREIGN_INSTALL_SCHEMA=READY\nFOREIGN_INSTALL_FLAGS=UNCHANGED\nRUNTIME_AND_GATEWAY=UNCHANGED\n'
            fi ;;
        *) echo 'FAIL: unexpected Docker call' >&2; return 77 ;;
    esac
}
python3() {
    if [[ "$*" == *"smite-node-pairing.py --complete-local-ir-foreign" ]]; then
        echo foreign-ready >> "$TMP/calls"
        [ "${FAIL_FOREIGN_443:-0}" != 1 ] || return 2
        echo 'IR_FOREIGN_INSTALL=READY_SIGNED_443'
    else
        command python3 "$@"
    fi
}
: > "$TMP/calls"
smite_install_ir_foreign_schema_stage > "$TMP/first"
grep -qx 'IR_FOREIGN_SCHEMA=READY' "$TMP/first"
grep -qx 'IR_FOREIGN_FLAGS=ENABLED_SIGNED_443' "$TMP/first"
grep -qx 'IR_FOREIGN_INSTALL=VERIFIED_READY_FOR_NODE_RESERVATION' "$TMP/first"
[ -f "$TMP/ready" ]
[ "$(grep -c -- '--migrate' "$TMP/calls")" = 1 ]
[ "$(grep -c -- '--review' "$TMP/calls")" = 2 ]
: > "$TMP/calls"
smite_install_ir_foreign_schema_stage > "$TMP/second"
[ "$(grep -c -- '--review' "$TMP/calls")" = 2 ]
! grep -q -- '--migrate' "$TMP/calls"
grep -qx 'IR_FOREIGN_SCHEMA=VERIFIED_RETAINED' "$TMP/second"
[ "$(grep -c '^foreign-readyfor line in 'SMITE_ROLE=foreign' 'SMITE_MANAGED_VERSION=2.0.0-rc.7' \
            'SMITE_UPSTREAM_REF=0000000000000000000000000000000000000000'; do
    cp "$SMITE_STATE_FILE" "$TMP/backup-state"
    key="${line%%=*}"
    sed -i "s/^$key=.*/$line/" "$SMITE_STATE_FILE"
    : > "$TMP/calls"
    if smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then
        echo 'FAIL: untrusted source/role accepted' >&2; exit 1
    fi
    [ ! -s "$TMP/calls" ]
    mv "$TMP/backup-state" "$SMITE_STATE_FILE"
done
ln -s "$SMITE_STATE_FILE" "$TMP/link.env"
SMITE_STATE_FILE="$TMP/link.env"
: > "$TMP/calls"
if smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
[ ! -s "$TMP/calls" ]
SMITE_STATE_FILE="$TMP/state.env"
: > "$TMP/calls"
if BAD_REVIEW=1 smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
! grep -q -- '--migrate' "$TMP/calls"
rm -f "$TMP/ready"
: > "$TMP/calls"
if FAIL_MIGRATE=1 smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
[ ! -f "$TMP/ready" ]
: > "$TMP/calls"
if BAD_RECEIPT=1 smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
[ -f "$TMP/ready" ]
: > "$TMP/calls"
smite_install_ir_foreign_schema_stage > "$TMP/retry"
! grep -q -- '--migrate' "$TMP/calls"
grep -qx 'IR_FOREIGN_SCHEMA=READY' "$TMP/retry"
echo 'IR_OPTION_1_RC9_FOREIGN_SCHEMA_AND_SIGNED_443=PASS_ISOLATED_RETRY_AND_HOLD'
 "$TMP/calls")" = 1 ]
: > "$TMP/calls"
if FAIL_FOREIGN_443=1 smite_install_ir_foreign_schema_stage > "$TMP/blocked" 2>&1; then
    echo 'FAIL: post-schema ingress rejection swallowed' >&2
    exit 1
fi
! grep -q -- '--migrate' "$TMP/calls"
[ "$(grep -c '^foreign-readyfor line in 'SMITE_ROLE=foreign' 'SMITE_MANAGED_VERSION=2.0.0-rc.7' \
            'SMITE_UPSTREAM_REF=0000000000000000000000000000000000000000'; do
    cp "$SMITE_STATE_FILE" "$TMP/backup-state"
    key="${line%%=*}"
    sed -i "s/^$key=.*/$line/" "$SMITE_STATE_FILE"
    : > "$TMP/calls"
    if smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then
        echo 'FAIL: untrusted source/role accepted' >&2; exit 1
    fi
    [ ! -s "$TMP/calls" ]
    mv "$TMP/backup-state" "$SMITE_STATE_FILE"
done
ln -s "$SMITE_STATE_FILE" "$TMP/link.env"
SMITE_STATE_FILE="$TMP/link.env"
: > "$TMP/calls"
if smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
[ ! -s "$TMP/calls" ]
SMITE_STATE_FILE="$TMP/state.env"
: > "$TMP/calls"
if BAD_REVIEW=1 smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
! grep -q -- '--migrate' "$TMP/calls"
rm -f "$TMP/ready"
: > "$TMP/calls"
if FAIL_MIGRATE=1 smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
[ ! -f "$TMP/ready" ]
: > "$TMP/calls"
if BAD_RECEIPT=1 smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
[ -f "$TMP/ready" ]
: > "$TMP/calls"
smite_install_ir_foreign_schema_stage > "$TMP/retry"
! grep -q -- '--migrate' "$TMP/calls"
grep -qx 'IR_FOREIGN_SCHEMA=READY' "$TMP/retry"
echo 'IR_OPTION_1_RC9_FOREIGN_SCHEMA=PASS_ISOLATED_RETRY_AND_FLAGS_UNCHANGED'
 "$TMP/calls")" = 1 ]
! grep -q 'IR_FOREIGN_FLAGS=ENABLED_SIGNED_443' "$TMP/blocked"
for line in 'SMITE_ROLE=foreign' 'SMITE_MANAGED_VERSION=2.0.0-rc.7' \
            'SMITE_UPSTREAM_REF=0000000000000000000000000000000000000000'; do
    cp "$SMITE_STATE_FILE" "$TMP/backup-state"
    key="${line%%=*}"
    sed -i "s/^$key=.*/$line/" "$SMITE_STATE_FILE"
    : > "$TMP/calls"
    if smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then
        echo 'FAIL: untrusted source/role accepted' >&2; exit 1
    fi
    [ ! -s "$TMP/calls" ]
    mv "$TMP/backup-state" "$SMITE_STATE_FILE"
done
ln -s "$SMITE_STATE_FILE" "$TMP/link.env"
SMITE_STATE_FILE="$TMP/link.env"
: > "$TMP/calls"
if smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
[ ! -s "$TMP/calls" ]
SMITE_STATE_FILE="$TMP/state.env"
: > "$TMP/calls"
if BAD_REVIEW=1 smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
! grep -q -- '--migrate' "$TMP/calls"
rm -f "$TMP/ready"
: > "$TMP/calls"
if FAIL_MIGRATE=1 smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
[ ! -f "$TMP/ready" ]
: > "$TMP/calls"
if BAD_RECEIPT=1 smite_install_ir_foreign_schema_stage >/dev/null 2>&1; then exit 1; fi
[ -f "$TMP/ready" ]
: > "$TMP/calls"
smite_install_ir_foreign_schema_stage > "$TMP/retry"
! grep -q -- '--migrate' "$TMP/calls"
grep -qx 'IR_FOREIGN_SCHEMA=READY' "$TMP/retry"
echo 'IR_OPTION_1_RC9_FOREIGN_SCHEMA=PASS_ISOLATED_RETRY_AND_FLAGS_UNCHANGED'
