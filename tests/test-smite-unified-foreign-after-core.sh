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
import json,sys,time
packet={
  "protocol":"smi1",
  "panel_url":"https://iran.example.org:443",
  "node_id":"foreign-node-0001",
  "node_name":"node-kh",
  "origin":"https://kh.example.org:443",
  "control_url":"https://kh.example.org:443/smite-node/"+"a"*32,
  "installation_code":"smi1_"+"B"*43,
  "expires_at":int(time.time())+3600,
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
# The ORIGINAL RC9 Core Journal is called by the selected after-core
# coordinator after Sanaei RO attachment. Mock only this read-only CLI;
# leave the real Panel packet / TTL validator fully exercised.
: > "$TMP/foreign-core-witness-calls"
python3() {
    if [[ "${2:-}" == "$ROOT/modules/smite-rc6-install-journal.py" ]] &&
       [ "${3:-}" = resume-foreign ]; then
        printf '%s\n' "$*" >> "$TMP/foreign-core-witness-calls"
        [[ "$*" == *'--attached-sanaei'* ]] &&
        [[ "$*" == *'--foreign-packet-file '* ]] &&
        [[ "$*" == *'--installer-pid '* ]] || return 2
        [ "$MODE" != foreign_core_owner_drift ] || return 2
        printf '%s\n' \
            'FOREIGN_CORE_STAGE=CORE_COMMITTED' \
            'FOREIGN_CORE_PROJECT=uopti_rc6_0123456789abcdef0123456789abcdef'
    else
        command python3 "$@"
    fi
}
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
                echo 'ghcr.io/aghajani82/smite-node@sha256:3df3c9d40c338ab87205bbe93e9ab9bd94eb4051558c4429fdd09f876b76b2c2'
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
        'image inspect -f {{.Id}} ghcr.io/aghajani82/smite-node@sha256:3df3c9d40c338ab87205bbe93e9ab9bd94eb4051558c4429fdd09f876b76b2c2')
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
# The real selected installer reuses original read-only Sanaei/443 witnesses
# AFTER a successful Gateway stage; fixture callbacks never change the host.
smite_install_sanaei_retained() {
    calls+=(post_ro)
    [ "$MODE" != post_ro_drift ]
}
smite_foreign_gateway_verify_local() {
    calls+=(verified_tls)
    [ "$MODE" != post_tls_drift ]
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

run 0 signed,paused,compose,sanaei,gateway,paused,compose,post_ro,verified_tls

# The SAME original Sanaei/Gateway choreography admits signed RC9 only with
# the exact sealed source. This still uses a stubbed release verifier and
# cannot be invoked on a real host while activation remains default-off.
printf 'SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.9\nSMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06\nSMITE_CONNECTION_MODE=standard\nSMITE_PANEL_DOMAIN=iran.example.org\nSMITE_FOREIGN_DOMAIN=kh.example.org\nSMITE_NODE_NAME=node-kh\n' > "$SMITE_STATE_FILE"
chmod 0600 "$SMITE_STATE_FILE"
MODE=ok; run 0 signed,paused,compose,sanaei,gateway,paused,compose,post_ro,verified_tls
grep -q 'resume-foreign --foreign-packet-file' "$TMP/foreign-core-witness-calls"
grep -q -- '--attached-sanaei' "$TMP/foreign-core-witness-calls"
grep -q -- '--installer-pid' "$TMP/foreign-core-witness-calls"
# Existing Sanaei is not removed/reinstalled merely because the current
# signed owner is unverified. Gateway must not start under owner drift.
MODE=foreign_core_owner_drift
run 2 signed,paused,compose,sanaei
MODE=ok
sed -i 's/^SMITE_UPSTREAM_REF=.*/SMITE_UPSTREAM_REF=0000000000000000000000000000000000000000/' "$SMITE_STATE_FILE"
run 2 ""
sed -i '/^SMITE_UPSTREAM_REF=/d' "$SMITE_STATE_FILE"
run 2 ""
printf 'SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.7\nSMITE_CONNECTION_MODE=standard\nSMITE_PANEL_DOMAIN=iran.example.org\nSMITE_FOREIGN_DOMAIN=kh.example.org\nSMITE_NODE_NAME=node-kh\n' > "$SMITE_STATE_FILE"
chmod 0600 "$SMITE_STATE_FILE"
MODE=ok
# The original after-core scope check did not recheck expiry. The
# selected one-choice path must now HOLD before Sanaei/Gateway for an
# expired OR implausibly far-future code, even with a valid signed pair.
python3 - "$PACKET" <<'PY_STALE'
import json,sys,time
from pathlib import Path
p=Path(sys.argv[1])
doc=json.loads(p.read_text())
doc['expires_at']=int(time.time())-1
p.write_text(json.dumps(doc))
PY_STALE
chmod 0600 "$PACKET"
# Verify the exact already existing CLI that option 2 invokes. A stale
# packet must fail independently of Docker stubs and Nginx test fixtures.
if python3 -B "$ROOT/modules/smite-unified-foreign-gateway-plan.py" \
        --packet-file "$PACKET" --precore-fields \
        >"$TMP/stale-precore.log" 2>&1; then
    echo 'FAIL: expired packet unexpectedly admitted by existing pre-core parser' >&2
    exit 1
fi
MODE=ok; run 2 signed
python3 - "$PACKET" <<'PY_FUTURE'
import json,sys,time
from pathlib import Path
p=Path(sys.argv[1])
doc=json.loads(p.read_text())
# Leave a safety margin beyond the two-hour grant limit. A fixture
# using now+7201 can become valid when the CI runner crosses one second.
doc['expires_at']=int(time.time())+7800
p.write_text(json.dumps(doc))
PY_FUTURE
chmod 0600 "$PACKET"
run 2 signed
python3 - "$PACKET" <<'PY_REFRESH'
import json,sys,time
from pathlib import Path
p=Path(sys.argv[1])
doc=json.loads(p.read_text())
doc['expires_at']=int(time.time())+3600
p.write_text(json.dumps(doc))
PY_REFRESH
chmod 0600 "$PACKET"
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
MODE=post_ro_drift; run 2 signed,paused,compose,sanaei,gateway,paused,compose,post_ro
MODE=post_tls_drift; run 2 signed,paused,compose,sanaei,gateway,paused,compose,post_ro,verified_tls

# Retry a completed Gateway in place to preserve the selected vhost.
smite_foreign_gateway_site_path() { printf '%s\n' "$TMP/foreign-site"; }
smite_foreign_gateway_verify_local() {
    calls+=(retained_tls)
    [ "$MODE" != drifted_tls ]
}
smite_foreign_gateway_recreate_node() {
    calls+=(retained_node)
    [ "$UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE" = "$PACKET" ]
}
MODE=ok
run 0 signed,paused,compose,sanaei,gateway,paused,compose,post_ro,retained_tls
calls=()
smite_install_unified_foreign_after_core "$PACKET" > "$TMP/retained"
grep -qx 'UNIFIED_FOREIGN_GATEWAY=VERIFIED_RETAINED' "$TMP/retained"
[ "$(IFS=,; echo "${calls[*]}")" = signed,paused,compose,sanaei,retained_tls,retained_node,paused,compose,post_ro ]
MODE=drifted_tls
calls=()
status=0
smite_install_unified_foreign_after_core "$PACKET" > "$TMP/drifted" 2>&1 || status=$?
[ "$status" = 2 ]
[ "$(IFS=,; echo "${calls[*]}")" = signed,paused,compose,sanaei,retained_tls ]
! grep -q 'PREPARED_FOR_SIGNED_ENROLLMENT' "$TMP/drifted"
# A long Sanaei setup can exhaust the two-hour grant before Gateway changes.
(
    MODE=ok
    smite_install_unified_foreign_sanaei() {
        calls+=(sanaei)
        python3 - "$PACKET" <<'PY_EXPIRE'
import json, sys, time
from pathlib import Path
path = Path(sys.argv[1])
packet = json.loads(path.read_text())
packet['expires_at'] = int(time.time()) - 1
path.write_text(json.dumps(packet))
PY_EXPIRE
    }
    cp -p "$PACKET" "$TMP/packet-before-expiry"
    run 2 signed,paused,compose,sanaei
    grep -q 'Foreign installation code expired' "$TMP/output"
    mv "$TMP/packet-before-expiry" "$PACKET"
)
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
# The same early fresh-packet check now rejects absence before touching
# Docker ownership probes, Sanaei or Gateway.
run 2 signed
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
assert "echo 'FOREIGN_CONNECTED=NOT_PROVEN'" in selected
assert 'return 2' in selected.split('FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES',1)[1].split('    fi', 1)[0]
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
saved_umask="$(umask)"
umask 022
smite_install_unified_foreign_capture_packet "$TMP" > "$TMP/intake-no-tty" 2>&1 || result=$?
umask "$saved_umask"
[ "$result" = 2 ]
# Parent + staging path must stay owner-private even if the caller's shell
# inherited a permissive umask. The stopped input never writes bearer data.
[ "$(stat -c '%a:%u' "$TMP/foreign-fixture")" = "700:$(id -u)" ]
[ "$(stat -c '%a:%u' "$TMP/foreign-fixture/foreign-staging")" = "700:$(id -u)" ]
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
assert 'smite_install_foreign_node; fi' in src[start:end]
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
# The exact future selected option-2 Core entry must pass the EXISTING
# signed-release gate before even reading the private one-use packet or
# creating a Core owner. The original Core Journal remains real-host HOLD.
SMITE_SELECTED_FRESH=1
SMITE_INSTALL_PROFILE=clean-rc
SMITE_FIELD_TRIAL_SOURCE_SHA=e7f76185e9a7da51d7069d5d0a829dc192cc1e06
SMITE_NODE_IMAGE=ghcr.io/aghajani82/smite-node@sha256:3df3c9d40c338ab87205bbe93e9ab9bd94eb4051558c4429fdd09f876b76b2c2
RELEASE_FIXTURE=HOLD
smite_install_unified_signed_pair_review() {
    [ "$RELEASE_FIXTURE" = pass ] || return 2
    echo 'UNIFIED_FOREIGN_IMAGE_PAIR=SIGNED_RELEASE_APPROVED'
}
: > "$TMP/foreign-core-cli-calls"
python3() {
    printf '%s\n' "$*" >> "$TMP/foreign-core-cli-calls"
    case "$*" in
        *smite-unified-foreign-gateway-plan.py*--precore-fields) return 0 ;;
        *smite-rc6-install-journal.py*--foreign-packet-file*--source*)
            printf 'uopti_rc6_%s\n' "$(printf 'a%.0s' {1..32})" ;;
        *) echo 'FAIL: unexpected Core packet/Journaling call' >&2; return 77 ;;
    esac
}
status=0
smite_install_unified_foreign_begin_core_from_panel "$PACKET" > "$TMP/foreign-core-release-hold" 2>&1 || status=$?
[ "$status" = 2 ]
[ ! -s "$TMP/foreign-core-cli-calls" ]
! grep -q 'FOREIGN_CORE_OWNER=' "$TMP/foreign-core-release-hold"
RELEASE_FIXTURE=pass
EXPECTED_INSTALLER_PID="$BASHPID"
smite_install_unified_foreign_begin_core_from_panel "$PACKET" > "$TMP/foreign-core-owner-fixture" 2>&1
grep -qx "FOREIGN_CORE_OWNER=uopti_rc6_$(printf 'a%.0s' {1..32})" "$TMP/foreign-core-owner-fixture"
grep -F -- "--installer-pid $EXPECTED_INSTALLER_PID --resumable-foreign" "$TMP/foreign-core-cli-calls" >/dev/null
[ "$(wc -l < "$TMP/foreign-core-cli-calls")" -eq 2 ]
grep -F -- "--resumable-foreign --foreign-packet-file $PACKET --source e7f76185e9a7da51d7069d5d0a829dc192cc1e06" "$TMP/foreign-core-cli-calls" >/dev/null
! grep -q -- '--foreign-inputs' "$TMP/foreign-core-cli-calls"
! grep -q -- 'smi1_B' "$TMP/foreign-core-cli-calls"
SMITE_NODE_IMAGE=ghcr.io/aghajani82/smite-node@sha256:0000000000000000000000000000000000000000000000000000000000000000
: > "$TMP/foreign-core-cli-calls"
status=0
smite_install_unified_foreign_begin_core_from_panel "$PACKET" > "$TMP/foreign-core-wrong-image" 2>&1 || status=$?
[ "$status" = 2 ] && [ ! -s "$TMP/foreign-core-cli-calls" ]
echo 'UNIFIED_FOREIGN_CORE_SINGLE_PACKET_RELEASE_GATED_HANDOFF=PASS_ISOLATED_NO_HOST_WRITES'

# Test the REAL new Core-stage decision function, confined to the disposable
# TMP journal locator. All Python/Docker/Node actions are mocked: never write
# /var/lib/u-opti or touch real services. The signed release still HOLDs.
(
    SMITE_SELECTED_FRESH=1
    SMITE_INSTALL_PROFILE=clean-rc
    SMITE_FIELD_TRIAL_SOURCE_SHA=e7f76185e9a7da51d7069d5d0a829dc192cc1e06
    SMITE_NODE_IMAGE=ghcr.io/aghajani82/smite-node@sha256:3df3c9d40c338ab87205bbe93e9ab9bd94eb4051558c4429fdd09f876b76b2c2
    local_definition="$(declare -f smite_install_unified_foreign_core_stage)"
    original_locator="journal_file=/var/lib/u-opti/rc6-install-journal/current.json"
    [[ "$local_definition" == *"$original_locator"* ]] || {
        echo "FAIL: original root owner locator changed"; exit 1;
    }
    local_definition="${local_definition/$original_locator/journal_file=$TMP\/core-current.json}"
    eval "$local_definition"
    # This fixture copies the production function into a temporary shell:
    # BASH_SOURCE then points at this test, not the original module.
    # Resolve ONLY that test-local dirname to the real module directory.
    dirname() { printf '%s\n' "$ROOT/modules"; }
    PROJECT="uopti_rc6_$(printf 'a%.0s' {1..32})"
    : > "$TMP/core-stage-calls"
    RELEASE_FIXTURE=HOLD
    FIX_STAGE=CORE_PENDING
    MOCK_NODE_FAIL=0
    SANAEI_RO_READY=0
    smite_install_sanaei_retained() {
        if [ "$SANAEI_RO_READY" = 1 ]; then
            printf 'witness-ro\n' >> "$TMP/core-stage-calls"
            return 0
        fi
        return 3
    }
    smite_install_unified_signed_pair_review() {
        printf 'release\n' >> "$TMP/core-stage-calls"
        [ "$RELEASE_FIXTURE" = pass ] || return 2
        echo 'UNIFIED_FOREIGN_IMAGE_PAIR=SIGNED_RELEASE_APPROVED'
    }
    smite_install_unified_foreign_begin_core_from_panel() {
        printf 'begin\n' >> "$TMP/core-stage-calls"
        printf '%s\n' "${2:-missing}" > "$TMP/core-stage-installer-pid"
        printf 'FOREIGN_CORE_OWNER=%s\n' "$PROJECT"
    }
    smite_install_foreign_node() {
        printf 'install\n' >> "$TMP/core-stage-calls"
        [ "$COMPOSE_PROJECT_NAME" = "$PROJECT" ] &&
        [ "$UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE" = "$PACKET" ] &&
        [ "$MOCK_NODE_FAIL" = 0 ]
    }
    python3() {
        case "$*" in
            *"smite-rc6-install-journal.py resume-foreign --foreign-packet-file $PACKET --attached-sanaei")
                printf 'resume-ro\n' >> "$TMP/core-stage-calls"
                printf 'FOREIGN_CORE_STAGE=%s\nFOREIGN_CORE_PROJECT=%s\n' "$FIX_STAGE" "$PROJECT" ;;
            *"smite-rc6-install-journal.py resume-foreign --foreign-packet-file $PACKET")
                printf 'resume\n' >> "$TMP/core-stage-calls"
                printf 'FOREIGN_CORE_STAGE=%s\nFOREIGN_CORE_PROJECT=%s\n' "$FIX_STAGE" "$PROJECT" ;;
            *"smite-rc6-install-journal.py commit")
                printf 'commit\n' >> "$TMP/core-stage-calls"
                printf 'RC6_INSTALL_TRANSACTION=COMMITTED\n' ;;
            *) printf 'FAIL: unexpected Core command\n' >&2; return 77 ;;
        esac
    }
    case_core() {
        local expected_rc="$1" expected_calls="$2" result=0
        local expected_installer_pid="$BASHPID"
        : > "$TMP/core-stage-calls"
        : > "$TMP/core-stage-installer-pid"
        smite_install_unified_foreign_core_stage "$PACKET" \
            > "$TMP/core-stage-report" 2>&1 || result=$?
        [ "$result" -eq "$expected_rc" ] || {
            echo "FAIL: Core stage return $result expected $expected_rc"; cat "$TMP/core-stage-report"; exit 1;
        }
        [ "$(cat "$TMP/core-stage-calls")" = "$expected_calls" ] || {
            echo 'FAIL: wrong Core stage callbacks'
            cat "$TMP/core-stage-calls"; exit 1;
        }
        if grep -qx 'begin' "$TMP/core-stage-calls"; then
            [ "$(cat "$TMP/core-stage-installer-pid")" = "$expected_installer_pid" ] || {
                echo 'FAIL: Core journal inherited transient child PID, not installer process'; exit 1;
            }
        fi
        if [ "$result" -eq 0 ]; then
            ! grep -q '^UNIFIED_FOREIGN_IMAGE_PAIR=' "$TMP/core-stage-report"
            grep -qx "FOREIGN_CORE_PROJECT=$PROJECT" "$TMP/core-stage-report"
            grep -qx 'FOREIGN_CORE_STAGE=CORE_COMMITTED' "$TMP/core-stage-report"
            grep -qx 'FOREIGN_CORE_NEXT=EXISTING_SANAEI_GATEWAY_SIGNED_PAIRING' "$TMP/core-stage-report"
        else
            ! grep -q '^FOREIGN_CORE_STAGE=CORE_COMMITTED' "$TMP/core-stage-report"
        fi
    }
    # No host Core action, not even resume read, before signed release.
    case_core 2 'release'
    RELEASE_FIXTURE=pass
    case_core 0 "$(printf 'release\nbegin\ninstall\ncommit')"
    touch "$TMP/core-current.json"
    FIX_STAGE=CORE_PENDING
    case_core 0 "$(printf 'release\nresume\ninstall\ncommit')"
    MOCK_NODE_FAIL=1
    case_core 2 "$(printf 'release\nresume\ninstall')"
    MOCK_NODE_FAIL=0
    FIX_STAGE=CORE_READY_TO_COMMIT
    case_core 0 "$(printf 'release\nresume\ncommit')"
    FIX_STAGE=CORE_COMMITTED
    case_core 0 "$(printf 'release\nresume')"
    SANAEI_RO_READY=1
    case_core 0 "$(printf 'release\nwitness-ro\nresume-ro')"
    SANAEI_RO_READY=0
    FIX_STAGE=INVALID
    case_core 2 "$(printf 'release\nresume')"
    PROJECT=not_an_owned_project
    FIX_STAGE=CORE_PENDING
    case_core 2 "$(printf 'release\nresume')"
    ln -s "$PACKET" "$TMP/symlink-packet"
    : > "$TMP/core-stage-calls"
    if smite_install_unified_foreign_core_stage "$TMP/symlink-packet" \
        > "$TMP/core-stage-symlink" 2>&1; then
        echo 'FAIL: symlinked private packet accepted'; exit 1
    fi
    [ ! -s "$TMP/core-stage-calls" ]
    echo 'UNIFIED_FOREIGN_CORE_STAGE=PASS_ISOLATED_RESUME_AND_NO_RECREATE'
)

# Exercise the ACTUAL internal one-choice Core -> Sanaei/Gateway hand-off.
# The already unit-tested functions are stubbed only at their boundaries;
# the wrapper must never run Host after failed Core, or falsely mark
# Connected after a prepared Gateway. One retry retains the same Core.
(
    SMITE_SELECTED_FRESH=1
    SMITE_INSTALL_PROFILE=clean-rc
    : > "$TMP/prepair-stage-calls"
    CORE_ALLOWED=1
    HOST_ALLOWED=1
    IDENTITY_PREFLIGHT_ALLOWED=1
    smite_install_unified_foreign_identity_preflight() {
        printf 'identity-preflight\n' >> "$TMP/prepair-stage-calls"
        [ "$IDENTITY_PREFLIGHT_ALLOWED" = 1 ] || return 2
        printf 'FOREIGN_SIGNED_PAIRING_PREFLIGHT=EXACT_READ_ONLY\n'
    }
    smite_install_unified_foreign_core_stage() {
        printf 'core\n' >> "$TMP/prepair-stage-calls"
        [ "$CORE_ALLOWED" = 1 ]
    }
    smite_install_unified_foreign_after_core() {
        printf 'host\n' >> "$TMP/prepair-stage-calls"
        [ "$HOST_ALLOWED" = 1 ]
    }
    expect_preparing() {
        local status=0 expected="$1" calls="$2"
        : > "$TMP/prepair-stage-calls"
        smite_install_unified_foreign_pre_pairing_stages "$PACKET" \
            > "$TMP/prepair-stage-result" 2>&1 || status=$?
        [ "$status" -eq "$expected" ] || {
            echo "FAIL: pre-pairing $status expected $expected"; exit 1;
        }
        [ "$(cat "$TMP/prepair-stage-calls")" = "$calls" ] || {
            echo "FAIL: pre-pairing order wrong"; cat "$TMP/prepair-stage-calls"; exit 1;
        }
        if [ "$expected" -eq 0 ]; then
            grep -qx 'FOREIGN_OPTION2_PRE_PAIRING=SIGNED_CORE_SANAEI_RO_GATEWAY_443_PREPARED' \
                "$TMP/prepair-stage-result"
            grep -qx 'FOREIGN_IDENTITY=AWAITING_ORIGINAL_SIGNED_PAIRING' \
                "$TMP/prepair-stage-result"
            grep -qx 'FOREIGN_CONNECTED=NOT_PROVEN' "$TMP/prepair-stage-result"
        else
            ! grep -q '^FOREIGN_OPTION2_PRE_PAIRING=' "$TMP/prepair-stage-result"
        fi
    }
    SMITE_SELECTED_FRESH=0
    expect_preparing 2 ''
    SMITE_SELECTED_FRESH=1
    CORE_ALLOWED=0
    expect_preparing 2 'core'
    CORE_ALLOWED=1
    HOST_ALLOWED=0
    expect_preparing 2 "$(printf 'core\nhost')"
    HOST_ALLOWED=1
    # The real original one-choice wrapper also refuses to claim Pairing
    # readiness when the final READ-ONLY promotion witness drifts.
    IDENTITY_PREFLIGHT_ALLOWED=0
    expect_preparing 2 "$(printf 'core\nhost\nidentity-preflight')"
    IDENTITY_PREFLIGHT_ALLOWED=1
    expect_preparing 0 "$(printf 'core\nhost\nidentity-preflight')"
    expect_preparing 0 "$(printf 'core\nhost\nidentity-preflight')"
    echo 'UNIFIED_FOREIGN_PRE_PAIRING_STAGE=PASS_ISOLATED_ORIGINAL_OWNERS'
)

# Exercise the ACTUAL non-mutating pre-Signed-Pairing adapter with its
# original verified source/packet files but a fake Python process. The
# original Python boundary is separately tested with genuine modules.
(
    SMITE_SELECTED_FRESH=1
    SMITE_INSTALL_PROFILE=clean-rc
    SMITE_STATE_DIR="$TMP"
    SMITE_STATE_FILE="$TMP/state.env"
    SMITE_NODE_DIR="$TMP/foreign-node"
    mkdir -p "$SMITE_NODE_DIR"
    printf 'NODE_ROLE=foreign\n' > "$SMITE_NODE_DIR/.env"
    printf 'SMITE_ROLE=foreign\n' > "$SMITE_STATE_FILE"
    : > "$TMP/identity-readonly-cli"
    REAL_PREFLIGHT="$(declare -f smite_install_unified_foreign_identity_preflight)"
    eval "$REAL_PREFLIGHT"
    dirname() { printf '%s\n' "$ROOT/modules"; }
    smite_foreign_gateway_domain() { printf '%s\n' kh.example.org; }
    smite_foreign_gateway_site_path() { printf '%s\n' "$TMP/3xui-kh.example.org"; }
    READONLY_PROOF=PASS
    READONLY_OWNER=PASS
    : > "$TMP/identity-runtime-probes"
    smite_install_unified_foreign_node_image_review() {
        printf 'signed-image\n' >> "$TMP/identity-runtime-probes"
        [ "$READONLY_OWNER" = PASS ]
    }
    smite_foreign_gateway_require_rc_paused() {
        printf 'paused-strict\n' >> "$TMP/identity-runtime-probes"
        [ "$READONLY_OWNER" = PASS ]
    }
    smite_foreign_gateway_rc7_compose() {
        printf 'compose %s\n' "$*" >> "$TMP/identity-runtime-probes"
        [ "$READONLY_OWNER" = PASS ] && [ "$*" = 'config --quiet' ]
    }
    smite_install_sanaei_retained() {
        printf 'sanaei-ro-sqlite\n' >> "$TMP/identity-runtime-probes"
        [ "$READONLY_OWNER" = PASS ]
    }
    python3() {
        printf '%s\n' "$*" >> "$TMP/identity-readonly-cli"
        [ "$READONLY_PROOF" = PASS ] || return 2
        printf 'FOREIGN_SIGNED_PAIRING_PREFLIGHT=EXACT_READ_ONLY\n'
    }
    output="$(smite_install_unified_foreign_identity_preflight "$PACKET")"
    [ "$output" = 'FOREIGN_SIGNED_PAIRING_PREFLIGHT=EXACT_READ_ONLY' ]
    [ "$(cat "$TMP/identity-runtime-probes")" = "$(printf 'signed-image\npaused-strict\ncompose config --quiet\nsanaei-ro-sqlite')" ] || {
        echo 'FAIL: final signed runtime/RO witnesses not exercised'; exit 1;
    }
    grep -F -- "--packet-file $PACKET --state-file $SMITE_STATE_FILE --gateway-state-file $SMITE_STATE_DIR/foreign-gateway.env --site-file $TMP/3xui-kh.example.org --node-env-file $SMITE_NODE_DIR/.env --prepairing-read-only" \
        "$TMP/identity-readonly-cli" >/dev/null
    ! grep -Fq 'smi1_B' "$TMP/identity-readonly-cli"
    READONLY_PROOF=HOLD
    if smite_install_unified_foreign_identity_preflight "$PACKET" \
       > "$TMP/identity-readonly-hold" 2>&1; then
        echo 'FAIL: drifted promotion admission was accepted'; exit 1
    fi
    ! grep -q '^FOREIGN_SIGNED_PAIRING_PREFLIGHT=' "$TMP/identity-readonly-hold"
    READONLY_PROOF=PASS
    READONLY_OWNER=HOLD
    : > "$TMP/identity-readonly-cli"
    if smite_install_unified_foreign_identity_preflight "$PACKET" \
       > "$TMP/identity-runtime-drift" 2>&1; then
        echo 'FAIL: unverified signed Node/Sanaei runtime admitted'; exit 1
    fi
    [ ! -s "$TMP/identity-readonly-cli" ]
    READONLY_OWNER=PASS
    SMITE_SELECTED_FRESH=0
    : > "$TMP/identity-readonly-cli"
    if smite_install_unified_foreign_identity_preflight "$PACKET" \
       > "$TMP/identity-readonly-unselected" 2>&1; then
        echo 'FAIL: unselected Foreign identity admission accepted'; exit 1
    fi
    [ ! -s "$TMP/identity-readonly-cli" ]
    SMITE_SELECTED_FRESH=1
    ln -s "$PACKET" "$TMP/identity-preflight-symlink"
    if smite_install_unified_foreign_identity_preflight "$TMP/identity-preflight-symlink" \
       > "$TMP/identity-readonly-symlink" 2>&1; then
        echo 'FAIL: symlinked Foreign identity packet accepted'; exit 1
    fi
    [ ! -s "$TMP/identity-readonly-cli" ]
    echo 'FOREIGN_ORIGINAL_SIGNED_IDENTITY_READ_ONLY_BOUNDARY=PASS'
)

echo 'UNIFIED_FOREIGN_POST_CORE_CHOREOGRAPHY=PASS (including retained Gateway retry)'

# Selected option-2 identity bridge: original stage order, no duplicate
# Pairing menu, no claim of activation or Connected until live proof.
(
    SMITE_SELECTED_FRESH=1
    SMITE_INSTALL_PROFILE=clean-rc
    SMITE_FIELD_TRIAL_SOURCE_SHA=e7f76185e9a7da51d7069d5d0a829dc192cc1e06
    STAGE_FAIL=
    : > "$TMP/selected-identity-stage-calls"
    smite_install_unified_foreign_pre_pairing_stages() {
        printf 'core-sanaei-443\n' >> "$TMP/selected-identity-stage-calls"
        [ "$STAGE_FAIL" != core ]
    }
    smite_install_unified_foreign_identity_stage() {
        printf 'original-identity\n' >> "$TMP/selected-identity-stage-calls"
        [ "$STAGE_FAIL" != identity ]
    }
    : > "$TMP/selected-identity-stage-calls"
    smite_install_unified_foreign_selected_stages "$PACKET" > "$TMP/selected-identity-ok"
    [ "$(cat "$TMP/selected-identity-stage-calls")" = "$(printf 'core-sanaei-443\noriginal-identity')" ]
    grep -qx 'FOREIGN_OPTION2_IDENTITY=SIGNED_PROOF_PREPARED' "$TMP/selected-identity-ok"
    grep -qx 'FOREIGN_NODE_ACTIVATION=NOT_PERFORMED' "$TMP/selected-identity-ok"
    grep -qx 'FOREIGN_CONNECTED=NOT_PROVEN' "$TMP/selected-identity-ok"
    STAGE_FAIL=core
    : > "$TMP/selected-identity-stage-calls"
    if smite_install_unified_foreign_selected_stages "$PACKET" > "$TMP/selected-identity-core-failed"; then
        echo 'FAIL: failed Core advanced to Identity' >&2; exit 1
    fi
    [ "$(cat "$TMP/selected-identity-stage-calls")" = core-sanaei-443 ]
    ! grep -q 'FOREIGN_OPTION2_IDENTITY=' "$TMP/selected-identity-core-failed"
    STAGE_FAIL=identity
    : > "$TMP/selected-identity-stage-calls"
    if smite_install_unified_foreign_selected_stages "$PACKET" > "$TMP/selected-identity-denied"; then
        echo 'FAIL: unproved Identity marked ready' >&2; exit 1
    fi
    [ "$(cat "$TMP/selected-identity-stage-calls")" = "$(printf 'core-sanaei-443\noriginal-identity')" ]
    ! grep -q 'FOREIGN_OPTION2_IDENTITY=' "$TMP/selected-identity-denied"
)

# The actual root identity stage must refuse a temporary/symlinked or
# otherwise non-owned packet BEFORE release review, Python, or redemption.
(
    SMITE_SELECTED_FRESH=1
    SMITE_INSTALL_PROFILE=clean-rc
    SMITE_FIELD_TRIAL_SOURCE_SHA=e7f76185e9a7da51d7069d5d0a829dc192cc1e06
    smite_install_unified_signed_pair_review() {
        echo NOT_CALLED >&2
        return 2
    }
    if smite_install_unified_foreign_identity_stage "$PACKET" > "$TMP/identity-root-guard" 2>&1; then
        echo 'FAIL: temporary packet admitted by original root identity path' >&2; exit 1
    fi
    grep -q 'requires the retained original private Panel packet' "$TMP/identity-root-guard"
    ! grep -q 'NOT_CALLED' "$TMP/identity-root-guard"
)
command python3 - "$ROOT/modules/smite-install.sh" <<'PY_SELECTED_HMAC_BRIDGE'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text()
body=s.split('smite_install_unified_foreign_identity_stage() {',1)[1].split(
    '\nsmite_install_unified_foreign_selected_stages() {',1)[0]
for marker in (
    "smite_install_unified_signed_pair_review",
    "smite_install_unified_foreign_identity_preflight",
    "smite-unified-foreign-identity-phase.py",
    "--selected-foreign --installer-pid",
):
    assert marker in body, marker
assert body.index('smite_install_unified_signed_pair_review') < body.index(
    'smite_install_unified_foreign_identity_preflight') < body.index(
    '--selected-foreign --installer-pid')
assert "FOREIGN_CONNECTED=YES" not in body
PY_SELECTED_HMAC_BRIDGE
echo 'FOREIGN_OPTION2_ORIGINAL_SIGNED_IDENTITY_BRIDGE=PASS_ISOLATED'

# Original option-2 durable packet capture is INSIDE the selected flow, but
# the signed release false gate must stop it before Journal.prepare, mkdir,
# hidden TTY input, Docker or any host side effects.
(
    SMITE_SELECTED_FRESH=1
    SMITE_INSTALL_PROFILE=clean-rc
    SMITE_FIELD_TRIAL_SOURCE_SHA=e7f76185e9a7da51d7069d5d0a829dc192cc1e06
    : > "$TMP/owned-packet-prehost-calls"
    smite_install_unified_signed_pair_review() {
        printf 'signed-release-review\n' >> "$TMP/owned-packet-prehost-calls"
        return 2
    }
    python3() {
        printf 'UNSAFE_PYTHON_EXECUTED\n' >> "$TMP/owned-packet-prehost-calls"
        return 77
    }
    smite_install_unified_foreign_pre_pairing_stages() {
        printf 'UNSAFE_CORE_HOST_EXECUTED\n' >> "$TMP/owned-packet-prehost-calls"
        return 77
    }
    if smite_install_unified_foreign_selected_stages         > "$TMP/owned-packet-release-hold" 2>&1; then
        echo 'FAIL: release-hold option 2 admitted real owned packet' >&2
        exit 1
    fi
    [ "$(cat "$TMP/owned-packet-prehost-calls")" = signed-release-review ]
    grep -q 'Foreign private grant cannot be captured before signed release'         "$TMP/owned-packet-release-hold"
    ! grep -q 'FOREIGN_OPTION2_IDENTITY=SIGNED_PROOF_PREPARED'         "$TMP/owned-packet-release-hold"
)
echo 'FOREIGN_OPTION2_DURABLE_PACKET_RELEASE_HOLD=PASS_ISOLATED_NO_HOST_WRITES'
