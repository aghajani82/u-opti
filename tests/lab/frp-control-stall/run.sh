#!/usr/bin/env bash
# Disposable CI runner only. Never run on IR/Grandoptical.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${UOPTI_DISPOSABLE_FRP_LAB:-} == YES ]] || exit 2
root="$PWD"
mkdir -p evidence
old="$root/.frp-old"
new="$root/.frp-new"
[[ $(git -C "$old" rev-parse HEAD) == 4a23aa181c1d7e28eecaa8216024ed753b9d27c8 ]]
[[ $(git -C "$new" rev-parse HEAD) == d8cf1800dc1abd7fda1828cab105d7a6b5a50eb1 ]]
# Copy official test only, not a repair. The 0.71.0 dispatcher is unmodified.
cp "$new/pkg/msg/handler_write_error_test.go" "$old/pkg/msg/"
cp tests/lab/frp-control-stall/effective_config_test.go "$old/pkg/config/v1/uopti_defaults_test.go"
cp tests/lab/frp-control-stall/effective_config_test.go "$new/pkg/config/v1/uopti_defaults_test.go"
(
 cd "$old"
 go test -race -v ./pkg/msg -run '^TestControlCryptoWriterKeepsErrorAfterTransportRecovery$'
 set +e
 go test -race -v ./pkg/msg -run '^TestDispatcherWriteErrorClosesControlAndFreshSessionWorks$' > "$root/evidence/upstream-0710-regression.txt" 2>&1
 rc=$?
 set -e
 [[ $rc == 1 ]]
 grep -Fq 'timed out waiting for failed control connection close' "$root/evidence/upstream-0710-regression.txt"
 ! grep -Eq 'DATA RACE|build failed|setup failed' "$root/evidence/upstream-0710-regression.txt"
 go test -v ./pkg/config/v1 -run '^TestUoptiGeneratedWSSDefaults$'
) 2>&1 | tee evidence/upstream-0710.txt
(
 cd "$new"
 go test -race -v -count=3 ./pkg/msg
 go test -v ./pkg/config/v1 -run '^TestUoptiGeneratedWSSDefaults$'
 go test -race -tags noweb ./client/... ./server/... ./pkg/transport/...
) 2>&1 | tee evidence/upstream-0711.txt
python3 tests/lab/frp-control-stall/assets.py | tee evidence/asset-audit.txt
for version in 0.71.0 0.71.1; do
 if [[ $version == 0.71.0 ]]; then source_dir="$old"; else source_dir="$new"; fi
 # The one-line constructor seam injects the proven retained WriteMsg error.
 # Dispatcher and production control lifecycle logic are NOT repaired/patched.
 python3 - "$source_dir" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])/'server/control.go'
s=p.read_text();old='ctl.msgDispatcher = msg.NewDispatcher(sessionCtx.Conn)'
assert s.count(old)==1
s=s.replace(old,'ctl.msgDispatcher = msg.NewDispatcher(uoptiFaultConn(sessionCtx.Conn, sessionCtx.LoginMsg.User))')
p.write_text(s)
PY
 cp tests/lab/frp-control-stall/fault.go "$source_dir/server/uopti_lab_fault.go"
 (cd "$source_dir"; CGO_ENABLED=0 go build -tags noweb -o "$root/evidence/$version/frps-fault" ./cmd/frps)
done
docker build -t uopti-frp-control-lab tests/lab/frp-control-stall
docker run --rm --network none --user 65534:65534 --sysctl net.ipv4.ip_unprivileged_port_start=0 --cap-drop ALL --security-opt no-new-privileges \
 -e UOPTI_DISPOSABLE_FRP_LAB=YES \
 -v "$root/evidence:/binaries:ro" \
 -v "$root/tests/lab/frp-control-stall:/lab:ro" \
 uopti-frp-control-lab python3 /lab/shared_wss.py | tee evidence/shared-wss-results.txt
