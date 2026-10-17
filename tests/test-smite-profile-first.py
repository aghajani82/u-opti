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


if __name__ == "__main__":
    unittest.main()
