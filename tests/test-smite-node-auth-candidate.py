#!/usr/bin/env python3
"""Offline Node security-candidate tests: NO containers, no live services."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules/smite-node-auth-candidate.py"
spec = importlib.util.spec_from_file_location("smite_auth_stage9", MODULE)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class Stage9Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        state_dir = self.root / "state"
        state_dir.mkdir()
        self.state = state_dir / "state.env"
        self.state.write_text(
            "SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n"
        )
        self.identities = self.root / "identities"
        self.identities.mkdir(mode=0o700)
        self.identity = self.identities / "node-identity.json"
        self.identity.write_text(json.dumps({
            "node_id": "bbbbbbbb-1111-2222-3333-444444444444",
            "node_secret": "a" * 64,
        }))
        self.identity.chmod(0o600)
        self.node_dir = self.root / "node"
        self.node_dir.mkdir()
        self.base = self.node_dir / "docker-compose.yml"
        self.base.write_text(
            "services:\n"
            "  smite-node:\n"
            "    container_name: smite-node\n"
            '    command: ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888", "--log-level", "info", "--access-log"]\n'
            "    network_mode: host\n"
            "    volumes:\n"
            "      - ./config:/etc/smite-node\n"
            "      - node-data:/var/lib/smite-node\n"
            "    env_file:\n"
            "      - .env\n"
        )
        self.candidate = self.node_dir / "docker-compose.security-candidate.yml"
        self.storage_root = self.root / "storage"
        self.storage_root.mkdir(mode=0o700)
        self.replay_dir = self.storage_root / "private" / "replay"
        self.kwargs = {
            "state_path": self.state,
            "identity": self.identity,
            "base_compose": self.base,
            "candidate": self.candidate,
            "replay_dir": self.replay_dir,
        }

    def test_prepare_idempotent_and_replay_persistent_without_touching_base(self):
        baseline = self.base.read_bytes()
        self.assertEqual(tool.prepare(**self.kwargs), "PREPARED")
        self.assertEqual(tool.prepare(**self.kwargs), "UNCHANGED")
        self.assertEqual(baseline, self.base.read_bytes())
        self.assertEqual(stat.S_IMODE(self.candidate.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.replay_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.replay_dir.parent.stat().st_mode), 0o700)
        yaml = self.candidate.read_text()
        self.assertTrue(yaml.startswith(tool.TAG))
        self.assertIn("- SMITE_AGENT_AUTH_MODE=strict", yaml)
        self.assertIn("- SMITE_NODE_PANEL_AUTH_MODE=signed", yaml)
        self.assertNotIn("SMITE_NODE_PANEL_AUTH_MODE: signed", yaml)
        self.assertIn(":ro", yaml)
        self.assertIn("/var/lib/smite-node/auth:rw", yaml)
        self.assertIn("http://127.0.0.1:8888/healthz", yaml)
        self.assertNotIn("http://127.0.0.1:8888/api/agent/status", yaml)
        self.assertNotIn("a" * 64, yaml)
        self.assertNotIn("docker compose up", yaml)
        self.assertEqual(json.loads(self.identity.read_text())["node_secret"], "a" * 64)

    def test_discard_candidate_never_deletes_identity_or_replay_data(self):
        tool.prepare(**self.kwargs)
        replay_file = self.replay_dir / "agent-replay.sqlite3"
        replay_file.write_bytes(b"persist-replay-data")
        self.assertEqual(
            tool.discard(
                candidate=self.candidate, identity=self.identity,
                replay_dir=self.replay_dir,
            ),
            "DISCARDED_CANDIDATE_ONLY",
        )
        self.assertFalse(self.candidate.exists())
        self.assertTrue(self.identity.exists())
        self.assertEqual(replay_file.read_bytes(), b"persist-replay-data")
        self.assertEqual(tool.prepare(**self.kwargs), "PREPARED")

    def test_refuse_edited_existing_candidate(self):
        tool.prepare(**self.kwargs)
        self.candidate.write_text(self.candidate.read_text() + "# unreviewed change\n")
        with self.assertRaises(tool.StageHold):
            tool.prepare(**self.kwargs)
        with self.assertRaises(tool.StageHold):
            tool.discard(
                candidate=self.candidate, identity=self.identity,
                replay_dir=self.replay_dir,
            )

    def test_require_existing_paired_identity_with_safe_permissions(self):
        self.identity.chmod(0o644)
        with self.assertRaises(tool.StageHold):
            tool.prepare(**self.kwargs)
        self.identity.chmod(0o600)
        self.identity.write_text("{}")
        with self.assertRaises(tool.StageHold):
            tool.prepare(**self.kwargs)
        self.identity.write_text(json.dumps({
            "node_id": "node-valid-identity", "node_secret": "a" * 64,
        }))
        self.identities.chmod(0o755)
        with self.assertRaises(tool.StageHold):
            tool.prepare(**self.kwargs)
        self.identities.chmod(0o700)
        self.identity.unlink()
        self.identity.symlink_to(self.state)
        with self.assertRaises(tool.StageHold):
            tool.prepare(**self.kwargs)
        self.assertFalse(self.candidate.exists())

    def test_private_mode_refused_and_compose_bind_must_be_loopback(self):
        self.state.write_text("SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=private\n")
        with self.assertRaises(tool.StageHold):
            tool.prepare(**self.kwargs)
        self.state.write_text("SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n")
        self.base.write_text(self.base.read_text().replace(
            '"127.0.0.1"', '"0.0.0.0"'
        ))
        with self.assertRaises(tool.StageHold):
            tool.prepare(**self.kwargs)
        self.assertFalse(self.candidate.exists())

    def test_candidate_remains_inert_and_live_activation_is_separately_gated(self):
        candidate_src = MODULE.read_text()
        for forbidden in (
            "subprocess.run(", "subprocess.Popen(", "os.system(",
            "docker compose -f", "systemctl restart", "docker restart",
        ):
            self.assertNotIn(forbidden, candidate_src)

        wrapper = (ROOT / "modules/smite-node-pairing-wizard.sh").read_text()
        self.assertIn("--enable-panel-field-trial", wrapper)
        self.assertIn("--activate-ir-node-field-trial", wrapper)
        self.assertIn("--rollback-node-field-trial", wrapper)
        self.assertIn("UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES", wrapper)
        self.assertNotIn("node_secret", wrapper)
        self.assertNotIn("pairing_code", wrapper)

        # Stage9 remains packaged as the reviewed inert Compose generator;
        # the live controller may invoke it only after explicit Field Trial admission.
        for name in ("install.sh", "u-opti"):
            self.assertIn("smite-node-auth-candidate.py", (ROOT / name).read_text())
        controller = (ROOT / "modules/smite-node-pairing.py").read_text()
        self.assertIn('CANDIDATE_HELPER = Path(__file__).with_name("smite-node-auth-candidate.py")', controller)
        self.assertIn("Explicit disposable-host Field Trial pairing approval required", controller)


if __name__ == "__main__":
    unittest.main()
