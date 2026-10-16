#!/usr/bin/env python3
"""Simulate a fresh U-OPTI install/update module bundle without system changes.

Existing CI imported modules directly from the complete repository checkout,
so a missing installer/update manifest entry could stay invisible. This test
copies ONLY the declared runtime files into an isolated temporary directory,
then imports the admission gate and its transitive dependencies.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import shutil
import tempfile
import unittest


BASE = Path(__file__).resolve().parents[1]
RUNTIME = (
    "smite-backhaul-management.sh",
    "smite-tunnel-wizard.sh",
    "smite-tunnel-control-center.sh",
    "smite-backhaul-standard.sh",
    "smite-backhaul-sidecar.py",
    "smite-backhaul-sidecar-readiness.py",
    "smite-backhaul-sidecar-nginx-plan.py",
    "smite-backhaul-sidecar-reconcile.py",
    "smite-backhaul-sidecar-guided-prep.py",
    "smite-backhaul-sidecar-guided-trial.py",
    "smite-backhaul-sidecar-ssh-pair.py",
    "smite-backhaul-sidecar-paste-pair.py",
    "smite-backhaul-sidecar-admission.py",
    "smite-backhaul-sidecar-token.py",
    "smite-backhaul-sidecar-live-trial.py",
    "smite-backhaul-rebuild-gate.sh",
)


def declared_install(name: str, data: str) -> bool:
    return len(re.findall(r'^\s*"' + re.escape(name) + r'"\s*$', data, re.M)) == 1


def declared_update(name: str, data: str) -> bool:
    list_entries = re.findall(r'^\s*"' + re.escape(name) + r'"\s*$', data, re.M)
    url = f'["{name}"]="$BASE_URL/modules/{name}"'
    target = f'["{name}"]="$TEMP_DIR/{name}"'
    return len(list_entries) == 2 and data.count(url) == 1 and data.count(target) == 1


class PackageClosureTest(unittest.TestCase):
    def test_installer_and_updater_have_full_runtime_closure(self):
        installer = (BASE / "install.sh").read_text()
        updater = (BASE / "u-opti").read_text()
        for name in RUNTIME:
            with self.subTest(name=name):
                self.assertTrue((BASE / "modules" / name).is_file())
                self.assertTrue(declared_install(name, installer),
                                f"Installer missing/duplicating {name}")
                self.assertTrue(declared_update(name, updater),
                                f"Updater missing/duplicating {name}")

    def test_fresh_install_can_import_admission_without_repo_checkout(self):
        installer = (BASE / "install.sh").read_text()
        with tempfile.TemporaryDirectory(prefix="uopti-package-closure-") as tmp:
            root = Path(tmp)
            for name in RUNTIME:
                if declared_install(name, installer):
                    shutil.copyfile(BASE / "modules" / name, root / name)

            entry = root / "smite-backhaul-sidecar-admission.py"
            self.assertTrue(entry.is_file())
            spec = importlib.util.spec_from_file_location("isolated_admission", entry)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            self.assertTrue(hasattr(module, "admission"))
            self.assertTrue(hasattr(module.paired, "reconcile"))
            self.assertTrue(hasattr(module.local, "inspect_local"))
            guided_path = root / "smite-backhaul-sidecar-guided-prep.py"
            guided_spec = importlib.util.spec_from_file_location(
                "isolated_guided_prep", guided_path)
            guided = importlib.util.module_from_spec(guided_spec)
            assert guided_spec.loader is not None
            guided_spec.loader.exec_module(guided)
            self.assertTrue(hasattr(guided, "prepare_fresh_pair"))
            oneflow = root / "smite-backhaul-sidecar-guided-trial.py"
            flow_spec = importlib.util.spec_from_file_location(
                "isolated_oneflow", oneflow)
            flow = importlib.util.module_from_spec(flow_spec)
            assert flow_spec.loader is not None
            flow_spec.loader.exec_module(flow)
            self.assertTrue(hasattr(flow, "install_fresh"))
            ssh_pair_path = root / "smite-backhaul-sidecar-ssh-pair.py"
            ssh_pair_spec = importlib.util.spec_from_file_location(
                "isolated_ssh_pair", ssh_pair_path)
            ssh_pair_module = importlib.util.module_from_spec(ssh_pair_spec)
            assert ssh_pair_spec.loader is not None
            ssh_pair_spec.loader.exec_module(ssh_pair_module)
            self.assertTrue(hasattr(ssh_pair_module, "send_ir"))
            self.assertTrue(hasattr(ssh_pair_module, "receive_kh"))
            paste_path = root / "smite-backhaul-sidecar-paste-pair.py"
            paste_spec = importlib.util.spec_from_file_location(
                "isolated_bitvise_pair", paste_path)
            paste_module = importlib.util.module_from_spec(paste_spec)
            assert paste_spec.loader is not None
            paste_spec.loader.exec_module(paste_module)
            self.assertTrue(hasattr(paste_module, "show_ir"))
            self.assertTrue(hasattr(paste_module, "paste_kh"))
            self.assertTrue((root / "smite-backhaul-standard.sh").is_file())
            trial_path = root / "smite-backhaul-sidecar-live-trial.py"
            trial_spec = importlib.util.spec_from_file_location("isolated_trial", trial_path)
            trial_module = importlib.util.module_from_spec(trial_spec)
            assert trial_spec.loader is not None
            trial_spec.loader.exec_module(trial_module)
            self.assertTrue(hasattr(trial_module, "install"))
            self.assertTrue(hasattr(trial_module, "rollback"))


    def test_dependency_chain_is_still_explicit(self):
        admission = (BASE / "modules/smite-backhaul-sidecar-admission.py").read_text()
        reconcile = (BASE / "modules/smite-backhaul-sidecar-reconcile.py").read_text()
        nginx = (BASE / "modules/smite-backhaul-sidecar-nginx-plan.py").read_text()
        sidecar = (BASE / "modules/smite-backhaul-sidecar.py").read_text()
        self.assertIn('"smite-backhaul-sidecar-reconcile.py"', admission)
        self.assertIn('"smite-backhaul-sidecar-readiness.py"', admission)
        self.assertIn('"smite-backhaul-sidecar.py"', reconcile)
        self.assertIn('"smite-backhaul-sidecar-nginx-plan.py"', reconcile)
        self.assertIn('"smite-backhaul-standard.sh"', nginx)
        self.assertIn('"smite-backhaul-standard.sh"', sidecar)


if __name__ == "__main__":
    unittest.main()
