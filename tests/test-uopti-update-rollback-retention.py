#!/usr/bin/env python3
"""Offline regression for U-OPTI updater rollback backup retention.

This test extracts the *actual updater failure branch* and executes it
with a stubbed restore outcome against disposable temp directories.
No GitHub downloads, installed paths, services, root, or VPS involved.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "u-opti"
START = (
    '            if [ "$UPDATE_FAILED" = "true" ]; then\n'
    '                echo\n'
    '                echo "Update failed during installation or verification."'
)
END = '            VERSION="$REMOTE_VERSION"'


def actual_rollback_failure_branch() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    begin = source.find(START)
    if begin < 0:
        raise AssertionError("Updater failure path changed: review the regression fixture")
    end = source.find(END, begin)
    if end < 0 or end - begin > 2200:
        raise AssertionError("Updater branch boundary changed: manual audit required")
    snippet = source[begin:end]
    if snippet.count("update_failed_restore") != 1:
        raise AssertionError("Unexpected restore call ordering")
    return snippet


class UpdaterRollbackRetentionTest(unittest.TestCase):
    def exercise(self, *, rollback_return_code: int) -> tuple[Path, Path, str]:
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-updater-rollback-lab-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        backup, stage = root / "backup", root / "download"
        backup.mkdir(mode=0o700)
        stage.mkdir(mode=0o700)
        for name in ("u-opti", "common.sh", "VERSION"):
            (backup / name).write_bytes(b"KNOWN_GOOD_PREVIOUS_INSTALL")
        # This wraps only the updater branch and replaces the real restore
        # helper with a controlled result. Real rm is limited to tmp paths.
        script = (
            'set -u\n'
            'BACKUP_DIR="$TEST_BACKUP_DIR"\n'
            'TEMP_DIR="$TEST_TEMP_DIR"\n'
            'LIB_PATH="$TEST_LIB_DIR"\n'
            'UPDATE_FAILED=true\n'
            'cleanup_update_temp() { rm -rf -- "$TEMP_DIR"; }\n'
            'update_failed_restore() { return "$STUB_RESTORE_RESULT"; }\n'
            'read() { :; }\n'
            'for attempt in once; do\n'
            + actual_rollback_failure_branch()
            + '\ndone\n'
        )
        env = {**os.environ,
               "TEST_BACKUP_DIR": str(backup),
               "TEST_TEMP_DIR": str(stage),
               "TEST_LIB_DIR": str(root),
               "STUB_RESTORE_RESULT": str(rollback_return_code)}
        run = subprocess.run(
            ["bash", "-c", script], env=env,
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertFalse(stage.exists(), "Temporary download files not cleaned")
        return backup, root, run.stdout

    def test_failed_rollback_keeps_last_known_good_backup(self):
        backup, _root, output = self.exercise(rollback_return_code=1)
        self.assertTrue(backup.is_dir(), "Critical: updater deleted the only backup")
        for name in ("u-opti", "common.sh", "VERSION"):
            self.assertEqual((backup / name).read_bytes(),
                             b"KNOWN_GOOD_PREVIOUS_INSTALL")
        self.assertIn("Automatic restore was incomplete", output)
        self.assertIn(str(backup), output)
        self.assertNotIn("Previous installation restored successfully.", output)

    def test_successful_rollback_cleans_backup_only_after_success(self):
        backup, _root, output = self.exercise(rollback_return_code=0)
        self.assertFalse(backup.exists())
        self.assertIn("Previous installation restored successfully.", output)
        self.assertNotIn("Automatic restore was incomplete", output)

    def test_updater_failure_branch_is_real_and_fails_closed(self):
        source = actual_rollback_failure_branch()
        self.assertIn('elif update_failed_restore; then', source)
        self.assertIn('python3 -B "$LIB_PATH/.uopti-update-pending/rescue.py" recover', source)
        self.assertIn('rm -rf -- "$BACKUP_DIR"', source)
        self.assertIn('echo "$BACKUP_DIR"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
