#!/usr/bin/env python3
"""Offline Stage15 FRP real-executor regression with disposable mocked Docker.

Run as root in CI so filesystem ownership, O_NOFOLLOW, 0600, lock and atomic
journal paths use the same checks as host trial. All paths are temporary.
No network, real Docker, actual Node, production or non-test host changes.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-stage15-frp-host-executor.py"
spec = importlib.util.spec_from_file_location("stage15_frp_test_host_executor", SOURCE)
assert spec and spec.loader
host = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = host
spec.loader.exec_module(host)

class FakeDocker:
    def __init__(self, paths):
        self.paths = paths
        self.enabled = False
        self.actions = []
        self.fail_restart = False

    def __call__(self, argv, **kwargs):
        self.actions.append(list(argv))
        if argv[:2] == ["docker", "compose"]:
            if "up" not in argv:
                raise AssertionError("Unexpected Docker Compose operation")
            if self.fail_restart:
                raise host.Hold("FAKE_RESTART_FAILURE")
            self.enabled = str(self.paths.overlay) in argv
            return ""
        if argv == ["docker", "inspect", "smite-node"]:
            files = [str(self.paths.base), str(self.paths.signed)]
            if self.enabled:
                files.append(str(self.paths.overlay))
            mounts = [
                {"Destination": "/etc/smite-node", "RW": True},
                {"Destination": "/run/smite-node-identity", "RW": False},
                {"Destination": "/var/lib/smite-node/auth", "RW": True},
            ]
            if self.enabled:
                for n in ("frpc", "frps"):
                    mounts.append({"Destination": "/usr/local/bin/" + n,
                                   "Source": str(self.paths.binaries / n),
                                   "RW": False})
            obj = {
                "Image": host.control.STAGE15_NODE_ID,
                "Config": {
                    "Image": "smite-node:stage15-local",
                    "Env": ["SMITE_AGENT_AUTH_MODE=strict",
                            "SMITE_NODE_PANEL_AUTH_MODE=signed",
                            "SMITE_ENGINE_INVENTORY_MODE=managed",
                            "PANEL_ADDRESS=02ir.kolbe1.ir:443"],
                    "Cmd": ["uvicorn", "main:app", "--host",
                            "127.0.0.1", "--port", "8888"],
                    "Labels": {
                        "com.docker.compose.project.config_files": ",".join(files)
                    },
                },
                "State": {"Running": True, "Health": {"Status": "healthy"}},
                "HostConfig": {"NetworkMode": "host", "PortBindings": None,
                               "Privileged": False},
                "Mounts": mounts,
            }
            return json.dumps([obj])
        raise AssertionError("Unexpected command: " + " ".join(argv))

class SignedStage15FrpHost(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.geteuid(), 0, "Use sudo -n for root ownership tests")
        self.tmp = tempfile.TemporaryDirectory(prefix="stage15-frp-host-ci-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        node = root / "smite-node"
        node.mkdir(mode=0o700)
        (node / "config").mkdir(mode=0o700)
        state = root / "state" / "smite-stage15-frp-engine"
        (root / "state").mkdir(mode=0o700)
        binaries = root / "opt" / "u-opti" / "engines" / "frp" / "v0.71.0"
        self.p = host.Paths(node=node, binaries=binaries, state=state,
                            identity=root / "identity.json",
                            replay=root / "replay.sqlite3", lock=root / "lock")
        node.joinpath("docker-compose.yml").write_text(
            "services:\n  smite-node:\n    image: smite-node:stage15-local\n"
            "    command: [uvicorn, main:app, --host, 127.0.0.1, --port, '8888']\n"
        )
        node.joinpath("docker-compose.security-candidate.yml").write_text(
            "services:\n  smite-node:\n    environment:\n      - SMITE_AGENT_AUTH_MODE=strict\n"
        )
        node.joinpath("docker-compose.security-candidate.yml").chmod(0o600)
        node.joinpath(".env").write_text(
            "SMITE_AGENT_AUTH_MODE=strict\nSMITE_NODE_PANEL_AUTH_MODE=signed\n"
            "SMITE_ENGINE_INVENTORY_MODE=managed\n"
        )
        node.joinpath(".env").chmod(0o600)
        self.p.identity.write_text('{"node":"synthetic","secret":"NOT_REAL"}')
        self.p.identity.chmod(0o600)
        self.p.replay.write_bytes(b"CI-REPLAY-DB-CONTINUITY")
        self.p.replay.chmod(0o600)
        self.stage = root / "stage"
        self.stage.mkdir(mode=0o700)
        self.pair = {"frpc": b"CI-OFFICIAL-FRPC-071", "frps": b"CI-OFFICIAL-FRPS-071"}
        for name, blob in self.pair.items():
            (self.stage / (name + ".bin")).write_bytes(blob)
        self.manifest = {
            "schema": 1, "engines": {"frp": {
                "sha256": hashlib.sha256(self.pair["frpc"]).hexdigest(),
                "server_sha256": hashlib.sha256(self.pair["frps"]).hexdigest(),
            }},
        }
        (self.stage / "engines.candidate.json").write_text(json.dumps(self.manifest))
        (self.stage / "summary.txt").write_text("FRP_ARCH=amd64\nFRP_VERSION=v0.71.0\n")
        self.fake = FakeDocker(self.p)
        self.signed_events = []
        self.env = patch.dict(os.environ, {host.FLAG: "YES"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.uname = patch.object(host.os, "uname", return_value=types.SimpleNamespace(nodename="kh", machine="x86_64"))
        self.uname.start()
        self.addCleanup(self.uname.stop)
        self.pkg = patch.object(host.package, "verify", return_value=True)
        self.pkg.start()
        self.addCleanup(self.pkg.stop)
        # The independent read-only plan and true Stage15 live preflight are
        # separately tested. The host transaction here uses synthetic results.
        self.pre = patch.object(host, "preflight", side_effect=lambda p, stage, **_:
                                host.protected(p))
        self.pre.start()
        self.addCleanup(self.pre.stop)
        self.parent = patch.object(host, "create_parent", side_effect=self.create_parent_ci)
        self.parent.start()
        self.addCleanup(self.parent.stop)

    @staticmethod
    def create_parent_ci(path, anchor):
        path.mkdir(mode=0o700, parents=True, exist_ok=False)

    def signed(self, expected, *, runner):
        self.signed_events.append(expected)
        self.assertIs(runner, self.fake)
        if getattr(self, "fail_ready", False) and expected == "ready":
            raise host.Hold("FAKE_SIGNED_REPLAY_FAIL")

    def install(self, **kwargs):
        return host.install(self.p, self.stage,
            snapshot_confirm=host.SNAPSHOT,
            role_confirm="INSTALL-STAGE15-FRP-KH",
            runner=self.fake, signed=self.signed, **kwargs)

    def rollback(self, recover=False):
        return host.rollback(self.p,
            role_confirm=("RECOVER" if recover else "ROLLBACK") + "-STAGE15-FRP-KH",
            runner=self.fake, signed=self.signed, allow_incomplete=recover)

    def clean_state(self):
        for path in (self.p.manifest, self.p.overlay,
                     self.p.binaries / "frpc", self.p.binaries / "frps",
                     self.p.journal):
            self.assertFalse(path.exists(), str(path))
        self.assertFalse(self.fake.enabled)
        self.assertEqual(self.p.identity.read_text(),
                         '{"node":"synthetic","secret":"NOT_REAL"}')
        self.assertEqual(self.p.replay.read_bytes(), b"CI-REPLAY-DB-CONTINUITY")

    def test_install_verified_signed_then_rollback(self):
        result = self.install()
        self.assertEqual(result["STAGE15_FRP_HOST_ENROLLMENT"], "PASS_SIGNED_FIELD_TRIAL")
        self.assertTrue(self.p.journal.exists())
        self.assertEqual(self.p.overlay.read_bytes(), host.proposal.OVERLAY.encode())
        self.assertIn(b"create_host_path: false", self.p.overlay.read_bytes())
        self.assertEqual(json.loads(self.p.manifest.read_text()), self.manifest)
        self.assertTrue(self.fake.enabled)
        self.assertEqual(host.verify(self.p, runner=self.fake, signed=self.signed)
                         ["STAGE15_FRP_HOST_VERIFY"], "PASS_SIGNED_REPLAY")
        self.assertEqual(self.rollback()["STAGE15_FRP_HOST_ROLLBACK"],
                         "PASS_SIGNED_PRIOR_RUNTIME")
        self.clean_state()
        self.assertEqual(self.signed_events[-1], "not-installed")
        self.assertTrue(all("up" not in cmd or cmd[-1] == "smite-node"
                            for cmd in self.fake.actions))
        self.assertTrue(all("docker-compose.security-candidate.yml"
                            in " ".join(cmd) for cmd in self.fake.actions if "up" in cmd))

    def test_power_loss_each_phase_can_recover(self):
        for point in ("journal", "frpc", "frps", "overlay", "manifest", "restart"):
            with self.subTest(point=point):
                self.signed_events.clear()
                with self.assertRaises(host.SimulatedCrash):
                    self.install(inject=point)
                self.assertTrue(self.p.journal.exists())
                self.rollback(recover=True)
                self.clean_state()

    def test_failed_post_restart_signed_replay_compensates(self):
        self.fail_ready = True
        # Avoid slow retry delays in test. Real host keeps bounded retries.
        with patch.object(host.time, "sleep", return_value=None):
            with self.assertRaisesRegex(host.Hold, "FRP_ENROLLMENT_ROLLED_BACK"):
                self.install()
        self.clean_state()
        self.assertIn("ready", self.signed_events)
        self.assertEqual(self.signed_events[-1], "not-installed")

    def test_external_signed_identity_or_replay_change_refuses_rollback(self):
        self.install()
        self.p.identity.write_text('{"node":"altered"}')
        with self.assertRaisesRegex(host.Hold, "SIGNED_IDENTITY_REPLAY_OR_COMPOSE_DRIFT"):
            self.rollback()
        self.assertTrue(self.p.journal.exists())
        self.assertTrue(self.p.overlay.exists())

    def test_external_overlay_change_requires_manual_review(self):
        self.install()
        self.p.overlay.write_text("unauthorized")
        with self.assertRaisesRegex(host.Hold, "FRP_HOST_ARTIFACT_EXTERNAL_DRIFT"):
            self.rollback()
        self.assertTrue(self.p.journal.exists())
        self.assertTrue(self.fake.enabled)

    def test_missing_committed_artifact_is_not_treated_as_incomplete_recovery(self):
        self.install()
        self.p.binaries.joinpath("frpc").unlink()
        with self.assertRaisesRegex(host.Hold, "FRP_HOST_ARTIFACT_MISSING"):
            self.rollback()
        self.assertTrue(self.p.journal.exists())
        self.assertTrue(self.fake.enabled)

    def test_journal_from_another_host_cannot_be_rolled_back(self):
        self.install()
        with patch.object(host.os, "uname",
                          return_value=types.SimpleNamespace(nodename="ir", machine="x86_64")):
            with self.assertRaisesRegex(host.Hold, "JOURNAL_HOST_ROLE_MISMATCH"):
                self.rollback()
        self.assertTrue(self.p.journal.exists())
        self.assertTrue(self.fake.enabled)

    def test_replay_inode_replacement_refuses_unsafe_recover(self):
        with self.assertRaises(host.SimulatedCrash):
            self.install(inject="overlay")
        replacement = self.p.replay.with_name("replay-replacement.sqlite3")
        replacement.write_bytes(self.p.replay.read_bytes())
        replacement.chmod(0o600)
        os.replace(replacement, self.p.replay)
        with self.assertRaisesRegex(host.Hold, "SIGNED_IDENTITY_REPLAY_OR_COMPOSE_DRIFT"):
            self.rollback(recover=True)
        self.assertTrue(self.p.journal.exists())

    def test_official_verified_arm_stage_on_amd64_host_is_denied(self):
        (self.stage / "summary.txt").write_text("FRP_ARCH=arm64\nFRP_VERSION=v0.71.0\n")
        with self.assertRaisesRegex(host.Hold, "OFFICIAL_FRP_STAGE_HOST_ARCH_MISMATCH"):
            self.install()
        self.assertFalse(self.p.journal.exists())
        self.assertFalse(self.p.binaries.exists())

    def test_host_cli_gated_and_no_other_host_changes(self):
        cmd = subprocess.run([sys.executable, "-B", str(SOURCE), "install",
                              "--stage", str(self.stage)],
                             capture_output=True, text=True, timeout=12,
                             env={**os.environ, host.FLAG: "NO"})
        self.assertEqual(cmd.returncode, 2)
        self.assertIn("FIELD_TRIAL_ONLY_NOT_A_GENERAL_INSTALLER", cmd.stderr)
        self.assertFalse(self.p.journal.exists())
        source = SOURCE.read_text()
        for forbidden in ("iptables ", "ufw ", "nginx -s",
                          "curl ", "socket.", "ssh ", "--publish"):
            self.assertNotIn(forbidden, source)

if __name__ == "__main__":
    unittest.main(verbosity=2)
