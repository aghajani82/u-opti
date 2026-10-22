#!/usr/bin/env python3
"""Offline compatibility regression: old fixed-file updater omitted new KH guard.

No network, host files, Nginx, Docker or tunnel engines. Mocks only curl.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = (ROOT / "u-opti").read_text()
SOURCE = ROOT / "modules/docker-3xui-xhttp-guard.py"
START = "# BEGIN: KH dynamic XHTTP guard legacy-updater compatibility"
END = "# END: KH dynamic XHTTP guard legacy-updater compatibility"
assert CLI.count(START) == CLI.count(END) == 1
SOURCE_TEXT = CLI.split(START, 1)[1].split(END, 1)[0]
FUNC = SOURCE_TEXT.split("if ! u_opti_ensure_kh_xhttp_guard_bundle; then", 1)[0]


class BootstrapTests(unittest.TestCase):
    def run_shell(self, folder, source):
        script = r"""
set -e
MODULES_PATH="$MODULES_DIR"
BRANCH="ff75584ba5c968df6f936e978c1e654150aa02c7"
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$BRANCH"
stat() {
    if [ "$1" = "-c" ] && [ "$2" = "%u" ]; then printf "0\n"; return 0; fi
    command stat "$@"
}
curl() {
    local dst=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -o) dst="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    [ -n "$dst" ] || return 1
    cp "$MOCK_SOURCE" "$dst"
}
""" + FUNC + """
u_opti_ensure_kh_xhttp_guard_bundle
"""
        return subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                              env={**os.environ, "MODULES_DIR": str(folder),
                                   "MOCK_SOURCE": str(source)}, timeout=20)

    def test_fresh_bootstrap_then_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "modules"
            folder.mkdir()
            for _ in range(2):
                result = self.run_shell(folder, SOURCE)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((folder / SOURCE.name).read_bytes(), SOURCE.read_bytes())

    def test_rejects_tampered_download_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "modules"
            folder.mkdir()
            bad = Path(d) / "tampered.py"
            bad.write_text("print('not the pinned guard')\n")
            result = self.run_shell(folder, bad)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((folder / SOURCE.name).exists())
            (folder / SOURCE.name).write_text("BAD\n")
            result = self.run_shell(folder, SOURCE)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((folder / SOURCE.name).read_text(), "BAD\n")

    def test_refuses_unsafe_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "modules"
            folder.mkdir()
            victim = Path(d) / "victim"
            victim.write_text("safe\n")
            (folder / SOURCE.name).symlink_to(victim)
            result = self.run_shell(folder, SOURCE)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(victim.read_text(), "safe\n")


if __name__ == "__main__":
    unittest.main()
