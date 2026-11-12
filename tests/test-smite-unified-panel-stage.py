"""Disposable, no-host-write tests for signed Iran Panel staged transaction."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
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
                f"SMITE_NODE_PAIRING_MASTER_KEY={MASTER}\n"
                f"SMITE_NODE_PAIRING_INGRESS_TOKEN={TOKEN}\n"
            ).encode(),
            stage.COMPOSE_REL:(
                "services:\n  smite-panel:\n    image: "+
                stage.OLD_PANEL+"\n    network_mode: host\n"
                "  smite-node:\n    image: ghcr.io/aghajani82/smite-node@sha256:"+"e"*64+"\n").encode(),
            stage.NGINX_REL:nginx(),
            stage.STATE_REL:b"SMITE_ROLE=panel-iran\nSMITE_CONNECTION_MODE=standard\nSMITE_PANEL_DOMAIN=panel.example.com\n",
            stage.SECRET_REL:('proxy_set_header X-Smite-Pairing-Ingress "'+TOKEN+'";\n').encode(),
            stage.PAIRING_REL:json.dumps({"schema":1,"master_key":MASTER,"ingress_token":TOKEN}).encode(),
            stage.IR_ID_REL:json.dumps({"version":1,"node_id":"iran-node-1234","node_secret":NODE}).encode(),
        }
        for path,raw in records.items():
            dest=self.root/path
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(raw)
            dest.chmod(0o600 if path in (stage.PANEL_REL,stage.SECRET_REL,
                         stage.PAIRING_REL,stage.IR_ID_REL) else 0o644)
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

    def test_confirmation_required_without_any_snapshot(self):
        with self.assertRaises(stage.StageHold):
            self.panel.prepare("YES")
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

    def test_existing_pairing_schema_required(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TABLE smite_node_inbound_nonces")
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())

    def test_absent_iran_identity_prevents_foreign_grants_stage(self):
        (self.root/stage.IR_ID_REL).unlink()
        with self.assertRaises(stage.StageHold):self.stage()
        self.assertFalse(self.panel.staging.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
