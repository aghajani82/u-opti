#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export SMITE_BH_STAGE_ROOT="$tmp/staging"
export SMITE_BH_STATE_FILE="$tmp/state"
export SMITE_BH_OVERLAY_ROOT="$tmp/overlay"
mkdir -p "$tmp/overlay/node" "$tmp/overlay/panel"
printf 'SMITE_ROLE=panel-iran\nSMITE_CONNECTION_MODE=standard\n' > "$SMITE_BH_STATE_FILE"
cat > "$tmp/overlay/node/core_adapters.py" <<'PY'
from typing import Dict, Any
class RatholeAdapter:
    pass
class BackhaulAdapter:
    def apply(self, tunnel_id: str, spec: Dict[str, Any]):
        """Apply Backhaul tunnel - supports both server and client modes"""
        if tunnel_id in self.processes:
            self.remove(tunnel_id)
        mode = spec.get('mode', 'client')
        if mode == 'server':
            config_path.write_text(self._render_toml({"server": server_config}), encoding="utf-8")
            log_fh.write(self._render_toml({"server": server_config}))
        else:
            config_path.write_text(self._render_toml({"client": config_dict}), encoding="utf-8")
            log_fh.write(self._render_toml({"client": config_dict}))
class ChiselAdapter:
    pass
PY
cat > "$tmp/overlay/panel/node_client.py" <<'PY'
from typing import Dict, Any
class NodeClient:
    async def send_to_node(self, node_id: str, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if not node:  	
                return {"status": "error", "message": f"Node {node_id} not found"} 	
            return {"status": "success"}
    async def apply_tunnel(self, node_id, data):
        pass
PY
cat > "$tmp/overlay/panel/main.py" <<'PY'
async def _restore_rathole_servers():
    pass
async def _restore_backhaul_servers():
    for tunnel in tunnels:
                if tunnel.core != "backhaul":
                    continue
                try:
                    backhaul_manager.start_server(tunnel.id, tunnel.spec or {})
                except Exception:
                    pass
async def _restore_chisel_servers():
    pass
PY
cat > "$tmp/overlay/panel/tunnels.py" <<'PY'
async def update_tunnel():
    if tunnel_update.spec is not None:
        tunnel.spec = tunnel_update.spec
    if spec_changed:
        try:
            if needs_gost_forwarding:
                pass
            elif needs_backhaul_server:
                manager = getattr(request.app.state, "backhaul_manager", None)
                if manager:
                    manager.start_server(tunnel.id, tunnel.spec or {})
        except Exception:
            pass

@router.post("/{tunnel_id}/apply")
async def apply_tunnel():
    pass

@router.delete("/{tunnel_id}")
async def delete_tunnel():
    if needs_gost_forwarding:
        pass
    elif needs_backhaul_server:
        if hasattr(request.app.state, "backhaul_manager"):
            request.app.state.backhaul_manager.stop_server(tunnel.id)
PY
cp "$tmp/overlay/node/core_adapters.py" "$tmp/node-before"
cp "$tmp/overlay/panel/tunnels.py" "$tmp/panel-before"
source modules/smite-backhaul-management.sh
id() { if [ "$1" = -u ]; then echo 0; else command id "$@"; fi; }
docker() {
    if [ "$1" = inspect ]; then
        case "$4" in
            *Config.Image*) echo "$SMITE_BH_IMAGE" ;;
            *State.Running*) echo true ;;
            *Mounts*) echo "$SMITE_BH_OVERLAY_ROOT/node/core_adapters.py" ;;
            *) return 1 ;;
        esac
    elif [ "$1" = exec ] && [ "$2" = smite-node ] && [ "$3" = backhaul ]; then
        echo v0.7.2
    elif [ "$1" = exec ] && [ "$2" = smite-node ] && [ "$3" = sh ]; then
        if [ "$(smite_bh_role)" = kh ]; then echo 4; else echo 0; fi
    else
        echo "Unexpected Docker call: $*" >&2; return 1
    fi
}
nginx() { [ "$1" = -t ]; }
pgrep() {
    if [ "$(smite_bh_role)" = kh ]; then echo 4; return 0; fi
    return 1
}
ss() {
    case "$1" in
        -lntH) if [ "$(smite_bh_role)" = ir ]; then
                    echo 'LISTEN 0 4096 127.0.0.1:7000 0.0.0.0:*'
                else
                    echo 'LISTEN 0 4096 127.0.0.1:56053 0.0.0.0:*'
                fi ;;
    esac
}
smite_bh_preflight ir >/dev/null
smite_bh_prepare ir >/dev/null
ir="$(find "$SMITE_BH_STAGE_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | head -n1)"
smite_bh_verify_stage "$ir" >/dev/null
grep -Fq 'normalize_node_spec(spec)' "$SMITE_BH_STAGE_ROOT/$ir/candidate/node/core_adapters.py"
grep -Fq 'compile_standard_specs(' "$SMITE_BH_STAGE_ROOT/$ir/candidate/panel/node_client.py"
cmp -s "$SMITE_BH_STAGE_ROOT/$ir/candidate/panel/uopti_backhaul_standard.py" \
    modules/smite-backhaul-spec.py
grep -Fq 'location ^~ /56053/www/' "$SMITE_BH_STAGE_ROOT/$ir/candidate/nginx/ir-xhttp.conf"
cmp -s "$tmp/node-before" "$SMITE_BH_OVERLAY_ROOT/node/core_adapters.py"
cmp -s "$tmp/panel-before" "$SMITE_BH_OVERLAY_ROOT/panel/tunnels.py"
printf 'SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n' > "$SMITE_BH_STATE_FILE"
# Four live KH Backhaul clients and TOMLs must NOT block offline staging.
# They must still be reported explicitly, never treated as activation-ready.
kh_precheck="$(smite_bh_preflight kh)"
grep -Fq 'WARNING: Existing Backhaul processes=4, configs=4.' <<< "$kh_precheck"
grep -Fq 'Prepare-only preflight PASS (kh)' <<< "$kh_precheck"
smite_bh_prepare kh >/dev/null
kh="$(find "$SMITE_BH_STAGE_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | grep -v "^$ir$" | head -n1)"
smite_bh_verify_stage "$kh" >/dev/null
grep -Fq 'proxy_ssl_verify on;' "$SMITE_BH_STAGE_ROOT/$kh/candidate/nginx/kh-bridge.conf"
echo '# tamper' >> "$SMITE_BH_STAGE_ROOT/$kh/candidate/nginx/kh-bridge.conf"
if smite_bh_verify_stage "$kh" >/dev/null 2>&1; then
    echo "ERROR: Corrupted stage verified" >&2; exit 1
fi
if smite_bh_discard_unused '../../etc' >/dev/null 2>&1; then
    echo "ERROR: Unsafe ID accepted" >&2; exit 1
fi
smite_bh_discard_unused "$kh" >/dev/null
test ! -e "$SMITE_BH_STAGE_ROOT/$kh"
smite_bh_verify_stage "$ir" >/dev/null
cmp -s "$tmp/node-before" "$SMITE_BH_OVERLAY_ROOT/node/core_adapters.py"
# The four simulated KH Backhaul processes/configs remain untouched.
test "$(pgrep -xc backhaul)" = 4
clear() { :; }
docker_smite_open_setup_wizard() { echo PRIVATE_OK; }
docker_smite_frp_standard_guide() { echo FRP_GUIDE_OK; }
smite_frp_wizard_menu() { echo FRP_WIZARD_OK; }
smite_bh_management_menu() { echo BACKHAUL_OK; }
menu="$(printf '1\n2\n3\n4\n0\n' | docker_smite_management_menu)"
for value in PRIVATE_OK FRP_GUIDE_OK FRP_WIZARD_OK BACKHAUL_OK; do
    grep -Fq "$value" <<< "$menu"
done
echo 'Backhaul offline staging, integrity, discard, unchanged FRP/Private menu: PASS'
