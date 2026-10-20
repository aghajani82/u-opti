#!/usr/bin/env python3
"""Read-only KH strict replay/bind-mount review with disposable files only."""
from __future__ import annotations

import importlib.util
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules/smite-node-replay-mount-admission.py"
spec = importlib.util.spec_from_file_location("uopti_kh_mount_review", MODULE)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class ReplayMountReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-kh-replay-mount-lab-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.node_dir = root / "node"
        self.node_dir.mkdir(mode=0o700)
        self.state = root / "state.env"
        self.state.write_text("SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n")
        self.ident_dir = root / "identities"
        self.ident_dir.mkdir(mode=0o700)
        self.identity = self.ident_dir / "node-identity.json"
        self.node_id = "bbbbbbbb-1111-2222-3333-444444444444"
        self.secret = "b" * 64
        self.identity.write_text(json.dumps({
            "node_id": self.node_id, "node_secret": self.secret, "version": 1
        }))
        self.identity.chmod(0o600)
        self.replay_parent = root / "security"
        self.replay_parent.mkdir(mode=0o700)
        self.replay = self.replay_parent / "replay"
        self.replay.mkdir(mode=0o700)
        self.db = self.replay / "agent-replay.sqlite3"
        # Match exact reviewed Smite v1 replay schema without external
        # packages or filesystem outside this isolated temporary root.
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE agent_nonces(node_id TEXT NOT NULL, "
                         "nonce TEXT NOT NULL, expires_at INTEGER NOT NULL, "
                         "PRIMARY KEY(node_id,nonce))")
            conn.execute("CREATE TABLE replay_store_identity("
                         "node_id TEXT NOT NULL PRIMARY KEY)")
            conn.execute("INSERT INTO replay_store_identity VALUES (?)", (self.node_id,))
            conn.execute("PRAGMA user_version=1")
        self.db.chmod(0o600)
        self.marker = self.ident_dir / "replay-enrollment.json"
        self.marker.write_text(json.dumps({
            "schema": 1, "node_id": self.node_id,
            "replay_database": tool.CONTAINER_REPLAY,
            "status": "ENROLLMENT_STARTED",
            "key_binding": self.binding(self.secret),
        }))
        self.marker.chmod(0o600)
        self.base = self.node_dir / "docker-compose.yml"
        self.base.write_text(
            "services:\n"
            "  smite-node:\n"
            "    network_mode: host\n"
            '    command: ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888", "--log-level", "info", "--access-log"]\n'
            "    volumes:\n"
            "      - ./config:/etc/smite-node\n"
            "      - node-data:/var/lib/smite-node\n"
        )
        self.candidate = self.node_dir / "docker-compose.security-candidate.yml"
        self.candidate.write_text(tool.candidate_helper.compose_candidate(
            identity=self.identity, replay_dir=self.replay
        ))
        self.candidate.chmod(0o600)
        self.arguments = dict(
            state=self.state, identity=self.identity,
            replay_dir=self.replay, base_compose=self.base,
            candidate=self.candidate,
        )

    def binding(self, secret):
        return hmac.new(
            secret.encode("ascii"),
            b"smite-replay-key-binding-v1:" + self.node_id.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def review(self):
        return tool.preflight(**self.arguments)

    def test_valid_pair_marker_db_and_compose_mounts_review_pass_only(self):
        before = {
            p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
            for p in (self.identity, self.marker, self.db, self.base, self.candidate)
        }
        self.assertEqual(self.review(), "KH_PRIVATE_BIND_MOUNTS_OFFLINE_PREFLIGHT_PASS")
        for p, unchanged in before.items():
            self.assertEqual((p.read_bytes(), stat.S_IMODE(p.stat().st_mode)), unchanged)
        self.assertIn(
            f"{self.ident_dir}:/run/smite-node-identity:ro",
            self.candidate.read_text(),
        )
        self.assertIn(
            f"{self.replay}:/var/lib/smite-node/auth:rw",
            self.candidate.read_text(),
        )

    def test_missing_replay_db_denied_even_with_marker(self):
        self.db.unlink()
        with self.assertRaises(tool.AdmissionHold):
            self.review()
        self.assertTrue(self.marker.exists())
        self.assertFalse(self.db.exists())

    def test_missing_or_modified_marker_and_wrong_identity_denied(self):
        self.marker.unlink()
        with self.assertRaises(tool.AdmissionHold):
            self.review()
        self.marker.write_text(json.dumps({
            "schema": 1, "node_id": "different-node",
            "replay_database": tool.CONTAINER_REPLAY,
            "status": "ENROLLMENT_STARTED",
            "key_binding": self.binding(self.secret),
        }))
        self.marker.chmod(0o600)
        with self.assertRaisesRegex(tool.AdmissionHold, "mismatch"):
            self.review()
        self.marker.write_text(json.dumps({
            "schema": 1, "node_id": self.node_id,
            "replay_database": tool.CONTAINER_REPLAY,
            "status": "ENROLLMENT_STARTED",
            "key_binding": self.binding(self.secret),
        }))
        self.identity.write_text(json.dumps({
            "node_id": "new-identity", "node_secret": self.secret
        }))
        with self.assertRaises(tool.AdmissionHold):
            self.review()


    def test_old_marker_wrong_host_path_and_key_mismatch_hold(self):
        valid = json.loads(self.marker.read_text())
        mutations = [
            {"key_binding": None},
            {"key_binding": ""},
            {"key_binding": "a" * 64},
            {"replay_database": str(self.db)},
            {"replay_database": "/tmp/fake.sqlite3"},
            {"status": "ENROLLMENT_COMPLETE"},
        ]
        for change in mutations:
            with self.subTest(change=change):
                doc = dict(valid)
                if change.get("key_binding", "present") is None:
                    doc.pop("key_binding")
                else:
                    doc.update(change)
                self.marker.write_text(json.dumps(doc))
                with self.assertRaisesRegex(tool.AdmissionHold, "identity/key mismatch"):
                    self.review()
        self.marker.write_text(json.dumps(valid))
        self.assertEqual(self.review(), "KH_PRIVATE_BIND_MOUNTS_OFFLINE_PREFLIGHT_PASS")

    def test_silent_secret_change_with_same_node_id_holds(self):
        old = self.identity.read_bytes()
        self.identity.write_text(json.dumps({
            "node_id": self.node_id, "node_secret": "c" * 64, "version": 1
        }))
        with self.assertRaisesRegex(tool.AdmissionHold, "identity/key mismatch"):
            self.review()
        self.identity.write_bytes(old)
        self.assertEqual(self.review(), "KH_PRIVATE_BIND_MOUNTS_OFFLINE_PREFLIGHT_PASS")

    def test_kh_pass_does_not_claim_panel_restore_admission(self):
        self.assertEqual(self.review(), "KH_PRIVATE_BIND_MOUNTS_OFFLINE_PREFLIGHT_PASS")
        self.assertIn("PANEL_BACKUP_REVOCATION_WITNESS=NOT_VERIFIED", MODULE.read_text())
        self.assertNotIn(self.secret, MODULE.read_text())

    def test_wrong_db_identity_schema_and_tamper_denied(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE replay_store_identity SET node_id='other'")
        with self.assertRaisesRegex(tool.AdmissionHold, "identity mismatch"):
            self.review()
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE replay_store_identity SET node_id=?", (self.node_id,))
            conn.execute("PRAGMA user_version=2")
        with self.assertRaisesRegex(tool.AdmissionHold, "schema"):
            self.review()
        self.db.chmod(0o644)
        with self.assertRaisesRegex(tool.AdmissionHold, "Untrusted private file"):
            self.review()

    def test_offline_quiescence_refuses_wal_journal_or_active_storage(self):
        # Offline inspection must not create SQLite -shm files or treat
        # uncheckpointed WAL contents as a complete nonce history.
        for extension in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=extension):
                sidecar = Path(str(self.db) + extension)
                sidecar.write_bytes(b"unreviewed historical nonce sidecar")
                with self.assertRaisesRegex(tool.AdmissionHold, "journal sidecar"):
                    self.review()
                sidecar.unlink()
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        with self.assertRaisesRegex(tool.AdmissionHold, "rollback-journal"):
            self.review()

    def test_stale_snapshot_quarantine_blocks_kh_admission(self):
        hold = self.ident_dir / "replay-restore-hold.json"
        hold.write_text(json.dumps({
            "schema": 1, "node_id": self.node_id,
            "status": "QUARANTINED", "replay_database": str(self.db)
        }))
        hold.chmod(0o600)
        with self.assertRaisesRegex(tool.AdmissionHold, "quarantined"):
            self.review()
        hold.unlink()
        hold.symlink_to(self.identity)
        with self.assertRaisesRegex(tool.AdmissionHold, "quarantined"):
            self.review()
        hold.unlink()
        self.assertEqual(self.review(), "KH_PRIVATE_BIND_MOUNTS_OFFLINE_PREFLIGHT_PASS")

    def test_source_and_target_mount_drift_refused(self):
        original = self.candidate.read_text()
        for changed in (
            original.replace(":/run/smite-node-identity:ro",
                             ":/run/smite-node-identity:rw"),
            original.replace(":/var/lib/smite-node/auth:rw",
                             ":/var/lib/smite-node/auth:ro"),
            original.replace("SMITE_AGENT_REPLAY_DB=/var/lib/smite-node/auth/agent-replay.sqlite3",
                             "SMITE_AGENT_REPLAY_DB=/tmp/new-store.sqlite3"),
            original + "  extra_service: {}\n",
        ):
            with self.subTest(changed=changed[-60:]):
                self.candidate.write_text(changed)
                with self.assertRaises(tool.AdmissionHold):
                    self.review()
        self.candidate.write_text(original)
        self.assertEqual(self.review(), "KH_PRIVATE_BIND_MOUNTS_OFFLINE_PREFLIGHT_PASS")

    def test_invalid_role_symlink_and_permissions_refused(self):
        self.state.write_text("SMITE_ROLE=iran\nSMITE_CONNECTION_MODE=standard\n")
        with self.assertRaises(tool.AdmissionHold):
            self.review()
        self.state.write_text("SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n")
        self.ident_dir.chmod(0o755)
        with self.assertRaises(tool.AdmissionHold):
            self.review()
        self.ident_dir.chmod(0o700)
        self.candidate.chmod(0o644)
        with self.assertRaises(tool.AdmissionHold):
            self.review()
        self.candidate.chmod(0o600)
        self.marker.unlink()
        self.marker.symlink_to(self.identity)
        with self.assertRaises(tool.AdmissionHold):
            self.review()

    def test_no_docker_writes_or_automatic_bootstrap(self):
        source = MODULE.read_text()
        for forbidden in (
            "docker compose up", "subprocess.run(", "os.system(",
            "initialize_new(", "mkdir(", "systemctl restart", "docker restart",
            "SMITE_AGENT_AUTH_MODE=strict\n    os.environ",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("ACTIVATION_GATE=HOLD", source)
        self.assertIn("DOCKER_COMPOSE_APPLY=NO", source)
        self.assertIn("REPLAY_DB_BOOTSTRAP=NO", source)
        self.assertIn("PERSISTENCE_REBOOT_TEST=NOT_DONE", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
