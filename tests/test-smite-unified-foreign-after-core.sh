#!/usr/bin/env bash
# One-choice Foreign option-2 post-core choreography, offline only.
# No Docker, network, TLS, certificate issuance, Nginx or host writes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SMITE_STATE_DIR="$TMP/state"
SMITE_STATE_FILE="$SMITE_STATE_DIR/state.env"
SMITE_NODE_DIR="$TMP/node"
mkdir -p "$SMITE_STATE_DIR/staging" "$SMITE_NODE_DIR"
chmod 0700 "$SMITE_STATE_DIR" "$SMITE_STATE_DIR/staging"
cat > "$SMITE_STATE_FILE" <<'STATE'
SMITE_ROLE=foreign
SMITE_MANAGED_VERSION=2.0.0-rc.7
SMITE_CONNECTION_MODE=standard
SMITE_PANEL_DOMAIN=iran.example.org
SMITE_FOREIGN_DOMAIN=kh.example.org
SMITE_NODE_NAME=node-kh
STATE
chmod 0600 "$SMITE_STATE_FILE"
PACKET="$SMITE_STATE_DIR/staging/foreign-install-packet.json"
python3 - "$PACKET" <<'PY'
import json,sys
packet={
  "protocol":"smi1",
  "panel_url":"https://iran.example.org:443",
  "node_id":"foreign-node-0001",
  "node_name":"node-kh",
  "origin":"https://kh.example.org:443",
  "control_url":"https://kh.example.org:443/smite-node/"+"a"*32,
  "installation_code":"smi1_"+"B"*43,
  "expires_at":1799999999,
}
with open(sys.argv[1],"w") as handle:json.dump(packet,handle)
PY
chmod 0600 "$PACKET"

source "$ROOT/modules/smite-install.sh"
source "$ROOT/modules/smite-foreign-gateway.sh"
# Preserve the ACTUAL release admission before replacing it with a scoped
# rehearsal success/failure stub. Only the mock may reach Sanaei/Gateway.
REAL_UNIFIED_RELEASE_REVIEW="$(declare -f smite_install_unified_signed_pair_review)"
[[ "$REAL_UNIFIED_RELEASE_REVIEW" == *'pairing._require_unified_foreign_release()'* ]]

SMITE_INSTALL_PROFILE=clean-rc
SMITE_SELECTED_FRESH=1
MODE=ok
calls=()
smite_install_unified_signed_pair_review() {
    calls+=(signed)
    [ "$MODE" != bad_signature ]
}
NODE_ID="sha256:$(printf 'd%.0s' {1..64})"
docker() {
    case "$*" in
        'inspect -f {{.Config.Image}} smite-node')
            if [ "$MODE" = wrong_image ] ||
               { [ "$MODE" = post_wrong_image ] && [ -f "$SMITE_STATE_DIR/foreign-gateway.env" ]; }; then
                echo 'ghcr.io/aghajani82/smite-node:latest'
            else
                echo 'ghcr.io/aghajani82/smite-node@sha256:587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483'
            fi
            ;;
        'inspect -f {{.Image}} smite-node')
            if [ "$MODE" = wrong_runtime_id ] ||
               { [ "$MODE" = post_wrong_runtime_id ] && [ -f "$SMITE_STATE_DIR/foreign-gateway.env" ]; }; then
                printf 'sha256:%064d\n' 0
            else
                printf '%s\n' "$NODE_ID"
            fi
            ;;
        'image inspect -f {{.Id}} ghcr.io/aghajani82/smite-node@sha256:587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483')
            printf '%s\n' "$NODE_ID"
            ;;
        *) return 99 ;;
    esac
}
smite_foreign_gateway_require_rc_paused() {
    calls+=(paused)
    [ "$MODE" != bad_paused ] && [ "$MODE" != post_bad_paused ] ||
    { [ "$MODE" = post_bad_paused ] && [ ! -f "$SMITE_STATE_DIR/foreign-gateway.env" ]; }
}
smite_foreign_gateway_rc7_compose() {
    calls+=(compose)
    [ "$*" = 'config --quiet' ] &&
    { [ "$MODE" != bad_compose ] && [ "$MODE" != post_bad_compose ] ||
      { [ "$MODE" = post_bad_compose ] && [ ! -f "$SMITE_STATE_DIR/foreign-gateway.env" ]; }; }
}
smite_install_unified_foreign_sanaei() {
    calls+=(sanaei)
    [ "$MODE" != failed_sanaei ]
}
smite_foreign_gateway_configure() {
    calls+=(gateway)
    [ "$UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE" = "$PACKET" ] || return 2
    if [ "$MODE" = failed_gateway ]; then
        return 2
    fi
    local exact="/smite-node/$(printf 'a%.0s' {1..32})"
    if [ "$MODE" = wrong_persisted_path ]; then exact="/smite-node/$(printf 'b%.0s' {1..32})"; fi
    cat > "$SMITE_STATE_DIR/foreign-gateway.env" <<ENV
SMITE_FOREIGN_GATEWAY_DOMAIN=kh.example.org
SMITE_FOREIGN_PANEL_DOMAIN=iran.example.org
SMITE_FOREIGN_CONTROL_PATH=$exact
SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443
SMITE_FOREIGN_GATEWAY_MODE=https-control-path
ENV
    chmod 0600 "$SMITE_STATE_DIR/foreign-gateway.env"
}

run() {
    local expected="$1" stages="$2" result=0 actual
    calls=()
    rm -f "$SMITE_STATE_DIR/foreign-gateway.env"
    smite_install_unified_foreign_after_core "$PACKET" > "$TMP/output" 2>&1 || result=$?
    actual="$(IFS=,; echo "${calls[*]-}")"
    if [ "$result" != "$expected" ] || [ "$actual" != "$stages" ]; then
        cat "$TMP/output"
        echo "FAIL: $MODE result=$result expected=$expected events=$actual expected_events=$stages"
        exit 1
    fi
    if [ "$result" = 0 ]; then
        grep -qx 'UNIFIED_FOREIGN_SANAEI_GATEWAY=PREPARED_FOR_SIGNED_ENROLLMENT' "$TMP/output"
        grep -qx 'UNIFIED_FOREIGN_CONNECTED=NOT_YET_VERIFIED' "$TMP/output"
    else
        ! grep -q 'UNIFIED_FOREIGN_SANAEI_GATEWAY=PREPARED_FOR_SIGNED_ENROLLMENT' "$TMP/output"
    fi
    ! grep -q 'smi1_B' "$TMP/output"
    ! grep -q 'PANEL_AND_IR_INSTALL=COMPLETE' "$TMP/output"
}

run 0 signed,paused,compose,sanaei,gateway,paused,compose
MODE=bad_signature; run 2 signed
MODE=wrong_image; run 2 signed
MODE=wrong_runtime_id; run 2 signed
MODE=bad_paused; run 2 signed,paused
MODE=bad_compose; run 2 signed,paused,compose
MODE=failed_sanaei; run 2 signed,paused,compose,sanaei
MODE=failed_gateway; run 2 signed,paused,compose,sanaei,gateway
MODE=wrong_persisted_path; run 2 signed,paused,compose,sanaei,gateway
# Even a successful Gateway callback may recreate/drift the exact Node.
# A second read-only witness must HOLD, before reporting prepared.
MODE=post_wrong_image; run 2 signed,paused,compose,sanaei,gateway
MODE=post_wrong_runtime_id; run 2 signed,paused,compose,sanaei,gateway
MODE=post_bad_paused; run 2 signed,paused,compose,sanaei,gateway,paused
MODE=post_bad_compose; run 2 signed,paused,compose,sanaei,gateway,paused,compose

MODE=ok
SMITE_SELECTED_FRESH=0
run 2 ""
SMITE_SELECTED_FRESH=1
SMITE_INSTALL_PROFILE=stable
run 2 ""
SMITE_INSTALL_PROFILE=clean-rc
sed -i 's/SMITE_ROLE=foreign/SMITE_ROLE=iran/' "$SMITE_STATE_FILE"
run 2 ""
sed -i 's/SMITE_ROLE=iran/SMITE_ROLE=foreign/' "$SMITE_STATE_FILE"

# An exact nonmatching host/domain must HOLD BEFORE any Sanaei/Gateway calls.
sed -i 's/SMITE_FOREIGN_DOMAIN=kh.example.org/SMITE_FOREIGN_DOMAIN=other.example.org/' "$SMITE_STATE_FILE"
run 2 signed,paused,compose
sed -i 's/SMITE_FOREIGN_DOMAIN=other.example.org/SMITE_FOREIGN_DOMAIN=kh.example.org/' "$SMITE_STATE_FILE"

# An interrupted/missing ephemeral grant packet cannot be silently rebuilt.
mv "$PACKET" "$PACKET.unavailable"
run 2 signed,paused,compose
mv "$PACKET.unavailable" "$PACKET"

# A publicly selected fresh Foreign option must now fail BEFORE any host
# mutations, since the trial signed runtime explicitly disallows activation
# and official RC7 cannot complete the same one-choice pairing transaction.
# This tests the ACTUAL menu dispatcher, not a duplicate installer mock.
# The explicit historical clean-rc branch below remains available for
# isolated preflight/compatibility tests.
SMITE_INSTALL_PROFILE=stable
status=0
smite_install_selected_fresh foreign > "$TMP/foreign-preflight-hold" 2>&1 || status=$?
[ "$status" = 2 ]
grep -qx 'FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES' "$TMP/foreign-preflight-hold"
grep -qx 'FOREIGN_CONNECTED=NOT_PROVEN' "$TMP/foreign-preflight-hold"
! grep -q 'Install Complete' "$TMP/foreign-preflight-hold"
! grep -q 'smi1_B' "$TMP/foreign-preflight-hold"
SMITE_INSTALL_PROFILE=clean-rc

# The selected Foreign core must return control to this SAME option, never
# display a completed installation or claim Connected while enrollment is HOLD.
python3 - "$ROOT/modules/smite-install.sh" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1]).read_text()
core=src.split('smite_install_foreign_node() {',1)[1].split(
    '\nsmite_install_sanaei_foreign() {',1)[0]
assert 'FOREIGN_CORE=READY_PAUSED_FOR_UNIFIED_CONTINUATION' in core
assert core.index('FOREIGN_CORE=READY_PAUSED_FOR_UNIFIED_CONTINUATION') < core.index(
    'Foreign Node Install Complete')
assert 'FOREIGN_CONNECTED=NOT_PROVEN' in core
selected=src.split('smite_install_selected_fresh() (',1)[1].split(
    '\nsmite_install_finish_local_ir() {',1)[0]
assert 'FOREIGN_ONE_CHOICE_INSTALL=INCOMPLETE_RETAIN_CORE' in selected
assert "echo 'FOREIGN_CONNECTED=NOT_PROVEN'" in selected
assert 'return 2' in selected.split('FOREIGN_ONE_CHOICE_INSTALL=INCOMPLETE_RETAIN_CORE',1)[1]
assert 'smite_install_finish_local_ir || return 2' in selected
PY

# The previous Gateway rehearsal permits a far-future expiry because
# it tests scope, NOT initial enrollment. For this *pre-core* admission the
# Panel grant must instead be genuinely fresh (at most two hours).
python3 - "$PACKET" <<'PY'
from pathlib import Path
import json,sys,time
path=Path(sys.argv[1])
record=json.loads(path.read_text())
record["expires_at"]=int(time.time())+3600
path.write_text(json.dumps(record))
PY
chmod 0600 "$PACKET"

# The existing Foreign core should take its three values from the SAME
# private Panel packet without prompting separately, but it must still fail
# at the preflight boundary in this disposable no-host test. No public
# installation route is enabled by this internal scoped branch.
smite_install_require_tools() { :; }
smite_install_ensure_docker() { :; }
smite_container_exists() { return 1; }
smite_install_clean_rc_preflight() { return 2; }
smite_install_pause() { :; }
clear() { :; }
read() { echo 'FAIL: retyped Panel packet scope' >&2; return 99; }
SMITE_FRP_TRIAL_ONLY=0
SMITE_INSTALL_FAILURE_CODE=2
SMITE_RC_SIGNED_REGISTRY=1
UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE="$PACKET"
SMITE_NODE_COMPOSE="$TMP/nonexistent-node-compose.yml"
: > "$TMP/core-input.log"
status=0
smite_install_foreign_node > "$TMP/core-input.log" 2>&1 || status=$?
[ "$status" = 2 ]
grep -qx 'FOREIGN_CORE_INPUT=VERIFIED_PANEL_PACKET' "$TMP/core-input.log"
grep -qx 'Panel domain   : iran.example.org' "$TMP/core-input.log"
grep -qx 'Foreign domain : kh.example.org' "$TMP/core-input.log"
grep -qx 'Node name      : node-kh' "$TMP/core-input.log"
! grep -q 'smi1_B' "$TMP/core-input.log"
# No silent fallback to old manual three-field prompts on malformed
# or expired grants, or on a nonfresh standalone invocation.
SMITE_SELECTED_FRESH=0
status=0
smite_install_foreign_node > "$TMP/core-invalid.log" 2>&1 || status=$?
[ "$status" = 2 ]
! grep -q '^FOREIGN_CORE_INPUT=VERIFIED_PANEL_PACKET' "$TMP/core-invalid.log"
SMITE_SELECTED_FRESH=1
python3 - "$PACKET" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1])
data=json.loads(p.read_text())
data["expires_at"]=1
p.write_text(json.dumps(data))
PY
chmod 0600 "$PACKET"
status=0
smite_install_foreign_node > "$TMP/core-expired.log" 2>&1 || status=$?
[ "$status" = 2 ]
! grep -q '^FOREIGN_CORE_INPUT=VERIFIED_PANEL_PACKET' "$TMP/core-expired.log"
! grep -q 'smi1_B' "$TMP/core-expired.log"
unset -f read clear

# The internal one-paste input cannot be invoked from a standalone or
# non-interactive shell. It must never claim enrollment or create a Node.
SMITE_SELECTED_FRESH=0
result=0
smite_install_unified_foreign_capture_packet "$TMP" > "$TMP/intake-not-selected" 2>&1 || result=$?
[ "$result" = 2 ] && [ ! -d "$TMP/foreign-fixture" ]
SMITE_SELECTED_FRESH=1
result=0
smite_install_unified_foreign_capture_packet "$TMP" > "$TMP/intake-no-tty" 2>&1 || result=$?
[ "$result" = 2 ]
[ ! -e "$TMP/foreign-fixture/foreign-staging/foreign-install-packet.json" ]
! grep -q 'FOREIGN_ONE_CHOICE_INPUT=VERIFIED' "$TMP/intake-no-tty"
! grep -q 'smi1_B' "$TMP/intake-no-tty"

# Core must provide the exact Panel 443 path to the existing
# smite_install_node_files BEFORE Docker is started (no post-Gateway rekey).
python3 - "$PACKET" <<'PY'
from pathlib import Path
import json,sys,time
p=Path(sys.argv[1])
data=json.loads(p.read_text())
data["expires_at"]=int(time.time())+3600
p.write_text(json.dumps(data))
PY
chmod 0600 "$PACKET"
smite_install_clean_rc_preflight() { return 0; }
smite_install_node_files() {
    printf '%s\n' "$5" > "$TMP/prebound-control"
    return 2  # intentional stop before any real Docker/image operation
}
status=0
smite_install_foreign_node > "$TMP/core-prebound" 2>&1 || status=$?
[ "$status" = 2 ]
[ "$(cat "$TMP/prebound-control")" = "https://kh.example.org:443/smite-node/$(printf 'a%.0s' {1..32})" ]
! grep -q 'smi1_B' "$TMP/core-prebound"
unset -f smite_install_node_files

# No publicly-selected fresh Option-2 entry may use this incomplete phase
# sequence until the signed trial runtime activation has been reviewed.
python3 - "$ROOT/modules/smite-install.sh" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1]).read_text()
start=src.index('smite_install_selected_fresh() (')
end=src.index('\nsmite_install_finish_local_ir() {',start)
assert 'smite_install_unified_foreign_after_core' not in src[start:end]
assert 'smite_install_foreign_node || return 2' in src[start:end]
assert 'smite_install_finish_local_ir || return 2' in src[start:end]
PY

# The REAL signed-pair gate refuses the current unapproved trial
# before Sanaei, Gateway, enrollment or identity mutation. Preserve all
# mock service stubs while restoring only this single real gate.
(
    eval "$REAL_UNIFIED_RELEASE_REVIEW"
    MODE=ok
    calls=()
    rm -f "$SMITE_STATE_DIR/foreign-gateway.env"
    status=0
    smite_install_unified_foreign_after_core "$PACKET" > "$TMP/release-hold" 2>&1 || status=$?
    [ "$status" = 2 ]
    [ "${#calls[@]}" -eq 0 ]
    [ ! -e "$SMITE_STATE_DIR/foreign-gateway.env" ]
    ! grep -q 'UNIFIED_FOREIGN_IMAGE_PAIR=SIGNED_RELEASE_APPROVED' "$TMP/release-hold"
    ! grep -q 'UNIFIED_FOREIGN_SANAEI_GATEWAY=PREPARED' "$TMP/release-hold"
    ! grep -q 'smi1_B' "$TMP/release-hold"
)
echo 'UNIFIED_FOREIGN_POST_CORE_CHOREOGRAPHY=PASS (19 scenarios)'
