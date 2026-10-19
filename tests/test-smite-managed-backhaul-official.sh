#!/usr/bin/env bash
# Real official Backhaul v0.7.2 artifact + exact reviewed Smite Node Compose.
# Strictly GitHub PR CI; no real Node Docker startup, service install or 443 listener.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != true || "${GITHUB_EVENT_NAME:-}" != pull_request ]]; then
  echo "HOLD: Backhaul archive trial is PR-only" >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_node="$root/.managed-smite-source/node/docker-compose.yml"
test -s "$source_node" || { echo "HOLD: missing reviewed Node Compose source" >&2; exit 2; }
lab="$(mktemp -d "${RUNNER_TEMP:?}/backhaul-txn-XXXXXXXX")"
chmod 0700 "$lab"
cleanup() { sudo rm -rf -- "$lab"; }
trap cleanup EXIT
mkdir -m 0700 "$lab/node" "$lab/node/config" "$lab/stages"
cp "$source_node" "$lab/node/docker-compose.yml"
cat > "$lab/node/.env" <<'EOF'
NODE_ROLE=foreign
NODE_API_PORT=8888
NODE_NAME=kh-trial
PANEL_ADDRESS=example.test:443
SMITE_VERSION=2.0.0-rc.0
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
EOF
chmod 0600 "$lab/node/.env"
sudo chown 0:0 "$lab/stages"
sudo chmod 0700 "$lab/stages"
url="https://github.com/Musixal/Backhaul/releases/download/v0.7.2/backhaul_linux_amd64.tar.gz"
expected="57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc"
curl -fsSL --retry 3 --proto '=https' --proto-redir '=https' "$url" -o "$lab/backhaul.tar.gz"
printf '%s  %s\n' "$expected" "$lab/backhaul.tar.gz" | sha256sum -c -
sudo python3 "$root/modules/smite-managed-backhaul.py" prepare \
  --node-dir "$lab/node" --archive "$lab/backhaul.tar.gz" \
  --staging-dir "$lab/stages" --arch amd64
stage="$(sudo find "$lab/stages" -mindepth 1 -maxdepth 1 -type d -name 'backhaul-plan-*' -print -quit)"
test -n "$stage"
sudo python3 "$root/modules/smite-managed-backhaul.py" verify --stage "$stage"
test "$(sudo "$stage/backhaul.bin" -v)" = "v0.7.2"
sudo docker compose -f "$lab/node/docker-compose.yml" \
  -f "$stage/compose.override.candidate.yml" config --format json > "$lab/merged.json"
python3 - "$lab/merged.json" <<'PY'
import json,sys
node=json.load(open(sys.argv[1]))["services"]["smite-node"]
assert node["network_mode"]=="host"
assert not node.get("ports"), "unexpected public Node port"
mounts=node["volumes"]
assert any(v["target"]=="/etc/smite-node" for v in mounts)
assert len([v for v in mounts if v["target"]=="/usr/local/bin/backhaul"])==1
engine=next(v for v in mounts if v["target"]=="/usr/local/bin/backhaul")
assert engine["read_only"] is True
assert engine["source"]=="/opt/u-opti/engines/backhaul/v0.7.2/backhaul"
assert not any(v["target"] in ("/usr/local/bin/frpc", "/usr/local/bin/frps") for v in mounts)
print("OFFICIAL_BACKHAUL_COMPOSE_CANDIDATE=PASS")
PY
test ! -e "$lab/node/config/engine-state/engines.json"
grep -Fxq 'SMITE_ENGINE_INVENTORY_MODE=managed' "$lab/node/.env"
echo "OFFICIAL_BACKHAUL_V0_7_2_STAGE_ONLY_NO_FRP=PASS"

# The identical official artifact now participates in the filesystem
# transaction, still without Docker up, services or public sockets.
baseline="$(sha256sum "$lab/node/docker-compose.yml" | awk '{print $1}')"
sudo chown -R 0:0 "$lab"
printf 'U-OPTI-BACKHAUL-ISOLATED-LAB-V1\n' | sudo tee "$lab/EXPERIMENTAL-LAB" >/dev/null
sudo chmod 0600 "$lab/EXPERIMENTAL-LAB"
# Even though the pinned image has a bundled Backhaul binary, the reviewed
# managed Node must return not-installed before enrollment.
bash "$root/tests/test-smite-managed-backhaul-node-runtime.sh" "$lab" absent
bash "$root/tests/test-smite-managed-backhaul-signed-api.sh" "$lab" absent
sudo env GITHUB_ACTIONS=true GITHUB_EVENT_NAME=pull_request \
  GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?}" RUNNER_TEMP="${RUNNER_TEMP:?}" \
  python3 "$root/modules/smite-managed-backhaul-transaction.py" activate \
  --lab-root "$lab" --stage "$stage"
sudo test -f "$lab/installed/backhaul"
sudo test -f "$lab/node/config/engine-state/engines.json"
# Recreate the container twice to establish independent inventory persistence.
bash "$root/tests/test-smite-managed-backhaul-node-runtime.sh" "$lab" ready
bash "$root/tests/test-smite-managed-backhaul-signed-api.sh" "$lab" ready
bash "$root/tests/test-smite-managed-backhaul-node-runtime.sh" "$lab" ready

# Wrong binary SHA must fail closed: the registered binary is unchanged.
sudo install -m 0755 "$stage/backhaul.bin" "$lab/mismatched-backhaul"
printf 'NOT-THE-PINNED-DIGEST' | sudo tee -a "$lab/mismatched-backhaul" >/dev/null
bash "$root/tests/test-smite-managed-backhaul-node-runtime.sh" "$lab" mismatched
sudo rm -f "$lab/mismatched-backhaul"

# Malformed registry must fail closed instead of fabricating ready status.
sudo mv "$lab/node/config/engine-state/engines.json" "$lab/node/config/engine-state/engines.backup"
printf '%s\\n' '{"schema":1,"engines":{"backhaul":{"sha256":"INVALID"}}}' | sudo tee "$lab/node/config/engine-state/engines.json" >/dev/null
sudo chmod 0600 "$lab/node/config/engine-state/engines.json"
bash "$root/tests/test-smite-managed-backhaul-node-runtime.sh" "$lab" malformed
sudo rm -f "$lab/node/config/engine-state/engines.json"
sudo mv "$lab/node/config/engine-state/engines.backup" "$lab/node/config/engine-state/engines.json"
bash "$root/tests/test-smite-managed-backhaul-node-runtime.sh" "$lab" ready

sudo docker compose -f "$lab/node/docker-compose.yml" config --format json \
  | python3 -c 'import json,sys; n=json.load(sys.stdin)["services"]["smite-node"]; assert not n.get("ports"); assert any(v["target"]=="/usr/local/bin/backhaul" and v["read_only"] for v in n["volumes"])'
sudo env GITHUB_ACTIONS=true GITHUB_EVENT_NAME=pull_request \
  GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?}" RUNNER_TEMP="${RUNNER_TEMP:?}" \
  python3 "$root/modules/smite-managed-backhaul-transaction.py" rollback --lab-root "$lab"
test "$(sudo sha256sum "$lab/node/docker-compose.yml" | awk '{print $1}')" = "$baseline"
sudo test ! -e "$lab/node/config/engine-state/engines.json"
sudo test ! -e "$lab/installed/backhaul"
bash "$root/tests/test-smite-managed-backhaul-node-runtime.sh" "$lab" absent
bash "$root/tests/test-smite-managed-backhaul-signed-api.sh" "$lab" absent
echo "BACKHAUL_REAL_ARTIFACT_TRANSACTION_AND_EXACT_ROLLBACK=PASS"
echo "BACKHAUL_SIGNED_NODE_API_NO_PORTS_RESTART_ROLLBACK=PASS"
echo "BACKHAUL_REAL_NODE_INVENTORY_BEFORE_AFTER_RECREATE_ROLLBACK=PASS"
