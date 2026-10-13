#!/usr/bin/env python3
"""Generate a candidate, NOT ACTIVE Standard Backhaul panel overlay.

Only the three pinned Smite v0.1.7 modules required for centralized
node payload validation and preventing a second panel Backhaul listener are
touched. The original and running containers are never modified here.
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import tempfile


# Parse the actual Python AST rather than line-matching a fragile regex.
# Only insert the opt-in guard after the single canonical missing-node return
# in NodeClient.send_to_node; leave get_tunnel_status and all other code alone.
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
        # Do not use a textual pattern: IR's source formatting is not identical
        # to the upstream fixture. AST ensures we match statements, not spaces.
        tree = ast.parse(source, filename=filename)
        candidates = [
            node
            for cls in tree.body
            if isinstance(cls, ast.ClassDef) and cls.name == "NodeClient"
            for node in cls.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "send_to_node"
        ]
        if len(candidates) != 1:
            raise ValueError("NodeClient.send_to_node must occur exactly once")
        method = candidates[0]
        guard_marker = "            # U-OPTI Standard Backhaul (opt-in):"
        method_source = ast.get_source_segment(source, method) or ""
        expected_return = ast.parse(
            'return {"status": "error", "message": f"Node {node_id} not found"}'
        ).body[0]
        lookup_blocks = []
        for section in ast.walk(method):
            if not isinstance(section, ast.AsyncWith):
                continue
            # The missing-node guard must be in the body of the session block
            # and immediately follow a lookup of 'node' from the DB result.
            for i, statement in enumerate(section.body):
                if not (
                    isinstance(statement, ast.If)
                    and isinstance(statement.test, ast.UnaryOp)
                    and isinstance(statement.test.op, ast.Not)
                    and isinstance(statement.test.operand, ast.Name)
                    and statement.test.operand.id == "node"
                    and not statement.orelse
                    and len(statement.body) == 1
                    and ast.dump(statement.body[0], include_attributes=False)
                    == ast.dump(expected_return, include_attributes=False)
                    and statement.col_offset == 12
                    and i > 0
                ):
                    continue
                previous = section.body[i - 1]
                if not (
                    isinstance(previous, ast.Assign)
                    and len(previous.targets) == 1
                    and isinstance(previous.targets[0], ast.Name)
                    and previous.targets[0].id == "node"
                    and isinstance(previous.value, ast.Call)
                    and isinstance(previous.value.func, ast.Attribute)
                    and previous.value.func.attr == "scalar_one_or_none"
                ):
                    continue
                lookup_blocks.append(statement)
        if len(lookup_blocks) != 1:
            raise ValueError(
                "NodeClient: expected one canonical missing-node return after "
                "the database lookup inside send_to_node"
            )
        marker_count = method_source.count(guard_marker)
        if marker_count:
            if marker_count != 1:
                raise ValueError("NodeClient: duplicate Standard guard markers")
            output = source
        else:
            insertion_line = lookup_blocks[0].end_lineno
            lines = source.splitlines(keepends=True)
            if not lines[insertion_line - 1].endswith(("\n", "\r")):
                raise ValueError("NodeClient: cannot safely insert after unterminated line")
            lines.insert(insertion_line, SEND_GUARD)
            output = "".join(lines)
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
        # A real Smite v0.1.7 Panel has TWO 'elif needs_backhaul_server:'
        # blocks: one in update_tunnel (may START a second Backhaul server)
        # and one in delete_tunnel (correctly STOPS it). Only patch the
        # update_tunnel method and preserve the delete handler verbatim.
        head, begin, rest = source.partition("async def update_tunnel(")
        body, end, tail = rest.partition('@router.post("/{tunnel_id}/apply")')
        if not begin or not end or "async def apply_tunnel(" not in tail:
            raise ValueError("Pinned Smite update/apply handler boundaries missing")
        if "    # Never allow an edit to silently downgrade" in body:
            if body.count("    # Never allow an edit to silently downgrade") != 1:
                raise ValueError("Ambiguous existing tunnel downgrade guard")
        elif body.count(UPDATE_ANCHOR) == 1:
            # Insert BEFORE the existing if-body; do not shadow update logic.
            body = body.replace(UPDATE_ANCHOR, UPDATE_GUARD + UPDATE_ANCHOR, 1)
        else:
            raise ValueError("Tunnel update upstream anchor missing")
        if MANAGER_GUARD in body:
            if body.count(MANAGER_GUARD) != 1:
                raise ValueError("Ambiguous existing Backhaul update guard")
        elif body.count(MANAGER_ANCHOR) == 1:
            body = body.replace(MANAGER_ANCHOR, MANAGER_GUARD, 1)
        else:
            raise ValueError("Backhaul update manager anchor missing")
        output = head + begin + body + end + tail
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
