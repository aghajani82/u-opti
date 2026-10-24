#!/usr/bin/env bash
# Real U-OPTI foreign clean-RC Compose + real Smite Node image, isolated PR CI.
# No live host networking, published ports, operator activation or VPS changes.
set -euo pipefail

if [ "${GITHUB_ACTIONS:-}" != true ] || [ "${GITHUB_EVENT_NAME:-}" != pull_request ]; then
  echo "HOLD: Stage24 Docker test is permitted only in disposable PR CI" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMITE="$ROOT/.stage24-smite-src"
test -f "$SMITE/node/docker-compose.yml" || { echo "HOLD: exact Smite source unavailable" >&2; exit 2; }
lab="$(mktemp -d)"
chmod 0700 "$lab"
project="stage24-${GITHUB_RUN_ID:-0}"
node_dir="$lab/node"
identity_dir="$lab/identities"
replay_anchor="$lab/var-lib"
replay_dir="$replay_anchor/u-opti/smite-node-security/replay"
base="$node_dir/docker-compose.yml"
candidate="$node_dir/docker-compose.security-candidate.yml"
ci_override="$lab/ci-isolation.yml"

compose() {
  sudo docker compose --project-name "$project" -f "$base" "$@" -f "$ci_override"
}
# Compose CLI requires all -f files BEFORE command: use dedicated wrappers.
paused() { sudo docker compose --project-name "$project" -f "$base" -f "$ci_override" "$@"; }
signed() { sudo docker compose --project-name "$project" -f "$base" -f "$candidate" -f "$ci_override" "$@"; }
cleanup() {
  paused down --remove-orphans >/dev/null 2>&1 || true
  sudo chown -R "$(id -u):$(id -g)" "$lab" >/dev/null 2>&1 || true
  rm -rf -- "$lab"
}
trap cleanup EXIT

mkdir -p "$node_dir" "$lab/state"
export SMITE_INSTALL_PROFILE=clean-rc
# Execute the real installer layout transformations. The reviewed
# Smite source replaces only the upstream Compose download; a clean
# Core install MUST NOT invoke FRP preparation or Compose injection.
source "$ROOT/modules/smite-install.sh"
SMITE_NODE_IMAGE="smite-node:stage15-local"
SMITE_NODE_DIR="$node_dir"
SMITE_NODE_COMPOSE="$base"
smite_download_upstream() {
  test "$1" = "node/docker-compose.yml"
  cp "$SMITE/node/docker-compose.yml" "$2"
}
# If the installer accidentally reintroduces host FRP, FAIL this
# real-Compose Docker test instead of silently swallowing the call.
smite_frp_prepare_binaries() {
  echo "HOLD: clean KH attempted host FRP download" >&2
  return 98
}
smite_frp_mount_compose() {
  echo "HOLD: clean KH attempted host FRP mount" >&2
  return 98
}
if ! smite_install_node_files node-kh-01 foreign panel.stage24.test:443 "" "" "" standard > "$lab/install.log"; then
  echo "HOLD: Stage24 reviewed Node installer did not complete" >&2
  # Print fixed failure classifications only, never .env or key material.
  grep -E '^(HOLD|ERROR)[: ]' "$lab/install.log" >&2 || true
  exit 1
fi
echo "STAGE24_NODE_INSTALLER=PASS"
# The actual U-OPTI installer runs as root on KH. The ephemeral GitHub
# shell does not. Mirror that root-owned writable container config mount,
# rather than granting elevated Docker capabilities to pass a test.
sudo chown -R 0:0 "$node_dir/config" "$node_dir/certs"
sudo chmod 0700 "$node_dir/config"
grep -Fxq "SMITE_NODE_PANEL_AUTH_MODE=paused" "$node_dir/.env"
grep -Fxq "SMITE_AGENT_AUTH_MODE=strict" "$node_dir/.env"
grep -Fxq "SMITE_CORE_FRP_HOST_INSTALL=SKIPPED" "$lab/install.log"
! grep -Eq '/usr/local/bin/frp(c|s)' "$base"
test ! -e "$node_dir/certs/ca.crt"
grep -qF '/healthz' "$base"
! grep -qF '/api/agent/status' "$base"
test "$(stat -c %a "$node_dir/.env")" = 600
baseline_sha="$(sha256sum "$base" | awk '{print $1}')"

printf 'SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n' > "$lab/state/state.env"
sudo install -d -m 0700 "$lab/identities"
# Mirror the production trust boundary exactly: /var/lib is an existing
# root-owned, non-writable anchor; U-OPTI creates the three private levels
# beneath it. Keep $lab itself runner-owned so CI can write unrelated files.
sudo install -d -o 0 -g 0 -m 0755 "$replay_anchor"
sudo python3 - "$identity_dir/node-identity.json" <<'PY'
import json, os, secrets, sys
path=sys.argv[1]
fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
with os.fdopen(fd,"w") as f:
    json.dump({"node_id":"stage24-kh-reserved-0001","node_secret":secrets.token_hex(32)},f)
    f.flush(); os.fsync(f.fileno())
PY

sudo python3 - "$ROOT/modules/smite-node-auth-candidate.py" "$lab/state/state.env" "$identity_dir/node-identity.json" "$base" "$candidate" "$replay_dir" <<'PY'
import importlib.util, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("uopti_stage9",sys.argv[1])
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
args={"state_path":Path(sys.argv[2]),"identity":Path(sys.argv[3]),
      "base_compose":Path(sys.argv[4]),"candidate":Path(sys.argv[5]),
      "replay_dir":Path(sys.argv[6])}
assert m.prepare(**args)=="PREPARED"
assert m.prepare(**args)=="UNCHANGED"
PY

test "$(sudo stat -c %a "$candidate")" = 600
test "$(sha256sum "$base" | awk '{print $1}')" = "$baseline_sha"
identity_sha="$(sudo sha256sum "$identity_dir/node-identity.json" | awk '{print $1}')"

# Confirm BOTH real installer-generated Compose files merge without an
# environment mapping/list collision, no exposed host TCP ports, and no
# downgrade. The production layout deliberately retains host networking;
# actual CI runtime below overrides it with network:none.
sudo docker compose -f "$base" config --format json > "$lab/paused.json"
sudo docker compose -f "$base" -f "$candidate" config --format json > "$lab/signed.json"
python3 - "$lab/paused.json" "$lab/signed.json" "$identity_dir" "$replay_dir" <<'PY'
import json,sys
paused,signed=(json.load(open(p))["services"]["smite-node"] for p in sys.argv[1:3])
def assert_composed(s):
    assert s["network_mode"]=="host", "Installer network setting unexpectedly changed"
    assert not s.get("ports"), "Unsafe published Node port"
    assert s["command"][s["command"].index("--host")+1]=="127.0.0.1"
    assert "127.0.0.1:" in s["healthcheck"]["test"][-1] and "/healthz" in s["healthcheck"]["test"][-1]
assert_composed(paused)
assert_composed(signed)
assert paused["environment"]["SMITE_NODE_PANEL_AUTH_MODE"]=="paused"
assert paused["environment"]["SMITE_AGENT_AUTH_MODE"]=="strict"
assert signed["environment"]["SMITE_NODE_PANEL_AUTH_MODE"]=="signed"
assert signed["environment"]["SMITE_AGENT_AUTH_MODE"]=="strict"
assert signed["environment"]["SMITE_AGENT_IDENTITY_PATH"]=="/run/smite-node-identity/node-identity.json"
assert signed["environment"]["SMITE_AGENT_REPLAY_DB"]=="/var/lib/smite-node/auth/agent-replay.sqlite3"
mounts=signed["volumes"]
assert any(v["source"]==sys.argv[3] and v["target"]=="/run/smite-node-identity" and v["read_only"] for v in mounts)
assert any(v["source"]==sys.argv[4] and v["target"]=="/var/lib/smite-node/auth" for v in mounts)
assert not any(v["source"]==sys.argv[3] for v in paused["volumes"])
print("STAGE24_REAL_INSTALLER_COMPOSE_MERGE=PASS")
PY

# The fixture only tightens isolation on an ephemeral GitHub runner.
# This overlay is NOT a proposed production config. !reset avoids
# needing the host's /dev/net/tun and elevated tunnel capabilities.
cat > "$ci_override" <<'YAML'
services:
  smite-node:
    container_name: stage24-kh
    network_mode: none
    build: !reset null
    devices: !reset []
    cap_add: !reset []
    cap_drop: [ALL]
    restart: "no"
YAML
sudo docker compose -f "$base" -f "$candidate" -f "$ci_override" config --quiet
sudo docker compose -f "$base" -f "$ci_override" config --quiet

# Compile real Smite Node image from the exact reviewed source SHA.
# This image is LOCAL to CI, with no tag publication or external services.
docker build -q -f "$SMITE/node/Dockerfile" --build-arg SMITE_VERSION=2.0.0-rc.0 -t smite-node:stage15-local "$SMITE/node" >/dev/null

# One-time enrollment is OFFLINE, explicit and scoped to a disposable runner.
# Mount the host folders at the EXACT CONTAINER paths used by Smite Strict:
# the key-bound marker must not record a host-only replay DB path.
sudo docker run --rm --network none --cap-drop ALL \
  --security-opt no-new-privileges \
  --mount "type=bind,source=$identity_dir,target=/run/smite-node-identity" \
  --mount "type=bind,source=$replay_dir,target=/var/lib/smite-node/auth" \
  --entrypoint python3 smite-node:stage15-local \
  -m app.replay_enrollment \
  --identity /run/smite-node-identity/node-identity.json \
  --replay-db /var/lib/smite-node/auth/agent-replay.sqlite3 \
  --confirm-first-provision > "$lab/first-enrollment.txt"
grep -qx 'REPLAY_DB_FIRST_ENROLLMENT=PROVISIONED' "$lab/first-enrollment.txt"
grep -qx 'SIGNED_TRAFFIC_ACTIVATION=NOT_AUTHORIZED' "$lab/first-enrollment.txt"
sudo test -s "$identity_dir/replay-enrollment.json"
sudo test -s "$replay_dir/agent-replay.sqlite3"
sudo python3 - "$identity_dir/node-identity.json" "$identity_dir/replay-enrollment.json" <<'PY'
import hashlib, hmac, json, sys
from pathlib import Path
identity=json.loads(Path(sys.argv[1]).read_text())
marker=json.loads(Path(sys.argv[2]).read_text())
node_id=identity["node_id"]
expected=hmac.new(
    identity["node_secret"].encode("ascii"),
    b"smite-replay-key-binding-v1:" + node_id.encode("ascii"),
    hashlib.sha256,
).hexdigest()
assert marker["node_id"]==node_id
assert marker["replay_database"]=="/var/lib/smite-node/auth/agent-replay.sqlite3"
assert hmac.compare_digest(marker["key_binding"], expected)
print("STAGE24_KEY_BOUND_CONTAINER_REPLAY_MARKER=PASS")
PY
test "$(sudo stat -c %a "$identity_dir/replay-enrollment.json")" = 600
test "$(sudo stat -c %a "$replay_dir/agent-replay.sqlite3")" = 600
marker_sha="$(sudo sha256sum "$identity_dir/replay-enrollment.json" | awk '{print $1}')"
# This preflight inspects offline host files only; it must not attempt to
# apply Compose, import Docker state, create a DB or silently rotate keys.
sudo python3 - "$ROOT/modules/smite-node-replay-mount-admission.py" \
  "$lab/state/state.env" "$identity_dir/node-identity.json" \
  "$replay_dir" "$base" "$candidate" <<'PY'
import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("kh_admission",sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
assert module.preflight(state=Path(sys.argv[2]),identity=Path(sys.argv[3]),
                       replay_dir=Path(sys.argv[4]),base_compose=Path(sys.argv[5]),
                       candidate=Path(sys.argv[6]))=="KH_PRIVATE_BIND_MOUNTS_OFFLINE_PREFLIGHT_PASS"
PY
echo "STAGE24_EXPLICIT_FIRST_REPLAY_ENROLLMENT=PASS"


wait_node() {
  for attempt in $(seq 1 35); do
    # A repeatedly exited container will never recover by polling longer.
    if [ "$(sudo docker inspect -f '{{.State.Running}}' stage24-kh 2>/dev/null)" != true ]; then
      break
    fi
    if sudo docker exec stage24-kh python3 -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8888/healthz',timeout=2)" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "HOLD: actual Compose Node did not become locally healthy" >&2
  sudo docker inspect stage24-kh --format 'STATE={{.State.Status}} EXIT={{.State.ExitCode}} ERROR={{.State.Error}}' >&2 || true
  # CI contains synthetic identity only; print failure class, never its
  # environment, .env, paired secret, mounts or complete app output.
  sudo docker logs stage24-kh 2>&1 |
    grep -E 'Traceback|Error|ERROR|Exception|Permission denied|No such file|unavailable|failed' |
    tail -18 >&2 || true
  exit 1
}
check_no_network() {
  test "$(sudo docker inspect -f '{{.HostConfig.NetworkMode}}' stage24-kh)" = none
  test "$(sudo docker inspect -f '{{.HostConfig.PortBindings}}' stage24-kh)" = "map[]"
}

# Inspect Docker's EFFECTIVE merged mount set, not just the candidate text.
# In particular the existing node-data named volume covers /var/lib/smite-node
# and the child private replay bind must still win at /var/lib/smite-node/auth.
check_signed_mounts() {
  sudo docker inspect stage24-kh --format '{{json .Mounts}}' |
    python3 -c '
import json,sys
mounts=json.load(sys.stdin)
def by_target(path):
    found=[m for m in mounts if m["Destination"]==path]
    assert len(found)==1, (path,"missing or conflicting mount")
    return found[0]
identity=by_target("/run/smite-node-identity")
replay=by_target("/var/lib/smite-node/auth")
parent=by_target("/var/lib/smite-node")
assert identity["Type"]=="bind" and identity["RW"] is False
assert replay["Type"]=="bind" and replay["RW"] is True
assert parent["Type"]=="volume"
print("STAGE24_NESTED_DOCKER_MOUNT_EFFECTIVE=PASS")
'
}
probe() { sudo docker exec -i stage24-kh python3 - "$@" ; }

# Phase A: installed paused + strict KH has no Node identity mount.
paused up -d --force-recreate --no-build >/dev/null
wait_node
check_no_network
probe <<'PY'
import urllib.error,urllib.request,os
assert os.getenv("SMITE_NODE_PANEL_AUTH_MODE")=="paused"
assert os.getenv("SMITE_AGENT_AUTH_MODE")=="strict"
assert not os.path.exists("/run/smite-node-identity/node-identity.json")
try: urllib.request.urlopen("http://127.0.0.1:8888/api/agent/status",timeout=4)
except urllib.error.HTTPError as e: assert e.code==503
else: raise AssertionError("Unpaired Agent status was exposed")
PY
echo "STAGE24_COMPOSE_PAUSED_STRICT=PASS"

# Phase B: same original files + private prepared security candidate.
# No installation rerun and no live Panel to contact: Node remains fail closed.
signed up -d --force-recreate --no-build >/dev/null
wait_node
check_no_network
check_signed_mounts
probe <<'PY'
import json,os,urllib.request,urllib.error
from pathlib import Path
from app.agent_auth import read_identity
from app.node_auth import sign_request
assert os.getenv("SMITE_NODE_PANEL_AUTH_MODE")=="signed"
assert os.getenv("SMITE_AGENT_AUTH_MODE")=="strict"
assert os.getenv("SMITE_ENGINE_INVENTORY_MODE")=="managed"
p=Path("/run/smite-node-identity/node-identity.json")
node,secret=read_identity(p)
assert node=="stage24-kh-reserved-0001"
try: p.write_text("malicious write")
except OSError: pass
else: raise AssertionError("Identity bind was writable")
base="http://127.0.0.1:8888/api/agent/status"
try: urllib.request.urlopen(base,timeout=4)
except urllib.error.HTTPError as e: assert e.code==401
else: raise AssertionError("Signed Agent allowed an unsigned request")
sig=sign_request(secret=secret,node_id=node,method="GET",
                 target="/api/agent/status",body=b"",nonce="c"*32)
request=urllib.request.Request(base,headers=sig)
with urllib.request.urlopen(request,timeout=4) as response:
    assert json.load(response)["status"]=="ok"
try: urllib.request.urlopen(request,timeout=4)
except urllib.error.HTTPError as e: assert e.code==401
else: raise AssertionError("Nonce replay was accepted")
# Real Node Agent, same bundled FRP/Backhaul binaries: NO engine may be
# considered installed without an explicit root-owned manifest.
inventory_url="http://127.0.0.1:8888/api/agent/engines"
sig=sign_request(secret=secret,node_id=node,method="GET",
                 target="/api/agent/engines",body=b"",nonce="e"*32)
with urllib.request.urlopen(urllib.request.Request(inventory_url,headers=sig),timeout=4) as response:
    actual=json.load(response)
assert actual["mode"]=="managed"
assert set(actual["engines"])=={"backhaul","frp","gost","rathole","chisel"}
assert set(actual["engines"].values())=={"not-installed"}
# Even an AUTHENTICATED tunnel Apply cannot start a bundled engine.
apply_url="http://127.0.0.1:8888/api/agent/tunnels/apply"
body=json.dumps({"tunnel_id":"not-installed","core":"backhaul","type":"tcp","spec":{}},
                sort_keys=True,separators=(",",":")).encode("ascii")
sig=sign_request(secret=secret,node_id=node,method="POST",
                 target="/api/agent/tunnels/apply",body=body,nonce="f"*32)
req=urllib.request.Request(
    apply_url, data=body,
    headers={**sig, "Content-Type": "application/json"}, method="POST"
)
try:
    urllib.request.urlopen(req,timeout=4)
except urllib.error.HTTPError as e:
    assert e.code==409, e.code
else:
    raise AssertionError("Bundled but not enrolled Backhaul was activated")
PY
echo "STAGE29_REAL_KH_NO_ENGINE_BUNDLED_APPLY=DENIED"
sudo test -s "$replay_dir/agent-replay.sqlite3"
test "$(sudo stat -c %a "$replay_dir/agent-replay.sqlite3")" = 600
test "$(sudo sha256sum "$identity_dir/node-identity.json" | awk '{print $1}')" = "$identity_sha"
test "$(sudo sha256sum "$identity_dir/replay-enrollment.json" | awk '{print $1}')" = "$marker_sha"
replay_sha="$(sudo sha256sum "$replay_dir/agent-replay.sqlite3" | awk '{print $1}')"
echo "STAGE24_COMPOSE_SIGNED_READONLY_HMAC=PASS"

# Phase C: idempotent rollback by dropping ONLY the security overlay.
# Credentials and nonce DB must NOT be discarded or legacy auth reinstated.
paused up -d --force-recreate --no-build >/dev/null
wait_node
check_no_network
probe <<'PY'
import os,urllib.request,urllib.error
assert os.getenv("SMITE_NODE_PANEL_AUTH_MODE")=="paused"
assert os.getenv("SMITE_AGENT_AUTH_MODE")=="strict"
assert not os.path.exists("/run/smite-node-identity/node-identity.json")
try: urllib.request.urlopen("http://127.0.0.1:8888/api/agent/status",timeout=4)
except urllib.error.HTTPError as e: assert e.code==503
else: raise AssertionError("Rollback enabled legacy Agent route")
PY
test "$(sudo sha256sum "$identity_dir/node-identity.json" | awk '{print $1}')" = "$identity_sha"
test "$(sudo sha256sum "$replay_dir/agent-replay.sqlite3" | awk '{print $1}')" = "$replay_sha"
echo "STAGE24_COMPOSE_ROLLBACK_TO_PAUSED=PASS"

# Phase D: signed is re-enabled with the original key AND durable nonce DB.
signed up -d --force-recreate --no-build >/dev/null
wait_node
check_no_network
probe <<'PY'
import json,urllib.error,urllib.request
from app.agent_auth import read_identity
from app.node_auth import sign_request
node,secret=read_identity("/run/smite-node-identity/node-identity.json")
url="http://127.0.0.1:8888/api/agent/status"
def call(nonce):
    sig=sign_request(secret=secret,node_id=node,method="GET",
                     target="/api/agent/status",body=b"",nonce=nonce)
    return urllib.request.urlopen(urllib.request.Request(url,headers=sig),timeout=4)
try: call("c"*32)
except urllib.error.HTTPError as e: assert e.code==401
else: raise AssertionError("Nonce DB was replaced on re-enable")
with call("d"*32) as response:
    assert json.load(response)["status"]=="ok"
PY
test "$(sudo sha256sum "$identity_dir/node-identity.json" | awk '{print $1}')" = "$identity_sha"
test "$(sha256sum "$base" | awk '{print $1}')" = "$baseline_sha"

echo "STAGE24_COMPOSE_REENABLE_DURABLE_REPLAY=PASS"
test "$(sudo sha256sum "$identity_dir/replay-enrollment.json" | awk '{print $1}')" = "$marker_sha"
check_signed_mounts

# Phase E: on a DISPOSABLE runner only, simulate losing the entire replay
# SQLite file while retaining the independent paired identity + marker.
# The container must NOT generate a new DB, including on force-recreate.
signed down --remove-orphans >/dev/null
sudo mv "$replay_dir/agent-replay.sqlite3" "$lab/held-replay-for-cleanup.sqlite3"
test ! -e "$replay_dir/agent-replay.sqlite3"
signed up -d --force-recreate --no-build >/dev/null
wait_node
check_no_network
check_signed_mounts
probe <<'PY'
import urllib.error, urllib.request
from app.agent_auth import read_identity
from app.node_auth import sign_request
node,secret=read_identity("/run/smite-node-identity/node-identity.json")
target="/api/agent/status"
signature=sign_request(secret=secret,node_id=node,method="GET",target=target,
                       body=b"",nonce="b"*32)
request=urllib.request.Request("http://127.0.0.1:8888"+target,headers=signature)
try: urllib.request.urlopen(request,timeout=4)
except urllib.error.HTTPError as error: assert error.code==503,error.code
else: raise AssertionError("Lost replay database accepted signed traffic")
PY
test ! -e "$replay_dir/agent-replay.sqlite3"
test "$(sudo sha256sum "$identity_dir/replay-enrollment.json" | awk '{print $1}')" = "$marker_sha"
# A second, explicit first-enrollment attempt MUST fail due to the marker:
# never fabricate a blank Replay DB from the same Node identity.
if sudo docker run --rm --network none --cap-drop ALL \
    --security-opt no-new-privileges \
    --mount "type=bind,source=$identity_dir,target=/run/smite-node-identity" \
    --mount "type=bind,source=$replay_dir,target=/var/lib/smite-node/auth" \
    --entrypoint python3 smite-node:stage15-local \
    -m app.replay_enrollment \
    --identity /run/smite-node-identity/node-identity.json \
    --replay-db /var/lib/smite-node/auth/agent-replay.sqlite3 \
    --confirm-first-provision > "$lab/second-enrollment.txt" 2>&1; then
  echo "HOLD: Previous Node identity was illegally re-enrolled after DB loss" >&2
  exit 1
fi
grep -q '^HOLD: Replay enrollment already started' "$lab/second-enrollment.txt"
test ! -e "$replay_dir/agent-replay.sqlite3"
echo "STAGE24_REPLAY_VOLUME_LOSS_FAIL_CLOSED=PASS"
echo "STAGE24_NO_BOOTSTRAP_ON_RECREATE=PASS"
echo "STAGE24_FRP_BACKHAUL_TLS_REAL_IR_KH=NOT_TESTED"
echo "STAGE24_HOST_NETWORK_AND_PORTS=UNTOUCHED"
