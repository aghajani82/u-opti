#!/usr/bin/env bash
# Import the EXACT reviewed Smite Node inventory logic in the pinned Node image.
# A disposable Docker sandbox only: no API daemon, no host network, no ports,
# no Node registration, no tunnels, no live IR/KH, no service restart.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != true ||
      "${GITHUB_EVENT_NAME:-}" != pull_request ||
      "${GITHUB_REPOSITORY:-}" != aghajani82/u-opti ]]; then
  echo "HOLD: signed Node engine inventory trial is PR-only" >&2
  exit 2
fi
lab="${1:?pass private lab root}"
case "${2:-}" in
  absent|ready|mismatched|malformed) expected="$2" ;;
  *) echo "HOLD: unexpected inventory trial state" >&2; exit 2 ;;
esac
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
smite="$root/.managed-smite-source"
[[ -f "$smite/node/app/config.py" && -f "$smite/node/app/engine_inventory.py" ]] || {
  echo "HOLD: exact reviewed Smite Node inventory unavailable" >&2; exit 2;
}
[[ -d "$lab" && ! -L "$lab" && "$lab" == "${RUNNER_TEMP:?}"/backhaul-txn-* ]] || {
  echo "HOLD: not an expected temporary lab" >&2; exit 2;
}
sudo test -f "$lab/EXPERIMENTAL-LAB" || {
  echo "HOLD: trial marker missing" >&2; exit 2;
}
[[ "$(sudo cat "$lab/EXPERIMENTAL-LAB")" == U-OPTI-BACKHAUL-ISOLATED-LAB-V1 ]] || {
  echo "HOLD: unrecognized trial marker" >&2; exit 2;
}
# In all cases a real pinned Backhaul executable is mounted; declaring
# an engine present based on a bundled executable alone MUST NOT be possible.
binary="$lab/stages/$(sudo find "$lab/stages" -mindepth 1 -maxdepth 1 -type d -name 'backhaul-plan-*' -printf '%f\n' | head -n 1)/backhaul.bin"
sudo test -f "$binary" || { echo "HOLD: candidate binary missing" >&2; exit 2; }
if [[ "$expected" == ready || "$expected" == malformed ]]; then
  binary="$lab/installed/backhaul"
  sudo test -f "$binary" || { echo "HOLD: installed binary missing" >&2; exit 2; }
fi
if [[ "$expected" == mismatched ]]; then
  binary="$lab/mismatched-backhaul"
  sudo test -f "$binary" || { echo "HOLD: explicit mismatched fixture missing" >&2; exit 2; }
fi
image="ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
# Execute the precise Python source module against the container's actual
# /usr/local/bin/backhaul, root permissions, and private state directory.
# The image is pinned and the reviewed source is mounted read-only; old
# bundled modules can NEVER substitute for the review branch.
sudo docker run --rm --platform linux/amd64 \
  --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 96 --memory 256m \
  --user 0:0 \
  --env SMITE_ENGINE_INVENTORY_MODE=managed \
  --env SMITE_ENGINE_MANIFEST_PATH=/etc/smite-node/engine-state/engines.json \
  --env EXPECTED_ENGINE_STATE="$expected" \
  --mount "type=bind,src=$lab/node/config,dst=/etc/smite-node,readonly" \
  --mount "type=bind,src=$binary,dst=/usr/local/bin/backhaul,readonly" \
  --mount "type=bind,src=$smite/node/app/config.py,dst=/app/app/config.py,readonly" \
  --mount "type=bind,src=$smite/node/app/engine_inventory.py,dst=/app/app/engine_inventory.py,readonly" \
  --entrypoint python "$image" -B -c '
import os
from app.engine_inventory import (
    engine_inventory, require_engine_ready, EngineInventoryUnavailable,
)
status = os.environ["EXPECTED_ENGINE_STATE"]
if status == "malformed":
    try:
        engine_inventory()
    except EngineInventoryUnavailable:
        print("NODE_MANAGED_MALFORMED_FAIL_CLOSED=PASS")
    else:
        raise AssertionError("malformed registry was accepted")
else:
    expected = "unavailable" if status == "mismatched" else (
        "not-installed" if status == "absent" else "ready"
    )
    result = engine_inventory()
    assert result["mode"] == "managed", result
    assert set(result["engines"]) == {"backhaul", "frp", "gost", "rathole", "chisel"}
    assert result["engines"]["backhaul"] == expected, result
    assert all(value == "not-installed"
               for name, value in result["engines"].items() if name != "backhaul")
    if expected == "ready":
        require_engine_ready("backhaul")
        print("NODE_MANAGED_BACKHAUL_READY=PASS")
    else:
        try:
            require_engine_ready("backhaul")
        except EngineInventoryUnavailable:
            print("NODE_MANAGED_BACKHAUL_NOT_READY=PASS")
        else:
            raise AssertionError("untrusted engine was allowed to Apply")
    try:
        require_engine_ready("frp")
    except EngineInventoryUnavailable:
        print("NODE_MANAGED_FRP_INDEPENDENT=PASS")
    else:
        raise AssertionError("bundled FRP incorrectly became installed")
'
echo "NODE_INVENTORY_CONTAINER_${expected^^}=PASS"
