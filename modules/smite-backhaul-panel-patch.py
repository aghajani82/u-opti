#!/usr/bin/env python3
"""Generate a candidate, NOT ACTIVE Standard Backhaul panel overlay.

Only the three pinned Smite v0.1.7 modules required for centralized
node payload validation and preventing a second panel Backhaul listener are
touched. The original and running containers are never modified here.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile


SEND_ANCHOR = (
    '            if not node:\n'
    '                return {"status": "error", "message": f"Node {node_id} not found"}\n'
)
SEND_GUARD = '''            # U-OPTI Standard Backhaul (opt-in): normalize all create/reapply
            # and startup node sends from the canonical persisted tunnel spec.
            if endpoint == "/api/agent/tunnels/apply" and data.get("core") == "backhaul":
                from app.models import Tunnel
                tunnel_result = await session.execute(
                    select(Tunnel).where(Tunnel.id == data.get("tunnel_id"))
                )
                stored_tunnel = tunnel_result.scalar_one_or_none()
                standard = bool(
                    stored_tunnel
                    and isinstance(stored_tunnel.spec, dict)
                    and stored_tunnel.spec.get("uopti_standard_backhaul") is True
                )
                if standard:
                    from app.uopti_backhaul_standard import (
                        StandardBackhaulSpecError, compile_standard_specs
                    )
                    try:
                        canonical = stored_tunnel.spec
                        role = (node.node_metadata or {}).get("role")
                        if role not in ("iran", "foreign"):
                            raise StandardBackhaulSpecError("Unknown node role")
                        ir_spec, kh_spec = compile_standard_specs(
                            canonical,
                            data_port=canonical.get("data_port", 56053),
                            control_port=canonical.get("control_port", 3080),
                            bridge_port=canonical.get("bridge_port", 13080),
                        )
                        data = dict(data)
                        data["spec"] = ir_spec if role == "iran" else kh_spec
                    except (StandardBackhaulSpecError, TypeError, ValueError) as exc:
                        return {
                            "status": "error",
                            "message": f"Standard Backhaul rejected: {exc}",
                        }
                elif isinstance(data.get("spec"), dict) and data["spec"].get(
                    "uopti_standard_backhaul"
                ) is True:
                    return {
                        "status": "error",
                        "message": "Standard Backhaul requires a persisted opt-in tunnel",
                    }
'''
STARTUP_ANCHOR = (
    '                if tunnel.core != "backhaul":\n'
    '                    continue\n'
)
STARTUP_GUARD = (
    '                # Standard Backhaul server belongs exclusively to IR Smite Node.\n'
    '                # Never start a duplicate wildcard listener on the Panel.\n'
    '                if (tunnel.spec or {}).get("uopti_standard_backhaul") is True:\n'
    '                    continue\n'
)
UPDATE_ANCHOR = '    if tunnel_update.spec is not None:\n'
UPDATE_GUARD = (
    '    # Never allow an edit to silently downgrade an active Standard tunnel.\n'
    '    if (tunnel.core == "backhaul"\n'
    '        and (tunnel.spec or {}).get("uopti_standard_backhaul") is True\n'
    '        and tunnel_update.spec is not None\n'
    '        and tunnel_update.spec.get("uopti_standard_backhaul") is not True):\n'
    '        raise HTTPException(status_code=400, detail="Standard Backhaul cannot be downgraded by editing its spec")\n'
)
MANAGER_ANCHOR = '            elif needs_backhaul_server:\n'
MANAGER_GUARD = (
    '            elif needs_backhaul_server and not (tunnel.spec or {}).get("uopti_standard_backhaul"):\n'
)


def one(source: str, anchor: str, addition: str, marker: str, label: str) -> str:
    if marker in source:
        if source.count(marker) != 1:
            raise ValueError(f"{label}: duplicate opt-in patch marker")
        return source
    if source.count(anchor) != 1:
        raise ValueError(f"{label}: upstream anchor must appear exactly once")
    return source.replace(anchor, anchor + addition, 1)


def patch_panel_source(filename: str, source: str) -> str:
    if filename == "node_client.py":
        output = one(
            source, SEND_ANCHOR, "\n" + SEND_GUARD,
            "            # U-OPTI Standard Backhaul (opt-in):", "NodeClient",
        )
    elif filename == "main.py":
        # Anchor constrained to the Backhaul restore method.
        head, begin, rest = source.partition("async def _restore_backhaul_servers():")
        body, end, tail = rest.partition("async def _restore_chisel_servers():")
        if not begin or not end:
            raise ValueError("Panel startup Backhaul restore boundaries missing")
        patched = one(
            body, STARTUP_ANCHOR, STARTUP_GUARD,
            "                # Standard Backhaul server belongs exclusively", "Startup",
        )
        output = head + begin + patched + end + tail
    elif filename == "tunnels.py":
        output = one(
            source, UPDATE_ANCHOR, UPDATE_GUARD,
            "    # Never allow an edit to silently downgrade", "Tunnel update",
        )
        if MANAGER_GUARD in output:
            if output.count(MANAGER_GUARD) != 1:
                raise ValueError("Ambiguous Backhaul panel manager guard")
        elif output.count(MANAGER_ANCHOR) == 1:
            output = output.replace(MANAGER_ANCHOR, MANAGER_GUARD, 1)
        else:
            raise ValueError("Backhaul panel manager update anchor missing")
    else:
        raise ValueError(f"Unexpected panel file {filename!r}")
    compile(output, filename, "exec")
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream_dir", type=Path)
    parser.add_argument("candidate_dir", type=Path)
    args = parser.parse_args()
    if args.upstream_dir.resolve() == args.candidate_dir.resolve():
        parser.error("Input and candidate output directories must differ")
    for filename in ("node_client.py", "main.py", "tunnels.py"):
        source = args.upstream_dir / filename
        destination = args.candidate_dir / filename
        candidate = patch_panel_source(filename, source.read_text(encoding="utf-8"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=destination.parent,
            prefix=".bh-panel-", delete=False,
        ) as file:
            file.write(candidate)
            stage = Path(file.name)
        os.chmod(stage, 0o644)
        os.replace(stage, destination)
    print("Standard Backhaul Panel candidate overlays prepared; NOT installed")


if __name__ == "__main__":
    main()
