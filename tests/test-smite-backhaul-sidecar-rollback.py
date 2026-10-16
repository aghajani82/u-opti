#!/usr/bin/env python3
"""Offline-only rollback ownership, checksum and drift simulations."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules" / "smite-backhaul-sidecar-rollback.py"
module_spec = importlib.util.spec_from_file_location("bh_rollback", SCRIPT)
rollback = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(rollback)

OLD = "a" * 64
NEW = "b" * 64
DRIFT = "c" * 64


def fixtures(role="ir"):
    manifest = {
        "role": role,
        "container_name": rollback.CONTAINER[role],
        "resources": [],
    }
    observed = {"container_name": rollback.CONTAINER[role], "resources": {}}
    for path, operation in rollback.ALLOW[role].items():
        manifest["resources"].append({
            "path": path,
            "operation": operation,
            "before_sha256": OLD if operation == "edit" else None,
            "applied_sha256": NEW,
            "backup_sha256": OLD if operation == "edit" else None,
        })
        observed["resources"][path] = NEW
    return manifest, observed


class RollbackModelTests(unittest.TestCase):
    def test_only_approved_sidecar_resources(self):
        for role in ("ir", "kh"):
            manifest, observed = fixtures(role)
            plan = rollback.plan_reversal(manifest, observed)
            self.assertTrue(all(x.startswith(("PLAN ONLY:", "NOT EXECUTED")) for x in plan))
            self.assertIn(rollback.CONTAINER[role], plan[0])
            self.assertFalse(any("smite-node" in step or "frps" in step for step in plan))
            self.assertTrue(any("nginx -t" in step for step in plan))

    def test_unsafe_observations_refused(self):
        for role in ("ir", "kh"):
            for modification in ("drift", "missing", "unknown", "wrong_container"):
                manifest, observed = fixtures(role)
                path = next(iter(observed["resources"]))
                if modification == "drift":
                    observed["resources"][path] = DRIFT
                elif modification == "missing":
                    del observed["resources"][path]
                elif modification == "unknown":
                    observed["resources"]["/etc/smite-node/backhaul/old.toml"] = NEW
                else:
                    observed["container_name"] = "smite-node"
                with self.subTest(role=role, scenario=modification):
                    with self.assertRaises(rollback.RollbackUnsafe):
                        rollback.plan_reversal(manifest, observed)

    def test_missing_backup_bad_sha_and_target_tamper(self):
        for scenario in ("badbackup", "badpath", "duplicates", "missing", "wrongop", "badsha"):
            manifest, observed = fixtures()
            path = manifest["resources"][0]["path"]
            if scenario == "badbackup":
                item = next(r for r in manifest["resources"] if r["operation"] == "edit")
                item["backup_sha256"] = DRIFT
            elif scenario == "badpath":
                manifest["resources"][0]["path"] = "/opt/smite-node/config"
            elif scenario == "duplicates":
                manifest["resources"][1]["path"] = path
            elif scenario == "missing":
                manifest["resources"].pop()
            elif scenario == "wrongop":
                manifest["resources"][0]["operation"] = "edit"
            elif scenario == "badsha":
                manifest["resources"][0]["applied_sha256"] = "abc"
            with self.subTest(scenario=scenario):
                with self.assertRaises(rollback.RollbackUnsafe):
                    rollback.plan_reversal(manifest, observed)

    def test_cli_does_not_change_sample_inputs(self):
        manifest, observed = fixtures("kh")
        with tempfile.TemporaryDirectory() as dirname:
            p1, p2 = Path(dirname) / "manifest.json", Path(dirname) / "observed.json"
            p1.write_text(json.dumps(manifest))
            p2.write_text(json.dumps(observed))
            before = (p1.read_bytes(), p2.read_bytes())
            p = subprocess.run(
                [sys.executable, str(SCRIPT),
                 "--manifest", str(p1), "--observed", str(p2)],
                capture_output=True, text=True,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("NO COMMANDS EXECUTED", p.stdout)
            self.assertEqual(before, (p1.read_bytes(), p2.read_bytes()))


if __name__ == "__main__":
    unittest.main()
