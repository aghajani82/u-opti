#!/usr/bin/env python3
"""Independent managed FRP candidate tests: no download, network or Docker."""
from __future__ import annotations
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE / "modules/smite-managed-frp.py"
spec = importlib.util.spec_from_file_location("uopti_managed_frp_test", SOURCE)
frp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frp)

ENV = (
    "NODE_ROLE=foreign\nSMITE_AGENT_AUTH_MODE=strict\n"
    "SMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_ENGINE_INVENTORY_MODE=managed\n"
)
COMPOSE = (
    "services:\n  smite-node:\n    image: smite-node:reviewed\n"
    "    network_mode: host\n    volumes:\n"
    "      - ./config:/etc/smite-node\n"
)


def elf(arch: str):
    binary = bytearray(128)
    binary[:4] = b"\x7fELF"
    binary[4:6] = bytes([2, 1])
    struct.pack_into("<H", binary, 18, frp.ELF_MACHINE[arch])
    binary[40:44] = b"test"
    return bytes(binary)


class OfflineFrp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="uopti-frp-offline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.node = self.root / "node"
        self.node.mkdir(mode=0o700)
        (self.node / "config").mkdir(mode=0o700)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)
        self.stages = self.root / "stages"
        self.stages.mkdir(mode=0o700)
        self.archive = self.root / "frp.tar.gz"

    def archive_with(self, *, arch="amd64", bad=None, missing=None):
        folder = f"frp_0.71.0_linux_{arch}"
        parts = {
            "frpc": elf(arch),
            "frps": elf(arch) + b"server",
            "frpc.toml": b"serverAddr = 'localhost'\n",
        }
        if missing:
            parts.pop(missing)
        if bad == "badelf":
            parts["frps"] = b"not-executable"
        with tarfile.open(self.archive, "w:gz") as tar:
            for name, data in parts.items():
                entry = tarfile.TarInfo(folder + "/" + name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
            if bad == "traversal":
                entry = tarfile.TarInfo("../../secret")
                entry.size = 3
                tar.addfile(entry, io.BytesIO(b"bad"))
            if bad == "duplicate":
                data = elf(arch)
                entry = tarfile.TarInfo(folder + "/frpc")
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
            if bad == "symlink":
                entry = tarfile.TarInfo(folder + "/link")
                entry.type = tarfile.SYMTYPE
                entry.linkname = "../outside"
                tar.addfile(entry)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def stage(self, *, arch="amd64"):
        digest = self.archive_with(arch=arch)
        return frp.prepare(self.node, self.archive, self.stages,
                           arch=arch, allowed_sha=digest)

    def test_frp_only_stages_both_pins_without_backhaul(self):
        stage = self.stage()
        self.assertTrue(frp.verify(stage, official_only=False))
        self.assertFalse(frp.verify(stage))  # Only fake checksum for unit tests
        manifest = json.loads((stage / "engines.candidate.json").read_text())
        self.assertEqual(set(manifest["engines"]), {"frp"})
        entry = manifest["engines"]["frp"]
        self.assertEqual(entry["sha256"], hashlib.sha256((stage / "frpc.bin").read_bytes()).hexdigest())
        self.assertEqual(entry["server_sha256"], hashlib.sha256((stage / "frps.bin").read_bytes()).hexdigest())
        overlay = (stage / "compose.override.candidate.yml").read_text()
        self.assertEqual(overlay.count("        read_only: true"), 2)
        self.assertIn("/usr/local/bin/frpc", overlay)
        self.assertIn("/usr/local/bin/frps", overlay)
        self.assertNotIn("backhaul", overlay)
        summary = (stage / "summary.txt").read_text()
        self.assertIn("BACKHAUL_INSTALL_REQUIRED=NO", summary)
        self.assertIn("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED", summary)
        self.assertEqual((self.node / "docker-compose.yml").read_text(), COMPOSE)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_preserves_existing_backhaul_enrollment(self):
        state = self.node / "config/engine-state"
        state.mkdir(mode=0o700)
        manifest = state / "engines.json"
        original = {"schema": 1, "engines": {"backhaul": {"sha256": "a" * 64}}}
        manifest.write_text(json.dumps(original))
        manifest.chmod(0o600)
        (self.node / "docker-compose.yml").write_text(
            COMPOSE + "      - /opt/u-opti/engines/backhaul/v0.7.2/backhaul:/usr/local/bin/backhaul:ro\n"
        )
        stage = self.stage()
        compiled = json.loads((stage / "engines.candidate.json").read_text())
        self.assertEqual(compiled["engines"]["backhaul"], original["engines"]["backhaul"])
        self.assertEqual(json.loads(manifest.read_text()), original)
        self.assertFalse(frp.verify(stage))  # Untrusted fixture SHA

    def test_absent_frps_traversal_duplicate_symlink_or_wrong_arch_denied(self):
        for bad, missing in ((None, "frps"), ("traversal", None),
                             ("duplicate", None), ("symlink", None),
                             ("badelf", None)):
            with self.subTest(bad=bad, missing=missing):
                digest = self.archive_with(bad=bad, missing=missing)
                with self.assertRaises(frp.Hold):
                    frp.prepare(self.node, self.archive, self.stages,
                                arch="amd64", allowed_sha=digest)
        digest = self.archive_with(arch="arm64")
        with self.assertRaises(frp.Hold):
            frp.prepare(self.node, self.archive, self.stages,
                        arch="amd64", allowed_sha=digest)

    def test_tampered_archive_and_staged_outputs_are_denied(self):
        digest = self.archive_with()
        with self.assertRaises(frp.Hold):
            frp.prepare(self.node, self.archive, self.stages,
                        arch="amd64", allowed_sha="0" * 64)
        stage = frp.prepare(self.node, self.archive, self.stages,
                            arch="amd64", allowed_sha=digest)
        (stage / "frps.bin").write_bytes(b"tampered")
        self.assertFalse(frp.verify(stage, official_only=False))

    def test_duplicate_env_and_existing_frp_mount_hold(self):
        (self.node / ".env").write_text(ENV + "SMITE_AGENT_AUTH_MODE=legacy\n")
        digest = self.archive_with()
        with self.assertRaises(frp.Hold):
            frp.prepare(self.node, self.archive, self.stages,
                        arch="amd64", allowed_sha=digest)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(
            COMPOSE + "      - /usr/bin/frpc:/usr/local/bin/frpc:ro\n")
        with self.assertRaises(frp.Hold):
            frp.prepare(self.node, self.archive, self.stages,
                        arch="amd64", allowed_sha=digest)

    def test_unrecognized_manifest_and_already_enrolled_frp_hold(self):
        state = self.node / "config/engine-state"
        state.mkdir(mode=0o700)
        manifest = state / "engines.json"
        manifest.write_text(json.dumps({"schema": 1, "engines": {
            "frp": {"sha256": "a" * 64, "server_sha256": "b" * 64}
        }}))
        manifest.chmod(0o600)
        digest = self.archive_with()
        with self.assertRaises(frp.Hold):
            frp.prepare(self.node, self.archive, self.stages,
                        arch="amd64", allowed_sha=digest)
        manifest.write_text(json.dumps({"schema": 1, "engines": {
            "frp": {"sha256": "a" * 64, "extra": "x"}
        }}))
        with self.assertRaises(frp.shared.Hold):
            frp.prepare(self.node, self.archive, self.stages,
                        arch="amd64", allowed_sha=digest)

    def test_cli_never_promotes_synthetic_frp_or_starts_service(self):
        stage = self.stage()
        p = subprocess.run(
            [sys.executable, "-B", str(SOURCE), "verify", "--stage", str(stage)],
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(p.returncode, 2)
        self.assertIn("HOLD", p.stdout)
        body = SOURCE.read_text()
        for disallowed in ("docker compose up", "docker restart", "systemctl ",
                           "subprocess.run", "ssh ", "nginx -s", "iptables "):
            self.assertNotIn(disallowed, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
