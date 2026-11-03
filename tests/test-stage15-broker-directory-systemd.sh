#!/usr/bin/env bash
# Disposable GitHub runner: real systemd + Docker bind inode orphan/recovery.
# NEVER run on IR or Grandoptical. No production container is addressed.
set -euo pipefail
[[ "$GITHUB_ACTIONS" == true && $EUID == 0 ]]
lab=$(mktemp -d)
suffix="$$"
unit="stage15-socket-fixture-$suffix.service"
name="stage15-socket-fixture-$suffix"
container="stage15-socket-view-$suffix"
path="/etc/systemd/system/$unit"
runtime="/run/$name"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  systemctl stop "$unit" 2>/dev/null || true
  rm -f -- "$path"
  systemctl daemon-reload
  rm -rf -- "$lab" "$runtime"
}
trap cleanup EXIT
command -v docker >/dev/null
docker info >/dev/null
cat > "$lab/server.py" <<'PY'
import socket,sys,os,importlib.util,pathlib
path=sys.argv[1]
spec=importlib.util.spec_from_file_location("fixture_broker",sys.argv[2])
broker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)
broker.SOCKET=pathlib.Path(path)
# Use the actual U-OPTI safe dead-socket lifecycle, never unconditional unlink.
broker._retire_dead_socket_at_start(0)
s=socket.socket(socket.AF_UNIX);s.bind(path);os.chmod(path,0o660);s.listen(4)
while True:
    c,_=s.accept();c.sendall(b'OK');c.close()
PY
cat > "$path" <<EOF
[Unit]
Description=Disposable Stage15 socket inode regression
[Service]
ExecStart=/usr/bin/python3 $lab/server.py $runtime/broker.sock $(pwd)/modules/smite-rc5-xhttp-root-broker.py
RuntimeDirectory=$name
RuntimeDirectoryMode=0750
EOF
systemctl daemon-reload
systemctl start "$unit"
for attempt in {1..50}; do [[ -S "$runtime/broker.sock" ]] && break; sleep 0.1; done
[[ -S "$runtime/broker.sock" ]]
# In the CI fixture only, a new disposable container pins the original inode.
docker pull busybox:1.36.1 >/dev/null
docker run -d --name "$container" --network none --read-only \
  --mount "type=bind,src=$runtime,dst=/run/u-opti/smite,readonly" \
  busybox:1.36.1 sleep 300 >/dev/null
host_before=$(stat -c '%d:%i' "$runtime")
node_before=$(docker exec "$container" stat -c '%d:%i' /run/u-opti/smite)
[[ "$host_before" == "$node_before" ]]
# Reproduce RC7 flaw: service restart with missing preservation. New host
# directory is created while Docker stays bound to the removed old inode.
systemctl restart "$unit"
for attempt in {1..50}; do [[ -S "$runtime/broker.sock" ]] && break; sleep 0.1; done
[[ -S "$runtime/broker.sock" ]]
host_after=$(stat -c '%d:%i' "$runtime")
node_stale=$(docker exec "$container" stat -c '%d:%i' /run/u-opti/smite)
[[ "$host_before" != "$host_after" ]]
[[ "$node_before" == "$node_stale" ]]
echo "ORIGINAL_RC7_DOCKER_BIND_ORPHANING=REPRODUCED"
# Apply the exact U-OPTI preservation directive before another broker stop.
printf '\nRuntimeDirectoryPreserve=yes\n' >> "$path"
systemctl daemon-reload
[[ $(systemctl show "$unit" --property=RuntimeDirectoryPreserve --value) == yes ]]
systemctl stop "$unit"
[[ $(stat -c '%d:%i' "$runtime") == "$host_after" ]]
# The current runtime directory must not move across a controlled restart.
# Remove a stopped socket ONLY after verifying its exact old inode.
python3 - "$runtime/broker.sock" <<'PY'
import importlib.util,pathlib,sys
spec=importlib.util.spec_from_file_location('fixture_migration',pathlib.Path('modules/smite-stage15-active-runtime.py').resolve())
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
p=pathlib.Path(sys.argv[1]);before=m.socket_identity(p,0)
assert before is not None
m.remove_stopped_socket(p,before,0)
assert not p.exists()
PY
systemctl start "$unit"
for attempt in {1..50}; do [[ -S "$runtime/broker.sock" ]] && break; sleep 0.1; done
[[ $(stat -c '%d:%i' "$runtime") == "$host_after" ]]
# In-place Docker restart, not recreate: container ID and image unchanged.
id_before=$(docker inspect -f '{{.Id}}' "$container")
image_before=$(docker inspect -f '{{.Image}}' "$container")
docker restart "$container" >/dev/null
[[ $(docker inspect -f '{{.Id}}' "$container") == "$id_before" ]]
[[ $(docker inspect -f '{{.Image}}' "$container") == "$image_before" ]]
[[ $(docker exec "$container" stat -c '%d:%i' /run/u-opti/smite) == "$host_after" ]]
[[ -S "$runtime/broker.sock" ]]
python3 - "$runtime/broker.sock" <<'PY'
import socket,sys
s=socket.socket(socket.AF_UNIX);s.settimeout(3);s.connect(sys.argv[1]);assert s.recv(2)==b'OK'
PY
systemctl restart "$unit"
for attempt in {1..50}; do [[ -S "$runtime/broker.sock" ]] && break; sleep 0.1; done
[[ $(stat -c '%d:%i' "$runtime") == "$host_after" ]]
[[ $(docker exec "$container" stat -c '%d:%i' /run/u-opti/smite) == "$host_after" ]]
echo "RC7_BROKER_SYSTEMD_DOCKER_REATTACH_AND_RESTART=PASS"
