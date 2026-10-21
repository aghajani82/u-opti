#!/usr/bin/env python3
"""Regression tests for U-OPTI top-level CLI/version and main-menu exit input."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "u-opti"

FIELD_MENU_FILES = [
    ROOT / "modules/docker.sh",
    ROOT / "modules/docker-3xui.sh",
    ROOT / "modules/smite.sh",
    ROOT / "modules/smite-install.sh",
    ROOT / "modules/smite-frp-wizard.sh",
    ROOT / "modules/smite-backhaul-management.sh",
    ROOT / "modules/smite-tunnel-wizard.sh",
    ROOT / "modules/smite-tunnel-control-center.sh",
    ROOT / "modules/smite-managed-frp-menu.sh",
    ROOT / "modules/smite-managed-backhaul-menu.sh",
    ROOT / "modules/smite-node-pairing-wizard.sh",
    ROOT / "modules/smite-profile-first-menu.sh",
]

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

    def test_field_trial_submenu_numeric_reads_are_normalized(self):
        """Every numeric menu read on the active Field Trial path trims CR/space."""
        for path in FIELD_MENU_FILES:
            lines = path.read_text().splitlines()
            for index, line in enumerate(lines):
                is_menu_read = "read " in line and (
                    "Choose [" in line
                    or "selection [" in line
                    or "backup [" in line
                    or (path.name == "docker-3xui.sh" and line.strip() == "read -r CHOICE")
                )
                if not is_menu_read:
                    continue
                window = "\n".join(lines[index + 1:index + 3])
                self.assertIn(
                    "[![:space:]]",
                    window,
                    f"{path.relative_to(ROOT)}:{index + 1} menu input is not normalized",
                )

if __name__ == "__main__":
    unittest.main(verbosity=2)
