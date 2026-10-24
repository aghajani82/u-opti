#!/usr/bin/env python3
"""Offline RC2 signed Panel local image transaction and SQLite backup test."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"modules/smite-rc2-panel-wss-activation.py"
spec=importlib.util.spec_from_file_location("rc2_panel_wss_transaction",SOURCE)
tx=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)


class PanelTransaction(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="rc2-panel-tx-")
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.site=root/"smite";self.site.mkdir(mode=0o700)
        self.base=self.site/"docker-compose.yml";self.base.write_text("base\n")
        self.signed=self.site/"docker-compose.signed-control.yml";self.signed.write_text("signed\n")
        self.overlay=self.site/"docker-compose.panel-wss-rc2.yml"
        self.state_parent=root/"u-opti";self.state_parent.mkdir(mode=0o700)
        self.state=self.state_parent/"rc2-panel"
        self.database_dir=root/"paneldata";self.database_dir.mkdir(mode=0o700)
        self.database=self.database_dir/"smite.db"
        con=sqlite3.connect(self.database)
        con.execute("CREATE TABLE sessions(id INTEGER PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO sessions(value) VALUES ('persisted')")
        con.commit();con.close()
        self.existing_mounts=[
            {"Destination":"/app/data","Source":str(self.database_dir),"Type":"bind","RW":True},
            {"Destination":"/app/certs","Source":str(root/"certs"),"Type":"bind","RW":True},
            {"Destination":"/app/config/.env","Source":str(root/"config.env"),"Type":"bind","RW":False},
            {"Destination":"/app/config/docker-compose.yml","Source":str(root/"old-compose"),"Type":"bind","RW":False},
            {"Destination":"/etc/smite-panel/trusted-nodes","Source":str(root/"origins"),"Type":"bind","RW":False},
        ]
        self.enabled=False
        self.recreated=0
        self.fail_new=False
        self.fail_rollback=False
        self.protected={}
        self.calls=[]
        self.unhealthy=False
        for name,value in (
            ("BASE",self.base),("SIGNED",self.signed),("OVERLAY",self.overlay),
            ("STATE",self.state),("JOURNAL",self.state/"record.json"),
            ("DATABASE_BACKUP",self.state/"smite-db.before.sqlite3"),
            ("LOCK",root/"lockfile"),
        ):
            p=patch.object(tx,name,value);p.start();self.addCleanup(p.stop)
        for name,fn in (
            ("safe_dir",self.safe_dir),("safe_file",self.safe_file),
            ("run",self.run),("inspect",self.inspect),
            ("panel_settings",self.panel_settings),
            ("source_pin",lambda o:None),("lock",self.lock),
            ("wait_panel",self.wait_panel),
        ):
            p=patch.object(tx,name,fn);p.start();self.addCleanup(p.stop)

    def safe_dir(self,path,private=False):
        st=path.lstat()
        if not stat.S_ISDIR(st.st_mode):
            raise tx.Hold("UNTRUSTED_DIRECTORY")
        if private and stat.S_IMODE(st.st_mode)!=0o700:
            raise tx.Hold("UNTRUSTED_DIRECTORY_MODE")

    def safe_file(self,path,limit=262144,exact_mode=None):
        st=path.lstat()
        if not stat.S_ISREG(st.st_mode) or path.is_symlink():
            raise tx.Hold("UNTRUSTED_FILE")
        if exact_mode is not None and stat.S_IMODE(st.st_mode)!=exact_mode:
            raise tx.Hold("UNTRUSTED_FILE_MODE")
        if st.st_size>limit:
            raise tx.Hold("FILE_LIMIT")
        return path.read_bytes()

    def lock(self):
        return os.open(tx.LOCK,os.O_CREAT|os.O_RDWR,0o600)

    def inspect(self):
        image=tx.CANDIDATE_ID if self.enabled else tx.BASE_ID
        src=tx.CANDIDATE if self.enabled else tx.ORIGINAL
        active_files=[str(self.base),str(self.signed)]
        if self.enabled:
            active_files.append(str(self.overlay))
        return {
            "Id":"panel-"+str(self.recreated),
            "Image":image,
            "Config":{
                "Image":src,
                "Env":[],
                "Labels":{
                    "com.docker.compose.service":"smite-panel",
                    "com.docker.compose.project.config_files":",".join(active_files)
                }
            },
            "State":{"Running":not self.unhealthy,
                     "Health":{"Status":"unhealthy" if self.unhealthy else "healthy"}},
            "Mounts":list(self.existing_mounts),
        }

    def service(self,enabled):
        env={"SMITE_PANEL_AGENT_AUTH_MODE":"signed",
             "SMITE_ENGINE_MANAGEMENT_MODE":"managed",
             "PANEL_DOMAIN":"ir.kolbe1.ir"}
        if enabled:
            env["SMITE_FRP_STANDARD_WSS"]="1"
        return {
            "image":tx.CANDIDATE if enabled else tx.ORIGINAL,
            "network_mode":"host",
            "environment":env,
            "volumes":[m.copy() for m in self.existing_mounts],
        }

    def run(self,args,*,data=None,timeout=40,json_output=False):
        self.calls.append((tuple(args),data))
        if args[0:3]==["docker","image","inspect"]:
            return tx.CANDIDATE_ID
        if args[:2]==["docker","compose"] and "config" in args:
            enabled=("-" in args and data is not None)
            return {"services":{"smite-panel":self.service(enabled)}}
        if args[:2]==["docker","compose"] and "up" in args:
            enabled=str(self.overlay) in args
            if enabled and self.fail_new:
                self.enabled=True
                self.unhealthy=True
                raise tx.Hold("SIMULATED_FAILED_NEW_RECREATION")
            if not enabled and self.fail_rollback:
                raise tx.Hold("SIMULATED_FAILED_ROLLBACK")
            self.enabled=enabled
            self.unhealthy=False
            self.recreated+=1
            return ""
        if args[0]=="curl":
            return ""
        raise AssertionError("unexpected command "+repr(args))

    def panel_settings(self,enabled):
        if enabled!=self.enabled:
            raise tx.Hold("PANEL_WSS_FLAG_DRIFT")
        return "./data/smite.db"

    def wait_panel(self,doc,enabled):
        tx.runtime_check(doc,enabled)

    def test_plan_is_read_only_and_preserves_signed_compose(self):
        with patch.object(tx.os,"geteuid",return_value=0), \
             patch.object(tx.os,"uname",return_value=type("N",(),{"nodename":"ir"})()):
            proof=tx.plan()
        self.assertEqual(proof["original_image"],tx.BASE_ID)
        self.assertEqual(proof["candidate_image"],tx.CANDIDATE_ID)
        self.assertEqual(proof["db_path"],str(self.database))
        self.assertFalse(self.state.exists())
        self.assertFalse(self.overlay.exists())
        self.assertEqual(self.recreated,0)

    def test_apply_verify_rollback_keeps_sqlite_backup_and_exact_signed(self):
        with patch.object(tx.os,"geteuid",return_value=0), \
             patch.object(tx.os,"uname",return_value=type("N",(),{"nodename":"ir"})()):
            tx.apply()
        self.assertTrue(self.enabled)
        self.assertEqual(self.recreated,1)
        self.assertEqual(tx.journal()["state"],"COMMITTED")
        self.assertEqual(stat.S_IMODE(self.overlay.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(tx.DATABASE_BACKUP.stat().st_mode),0o600)
        backup=sqlite3.connect(tx.DATABASE_BACKUP)
        try:
            self.assertEqual(backup.execute("SELECT value FROM sessions").fetchone()[0],
                             "persisted")
        finally:backup.close()
        tx.verify()
        tx.rollback()
        self.assertFalse(self.enabled)
        self.assertEqual(self.recreated,2)
        self.assertFalse(self.overlay.exists())
        self.assertEqual(tx.journal()["state"],"ROLLED_BACK")
        self.assertTrue(tx.DATABASE_BACKUP.is_file())
        self.assertEqual(self.base.read_text(),"base\n")
        self.assertEqual(self.signed.read_text(),"signed\n")

    def test_candidate_unhealthy_forces_original_image_rollback(self):
        self.fail_new=True
        with patch.object(tx.os,"geteuid",return_value=0), \
             patch.object(tx.os,"uname",return_value=type("N",(),{"nodename":"ir"})()):
            with self.assertRaisesRegex(tx.Hold,"PANEL_ACTIVATION_FAILED_ROLLED_BACK"):
                tx.apply()
        self.assertFalse(self.enabled)
        self.assertFalse(self.unhealthy)
        self.assertEqual(tx.journal()["state"],"ROLLED_BACK")
        self.assertTrue(tx.DATABASE_BACKUP.exists())

    def test_backup_error_never_restarts_live_panel(self):
        with patch.object(tx.os,"geteuid",return_value=0), \
             patch.object(tx.os,"uname",return_value=type("N",(),{"nodename":"ir"})()),\
             patch.object(tx,"backup_db",side_effect=tx.Hold("NO_BACKUP")):
            with self.assertRaisesRegex(tx.Hold,"BACKUP_PREPARATION_HOLD_NO_RESTART"):
                tx.apply()
        self.assertFalse(self.enabled)
        self.assertEqual(self.recreated,0)
        self.assertFalse(self.overlay.exists())
        self.assertEqual(tx.journal()["state"],"PREPARED")

    def test_compose_drift_refuses_rollback_and_retains_backup(self):
        with patch.object(tx.os,"geteuid",return_value=0), \
             patch.object(tx.os,"uname",return_value=type("N",(),{"nodename":"ir"})()):
            tx.apply()
        self.signed.write_text("UNEXPECTED CHANGE\n")
        with self.assertRaisesRegex(tx.Hold,"PROTECTED_PANEL_COMPOSE_DRIFT"):
            tx.rollback()
        self.assertTrue(self.enabled)
        self.assertTrue(tx.DATABASE_BACKUP.is_file())

    def test_prepared_recovery_restores_original(self):
        with patch.object(tx.os,"geteuid",return_value=0), \
             patch.object(tx.os,"uname",return_value=type("N",(),{"nodename":"ir"})()):
            proof=tx.plan()
            doc=tx.record(proof)
            tx.backup_db(doc)
            tx.create_file(tx.OVERLAY,tx.OVERLAY_TEXT.encode(),0o600)
            self.enabled=True
            self.recreated=1
            tx.rollback(recover=True)
        self.assertFalse(self.enabled)
        self.assertEqual(tx.journal()["state"],"ROLLED_BACK")

    def test_never_restarts_other_services_or_rewrites_db(self):
        source=SOURCE.read_text()
        for forbidden in ("docker compose down", "docker compose stop",
                          "docker exec smite-node", "sqlite3.connect('smite.db')",
                          "systemctl reload nginx","ufw ","iptables "):
            self.assertNotIn(forbidden,source)
        self.assertIn('"--no-deps"',source)
        self.assertIn('"--pull","never"',source)
        self.assertIn("DATABASE_AUTORESTORE=NO",source)
        self.assertIn("SNAPSHOTS-AND-IR-CONSOLE-VERIFIED",source)


if __name__=="__main__":
    unittest.main(verbosity=2)
