"""Root's independent read-only lease snapshots and signed Node request tests."""
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/"modules"
spec=importlib.util.spec_from_file_location("root_lease_evidence",ROOT/"smite-stage15-live-evidence.py")
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class LeaseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.db=Path(tmp.name)/"panel-snapshot.db"
        conn=sqlite3.connect(self.db)
        conn.executescript("""CREATE TABLE tunnels(
            id TEXT PRIMARY KEY,core TEXT,status TEXT,node_id TEXT,
            iran_node_id TEXT,foreign_node_id TEXT,spec TEXT);
            CREATE TABLE frp_proxy_leases(
            tunnel_id TEXT,owner_tunnel_id TEXT,iran_node_id TEXT,
            foreign_node_id TEXT,remote_port INTEGER);""")
        self.conn=conn
        self.addCleanup(conn.close)
        self.binding={"ir_node":"node-ir-0001","kh_node":"node-kh-0001",
          "owner":"owner-0001","child":"child-0001","lease":"child-0001",
          "port":38658,"path":"/38658/shop",
          "owner_proof_sha256":"a"*64,"kh_inventory_sha256":"b"*64}
        self.row("owner-0001",{"bind_port":7000,"ports":[38658]})
        self.row("child-0001",{"shared_frps_owner":"owner-0001"})
        self.conn.execute("INSERT INTO frp_proxy_leases VALUES(?,?,?,?,?)",
            ("child-0001","owner-0001","node-ir-0001","node-kh-0001",38658))
        self.conn.commit()

    def row(self,id,spec,status="active"):
        self.conn.execute("INSERT INTO tunnels VALUES(?,?,?,?,?,?,?)",
           (id,"frp",status,"node-ir-0001","node-ir-0001",
            "node-kh-0001",json.dumps(spec)))

    def test_active_shared_unique_lease(self):
        result=m._lease(self.binding,self.db)
        self.assertEqual(result["role"],"shared")
        self.assertEqual(result["state"],"active")

    def test_direct_no_child_lease(self):
        self.conn.execute("DELETE FROM frp_proxy_leases")
        self.conn.commit()
        self.binding.update(child="owner-0001",lease="owner-0001",port=45121)
        self.assertEqual(m._lease(self.binding,self.db)["role"],"direct")

    def test_shared_lease_missing_holds(self):
        self.conn.execute("DELETE FROM frp_proxy_leases");self.conn.commit()
        with self.assertRaises(m.LiveEvidenceHold):m._lease(self.binding,self.db)

    def test_wrong_lease_owner_holds(self):
        self.conn.execute("UPDATE frp_proxy_leases SET owner_tunnel_id='other-owner'")
        self.conn.commit()
        with self.assertRaises(m.LiveEvidenceHold):m._lease(self.binding,self.db)

    def test_inactive_owner_holds(self):
        self.conn.execute("UPDATE tunnels SET status='error' WHERE id='owner-0001'")
        self.conn.commit()
        with self.assertRaises(m.LiveEvidenceHold):m._lease(self.binding,self.db)

    def test_node_hmac_wire_format_exact(self):
        secret=b"a"*64
        with patch.object(m.time,"time",return_value=1000),patch.object(m.secrets,"token_hex",return_value="b"*32):
            h=m._signed_headers("node-ir-0001",secret,b'{"kind":"frps_owner","port":38658}')
        expected="\n".join(("smite-node-hmac-v1","node-ir-0001","POST",
            "/api/agent/approval/evidence","1000","b"*32,
            hashlib.sha256(b'{"kind":"frps_owner","port":38658}').hexdigest())).encode()
        self.assertEqual(h["X-Smite-Signature"],hmac.new(secret,expected,hashlib.sha256).hexdigest())

    def test_public_url_requires_https_443_or_ir_loopback(self):
        for url in ("http://example.com/api/agent/approval/evidence",
           "https://example.com:8443/api/agent/approval/evidence",
           "http://127.0.0.1:3333/api/agent/approval/evidence"):
            with self.subTest(url=url),self.assertRaises(m.LiveEvidenceHold):
                m._node_attestation({"node_id":"node-ir-0001","url":url,
                    "secret_path":"/nonexistent"},"frps_owner",38658)


    def test_missing_or_incompatible_lease_schema_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing=Path(tmp)/"stale.db"
            with sqlite3.connect(missing) as db:
                db.execute("CREATE TABLE tunnels(id TEXT)")
            with self.assertRaises(m.LiveEvidenceHold):
                m._lease(self.binding,missing)

    def test_current_committed_lease_change_is_seen_not_stale(self):
        self.assertEqual(m._lease(self.binding,self.db)["state"],"active")
        self.conn.execute("UPDATE frp_proxy_leases SET remote_port=39001")
        self.conn.commit()
        with self.assertRaises(m.LiveEvidenceHold):
            m._lease(self.binding,self.db)

    def test_expired_consistency_read_budget_holds(self):
        with patch.object(m.time,"monotonic",side_effect=[10.0,20.0]):
            with self.assertRaisesRegex(m.LiveEvidenceHold,"READ_TOO_OLD"):
                m._lease(self.binding,self.db,max_read_seconds=3)

    def test_untrusted_symlink_lease_source_holds(self):
        alias=self.db.with_name("alias.db")
        alias.symlink_to(self.db)
        with self.assertRaisesRegex(m.LiveEvidenceHold,"SOURCE_UNTRUSTED"):
            m._lease(self.binding,alias)

    def test_updated_owner_status_is_not_accepted_from_old_snapshot(self):
        self.assertEqual(m._lease(self.binding,self.db)["role"],"shared")
        self.conn.execute("UPDATE tunnels SET status='error' WHERE id='child-0001'")
        self.conn.commit()
        with self.assertRaisesRegex(m.LiveEvidenceHold,"STATUS_MISMATCH"):
            m._lease(self.binding,self.db)

if __name__=="__main__":
    unittest.main()
