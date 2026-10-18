#!/usr/bin/env python3
"""Stage 10 READ-ONLY Smite image/host-overlay compatibility admission.

Reads extracted candidate-image source directories, NOT running Docker.
This checks source/module parity ONLY; it DOES NOT prove image provenance,
registry digests, active mount layout, or end-to-end 443/FRP/Backhaul traffic.
Always HOLD activation until separate image and live admission is completed.

Never prints tokens, file contents, or any secret; it reports only short
per-module statuses. Deliberately rejects overlays that shadow new code.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys

SHADOWS = (
    ("panel", "main.py"),
    ("panel", "app/node_client.py"),
    ("panel", "app/routers/tunnels.py"),
    ("panel", "app/routers/nodes.py"),
    ("panel", "app/tunnel_reapply_manager.py"),
    ("panel", "app/routers/core_health.py"),
    ("node", "app/panel_client.py"),
    ("node", "app/core_adapters.py"),
)
# The U-OPTI host filenames are not identical to the in-image paths.
OVERLAY_NAMES = {
    ("panel", "main.py"): "panel/main.py",
    ("panel", "app/node_client.py"): "panel/node_client.py",
    ("panel", "app/routers/tunnels.py"): "panel/tunnels.py",
    ("panel", "app/routers/nodes.py"): "panel/nodes.py",
    ("panel", "app/tunnel_reapply_manager.py"): "panel/tunnel_reapply_manager.py",
    ("panel", "app/routers/core_health.py"): "panel/core_health.py",
    ("node", "app/panel_client.py"): "node/panel_client.py",
    ("node", "app/core_adapters.py"): "node/core_adapters.py",
}

REQUIRED_MODULES = {
    "panel": (
        "main.py",
        "app/node_auth.py",
        "app/node_pairing_store.py",
        "app/signed_node_registration.py",
        "app/signed_agent_transport.py",
        "app/agent_request_signer.py",
        "app/routers/node_pairing.py",
        "app/routers/signed_nodes.py",
        "app/routers/nodes.py",
        "app/node_client.py",
    ),
    "node": (
        "main.py",
        "app/node_auth.py",
        "app/agent_auth.py",
        "app/signed_panel_client.py",
        "app/panel_client.py",
        "app/routers/agent.py",
    ),
}


class AuditHold(RuntimeError):
    pass


def _read_regular(path: Path, *, max_size: int = 2_000_000) -> bytes:
    """Read a regular non-symlink source with no-follow and bounded content."""
    try:
        if path.is_symlink():
            raise AuditHold("Symlinked source is untrusted")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_size:
            raise AuditHold("Source is absent, too large or not a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            after = os.fstat(stream.fileno())
            if not stat.S_ISREG(after.st_mode) or after.st_size > max_size:
                raise AuditHold("Source changed or is unsafe")
            body = stream.read(max_size + 1)
            if len(body) > max_size:
                raise AuditHold("Source exceeds maximum size")
            return body
    except OSError as exc:
        raise AuditHold("Source unavailable") from exc


def assess(
    *, panel_root: Path, node_root: Path, overlay_root: Path,
    panel_compose: Path, node_compose: Path,
) -> list[tuple[str, str]]:
    """Return ordered machine-safe results, never sensitive contents."""
    outputs: list[tuple[str, str]] = []
    image_dirs = {"panel": panel_root, "node": node_root}
    for service, required in REQUIRED_MODULES.items():
        for filename in required:
            try:
                source = _read_regular(image_dirs[service] / filename)
                compile(source, f"{service}/{filename}", "exec")
                outputs.append((f"IMAGE/{service}/{filename}", "SOURCE_PRESENT"))
            except (AuditHold, SyntaxError, UnicodeError, ValueError):
                outputs.append((f"IMAGE/{service}/{filename}", "HOLD_MISSING_OR_INVALID"))

    composes: dict[str, str] = {}
    for role, filename in (("panel", panel_compose), ("node", node_compose)):
        try:
            text = _read_regular(filename, max_size=250_000).decode("utf-8")
            if f"  smite-{role}:\n" not in text:
                raise AuditHold("Compose missing expected service")
            composes[role] = text
            outputs.append((f"COMPOSE/{role}", "SOURCE_PRESENT"))
        except (AuditHold, UnicodeError):
            outputs.append((f"COMPOSE/{role}", "HOLD_MISSING_OR_INVALID"))
            composes[role] = ""

    for role, img_rel in SHADOWS:
        host_path = overlay_root / OVERLAY_NAMES[(role, img_rel)]
        dest = "/app/" + img_rel
        # Parse on known destination rather than an unreliable global grep.
        lines = composes[role].splitlines()
        matches = [
            line.strip().removeprefix("- ").strip()
            for line in lines
            if line.strip().startswith("- ") and ":" + dest + ":" in line
        ]
        if len(matches) > 1:
            status = "HOLD_DUPLICATE_SHADOWS"
        elif not matches:
            status = "NO_HOST_SHADOW"
        else:
            source_path = matches[0].split(":" + dest + ":", 1)[0]
            if not source_path.startswith("/") or not source_path.startswith(str(overlay_root) + "/"):
                status = "HOLD_UNTRUSTED_SHADOW_SOURCE"
            elif Path(source_path) != host_path:
                status = "HOLD_UNEXPECTED_SHADOW_SOURCE"
            else:
                try:
                    a = _read_regular(host_path)
                    b = _read_regular(image_dirs[role] / img_rel)
                    status = (
                        "BYTE_IDENTICAL_SHADOW" if hashlib.sha256(a).digest() == hashlib.sha256(b).digest()
                        else "HOLD_OBSOLETE_SHADOW"
                    )
                except AuditHold:
                    status = "HOLD_MISSING_SHADOW_SOURCE"
        outputs.append((f"OVERLAY/{role}/{img_rel}", status))

    # Important: independent of source parity, an offline comparison cannot
    # prove a running image digest, actual Docker mounts or network security.
    outputs.append(("DOCKER_IMAGE_PROVENANCE", "UNVERIFIED"))
    outputs.append(("RUNNING_DOCKER_MOUNTS", "UNVERIFIED"))
    outputs.append(("PANEL_HTTPS_443_AND_HMAC", "UNVERIFIED"))
    outputs.append(("FRP_BACKHAUL_REAL_TRAFFIC", "UNVERIFIED"))
    outputs.append(("AUTH_ACTIVATION", "BLOCKED"))
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-image-app", type=Path, required=True)
    parser.add_argument("--node-image-app", type=Path, required=True)
    parser.add_argument("--overlay-root", type=Path, default=Path("/opt/u-opti-smite"))
    parser.add_argument("--panel-compose", type=Path, default=Path("/opt/smite/docker-compose.yml"))
    parser.add_argument("--node-compose", type=Path, default=Path("/opt/smite-node/docker-compose.yml"))
    args = parser.parse_args()
    results = assess(
        panel_root=args.panel_image_app,
        node_root=args.node_image_app,
        overlay_root=args.overlay_root,
        panel_compose=args.panel_compose,
        node_compose=args.node_compose,
    )
    for key, value in results:
        print(f"{key}={value}")
    failures = [v for _, v in results if v.startswith("HOLD_")]
    print(f"STAGE10_SOURCE_AUDIT={'HOLD' if failures else 'PARITY_ONLY'}")
    print("STAGE10_READY_FOR_ACTIVATION=NO")
    # Never indicate success to a script consuming this as deploy admission.
    # A parity-only result is useful evidence, NOT deployment approval.
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
