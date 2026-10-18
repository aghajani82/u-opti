#!/usr/bin/env python3
"""Stage 11: produce OFFLINE, never-mounted Smite security overlay candidates.

Inputs: locally extracted /app trees from REVIEWED unpublished Panel/Node
images and current host U-OPTI source overlays. Outputs: a root-private,
immutable-on-rerun review bundle containing candidates copied from the new
security image, plus a secret-free discrepancy manifest.

This is NOT an automatic merge. Custom FRP/Backhaul/gateway changes absent
from the new image always HOLD. No Docker/Compose/API/restart commands.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

SHADOWS = (
    ("panel", "main.py", "panel/main.py"),
    ("panel", "app/node_client.py", "panel/node_client.py"),
    ("panel", "app/routers/tunnels.py", "panel/tunnels.py"),
    ("panel", "app/routers/nodes.py", "panel/nodes.py"),
    ("panel", "app/tunnel_reapply_manager.py", "panel/tunnel_reapply_manager.py"),
    ("panel", "app/routers/core_health.py", "panel/core_health.py"),
    ("node", "app/panel_client.py", "node/panel_client.py"),
    ("node", "app/core_adapters.py", "node/core_adapters.py"),
)

# Required hooks survive when security-aware images incorporate the former
# U-OPTI host-only FRP/Backhaul logic. Missing markers produce explicit HOLD.
CONTRACTS = {
    ("panel", "main.py"): (
        "signed_nodes.router", "node_pairing.router",
        "uopti_standard_backhaul",
    ),
    ("panel", "app/node_client.py"): (
        "prepare_node_command(", 'smite_panel_agent_auth_mode == "signed"',
    ),
    ("node", "app/panel_client.py"): (
        "signed_register()", 'smite_node_panel_auth_mode == "signed"',
    ),
    ("node", "app/core_adapters.py"): (
        "normalize_node_spec(spec)", "frp_client_server_port(",
    ),
}
# These U-OPTI host modifications still need human migration unless present
# in the image's corresponding source. Do not blindly copy them across.
HOST_MARKERS = {
    ("panel", "app/node_client.py"): ('get("control_address")',),
    ("node", "app/panel_client.py"): (
        "SMITE_CONTROL_ADDRESS", "SMITE_BACKHAUL_ADDRESS",
    ),
    ("node", "app/core_adapters.py"): ("frp_client_server_port(",),
    ("panel", "main.py"): ('existing_ports = server_spec.get("ports", [])',),
}


class Hold(Exception):
    pass


def _read(path: Path) -> bytes:
    try:
        if path.is_symlink():
            raise Hold("Unsafe symlink")
        entry = path.lstat()
        if not stat.S_ISREG(entry.st_mode) or entry.st_size > 2_000_000:
            raise Hold("Invalid input file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            return stream.read(2_000_001)
    except OSError as exc:
        raise Hold("Missing input file") from exc


def _review(base: Path, overlay: Path, service: str, name: str) -> dict:
    try:
        image_bytes = _read(base)
        compile(image_bytes, service + "/" + name, "exec")
    except (Hold, SyntaxError, ValueError):
        raise Hold("Image Python source missing/invalid")
    base_text = image_bytes.decode("utf-8")
    try:
        installed = _read(overlay)
    except Hold:
        installed = None
    overlay_text = installed.decode("utf-8") if installed is not None else ""
    requirements = CONTRACTS.get((service, name), ())
    missing_guards = [x for x in requirements if x not in base_text]
    old_extras = [
        x for x in HOST_MARKERS.get((service, name), ())
        if x in overlay_text and x not in base_text
    ]
    return {
        "role": service,
        "module": name,
        "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "mounted_overlay_known": installed is not None,
        "byte_identical": installed == image_bytes if installed is not None else False,
        "missing_image_guards": len(missing_guards),
        "host_feature_conflicts": len(old_extras),
        "status": "HOLD_REVIEW_REQUIRED" if (
            missing_guards or old_extras or installed != image_bytes
        ) else "SOURCE_PARITY_ONLY",
    }


def prepare(
    *, panel_root: Path, node_root: Path,
    host_overlays: Path, destination: Path,
) -> list[dict]:
    if destination.exists() or destination.is_symlink():
        raise Hold("Existing review bundle: never overwrite")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise Hold("Review bundle parent missing/unsafe")
    # Only use user-supplied extracted image trees. Never touch live mount.
    for p in (panel_root, node_root, host_overlays):
        if not p.is_dir() or p.is_symlink():
            raise Hold("Invalid source directory")
    # Validate all sources and contract requirements BEFORE writing bundle.
    manifest, sources = [], []
    for role, filename, host_name in SHADOWS:
        source = (panel_root if role == "panel" else node_root) / filename
        data = _read(source)
        review = _review(source, host_overlays / host_name, role, filename)
        manifest.append(review)
        sources.append((host_name, data))
    destination.mkdir(mode=0o700)
    try:
        for name, data in sources:
            path = destination / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        payload = {
            "schema": 1,
            "activation_allowed": False,
            "source_images_provenance_verified": False,
            "old_host_mounts_modified": False,
            "files": manifest,
        }
        # Manifest contains ONLY source hashes and booleans/counts,
        # never plaintext FRP/Backhaul/pairing secrets or diff lines.
        fd = os.open(destination / "REVIEW.json", os.O_WRONLY | os.O_CREAT |
                     os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        # Keep partially staged review bundle for diagnosis: never risk
        # deleting a directory when an unexpected mutation/race occurred.
        raise Hold("Bundle staging failed; inspect private output manually")
    return manifest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel-image-app", type=Path, required=True)
    p.add_argument("--node-image-app", type=Path, required=True)
    p.add_argument("--existing-overlays", type=Path,
                   default=Path("/opt/u-opti-smite"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        rows = prepare(
            panel_root=args.panel_image_app,
            node_root=args.node_image_app,
            host_overlays=args.existing_overlays,
            destination=args.output,
        )
    except (Hold, OSError, ValueError, UnicodeError) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 2
    for row in rows:
        print(
            f"{row['role']}/{row['module']}: {row['status']} "
            f"old_features={row['host_feature_conflicts']} "
            f"missing_guards={row['missing_image_guards']}"
        )
    print("STAGE11=REVIEW_BUNDLE_ONLY")
    print("STAGE11_LIVE_DEPLOYMENT=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
