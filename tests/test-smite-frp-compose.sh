#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Exercise the real installer helper offline using disposable Compose fixtures.
source modules/smite-install.sh
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
SMITE_FRP_BIN_DIR="$tmp/bin"
mkdir -p "$SMITE_FRP_BIN_DIR"
for name in frpc frps; do
    printf '#!/bin/sh\nprintf "0.71.0\\n"\n' > "$SMITE_FRP_BIN_DIR/$name"
    chmod 0755 "$SMITE_FRP_BIN_DIR/$name"
done

cat > "$tmp/panel.yml" <<'YAML'
services:
  smite-panel:
    image: ghcr.io/zzedix/smite-panel@sha256:test
    network_mode: host
    volumes:
      - ./panel/data:/app/data
    restart: unless-stopped
  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx:/etc/nginx:ro
YAML

cat > "$tmp/node.yml" <<'YAML'
services:
  smite-node:
    image: ghcr.io/zzedix/smite-node@sha256:test
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
    restart: unless-stopped
volumes:
  node-data:
    driver: local
YAML

smite_frp_mount_compose "$tmp/panel.yml" smite-panel
smite_frp_mount_compose "$tmp/node.yml" smite-node
# A second call should not add duplicate mounts.
smite_frp_mount_compose "$tmp/panel.yml" smite-panel
smite_frp_mount_compose "$tmp/node.yml" smite-node

grep -Fq "      - $SMITE_FRP_BIN_DIR/frps:/usr/local/bin/frps:ro" "$tmp/panel.yml"
! grep -Fq ':/usr/local/bin/frpc' "$tmp/panel.yml"
grep -Fq "      - $SMITE_FRP_BIN_DIR/frpc:/usr/local/bin/frpc:ro" "$tmp/node.yml"
grep -Fq "      - $SMITE_FRP_BIN_DIR/frps:/usr/local/bin/frps:ro" "$tmp/node.yml"
[ "$(grep -Fc ':/usr/local/bin/frps:ro' "$tmp/panel.yml")" -eq 1 ]
[ "$(grep -Fc ':/usr/local/bin/frpc:ro' "$tmp/node.yml")" -eq 1 ]
[ "$(grep -Fc ':/usr/local/bin/frps:ro' "$tmp/node.yml")" -eq 1 ]
grep -Fq '  nginx:' "$tmp/panel.yml"
grep -Fq 'volumes:' "$tmp/node.yml"

docker() {
    [ "$1" = exec ] || return 1
    case "$3" in
        /usr/local/bin/frps|/usr/local/bin/frpc) echo 0.71.0 ;;
        *) return 1 ;;
    esac
}
smite_frp_verify_container smite-panel
smite_frp_verify_container smite-node

# Fail closed when the generated file already mounts a different FRP binary.
sed -i "s#$SMITE_FRP_BIN_DIR/frpc:/usr/local/bin/frpc:ro#/unexpected/frpc:/usr/local/bin/frpc:ro#" "$tmp/node.yml"
if smite_frp_mount_compose "$tmp/node.yml" smite-node; then
    echo "ERROR: A conflicting mount was accepted." >&2
    exit 1
fi
echo "Smite FRP Compose helper tests passed."
