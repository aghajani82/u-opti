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
routes = '''async def update_tunnel():
    if tunnel_update.spec is not None:
        tunnel.spec = tunnel_update.spec
    try:
        if needs_gost_forwarding:
            pass
            elif needs_backhaul_server:
                manager = getattr(request.app.state, "backhaul_manager", None)
    except Exception:
        pass
'''
# A real branch uses valid Python indentation; test a faithful method fragment
# with a valid surrounding conditional instead of the invalid dummy above.
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
'''

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
    compile(output, name, "exec")

for name, content in (("node_client.py", client.replace(
    'return {"status": "error", "message": f"Node {node_id} not found"}',
    'return {"status": "error"}')),
    ("main.py", main.replace('async def _restore_chisel_servers():', "async def _restore_non_backhaul():")),
    ("tunnels.py", routes.replace('elif needs_backhaul_server:', 'elif needs_other_server:'))):
    try:
        patcher.patch_panel_source(name, content)
    except ValueError:
        continue
    raise AssertionError("Unexpected Panel upstream layout was accepted")

print("Standard Backhaul Panel candidate patch: PASS")
