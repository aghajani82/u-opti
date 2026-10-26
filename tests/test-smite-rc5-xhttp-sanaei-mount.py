#!/usr/bin/env python3
"""Offline KH Sanaei read-only mount admission tests."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-rc5-xhttp-sanaei-mount.py"
spec = importlib.util.spec_from_file_location("sanaei_mount_admission", SOURCE)
helper = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(helper)


COMPOSE = f"""services:
  smite-node:
    volumes:
{helper.MOUNT}
    environment:
      - SMITE_SANAEI_INVENTORY_ENABLED=${{SMITE_SANAEI_INVENTORY_ENABLED:-false}}
"""


class SanaeiMountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sanaei-ro-mount-")
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.addCleanup(self.tmp.cleanup)
        instance = self.root / "opt/3x-ui/instances/01/db"
        instance.mkdir(parents=True)
        for path in (self.root / "opt", self.root / "opt/3x-ui",
                     self.root / "opt/3x-ui/instances", self.root / "opt/3x-ui/instances/01",
                     self.root / "opt/3x-ui/instances/01/db"):
            path.chmod(0o755)
        db = instance / "x-ui.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE inbounds (port INTEGER, listen TEXT, protocol TEXT, stream_settings TEXT, enable INTEGER)")
        db.chmod(0o644)
        node = self.root / "opt/smite-node"
        node.mkdir(parents=True)
        (self.root / "opt").chmod(0o755)
        self.compose = node / "docker-compose.yml"
        self.compose.write_text(COMPOSE)
        self.compose.chmod(0o644)
        self.env = node / ".env"
        self.env.write_text("NODE_ROLE=foreign\nSMITE_SANAEI_INVENTORY_ENABLED=false\n")
        self.env.chmod(0o600)
        self.node_env = "/opt/smite-node/.env"
        self.node_compose = "/opt/smite-node/docker-compose.yml"

    def configure(self, **overrides):
        args = dict(
            root=self.root, instance_id="01", node_env=self.node_env,
            node_compose=self.node_compose, confirm_foreign_node=True,
        )
        args.update(overrides)
        helper.configure(**args)

    def test_mount_uses_registered_instance_db_read_only_and_exposes_no_rows(self):
        db = self.root / "opt/3x-ui/instances/01/db/x-ui.db"
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        self.configure()
        env = self.env.read_text()
        self.assertIn("SMITE_SANAEI_DB_HOST_PATH=/opt/3x-ui/instances/01/db", env)
        self.assertIn("SMITE_SANAEI_INVENTORY_ENABLED=true", env)
        self.assertEqual(env.count("SMITE_SANAEI_DB_HOST_PATH="), 1)
        self.assertEqual(env.count("SMITE_SANAEI_INVENTORY_ENABLED="), 1)
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)

    def test_reconfiguration_is_idempotent(self):
        self.configure()
        first = self.env.read_bytes()
        self.configure()
        self.assertEqual(self.env.read_bytes(), first)

    def test_missing_confirmation_invalid_id_or_schema_holds_without_edit(self):
        before = self.env.read_bytes()
        with self.assertRaisesRegex(helper.MountHold, "FOREIGN_NODE_CONFIRMATION_REQUIRED"):
            self.configure(confirm_foreign_node=False)
        with self.assertRaisesRegex(helper.MountHold, "INVALID_SANAEI_INSTANCE_ID"):
            self.configure(instance_id="0A")
        self.assertEqual(self.env.read_bytes(), before)

    def test_symlink_database_unsafe_compose_and_duplicate_env_hold(self):
        db = self.root / "opt/3x-ui/instances/01/db/x-ui.db"
        original = self.root / "opt/3x-ui/instances/01/db/real.db"
        db.rename(original)
        db.symlink_to(original)
        with self.assertRaisesRegex(helper.MountHold, "SANAEI_DATABASE_SYMLINK"):
            self.configure()
        db.unlink()
        original.rename(db)
        self.compose.write_text(COMPOSE.replace(helper.MOUNT, "      - /tmp/wrong:/run/smite-sanaei-ro/x-ui.db:rw"))
        with self.assertRaisesRegex(helper.MountHold, "UNREVIEWED_NODE_COMPOSE_LAYOUT"):
            self.configure()
        self.compose.write_text(COMPOSE)
        self.env.write_text("SMITE_SANAEI_DB_HOST_PATH=/old\nSMITE_SANAEI_DB_HOST_PATH=/duplicate\n")
        self.env.chmod(0o600)
        with self.assertRaisesRegex(helper.MountHold, "DUPLICATE_SANAEI_ENV_KEY"):
            self.configure()

    def test_installer_reuses_existing_clean_rc_flow_and_packages_helper(self):
        installer = (ROOT / "modules/smite-install.sh").read_text()
        package = (ROOT / "install.sh").read_text()
        self.assertIn("smite-rc5-xhttp-sanaei-mount.py", package)
        self.assertIn("smite_install_sanaei_foreign", installer)
        self.assertIn("--confirm-foreign-node", installer)
        self.assertIn("KH_CLIENT_IDENTIFIERS=NOT_READ", installer)


if __name__ == "__main__":
    unittest.main()
