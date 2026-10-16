#!/usr/bin/env python3
"""Only simulated JSON input: no host discovery or live service operations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules" / "smite-backhaul-sidecar-preflight.py"
_spec = importlib.util.spec_from_file_location("sidecar_preflight_offline", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(mod)


def make_snapshot(role: str, now: datetime):
    listeners = (
        [
            {"address": "0.0.0.0", "port": 443, "owner": "nginx"},
            {"address": "127.0.0.1", "port": 8443, "owner": "nginx"},
            {"address": "127.0.0.1", "port": 7000, "owner": "frps"},
        ] if role == "ir"
        else [{"address": "127.0.0.1", "port": 56053, "owner": "xray"}]
    )
    return {
        "role": role,
        "observed_at": now.isoformat(),
        "ports": {"role": role, "network_mode": "host", "listeners": listeners},
        "checks": {key: True for key in mod.EXPECTED[role]},
        "versions": {"backhaul": "v0.7.2", "smite": "v0.1.7"},
        "baseline": {"legacy_clients": 0 if role == "ir" else 4},
    }


class StrictPreflightTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)

    def test_valid_simulated_snapshots_are_not_deployment_approval(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                data = make_snapshot(role, self.now - timedelta(minutes=1))
                report = mod.review(data, role, self.now)
                self.assertIn("NOT AUTHORIZED TO DEPLOY OR MERGE", report)
                self.assertTrue(all("INSTALL NOW" not in p for p in report))

    def test_missing_stale_and_future_evidence_refused(self):
        for shift in (timedelta(minutes=-16), timedelta(minutes=3)):
            snapshot = make_snapshot("ir", self.now + shift)
            with self.assertRaisesRegex(mod.PreflightRefused, "expired or future"):
                mod.review(snapshot, "ir", self.now)
        snapshot = make_snapshot("ir", self.now)
        snapshot["observed_at"] = "2026-10-13T09:00:00"
        with self.assertRaisesRegex(mod.PreflightRefused, "UTC offset"):
            mod.review(snapshot, "ir", self.now)

    def test_require_exact_state_checks_and_versions(self):
        for role in ("ir", "kh"):
            for key in mod.EXPECTED[role]:
                with self.subTest(role=role, check=key):
                    snapshot = make_snapshot(role, self.now)
                    snapshot["checks"][key] = False
                    with self.assertRaisesRegex(mod.PreflightRefused, "incomplete"):
                        mod.review(snapshot, role, self.now)
            for name, version in (("backhaul", "v0.7.1"), ("smite", "v0.1.8")):
                snapshot = make_snapshot(role, self.now)
                snapshot["versions"][name] = version
                with self.assertRaisesRegex(mod.PreflightRefused, "version"):
                    mod.review(snapshot, role, self.now)

    def test_port_conflicts_missing_owners_and_legacy_drift(self):
        for role, reserved_port in (("ir", 3080), ("ir", 56053), ("kh", 13080)):
            with self.subTest(role=role, port=reserved_port):
                snapshot = make_snapshot(role, self.now)
                snapshot["ports"]["listeners"].append(
                    {"address": "::", "port": reserved_port, "owner": "unknown"}
                )
                with self.assertRaisesRegex(mod.PreflightRefused, "port owner"):
                    mod.review(snapshot, role, self.now)
        for role in ("ir", "kh"):
            snapshot = make_snapshot(role, self.now)
            snapshot["baseline"]["legacy_clients"] += 1
            with self.assertRaisesRegex(mod.PreflightRefused, "baseline"):
                mod.review(snapshot, role, self.now)

    def test_missing_extra_or_forged_structure_fails(self):
        sample = make_snapshot("ir", self.now)
        sample["secret"] = "unused"
        with self.assertRaisesRegex(mod.PreflightRefused, "fields"):
            mod.review(sample, "ir", self.now)
        sample = make_snapshot("ir", self.now)
        sample["checks"]["extra"] = True
        with self.assertRaisesRegex(mod.PreflightRefused, "checks"):
            mod.review(sample, "ir", self.now)
        sample = make_snapshot("ir", self.now)
        sample["ports"]["listeners"].pop()
        with self.assertRaisesRegex(mod.PreflightRefused, "port owner"):
            mod.review(sample, "ir", self.now)
        sample = make_snapshot("ir", self.now)
        with self.assertRaisesRegex(mod.PreflightRefused, "Role mismatch"):
            mod.review(sample, "kh", self.now)

    def test_cli_from_private_snapshot_only_no_secrets_echoed(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "snapshot.json"
            snapshot = make_snapshot("kh", datetime.now(timezone.utc))
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            ret = subprocess.run(
                [sys.executable, str(SCRIPT), "--role", "kh", "--snapshot", str(path)],
                capture_output=True, text=True,
            )
            self.assertEqual(ret.returncode, 0, ret.stderr)
            self.assertIn("NOT AUTHORIZED", ret.stdout)
            self.assertNotIn("127.0.0.1", ret.stdout)
            path.unlink()
            path.symlink_to(Path(name) / "missing")
            ret = subprocess.run(
                [sys.executable, str(SCRIPT), "--role", "kh", "--snapshot", str(path)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(ret.returncode, 0)
            self.assertIn("FAIL CLOSED", ret.stderr)


if __name__ == "__main__":
    unittest.main()
