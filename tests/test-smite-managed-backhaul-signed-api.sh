#!/usr/bin/env bash
# Disposable REAL Smite Node API (not just inventory function).
# PR CI only. No host networking, no published ports, no external Panel,
# no tunnel activation; tests signed GET and refused Apply via loopback.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != true ||
      "${GITHUB_EVENT_NAME:-}" != pull_request ||
      "${GITHUB_REPOSITORY:-}" != aghajani82/u-opti ]]; then
  echo "HOLD: signed Node API test is restricted to pull-request CI" >&2
  exit 2
fi

lab="${1:?requires isolated lab root}"
case "${2:-}" in
  absent|ready) phase="$2" ;;
  *) echo "HOLD: invalid Node API trial phase" >&2; exit 2 ;;
esac
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
smite="$root/.managed-smite-source"
[[ -f "$smite/node/main.py" &&
   -f "$smite/node/app/agent_auth.py" &&
   -f "$smite/node/app/core_adapters.py" ]] || {
  echo "HOLD: pinned reviewed Node API source missing" >&2
  exit 2
}
[[ -d "$lab" && ! -L "$lab" &&
   "$lab" == "${RUNNER_TEMP:?}"/backhaul-txn-* ]] || {
  echo "HOLD: invalid disposable Node directory" >&2
  exit 2
}
[[ "$(sudo cat "$lab/EXPERIMENTAL-LAB")" == U-OPTI-BACKHAUL-ISOLATED-LAB-V1 ]] || {
  echo "HOLD: expected private lab marker missing" >&2
  exit 2
}

if [[ "$phase" == ready ]]; then
  binary="$lab/installed/backhaul"
  sudo test -f "$lab/node/config/engine-state/engines.json"
else
  binary="$(sudo find "$lab/stages" -mindepth 2 -maxdepth 2 -type f -name backhaul.bin -print -quit)"
  sudo test ! -e "$lab/node/config/engine-state/engines.json"
fi
[[ -n "$binary" ]] && sudo test -f "$binary" || {
  echo "HOLD: Backhaul trial binary missing" >&2
  exit 2
}

# Never share a real pairing secret. This synthetic identity is generated only
# for a throwaway private Docker container and is never printed.
sudo install -d -m 0700 "$lab/node/config/identity" "$lab/node-data" "$lab/node-data/auth"
if ! sudo test -e "$lab/node/config/identity/node-identity.json"; then
  sudo python3 - "$lab/node/config/identity/node-identity.json" <<'PY_IDENTITY'
import json, os, secrets, sys
dest = sys.argv[1]
fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as stream:
    json.dump({"node_id": "smitecibackhaul01",
               "node_secret": secrets.token_hex(32)}, stream)
    stream.flush()
    os.fsync(stream.fileno())
PY_IDENTITY
fi

image="ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
name="uopti-managed-api-${GITHUB_RUN_ID:?}-${phase}"
cleanup() {
  sudo docker rm -f "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT
sudo docker run -d --name "$name" \
  --platform linux/amd64 \
  --network none --read-only --cap-drop ALL --pids-limit 96 --memory 384m \
  --security-opt no-new-privileges --user 0:0 \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --env SMITE_AGENT_AUTH_MODE=strict \
  --env SMITE_NODE_PANEL_AUTH_MODE=paused \
  --env SMITE_ENGINE_INVENTORY_MODE=managed \
  --env SMITE_AGENT_IDENTITY_PATH=/etc/smite-node/identity/node-identity.json \
  --env SMITE_AGENT_REPLAY_DB=/var/lib/smite-node/auth/agent-replay.sqlite3 \
  --env SMITE_ENGINE_MANIFEST_PATH=/etc/smite-node/engine-state/engines.json \
  --env NODE_API_PORT=8888 \
  --mount "type=bind,src=$smite/node/app,dst=/app/app,readonly" \
  --mount "type=bind,src=$smite/node/main.py,dst=/app/main.py,readonly" \
  --mount "type=bind,src=$lab/node/config,dst=/etc/smite-node" \
  --mount "type=bind,src=$lab/node-data,dst=/var/lib/smite-node" \
  --mount "type=bind,src=$binary,dst=/usr/local/bin/backhaul,readonly" \
  --entrypoint python "$image" -m uvicorn main:app \
  --host 127.0.0.1 --port 8888 --no-access-log >/dev/null

# Prove no host port was published, and Docker's network namespace is isolated.
sudo docker inspect --format '{{json .HostConfig}}' "$name" | python3 -c '
import json, sys
host = json.load(sys.stdin)
assert host["NetworkMode"] == "none", "Unexpected Node network exposure"
assert not host.get("PortBindings"), "Node published a host port"
assert host.get("ReadonlyRootfs") is True, "Container root is writable"
assert host.get("CapDrop") == ["ALL"], "Unexpected Linux capabilities"
print("SIGNED_NODE_NETWORK_NONE_NO_HOST_PORTS=PASS")
'
for attempt in $(seq 1 16); do
  if sudo docker exec "$name" python -c     "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8888/', timeout=2)" \
    >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == 16 ]]; then
    sudo docker logs --tail 40 "$name" >&2 || true
    echo "FAIL: actual strict Node never became healthy" >&2
    exit 1
  fi
  sleep 1
done

# Only the actual reviewed signed endpoint and its real auth/replay system are
# exercised. A successful Backhaul Apply is intentionally NEVER attempted.
probe() {
  local check_mode="$1"
  sudo docker exec -i --env "EXPECTED_ENGINE_STATE=$phase" \
    --env "PROBE_MODE=$check_mode" "$name" python -B - <<'PY_PROBE'
import json, os, urllib.error, urllib.request
from app.agent_auth import read_identity
from app.node_auth import sign_request

base = "http://127.0.0.1:8888"
identity, secret = read_identity("/etc/smite-node/identity/node-identity.json")
phase = os.environ["EXPECTED_ENGINE_STATE"]
mode = os.environ["PROBE_MODE"]
replay_file = "/var/lib/smite-node/auth/last-signed-request.json"

def request(method, endpoint, body=b"", headers=None):
    req = urllib.request.Request(
        base + endpoint,
        data=body if method == "POST" else None,
        method=method,
        headers=headers or {},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()

def signed(method, endpoint, body=b"", *, key=None):
    signature = sign_request(
        secret=secret if key is None else key,
        node_id=identity, method=method, target=endpoint, body=body,
    )
    return signature

endpoint = "/api/agent/engines"
if mode == "after-restart":
    with open(replay_file, encoding="utf-8") as f:
        old_headers = json.load(f)
    assert request("GET", endpoint, headers=old_headers)[0] == 401, "replay accepted after Node restart"
else:
    assert request("GET", endpoint)[0] == 401, "unsigned inventory accepted"
    assert request("GET", endpoint, headers=signed("GET", endpoint, key="a"*64))[0] == 401, "wrong signature accepted"

headers = signed("GET", endpoint)
status, payload = request("GET", endpoint, headers=headers)
assert status == 200, ("signed status", status, payload[:140])
inventory = json.loads(payload)
assert inventory["mode"] == "managed"
assert set(inventory["engines"]) == {"backhaul", "frp", "gost", "rathole", "chisel"}
expect = "ready" if phase == "ready" else "not-installed"
assert inventory["engines"]["backhaul"] == expect, inventory
assert all(state == "not-installed" for name, state in inventory["engines"].items()
           if name != "backhaul"), inventory
assert request("GET", endpoint, headers=headers)[0] == 401, "nonce replay accepted"

if mode == "initial":
    with open(replay_file, "w", encoding="utf-8") as f:
        json.dump(headers, f)
    os.chmod(replay_file, 0o600)

def denied_apply(core):
    endpoint = "/api/agent/tunnels/apply"
    body = json.dumps({
        "tunnel_id": "ci-denied-no-tunnel-start",
        "core": core, "type": "tcp", "spec": {},
    }, separators=(",", ":")).encode()
    status, content = request("POST", endpoint, body=body,
                              headers=signed("POST", endpoint, body))
    assert status == 409, (core, status, content[:160])
denied_apply("frp")
if phase != "ready":
    denied_apply("backhaul")
status, content = request("GET", "/api/agent/status",
                          headers=signed("GET", "/api/agent/status"))
assert status == 200, (status, content[:160])
assert json.loads(content)["active_tunnels"] == 0
print("SIGNED_API_BACKHAUL_" + phase.upper() + "_" + mode.upper() + "=PASS")
PY_PROBE
}
probe initial
sudo docker restart "$name" >/dev/null
for attempt in $(seq 1 16); do
  if sudo docker exec "$name" python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8888/', timeout=2)" \
    >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == 16 ]]; then
    sudo docker logs --tail 40 "$name" >&2 || true
    echo "FAIL: signed Node failed its own restart" >&2
    exit 1
  fi
  sleep 1
done
probe after-restart
echo "SIGNED_NODE_API_${phase^^}_RESTART=PASS"
