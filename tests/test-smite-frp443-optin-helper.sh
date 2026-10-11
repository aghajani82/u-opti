#!/usr/bin/env bash
# Standard FRP trial must work with pinned upstream images lacking the helper.
# Private Network Wizard and regular Smite setups never get the trial overlay.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export SMITE_OVERLAY_DIR="$tmp/overlay"
export SMITE_NODE_COMPOSE="$tmp/node-compose.yml"
export SMITE_PANEL_COMPOSE="$tmp/no-panel.yml"
mkdir -p "$SMITE_OVERLAY_DIR/node"
source "$root/modules/smite.sh"

cat > "$SMITE_OVERLAY_DIR/node/core_adapters.py" <<'PY'
from pathlib import Path
class FrpAdapter:
    def apply(self, spec):
        server_port = spec.get('server_port', 7000)
        config_content = "serverPort: {}\n".format(server_port)
        config_content += "\nproxies:\n"
PY
cp "$SMITE_OVERLAY_DIR/node/core_adapters.py" "$tmp/legacy"
docker() { return 1; }

# Missing helper leaves the upstream FRP behavior untouched.
smite_patch_frp443_overlay
cmp -s "$SMITE_OVERLAY_DIR/node/core_adapters.py" "$tmp/legacy"

# Explicit opt-in creates a syntax-valid helper and must not require
# publishing a new image; integration is a read-only Compose mount.
smite_prepare_frp443_trial_helper
test -s "$SMITE_OVERLAY_DIR/node/frp_gateway_config.py"
cp "$SMITE_OVERLAY_DIR/node/frp_gateway_config.py" "$tmp/expected"
smite_prepare_frp443_trial_helper
cmp -s "$SMITE_OVERLAY_DIR/node/frp_gateway_config.py" "$tmp/expected"

python3 - "$SMITE_OVERLAY_DIR/node/frp_gateway_config.py" <<'PY'
from pathlib import Path
import importlib.util
import sys
spec = importlib.util.spec_from_file_location("frp_gateway_config", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.frp_client_server_port({}, 17000) == 17000
assert module.frp_tls_transport_yaml({}) == ""
settings = {"frp_gateway_port": "443", "frp_tls_server_name": "frp.ir.example.test"}
assert module.frp_client_server_port(settings, 17000) == 443
result = module.frp_tls_transport_yaml(settings)
assert 'serverName: "frp.ir.example.test"' in result
assert "disableCustomTLSFirstByte: true" in result
for invalid in [
    {"frp_gateway_port": 443},
    {"frp_gateway_port": 0, "frp_tls_server_name": "frp.ir.example.test"},
    {"frp_gateway_port": True, "frp_tls_server_name": "frp.ir.example.test"},
    {"frp_tls_server_name": "invalid domain"},
    {"frp_tls_server_name": "127..0.0.1"},
]:
    try:
        module.frp_client_server_port(invalid, 17000)
        module.frp_tls_transport_yaml(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe FRP gateway setting was accepted")
print("PASS: FRP gateway helper is safe and backwards-compatible")
PY

smite_patch_frp443_overlay
grep -Fq 'frp_client_server_port(spec,' "$SMITE_OVERLAY_DIR/node/core_adapters.py"
grep -Fq 'frp_tls_transport_yaml(spec)' "$SMITE_OVERLAY_DIR/node/core_adapters.py"
cp "$SMITE_OVERLAY_DIR/node/core_adapters.py" "$tmp/patched"
smite_patch_frp443_overlay
cmp -s "$SMITE_OVERLAY_DIR/node/core_adapters.py" "$tmp/patched"

cat > "$SMITE_NODE_COMPOSE" <<'EOF_COMPOSE'
services:
  smite-node:
    volumes:
      - node-data:/var/lib/smite-node
EOF_COMPOSE
touch "$SMITE_OVERLAY_DIR/node/panel_client.py"
docker() {
    if [ "$1" = compose ] && [ "$3" = "$SMITE_NODE_COMPOSE" ] && [ "$4" = config ]; then
        return 0
    fi
    return 1
}
smite_patch_compose_mounts
grep -Fq "$SMITE_OVERLAY_DIR/node/frp_gateway_config.py:/app/app/frp_gateway_config.py:ro" "$SMITE_NODE_COMPOSE"
grep -Fq "$SMITE_OVERLAY_DIR/node/core_adapters.py:/app/app/core_adapters.py:ro" "$SMITE_NODE_COMPOSE"
cp "$SMITE_NODE_COMPOSE" "$tmp/compose.expected"
smite_patch_compose_mounts
cmp -s "$SMITE_NODE_COMPOSE" "$tmp/compose.expected"
echo "PASS: Standard FRP trial helper mounted idempotently without changing the default install Wizard"
