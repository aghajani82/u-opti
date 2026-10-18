#!/usr/bin/env python3
"""Safe, offline regression tests for U-OPTI's Smite panel overlay auth guard."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "modules/smite-panel-auth-overlay.py"

SOURCE = """from fastapi import FastAPI, HTTPException
from app.routers import auth, panel, nodes, tunnels, status, logs, core_health
from app.routers import settings as settings_router

# Preserve critical U-OPTI host-side Smite compatibility code.
backhaul_address = "PRIVATE_BACKHAUL_ROUTE_KEEP"
app = FastAPI()
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(panel.router, prefix="/api/panel", tags=["panel"])
app.include_router(nodes.router, prefix="/api/nodes", tags=["nodes"])
app.include_router(tunnels.router, prefix="/api/tunnels", tags=["tunnels"])
app.include_router(status.router, prefix="/api/status", tags=["status"])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
app.include_router(core_health.router, prefix="/api/core-health", tags=["core-health"])
app.include_router(settings_router.router)
"""


def run(path):
    return subprocess.run(
        [sys.executable, "-B", str(HELPER), str(path)],
        capture_output=True, text=True, check=False,
    )


class OverlayAuthTests(unittest.TestCase):
    def test_fresh_patch_and_second_pass_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "main.py"
            path.write_text(SOURCE)
            path.chmod(0o644)
            first = run(path)
            self.assertEqual(first.returncode, 0, first.stderr)
            changed = path.read_text()
            self.assertIn("PRIVATE_BACKHAUL_ROUTE_KEEP", changed)
            self.assertEqual(changed.count("admin_only = [Depends(auth.get_current_user)]"), 1)
            for route in ("tunnels.router", "logs.router", "core_health.router", "settings_router.router"):
                route_line = next(x for x in changed.splitlines() if x.strip().startswith("app.include_router(" + route))
                self.assertIn("dependencies=admin_only", route_line)
            for route in ("nodes.router", "panel.router", "status.router"):
                route_line = next(x for x in changed.splitlines() if x.strip().startswith("app.include_router(" + route))
                self.assertNotIn("dependencies=admin_only", route_line)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            second = run(path)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(path.read_text(), changed)
            self.assertIn("already prepared", second.stdout)

    def test_partial_guard_fails_closed_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "main.py"
            partial = SOURCE.replace(
                'app.include_router(tunnels.router, prefix="/api/tunnels", tags=["tunnels"])',
                'app.include_router(tunnels.router, prefix="/api/tunnels", tags=["tunnels"], dependencies=admin_only)',
            )
            path.write_text(partial)
            result = run(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("HOLD", result.stderr)
            self.assertEqual(path.read_text(), partial)

    def test_unknown_router_layout_is_not_modified(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "main.py"
            unexpected = SOURCE.replace(
                'app.include_router(tunnels.router, prefix="/api/tunnels", tags=["tunnels"])',
                'app.include_router(tunnels.router, prefix="/api/tunnels")',
            )
            path.write_text(unexpected)
            result = run(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(), unexpected)

    def test_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "original.py"
            target.write_text(SOURCE)
            link = Path(folder) / "main.py"
            link.symlink_to(target)
            result = run(link)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_text(), SOURCE)

    def test_deployment_wiring_and_manifest(self):
        smite = (ROOT / "modules/smite.sh").read_text()
        copy = 'docker cp smite-panel:/app/main.py "$SMITE_OVERLAY_DIR/panel/main.py"'
        helper = '"$auth_helper_dir/smite-panel-auth-overlay.py"'
        self.assertEqual(smite.count(copy), 1)
        self.assertEqual(smite.count(helper), 1)
        self.assertLess(smite.index(copy), smite.index(helper))

        installer = (ROOT / "install.sh").read_text()
        updater = (ROOT / "u-opti").read_text()
        name = "smite-panel-auth-overlay.py"
        self.assertTrue(HELPER.is_file())
        self.assertEqual(installer.count('    "' + name + '"'), 1)
        self.assertEqual(updater.count('                "' + name + '"'), 2)
        self.assertEqual(updater.count('["' + name + '"]="$BASE_URL/modules/' + name + '"'), 1)
        self.assertEqual(updater.count('["' + name + '"]="$TEMP_DIR/' + name + '"'), 1)


if __name__ == "__main__":
    unittest.main()
