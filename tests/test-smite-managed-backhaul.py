#!/usr/bin/env python3
"""Phase 1 next milestone: offline independent Backhaul package contract.

All test roots are private temporary directories; no Docker, host services,
external downloads, live manifest, FRP, U-OPTI Stable or Smite Node is changed.
"""
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

SOURCE = Path(__file__).resolve().parents[1] / "modules" / "smite-managed-backhaul.py"
spec = importlib.util.spec_from_file_location("smite_managed_backhaul", SOURCE)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

COMPOSE = """services:
  smite-node:
    image: smite-node:stage15-local
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
"""
ENV = """NODE_ROLE=foreign
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
"""


def archive_for(path: Path, *, name: str = "release/backhaul", content: bytes | None = None,
                symlink: bool = False) -> str:
    data = content if content is not None else b"\x7fELF" + b"\x00" * 32
    with tarfile.open(path, "w:gz") as tf:
        member = tarfile.TarInfo(name)
        if symlink:
            member.type = tarfile.SYMTYPE
            member.linkname = "../../evil"
        else:
            member.size = len(data)
        tf.addfile(member, None if symlink else io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BackhaulPrepare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stage_root = self.root / "private"
        self.stage_root.mkdir(mode=0o700)
        self.node = self.root / "node"
        self.node.mkdir()
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)
        (self.node / "config").mkdir(mode=0o700)
        self.archive = self.root / "backhaul.tar.gz"
        self.trusted_sha = archive_for(self.archive)

    def prepare(self):
        return engine.prepare(
            self.node, self.archive, self.stage_root,
            arch="amd64", allowed_sha=self.trusted_sha,
        )

    def test_offline_prepare_keeps_core_frp_and_registry_untouched(self):
        baseline = {
            name: (self.node / name).read_bytes()
            for name in (".env", "docker-compose.yml")
        }
        stage = self.prepare()
        self.assertTrue(engine.verify(stage, official_only=False))
        self.assertEqual(stat.S_IMODE(stage.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((stage / "backhaul.bin").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((stage / "engines.candidate.json").stat().st_mode), 0o600)
        declared = json.loads((stage / "engines.candidate.json").read_text())
        self.assertEqual(declared["schema"], 1)
        self.assertEqual(set(declared["engines"]), {"backhaul"})
        self.assertEqual(declared["engines"]["backhaul"]["sha256"],
                         hashlib.sha256(b"\x7fELF" + b"\x00" * 32).hexdigest())
        overlay = (stage / "compose.override.candidate.yml").read_text()
        self.assertIn("target: /usr/local/bin/backhaul", overlay)
        self.assertIn("read_only: true", overlay)
        self.assertNotIn("frpc", overlay)
        self.assertNotIn("ports:", overlay)
        self.assertNotIn("7000", overlay)
        self.assertNotIn("3080", overlay)
        self.assertEqual((self.node / ".env").read_bytes(), baseline[".env"])
        self.assertEqual((self.node / "docker-compose.yml").read_bytes(),
                         baseline["docker-compose.yml"])
        self.assertFalse((self.node / "config" / "engine-state").exists())
        self.assertFalse((self.node / "config" / "engine-state" / "engines.json").exists())
        (stage / "backhaul.bin").write_bytes(b"tampered")
        self.assertFalse(engine.verify(stage, official_only=False))

    def test_preserves_other_independently_registered_engines(self):
        state = self.node / "config" / "engine-state"
        state.mkdir(mode=0o700)
        original = {"schema": 1, "engines": {"gost": {"sha256": "c" * 64}}}
        (state / "engines.json").write_text(json.dumps(original))
        (state / "engines.json").chmod(0o600)
        stage = self.prepare()
        proposal = json.loads((stage / "engines.candidate.json").read_text())
        self.assertEqual(proposal["engines"]["gost"]["sha256"], "c" * 64)
        self.assertEqual(json.loads((state / "engines.json").read_text()), original)
        with self.assertRaises(engine.Hold):
            original["engines"]["backhaul"] = {"sha256": "a" * 64}
            (state / "engines.json").write_text(json.dumps(original))
            self.prepare()

    def test_clean_rc_and_private_paths_are_mandatory(self):
        env = self.node / ".env"
        env.write_text(ENV.replace("SMITE_ENGINE_INVENTORY_MODE=managed",
                                   "SMITE_ENGINE_INVENTORY_MODE=legacy"))
        with self.assertRaises(engine.Hold):
            self.prepare()
        env.write_text(ENV)
        self.stage_root.chmod(0o755)
        with self.assertRaises(engine.Hold):
            self.prepare()
        self.stage_root.chmod(0o700)
        bad = self.node / "config" / "engine-state"
        bad.symlink_to(self.root)
        with self.assertRaises(engine.Hold):
            self.prepare()

    def test_unknown_compose_and_symlinks_are_denied(self):
        config = self.node / "docker-compose.yml"
        config.write_text(COMPOSE.replace("network_mode: host", "network_mode: bridge"))
        with self.assertRaises(engine.Hold):
            self.prepare()
        config.write_text(COMPOSE)
        config.unlink()
        config.symlink_to(self.archive)
        with self.assertRaises(engine.Hold):
            self.prepare()

    def test_archive_digest_tamper_traversal_and_link_are_denied(self):
        with self.assertRaises(engine.Hold):
            engine.prepare(self.node, self.archive, self.stage_root, arch="amd64",
                           allowed_sha="0" * 64)
        self.assertEqual(list(self.stage_root.iterdir()), [])
        self.trusted_sha = archive_for(self.archive, name="../../backhaul")
        with self.assertRaises(engine.Hold):
            self.prepare()
        self.trusted_sha = archive_for(self.archive, symlink=True)
        with self.assertRaises(engine.Hold):
            self.prepare()
        self.trusted_sha = archive_for(self.archive, content=b"not-elf")
        with self.assertRaises(engine.Hold):
            self.prepare()
        self.assertEqual(list(self.stage_root.iterdir()), [])

    def test_declared_official_hashes_match_reviewed_release(self):
        self.assertEqual(engine.VERSION, "v0.7.2")
        self.assertEqual(engine.OFFICIAL_TAR_SHA256["amd64"],
                         "57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc")
        self.assertEqual(engine.OFFICIAL_TAR_SHA256["arm64"],
                         "9a424c97ff16fc3f682e8314c418790d2b5bf3136e008edbb6cd402ea00999f6")
        # Preview API exposes no arbitrary --expected-sha256 argument.
        args_source = SOURCE.read_text()
        self.assertNotIn("parser.add_argument(\"--expected-sha256\"", args_source)
        self.assertNotIn("docker compose up", args_source)
        self.assertNotIn("subprocess.run", args_source)


if __name__ == "__main__":
    unittest.main()
