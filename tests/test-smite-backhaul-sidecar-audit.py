#!/usr/bin/env python3
"""Offline JSON listener-snapshot safety regressions (no host inspection)."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules" / "smite-backhaul-sidecar-audit.py"
spec = importlib.util.spec_from_file_location("audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

IR = {"role": "ir", "network_mode": "host", "listeners": [
    {"address": "0.0.0.0", "port": 443, "owner": "nginx"},
    {"address": "127.0.0.1", "port": 8443, "owner": "nginx"},
    {"address": "127.0.0.1", "port": 7000, "owner": "frps"},
]}
KH = {"role": "kh", "network_mode": "host", "legacy_backhaul_clients": 4,
      "listeners": [{"address": "127.0.0.1", "port": 56053, "owner": "xray"}]}


class SidecarAuditTests(unittest.TestCase):
    def test_expected_topology_snapshots(self):
        for role, inventory in (("ir", IR), ("kh", KH)):
            result = audit.audit(inventory, role)
            self.assertTrue(all(line.startswith("PASS:") for line in result))

    def test_any_port_collision_blocks(self):
        for role, inventory, target in (
            ("ir", IR, 3080), ("ir", IR, 56053), ("kh", KH, 13080)
        ):
            for address in ("0.0.0.0", "::", "127.0.0.1", "91.107.174.237"):
                snapshot = json.loads(json.dumps(inventory))
                snapshot["listeners"].append(
                    {"address": address, "port": target, "owner": "unknown"}
                )
                result = audit.audit(snapshot, role)
                self.assertTrue(any(s.startswith(f"BLOCK: planned port {target} ") for s in result))

    def test_missing_and_incorrect_owner_fails(self):
        snapshot = json.loads(json.dumps(IR))
        snapshot["listeners"][1]["owner"] = "other"
        self.assertTrue(any("existing nginx port 8443 missing" in s
                            for s in audit.audit(snapshot, "ir")))
        snapshot = json.loads(json.dumps(KH))
        snapshot["listeners"][0]["address"] = "0.0.0.0"
        self.assertTrue(any("not bound on IPv4 loopback" in s
                            for s in audit.audit(snapshot, "kh")))

    def test_invalid_and_ambiguous_inventory_rejected(self):
        samples = [
            {**IR, "network_mode": "bridge"},
            {**IR, "role": "kh"},
            {**IR, "listeners": []},
            {**IR, "listeners": [{**IR["listeners"][0], "port": "443"}]},
            {**IR, "listeners": [{**IR["listeners"][0], "port": True}]},
            {**IR, "listeners": [{**IR["listeners"][0], "address": "example.com"}]},
            {**IR, "listeners": [IR["listeners"][0], IR["listeners"][0]]},
            {**IR, "listeners": [{**IR["listeners"][0], "token": "not allowed"}]},
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                with self.assertRaises(audit.AuditError):
                    audit.audit(sample, "ir")

    def test_cli_snapshot_only_and_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "inventory.json"
            snapshot.write_text(json.dumps(KH))
            argv = [sys.executable, str(SCRIPT), "--role", "kh",
                    "--snapshot", str(snapshot)]
            p = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("NOT LIVE HOST STATUS", p.stdout)
            self.assertIn("NOT AUTHORIZATION", p.stdout)
            inventory = json.loads(snapshot.read_text())
            inventory["listeners"].append(
                {"address": "127.0.0.1", "port": 13080, "owner": "unknown"})
            snapshot.write_text(json.dumps(inventory))
            p = subprocess.run(argv, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("BLOCK: planned port 13080", p.stdout)


if __name__ == "__main__":
    unittest.main()
