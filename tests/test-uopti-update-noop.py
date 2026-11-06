#!/usr/bin/env python3
"""Offline tests against the real U-OPTI no-op guard and pinned blob verifier.

No network calls, root privileges, service operations or live installation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "u-opti"
GUARD_START = "            # UPDATE_FILE_NAMES is the one authoritative inventory for download,"
GUARD_END = '            echo "  Downloading changed modules..."'
VERIFIER_START = "            u_opti_verify_source_blob() {"
VERIFIER_END = "            # Fallback only after a raw-download network failure."


def actual_sections() -> tuple[str, str]:
    source = SOURCE.read_text(encoding="utf-8")
    a, b = source.index(GUARD_START), source.index(GUARD_END)
    guard = source[a:b]
    x, y = source.index(VERIFIER_START), source.index(VERIFIER_END)
    verifier = source[x:y]
    assert "ALREADY UP TO DATE" in guard
    assert guard.index("ALREADY UP TO DATE") < source[b:].index("Downloading changed modules...") + len(guard)
    assert 'u_opti_verify_source_blob "u-opti" "$INSTALL_PATH"' in guard
    assert 'u_opti_verify_source_blob "lib/common.sh" "$LIB_PATH/common.sh"' in guard
    assert 'cmp -s "$TEMP_DIR/VERSION" "$LIB_PATH/VERSION"' in guard
    assert '"$LIB_PATH/INSTALL_REF"' in guard
    assert 'cleanup_update_temp' in guard
    assert "Transaction committed" not in guard
    return verifier, guard


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class VerifiedNoopUpdater(unittest.TestCase):
    def exercise(self, scenario: str) -> str:
        verifier, guard = actual_sections()
        with tempfile.TemporaryDirectory(prefix="uopti-noop-offline-") as temp:
            root = Path(temp)
            lib, mods, stage = root / "lib", root / "mods", root / "stage"
            for directory in (lib, mods, stage):
                directory.mkdir(mode=0o700)
            install = root / "u-opti"
            content = {
                "u-opti": b"#!/bin/bash\n# verified launcher\n",
                "lib/common.sh": b"# verified library\n",
                "modules/alpha.sh": b"echo alpha\n",
                "modules/beta.sh": b"echo beta\n",
            }
            destination = {
                "u-opti": install,
                "lib/common.sh": lib / "common.sh",
                "modules/alpha.sh": mods / "alpha.sh",
                "modules/beta.sh": mods / "beta.sh",
            }
            tree = []
            for path, data in content.items():
                destination[path].write_bytes(data)
                tree.append({
                    "path": path, "size": len(data), "sha": git_blob(data),
                    "mode": "100644", "type": "blob",
                })
            (lib / "VERSION").write_bytes(b"0.17.8\n")
            (lib / "INSTALL_REF").write_bytes(b"main\n")
            (stage / "VERSION").write_bytes(b"0.17.8\n")
            manifest = root / "pinned-tree.json"
            manifest.write_text(json.dumps({"truncated": False, "tree": tree}))
            same = "true"

            if scenario == "local_module_modified":
                (mods / "alpha.sh").write_bytes(b"echo tampered\n")
            elif scenario == "local_module_missing":
                (mods / "alpha.sh").unlink()
            elif scenario == "launcher_changed":
                install.write_bytes(b"#!/bin/bash\n# updated upstream launcher needed\n")
            elif scenario == "common_changed":
                (lib / "common.sh").write_bytes(b"# old library\n")
            elif scenario == "version_file_changed":
                (lib / "VERSION").write_bytes(b"0.17.8\n\n")
            elif scenario == "ref_changed":
                (lib / "INSTALL_REF").write_bytes(b"other-branch\n")
            elif scenario == "ref_missing":
                (lib / "INSTALL_REF").unlink()
            elif scenario == "ref_symlink":
                (lib / "INSTALL_REF").unlink()
                (lib / "INSTALL_REF").symlink_to(stage / "VERSION")
            elif scenario == "launcher_symlink":
                install.unlink()
                install.symlink_to(stage / "VERSION")
            elif scenario == "new_version":
                same = "false"
                (stage / "VERSION").write_bytes(b"0.17.9\n")
            elif scenario != "all_match":
                self.fail(f"Unknown test scenario: {scenario}")

            def q(path: Path) -> str:
                return shlex.quote(str(path))

            script = (
                "set -u\n"
                f"TEMP_DIR={q(stage)}\n"
                f"INSTALL_PATH={q(install)}\n"
                f"MODULES_PATH={q(mods)}\n"
                f"LIB_PATH={q(lib)}\n"
                f"UPDATE_TREE_MANIFEST={q(manifest)}\n"
                "BRANCH=main\nVERSION=0.17.8\n"
                f"SAME_VERSION_UPDATE={same}\n"
                "UPDATE_FILE_NAMES=(alpha.sh beta.sh)\n"
                "u_opti_update_progress() { :; }\n"
                "cleanup_update_temp() { :; }\n"
                "read() { :; }\n"
                + verifier
                + "\nfor _round in once; do\n"
                + guard
                + "\n  echo STAGING_REACHED\n"
                + "done\n"
            )
            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_verified_matching_install_skips_download_and_install(self):
        output = self.exercise("all_match")
        self.assertIn("ALREADY UP TO DATE", output)
        self.assertIn("No installation or restart required.", output)
        self.assertIn("Modules checked : 2", output)
        self.assertNotIn("STAGING_REACHED", output)

    def test_any_change_keeps_regular_update_path(self):
        scenarios = (
            "local_module_modified",
            "local_module_missing",
            "launcher_changed",
            "common_changed",
            "version_file_changed",
            "ref_changed",
            "ref_missing",
            "ref_symlink",
            "launcher_symlink",
            "new_version",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                output = self.exercise(scenario)
                self.assertNotIn("ALREADY UP TO DATE", output)
                self.assertIn("STAGING_REACHED", output)

    def test_noop_occurs_before_any_download_or_backup(self):
        source = SOURCE.read_text()
        guard = source.index("ALREADY UP TO DATE")
        # A CHANGED launcher must be fetched early to discover newly added
        # modules; an already matching launcher still reaches the no-op gate
        # without that extra download. The normal staging path remains later.
        self.assertIn(
            'if ! u_opti_verify_source_blob "u-opti" "$INSTALL_PATH"',
            source[:guard],
        )
        self.assertLess(
            guard,
            source.index('if [ ! -f "$TEMP_DIR/u-opti" ]'),
        )
        self.assertLess(guard, source.index('BACKUP_DIR=$(mktemp -d "$LIB_PATH/.uopti-backup-'))
        self.assertLess(guard, source.index('python3 -B "$TEMP_DIR/u-opti-update-transaction.py" apply'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
