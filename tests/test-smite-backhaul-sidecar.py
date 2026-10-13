#!/usr/bin/env python3
"""Pure offline regression tests for independent Sidecar candidates."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules" / "smite-backhaul-sidecar.py"
loader = importlib.util.spec_from_file_location("sidecar", MODULE)
sidecar = importlib.util.module_from_spec(loader)
assert loader.loader is not None
loader.loader.exec_module(sidecar)


class SidecarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token = Path(self.temp.name) / "token"
        self.secret = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi0123456789"
        self.token.write_text(self.secret + "\n")
        self.token.chmod(0o600)
        self.stages = []

    def stage(self, role: str) -> Path:
        created = sidecar.prepare(role, self.token, "ir.kolbe1.ir", "kh.kolbe1.ir")
        self.stages.append(created)
        self.addCleanup(lambda p=created: __import__("shutil").rmtree(p))
        return created

    def test_isolated_paired_artifacts(self) -> None:
        ir = self.stage("ir")
        kh = self.stage("kh")
        self.assertNotEqual(ir, kh)
        for p in (ir, kh):
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700)
            self.assertTrue(all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in p.iterdir()))
            self.assertIn("NOT INSTALLED", (p / "NOT-INSTALLED.txt").read_text())
        ir_toml = tomllib.loads((ir / "ir.toml").read_text())
        kh_toml = tomllib.loads((kh / "kh.toml").read_text())
        self.assertEqual(ir_toml["server"]["bind_addr"], "127.0.0.1:3080")
        self.assertEqual(ir_toml["server"]["ports"], ["127.0.0.1:56053=127.0.0.1:56053"])
        self.assertEqual(kh_toml["client"]["remote_addr"], "127.0.0.1:13080")
        self.assertEqual(ir_toml["server"]["token"], kh_toml["client"]["token"])
        self.assertEqual(ir_toml["server"]["transport"], "ws")
        self.assertEqual(kh_toml["client"]["transport"], "ws")
        # Never let Sidecar tune host sysctl values under host networking.
        self.assertIs(ir_toml["server"]["skip_optz"], True)
        self.assertIs(kh_toml["client"]["skip_optz"], True)
        self.assertEqual(ir_toml["server"]["web_port"], 0)
        self.assertEqual(kh_toml["client"]["web_port"], 0)
        ir_control = (ir / "ir-control.inc").read_text()
        self.assertIn("location = /channel {", ir_control)
        # v0.7.2's WebSocketDialer appends a random path segment.
        self.assertIn("location ^~ /tunnel/ {", ir_control)
        self.assertNotIn("location = /tunnel {", ir_control)
        self.assertIn("location ^~ /56053/www/", (ir / "ir-xhttp.inc").read_text())
        kh_bridge = (kh / "kh-bridge.conf").read_text()
        self.assertIn("proxy_pass https://ir.kolbe1.ir:443;", kh_bridge)
        self.assertIn("location ^~ /tunnel/ {", kh_bridge)
        self.assertIn("proxy_ssl_verify on;", kh_bridge)
        for stage in (ir, kh):
            compose = (stage / "compose.candidate.yaml").read_text()
            self.assertIn("network_mode: host", compose)
            self.assertIn('restart: "no"', compose)
            self.assertIn("cap_drop: [ALL]", compose)
            self.assertIn("@sha256:", compose)
            self.assertNotIn(self.secret, compose)
            self.assertNotIn("smite-node:", compose)
        # IR has not been given the KH bridge; KH has not been given IR listeners.
        self.assertFalse((kh / "ir-control.inc").exists())
        self.assertFalse((ir / "kh-bridge.conf").exists())

    def test_fail_closed_secret_and_input(self) -> None:
        self.token.chmod(0o644)
        with self.assertRaises(sidecar.UnsafeCandidate):
            self.stage("ir")
        self.token.chmod(0o600)
        bad = Path(self.temp.name) / "linked"
        bad.symlink_to(self.token)
        with self.assertRaises(sidecar.UnsafeCandidate):
            sidecar.read_private_token(bad)
        self.token.write_text("short\n")
        with self.assertRaises(sidecar.UnsafeCandidate):
            self.stage("kh")
        self.token.write_text(self.secret + '\n"bad')
        with self.assertRaises(sidecar.UnsafeCandidate):
            self.stage("kh")
        with self.assertRaises(sidecar.UnsafeCandidate):
            sidecar.candidate_files("kh", self.secret, "evil;include", "kh.kolbe1.ir")
        with self.assertRaises(sidecar.UnsafeCandidate):
            sidecar.candidate_files("none", self.secret, "ir.kolbe1.ir", "kh.kolbe1.ir")

    def test_cli_refuses_to_echo_secret(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MODULE), "--role", "ir",
             "--token-file", str(self.token)],
            capture_output=True, text=True, check=True,
        )
        self.assertNotIn(self.secret, result.stdout + result.stderr)
        self.assertIn("NOT INSTALLED", result.stdout)
        import re
        found = re.search(r"PREPARED PRIVATE OFFLINE CANDIDATE: (.+) \(ir\)", result.stdout)
        self.assertIsNotNone(found)
        stage = Path(found.group(1))
        self.addCleanup(lambda: __import__("shutil").rmtree(stage))
        self.assertTrue(stage.is_dir())

if __name__ == "__main__":
    unittest.main()
