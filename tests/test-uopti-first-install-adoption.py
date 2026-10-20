#!/usr/bin/env python3
"""Execute the real installer commit block using disposable paths.

CI-only offline harness, no curl/apt/root/VPS. The Python stub inside the
synthetic download directory imports and calls the actual transaction helper
with TEST_LIB/TEST_INSTALL; the Bash block is copied VERBATIM from install.sh.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
HELPER = ROOT / "modules/u-opti-update-transaction.py"
BEGIN = 'echo "Preparing recoverable installation transaction..."'
END = 'echo "======================================"\necho "       Installation completed"'
MODULES = ["alpha.sh", "new.py"]
LAUNCHER = (
    b'#!/bin/bash\n'
    b'if [ -e "$LIB_PATH/.uopti-update-pending" ]; then\n'
    b'    python3 -B "$RECOVERY_SCRIPT" recover\n'
    b'    exec "$INSTALL_PATH" "$@"\n'
    b'fi\n'
    b'source "$LIB_PATH/common.sh"\n'
)


def installer_commit_block():
    source = INSTALLER.read_text(encoding="utf-8")
    i = source.find(BEGIN)
    j = source.find(END, i)
    if i < 0 or j < 0 or j < i or j - i > 11000:
        raise AssertionError("Original install transaction block changed; review test")
    return source[i:j]


class FirstInstallAndAdoptionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-fresh-adoption-test-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bin = root / "bin"
        self.lib = root / "lib"
        self.stage = root / "stage"
        for d in (self.bin, self.stage):
            d.mkdir(mode=0o700)
        self.install = self.bin / "u-opti"
        self.modules = self.lib / "modules"
        self.staged = {
            "u-opti": LAUNCHER + b'echo new\n',
            "common.sh": b"# new common\n",
            "VERSION": b"0.17.0\n",
            "alpha.sh": b"echo new alpha\n",
            "new.py": b"print('new')\n",
        }
        for name, data in self.staged.items():
            (self.stage / name).write_bytes(data)
        stub = self.stage / "u-opti-update-transaction.py"
        # This exact CLI wrapper calls the actual real helper. Its only
        # injected values are disposable lib and install filesystem paths.
        stub.write_text(
            "import importlib.util, os, pathlib, sys, signal\n"
            f"spec=importlib.util.spec_from_file_location('actual_helper', {str(HELPER)!r})\n"
            "m=importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "original=m._atomic\n"
            "def injected(path, body, mode):\n"
            "    original(path, body, mode)\n"
            "    if os.environ.get('INJECT_PARENT_KILL')=='YES' and "
            "path == pathlib.Path(os.environ['TEST_LIB'])/'common.sh':\n"
            "        os.kill(os.getppid(), signal.SIGKILL)\n"
            "        os._exit(91)\n"
            "m._atomic=injected\n"
            "stage, backup=map(pathlib.Path,sys.argv[2:4])\n"
            "mods=sys.argv[4:]\n"
            "m.apply(stage, backup, mods,\n"
            "        lib=pathlib.Path(os.environ['TEST_LIB']),\n"
            "        install=pathlib.Path(os.environ['TEST_INSTALL']))\n"
        )
        self.legacy = {
            "u-opti": b"#!/bin/bash\necho legacy\n",
            "common.sh": b"# old common\n",
            "VERSION": b"0.16.7\n",
            "alpha.sh": b"echo old alpha\n",
        }
        self.env = {**os.environ, "TEST_LIB": str(self.lib),
                    "TEST_INSTALL": str(self.install)}

    def _script(self):
        return (
            "set -e\n"
            f"LIB_PATH={str(self.lib)!r}\n"
            f"MODULES_PATH={str(self.modules)!r}\n"
            f"INSTALL_PATH={str(self.install)!r}\n"
            f"TEMP_DIR={str(self.stage)!r}\n"
            "BRANCH=feature/test-closeout\n"
            "MODULES=(alpha.sh new.py)\n"
            + installer_commit_block()
        )

    def _run(self, *, adopt=False, kill=False):
        env = {**self.env, "U_OPTI_ADOPT_EXISTING": "YES" if adopt else "NO",
               "INJECT_PARENT_KILL": "YES" if kill else "NO"}
        return subprocess.run(
            ["bash", "-c", self._script()],
            capture_output=True, text=True, env=env, timeout=12,
        )

    def _setup_legacy(self):
        self.modules.mkdir(parents=True, mode=0o700)
        for name, data in self.legacy.items():
            path = (self.install if name=="u-opti" else
                    self.lib/name if name in ("common.sh", "VERSION")
                    else self.modules/name)
            path.write_bytes(data)
            path.chmod(0o755)

    def _dest(self, name):
        return (self.install if name=="u-opti" else
                self.lib/name if name in ("common.sh", "VERSION")
                else self.modules/name)

    def _recover_in_fresh_python(self):
        code = (
            "import importlib.util,pathlib\n"
            f"s=importlib.util.spec_from_file_location('real', {str(HELPER)!r})\n"
            "m=importlib.util.module_from_spec(s)\ns.loader.exec_module(m)\n"
            f"print(m.recover(lib=pathlib.Path({str(self.lib)!r}),"
            f"install=pathlib.Path({str(self.install)!r})))\n"
        )
        return subprocess.run([sys.executable, "-B", "-c", code],
                              capture_output=True, text=True, timeout=10)

    def test_brand_new_install_uses_recoverable_journal_and_pins_channel(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("journal-backed installation", r.stdout)
        for name, data in self.staged.items():
            self.assertEqual(self._dest(name).read_bytes(), data)
        self.assertEqual((self.lib/"INSTALL_REF").read_text(),
                         "feature/test-closeout\n")
        self.assertFalse((self.lib/".uopti-update-pending").exists())
        self.assertEqual(len(list(self.lib.glob(".uopti-backup-*"))), 1)

    def test_existing_install_holds_without_adoption_consent(self):
        self._setup_legacy()
        r = self._run()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("HOLD: Existing U-OPTI installation", r.stderr)
        for name, data in self.legacy.items():
            self.assertEqual(self._dest(name).read_bytes(), data)
        self.assertFalse(self._dest("new.py").exists())
        self.assertFalse((self.lib/".uopti-update-pending").exists())

    def test_first_legacy_adoption_succeeds_preserving_old_backups(self):
        self._setup_legacy()
        r = self._run(adopt=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for name, data in self.staged.items():
            self.assertEqual(self._dest(name).read_bytes(), data)
        backups = list(self.lib.glob(".uopti-backup-*"))
        self.assertEqual(len(backups), 1)
        for name, data in self.legacy.items():
            self.assertEqual((backups[0] / name).read_bytes(), data)
        self.assertTrue((backups[0]/".new.py-was-missing").is_file())

    def test_fresh_crash_recovers_to_empty_install_on_new_process(self):
        # SIGKILL only sandbox Bash, then independent interpreter recovers.
        r = self._run(kill=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self._dest("u-opti").read_bytes(), self.staged["u-opti"])
        self.assertTrue((self.lib/".uopti-update-pending"/"manifest.json").is_file())
        recovered = self._recover_in_fresh_python()
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("ROLLED_BACK_FROM_DURABLE_JOURNAL", recovered.stdout)
        for name in self.staged:
            self.assertFalse(self._dest(name).exists(), name)
        self.assertTrue(self.lib.is_dir())

    def test_adoption_crash_restores_exact_previous_install(self):
        self._setup_legacy()
        r = self._run(adopt=True, kill=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.lib/".uopti-update-pending").is_dir())
        recovered = self._recover_in_fresh_python()
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        for name, data in self.legacy.items():
            self.assertEqual(self._dest(name).read_bytes(), data)
        self.assertFalse(self._dest("new.py").exists())
        self.assertFalse((self.lib/".uopti-update-pending").exists())

    def test_foreign_symlink_hold_before_writing(self):
        self._setup_legacy()
        (self.modules/"alpha.sh").unlink()
        (self.modules/"alpha.sh").symlink_to(self.stage/"alpha.sh")
        r = self._run(adopt=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("HOLD: Unsafe symlink", r.stderr)
        self.assertEqual(self._dest("u-opti").read_bytes(), self.legacy["u-opti"])
        self.assertFalse((self.lib/".uopti-update-pending").exists())

    def test_installer_recovery_guard_precedes_network_and_packages(self):
        s = INSTALLER.read_text()
        recovery = 'python3 -B "$RESCUE" recover'
        self.assertLess(s.index(recovery), s.index("REQUIRED_PACKAGES=("))
        self.assertLess(s.index(recovery), s.index("Downloading VERSION"))
        self.assertLess(s.index("u_opti_resolve_source_sha"),
                        s.index("Downloading VERSION"))
        self.assertIn('U_OPTI_ADOPT_EXISTING:-NO', s)
        self.assertNotIn('cp "$TEMP_DIR/u-opti" "$INSTALL_PATH"', s)
        self.assertIn('python3 -B "$TEMP_DIR/u-opti-update-transaction.py" apply',
                      s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
