#!/usr/bin/env python3
"""Disposable transaction/reboot simulator exercising REAL updater helper.

No host files, services, network or GitHub traffic. An independent Python
child exits with os._exit(91) after the second actual atomic replacement,
then a NEW interpreter invokes the real recovery code from a different path.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "modules/u-opti-update-transaction.py"
spec = importlib.util.spec_from_file_location("uopti_recovery_test_real", HELPER)
txn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(txn)

MODULES = ["alpha.sh", "new.py"]
OLD = {"u-opti": b"#!/bin/bash\necho OLD\n",
       "common.sh": b"# shared old\n",
       "VERSION": b"0.16.7\n",
       "alpha.sh": b"echo prior alpha\n"}
NEW = {"u-opti": (
        b'#!/bin/bash\n'
        b'if [ -e "$LIB_PATH/.uopti-update-pending" ]; then\n'
        b'    python3 -B "$RECOVERY_SCRIPT" recover\n'
        b'    exec "$INSTALL_PATH" "$@"\n'
        b'fi\n'
        b'source "$LIB_PATH/common.sh"\n'
        b'echo NEW\n'
       ),
       "common.sh": b"# shared new\n",
       "VERSION": b"0.17.0\n",
       "alpha.sh": b"echo upgraded alpha\n",
       "new.py": b"print('new')\n"}


class DurableUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="uopti-powerloss-lab-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lib = self.root / "lib"
        self.bin = self.root / "bin"
        self.stage = self.root / "stage"
        self.backup = self.lib / ".uopti-backup-ci-01234567"
        self.module_dir = self.lib / "modules"
        for directory in (self.lib, self.bin, self.stage, self.backup,
                          self.module_dir):
            directory.mkdir(mode=0o700)
        self.install = self.bin / "u-opti"
        self.destinations = {"u-opti": self.install, "common.sh": self.lib/"common.sh",
                             "VERSION": self.lib/"VERSION"}
        self.destinations.update({
            name: self.module_dir/name for name in MODULES
        })
        for name, payload in NEW.items():
            file = self.stage / name
            file.write_bytes(payload)
            file.chmod(0o600)
        for name, payload in OLD.items():
            mode = 0o644 if name == "VERSION" else 0o755
            file = self.destinations[name]
            file.write_bytes(payload)
            file.chmod(mode)
            saved = self.backup/name
            saved.write_bytes(payload)
            saved.chmod(0o600)
        (self.backup / ".new.py-was-missing").write_bytes(b"")
        (self.lib / "INSTALL_REF").write_bytes(b"main\n")
        (self.lib / "INSTALL_REF").chmod(0o644)
        (self.backup / "INSTALL_REF").write_bytes(b"main\n")
        (self.backup / "INSTALL_REF").chmod(0o600)


    def _child(self, code: str) -> subprocess.CompletedProcess:
        intro = (
            "import os, importlib.util\nfrom pathlib import Path\n"
            f"spec=importlib.util.spec_from_file_location('real_uopti_recovery', {str(HELPER)!r})\n"
            "m=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(m)\n"
            f"lib=Path({str(self.lib)!r})\n"
            f"install=Path({str(self.install)!r})\n"
            f"stage=Path({str(self.stage)!r})\n"
            f"backup=Path({str(self.backup)!r})\n"
        )
        return subprocess.run(
            [sys.executable, "-B", "-c", intro + code],
            capture_output=True, text=True, timeout=12,
        )

    def _crash_after_two_atomic_live_writes(self):
        result = self._child(
            "original=m._atomic\n"
            "def crash(dest,data,mode):\n"
            "    original(dest,data,mode)\n"
            "    if dest == lib/'common.sh': os._exit(91)\n"
            "m._atomic=crash\n"
            "m.apply(stage,backup,['alpha.sh','new.py'],lib=lib,install=install)\n"
        )
        self.assertEqual(result.returncode, 91, result.stderr)
        self.assertTrue((self.lib / txn.TXN_NAME / "manifest.json").is_file())
        self.assertEqual(self.install.read_bytes(), NEW["u-opti"])
        self.assertEqual(self.destinations["common.sh"].read_bytes(), NEW["common.sh"])
        self.assertEqual(self.destinations["alpha.sh"].read_bytes(), OLD["alpha.sh"])

    def test_ref_commits_with_version_without_post_commit_write(self):
        result = txn.apply(self.stage, self.backup, MODULES,
                           source_ref="feature/rc-closeout",
                           lib=self.lib, install=self.install)
        self.assertEqual(result, "VERIFIED_TRANSACTION_COMMIT")
        self.assertEqual((self.lib / "INSTALL_REF").read_bytes(),
                         b"feature/rc-closeout\n")
        self.assertEqual((self.lib / "VERSION").read_bytes(), NEW["VERSION"])
        self.assertEqual(
            stat.S_IMODE((self.lib / "INSTALL_REF").stat().st_mode), 0o644
        )
        self.assertFalse((self.lib / txn.TXN_NAME).exists())

    def test_interrupt_after_metadata_change_recovers_old_ref_and_bytes(self):
        result = self._child(
            "original=m._atomic\n"
            "def crash(dest,data,mode):\n"
            "    original(dest,data,mode)\n"
            "    if dest == lib/'INSTALL_REF': os._exit(93)\n"
            "m._atomic=crash\n"
            "m.apply(stage,backup,['alpha.sh','new.py'],"
            "lib=lib,install=install,source_ref='feature/rc-closeout')\n"
        )
        self.assertEqual(result.returncode, 93, result.stderr)
        self.assertEqual((self.lib / "INSTALL_REF").read_bytes(),
                         b"feature/rc-closeout\n")
        manifest = (self.lib / txn.TXN_NAME / "manifest.json").read_text()
        self.assertIn('"INSTALL_REF"', manifest)
        recovered = self._child("print(m.recover(lib=lib,install=install))\n")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual((self.lib / "INSTALL_REF").read_bytes(), b"main\n")
        for name, expected in OLD.items():
            self.assertEqual(self.destinations[name].read_bytes(), expected)
        self.assertFalse(self.destinations["new.py"].exists())

    def test_untrusted_source_ref_holds_before_journal(self):
        for invalid in ("../main", "a ref", "/main", "main\\nSECOND", ""):
            with self.subTest(ref=repr(invalid)):
                with self.assertRaises(txn.Hold):
                    txn.apply(self.stage, self.backup, MODULES,
                              source_ref=invalid, lib=self.lib,
                              install=self.install)
                self.assertFalse((self.lib / txn.TXN_NAME).exists())
        self.assertEqual((self.lib / "INSTALL_REF").read_bytes(), b"main\n")

    def test_future_launcher_cannot_drop_preimport_recovery(self):
        # Fail before the durable pending journal is armed.
        (self.stage/"u-opti").write_bytes(b"#!/bin/bash\necho NO_RECOVERY\n")
        with self.assertRaisesRegex(
            txn.Hold, "CANDIDATE_LAUNCHER_LACKS_PREIMPORT_RECOVERY"
        ):
            txn.apply(self.stage, self.backup, MODULES,
                      lib=self.lib, install=self.install)
        self.assertFalse((self.lib/txn.TXN_NAME).exists())
        for name, value in OLD.items():
            self.assertEqual(self.destinations[name].read_bytes(), value)

    def test_full_atomic_commit_and_permissions(self):
        self.assertEqual(
            txn.apply(self.stage, self.backup, MODULES,
                      lib=self.lib, install=self.install),
            "VERIFIED_TRANSACTION_COMMIT",
        )
        for name, value in NEW.items():
            self.assertEqual(self.destinations[name].read_bytes(), value)
            self.assertEqual(
                stat.S_IMODE(self.destinations[name].stat().st_mode),
                0o644 if name == "VERSION" else 0o755,
            )
        self.assertFalse((self.lib/txn.TXN_NAME).exists())
        self.assertFalse((self.lib/txn.DONE_NAME).exists())
        self.assertEqual(txn.recover(lib=self.lib, install=self.install),
                         "NO_PENDING_UPDATE")

    def test_hard_child_exit_recovers_on_separate_interpreter(self):
        self._crash_after_two_atomic_live_writes()
        result = self._child("print(m.recover(lib=lib,install=install))\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ROLLED_BACK_FROM_DURABLE_JOURNAL", result.stdout)
        for name, value in OLD.items():
            self.assertEqual(self.destinations[name].read_bytes(), value)
        self.assertFalse(self.destinations["new.py"].exists())
        self.assertFalse((self.lib/txn.TXN_NAME).exists())
        self.assertTrue(self.backup.exists())  # preserved for operator review

    def test_tampered_backup_holds_without_destroying_journal(self):
        self._crash_after_two_atomic_live_writes()
        (self.backup/"u-opti").write_bytes(b"TAMPERED")
        result = self._child("print(m.recover(lib=lib,install=install))\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.lib/txn.TXN_NAME/"manifest.json").is_file())
        self.assertEqual(self.install.read_bytes(), NEW["u-opti"])
        (self.backup/"u-opti").write_bytes(OLD["u-opti"])
        self.assertEqual(self._child(
            "print(m.recover(lib=lib,install=install))\n").returncode, 0)

    def test_foreign_target_tamper_holds_without_overwrite(self):
        self._crash_after_two_atomic_live_writes()
        self.destinations["alpha.sh"].write_bytes(b"OPERATOR_ADDED_CONTENT")
        result = self._child("print(m.recover(lib=lib,install=install))\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.destinations["alpha.sh"].read_bytes(),
                         b"OPERATOR_ADDED_CONTENT")
        self.assertTrue((self.lib/txn.TXN_NAME).exists())

    def test_crash_during_post_commit_cleanup_never_rolls_back_new_version(self):
        result = self._child(
            "original=m._clear_finished\n"
            "def fail_finished(done):\n"
            "    if done.exists(): os._exit(92)\n"
            "    return original(done)\n"
            "m._clear_finished=fail_finished\n"
            "m.apply(stage,backup,['alpha.sh','new.py'],lib=lib,install=install)\n"
        )
        self.assertEqual(result.returncode, 92, result.stderr)
        self.assertFalse((self.lib/txn.TXN_NAME).exists())
        self.assertTrue((self.lib/txn.DONE_NAME).is_dir())
        self.assertEqual(txn.recover(lib=self.lib, install=self.install),
                         "NO_PENDING_UPDATE")
        for name, payload in NEW.items():
            self.assertEqual(self.destinations[name].read_bytes(), payload)
        # Finished-record cleanup can be retried separately without rollback.
        txn._clear_finished(self.lib/txn.DONE_NAME)
        self.assertFalse((self.lib/txn.DONE_NAME).exists())

    def test_unknown_or_broken_transaction_fails_closed(self):
        bad = self.lib/txn.TXN_NAME
        bad.mkdir(mode=0o700)
        with self.assertRaises(txn.Hold):
            txn.recover(lib=self.lib, install=self.install)
        self.assertTrue(bad.exists())

    def test_host_entrypoint_runs_recovery_before_sourcing_modules(self):
        source = (ROOT/"u-opti").read_text()
        self.assertLess(source.index("python3 -B \"$RECOVERY_SCRIPT\" recover"),
                        source.index('source "$LIB_PATH/common.sh"'))
        self.assertIn('exec "$INSTALL_PATH" "$@"', source)
        self.assertLess(source.index('exec "$INSTALL_PATH" "$@"'),
                        source.index('source "$LIB_PATH/common.sh"'))
        self.assertIn('mktemp -d "$LIB_PATH/.uopti-backup-XXXXXXXX"', source)
        self.assertIn('python3 -B "$TEMP_DIR/u-opti-update-transaction.py" apply',
                      source)
        self.assertIn('"u-opti-update-transaction.py"', (ROOT/"install.sh").read_text())
        self.assertTrue((ROOT/"tests/test-uopti-source-pin.py").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
