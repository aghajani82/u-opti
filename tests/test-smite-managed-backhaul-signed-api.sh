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
engine="${SMITE_CI_ENGINE:-backhaul}"
case "$engine" in backhaul|frp) ;; *) echo "HOLD: unknown CI-only engine" >&2; exit 2 ;; esac
existing_frp="${SMITE_CI_EXISTING_FRP:-0}"
case "$existing_frp" in 0) ;; 1) [[ "$engine" == backhaul ]] || exit 2 ;; *) exit 2 ;; esac
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
if [[ "$engine" == "backhaul" ]]; then
  prefix="backhaul-txn-"
else
  prefix="uopti-official-frp-"
fi
[[ -d "$lab" && ! -L "$lab" &&
   "$lab" == "${RUNNER_TEMP:?}"/"$prefix"* ]] || {
  echo "HOLD: invalid disposable Node directory" >&2
  exit 2
}
[[ "$(sudo cat "$lab/EXPERIMENTAL-LAB")" == U-OPTI-BACKHAUL-ISOLATED-LAB-V1 ]] || {
  echo "HOLD: expected private lab marker missing" >&2
  exit 2
}

if [[ "$engine" == "backhaul" ]]; then
  if [[ "$phase" == ready ]]; then
    binary="$lab/installed/backhaul"
    sudo test -f "$lab/node/config/engine-state/engines.json"
  else
    binary="$(sudo find "$lab/stages" -mindepth 2 -maxdepth 2 -type f -name backhaul.bin -print -quit)"
    if [[ "$existing_frp" == 1 ]]; then
      sudo test -f "$lab/node/config/engine-state/engines.json"
    else
      sudo test ! -e "$lab/node/config/engine-state/engines.json"
    fi
  fi
  if [[ "$existing_frp" == 1 ]]; then
    sudo test -f "$lab/installed/frp/frpc"
    sudo test -f "$lab/installed/frp/frps"
  fi
  [[ -n "$binary" ]] && sudo test -f "$binary" || {
    echo "HOLD: Backhaul trial binary missing" >&2
    exit 2
  }
else
  if [[ "$phase" == ready ]]; then
    sudo test -f "$lab/node/config/engine-state/engines.json"
    sudo test -f "$lab/installed/frp/frpc"
    sudo test -f "$lab/installed/frp/frps"
  else
    sudo test ! -e "$lab/node/config/engine-state/engines.json"
    sudo test ! -e "$lab/installed/frp/frpc"
    sudo test ! -e "$lab/installed/frp/frps"
  fi
fi

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
compose_mode="${SMITE_CI_COMPOSE_RECREATE:-0}"
compose_file="$lab/smite-node-isolated-$phase.json"
project="uopti-bh-${GITHUB_RUN_ID:?}-$phase"
case "$compose_mode" in 0|1) ;; *) echo "HOLD: unknown trial mode" >&2; exit 2 ;; esac
cleanup() {
  if [[ "$compose_mode" == 1 ]]; then
    if [[ -f "$compose_file" ]]; then
      sudo docker compose -p "$project" -f "$compose_file" down --remove-orphans >/dev/null 2>&1 || :
    fi
    # Always unlink this disposable plan (even if Compose modified
    # or replaced its file between the initial existence test and here).
    sudo rm -f -- "$compose_file" || {
      echo "HOLD: PRIVATE_COMPOSE_FILE_CLEANUP_FAILED" >&2
      return 2
    }
  else
    sudo docker rm -f "$name" >/dev/null 2>&1 || :
  fi
}
trap cleanup EXIT
if [[ "$compose_mode" == 1 ]]; then
  sudo docker compose -f "$lab/node/docker-compose.yml" config --format json |
    sudo env GITHUB_ACTIONS=true GITHUB_EVENT_NAME=pull_request \
      GITHUB_REPOSITORY="${GITHUB_REPOSITORY:?}" RUNNER_TEMP="${RUNNER_TEMP:?}" \
      SMITE_CI_EXISTING_FRP="$existing_frp" \
      python3 "$root/tests/smite-managed-backhaul-compose-fixture.py" \
      "$lab" "$phase" "${GITHUB_RUN_ID:?}" "$smite" "$compose_file" "$engine"
  sudo docker compose -p "$project" -f "$compose_file" config --quiet
  sudo docker compose -p "$project" -f "$compose_file" up -d --no-build --force-recreate --no-deps smite-node >/dev/null
else
  if [[ "$engine" != "backhaul" ]]; then
    echo "HOLD: FRP test requires isolated Docker Compose" >&2
    exit 2
  fi
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
fi

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
sudo docker inspect --format '{{json .Mounts}}' "$name" | python3 -c '
import json,sys,os
mounts=json.load(sys.stdin)
root,phase,smite,engine=sys.argv[1:]
wanted={"/etc/smite-node":root+"/node/config","/var/lib/smite-node":root+"/node-data",
        "/app/main.py":smite+"/node/main.py","/app/app":smite+"/node/app"}
if os.environ.get("SMITE_CI_COMPOSE_RECREATE")=="1":
    expected=set(wanted)
    dual=os.environ.get("SMITE_CI_EXISTING_FRP")=="1"
    chosen=(["/usr/local/bin/backhaul"] if engine=="backhaul"
            else ["/usr/local/bin/frpc","/usr/local/bin/frps"])
    if phase=="ready": expected.update(chosen)
    if dual: expected.update(["/usr/local/bin/frpc","/usr/local/bin/frps"])
    relevant=[m for m in mounts if m["Destination"] in expected]
    assert {m["Destination"] for m in relevant}==expected, relevant
    for m in relevant:
        if m["Destination"]=="/usr/local/bin/backhaul":
            assert engine=="backhaul"
            assert m["Source"]==root+"/installed/backhaul" and m["RW"] is False
        elif m["Destination"] in ("/usr/local/bin/frpc","/usr/local/bin/frps"):
            assert engine=="frp" or dual
            assert m["Source"]==root+"/installed/frp/"+m["Destination"].rsplit("/",1)[-1] and m["RW"] is False
        else: assert m["Source"]==wanted[m["Destination"]]
    forbidden=([] if dual else
               ["/usr/local/bin/frpc","/usr/local/bin/frps"]
               if engine=="backhaul" else ["/usr/local/bin/backhaul"])
    assert not any(m["Destination"] in forbidden for m in mounts)
print("NODE_ACTUAL_DOCKER_MOUNTS_VERIFIED=PASS")
' "$lab" "$phase" "$smite" "$engine"
for attempt in $(seq 1 16); do
  if sudo docker exec "$name" python -c     "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8888/healthz', timeout=2)" \
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
    --env "EXPECTED_ENGINE_NAME=$engine" \
    --env "EXPECTED_EXISTING_FRP=$existing_frp" \
    --env "PROBE_MODE=$check_mode" "$name" python -B - <<'PY_PROBE'
import json, os, urllib.error, urllib.request
from app.agent_auth import read_identity
from app.node_auth import sign_request

base = "http://127.0.0.1:8888"
identity, secret = read_identity("/etc/smite-node/identity/node-identity.json")
phase = os.environ["EXPECTED_ENGINE_STATE"]
engine = os.environ["EXPECTED_ENGINE_NAME"]
dual = os.environ["EXPECTED_EXISTING_FRP"] == "1"
mode = os.environ["PROBE_MODE"]
replay_file = "/var/lib/smite-node/auth/last-signed-request.json"

def request(method, endpoint, body=b"", headers=None):
    req = urllib.request.Request(
        base + endpoint,
        data=body if method == "POST" else None,
        method=method,
        headers={
            **(headers or {}),
            **({"Content-Type": "application/json"} if method == "POST" else {}),
        },
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
assert inventory["engines"][engine] == expect, inventory
if dual:
    assert engine == "backhaul", engine
    assert inventory["engines"]["frp"] == "ready", inventory
assert all(state == "not-installed" for name, state in inventory["engines"].items()
           if name != engine and not (dual and name == "frp")), inventory
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
# A selected engine is never actually started in the PR trial. For
# installed mode, do NOT submit an Apply that could run the executable.
# Only absent engines must reliably reject Apply before tunnel creation.
if engine == "backhaul":
    if not dual:
        denied_apply("frp")
    if phase != "ready":
        denied_apply("backhaul")
else:
    denied_apply("backhaul")
    if phase != "ready":
        denied_apply("frp")
status, content = request("GET", "/api/agent/status",
                          headers=signed("GET", "/api/agent/status"))
assert status == 200, (status, content[:160])
assert json.loads(content)["active_tunnels"] == 0
print("SIGNED_API_" + engine.upper() + "_" + phase.upper() + "_" + mode.upper() + "=PASS")
if dual:
    print("SIGNED_EXISTING_FRP_" + phase.upper() + "_" + mode.upper() + "=PASS")
PY_PROBE
}
assert_docker_health() {
  if [[ "$compose_mode" != 1 ]]; then return 0; fi
  local status
  for attempt in $(seq 1 25); do
    status="$(sudo docker inspect -f '{{.State.Health.Status}}' "$name")"
    if [[ "$status" == healthy ]]; then
      echo "STRICT_NODE_DOCKER_HEALTHY_${phase^^}=PASS"
      return 0
    fi
    sleep 1
  done
  echo "FAIL: strict-mode local Docker health never became healthy" >&2
  return 1
}
assert_docker_health
probe initial
if [[ "$compose_mode" == 1 ]]; then
  sudo docker compose -p "$project" -f "$compose_file" up -d --no-build --force-recreate --no-deps smite-node >/dev/null
else
  sudo docker restart "$name" >/dev/null
fi
for attempt in $(seq 1 16); do
  if sudo docker exec "$name" python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8888/healthz', timeout=2)" \
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
assert_docker_health
probe after-restart
echo "SIGNED_NODE_API_${phase^^}_RESTART=PASS"
if [[ "$compose_mode" == 1 ]]; then
  echo "SIGNED_NODE_COMPOSE_${phase^^}_RECREATED=PASS"
fi
# Explicitly stop disposable Node and remove the temporary Compose file.
# Keep the EXIT cleanup handler as a fallback until this postcondition passes.
cleanup
if [[ "$compose_mode" == 1 ]]; then
  # A second unconditional unlink is intentionally idempotent: a restarted
  # compose client may still have held the plan during docker compose down.
  sudo rm -f -- "$compose_file"
  if sudo test -e "$compose_file"; then
    echo "HOLD: PRIVATE_COMPOSE_FILE_REMAINS_AFTER_CLEANUP" >&2
    exit 2
  fi
fi
trap - EXIT
echo "SIGNED_NODE_PRIVATE_COMPOSE_CLEANUP=PASS"
