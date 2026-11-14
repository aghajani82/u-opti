"""Disposable, no-host-write tests for signed Iran Panel staged transaction."""
import importlib.util
import json
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("unified_panel_stager",ROOT/"modules"/"smite-unified-panel-stage.py")
stage=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=stage
spec.loader.exec_module(stage)

MASTER="a"*43+"="
TOKEN="b"*64
NODE="c"*64

def nginx(domain="panel.example.com"):
    return ("""# Managed by U-OPTI - Smite Panel TLS backend
server {
    listen 127.0.0.1:8443 ssl;
    server_name """+domain+""";

    ssl_certificate /etc/letsencrypt/live/panel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/panel.example.com/privkey.pem;

    # BEGIN U-OPTI SMITE SIGNED PAIRING REDEEM
    location = /api/node-pairing/redeem {
        limit_except POST { deny all; }
        include /etc/nginx/u-opti-smite-pairing-secret.conf;
        proxy_pass http://127.0.0.1:8000;
    }
    # END U-OPTI SMITE SIGNED PAIRING REDEEM

    # BEGIN U-OPTI STANDARD FRP WSS
    location = /~!frp {
        proxy_pass http://127.0.0.1:7000;
    }
    # END U-OPTI STANDARD FRP WSS

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
""").encode()

def admission():
    return {"status":"verified_trial_pair","source_sha":stage.SOURCE,
            "panel":stage.NEW_PANEL,"node":stage.NEW_NODE,
            "host_activation_allowed":False}


class Prepare(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.panel=stage.PanelStage(self.root,admission=admission)
        self.original={}
        records={
            stage.PANEL_REL:(
                "PANEL_DOMAIN=panel.example.com\n"
                "DB_TYPE=sqlite\nDB_PATH=./data/smite.db\n"
                "SMITE_NODE_REGISTRATION_MODE=signed\n"
                "SMITE_PANEL_AGENT_AUTH_MODE=signed\n"
                "SMITE_NODE_PAIRING_PREVIEW_ENABLED=true\n"
                "SMITE_SIGNED_NODE_ORIGINS_PATH=/etc/smite-panel/trusted-nodes/approved-origins.json\n"
                f"SMITE_NODE_PAIRING_MASTER_KEY={MASTER}\n"
                f"SMITE_NODE_PAIRING_INGRESS_TOKEN={TOKEN}\n"
            ).encode(),
            stage.COMPOSE_REL:(
                "services:\n  smite-panel:\n    image: "+
                stage.OLD_PANEL+"\n    network_mode: host\n"
                "  smite-node:\n    image: ghcr.io/aghajani82/smite-node@sha256:"+"e"*64+"\n").encode(),
            stage.NGINX_REL:nginx(),
            stage.SIGNED_COMPOSE_REL: (
                b"services:\n  smite-panel:\n    volumes:\n"
                b"      - /etc/u-opti/smite/panel-trusted-nodes:/etc/smite-panel/trusted-nodes:ro\n"
            ),
            stage.ORIGINS_REL: json.dumps({"version": 1, "nodes": {
                "iran-node-1234": {"role": "iran", "node_name": "node-ir",
                                   "origin": "http://127.0.0.1:8888",
                                   "control_url": "http://127.0.0.1:8888/api/agent"}
            }}).encode(),
            stage.STATE_REL:b"SMITE_NODE_NAME=node-ir\nSMITE_ROLE=panel-iran\nSMITE_CONNECTION_MODE=standard\nSMITE_PANEL_DOMAIN=panel.example.com\n",
            stage.SECRET_REL:('proxy_set_header X-Smite-Pairing-Ingress "'+TOKEN+'";\n').encode(),
            stage.PAIRING_REL:json.dumps({"schema":1,"master_key":MASTER,"ingress_token":TOKEN}).encode(),
            stage.IR_ID_REL:json.dumps({"version":1,"node_id":"iran-node-1234","node_secret":NODE}).encode(),
        }
        for path,raw in records.items():
            dest=self.root/path
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(raw)
            dest.chmod(0o600 if path in (stage.PANEL_REL,stage.SECRET_REL,
                         stage.PAIRING_REL,stage.IR_ID_REL,stage.SIGNED_COMPOSE_REL,stage.ORIGINS_REL) else 0o644)
            self.original[path]=raw
        self.db=self.root/stage.DB_REL
        self.db.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""
            CREATE TABLE nodes(id TEXT,name TEXT,metadata TEXT);
            CREATE TABLE smite_node_identities(node_id TEXT,node_role TEXT,encrypted_secret TEXT,paired_at INTEGER,revoked_at INTEGER);
            CREATE TABLE smite_node_pairing_codes(code_hash TEXT,node_id TEXT,consumed_at INTEGER);
            CREATE TABLE smite_node_inbound_nonces(node_id TEXT,nonce TEXT,expires_at INTEGER);
            INSERT INTO nodes VALUES('iran-node-1234','node-ir','{}');
            INSERT INTO smite_node_identities VALUES('iran-node-1234','iran','secret-ciphertext',100,NULL);
            INSERT INTO smite_node_inbound_nonces VALUES('iran-node-1234','nonce',200);
            """)
        self.db.chmod(0o600)
        replay = self.root/stage.REPLAY_DB_REL
        replay.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(replay) as conn:
            conn.execute("PRAGMA user_version=1")
            conn.execute("CREATE TABLE replay_store_identity(node_id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO replay_store_identity VALUES('iran-node-1234')")
            conn.execute("CREATE TABLE agent_nonces(node_id TEXT, nonce TEXT, expires_at INTEGER)")
            conn.execute("INSERT INTO agent_nonces VALUES('iran-node-1234','replay-nonce',2222)")
        replay.chmod(0o600)
        binding = hmac.new(NODE.encode(),
                           b"smite-replay-key-binding-v1:iran-node-1234",
                           hashlib.sha256).hexdigest()
        marker = self.root/stage.REPLAY_MARKER_REL
        marker.write_text(json.dumps({
            "schema":1,"node_id":"iran-node-1234",
            "replay_database":"/var/lib/smite-node/auth/agent-replay.sqlite3",
            "status":"ENROLLMENT_STARTED", "key_binding":binding}))
        marker.chmod(0o600)
        self.original[stage.REPLAY_MARKER_REL]=marker.read_bytes()
        (self.root/"var/lib/u-opti").mkdir(parents=True,exist_ok=True)

    def assert_untouched(self):
        for path,raw in self.original.items():
            self.assertEqual((self.root/path).read_bytes(),raw,path)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT encrypted_secret FROM smite_node_identities").fetchone()[0],"secret-ciphertext")

    def stage(self):
        return self.panel.prepare(stage.CONFIRM)

    def test_prepare_consistent_snapshots_candidates_and_status(self):
        result=self.stage()
        self.assertEqual(result["state"],"PREPARED_ONLY")
        self.assertEqual(result["live_writes"],"NONE")
        self.assertFalse(result["activation_allowed"])
        self.assert_untouched()
        folder=self.panel.staging
        self.assertEqual(folder.stat().st_mode & 0o777,0o700)
        self.assertEqual(self.panel.status(),result)
        journal=json.loads((folder/"journal.json").read_text())
        self.assertFalse(journal["live_write"])
        self.assertEqual(journal["source_sha"],stage.SOURCE)
        for name in (*journal["snapshots"],*journal["candidates"],"journal.json"):
            self.assertEqual((folder/name).stat().st_mode & 0o777,0o600)
        env=(folder/"candidate-panel-env").read_text()
        self.assertIn("SMITE_FOREIGN_INSTALL_ENABLED=true",env)
        self.assertIn("SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED=true",env)
        self.assertIn("SMITE_NODE_PAIRING_MASTER_KEY="+MASTER,env)
        compose=(folder/"candidate-panel-compose").read_text()
        self.assertIn(stage.NEW_PANEL,compose)
        self.assertNotIn(stage.OLD_PANEL,compose)
        self.assertIn("smite-node@sha256:"+"e"*64,compose)
        proxy=(folder/"candidate-nginx-backend").read_text()
        self.assertIn("location = /api/foreign-install/redeem",proxy)
        self.assertIn("location = /~!frp",proxy)
        self.assertIn('proxy_set_header X-Smite-Pairing-Ingress "";',proxy)
        with sqlite3.connect(folder/"panel-db.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT nonce FROM smite_node_inbound_nonces").fetchone()[0],"nonce")
            self.assertEqual(conn.execute("SELECT encrypted_secret FROM smite_node_identities").fetchone()[0],"secret-ciphertext")
        with sqlite3.connect(folder/"iran-replay.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT nonce FROM agent_nonces").fetchone()[0],"replay-nonce")
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone(),(1,))

    def test_stage_requires_unrevoked_iran_identity_in_the_panel_database(self):
        for update in (
            "UPDATE smite_node_identities SET revoked_at=200",
            "UPDATE smite_node_identities SET node_role='foreign'",
            "UPDATE nodes SET name='replacement'",
        ):
            with self.subTest(update=update), sqlite3.connect(self.db) as conn:
                conn.execute("BEGIN")
                conn.execute(update)
                # The preflight uses an independent read-only connection.
                conn.commit()
                with self.assertRaises(stage.StageHold):
                    self.panel.prepare(stage.CONFIRM)
                self.assertFalse(self.panel.staging.exists())
                conn.execute("UPDATE smite_node_identities SET revoked_at=NULL,node_role='iran'")
                conn.execute("UPDATE nodes SET name='node-ir'")

    def test_stage_rejects_changed_iran_origin_before_creating_snapshot(self):
        path = self.root / stage.ORIGINS_REL
        origins = json.loads(path.read_text())
        origins["nodes"]["iran-node-1234"]["control_url"] = "http://127.0.0.1:9999/api/agent"
        path.write_text(json.dumps(origins))
        with self.assertRaises(stage.StageHold):
            self.panel.prepare(stage.CONFIRM)
        self.assertFalse(self.panel.staging.exists())

    def test_live_baseline_requires_completed_owner_and_exact_active_overlay(self):
        project = "uopti_rc6_" + "a" * 32
        complete = {"ir_phase": "COMPLETE", "id": project}
        command = [
            "docker", "compose", "--project-name", project,
            "-f", "/" + stage.COMPOSE_REL, "-f", "/" + stage.SIGNED_COMPOSE_REL,
        ]
        journal = SimpleNamespace(
            folder=self.root, load=lambda: complete, _ir_witness=lambda record: None,
        )
        journal_module = SimpleNamespace(
            Journal=lambda: journal, trusted=lambda *args: None, Hold=RuntimeError,
        )
        runner = unittest.mock.Mock()
        pairing = SimpleNamespace(
            _panel_compose_command=unittest.mock.Mock(return_value=command),
            _run=runner, WizardHold=RuntimeError,
        )
        live = stage.PanelStage()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            stage, "_module", side_effect=lambda name: journal_module
            if name == "smite-rc6-install-journal" else pairing
        ):
            live.verify_live_baseline()
            runner.assert_called_once_with(command + ["config", "--quiet"], timeout=30)
            runner.reset_mock()
            pairing._panel_compose_command.return_value = command[:-2]
            with self.assertRaises(stage.StageHold):
                live.verify_live_baseline()
            runner.assert_not_called()
            pairing._panel_compose_command.return_value = command
            complete["ir_phase"] = "ADMIN_CREATED"
            with self.assertRaises(stage.StageHold):
                live.verify_live_baseline()
            runner.assert_not_called()
            with patch.dict(os.environ, {"DOCKER_HOST": "tcp://remote.example:2375"}):
                with self.assertRaises(stage.StageHold):
                    live.verify_live_baseline()
            runner.assert_not_called()

    def test_confirmation_required_without_any_snapshot(self):
        with self.assertRaises(stage.StageHold):
            self.panel.prepare("YES")
        self.assertFalse(self.panel.staging.exists())
        self.assert_untouched()

    def test_live_report_checks_both_endpoints_without_guessing_installed_sha(self):
        record = {"role": "panel-iran", "ir_phase": "COMPLETE",
                  "id": "uopti_rc6_" + "a" * 32, "source": "b" * 40}
        journal = SimpleNamespace(ir_admin_present=lambda: True)
        journal_module = SimpleNamespace(Hold=RuntimeError, VERSION="2.0.0-rc.7")
        run = unittest.mock.Mock(return_value="200")
        pairing = SimpleNamespace(
            _run=run, WizardHold=RuntimeError,
            _local_signed_replay_probe=unittest.mock.Mock(),
            _wait_panel_signed_checkin=unittest.mock.Mock(),
            _panel_to_ir_signed_probe=unittest.mock.Mock(),
        )
        ref = self.root / stage.INSTALL_REF_REL
        ref.parent.mkdir(parents=True)
        ref.write_text("trial/unified-smite-install\n")
        load_module = stage._module
        with patch.object(self.panel, "verify_live_baseline",
                          return_value=(journal, record, journal_module)), \
                patch.object(stage, "_module", side_effect=lambda name: pairing
                             if name == "smite-node-pairing" else load_module(name)):
            report = self.panel.live_baseline_report()
            self.assertEqual(report["IR_INSTALL_SOURCE_ON_HOST"], "UNKNOWN")
            self.assertEqual(report["IR_SIGNED_TWO_WAY"],
                             "PASS_EXISTING_SIGNED_CONTROL_PROBES")
            pairing._local_signed_replay_probe.assert_called_once_with()
            pairing._wait_panel_signed_checkin.assert_called_once_with(
                "iran-node-1234", timeout=6)
            pairing._panel_to_ir_signed_probe.assert_called_once_with(
                "iran-node-1234")
            loopback, https = [call.args[0] for call in run.call_args_list]
            self.assertEqual(loopback[-1], "http://127.0.0.1:8000/api/status")
            self.assertEqual(https[-3:], ["--resolve", "panel.example.com:443:127.0.0.1",
                                           "https://panel.example.com:443/api/status"])
            self.assertNotIn("--insecure", https)
            ref.write_text("c" * 40 + "\n")
            self.assertEqual(self.panel.live_baseline_report()["IR_INSTALL_SOURCE_ON_HOST"], "c" * 40)
            run.return_value = "302"
            pairing._local_signed_replay_probe.reset_mock()
            with self.assertRaises(stage.StageHold):
                self.panel.live_baseline_report()
            pairing._local_signed_replay_probe.assert_not_called()
            run.return_value = "200"
            for failing in (
                pairing._local_signed_replay_probe,
                pairing._wait_panel_signed_checkin,
                pairing._panel_to_ir_signed_probe,
            ):
                failing.side_effect = RuntimeError("signed control unavailable")
                with self.assertRaises(stage.StageHold):
                    self.panel.live_baseline_report()
                failing.side_effect = None
        self.assertFalse(self.panel.staging.exists())
        self.assert_untouched()

    def test_signed_pair_must_pass_before_writes(self):
        self.panel._admission=lambda: {"status":"not verified"}
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())
        self.assert_untouched()

    def test_preexisting_stage_is_never_overwritten(self):
        self.stage()
        first=(self.panel.staging/"journal.json").read_bytes()
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertEqual((self.panel.staging/"journal.json").read_bytes(),first)
        self.assert_untouched()

    def test_wal_committed_rows_in_snapshot(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("INSERT INTO nodes VALUES('other-node','node-other','{}')")
        self.stage()
        with sqlite3.connect(self.panel.staging/"panel-db.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],2)
        self.assert_untouched()

    def test_bad_role_or_domain_holds_without_stage_dir(self):
        targets=[
            (stage.STATE_REL,b"panel-iran",b"foreign"),
            (stage.PANEL_REL,b"panel.example.com",b"other.example.com"),
            (stage.STATE_REL,b"standard",b"private"),
            (stage.PANEL_REL,b"DB_PATH=./data/smite.db",b"DB_PATH=/tmp/evil"),
            (stage.PANEL_REL,b"SMITE_NODE_REGISTRATION_MODE=signed",b"SMITE_NODE_REGISTRATION_MODE=legacy"),
        ]
        for path,before,after in targets:
            target=self.root/path
            original=target.read_bytes()
            target.write_bytes(original.replace(before,after))
            try:
                with self.subTest(path=path,after=after),self.assertRaises(stage.StageHold):
                    self.stage()
                self.assertFalse(self.panel.staging.exists())
            finally:
                target.write_bytes(original)

    def test_bad_secret_includes_and_mismatched_key_halt(self):
        for path,before,after in [
            (stage.SECRET_REL,TOKEN.encode(),b"0"*64),
            (stage.PAIRING_REL,MASTER.encode(),b"0"*44),
            (stage.PANEL_REL,TOKEN.encode(),b"d"*64),
        ]:
            target=self.root/path
            original=target.read_bytes()
            target.write_bytes(original.replace(before,after))
            try:
                with self.subTest(path=path),self.assertRaises(stage.StageHold):
                    self.stage()
                self.assertFalse(self.panel.staging.exists())
            finally:
                target.write_bytes(original)

    def test_existing_trial_flag_or_duplicate_env_halts(self):
        path=self.root/stage.PANEL_REL
        original=path.read_bytes()
        for extra in (b"SMITE_FOREIGN_INSTALL_ENABLED=true\n",
                      b"SMITE_PANEL_AGENT_AUTH_MODE=signed\n"):
            path.write_bytes(original+extra)
            try:
                with self.assertRaises(stage.StageHold):self.stage()
                self.assertFalse(self.panel.staging.exists())
            finally:
                path.write_bytes(original)

    def test_unrecognized_image_or_unmanaged_nginx_halts(self):
        for path,old,new in [
            (stage.COMPOSE_REL,stage.OLD_PANEL.encode(),b"smite-panel:latest"),
            (stage.NGINX_REL,b"Managed by U-OPTI",b"Unmanaged Gateway"),
        ]:
            target=self.root/path
            original=target.read_bytes()
            target.write_bytes(original.replace(old,new))
            try:
                with self.assertRaises(stage.StageHold):self.stage()
                self.assertFalse(self.panel.staging.exists())
            finally:
                target.write_bytes(original)

    def test_symlink_and_hardlink_inputs_halt(self):
        target=self.root/stage.SECRET_REL
        original=target.read_bytes()
        target.unlink()
        target.symlink_to(self.root/stage.PAIRING_REL)
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())
        target.unlink()
        target.write_bytes(original)
        target.chmod(0o600)
        link=self.root/"duplicate-link"
        os.link(target,link)
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())
        link.unlink()

    def test_partial_interrupted_stage_is_quarantined(self):
        original=self.panel._write
        def interrupted(name,data):
            if name=="candidate-panel-compose":
                raise OSError("simulated interruption")
            original(name,data)
        with patch.object(self.panel,"_write",side_effect=interrupted):
            with self.assertRaises(stage.StageHold):self.stage()
        self.assertTrue(self.panel.staging.is_dir())
        self.assertFalse((self.panel.staging/"journal.json").exists())
        with self.assertRaises(stage.StageHold):self.panel.status()
        with self.assertRaises(stage.StageHold):self.stage()
        self.assert_untouched()

    def test_snapshot_tampering_detected_without_live_change(self):
        self.stage()
        path=self.panel.staging/"candidate-panel-compose"
        path.write_bytes(b"tampered")
        with self.assertRaises(stage.StageHold):self.panel.status()
        self.assert_untouched()

    def test_forged_candidate_and_rehashed_journal_still_hold(self):
        # The previous stage status only checked the expected HASH values.
        # An attacker able to alter the private stage and its own journal
        # could previously bless changed Panel flags, image or ingress.
        import hashlib
        for name, replacement in (
            ("candidate-panel-env",
             lambda b: b.replace(b"SMITE_FOREIGN_INSTALL_ENABLED=true",
                                 b"SMITE_FOREIGN_INSTALL_ENABLED=false")),
            ("candidate-panel-compose",
             lambda b: b.replace(stage.NEW_PANEL.encode(),
                                 b"ghcr.io/foreign/unsigned:latest")),
            ("candidate-nginx-backend",
             lambda b: b.replace(b"proxy_cache off;", b"proxy_cache on;")),
        ):
            with self.subTest(candidate=name):
                # Reset a complete, original signed stage, not any host files.
                if self.panel.staging.exists():
                    import shutil
                    shutil.rmtree(self.panel.staging)
                self.stage()
                before = self.panel.status()
                self.assertEqual(before["state"], "PREPARED_ONLY")
                dest = self.panel.staging / name
                changed = replacement(dest.read_bytes())
                self.assertNotEqual(changed, dest.read_bytes())
                dest.write_bytes(changed)
                journal = self.panel.staging / "journal.json"
                recorded = json.loads(journal.read_text())
                recorded["candidates"][name] = hashlib.sha256(changed).hexdigest()
                journal.write_text(json.dumps(recorded, sort_keys=True) + "\n")
                self.assertEqual(
                    hashlib.sha256(dest.read_bytes()).hexdigest(),
                    recorded["candidates"][name])
                with self.assertRaises(stage.StageHold):
                    self.panel.status()
                self.assert_untouched()

    def test_forged_preimage_and_matching_digest_do_not_override_renderer(self):
        import hashlib
        self.stage()
        original = self.panel.staging / "before-panel-compose"
        fake = original.read_bytes().replace(
            stage.OLD_PANEL.encode(), b"ghcr.io/unreviewed/foreign:latest")
        self.assertNotEqual(original.read_bytes(), fake)
        original.write_bytes(fake)
        journal = self.panel.staging / "journal.json"
        record = json.loads(journal.read_text())
        record["snapshots"][original.name] = hashlib.sha256(fake).hexdigest()
        journal.write_text(json.dumps(record, sort_keys=True) + "\n")
        with self.assertRaises(stage.StageHold):
            self.panel.status()
        self.assert_untouched()

    def test_staging_journal_duplicate_nested_or_unreviewed_fields_hold(self):
        self.stage()
        journal = self.panel.staging / "journal.json"
        original = journal.read_bytes()
        variants = (
            original.rstrip().removesuffix(b"}") +
                b',"source_sha":"0000000000000000000000000000000000000000"}\n',
            original.replace(b'"snapshots": {',
                             b'"snapshots": {"before-panel-env":"0",', 1),
            original.rstrip().removesuffix(b"}") +
                b',"production_apply":true}\n',
            original.replace(b'"candidates": {',b'"candidates": [], "unused": {', 1),
        )
        for forged in variants:
            self.assertNotEqual(forged, original, "fixture was not mutated")
            with self.subTest(forged=forged[:48]):
                journal.write_bytes(forged)
                with self.assertRaises((stage.StageHold, ValueError, TypeError)):
                    self.panel.status()
                self.assert_untouched()
        journal.write_bytes(original)
        self.assertEqual(self.panel.status()["state"], "PREPARED_ONLY")

    def test_staging_journal_invalid_digest_type_holds_cleanly(self):
        self.stage()
        journal = self.panel.staging / "journal.json"
        saved = json.loads(journal.read_text())
        saved["candidates"]["candidate-panel-env"] = None
        journal.write_text(json.dumps(saved))
        with self.assertRaises(stage.StageHold):
            self.panel.status()
        self.assert_untouched()

    def test_extra_state_or_sqlite_wal_sidecar_halts_status(self):
        self.stage()
        sidecar=self.panel.staging/"panel-db.sqlite3-wal"
        sidecar.write_bytes(b"unreviewed")
        with self.assertRaises(stage.StageHold):self.panel.status()
        sidecar.unlink()
        self.assertEqual(self.panel.status()["state"],"PREPARED_ONLY")

    def test_existing_pairing_schema_required(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TABLE smite_node_inbound_nonces")
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())

    def test_replay_marker_tamper_holds_before_staging(self):
        marker = self.root/stage.REPLAY_MARKER_REL
        original = marker.read_bytes()
        marker.write_bytes(original.replace(b"replay-key-binding-v1",b"invalid-binding"))
        # Corrupt the stored HMAC commitment, preserving JSON syntax.
        marker.write_bytes(original.replace(
            json.loads(original)["key_binding"].encode(), b"0"*64))
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())

    def test_missing_replay_database_halts_before_staging(self):
        (self.root/stage.REPLAY_DB_REL).unlink()
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())

    def test_mismatched_replay_identity_prevents_stage(self):
        with sqlite3.connect(self.root/stage.REPLAY_DB_REL) as conn:
            conn.execute("UPDATE replay_store_identity SET node_id='wrong-node'")
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())

    def test_replay_wal_snapshot_preserves_nonce(self):
        replay = self.root/stage.REPLAY_DB_REL
        with sqlite3.connect(replay) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("INSERT INTO agent_nonces VALUES('iran-node-1234','recent',3000)")
        self.stage()
        with sqlite3.connect(self.panel.staging/"iran-replay.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM agent_nonces").fetchone()[0],2)
        self.assertEqual((self.root/stage.REPLAY_MARKER_REL).read_bytes(),
                         self.original[stage.REPLAY_MARKER_REL])

    def test_absent_iran_identity_prevents_foreign_grants_stage(self):
        (self.root/stage.IR_ID_REL).unlink()
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
