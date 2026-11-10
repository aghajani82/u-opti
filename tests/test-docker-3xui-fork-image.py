#!/usr/bin/env python3
"""Offline regression guard for U-OPTI's Sanaei Docker installation source."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SANA = ROOT / "modules" / "docker-3xui.sh"
SMITE = ROOT / "modules" / "smite-install.sh"
FORK_IMAGE = "ghcr.io/aghajani82/3x-ui:main"


class SanaeiForkImageTest(unittest.TestCase):
    def test_fresh_install_uses_fork_image(self):
        content = SANA.read_text()
        actual = re.findall(r'^DOCKER_3XUI_IMAGE="([^"]+)"$', content, re.M)
        self.assertEqual(actual, [FORK_IMAGE])
        self.assertNotIn("ghcr.io/mhsanaei/3x-ui", content.lower())

    def test_compose_and_pull_are_tied_to_the_fork_image(self):
        content = SANA.read_text()
        self.assertIn("    image: $DOCKER_3XUI_IMAGE", content)
        self.assertIn('docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" pull', content)
        self.assertIn('if ! docker compose -f "$DOCKER_3XUI_COMPOSE_FILE" pull; then', content)
        self.assertIn('Error: Failed to pull 3x-UI image.', content)

    def test_smite_foreign_uses_existing_sanaei_installer(self):
        content = SMITE.read_text()
        self.assertIn("smite_install_sanaei_foreign()", content)
        self.assertIn("docker_3xui_install", content)


if __name__ == "__main__":
    unittest.main()
