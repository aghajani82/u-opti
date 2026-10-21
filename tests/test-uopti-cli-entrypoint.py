#!/usr/bin/env python3
"""Regression tests for U-OPTI top-level CLI/version and main-menu exit input."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "u-opti"

class UOptiCliEntrypointTests(unittest.TestCase):
    def _sandbox_script(self, folder: Path) -> Path:
        text = SOURCE.read_text()
        lib = folder / "lib"
        modules = lib / "modules"
        modules.mkdir(parents=True)
        (lib / "VERSION").write_text("9.8.7\n")
        text = text.replace('INSTALL_PATH="/usr/local/bin/u-opti"', f'INSTALL_PATH="{folder}/u-opti"')
        text = text.replace('LIB_PATH="/usr/local/lib/u-opti"', f'LIB_PATH="{lib}"')
        text = text.replace('MODULES_PATH="$LIB_PATH/modules"', f'MODULES_PATH="{modules}"')
        script = folder / "u-opti"
        script.write_text(text)
        script.chmod(0o755)
        return script

    def test_version_exits_before_module_loading(self):
        with tempfile.TemporaryDirectory() as td:
            script = self._sandbox_script(Path(td))
            for arg in ("--version", "-V", "version"):
                p = subprocess.run([str(script), arg], text=True, capture_output=True, timeout=5)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout, "9.8.7\n")
                self.assertNotIn("No such file", p.stderr)

    def test_main_menu_exit_is_explicit_and_input_is_normalized(self):
        code = SOURCE.read_text()
        self.assertIn('case "$choice" in', code)
        self.assertIn("        0)\n            exit 0", code)
        self.assertIn("[![:space:]]", code)

if __name__ == "__main__":
    unittest.main(verbosity=2)
