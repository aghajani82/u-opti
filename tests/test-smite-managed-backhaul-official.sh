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
# Strict replay source comes from the same reviewed Smite Draft as the
# fail-closed quarantine implementation. This is CI-only first enrollment.
smite_sha="02d05056d3a4baf577c9d3781d62af61c000f1ac"
[[ "$(git -C "$root/.managed-smite-source" rev-parse HEAD)" == "$smite_sha" ]] || {
  echo "HOLD: signed Node source not the reviewed security commit" >&2
  exit 2
}
export SMITE_CI_STRICT_REPLAY_BOOTSTRAP=1
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
  python3 "$root/modules/smite-managed-backhaul-control.py" install \
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
  python3 "$root/modules/smite-managed-backhaul-control.py" rollback --lab-root "$lab"
test "$(sudo sha256sum "$lab/node/docker-compose.yml" | awk '{print $1}')" = "$baseline"
sudo test ! -e "$lab/node/config/engine-state/engines.json"
sudo test ! -e "$lab/installed/backhaul"
bash "$root/tests/test-smite-managed-backhaul-node-runtime.sh" "$lab" absent
bash "$root/tests/test-smite-managed-backhaul-signed-api.sh" "$lab" absent
echo "BACKHAUL_REAL_ARTIFACT_TRANSACTION_AND_EXACT_ROLLBACK=PASS"
echo "BACKHAUL_SIGNED_NODE_API_NO_PORTS_RESTART_ROLLBACK=PASS"
echo "BACKHAUL_REAL_NODE_INVENTORY_BEFORE_AFTER_RECREATE_ROLLBACK=PASS"

# New lifecycle milestone: one controller holds the whole compensation
# boundary while the actual pinned Node API restarts and answers signed HMAC.
# On simulated failed post-restart health, it MUST automatically rollback.
# Pass only the required GitHub PR metadata through sudo; the isolated
# signed-API helper needs GITHUB_RUN_ID for its unique throwaway container.
sudo env GITHUB_ACTIONS=true GITHUB_EVENT_NAME=pull_request \
  GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?}" RUNNER_TEMP="${RUNNER_TEMP:?}" \
  GITHUB_RUN_ID="${GITHUB_RUN_ID:?}" SMITE_CI_COMPOSE_RECREATE=1 \
  SMITE_CI_STRICT_REPLAY_BOOTSTRAP=1 \
  python3 "$root/tests/test-smite-managed-backhaul-lifecycle-official.py" \
  "$lab" "$stage"


# Repeat the exact signed Docker lifecycle with an ALREADY INSTALLED
# official FRP v0.71.0 pair. This is a disposable fixture only: no FRP
# service starts, no public port opens, and the real host installer stays HOLD.
frp_asset="frp_0.71.0_linux_amd64.tar.gz"
frp_url="https://github.com/fatedier/frp/releases/download/v0.71.0/$frp_asset"
frp_hash="84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716"
# The trial lab was deliberately changed to owner=root, mode 0700.
# Download/verify the second official asset as root, not the runner user.
sudo curl --fail --silent --show-error --location --retry 3 --retry-delay 2 \
  --max-time 120 --output "$lab/$frp_asset" "$frp_url"
test "$(sudo sha256sum "$lab/$frp_asset" | awk '{print $1}')" = "$frp_hash"

# Only after the pinned tar digest matches, read exactly the two regular
# role executables from the archive; never extract arbitrary tar paths.
sudo python3 - "$lab" "$lab/$frp_asset" <<'PY_EXISTING_FRP'
from pathlib import Path
import hashlib, json, os, stat, sys, tarfile
root, archive = Path(sys.argv[1]), Path(sys.argv[2])
parent = root / "installed"
parent.mkdir(mode=0o700)
frp_dir = parent / "frp"
frp_dir.mkdir(mode=0o700)
digests = {}
with tarfile.open(archive, "r:gz") as tar:
    for name in ("frpc", "frps"):
        target_name = f"frp_0.71.0_linux_amd64/{name}"
        matches = [m for m in tar.getmembers() if m.name == target_name]
        assert len(matches) == 1 and matches[0].isfile()
        assert 4 <= matches[0].size <= 50 * 1024 * 1024
        with tar.extractfile(matches[0]) as inp:
            data = inp.read(50 * 1024 * 1024 + 1)
        assert len(data) == matches[0].size and data.startswith(b"\x7fELF")
        file = frp_dir / name
        fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o755)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        digests[name] = hashlib.sha256(data).hexdigest()
compose = root / "node/docker-compose.yml"
original = compose.read_text()
line = "      - ./config:/etc/smite-node\n"
assert original.count(line) == 1
mounts = "".join(
    f"      - {frp_dir / name}:/usr/local/bin/{name}:ro\n"
    for name in ("frpc", "frps"))
compose.write_text(original.replace(line, line + mounts, 1))
state = root / "node/config/engine-state"
state.mkdir(mode=0o700)
manifest = state / "engines.json"
document = {"schema": 1, "engines": {
    "frp": {"sha256": digests["frpc"], "server_sha256": digests["frps"]}}}
fd = os.open(manifest, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as out:
    json.dump(document, out, sort_keys=True)
    out.flush()
    os.fsync(out.fileno())
print("ISOLATED_OFFICIAL_FRP_PREEXISTING_FIXTURE=PASS")
PY_EXISTING_FRP

sudo python3 "$root/modules/smite-managed-backhaul.py" prepare \
  --node-dir "$lab/node" --archive "$lab/backhaul.tar.gz" \
  --staging-dir "$lab/stages" --arch amd64 >/dev/null
stage_with_frp=""
while IFS= read -r candidate_stage; do
  if [[ "$candidate_stage" != "$stage" ]]; then
    stage_with_frp="$candidate_stage"
  fi
done < <(sudo find "$lab/stages" -mindepth 1 -maxdepth 1 -type d -name 'backhaul-plan-*')
[[ -n "$stage_with_frp" ]] || { echo "HOLD: existing-FRP candidate missing" >&2; exit 2; }
sudo python3 "$root/modules/smite-managed-backhaul.py" verify --stage "$stage_with_frp" >/dev/null
frp_before="$(sudo sha256sum "$lab/installed/frp/frpc" "$lab/installed/frp/frps" | sha256sum | awk '{print $1}')"
compose_before="$(sudo sha256sum "$lab/node/docker-compose.yml" | awk '{print $1}')"
manifest_before="$(sudo sha256sum "$lab/node/config/engine-state/engines.json" | awk '{print $1}')"
sudo env GITHUB_ACTIONS=true GITHUB_EVENT_NAME=pull_request \
  GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?}" RUNNER_TEMP="${RUNNER_TEMP:?}" \
  GITHUB_RUN_ID="${GITHUB_RUN_ID:?}" SMITE_CI_COMPOSE_RECREATE=1 \
  SMITE_CI_STRICT_REPLAY_BOOTSTRAP=1 \
  SMITE_CI_EXISTING_FRP=1 \
  python3 "$root/tests/test-smite-managed-backhaul-lifecycle-official.py" \
  "$lab" "$stage_with_frp"
test "$(sudo sha256sum "$lab/installed/frp/frpc" "$lab/installed/frp/frps" | sha256sum | awk '{print $1}')" = "$frp_before"
test "$(sudo sha256sum "$lab/node/docker-compose.yml" | awk '{print $1}')" = "$compose_before"
test "$(sudo sha256sum "$lab/node/config/engine-state/engines.json" | awk '{print $1}')" = "$manifest_before"
sudo test ! -e "$lab/installed/backhaul"
sudo test ! -e "$lab/recovery-journal"
echo "OFFICIAL_DUAL_ENGINE_FRP_SURVIVED_BACKHAUL_SIGNED_RECREATE_AND_ROLLBACK=PASS"
