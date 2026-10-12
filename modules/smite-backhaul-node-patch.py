#!/usr/bin/env python3
"""Offline, idempotent Smite v0.1.7 BackhaulAdapter overlay transform.

Refuses unknown layouts. Does not change live Smite code. The transformed
overlay must be staged, tested and mounted separately with explicit approval.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile

OPTIN = 'uopti_standard_backhaul'
ANCHOR = '    def apply(self, tunnel_id: str, spec: Dict[str, Any]):\n        """Apply Backhaul tunnel - supports both server and client modes"""\n'
GUARD = (
    '        if spec.get("uopti_standard_backhaul") is True:\n'
    '            from app.uopti_backhaul_standard import normalize_node_spec\n'
    '            spec = normalize_node_spec(spec)\n'
)
SECURE = (
    '            if spec.get("uopti_standard_backhaul") is True:\n'
    '                with os.fdopen(os.open(str(config_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600), "w", encoding="utf-8") as config_file:\n'
    '                    os.fchmod(config_file.fileno(), 0o600)\n'
    '                    config_file.write(self._render_toml({"@role": @var}))\n'
    '            else:\n'
    '                config_path.write_text(self._render_toml({"@role": @var}), encoding="utf-8")'
)


def patch_source(source: str) -> str:
    head, sep, rest = source.partition("class BackhaulAdapter:")
    body, next_class, tail = rest.partition("class ChiselAdapter:")
    if not sep or not next_class:
        raise ValueError("Pinned Smite v0.1.7 BackhaulAdapter class boundaries missing")
    if GUARD in body:
        if body.count(GUARD) != 1 or body.count("os.O_NOFOLLOW") != 2 or body.count(
            'if not spec.get("uopti_standard_backhaul"):'
        ) != 2:
            raise ValueError("Partial or ambiguous existing Backhaul Standard patch")
        return source
    if body.count(ANCHOR) != 1:
        raise ValueError("Unexpected Backhaul apply method")
    body = body.replace(ANCHOR, ANCHOR + GUARD, 1)
    for role, var in (("server", "server_config"), ("client", "config_dict")):
        original_write = (
            f'            config_path.write_text(self._render_toml({{"{role}": {var}}}), encoding="utf-8")'
        )
        if body.count(original_write) != 1:
            raise ValueError(f"Unexpected Backhaul {role} config write")
        replacement = SECURE.replace("@role", role).replace("@var", var)
        body = body.replace(original_write, replacement, 1)
        original_log = f'            log_fh.write(self._render_toml({{"{role}": {var}}}))'
        if body.count(original_log) != 1:
            raise ValueError(f"Unexpected Backhaul {role} secret-bearing log")
        body = body.replace(
            original_log,
            '            if not spec.get("uopti_standard_backhaul"):\n'
            + "    " + original_log,
            1,
        )

    modified = head + sep + body + next_class + tail
    compile(modified, "<smite-standard-backhaul-overlay>", "exec")
    return modified


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a candidate BackhaulAdapter overlay")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        parser.error("Source and destination must differ: never patch a live mount in place")
    original = args.source.read_text(encoding="utf-8")
    patched = patch_source(original)
    # Atomic candidate output only; never edit the input/source.
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=args.destination.parent,
        prefix=".backhaul-overlay-", delete=False,
    ) as handle:
        handle.write(patched)
        stage = Path(handle.name)
    os.chmod(stage, 0o644)
    os.replace(stage, args.destination)
    print("Candidate Backhaul Standard node overlay prepared (NOT activated)")


if __name__ == "__main__":
    main()
