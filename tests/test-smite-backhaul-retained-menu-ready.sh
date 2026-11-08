#!/usr/bin/env bash
# Synthetic signed-status refusal regression. No Docker, Node, host writes
# beyond a disposable temporary test directory; no production access.
set -euo pipefail
cd "$(dirname "$0")/.."
work="$(mktemp -d -t uopti-bh-ready-menu-XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT
printf 'mock-control\n' > "$work/control"
printf 'mock-executor\n' > "$work/executor"
cat > "$work/python3" <<'SH'
#!/usr/bin/env bash
set -eu
if [ "$1" != -B ] || [ "$2" != "$UOPTI_RC7_TEST_CONTROL" ]; then
    echo "UNEXPECTED_EXECUTOR_CALL"
    exit 98
fi
[ "$3" = verify-rc7-bundle ]
[ "$4" = --auto-role ]
[ "$5" = --expect-backhaul-ready ]
if [ "$UOPTI_RC7_TEST_MODE" = missing ]; then
    echo 'HOLD: SIGNED_STATUS_UNVERIFIED' >&2
    exit 2
fi
printf '%s\n' \
    'RC7_BACKHAUL_ENGINE=READY_SIGNED_INVENTORY' \
    'RC7_FRP_ENGINE=READY_SIGNED_INVENTORY' \
    'RC7_BACKHAUL_MANIFEST_PLAN=COMMITTED_PAIR_VERIFIED_READ_ONLY' \
    'RC7_SIGNED_REPLAY=PASS' \
    'NODE_RECREATED=NO'
if [ "$UOPTI_RC7_TEST_ROLE" = foreign ]; then
    printf '%s\n' \
        'RC7_IR_SIGNED_FRPS_OWNER=NOT_APPLICABLE_FOREIGN' \
        'RC7_FOREIGN_LOCAL_SIGNED_FRPC_CHILDREN=PASS_STABLE_LOCAL_ONLY'
else
    printf '%s\n' \
        'RC7_IR_SIGNED_FRPS_OWNER=PASS_SIGNED_AGENT_LISTENER_STABLE'
fi
if [ "$UOPTI_RC7_TEST_MODE" = partial ]; then
    # Extra misleading lines are irrelevant: a negative/truncated witness
    # must never satisfy the entire trusted verification tuple.
    echo 'RC7_SIGNED_REPLAY=HOLD'
fi
SH
chmod 0700 "$work/python3"
export PATH="$work:$PATH"
export UOPTI_RC7_TEST_CONTROL="$work/control"
export UOPTI_RC7_TEST_EXECUTOR="$work/executor"
menu='source modules/smite-managed-backhaul-menu.sh
SMITE_MANAGED_BACKHAUL_CONTROL="$UOPTI_RC7_TEST_CONTROL"
SMITE_MANAGED_BACKHAUL_HOST_EXECUTOR="$UOPTI_RC7_TEST_EXECUTOR"
smite_managed_bh_ir_retained_canary'
export UOPTI_RC7_TEST_MODE=ready
export UOPTI_RC7_TEST_ROLE=foreign
out="$(printf 'F\n' | bash -c "$menu" || :)"
grep -Fq 'HOLD: RETAINED_FOREIGN_BACKHAUL_ALREADY_ENROLLED_SIGNED; no changes.' <<< "$out"
! grep -Fq 'Type SNAPSHOT-RESTORE' <<< "$out"
! grep -Fq 'UNEXPECTED_EXECUTOR_CALL' <<< "$out"

export UOPTI_RC7_TEST_ROLE=ir
out="$(printf 'I\n' | bash -c "$menu" || :)"
grep -Fq 'HOLD: RETAINED_IR_BACKHAUL_ALREADY_ENROLLED_SIGNED; no changes.' <<< "$out"
! grep -Fq 'UNEXPECTED_EXECUTOR_CALL' <<< "$out"

# If signed post-enrollment inventory is missing, do NOT trust the
# already-enrolled shortcut. The existing installer/recovery gates remain.
export UOPTI_RC7_TEST_MODE=missing
export UOPTI_RC7_TEST_ROLE=foreign
out="$(printf 'F\n' | bash -c "$menu" || :)"
grep -Fq 'Foreign live clients: independently tested isolated restore' <<< "$out"
! grep -Fq 'ALREADY_ENROLLED_SIGNED' <<< "$out"
export UOPTI_RC7_TEST_ROLE=ir
out="$(printf 'I\n' | bash -c "$menu" || :)"
grep -Fq 'UNEXPECTED_EXECUTOR_CALL' <<< "$out"
! grep -Fq 'ALREADY_ENROLLED_SIGNED' <<< "$out"

echo "PASS: signed already-enrolled refusal precedes confirmation; missing witness falls through existing gates"
