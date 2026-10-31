"""Offline KH runtime observation tests using a temporary SQLite database.

No Docker daemon, root privileges, external network or live host access.
All commands are injected deterministic read-only fixtures.
"""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"modules/smite-stage15-kh-host-observer.py"
spec=importlib.util.spec_from_file_location("kh_observer",PATH)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)


class KHObserverTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db=self.root/"x-ui.db"
        self.proc=self.root/"proc"
        entry=self.proc/"777"
        entry.mkdir(parents=True)
        fields=["S"]+["0"]*18+["123456"]+["0"]*4
        (entry/"stat").write_text("777 (xray) "+" ".join(fields))
        self.node={
            "Image":m.NODE_IMAGE,
            "State":{"Running":True,"Health":{"Status":"healthy"}},
            "RestartCount":0,
        }
        self.ui={
            "Id":"c"*64,
            "State":{"Running":True},
            "RestartCount":0,
            "Mounts":[{"Type":"volume","Source":str(self.root),
                       "Destination":"/etc/x-ui"}],
        }
        self.ss='LISTEN 0 4096 127.0.0.1:38658 0.0.0.0:* users:(("xray",pid=777,fd=13))'
        self.frpc="PID COMMAND\n221 frpc\n222 frpc\n223 frpc\n224 python3\n"
        self.xray="PID COMMAND\n777 xray\n778 x-ui\n"
        self.rows=[
            (38658,"127.0.0.1","vless",
             json.dumps({"network":"xhttp","xhttpSettings":{"path":"/38658/shop"},
                         "extra":{"id":"DO_NOT_EXPOSE_SECRET"}}),1),
            (45121,"127.0.0.1","vless",
             json.dumps({"network":"xhttp","xhttpSettings":{"path":"/45121/www"}}),1),
        ]
        self.write_db()

    def write_db(self):
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE IF NOT EXISTS inbounds("
                       "port INTEGER,listen TEXT,protocol TEXT,"
                       "stream_settings TEXT,enable INTEGER)")
            db.execute("DELETE FROM inbounds")
            db.executemany("INSERT INTO inbounds VALUES(?,?,?,?,?)",self.rows)

    def mock_runner(self,*argv):
        if argv==("docker","inspect","smite-node"):
            return json.dumps([self.node])
        if argv==("docker","inspect","3xui-01"):
            return json.dumps([self.ui])
        if argv==("docker","top","smite-node","-eo","pid,comm"):
            return self.frpc
        if argv==("docker","top","3xui-01","-eo","pid,comm"):
            return self.xray
        if argv==("ss","-Hlntp"):
            return self.ss
        self.fail("Unexpected command: "+str(argv))

    def collect(self,**kwargs):
        return m.collect_kh(node_id="node-kh-0001",port=38658,
                            path="/38658/shop",db_path=self.db,
                            proc_root=self.proc,runner=self.mock_runner,
                            require_host=False,**kwargs)

    def test_reads_live_sqlite_and_xray_and_redacts_credentials(self):
        facts=self.collect()
        self.assertEqual(facts["xray_pid"],777)
        self.assertEqual(facts["xray_start_ticks"],123456)
        self.assertEqual(facts["frpc_count"],3)
        self.assertEqual(facts["path"],"/38658/shop")
        self.assertEqual(len(facts["db_view_sha256"]),64)
        self.assertNotIn("DO_NOT_EXPOSE_SECRET",repr(facts))
        self.assertEqual(facts["sanaei_container_id"],"c"*64)

    def test_wrong_runtime_image_and_restart_hold(self):
        self.node["Image"]="sha256:"+"a"*64
        with self.assertRaisesRegex(m.ObserverHold,"KH_NODE_RUNTIME_DRIFT"):
            self.collect()
        self.node["Image"]=m.NODE_IMAGE
        self.ui["RestartCount"]=1
        with self.assertRaisesRegex(m.ObserverHold,"SANAEI_RUNTIME_DRIFT"):
            self.collect()

    def test_duplicate_inbound_or_path_drift_holds(self):
        self.rows.append(self.rows[0])
        self.write_db()
        with self.assertRaisesRegex(m.ObserverHold,"SANAEI_XHTTP_DUPLICATE"):
            self.collect()
        self.rows=[row for row in self.rows if row[0] != 38658]
        self.write_db()
        with self.assertRaisesRegex(m.ObserverHold,"SANAEI_XHTTP_INBOUND_NOT_UNIQUE"):
            self.collect()

    def test_non_loopback_inbound_holds(self):
        row=list(self.rows[0])
        row[1]="0.0.0.0"
        self.rows[0]=tuple(row)
        self.write_db()
        with self.assertRaisesRegex(m.ObserverHold,"SANAEI_XHTTP_ENTRY_INVALID"):
            self.collect()

    def test_wal_partial_and_untrusted_copy_hold(self):
        wal=self.root/"x-ui.db-wal"
        wal.write_bytes(b"fake wal")
        with self.assertRaisesRegex(m.ObserverHold,"SANAEI_WAL_INCOMPLETE"):
            self.collect()
        wal.unlink()
        self.ui["Mounts"]=[]
        with self.assertRaisesRegex(m.ObserverHold,
                                    "SANAEI_AUTHORITATIVE_MOUNT_UNVERIFIED"):
            self.collect()

    def test_frpc_and_xray_owner_must_match(self):
        self.frpc="PID COMMAND\n221 frpc\n222 frpc\n224 python3\n"
        with self.assertRaisesRegex(m.ObserverHold,"KH_FRPC_PROCESS_DRIFT"):
            self.collect()
        self.frpc="PID COMMAND\n221 frpc\n222 frpc\n223 frpc\n"
        self.ss=self.ss.replace("pid=777","pid=999")
        with self.assertRaisesRegex(m.ObserverHold,"KH_XRAY_SOCKET_OWNER_DRIFT"):
            self.collect()
        self.ss=self.ss.replace("127.0.0.1","0.0.0.0")
        with self.assertRaisesRegex(m.ObserverHold,"PUBLIC_OR_NON_LOOPBACK_XRAY"):
            self.collect()

    def test_process_generation_mismatch_holds(self):
        path=self.proc/"777"/"stat"
        before=path.read_text()
        calls=0
        original=m.pid_start_ticks
        def changed(pid,*,proc_root):
            nonlocal calls
            calls+=1
            return 123456 if calls==1 else 789101
        with patch.object(m,"pid_start_ticks",side_effect=changed):
            with self.assertRaisesRegex(m.ObserverHold,"KH_RUNTIME_GENERATION_CHANGED"):
                self.collect()
        self.assertEqual(path.read_text(),before)

    def test_unexpected_or_expired_observation_holds(self):
        with patch.object(m.time,"monotonic",side_effect=[1,10]):
            with self.assertRaisesRegex(m.ObserverHold,"KH_OBSERVATION_EXPIRED"):
                self.collect()
        with self.assertRaisesRegex(m.ObserverHold,"KH_ROOT_ONLY"):
            with patch.object(m.os,"geteuid",return_value=0), \
                 patch.object(m.socket,"gethostname",return_value="grandoptical"):
                m.collect_kh(node_id="node-kh-0001",port=38658,
                             path="/38658/shop",db_path=self.db,
                             runner=self.mock_runner,proc_root=self.proc)

    def test_source_has_no_signing_grant_or_service_entrypoint(self):
        source=PATH.read_text()
        for forbidden in ('install_grant(', 'serve_forever(', 'Popen(',
                          '"docker","restart"', '"docker","stop"',
                          'ALTER TABLE','UPDATE inbounds', 'DELETE FROM inbounds'):
            self.assertNotIn(forbidden,source)
        self.assertIn("OFFLINE_REVIEW_LIBRARY_ONLY_NO_LIVE_APPROVAL",source)


if __name__=="__main__":
    unittest.main()
