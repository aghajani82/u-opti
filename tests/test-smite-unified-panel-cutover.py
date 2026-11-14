"""Full disposable Iran Panel service cutover and interrupted rollback tests.

The existing RC7 Node/FRP/Sanaei are NEVER manipulated or restarted.
All service callbacks run in memory; production root is hard denied.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


fixture = load("cutover_panel_fixture", ROOT / "tests" /
               "test-smite-unified-panel-stage.py")
cut = load("cutover_panel_runtime", ROOT / "modules" /
           "smite-unified-panel-cutover.py")


class FakePanelOnly:
    def __init__(self):
        self.calls = []
        self.running = "original"
        self.once = None

    def _event(self, name):
        self.calls.append(name)
        if self.once == name:
            self.once = None
            raise OSError("simulated power loss AFTER operation " + name)

    def stop_panel(self):
        self.running = None
        self._event("stop-panel")

    def nginx_check_and_reload(self):
        self._event("nginx-validate-reload")

    def start_panel(self, role):
        if role not in ("candidate", "original"):
            raise AssertionError("Unexpected runtime target")
        self.running = role
        self._event("start-" + role)

    def verify_panel(self, role):
        if self.running != role:
            raise AssertionError("Panel not at expected reviewed image")
        self._event("health-" + role)


class PanelServiceCutover(unittest.TestCase):
    def setUp(self):
        fixture.Prepare.setUp(self)
        with sqlite3.connect(self.db) as conn:
            conn.execute("ALTER TABLE nodes ADD COLUMN status TEXT")
            conn.execute("ALTER TABLE nodes ADD COLUMN last_seen TEXT")
            conn.execute(
                "UPDATE nodes SET metadata=?,status=?,last_seen=?",
                ('{"role":"iran","provisioning":"signed_checkin"}',
                 "active", "2026-11-14T10:00:00Z"))
        self.node = fixture.Prepare._signed_node_runtime(self)
        self.panel = fixture.stage.PanelStage(
            self.root, admission=fixture.admission,
            runtime_reader=lambda: dict(self.node))
        self.panel.prepare(fixture.stage.CONFIRM)
        self.driver = FakePanelOnly()
        self.engine = cut.Cutover(self.root, stage=self.panel,
                                  driver=self.driver, fixture_capability=True)
        self.replay = self.root / fixture.stage.REPLAY_DB_REL
        self.saved_replay = self.replay.read_bytes()
        self.identity = (self.root / fixture.stage.IR_ID_REL).read_bytes()

    def _journal(self):
        return json.loads((self.engine.folder / "journal.json").read_text())

    def _apply(self, fail_after=None):
        return self.engine.apply(confirm=cut.CONFIRM, fail_after=fail_after)

    def _rollback(self, fail_after=None):
        return self.engine.rollback(confirm=cut.CONFIRM, fail_after=fail_after)

    def _untouched(self):
        self.assertEqual(self.replay.read_bytes(), self.saved_replay)
        self.assertEqual((self.root / fixture.stage.IR_ID_REL).read_bytes(),
                         self.identity)
        self.assertEqual(
            self.panel._check_retained_runtime(),
            "RETAINED_IRAN_NODE_CONTAINER_UNCHANGED")

    def _config(self, candidate):
        for name in self.engine.tx_mod.CONFIG:
            self.assertEqual(
                self.engine.tx._live(name),
                (self.engine.tx._candidate(name) if candidate
                 else self.engine.tx._snapshot(name)), name)

    def test_full_cutover_uses_only_panel_callbacks_and_retains_signed_node(self):
        report = self._apply()
        self.assertEqual(report["status"], "REHEARSED_WITH_PANEL_SERVICE")
        self.assertFalse(report["production"])
        self.assertFalse(report["node_recreated"])
        self.assertEqual(self._journal()["phase"], "COMMITTED")
        self._config(True)
        self.assertEqual(
            self.driver.calls,
            ["stop-panel", "nginx-validate-reload",
             "start-candidate", "health-candidate"])
        self.assertEqual(
            self.engine.tx._tables(),
            {"smite_foreign_install_grants", "smite_foreign_install_origins"})
        self._untouched()
        self.assertEqual(self._apply()["status"], "ALREADY_REHEARSED")
        self.assertEqual(len(self.driver.calls), 4)

    def test_cutover_and_rollback_keep_additive_schema_and_never_rewind_replay(self):
        self._apply()
        report = self._rollback()
        self.assertEqual(report["status"], "ROLLED_BACK_PANEL_ONLY")
        self.assertFalse(report["production"])
        self.assertFalse(report["database_rewound"])
        self.assertFalse(report["node_recreated"])
        self._config(False)
        self.assertEqual(self.driver.running, "original")
        self.assertEqual(self.driver.calls[-4:],
                         ["stop-panel", "nginx-validate-reload",
                          "start-original", "health-original"])
        self.assertEqual(
            self.engine.tx._tables(),
            {"smite_foreign_install_grants", "smite_foreign_install_origins"})
        self._untouched()
        self.assertEqual(self._rollback()["status"], "ALREADY_ROLLED_BACK")
        with self.assertRaises(cut.Hold):
            self._apply()

    def test_resume_exact_phase_after_each_interrupted_step(self):
        for step in cut.STEPS:
            with self.subTest(step=step):
                self.setUp()
                with self.assertRaises(cut.Hold):
                    self._apply(fail_after=step)
                self.assertEqual(self._journal()["phase"], "AFTER_" + step)
                self._untouched()
                report = self._apply()
                self.assertEqual(report["status"], "REHEARSED_WITH_PANEL_SERVICE")
                self.assertEqual(self._journal()["phase"], "COMMITTED")
                self._config(True)
                self._untouched()

    def test_service_crash_after_start_before_checkpoint_resumes(self):
        self.driver.once = "start-candidate"
        with self.assertRaises(OSError):
            self._apply()
        self.assertEqual(self._journal()["phase"], "BEFORE_START")
        self.assertEqual(self.driver.running, "candidate")
        self._config(True)
        self.assertEqual(self._apply()["status"], "REHEARSED_WITH_PANEL_SERVICE")
        self.assertEqual(self._journal()["phase"], "COMMITTED")
        self._untouched()

    def test_rollback_after_each_interrupted_cutover_stage(self):
        for step in cut.STEPS:
            with self.subTest(step=step):
                self.setUp()
                with self.assertRaises(cut.Hold):
                    self._apply(fail_after=step)
                result = self._rollback()
                self.assertEqual(result["status"], "ROLLED_BACK_PANEL_ONLY")
                self.assertEqual(self.driver.running, "original")
                self._config(False)
                self._untouched()

    def test_retry_rollback_after_atomic_config_restore_before_checkpoint(self):
        self._apply()
        with self.assertRaises(cut.Hold):
            self._rollback(fail_after="nginx-backend")
        self.assertEqual(self._journal()["phase"], "BEFORE_ROLLBACK")
        self.assertEqual(self.engine.tx._live("nginx-backend"),
                         self.engine.tx._snapshot("nginx-backend"))
        self.assertEqual(self._rollback()["status"], "ROLLED_BACK_PANEL_ONLY")
        self.assertEqual(self.driver.running, "original")
        self._config(False)
        self._untouched()

    def test_rollback_service_crash_after_restart_resumes_without_rewinding_db(self):
        self._apply()
        self.driver.once = "start-original"
        with self.assertRaises(OSError):
            self._rollback()
        self.assertEqual(self._journal()["phase"], "BEFORE_ROLLBACK")
        self.assertEqual(self._rollback()["status"], "ROLLED_BACK_PANEL_ONLY")
        self._untouched()
        self._config(False)

    def test_outside_config_change_blocks_apply_and_rollback(self):
        with self.assertRaises(cut.Hold):
            self._apply(fail_after="ENV")
        nginx = self.root / self.engine.tx_mod.CONFIG["nginx-backend"]
        nginx.write_bytes(b"unreviewed external operator change")
        log = self._journal()
        with self.assertRaises(cut.Hold):
            self._apply()
        with self.assertRaises(cut.Hold):
            self._rollback()
        self.assertEqual(log, self._journal())
        self.assertEqual(nginx.read_bytes(), b"unreviewed external operator change")

    def test_node_started_at_drift_blocks_before_mutations(self):
        self.node["started_at"] = "2026-11-14T17:11:12.123456789Z"
        with self.assertRaises((cut.Hold, fixture.stage.StageHold)):
            self._apply()
        self.assertFalse(self.engine.folder.exists())
        self.assertFalse(self.driver.calls)

    def test_node_drift_after_first_step_blocks_resume_and_rollback(self):
        with self.assertRaises(cut.Hold):
            self._apply(fail_after="COMPOSE")
        calls = list(self.driver.calls)
        self.node["container_id"] = "f"*64
        with self.assertRaises((cut.Hold, fixture.stage.StageHold)):
            self._apply()
        with self.assertRaises((cut.Hold, fixture.stage.StageHold)):
            self._rollback()
        self.assertEqual(self.driver.calls, calls)

    def test_pending_new_pairing_code_blocks_all_cutover_resume_or_restore(self):
        with self.assertRaises(cut.Hold):
            self._apply(fail_after="SCHEMA")
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO smite_node_pairing_codes VALUES (?,?,NULL)",
                ("fresh-code", "iran-node-1234"))
        calls = list(self.driver.calls)
        with self.assertRaises(cut.Hold):
            self._apply()
        with self.assertRaises(cut.Hold):
            self._rollback()
        self.assertEqual(self.driver.calls, calls)

    def test_foreign_grant_blocks_restore_without_mutation(self):
        self._apply()
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO smite_foreign_install_grants "
                "(code_hash,node_id,node_name,origin,control_url,"
                "issued_by,issued_at,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                ("a"*64, "foreign-node-1234", "node-kh",
                 "https://kh.example.com:443",
                 "https://kh.example.com:443/smite-node/"+"b"*32,
                 "operator", 1850000000, 1850007200))
        calls = list(self.driver.calls)
        with self.assertRaises(cut.Hold):
            self._rollback()
        self.assertEqual(self.driver.calls, calls)
        self._config(True)

    def test_no_user_callable_production_apply_or_rollback(self):
        program = (ROOT / "modules" /
                   "smite-unified-panel-cutover.py").read_text()
        self.assertNotIn('parser.add_argument("--apply"', program)
        self.assertNotIn('parser.add_argument("--rollback"', program)
        with self.assertRaises(cut.Hold):
            cut.Cutover(Path("/"), fixture_capability=True,
                        stage=self.panel, driver=self.driver)
        with self.assertRaises(cut.Hold):
            cut.Cutover(self.root)
        with self.assertRaises(cut.Hold):
            self.engine.apply(confirm="I-APPROVE-PRODUCTION")

    def test_direct_writer_and_step_reject_production_root(self):
        with patch.object(self.engine, "root", Path("/")):
            with self.assertRaises(cut.Hold):
                self.engine._write({"phase": "BEFORE_COMPOSE"})
        self.assertFalse(self.engine.folder.exists())

    def test_journal_symlink_or_extra_key_blocks_resume(self):
        with self.assertRaises(cut.Hold):
            self._apply(fail_after="COMPOSE")
        ledger = self.engine.folder / "journal.json"
        original = ledger.read_bytes()
        ledger.write_bytes(original.rstrip().removesuffix(b"}") +
                           b',"production":true}\n')
        with self.assertRaises(cut.Hold):
            self._apply()
        ledger.unlink()
        ledger.symlink_to(self.panel.staging / "journal.json")
        with self.assertRaises(cut.Hold):
            self._rollback()

    def test_source_snapshot_and_node_preservation_on_initial_review(self):
        data = self.engine.review()
        self.assertEqual(data["status"], "READ_ONLY_DISPOSABLE_REVIEW")
        self.assertIsNone(data["phase"])
        self.assertFalse(self.engine.folder.exists())
        self._untouched()


if __name__ == "__main__":
    unittest.main(verbosity=2)
