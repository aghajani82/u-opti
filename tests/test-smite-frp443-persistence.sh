#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export SMITE_STATE_DIR="$tmp/state"
export SMITE_GATEWAY_BACKEND_CONF="$tmp/backend.conf"
export SMITE_GATEWAY_STREAM_CONF="$tmp/stream.conf"
export SMITE_GATEWAY_MAP_FILE="$tmp/regular-map.conf"
export SMITE_GATEWAY_FRP_SNI_MAP_FILE="$tmp/frp-map.conf"
source "$root/modules/smite-gateway.sh"

cat > "$SMITE_GATEWAY_BACKEND_CONF" <<'EOF_BACKEND'
# Managed by U-OPTI - Smite Panel TLS backend
server {
    listen 127.0.0.1:8443 ssl;
    server_name ir.kolbe1.ir;
    ssl_certificate /etc/letsencrypt/live/ir.kolbe1.ir/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ir.kolbe1.ir/privkey.pem;
    location /19001/web {
        proxy_pass http://127.0.0.1:19001;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
EOF_BACKEND
cp "$SMITE_GATEWAY_BACKEND_CONF" "$tmp/backend.expected"
smite_gateway_write_backend "ir.kolbe1.ir"
cmp -s "$SMITE_GATEWAY_BACKEND_CONF" "$tmp/backend.expected"
if smite_gateway_write_backend "unexpected.ir.kolbe1.ir"; then
    echo "ERROR: A different domain must not overwrite custom XHTTP locations"
    exit 1
fi
cmp -s "$SMITE_GATEWAY_BACKEND_CONF" "$tmp/backend.expected"

cat > "$SMITE_GATEWAY_STREAM_CONF" <<'EOF_STREAM'
# Managed by U-OPTI - Smite TCP/443 SNI gateway
stream {
    map $ssl_preread_server_name $uopti_smite_backend {
        include /etc/nginx/u-opti-smite-stream-map.conf;
        default 127.0.0.1:8443;
    }
    map "$ssl_preread_server_name|$remote_addr" $uopti_frp_canary_backend {
        "frp-file.ir.kolbe1.ir|127.0.0.1" 127.0.0.1:17000;
        "frp-file.ir.kolbe1.ir|91.107.185.50" 127.0.0.1:17000;
        "frp-xhttp.ir.kolbe1.ir|127.0.0.1" 127.0.0.1:17001;
        "frp-xhttp.ir.kolbe1.ir|91.107.185.50" 127.0.0.1:17001;
        default $uopti_smite_backend;
    }
    server {
        listen 127.0.0.1:14443;
        ssl_preread on;
        proxy_pass $uopti_frp_canary_backend;
    }
    server {
        listen 443;
        ssl_preread on;
        proxy_pass $uopti_frp_canary_backend;
    }
}
EOF_STREAM

smite_gateway_write_stream "ir.kolbe1.ir"
test "$(grep -cE '^[[:space:]]*"frp-' "$SMITE_GATEWAY_FRP_SNI_MAP_FILE")" -eq 4
grep -Fq 'include '"$SMITE_GATEWAY_FRP_SNI_MAP_FILE"';' "$SMITE_GATEWAY_STREAM_CONF"
grep -Fq 'listen 127.0.0.1:14443;' "$SMITE_GATEWAY_STREAM_CONF"
grep -Fq 'proxy_pass $uopti_frp_canary_backend;' "$SMITE_GATEWAY_STREAM_CONF"
smite_gateway_write_stream "ir.kolbe1.ir"
test "$(grep -cE '^[[:space:]]*"frp-' "$SMITE_GATEWAY_FRP_SNI_MAP_FILE")" -eq 4
test "$(grep -Fc 'listen 127.0.0.1:14443;' "$SMITE_GATEWAY_STREAM_CONF")" -eq 1

# Bad manual routes must fail closed before replacing Nginx config.
rm -f "$SMITE_GATEWAY_FRP_SNI_MAP_FILE"
cat > "$SMITE_GATEWAY_STREAM_CONF" <<'EOF_BAD'
stream {
    map "$ssl_preread_server_name|$remote_addr" $uopti_frp_canary_backend {
        "frp-file.ir.kolbe1.ir|91.107.185.50" 0.0.0.0:17000;
        default $uopti_smite_backend;
    }
}
EOF_BAD
cp "$SMITE_GATEWAY_STREAM_CONF" "$tmp/bad.expected"
if smite_gateway_write_stream "ir.kolbe1.ir"; then
    echo "ERROR: Unsafe legacy FRP map unexpectedly accepted"
    exit 1
fi
cmp -s "$SMITE_GATEWAY_STREAM_CONF" "$tmp/bad.expected"

# Reconcile the old host-side Smite adapter without touching a live container.
export SMITE_OVERLAY_DIR="$tmp/overlays"
mkdir -p "$SMITE_OVERLAY_DIR/node"
cat > "$SMITE_OVERLAY_DIR/node/core_adapters.py" <<'PY_ADAPTER'
from pathlib import Path

class FrpAdapter:
    def apply(self, spec):
        if spec.get("mode") == "client":
            bind_port = spec.get('bind_port', 7000)
            token = spec.get('token')
            config_content = f"""bindPort: {bind_port}
"""
            server_addr = spec.get('server_addr', '').strip()
            server_port = spec.get('server_port', 7000)
            token = spec.get('token')
            config_content = "serverPort: {}\n".format(server_port)
            config_content += "\nproxies:\n"
PY_ADAPTER
source "$root/modules/smite.sh"
docker() {
    if [ "$#" -eq 5 ] && [ "$1" = "exec" ] && [ "$2" = "smite-node" ] &&
       [ "$3" = "test" ] && [ "$4" = "-f" ]; then
        return 0
    fi
    return 1
}
smite_patch_frp443_overlay
grep -Fq "server_port = frp_client_server_port(spec," "$SMITE_OVERLAY_DIR/node/core_adapters.py"
grep -Fq "tls_transport = frp_tls_transport_yaml(spec)" "$SMITE_OVERLAY_DIR/node/core_adapters.py"
grep -Fq "config_content += tls_transport" "$SMITE_OVERLAY_DIR/node/core_adapters.py"
cp "$SMITE_OVERLAY_DIR/node/core_adapters.py" "$tmp/adapter.expected"
smite_patch_frp443_overlay
cmp -s "$SMITE_OVERLAY_DIR/node/core_adapters.py" "$tmp/adapter.expected"

echo "PASS: Smite FRP 443 routes, backend, and compatibility persist across repair"
