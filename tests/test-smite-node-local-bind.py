#!/usr/bin/env python3
"""Offline tests for persistent Standard Smite Node localhost binding."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "modules/smite-node-local-bind.py"
spec = importlib.util.spec_from_file_location("smite_node_bind", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

COMPOSE = """services:
  smite-node:
    image: alpine:3.21
    container_name: smite-node
    network_mode: host
    environment:
      - NODE_API_PORT=8888
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "print('healthy')"]
volumes:
  node-data:
    driver: local
"""


class SecureNodeBindTests(unittest.TestCase):
    def test_standard_compose_loopback_and_idempotence(self):
        new, changed = module.transform(COMPOSE, "127.0.0.1")
        self.assertTrue(changed)
        self.assertIn("--host 127.0.0.1", new)
        self.assertIn('$${NODE_API_PORT:-8888}', new)
        self.assertNotIn("--host 0.0.0.0", new)
        again, changed = module.transform(new, "127.0.0.1")
        self.assertFalse(changed)
        self.assertEqual(again, new)
        if shutil.which("docker") and subprocess.run(
            ["docker", "compose", "version"], capture_output=True
        ).returncode == 0:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "docker-compose.yml"
                path.write_text(new)
                result = subprocess.run(
                    ["docker", "compose", "-f", str(path), "config", "--format", "json"],
                    capture_output=True, text=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                command = json.loads(result.stdout)["services"]["smite-node"]["command"]
                self.assertEqual(command[:2], ["/bin/sh", "-c"])
                self.assertIn("--host 127.0.0.1", command[2])
                self.assertIn('"${NODE_API_PORT:-8888}"', command[2])

    def test_private_mode_is_not_accidentally_migrated(self):
        for ip in ("", "10.77.10.20"):
            with self.assertRaises(ValueError):
                module.bind_host("private", ip)
        self.assertEqual(module.bind_host("standard", ""), "127.0.0.1")
        with self.assertRaises(ValueError):
            module.bind_host("standard", "10.77.10.20")

    def test_unknown_compose_fails_closed(self):
        with self.assertRaises(ValueError):
            module.transform(COMPOSE.replace("network_mode: host", "network_mode: bridge"), "127.0.0.1")
        with self.assertRaises(ValueError):
            module.transform(COMPOSE.replace("container_name: smite-node", "container_name: other"), "127.0.0.1")
        with self.assertRaises(ValueError):
            module.transform(COMPOSE.replace("    restart:", '    command: ["echo", "bad"]\n    restart:'), "127.0.0.1")

    def test_cli_creates_backup_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "docker-compose.yml"
            path.write_text(COMPOSE)
            args = [sys.executable, "-B", str(HELPER), str(path), "--mode", "standard"]
            first = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            backups = list(Path(folder).glob("docker-compose.yml.bind-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), COMPOSE)
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
            second = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("UNCHANGED", second.stdout)
            self.assertEqual(len(list(Path(folder).glob("*.bak"))), 1)

    def test_fresh_repair_and_update_packaging(self):
        install = (ROOT / "install.sh").read_text()
        update = (ROOT / "u-opti").read_text()
        smite = (ROOT / "modules/smite.sh").read_text()
        node_install = (ROOT / "modules/smite-install.sh").read_text()
        name = "smite-node-local-bind.py"
        self.assertEqual(install.count('    "' + name + '"'), 1)
        self.assertEqual(update.count('                "' + name + '"'), 2)
        self.assertEqual(update.count('["' + name + '"]="$BASE_URL/modules/' + name + '"'), 1)
        self.assertEqual(update.count('["' + name + '"]="$TEMP_DIR/' + name + '"'), 1)
        self.assertIn("smite-node-local-bind.py", smite)
        self.assertIn("smite-node-local-bind.py", node_install)
        self.assertIn('"$connection_mode"; then', node_install)


if __name__ == "__main__":
    unittest.main()
