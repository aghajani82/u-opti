#!/usr/bin/env python3
"""Offline clean-RC Broker Compose admission tests; no Docker/host changes."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-rc5-xhttp-broker-compose.py"
spec = importlib.util.spec_from_file_location("broker_compose_admission_test", SOURCE)
helper = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(helper)


PANEL = """services:
  smite-panel:
    image: panel:test
    volumes:
      - ./panel/data:/app/data
      - ./panel/certs:/app/certs
      - ./.env:/app/config/.env:ro
      - ./docker-compose.yml:/app/config/docker-compose.yml:ro
  nginx:
    image: nginx:test
    volumes:
      - ./nginx:/etc/nginx:ro
"""

NODE = """services:
  smite-node:
    image: node:test
    container_name: smite-node
    user: "0:${SMITE_UOPTI_BROKER_GID:-0}"
    volumes:
      - ./config:/etc/smite-node
      - /run/u-opti/smite:/run/u-opti/smite:ro
"""


NODE_BASE = """services:
  smite-node:
    image: node:test
    container_name: smite-node
    volumes:
      - ./config:/etc/smite-node
"""

class BrokerComposeTests(unittest.TestCase):
    def temp(self, contents: str, *, symlink: bool = False) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "docker-compose.yml"
        if symlink:
            target = Path(directory.name) / "target.yml"
            target.write_text(contents)
            path.symlink_to(target)
        else:
            path.write_text(contents)
            path.chmod(0o600)
        return path

    def test_panel_key_mount_is_read_only_scoped_and_idempotent(self):
        path = self.temp(PANEL)
        helper.prepare_panel(path)
        first = path.read_text()
        self.assertIn(helper.PANEL_MOUNT, first)
        self.assertEqual(first.count("/run/secrets/smite-uopti-xhttp-broker.key"), 1)
        helper.prepare_panel(path)
        self.assertEqual(path.read_text(), first)
        panel_block = first.split("  smite-panel:\n", 1)[1].split("  nginx:\n", 1)[0]
        nginx_block = first.split("  nginx:\n", 1)[1]
        self.assertIn("route-broker.key:/run/secrets", panel_block)
        self.assertNotIn("route-broker.key", nginx_block)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_panel_layout_conflict_and_symlink_hold_without_rewrite(self):
        wrong = self.temp(PANEL.replace(
            "./docker-compose.yml:/app/config/docker-compose.yml:ro",
            "./other.yml:/app/config/docker-compose.yml:ro",
        ))
        before = wrong.read_bytes()
        with self.assertRaisesRegex(helper.ComposeHold, "UNREVIEWED_PANEL_VOLUME_LAYOUT"):
            helper.prepare_panel(wrong)
        self.assertEqual(wrong.read_bytes(), before)
        link = self.temp(PANEL, symlink=True)
        with self.assertRaisesRegex(helper.ComposeHold, "UNTRUSTED_COMPOSE_CANDIDATE"):
            helper.prepare_panel(link)

    def test_node_peer_gid_socket_and_no_key_mount(self):
        path = self.temp(NODE)
        helper.verify_node(path, 39100)
        with self.assertRaisesRegex(helper.ComposeHold, "NODE_BROKER_PEER_MOUNT_UNAVAILABLE"):
            helper.verify_node(self.temp(NODE.replace(helper.NODE_USER, "")), 39100)
        with self.assertRaisesRegex(helper.ComposeHold, "BROKER_KEY_MUST_NOT_BE_MOUNTED_IN_NODE"):
            helper.verify_node(self.temp(NODE + "    # /route-broker.key\n"), 39100)
        for gid in (0, -1, 65536):
            with self.assertRaisesRegex(helper.ComposeHold, "INVALID_BROKER_PEER_GID"):
                helper.verify_node(path, gid)

    def test_node_prepare_adds_and_validates_readonly_broker_peer_mount(self):
        path = self.temp(NODE_BASE)
        before_mode = path.stat().st_mode & 0o777
        helper.prepare_node(path, 39100)
        first = path.read_text()
        self.assertIn(helper.NODE_USER, first)
        self.assertIn(helper.NODE_SOCKET_MOUNT, first)
        helper.verify_node(path, 39100)
        helper.prepare_node(path, 39100)
        self.assertEqual(path.read_text(), first)
        self.assertEqual(path.stat().st_mode & 0o777, before_mode)

    def test_node_prepare_rejects_conflicting_user_without_mutation(self):
        conflicting = NODE_BASE.replace(
            "    container_name: smite-node\n",
            "    container_name: smite-node\n    user: 1000:1000\n",
        )
        path = self.temp(conflicting)
        before = path.read_bytes()
        with self.assertRaisesRegex(helper.ComposeHold, "CONFLICTING_NODE_BROKER_USER"):
            helper.prepare_node(path, 39100)
        self.assertEqual(path.read_bytes(), before)

    def test_node_broker_enablement_changes_only_one_private_env_key(self):
        with tempfile.TemporaryDirectory(prefix="broker-node-env-") as raw:
            path = Path(raw) / ".env"
            path.write_text(
                "NODE_ROLE=iran\nSMITE_UOPTI_ROUTE_BROKER_ENABLED=false\n"
                "SMITE_UOPTI_ROUTE_BROKER_SOCKET=/run/u-opti/smite/xhttp-broker.sock\n"
            )
            path.chmod(0o600)
            helper.set_node_broker_enabled(path, True)
            first = path.read_text()
            self.assertIn("SMITE_UOPTI_ROUTE_BROKER_ENABLED=true\n", first)
            self.assertEqual(first.count("SMITE_UOPTI_ROUTE_BROKER_ENABLED="), 1)
            self.assertIn("SMITE_UOPTI_ROUTE_BROKER_SOCKET=/run/u-opti/smite/xhttp-broker.sock", first)
            helper.set_node_broker_enabled(path, True)
            self.assertEqual(path.read_text(), first)
            helper.set_node_broker_enabled(path, False)
            self.assertIn("SMITE_UOPTI_ROUTE_BROKER_ENABLED=false\n", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_node_broker_enablement_rejects_missing_duplicate_and_unsafe_env(self):
        for contents, expected in (
            ("NODE_ROLE=iran\n", "NODE_BROKER_FLAG_MISSING_OR_DUPLICATE"),
            ("SMITE_UOPTI_ROUTE_BROKER_ENABLED=false\nSMITE_UOPTI_ROUTE_BROKER_ENABLED=false\n",
             "NODE_BROKER_FLAG_MISSING_OR_DUPLICATE"),
            ("SMITE_UOPTI_ROUTE_BROKER_ENABLED=yes\n", "INVALID_NODE_BROKER_STATE"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / ".env"
                path.write_text(contents)
                path.chmod(0o600)
                before = path.read_bytes()
                with self.assertRaisesRegex(helper.ComposeHold, expected):
                    helper.set_node_broker_enabled(path, True)
                self.assertEqual(path.read_bytes(), before)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"
            path.write_text("SMITE_UOPTI_ROUTE_BROKER_ENABLED=false\n")
            path.chmod(0o644)
            with self.assertRaisesRegex(helper.ComposeHold, "UNTRUSTED_NODE_ENV"):
                helper.set_node_broker_enabled(path, True)

    def test_installer_starts_inert_broker_then_attests_node_socket(self):
        installer = (ROOT / "modules/smite-install.sh").read_text()
        package = (ROOT / "install.sh").read_text()
        self.assertIn('"smite-rc5-xhttp-broker-compose.py"', package)
        self.assertIn("smite_install_clean_rc_broker_prepare", installer)
        self.assertIn("smite_install_clean_rc_broker_panel_mount", installer)
        self.assertIn("SMITE_UOPTI_ROUTE_BROKER_ENABLED=false", installer)
        self.assertIn('node-prepare "$SMITE_NODE_COMPOSE"', installer)
        self.assertIn("smite_install_clean_rc_broker_start_node_forwarding", installer)
        self.assertIn("--activate-existing --confirm-local-root", installer)
        self.assertIn("BROKER_TRUSTED_GRANTS=NONE_ROUTE_APPLY_HOLD", installer)
        self.assertIn("NODE_BROKER_FORWARDING=PASS_SOCKET_PEER_ATTESTED", installer)


if __name__ == "__main__":
    unittest.main()
