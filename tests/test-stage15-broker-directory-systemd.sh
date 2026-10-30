#!/usr/bin/env bash
# Disposable GitHub runner only. Never touches the real Smite service/paths.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && $EUID == 0 ]]
lab=$(mktemp -d)
unit="stage15-socket-fixture-$$.service"
name="stage15-socket-fixture-$$"
path="/etc/systemd/system/$unit"
runtime="/run/$name"
cleanup() {
  umount "$lab/view" 2>/dev/null || true
  systemctl stop "$unit" 2>/dev/null || true
  rm -f "$path"
  systemctl daemon-reload
  rm -rf -- "$lab" "$runtime"
}
trap cleanup EXIT
cat > "$lab/server.py" <<'PY'
import socket,sys,os,signal
path=sys.argv[1]
if os.path.exists(path):os.unlink(path)
s=socket.socket(socket.AF_UNIX);s.bind(path);s.listen(4)
def stop(*args):
    s.close();os.unlink(path);raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
while True:
    c,_=s.accept();c.sendall(b'OK');c.close()
PY
cat > "$path" <<EOF
[Unit]
Description=Disposable Stage15 socket inode regression
[Service]
ExecStart=/usr/bin/python3 $lab/server.py $runtime/broker.sock
RuntimeDirectory=$name
RuntimeDirectoryMode=0750
EOF
systemctl daemon-reload
systemctl start "$unit"
for attempt in {1..50}; do [[ -S "$runtime/broker.sock" ]] && break; sleep 0.1; done
[[ -S "$runtime/broker.sock" ]]
mkdir "$lab/view"
mount --bind "$runtime" "$lab/view"
before=$(stat -c '%d:%i' "$runtime")
# Same ordering as the real migration: preserve, daemon-reload, then stop.
printf '\nRuntimeDirectoryPreserve=yes\n' >> "$path"
systemctl daemon-reload
[[ $(systemctl show "$unit" --property=RuntimeDirectoryPreserve --value) == yes ]]
systemctl stop "$unit"
[[ $(stat -c '%d:%i' "$runtime") == "$before" ]]
systemctl start "$unit"
for attempt in {1..50}; do [[ -S "$lab/view/broker.sock" ]] && break; sleep 0.1; done
python3 - "$lab/view/broker.sock" <<'PY'
import socket,sys
s=socket.socket(socket.AF_UNIX);s.settimeout(3);s.connect(sys.argv[1]);assert s.recv(2)==b'OK'
PY
[[ $(stat -c '%d:%i' "$runtime") == "$before" ]]
echo 'BROKER_RESTART_WITHOUT_NODE_REMOUNT=PASS'
