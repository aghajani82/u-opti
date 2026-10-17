#!/usr/bin/env python3
"""Hermetic Profile First tests: no Docker, Nginx, Smite or real VPS access."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "modules/smite-profile-first.py"
spec = importlib.util.spec_from_file_location("profile_first_test", SRC)
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class ProfileFirstTest(unittest.TestCase):
    def test_distinct_custom_paths_and_ports_are_valid(self):
        doc = plan.validate("13914", "/13914/shop", "58408", "/58408/ooo")
        self.assertEqual(doc["frp"]["port"], 13914)
        self.assertEqual(doc["backhaul"]["path"], "/58408/ooo")

    def test_overlapping_and_unsafe_profiles_refused(self):
        bad = [
            ("13914", "/13914/shop", "13914", "/58408/ooo"),
            ("13914", "/13914/shop", "58408", "/13914/shop"),
            ("13914", "/13914/shop", "58408", "/13914/shop/extra"),
            ("13914", "/tunnel/secret", "58408", "/58408/ooo"),
            ("13914", "/13914/shop", "58408", "/api"),
            ("13914", "/13914/shop", "58408", "/12345/ooo"),
            ("00013914", "/13914/shop", "58408", "/58408/ooo"),
        ]
        for fp, fx, bp, bx in bad:
            with self.subTest(fp=fp, fx=fx, bp=bp, bx=bx):
                with self.assertRaises(plan.ProfileHold):
                    plan.validate(fp, fx, bp, bx)

    def test_cli_check_does_not_touch_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tunnels" / "profile-first.json"
            argv = ["planner", "--check", "--file", str(path),
                    "--frp-port", "13914", "--frp-path", "/13914/shop",
                    "--backhaul-port", "58408", "--backhaul-path", "/58408/ooo"]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as out:
                self.assertEqual(plan.main(), 0)
            self.assertIn("PROFILE_FIRST_VALID", out.getvalue())
            self.assertFalse(path.exists())

    def test_save_idempotent_and_existing_plan_no_overwrite(self):
        doc = plan.validate("13914", "/13914/shop", "58408", "/58408/ooo")
        updated = plan.validate("13914", "/13914/new", "58408", "/58408/ooo")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tunnels" / "profile-first.json"
            with patch.object(plan.os, "geteuid", return_value=0), \
                 patch.object(plan, "safe_dir"), patch.object(plan, "safe_file"):
                self.assertEqual(plan.store(path, doc), "PROFILE_FIRST_SAVED_NO_SERVICES_CHANGED")
                self.assertEqual(plan.load(path), doc)
                self.assertEqual(plan.store(path, doc), "PROFILE_FIRST_ALREADY_MATCHED_NO_CHANGE")
                with self.assertRaises(plan.ProfileHold):
                    plan.store(path, updated)
                with patch.object(plan, "active_traces", return_value=True):
                    with self.assertRaises(plan.ProfileHold):
                        plan.store(path, updated, replace=True)
                self.assertEqual(plan.load(path), doc)

    def test_live_auto_published_route_prevents_profile_replacement(self):
        doc = plan.validate("13914", "/13914/shop", "58408", "/58408/ooo")
        updated = plan.validate("13914", "/13914/changed", "58408", "/58408/ooo")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            routes = root / "frp-routes.inc"
            routes.write_text("# FRP Nginx\n    location = /13914/shop {\n")
            path = root / "tunnels" / "profile-first.json"
            with patch.object(plan, "FRP_NGINX_ROUTES", routes), \
                 patch.object(plan.os, "geteuid", return_value=0), \
                 patch.object(plan, "safe_dir"), patch.object(plan, "safe_file"):
                self.assertEqual(plan.store(path, doc), "PROFILE_FIRST_SAVED_NO_SERVICES_CHANGED")
                self.assertTrue(plan.active_traces())
                with self.assertRaises(plan.ProfileHold):
                    plan.store(path, updated, replace=True)
                self.assertEqual(plan.load(path), doc)

    def test_missing_plan_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "tunnels"
            parent.mkdir()
            path = parent / "profile-first.json"
            self.assertIsNone(plan.load(path))
            target = Path(tmp) / "other"
            target.write_text("anything")
            path.symlink_to(target)
            with self.assertRaises(plan.ProfileHold):
                plan.load(path)



FRP_SRC = Path(__file__).resolve().parents[1] / "modules/smite-frp-xhttp-paths.py"
frp_spec = importlib.util.spec_from_file_location("frp_profile_first_test", FRP_SRC)
frp = importlib.util.module_from_spec(frp_spec)
frp_spec.loader.exec_module(frp)


class FRPProfileFirstSyncTests(unittest.TestCase):
    """Test the real Nginx renderer with synthetic Smite tunnel JSON only."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.profile = root / "tunnels" / "profile-first.json"
        self.profile.parent.mkdir(mode=0o700)
        self.profile.write_text(
            '{"version":1,"frp":{"port":42175,"path":"/42175/windows64"},'
            '"backhaul":{"port":12744,"path":"/12744/software"}}\n',
            encoding="utf-8",
        )
        self.profile.chmod(0o600)
        self.registry = root / "registry.json"
        self.snapshot = root / "tunnels.json"
        self.output = root / "nginx.conf"
        self.sidecar = root / "no-sidecar.inc"
        self.patchers = [
            patch.object(frp, "PROFILE_FIRST_PLAN", self.profile),
            patch.object(frp, "SIDECAR_INCLUDE", self.sidecar),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def applied(self, port=42175):
        self.snapshot.write_text(
            '{"t1":{"core":"frp","spec":{"mode":"server","type":"tcp",'
            '"ports":[{"remote":' + str(port) + '}]}}}\n',
            encoding="utf-8",
        )

    def test_saved_plan_auto_renders_only_applied_port(self):
        self.applied()
        with redirect_stdout(io.StringIO()):
            frp.render(self.snapshot, self.output, self.registry)
        nginx = self.output.read_text()
        self.assertIn("location = /42175/windows64 {", nginx)
        self.assertIn("location ^~ /42175/windows64/ {", nginx)
        self.assertIn("proxy_pass http://127.0.0.1:42175;", nginx)
        self.assertNotIn("/42175/web", nginx)
        self.assertNotIn("/12744/software", nginx)

    def test_no_applied_frp_means_no_gateway_route(self):
        self.snapshot.write_text("{}\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            frp.render(self.snapshot, self.output, self.registry)
        self.assertNotIn("location =", self.output.read_text())

    def test_no_plan_keeps_legacy_behavior(self):
        self.profile.unlink()
        self.applied()
        with redirect_stdout(io.StringIO()):
            frp.render(self.snapshot, self.output, self.registry)
        self.assertIn("location = /42175/web {", self.output.read_text())

    def test_explicit_registry_overrides_saved_plan(self):
        self.applied()
        self.registry.write_text('{"42175":"/42175/manual"}\n', encoding="utf-8")
        self.registry.chmod(0o600)
        with redirect_stdout(io.StringIO()):
            frp.render(self.snapshot, self.output, self.registry)
        content = self.output.read_text()
        self.assertIn("location = /42175/manual {", content)
        self.assertNotIn("/42175/windows64", content)

    def test_other_applied_port_keeps_legacy_default(self):
        self.applied(45123)
        with redirect_stdout(io.StringIO()):
            frp.render(self.snapshot, self.output, self.registry)
        self.assertIn("location = /45123/web {", self.output.read_text())
        self.assertNotIn("/42175/windows64", self.output.read_text())

    def test_unsafe_plan_fails_closed(self):
        self.applied()
        self.profile.chmod(0o644)
        with self.assertRaises(frp.RouteError):
            frp.render(self.snapshot, self.output, self.registry)
        self.assertFalse(self.output.exists())

    def test_symlinked_plan_fails_closed(self):
        self.applied()
        other = self.profile.with_name("valid-plan.json")
        self.profile.rename(other)
        self.profile.symlink_to(other)
        with self.assertRaises(frp.RouteError):
            frp.render(self.snapshot, self.output, self.registry)
        self.assertFalse(self.output.exists())

    def test_saved_path_overlapping_sidecar_is_rejected(self):
        self.applied()
        self.sidecar.write_text("    location = /42175/windows64 {\n")
        with self.assertRaises(frp.RouteError):
            frp.render(self.snapshot, self.output, self.registry)

    def test_readonly_get_reports_effective_path_from_plan(self):
        argv = ["frp", "get", "42175"]
        with patch.object(sys, "argv", argv), \
             patch.object(frp, "DEFAULT_MAP", self.registry), \
             redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(frp.main(), 0)
        self.assertEqual(stdout.getvalue().strip(), "/42175/windows64")

if __name__ == "__main__":
    unittest.main()
