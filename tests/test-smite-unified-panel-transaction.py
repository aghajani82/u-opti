"""No-network disposable Panel transaction and rollback rehearsal tests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
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

    def test_new_signed_identity_blocks_rollback(self):
        self._invoke()
        with sqlite3.connect(self.db) as conn:
            conn.execute("""INSERT INTO smite_node_identities
                VALUES ('foreign-identity','foreign','other-cipher',444,NULL)""")
        with self.assertRaises(trans.Hold):self._undo()
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


if __name__=="__main__":
    unittest.main(verbosity=2)
