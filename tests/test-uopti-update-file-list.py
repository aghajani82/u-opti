#!/usr/bin/env python3
"""Regression: critical Smite broker files must participate in U-OPTI updates."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "u-opti"
INSTALLER = ROOT / "install.sh"

CRITICAL_BROKER_FILES = {
    "smite-clean-rc-preflight.sh",
    "smite-xhttp-nginx-route",
    "smite_xhttp_nginx_plan.py",
    "smite-rc5-xhttp-root-broker.py",
    "smite-rc5-xhttp-broker-provision.py",
    "smite-rc5-xhttp-nonce-ledger.py",
    "smite-rc5-xhttp-signed-intent.py",
    "smite-rc5-xhttp-bridge-install.py",
    "smite-rc5-xhttp-bridge-admission.py",
}


def array_body(source: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*=\((.*?)^\s*\)", source, re.M | re.S)
    if not match:
        raise AssertionError(f"Could not find updater array {name}")
    return match.group(1)


def quoted_names(body: str) -> set[str]:
    return set(re.findall(r'"([^"\n]+)"', body))


class UpdaterFileListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = UPDATER.read_text()
        cls.installer = INSTALLER.read_text()

    def test_all_updated_modules_participate_in_backup(self):
        updated = quoted_names(array_body(self.source, "UPDATE_FILE_NAMES"))
        self.assertIn('BACKUP_FILES=("${UPDATE_FILE_NAMES[@]}")', self.source)
        self.assertTrue(updated)

    def test_stage15_executor_imports_from_actual_first_install_file_set(self):
        installed = quoted_names(array_body(self.installer, "MODULES"))
        with tempfile.TemporaryDirectory() as temp:
            for name in installed:
                shutil.copyfile(ROOT / "modules" / name, Path(temp) / name)
            result = subprocess.run([sys.executable, "-B",
                str(Path(temp) / "smite-stage15-frp-host-executor.py"), "--help"],
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_broker_modules_are_downloaded_compared_and_backed_up(self):
        names = {
            "UPDATE_FILE_NAMES": quoted_names(array_body(self.source, "UPDATE_FILE_NAMES")),
        }
        for array, items in names.items():
            with self.subTest(array=array):
                self.assertTrue(
                    CRITICAL_BROKER_FILES.issubset(items),
                    f"{array} missing: {sorted(CRITICAL_BROKER_FILES - items)}",
                )


    def test_rc7_wss_read_only_plan_installed_and_updated(self):
        helper = "smite-rc7-wss-preflight.py"
        for array in ("UPDATE_FILE_NAMES",):
            with self.subTest(array=array):
                self.assertIn(helper, quoted_names(array_body(self.source, array)))
        self.assertIn(helper, quoted_names(array_body(self.installer, "MODULES")))

    def test_rc7_wss_activation_modules_installed_and_updated(self):
        for helper in ("smite-rc7-wss-runtime.py", "smite-rc7-wss-edge.py"):
            for array in ("UPDATE_FILE_NAMES",):
                with self.subTest(helper=helper, array=array):
                    self.assertIn(helper, quoted_names(array_body(self.source, array)))
            self.assertIn(helper, quoted_names(array_body(self.installer, "MODULES")))

    def test_rc7_frp_enrollment_in_installer_and_updater(self):
        helper = "smite-rc7-frp-enrollment.py"
        for name in ("UPDATE_FILE_NAMES",):
            self.assertIn(helper, quoted_names(array_body(self.source, name)))
        self.assertIn(helper, quoted_names(array_body(self.installer, "MODULES")))

    def test_fresh_install_packages_all_updater_managed_modules(self):
        """First installs must not omit modules required by later RC flows."""
        installed = quoted_names(array_body(self.installer, "MODULES"))
        updated = quoted_names(array_body(self.source, "UPDATE_FILE_NAMES"))
        self.assertFalse(
            updated - installed,
            f"First install missing updater-managed modules: {sorted(updated - installed)}",
        )
        # These legacy extras have their own compatibility/bootstrap paths.
        self.assertEqual(
            installed - updated,
            {
                "smite-digest-migrate.sh",
                "smite-private-network.sh",
                "smite-easytier.sh",
            },
        )
        self.assertIn("smite-clean-rc-preflight.sh", installed)
        self.assertIn(
            "smite_clean_rc_prepare_gateway_packages()",
            self.installer,
        )
        self.assertIn(
            'SMITE_RC_PREFLIGHT_MODULE="$MODULES_PATH/smite-clean-rc-preflight.sh"',
            self.source,
        )
        self.assertLess(
            self.installer.index('smite_clean_rc_prepare_gateway_packages()'),
            self.installer.index("Preparing recoverable installation transaction..."),
        )

    def test_signed_rc7_root_is_installed_and_transactionally_updated(self):
        name = "smite-rc7-sigstore-trusted-root.json"
        installed = quoted_names(array_body(self.installer, "MODULES"))
        managed = quoted_names(array_body(self.source, "UPDATE_FILE_NAMES"))
        self.assertIn(name, installed)
        self.assertIn(name, managed)
        self.assertIn('BACKUP_FILES=("${UPDATE_FILE_NAMES[@]}")'.replace("\\$", "$"),
                      self.source)
        self.assertIn('.${FILE}-was-missing', self.source)
        self.assertTrue((ROOT / "modules" / name).is_file())

    def test_running_old_updater_imports_exact_candidate_inventory_before_backup(self):
        # Test real updater Bash block, not a separate reimplementation.
        # The fetched candidate's SHA/Git blob is verified by
        # download_repo_file before this block consumes the literal array.
        begin = "            # A running OLD launcher cannot know new module names introduced"
        end = "            # UPDATE_FILE_NAMES is the one authoritative inventory for download,"
        segment = self.source[self.source.index(begin):self.source.index(end)]
        self.assertIn('download_repo_file "u-opti" "$TEMP_DIR/u-opti"', segment)
        self.assertIn("u_opti_verify_source_blob", segment)
        self.assertIn("PY_UPDATER_CANDIDATE_INVENTORY", segment)
        self.assertNotIn("source \"$TEMP_DIR/u-opti\"", segment)
        self.assertNotIn("eval ", segment)

        fixtures = (
            ("add-root", ("base.sh", "smite-rc7-sigstore-trusted-root.json"),
             True),
            ("same", ("base.sh",), True),
            ("remove-existing", ("replacement.sh",), False),
            ("duplicate", ("base.sh", "base.sh"), False),
            ("malformed-name", ("base.sh", "../injected.sh"), False),
            ("shell-expansion", ("base.sh", "$(touch /tmp/never-executed)"),
             False),
        )
        for scenario, names, allowed in fixtures:
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as temp:
                    lab = Path(temp)
                    stage = lab / "stage"; stage.mkdir()
                    candidate = lab / "candidate"
                    old = lab / "old-launcher"
                    old.write_text("old byte-for-byte launcher\n")
                    inventory = "\n".join(
                        '                "' + n + '"' for n in names
                    )
                    candidate.write_text(
                        "#!/bin/bash\n"
                        "            UPDATE_FILE_NAMES=(\n"
                        + inventory + "\n            )\n",
                    )
                    bash = (
                        "set -u\n"
                        f"TEMP_DIR={stage}\nINSTALL_PATH={old}\n"
                        f"CANDIDATE={candidate}\n"
                        'UPDATE_FILE_NAMES=("base.sh")\n'
                        'u_opti_verify_source_blob() { cmp -s "$2" "$CANDIDATE"; }\n'
                        'download_repo_file() { cp -- "$CANDIDATE" "$2"; }\n'
                        'cleanup_update_temp() { :; }\n'
                        "for _round in once; do\n"
                        + segment +
                        'printf "RESULT=%s\\n" "${UPDATE_FILE_NAMES[@]}"\n'.replace("\\$", "$")
                        + "done\n"
                    )
                    proc = subprocess.run(
                        ["bash", "-c", bash], capture_output=True, text=True,
                        timeout=10,
                    )
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    if allowed:
                        self.assertIn("RESULT=base.sh", proc.stdout)
                        if scenario == "add-root":
                            self.assertIn(
                                "RESULT=smite-rc7-sigstore-trusted-root.json",
                                proc.stdout,
                            )
                    else:
                        self.assertNotIn("RESULT=", proc.stdout)
                        self.assertIn("HOLD:", proc.stdout + proc.stderr)
                    self.assertFalse((lab / "never-executed").exists())

    def test_matching_launcher_does_not_redownload_or_expand_file_list(self):
        begin = "            # A running OLD launcher cannot know new module names introduced"
        end = "            # UPDATE_FILE_NAMES is the one authoritative inventory for download,"
        segment = self.source[self.source.index(begin):self.source.index(end)]
        with tempfile.TemporaryDirectory() as temp:
            lab = Path(temp)
            candidate = lab / "candidate"
            candidate.write_text("#!/bin/bash\n")
            stage = lab / "stage"; stage.mkdir()
            bash = (
                "set -u\n"
                f"TEMP_DIR={stage}\nINSTALL_PATH={candidate}\n"
                f"CANDIDATE={candidate}\n"
                'UPDATE_FILE_NAMES=("base.sh")\n'
                'u_opti_verify_source_blob() { cmp -s "$2" "$CANDIDATE"; }\n'
                'download_repo_file() { echo UNEXPECTED_DOWNLOAD; return 1; }\n'
                'cleanup_update_temp() { :; }\n'
                "for _round in once; do\n"
                + segment +
                'printf "RESULT=%s\\n" "${UPDATE_FILE_NAMES[@]}"\n'.replace("\\$", "$")
                + "done\n"
            )
            proc = subprocess.run(["bash", "-c", bash],
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("RESULT=base.sh", proc.stdout)
            self.assertNotIn("UNEXPECTED_DOWNLOAD", proc.stdout)

    def test_fresh_installer_checks_python_json_and_shell_separately(self):
        """Avoid repeating the older updater bug during fresh installation."""
        import json

        self.assertIn('*.py|smite-xhttp-nginx-route) python3 -m py_compile', self.installer)
        self.assertIn('*.json) python3 -c', self.installer)
        self.assertIn('json.load(open(sys.argv[1]', self.installer)
        self.assertIn('*) bash -n "$TEMP_DIR/$MODULE"', self.installer)
        candidate = ROOT / "modules/smite-field-trial-candidate.json"
        json.loads(candidate.read_text(encoding="utf-8"))
        helper = ROOT / "modules/smite-xhttp-nginx-route"
        compile(helper.read_text(encoding="utf-8"), str(helper), "exec")


    def test_extensionless_xhttp_route_is_checked_as_python(self):
        """Prevent the updater from running bash -n on a Python helper."""
        helper = ROOT / "modules/smite-xhttp-nginx-route"
        source = helper.read_text()
        self.assertTrue(source.startswith("#!/usr/bin/env python3"))
        compile(source, str(helper), "exec")
        self.assertIn("smite-xhttp-nginx-route", quoted_names(array_body(self.source, "UPDATE_FILE_NAMES")))
        self.assertIn('"$TEMP_DIR/"*.py)', self.source)
        self.assertIn('"$TEMP_DIR/smite-xhttp-nginx-route")', self.source)

    def test_json_candidate_is_checked_as_json(self):
        """Prevent the updater from running bash -n on a JSON candidate."""
        import json

        candidate = ROOT / "modules/smite-field-trial-candidate.json"
        json.loads(candidate.read_text())
        self.assertIn(
            "smite-field-trial-candidate.json",
            quoted_names(array_body(self.source, "UPDATE_FILE_NAMES")),
        )
        self.assertIn('"$TEMP_DIR/"*.json)', self.source)
        self.assertIn("json.load(open(sys.argv[1]", self.source)


    def test_legacy_missing_optional_modules_are_journal_backed(self):
        """An older installation legitimately lacks newly added Smite modules."""
        import os
        source = self.source
        start = source.index('            for FILE in "${BACKUP_FILES[@]}"; do\\n'.replace('\\n', '\n'))
        end = source.index('            if [ ! -f "$BACKUP_DIR/u-opti" ]', start)
        body = source[start:end]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mods, backup = root / "modules", root / "backup"
            mods.mkdir()
            backup.mkdir()
            (mods / "system.sh").write_text("unchanged core", encoding="utf-8")
            script = (
                'set -e\\n'.replace('\\n', '\n')
                + 'BACKUP_FILES=(system.sh smite-profile-first.py smite-profile-first-menu.sh '
                'smite-tunnel-wizard.sh smite-tunnel-control-center.sh)\\n'.replace('\\n', '\n')
                + 'BACKUP_OK=true\\n'.replace('\\n', '\n')
                + body + 'printf "BACKUP_OK=%s\\n" "$BACKUP_OK"\\n'.replace('\\n', '\n')
            )
            env = dict(os.environ, MODULES_PATH=str(mods), BACKUP_DIR=str(backup))
            result = subprocess.run(["bash", "-c", script], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("BACKUP_OK=true", result.stdout)
            self.assertEqual((backup / "system.sh").read_text(), "unchanged core")
            for name in ("smite-profile-first.py", "smite-profile-first-menu.sh",
                         "smite-tunnel-wizard.sh", "smite-tunnel-control-center.sh"):
                self.assertTrue((backup / ("." + name + "-was-missing")).is_file())
            (mods / "system.sh").unlink()
            result = subprocess.run(["bash", "-c", script], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("BACKUP_OK=false", result.stdout)
            self.assertIn("Installed module was not found: system.sh", result.stdout)


if __name__ == "__main__":
    unittest.main()
