#!/usr/bin/env python3
"""Disposable Backhaul-only transaction and recovery: zero live services."""
from __future__ import annotations
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "modules"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pkg = load("bh_package_fixture", ROOT / "smite-managed-backhaul.py")
lab = load("bh_tx_fixture", ROOT / "smite-managed-backhaul-transaction.py")

COMPOSE = """services:
  smite-node:
    image: smite-node:stage15-local
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
"""
ENV = """NODE_ROLE=iran
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
"""


class TransactionLab(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bh-transaction-lab-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        (self.root / "EXPERIMENTAL-LAB").write_text(lab.MARKER)
        self.node = self.root / "node"
        self.node.mkdir(mode=0o700)
        self.config = self.node / "config"
        self.config.mkdir(mode=0o700)
        (self.node / ".env").write_text(ENV)
        self.compose = self.node / "docker-compose.yml"
        self.compose.write_text(COMPOSE)
        self.stages = self.root / "stages"
        self.stages.mkdir(mode=0o700)
        archive = self.root / "official-fixture.tar.gz"
        with tarfile.open(archive, "w:gz") as f:
            binary = b"\x7fELF" + b"BACKHAUL-CI-INERT-FIXTURE"
            m = tarfile.TarInfo("backhaul")
            m.size = len(binary)
            f.addfile(m, io.BytesIO(binary))
        self.digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.archive = archive
        self.patch_env = patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "aghajani82/u-opti",
            "RUNNER_TEMP": str(self.root.parent),
        })
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)

    def prepare(self):
        return pkg.prepare(self.node, self.archive, self.stages,
                           arch="amd64", allowed_sha=self.digest)

    def test_install_and_exact_rollback_do_not_change_other_engines(self):
        state = self.config / "engine-state"
        state.mkdir(mode=0o700)
        original = {"schema": 1, "engines": {"gost": {"sha256": "d" * 64}}}
        manifest = state / "engines.json"
        manifest.write_text(json.dumps(original))
        manifest.chmod(0o600)
        source_bytes = manifest.read_bytes()
        stage = self.prepare()
        self.assertEqual(lab.activate(self.root, stage, fixture=True),
                         "LAB_FILES_APPLIED_NO_DOCKER_NO_LIVE_ENGINE")
        self.assertIn(str(self.root / "installed/backhaul"), self.compose.read_text())
        self.assertIn(":/usr/local/bin/backhaul:ro", self.compose.read_text())
        actual = json.loads(manifest.read_text())["engines"]
        self.assertEqual(actual["gost"], original["engines"]["gost"])
        self.assertIn("backhaul", actual)
        self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.root / "installed/backhaul").stat().st_mode), 0o755)
        with self.assertRaises(lab.Hold):
            lab.activate(self.root, stage, fixture=True)
        self.assertEqual(lab.rollback(self.root), "LAB_EXACT_ROLLBACK_CONFIRMED")
        self.assertEqual(self.compose.read_text(), COMPOSE)
        self.assertEqual(manifest.read_bytes(), source_bytes)
        self.assertFalse((self.root / "installed/backhaul").exists())
        self.assertFalse((self.root / "recovery-journal").exists())
        self.assertEqual(set(json.loads(manifest.read_text())["engines"]), {"gost"})

    def test_fresh_registry_creation_and_removal(self):
        stage = self.prepare()
        self.compose.chmod(0o644)
        lab.activate(self.root, stage, fixture=True)
        self.assertEqual(
            set(json.loads((self.config / "engine-state/engines.json").read_text())["engines"]),
            {"backhaul"},
        )
        lab.rollback(self.root)
        self.assertFalse((self.config / "engine-state/engines.json").exists())
        self.assertEqual(self.compose.read_text(), COMPOSE)
        self.assertEqual(stat.S_IMODE(self.compose.stat().st_mode), 0o644)

    def test_recovery_from_each_partial_install_stage(self):
        for step in ("after-binary", "after-compose", "after-manifest"):
            with self.subTest(step=step):
                stage = self.prepare()
                with self.assertRaises(lab.Hold):
                    lab.activate(self.root, stage, fixture=True, inject=step)
                self.assertTrue((self.root / "recovery-journal").exists())
                self.assertEqual(lab.rollback(self.root), "LAB_EXACT_ROLLBACK_CONFIRMED")
                self.assertEqual(self.compose.read_text(), COMPOSE)
                self.assertFalse((self.root / "installed/backhaul").exists())

    def test_refuse_out_of_band_compose_and_registry_changes(self):
        stage = self.prepare()
        lab.activate(self.root, stage, fixture=True)
        self.compose.write_text(self.compose.read_text() + "# operator edit\n")
        with self.assertRaisesRegex(lab.Hold, "Compose modified"):
            lab.rollback(self.root)
        self.assertTrue((self.root / "recovery-journal").exists())
        self.compose.write_text(COMPOSE + "      - " +
                                str(self.root / "installed/backhaul") +
                                ":/usr/local/bin/backhaul:ro\n")
        manifest = self.config / "engine-state/engines.json"
        manifest.write_text('{"schema":1,"engines":{"backhaul":{"sha256":"f"}}}')
        with self.assertRaisesRegex(lab.Hold, "Registry modified"):
            lab.rollback(self.root)

    def test_refuse_unknown_stage_and_untrusted_node(self):
        stage = self.prepare()
        (self.node / ".env").write_text(ENV.replace("strict", "legacy"))
        with self.assertRaises(lab.Hold):
            lab.activate(self.root, stage, fixture=True)
        self.assertFalse((self.root / "recovery-journal").exists())
        (self.node / ".env").write_text(ENV)
        (self.root / "EXPERIMENTAL-LAB").write_text("not verified\n")
        with self.assertRaises(lab.Hold):
            lab.activate(self.root, stage, fixture=True)

    def test_refuse_non_ci_and_synthetic_fixture_via_public_api(self):
        stage = self.prepare()
        with self.assertRaises(lab.Hold):
            lab.activate(self.root, stage)  # Real launcher never accepts synthetic SHA.
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaisesRegex(lab.Hold, "CI ONLY"):
                lab.activate(self.root, stage, fixture=True)
        self.assertFalse((self.root / "recovery-journal").exists())

    def test_no_shell_docker_or_network_execution_available(self):
        src = (ROOT / "smite-managed-backhaul-transaction.py").read_text()
        for dangerous in ("subprocess", "os.system(", "socket.", "requests.", "httpx.",
                          "docker compose up", "systemctl restart"):
            self.assertNotIn(dangerous, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
