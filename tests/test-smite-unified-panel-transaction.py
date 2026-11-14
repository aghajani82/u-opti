"""No-network disposable Panel transaction and rollback rehearsal tests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = load("uopti_panel_stage_fixture", ROOT / "tests" / "test-smite-unified-panel-stage.py")
trans = load("uopti_panel_transaction", ROOT / "modules" / "smite-unified-panel-transaction.py")


class OfflineRollout(unittest.TestCase):
    def setUp(self):
        # Use the already-vetted disposable Panel/Replay/Gateway fixture.
        fixture.Prepare.setUp(self)
        self.panel.prepare(fixture.stage.CONFIRM)
        self.executor = trans.PanelTransaction(
            self.root, stager=self.panel, fixture_capability=True)

    def _invoke(self, fail_after=None):
        return self.executor.rehearse(confirm=trans.CONFIRM, fail_after=fail_after)

    def _undo(self):
        return self.executor.rollback_rehearsal(confirm=trans.CONFIRM)

    def _assert_originals(self):
        for name, rel in trans.CONFIG.items():
            self.assertEqual((self.root / rel).read_bytes(),
                             self.panel._read(fixture.stage.STAGE_REL +
                                              "/before-" + name, mode=0o600),
                             "drifted " + name)
        fixture.Prepare.assert_untouched(self)

    def _ledger(self):
        return json.loads((self.executor.rehearsal / "journal.json").read_text())

    def test_review_is_inert_and_bound_to_signed_preimages(self):
        result = self.executor.review()
        self.assertEqual(result["status"], "REVIEWED_PREIMAGES_ONLY")
        self.assertFalse(result["live_activation_allowed"])
        self.assertEqual(result["steps"],
                         ["COMPOSE_IMAGE","ADDITIVE_SCHEMA","PANEL_FLAGS","NGINX_443"])
        self.assertFalse(self.executor.rehearsal.exists())
        self._assert_originals()

    def test_fresh_apply_holds_if_signed_state_changed_after_staging(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO smite_node_inbound_nonces VALUES (?, ?, ?)",
                         ("iran-node-1234", "new-nonce", 400))
        with self.assertRaises(trans.Hold):
            self._invoke()
        self.assertFalse(self.executor.rehearsal.exists())
        self._assert_originals()

    def test_apply_and_rollback_share_the_same_nonblocking_lock(self):
        with self.executor._operation(trans.CONFIRM):
            with self.assertRaises(trans.Hold):
                self._invoke()
            with self.assertRaises(trans.Hold):
                self._undo()
        self.assertFalse(self.executor.rehearsal.exists())
        self.assertEqual(self._invoke()["status"], "REHEARSED_OFFLINE")

    def test_successful_rehearsal_is_offline_and_leaves_stage_untouched(self):
        stagejournal=(self.panel.staging / "journal.json").read_bytes()
        result=self._invoke()
        self.assertEqual(result["status"],"REHEARSED_OFFLINE")
        self.assertFalse(result["production"])
        self.assertFalse(result["runtime_started"])
        self.assertEqual(self._ledger()["phase"],"REHEARSED")
        self.assertEqual((self.panel.staging / "journal.json").read_bytes(),stagejournal)
        for label in trans.CONFIG:
            self.assertEqual((self.root / trans.CONFIG[label]).read_bytes(),
                             self.executor._candidate(label))
        self.assertEqual((self.root / fixture.stage.IR_ID_REL).read_bytes(),
                         self.original[fixture.stage.IR_ID_REL])
        self.assertEqual((self.root / fixture.stage.REPLAY_MARKER_REL).read_bytes(),
                         self.original[fixture.stage.REPLAY_MARKER_REL])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM smite_foreign_install_grants").fetchone()[0],0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM smite_foreign_install_origins").fetchone()[0],0)
            self.assertEqual(
                conn.execute("SELECT encrypted_secret FROM smite_node_identities").fetchone()[0],
                "secret-ciphertext")

    def test_rollback_restores_only_config_and_retains_additive_schema(self):
        self._invoke()
        result=self._undo()
        self.assertEqual(result["status"],"ROLLED_BACK_OFFLINE")
        self.assertEqual(result["schema"],"PRESERVED")
        self.assertEqual(self._ledger()["phase"],"ROLLED_BACK")
        self._assert_originals()
        self.assertEqual(self._undo()["status"],"ALREADY_ROLLED_BACK")
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM smite_foreign_install_grants").fetchone()[0],0)

    def test_interrupted_upgrade_resumes_from_the_original_stage(self):
        with self.assertRaises(trans.Hold):
            self._invoke(fail_after="ENV")
        self.assertEqual(self._ledger()["phase"], "AFTER_ENV")
        with patch.object(self.executor, "_replace", wraps=self.executor._replace) as replace, \
                patch.object(self.executor, "_schema_rehearsal", side_effect=AssertionError):
            self.assertEqual(self._invoke()["status"], "REHEARSED_OFFLINE")
        self.assertEqual([call.args[0] for call in replace.call_args_list], ["nginx-backend"])
        self.assertEqual(self._ledger()["phase"], "REHEARSED")
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT name FROM nodes WHERE id='iran-node-1234'"
            ).fetchone(), ("node-ir",))
            self.assertEqual(conn.execute(
                "SELECT encrypted_secret FROM smite_node_identities"
            ).fetchone(), ("secret-ciphertext",))

    def test_retry_after_config_write_before_checkpoint_skips_the_existing_write(self):
        write = self.executor._journal_write

        def lose_checkpoint(record):
            if record["phase"] == "AFTER_NGINX":
                raise OSError("simulated interruption before checkpoint")
            write(record)

        with patch.object(self.executor, "_journal_write", side_effect=lose_checkpoint):
            with self.assertRaises(OSError):
                self._invoke()
        self.assertEqual(self._ledger()["phase"], "BEFORE_NGINX")
        with patch.object(self.executor, "_replace", side_effect=AssertionError):
            self.assertEqual(self._invoke()["status"], "REHEARSED_OFFLINE")

    def test_retry_does_not_rewrite_drift_in_a_completed_step(self):
        with self.assertRaises(trans.Hold):
            self._invoke(fail_after="ENV")
        path = self.root / trans.CONFIG["panel-compose"]
        path.write_bytes(self.original[trans.CONFIG["panel-compose"]])
        with patch.object(self.executor, "_replace", side_effect=AssertionError):
            with self.assertRaises(trans.Hold):
                self._invoke()
        self.assertEqual(self._ledger()["phase"], "AFTER_ENV")

    def test_step_requires_config_readback_before_checkpoint(self):
        with patch.object(self.executor, "_replace", return_value=None) as replace:
            with self.assertRaises(trans.Hold):
                self._invoke()
        self.assertEqual([call.args[0] for call in replace.call_args_list], ["panel-compose"])
        self.assertEqual(self._ledger()["phase"], "BEFORE_COMPOSE")
        self._assert_originals()
        self.assertEqual(self._invoke()["status"], "REHEARSED_OFFLINE")

    def test_repeated_rollback_refuses_drift_after_the_original_rollback(self):
        self._invoke()
        self._undo()
        path = self.root / trans.CONFIG["panel-compose"]
        candidate = self.executor._candidate("panel-compose")
        path.write_bytes(candidate)
        with self.assertRaises(trans.Hold):
            self._undo()
        self.assertEqual(path.read_bytes(), candidate)
        self.assertEqual(self._ledger()["phase"], "ROLLED_BACK")

    def test_completed_upgrade_rechecks_without_replaying_config_writes(self):
        self._invoke()
        with patch.object(self.executor, "_replace", side_effect=AssertionError):
            self.assertEqual(self._invoke()["status"], "REHEARSED_OFFLINE")
            (self.root / trans.CONFIG["panel-env"]).write_bytes(b"changed")
            with self.assertRaises(trans.Hold):
                self._invoke()
        self.assertEqual(self._ledger()["phase"], "REHEARSED")

    def test_interrupted_after_compose_restores_only_owned_files(self):
        with self.assertRaises(trans.Hold):self._invoke(fail_after="COMPOSE")
        self.assertEqual(self._ledger()["phase"],"AFTER_COMPOSE")
        self._undo()
        self._assert_originals()

    def test_interrupted_after_schema_preserves_new_additive_tables(self):
        with self.assertRaises(trans.Hold):self._invoke(fail_after="SCHEMA")
        self.assertEqual(self._ledger()["phase"],"AFTER_SCHEMA")
        self._undo()
        self._assert_originals()
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM smite_foreign_install_grants").fetchone()[0],0)

    def test_interrupted_schema_missing_unique_blocks_resume_and_rollback(self):
        with self.assertRaises(trans.Hold):
            self._invoke(fail_after="SCHEMA")
        baseline = {name:self.executor._live(name) for name in trans.CONFIG}
        # The exact Smite migration MUST retain the origin/grant binding's
        # UNIQUE constraint; SELECT ... LIMIT 0 alone cannot detect loss.
        with sqlite3.connect(self.db) as db:
            db.execute("DROP TABLE smite_foreign_install_origins")
            db.execute("""CREATE TABLE smite_foreign_install_origins (
                node_id TEXT PRIMARY KEY, node_name TEXT NOT NULL,
                origin TEXT NOT NULL, control_url TEXT NOT NULL,
                grant_hash TEXT NOT NULL, approved_at INTEGER NOT NULL)""")
        with self.assertRaises(trans.Hold):
            self._invoke()
        with self.assertRaises(trans.Hold):
            self._undo()
        self.assertEqual(self._ledger()["phase"], "AFTER_SCHEMA")
        for name, expected in baseline.items():
            self.assertEqual(self.executor._live(name), expected)

    def test_interrupted_schema_extra_index_blocks_resume(self):
        with self.assertRaises(trans.Hold):
            self._invoke(fail_after="SCHEMA")
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE INDEX unreviewed_grant_index "
                       "ON smite_foreign_install_grants(node_id)")
        with self.assertRaises(trans.Hold):
            self._invoke()
        with self.assertRaises(trans.Hold):
            self._undo()
        self.assertEqual(self._ledger()["phase"], "AFTER_SCHEMA")

    def test_unexpected_foreign_grant_trigger_blocks_resume_and_rollback(self):
        with self.assertRaises(trans.Hold):
            self._invoke(fail_after="SCHEMA")
        with sqlite3.connect(self.db) as db:
            db.execute("""CREATE TRIGGER unreviewed_foreign_grant_trigger
                AFTER INSERT ON smite_foreign_install_grants
                BEGIN SELECT RAISE(ABORT, 'unreviewed trigger'); END""")
        with patch.object(self.executor, "_replace",
                          side_effect=AssertionError("unexpected config restore")):
            with self.assertRaises(trans.Hold):
                self._invoke()
            with self.assertRaises(trans.Hold):
                self._undo()
        self.assertEqual(self._ledger()["phase"], "AFTER_SCHEMA")

    def test_interrupted_partial_schema_blocks_resume_before_config_update(self):
        with self.assertRaises(trans.Hold):
            self._invoke(fail_after="SCHEMA")
        with sqlite3.connect(self.db) as db:
            db.execute("DROP TABLE smite_foreign_install_origins")
        with patch.object(self.executor, "_replace",
                          side_effect=AssertionError("unexpected config write")):
            with self.assertRaises(trans.Hold):
                self._invoke()
        self.assertEqual(self._ledger()["phase"], "AFTER_SCHEMA")

    def test_interrupted_after_flags_restores_two_flags_without_key_rotation(self):
        with self.assertRaises(trans.Hold):self._invoke(fail_after="ENV")
        self.assertEqual(self._ledger()["phase"],"AFTER_ENV")
        self._undo()
        self._assert_originals()

    def test_interrupted_after_nginx_restores_exact_trusted_ingress(self):
        with self.assertRaises(trans.Hold):self._invoke(fail_after="NGINX")
        self.assertEqual(self._ledger()["phase"],"AFTER_NGINX")
        self._undo()
        self._assert_originals()

    def test_operator_approval_missing_and_true_root_refused(self):
        with self.assertRaises(trans.Hold):
            self.executor.rehearse(confirm="yes")
        self.assertFalse(self.executor.rehearsal.exists())
        with self.assertRaises(trans.Hold):
            trans.PanelTransaction(self.root, stager=self.panel,
                                   fixture_capability=False).rehearse(confirm=trans.CONFIRM)
        with self.assertRaises(trans.Hold):
            trans.PanelTransaction(Path("/"), fixture_capability=True).rehearse(confirm=trans.CONFIRM)
        self.assertFalse(self.executor.rehearsal.exists())
        self._assert_originals()

    def test_preimage_drift_refuses_any_rehearsal_state(self):
        path=self.root / fixture.stage.COMPOSE_REL
        path.write_bytes(path.read_bytes().replace(
            fixture.stage.OLD_PANEL.encode(),b"unapproved-image"))
        with self.assertRaises(trans.Hold):self._invoke()
        self.assertFalse(self.executor.rehearsal.exists())
        self.assertEqual((self.root / fixture.stage.NGINX_REL).read_bytes(),
                         self.original[fixture.stage.NGINX_REL])

    def test_stage_tampering_fails_review_and_blocks_all_mutations(self):
        p=self.panel.staging / "candidate-panel-env"
        p.write_bytes(p.read_bytes()+b"SMITE_FOREIGN_INSTALL_ENABLED=false\n")
        with self.assertRaises(trans.Hold):self._invoke()
        self.assertFalse(self.executor.rehearsal.exists())
        self._assert_originals()

    def test_new_foreign_grant_blocks_rollback_without_reverting_any_config(self):
        self._invoke()
        with sqlite3.connect(self.db) as conn:
            conn.execute("""INSERT INTO smite_foreign_install_grants
                (code_hash,node_id,node_name,origin,control_url,issued_by,issued_at,expires_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                ("d"*64,"foreign-123456","foreign","https://example.org:443",
                 "https://example.org:443/smite-node/"+"e"*32,"admin",1,7201))
        before=(self.root / trans.CONFIG["panel-env"]).read_bytes()
        with self.assertRaises(trans.Hold):self._undo()
        self.assertEqual((self.root / trans.CONFIG["panel-env"]).read_bytes(),before)
        self.assertEqual(self._ledger()["phase"],"REHEARSED")

    def test_new_pending_pairing_code_blocks_panel_rollback(self):
        self._invoke()
        # Real Panel may issue a signed pairing code BEFORE the Node uses it.
        # No new Node/identity/grant exists yet, but reverting the Panel
        # signing settings would invalidate a live pending handshake.
        original=(self.root / trans.CONFIG["panel-compose"]).read_bytes()
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO smite_node_pairing_codes "
                "(code_hash,node_id,consumed_at) VALUES (?,?,NULL)",
                ("f"*64,"iran-node-1234"))
        with self.assertRaises(trans.Hold):
            self._undo()
        self.assertEqual(
            (self.root / trans.CONFIG["panel-compose"]).read_bytes(),original)
        self.assertEqual(self._ledger()["phase"],"REHEARSED")
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM smite_node_pairing_codes").fetchone()[0],1)

    def test_new_signed_panel_inbound_nonce_blocks_rollback(self):
        self._invoke()
        original=(self.root / trans.CONFIG["panel-env"]).read_bytes()
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO smite_node_inbound_nonces "
                "(node_id,nonce,expires_at) VALUES (?,?,?)",
                ("iran-node-1234","fresh-panel-nonce",2000))
        with self.assertRaises(trans.Hold):
            self._undo()
        self.assertEqual(
            (self.root / trans.CONFIG["panel-env"]).read_bytes(),original)
        self.assertEqual(self._ledger()["phase"],"REHEARSED")
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM smite_node_inbound_nonces").fetchone()[0],2)

    def test_new_signed_identity_blocks_rollback(self):
        self._invoke()
        with sqlite3.connect(self.db) as conn:
            conn.execute("""INSERT INTO smite_node_identities
                VALUES ('foreign-identity','foreign','other-cipher',444,NULL)""")
        with self.assertRaises(trans.Hold):self._undo()
        self.assertEqual(self._ledger()["phase"],"REHEARSED")

    def test_existing_foreign_node_metadata_pairing_change_blocks_rollback(self):
        self._invoke()
        # A new reservation/change of Pairing state can update an
        # EXISTING row without adding an ID or issuing a grant yet.
        # The original id+name-only check missed this and could revert
        # Panel config after another node started signed enrollment.
        before=(self.root / trans.CONFIG["panel-env"]).read_bytes()
        original_row=None
        with sqlite3.connect(self.db) as conn:
            original_row=conn.execute(
                "SELECT id,name,metadata FROM nodes WHERE id='iran-node-1234'"
            ).fetchone()
            self.assertIsNotNone(original_row)
            conn.execute(
                "UPDATE nodes SET metadata=? WHERE id=?",
                ('{"role":"foreign","provisioning":"signed_checkin"}',original_row[0]))
            self.assertEqual(conn.execute(
                "SELECT id,name FROM nodes WHERE id=?",(original_row[0],)
            ).fetchone(),original_row[:2])
        with self.assertRaises(trans.Hold):
            self._undo()
        self.assertEqual(
            (self.root / trans.CONFIG["panel-env"]).read_bytes(),before)
        self.assertEqual(self._ledger()["phase"],"REHEARSED")
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT metadata FROM nodes WHERE id=?",(original_row[0],)
            ).fetchone()[0],
                '{"role":"foreign","provisioning":"signed_checkin"}')

    def test_node_schema_drift_blocks_rollback_without_config_change(self):
        self._invoke()
        before=(self.root / trans.CONFIG["panel-compose"]).read_bytes()
        with sqlite3.connect(self.db) as conn:
            conn.execute("ALTER TABLE nodes ADD COLUMN pairing_status TEXT")
        with self.assertRaises(trans.Hold):
            self._undo()
        self.assertEqual(
            (self.root / trans.CONFIG["panel-compose"]).read_bytes(),before)
        self.assertEqual(self._ledger()["phase"],"REHEARSED")

    def test_new_reserved_foreign_node_blocks_rollback_before_grant_issue(self):
        self._invoke()
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO nodes VALUES ('new-reservation','node-foreign','{}')")
        with self.assertRaises(trans.Hold):self._undo()
        self.assertEqual(self._ledger()["phase"],"REHEARSED")

    def test_wrong_new_grant_schema_blocks_rollback(self):
        self._invoke()
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TABLE smite_foreign_install_grants")
            conn.execute("CREATE TABLE smite_foreign_install_grants (node_id TEXT)")
        with self.assertRaises(trans.Hold):self._undo()
        self.assertEqual(self._ledger()["phase"],"REHEARSED")

    def test_tampered_stage_database_snapshot_blocks_rollback(self):
        self._invoke()
        backup=self.panel.staging/"panel-db.sqlite3"
        with sqlite3.connect(backup) as conn:
            conn.execute("INSERT INTO nodes VALUES ('unexpected','attacker','{}')")
        with self.assertRaises(trans.Hold):self._undo()
        self.assertEqual(self._ledger()["phase"],"REHEARSED")

    def test_advanced_replay_nonce_blocks_rollback_without_rewind(self):
        self._invoke()
        replay=self.root / fixture.stage.REPLAY_DB_REL
        with sqlite3.connect(replay) as conn:
            conn.execute("""INSERT INTO agent_nonces
                VALUES ('iran-node-1234','consumed-later',4444)""")
        with self.assertRaises(trans.Hold):self._undo()
        with sqlite3.connect(replay) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_nonces").fetchone()[0],2)
        self.assertEqual(self._ledger()["phase"],"REHEARSED")

    def test_unknown_live_config_after_interruption_is_not_overwritten(self):
        with self.assertRaises(trans.Hold):self._invoke(fail_after="NGINX")
        path=self.root / trans.CONFIG["nginx-backend"]
        path.write_bytes(b"outside-operator-change")
        with self.assertRaises(trans.Hold):self._undo()
        self.assertEqual(path.read_bytes(),b"outside-operator-change")

    def test_journal_tamper_or_symlink_halts(self):
        with self.assertRaises(trans.Hold):self._invoke(fail_after="COMPOSE")
        p=self.executor.rehearsal / "journal.json"
        original=p.read_bytes()
        p.write_bytes(original[:-2]+b',"source":"0"}')
        with self.assertRaises(trans.Hold):self._undo()
        p.unlink()
        p.symlink_to(self.panel.staging / "journal.json")
        with self.assertRaises(trans.Hold):self._undo()
        self.assertEqual((self.panel.staging / "journal.json").is_file(),True)

    def test_crash_during_rollback_can_be_retried_without_losing_journal(self):
        self._invoke()
        original=self.executor._replace
        calls=[]
        def interrupted(name,content):
            calls.append(name)
            if name=="panel-env":
                raise OSError("fixture simulated power loss")
            original(name,content)
        with patch.object(self.executor,"_replace",side_effect=interrupted):
            with self.assertRaises(OSError):self._undo()
        self.assertEqual(self._ledger()["phase"],"BEFORE_ROLLBACK")
        self.assertEqual(self._undo()["status"],"ROLLED_BACK_OFFLINE")
        self._assert_originals()

    def test_disabled_prod_cli_has_no_apply_or_rollback(self):
        script=(ROOT / "modules" / "smite-unified-panel-transaction.py").read_text()
        self.assertIn("parser.add_argument(\"--review\"",script)
        self.assertNotIn('parser.add_argument("--apply"',script)
        self.assertNotIn('parser.add_argument("--rollback"',script)
        self.assertNotIn("docker compose up",script)
        self.assertNotIn("systemctl restart",script)


class LiveHeartbeatContinuity(unittest.TestCase):
    """Real disposable SQLite; no live host, no Docker or network writes."""

    def setUp(self):
        fixture.Prepare.setUp(self)
        with sqlite3.connect(self.db) as db:
            db.execute("ALTER TABLE nodes ADD COLUMN status TEXT")
            db.execute("ALTER TABLE nodes ADD COLUMN last_seen TEXT")
            db.execute(
                "UPDATE nodes SET metadata=?, status=?, last_seen=?",
                ('{"role":"iran","provisioning":"signed_checkin"}',
                 "active", "2026-11-14 10:00:00"))
        # Both retained snapshots include a live unexpired signed nonce.
        # An attacker or interrupted upgrade must not be allowed to erase
        # either nonce while the original HMAC/replay validity window remains.
        self.unexpired_nonce = int(time.time()) + 3600
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO smite_node_inbound_nonces VALUES (?,?,?)",
                       ("iran-node-1234", "unexpired-inbound",
                        self.unexpired_nonce))
        with sqlite3.connect(self.root/fixture.stage.REPLAY_DB_REL) as db:
            db.execute("INSERT INTO agent_nonces VALUES (?,?,?)",
                       ("iran-node-1234", "unexpired-replay",
                        self.unexpired_nonce))
        self.panel.prepare(fixture.stage.CONFIRM)
        self.executor = trans.PanelTransaction(
            self.root, stager=self.panel, fixture_capability=True)

    def check(self):
        return self.executor._live_continuity()

    def test_signed_iran_heartbeat_and_replay_nonce_changes_admitted(self):
        self.assertEqual(self.check(), "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT")
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE nodes SET last_seen=?, metadata=?",
                       ("2026-11-14 10:01:00",
                        '{"role":"iran","provisioning":"signed_checkin",'
                        '"frp_connected":true,"frp_remote_port":20182}'))
            db.execute("INSERT INTO smite_node_inbound_nonces "
                       "VALUES('iran-node-1234','fresh-hmac',7777)")
            db.execute("DELETE FROM smite_node_inbound_nonces "
                       "WHERE nonce='nonce'")
        with sqlite3.connect(self.root/fixture.stage.REPLAY_DB_REL) as db:
            db.execute("INSERT INTO agent_nonces "
                       "VALUES('iran-node-1234','fresh-replay',8888)")
            db.execute("DELETE FROM agent_nonces WHERE nonce='replay-nonce'")
        self.assertEqual(self.check(), "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT")
        # The original offline fixture rollback deliberately stays stricter.
        self.assertTrue(self.executor._new_enrollment())
        self.assertTrue(self.executor._replay_drift())
        self.assertEqual(self.panel.status()["state"],"PREPARED_ONLY")

    def test_live_inbound_nonce_cannot_be_deleted_before_expiry(self):
        self.assertEqual(self.check(), "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT")
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM smite_node_inbound_nonces WHERE nonce=?",
                       ("unexpired-inbound",))
        with self.assertRaises(trans.Hold):
            self.check()

    def test_nonce_at_exact_expiry_still_blocks_early_deletion(self):
        # Both pinned Smite replay stores prune only when expires_at < now;
        # equality must remain replay-protected.
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM smite_node_inbound_nonces WHERE nonce=?",
                       ("unexpired-inbound",))
        with patch.object(trans.time, "time", return_value=self.unexpired_nonce):
            with self.assertRaises(trans.Hold):
                self.check()

    def test_live_replay_nonce_cannot_be_deleted_before_expiry(self):
        self.assertEqual(self.check(), "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT")
        with sqlite3.connect(self.root/fixture.stage.REPLAY_DB_REL) as db:
            db.execute("DELETE FROM agent_nonces WHERE nonce=?",
                       ("unexpired-replay",))
        with self.assertRaises(trans.Hold):
            self.check()

    def test_expired_inbound_nonce_cleanup_remains_admitted(self):
        # The legacy fixture nonce has already expired; housekeeping may
        # remove it, but must leave the unexpired one untouched.
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM smite_node_inbound_nonces WHERE nonce=?",
                       ("nonce",))
        self.assertEqual(self.check(), "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT")

    def test_expired_replay_nonce_cleanup_remains_admitted(self):
        with sqlite3.connect(self.root/fixture.stage.REPLAY_DB_REL) as db:
            db.execute("DELETE FROM agent_nonces WHERE nonce=?",
                       ("replay-nonce",))
        self.assertEqual(self.check(), "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT")

    def test_pending_pairing_code_is_not_heartbeat(self):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO smite_node_pairing_codes VALUES "
                       "('new-code','iran-node-1234',NULL)")
        with self.assertRaises(trans.Hold): self.check()

    def test_identity_secret_change_blocks(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE smite_node_identities "
                       "SET encrypted_secret='rotated' WHERE node_role='iran'")
        with self.assertRaises(trans.Hold): self.check()

    def test_node_metadata_change_blocks(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE nodes SET metadata=?",
                       ('{"role":"foreign","provisioning":"signed_checkin"}',))
        with self.assertRaises(trans.Hold): self.check()

    def test_node_status_change_is_not_heartbeat(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE nodes SET status='inactive'")
        with self.assertRaises(trans.Hold): self.check()

    def test_new_foreign_reservation_blocks(self):
        with sqlite3.connect(self.db) as db:
            db.execute(
                "INSERT INTO nodes(id,name,metadata,status,last_seen) VALUES"
                "('foreign-new','node-kh','{}','pending',NULL)")
        with self.assertRaises(trans.Hold): self.check()

    def test_new_nonce_for_wrong_node_blocks(self):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO smite_node_inbound_nonces VALUES "
                       "('foreign-new','forged',9000)")
        with self.assertRaises(trans.Hold): self.check()

    def test_changed_nonce_expiry_blocks(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE smite_node_inbound_nonces SET expires_at=9999")
        with self.assertRaises(trans.Hold): self.check()

    def test_replay_identity_drift_blocks(self):
        with sqlite3.connect(self.root/fixture.stage.REPLAY_DB_REL) as db:
            db.execute(
                "UPDATE replay_store_identity SET node_id='another-node'")
        with self.assertRaises(trans.Hold): self.check()

    def test_node_schema_change_blocks(self):
        with sqlite3.connect(self.db) as db:
            db.execute("ALTER TABLE nodes ADD COLUMN unreviewed TEXT")
        with self.assertRaises(trans.Hold): self.check()

    def test_actual_foreign_grant_row_blocks_even_if_signing_identity_unchanged(self):
        with sqlite3.connect(self.db) as db:
            for sql in trans.GRANT_DDL:
                db.execute(sql)
            db.execute(
                "INSERT INTO smite_foreign_install_grants "
                "(code_hash,node_id,node_name,origin,control_url,issued_by,"
                "issued_at,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                ("f"*64, "foreign-node-1234", "node-kh",
                 "https://kh.example.com:443",
                 "https://kh.example.com:443/smite-node/"+"e"*32,
                 "admin", 1850000000, 1850007200))
        with self.assertRaises(trans.Hold): self.check()

    def test_root_read_only_review_requires_baseline_and_live_continuity(self):
        baseline = {
            "IR_INSTALL_CHECKPOINT": "COMPLETE",
            "IR_GATEWAY_TLS443": "PASS",
            "IR_PANEL_LOOPBACK": "PASS",
            "IR_ADMIN": "PRESENT",
            "IR_SIGNED_RUNTIME_AND_REPLAY": "VERIFIED_READ_ONLY",
            "IR_SIGNED_TWO_WAY": "PASS_EXISTING_SIGNED_CONTROL_PROBES",
        }
        # The real root/ service is NEVER accessed. Mock only the root
        # selector, while sealed stage and original config stay disposable.
        with (patch.object(self.executor, "root", Path("/")),
              patch.object(self.executor, "_live",
                           side_effect=self.executor._snapshot),
              patch.object(self.executor, "_tables", return_value=set()),
              patch.object(self.panel, "live_baseline_report",
                           return_value=baseline) as report,
              patch.object(self.executor, "_live_continuity",
                           return_value="HEARTBEAT_ONLY_NO_NEW_ENROLLMENT") as reconcile):
            self.assertEqual(
                self.executor.review()["status"], "REVIEWED_PREIMAGES_ONLY")
            report.assert_called_once_with()
            reconcile.assert_called_once_with()

    def test_root_read_only_review_refuses_missing_signed_control_proof(self):
        baseline = {
            "IR_INSTALL_CHECKPOINT": "COMPLETE",
            "IR_GATEWAY_TLS443": "PASS",
            "IR_PANEL_LOOPBACK": "PASS",
            "IR_ADMIN": "PRESENT",
            "IR_SIGNED_RUNTIME_AND_REPLAY": "VERIFIED_READ_ONLY",
            "IR_SIGNED_TWO_WAY": "NOT_CHECKED",
        }
        # Pinned signatures, a healthy container and HTTPS/443 alone are
        # insufficient to authorize a running Iran Panel migration.
        with (patch.object(self.executor, "root", Path("/")),
              patch.object(self.executor, "_live",
                           side_effect=self.executor._snapshot),
              patch.object(self.executor, "_tables", return_value=set()),
              patch.object(self.panel, "live_baseline_report",
                           return_value=baseline),
              patch.object(self.executor, "_live_continuity") as reconcile):
            with self.assertRaises(trans.Hold):
                self.executor.review()
            reconcile.assert_not_called()

    def test_root_read_only_review_refuses_missing_live_gateway_evidence(self):
        invalid = {
            "IR_INSTALL_CHECKPOINT": "COMPLETE",
            "IR_GATEWAY_TLS443": "HOLD",
            "IR_PANEL_LOOPBACK": "PASS",
            "IR_ADMIN": "PRESENT",
            "IR_SIGNED_RUNTIME_AND_REPLAY": "VERIFIED_READ_ONLY",
        }
        with (patch.object(self.executor, "root", Path("/")),
              patch.object(self.executor, "_live",
                           side_effect=self.executor._snapshot),
              patch.object(self.executor, "_tables", return_value=set()),
              patch.object(self.panel, "live_baseline_report",
                           return_value=invalid),
              patch.object(self.executor, "_live_continuity") as reconcile):
            with self.assertRaises(trans.Hold):
                self.executor.review()
            reconcile.assert_not_called()


if __name__=="__main__":
    unittest.main(verbosity=2)
