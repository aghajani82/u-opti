#!/usr/bin/env bash
# PR-only real, signed Smite Node + dual FRP artifact + Compose restart/recovery.
# No open ports, no real tunnels, no Panel Apply, no VPS interaction.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != "true" ||
      "${GITHUB_EVENT_NAME:-}" != "pull_request" ||
      "${GITHUB_REPOSITORY:-}" != "aghajani82/u-opti" ||
      -z "${RUNNER_TEMP:-}" || -z "${GITHUB_RUN_ID:-}" ]]; then
  echo "HOLD: Real signed FRP runtime requires disposable PR CI" >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_node="$root/.managed-smite-source/node/docker-compose.yml"
test -s "$source_node" && test -s "$root/.managed-smite-source/node/app/engine_inventory.py" || {
  echo "HOLD: Exact reviewed Smite Node checkout is missing" >&2
  exit 2
}
lab="$(mktemp -d "${RUNNER_TEMP:?}/uopti-official-frp-XXXXXXXX")"
chmod 0700 "$lab"
cleanup() { sudo rm -rf -- "$lab"; }
trap cleanup EXIT
mkdir -m 0700 "$lab/node" "$lab/node/config" "$lab/stages"
cp "$source_node" "$lab/node/docker-compose.yml"
cat > "$lab/node/.env" <<'EOF'
NODE_ROLE=foreign
NODE_API_PORT=8888
NODE_NAME=kh-frp-ci
PANEL_ADDRESS=example.test:443
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
EOF
chmod 0600 "$lab/node/.env"
asset="frp_0.71.0_linux_amd64.tar.gz"
url="https://github.com/fatedier/frp/releases/download/v0.71.0/$asset"
expected="84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716"
curl --fail --silent --show-error --location --retry 3 --retry-delay 2 \
  --max-time 120 --output "$lab/$asset" "$url"
printf '%s  %s\n' "$expected" "$lab/$asset" | sha256sum --check --status

# All filesystem admission and recovery is root-only inside disposable lab.
sudo chown -R 0:0 "$lab"
sudo chmod 0700 "$lab" "$lab/node" "$lab/node/config" "$lab/stages"
printf 'U-OPTI-BACKHAUL-ISOLATED-LAB-V1\n' |
  sudo tee "$lab/EXPERIMENTAL-LAB" >/dev/null
sudo chmod 0600 "$lab/EXPERIMENTAL-LAB"
sudo python3 "$root/modules/smite-managed-frp.py" prepare \
  --node-dir "$lab/node" --archive "$lab/$asset" \
  --staging-dir "$lab/stages" --arch amd64 >/dev/null
stage="$(sudo find "$lab/stages" -mindepth 1 -maxdepth 1 \
  -type d -name 'frp-plan-*' -print -quit)"
test -n "$stage"
sudo python3 "$root/modules/smite-managed-frp.py" verify --stage "$stage" >/dev/null

# The source Compose is checked rather than run: host network is NEVER used
# for runtime testing. The adapter projects only allowlisted mounts to a
# distinct network:none Compose with no host published ports/capabilities.
sudo docker compose -f "$lab/node/docker-compose.yml" \
  -f "$stage/compose.override.candidate.yml" config --format json |
  python3 -c '
import json,sys
node=json.load(sys.stdin)["services"]["smite-node"]
assert node["network_mode"]=="host" and not node.get("ports")
mounts={m["target"]:m for m in node["volumes"]}
for name in ("frpc","frps"):
    m=mounts["/usr/local/bin/"+name]
    assert m["read_only"] is True
    assert m["source"]=="/opt/u-opti/engines/frp/v0.71.0/"+name
assert "/usr/local/bin/backhaul" not in mounts
print("OFFICIAL_FRP_SOURCE_COMPOSE_DUAL_RO_MOUNTS=PASS")
'
baseline="$(sudo sha256sum "$lab/node/docker-compose.yml" | awk '{print $1}')"
export SMITE_CI_ENGINE=frp SMITE_CI_COMPOSE_RECREATE=1
bash "$root/tests/test-smite-managed-backhaul-signed-api.sh" "$lab" absent
sudo test ! -e "$lab/smite-node-isolated-absent.json" || {
  echo "HOLD: FIRST_SIGNED_FRP_COMPOSE_CLEANUP_INCOMPLETE" >&2
  exit 2
}
echo "SIGNED_FRP_NODE_ABSENT_BEFORE_INSTALL=PASS"

txn() {
  local op="$1"
  shift
  sudo env GITHUB_ACTIONS=true GITHUB_EVENT_NAME=pull_request \
    GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?}" RUNNER_TEMP="${RUNNER_TEMP:?}" \
    python3 "$root/modules/smite-managed-frp-transaction.py" "$op" \
    --lab-root "$lab" "$@"
}
txn activate --stage "$stage" >/dev/null
bash "$root/tests/test-smite-managed-backhaul-signed-api.sh" "$lab" ready
echo "SIGNED_FRP_DUAL_BINARY_READY_AFTER_COMPOSE_RECREATE=PASS"
txn rollback >/dev/null
echo "OFFICIAL_FRP_FILESYSTEM_ROLLBACK=PASS"
test "$(sudo sha256sum "$lab/node/docker-compose.yml" | awk '{print $1}')" = "$baseline"
sudo test ! -e "$lab/node/config/engine-state/engines.json"
sudo test ! -e "$lab/installed/frp/frpc"
sudo test ! -e "$lab/installed/frp/frps"
sudo test ! -e "$lab/smite-node-isolated-absent.json" || {
  echo "HOLD: STALE_ABSENT_COMPOSE_FROM_PREVIOUS_PROBE" >&2
  exit 2
}
echo "OFFICIAL_FRP_ROLLBACK_BYTES_RESTORED=PASS"
bash "$root/tests/test-smite-managed-backhaul-signed-api.sh" "$lab" absent
echo "SIGNED_FRP_ABSENT_AFTER_EXACT_ROLLBACK=PASS"

# Fault is injected after ONLY the client binary is installed. Old Node
# identity and signed inventory must recover without starting any FRP.
# Inject interruption exclusively through the reviewed PR-only runner
# method; NEVER invoke a second normal installation at this point.
sudo env GITHUB_ACTIONS=true GITHUB_EVENT_NAME=pull_request \
  GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?}" RUNNER_TEMP="${RUNNER_TEMP:?}" \
  python3 -B - "$root" "$lab" "$stage" <<'PY'
from pathlib import Path
import importlib.util,sys
repo,lab,stage=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location(
    "frp_signed_ci_inject",repo/"modules/smite-managed-frp-transaction.py")
tx=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)
with tx.lock(lab):
    try:
        tx.activate(lab,stage,inject="after-frpc")
    except tx.Hold as exc:
        assert str(exc)=="INJECTED_INTERRUPTION"
    else:
        raise AssertionError("failure injection not rejected")
    tx.rollback(lab)
print("FRP_FAULT_AFTER_FRPC_EXACT_ROLLBACK=PASS")
PY
bash "$root/tests/test-smite-managed-backhaul-signed-api.sh" "$lab" absent
echo "SIGNED_FRP_NODE_RECOVERED_AFTER_INTERRUPTED_INSTALL=PASS"
