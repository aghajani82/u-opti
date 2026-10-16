#!/usr/bin/env python3
"""Offline review of isolated Smite v0.1.7 Standard Backhaul panel patch."""
import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1]
module = importlib.util.spec_from_file_location(
    "smite_bh_panel", root / "modules/smite-backhaul-panel-patch.py"
)
patcher = importlib.util.module_from_spec(module)
module.loader.exec_module(patcher)

client = '''from typing import Dict, Any
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
'''
main = '''async def _restore_rathole_servers():
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
'''
# Match the current IR observation: two Backhaul manager branches in
# separate update_tunnel and delete_tunnel handlers.
routes = '''async def update_tunnel():
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
    if needs_node_apply:
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
'''

# Reproduce the actual IR situation: equivalent Python lookup statements
# but one or both lines contain invisible trailing spaces/tabs. The patch
# must remain confined to send_to_node, never touching get_tunnel_status.
node_anchor = '            if not node:\n                return {"status": "error", "message": f"Node {node_id} not found"}\n'
assert client.count(node_anchor) == 1
variant = client.replace(
    node_anchor,
    '            if not node:  \t\n                return {"status": "error", "message": f"Node {node_id} not found"}  \t\n',
)
variant += '''
    async def get_tunnel_status(self, node_id):
        if not node:
            return {"status": "error", "message": f"Node {node_id} not found"}
'''
patched_variant = patcher.patch_panel_source("node_client.py", variant)
assert patched_variant.count("# U-OPTI Standard Backhaul (opt-in):") == 1
assert patcher.patch_panel_source("node_client.py", patched_variant) == patched_variant
assert patched_variant.split("    async def get_tunnel_status(", 1)[1] == variant.split("    async def get_tunnel_status(", 1)[1]
assert 'if not node:  \t\n' in patched_variant

assert routes.count("elif needs_backhaul_server:") == 2
original_delete_handler = routes.split('@router.delete("/{tunnel_id}")', 1)[1]

for name, content in (("node_client.py", client), ("main.py", main), ("tunnels.py", routes)):
    output = patcher.patch_panel_source(name, content)
    assert output == patcher.patch_panel_source(name, output)
    assert output != content
    assert output.count("uopti_standard_backhaul") >= 1
    if name == "node_client.py":
        assert "compile_standard_specs(" in output
        assert 'role == "iran"' in output
        assert 'role not in ("iran", "foreign")' in output
        assert "persisted opt-in tunnel" in output
        assert "select(Tunnel)" in output
    elif name == "main.py":
        assert output.index("uopti_standard_backhaul") < output.index("backhaul_manager.start_server")
    else:
        assert 'elif needs_backhaul_server and not (tunnel.spec or {}).get("uopti_standard_backhaul")' in output
        assert "cannot be downgraded" in output
        # A non-standard tunnel delete must still stop its own server.
        assert output.split('@router.delete("/{tunnel_id}")', 1)[1] == original_delete_handler
        assert output.count("elif needs_backhaul_server:") == 1
        assert output.count("elif needs_backhaul_server and not ") == 1
    compile(output, name, "exec")

for name, content in (("node_client.py", client.replace(
    'return {"status": "error", "message": f"Node {node_id} not found"}',
    'return {"status": "error"}')),
    ("main.py", main.replace('async def _restore_chisel_servers():', "async def _restore_non_backhaul():")),
    ("tunnels.py", routes.replace('            elif needs_backhaul_server:', '            elif needs_other_server:')),
    ("tunnels.py", routes.replace('@router.post("/{tunnel_id}/apply")', '@router.post("/other/apply")'))):
    try:
        patcher.patch_panel_source(name, content)
    except ValueError:
        continue
    raise AssertionError("Unexpected Panel upstream layout was accepted")

print("Standard Backhaul Panel candidate patch: PASS")
