#!/usr/bin/env python3
"""Fail-closed, idempotent admin JWT guard for U-OPTI's mounted Smite main.py.

Protects management APIs without touching node bootstrap, healthchecks,
FRP/Backhaul runtime config, Docker, Nginx or upstream Docker images.
The panel overlay is bind-mounted over /app/main.py; patch *after* docker cp.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import stat
import sys
import tempfile


ROUTES = (
    ('app.include_router(tunnels.router, prefix="/api/tunnels", tags=["tunnels"])',
     'app.include_router(tunnels.router, prefix="/api/tunnels", tags=["tunnels"], dependencies=admin_only)'),
    ('app.include_router(logs.router, prefix="/api/logs", tags=["logs"])',
     'app.include_router(logs.router, prefix="/api/logs", tags=["logs"], dependencies=admin_only)'),
    ('app.include_router(core_health.router, prefix="/api/core-health", tags=["core-health"])',
     'app.include_router(core_health.router, prefix="/api/core-health", tags=["core-health"], dependencies=admin_only)'),
    ('app.include_router(settings_router.router)',
     'app.include_router(settings_router.router, dependencies=admin_only)'),
)
IMPORT_BEFORE = "from fastapi import FastAPI, HTTPException\n"
IMPORT_AFTER = "from fastapi import FastAPI, HTTPException, Depends\n"
AUTH_ANCHOR = 'app.include_router(auth.router, prefix="/api/auth", tags=["auth"])'
ADMIN_MARKER = "admin_only = [Depends(auth.get_current_user)]"


def patch(text: str) -> tuple[str, bool]:
    ast.parse(text)
    new_count = [text.count(new) for _, new in ROUTES]
    old_count = [text.count(old) for old, _ in ROUTES]

    # Do not silently accept partial patches or unknown upstream layouts.
    if new_count == [1] * len(ROUTES) and old_count == [0] * len(ROUTES):
        if text.count(IMPORT_AFTER) != 1 or text.count(ADMIN_MARKER) != 1:
            raise ValueError("Partial or unknown Smite admin guard; refusing to proceed")
        if text.count(AUTH_ANCHOR) != 1:
            raise ValueError("Ambiguous authentication router")
        return text, False

    if new_count != [0] * len(ROUTES) or old_count != [1] * len(ROUTES):
        raise ValueError("Unexpected Smite admin router layout; refusing to proceed")
    if text.count(IMPORT_BEFORE) != 1 or text.count(IMPORT_AFTER) != 0:
        raise ValueError("Unexpected FastAPI import layout")
    if text.count(AUTH_ANCHOR) != 1 or "admin_only" in text:
        raise ValueError("Unexpected authentication anchor or existing guard")

    updated = text.replace(IMPORT_BEFORE, IMPORT_AFTER, 1)
    updated = updated.replace(AUTH_ANCHOR, ADMIN_MARKER + "\n" + AUTH_ANCHOR, 1)
    for old, new in ROUTES:
        updated = updated.replace(old, new, 1)
    ast.parse(updated)
    return updated, True


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: smite-panel-auth-overlay.py /path/to/panel/main.py", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    if path.is_symlink() or not path.is_file():
        print("HOLD: Smite overlay must be an existing regular file, not a symlink", file=sys.stderr)
        return 2

    original = path.read_text(encoding="utf-8")
    try:
        updated, changed = patch(original)
    except (ValueError, SyntaxError) as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2

    if not changed:
        print("SMITE_ADMIN_API_AUTH: already prepared")
        return 0

    mode = stat.S_IMODE(path.stat().st_mode)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".smite-admin-auth-", delete=False
        ) as stage:
            temporary = Path(stage.name)
            stage.write(updated)
            stage.flush()
            os.fsync(stage.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    print("SMITE_ADMIN_API_AUTH: guarded overlay prepared (restart required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
