"""Offline only: verify real Smite registry shape against Panel SQLite leases.

No Docker, no root keys, no network, no grant, no approval service, no live
host. This proves only deterministic equality of synthetic observations.
"""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1] / "modules"


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


ir=load("stage15_ir_registry", "smite-stage15-ir-host-observer.py")
leases=load("stage15_ir_lease", "smite-stage15-live-evidence.py")


class RegistryLeaseCompatibility(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db=Path(temp.name)/"panel.db"
        self.owner="123e4567-e89b-42d3-a456-426614174000"
        self.child="child-frp10"
        self.binding={
            "ir_node":"node-ir-0001","kh_node":"node-kh-0001",
            "owner":self.owner,"child":self.child,"lease":self.child,
            "port":38658,"path":"/38658/shop",
        }
        self.registry={self.owner:{"core":"frp","spec":{
            "mode":"server","bind_port":7000}}}
        with sqlite3.connect(self.db) as db:
            db.executescript("""CREATE TABLE tunnels(
                id TEXT PRIMARY KEY,core TEXT,status TEXT,node_id TEXT,
                iran_node_id TEXT,foreign_node_id TEXT,spec TEXT);
                CREATE TABLE frp_proxy_leases(
                tunnel_id TEXT PRIMARY KEY,owner_tunnel_id TEXT,
                iran_node_id TEXT,foreign_node_id TEXT,remote_port INTEGER,
                UNIQUE(iran_node_id,remote_port));""")
            db.execute("INSERT INTO tunnels VALUES (?,?,?,?,?,?,?)",
                      (self.owner,"frp","active","node-ir-0001",
                       "node-ir-0001","node-kh-0001",
                       json.dumps({"bind_port":7000})))
            db.execute("INSERT INTO tunnels VALUES (?,?,?,?,?,?,?)",
                      (self.child,"frp","active","node-ir-0001",
                       "node-ir-0001","node-kh-0001",
                       json.dumps({"mode":"client",
                                   "shared_frps_owner":self.owner})))
            db.execute("INSERT INTO frp_proxy_leases VALUES (?,?,?,?,?)",
                       (self.child,self.owner,
                        "node-ir-0001","node-kh-0001",38658))

    def assert_matched(self):
        raw=json.dumps(self.registry).encode()
        owner=ir.registry_owner(raw, expected_owner=self.binding["owner"])
        lease=leases._lease(self.binding,self.db)
        self.assertEqual(owner,self.binding["owner"])
        self.assertEqual(lease["owner"],owner)
        self.assertEqual(lease["lease"],self.child)
        self.assertEqual(lease["port"],38658)
        self.assertEqual(lease["role"],"shared")
        return lease

    def test_flat_node_registry_maps_to_unique_active_panel_lease(self):
        self.assert_matched()

    def test_panel_mode_absent_node_mode_server_is_the_valid_split(self):
        # Panel persists the operator's spec, Node persists the applied spec.
        # Explicit Node server mode is mandatory despite absent Panel mode.
        self.assert_matched()
        self.registry[self.owner]["spec"].pop("mode")
        with self.assertRaisesRegex(ir.ObserverHold,
                                    "IR_OWNER_REGISTRY_NOT_SINGLETON"):
            self.assert_matched()

    def test_explicit_contradictory_panel_mode_holds(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE tunnels SET spec=? WHERE id=?",
                       (json.dumps({"mode":"client", "bind_port":7000}),
                        self.owner))
        with self.assertRaisesRegex(leases.LiveEvidenceHold,
                                    "FRPS_OWNER_SPEC_MISMATCH"):
            self.assert_matched()

    def test_missing_panel_port_holds_even_with_valid_node_registry(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE tunnels SET spec=? WHERE id=?",
                       (json.dumps({}), self.owner))
        with self.assertRaisesRegex(leases.LiveEvidenceHold,
                                    "FRPS_OWNER_SPEC_MISMATCH"):
            self.assert_matched()

    def test_three_existing_routes_direct_plus_two_shared_leases(self):
        # The real field trial has a direct owner route at 45121, plus
        # separate KH child leases for 38658 and 28897. No child registry
        # entry is required on the IR Node. This is a synthetic DB only.
        child2="child-blog-002"
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO tunnels VALUES (?,?,?,?,?,?,?)",
                       (child2,"frp","active","node-ir-0001",
                        "node-ir-0001","node-kh-0001",
                        json.dumps({"shared_frps_owner":self.owner})))
            db.execute("INSERT INTO frp_proxy_leases VALUES (?,?,?,?,?)",
                       (child2,self.owner,"node-ir-0001","node-kh-0001",28897))
        self.assert_matched()  # 38658/shop shared
        blog={**self.binding,"child":child2,"lease":child2,
              "port":28897,"path":"/28897/blog"}
        self.assertEqual(leases._lease(blog,self.db)["role"],"shared")
        direct={**self.binding,"child":self.owner,"lease":self.owner,
                "port":45121,"path":"/45121/www"}
        self.assertEqual(leases._lease(direct,self.db)["role"],"direct")
        self.assertEqual(ir.registry_owner(json.dumps(self.registry).encode(),
                                          expected_owner=self.owner),self.owner)
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE frp_proxy_leases SET owner_tunnel_id=?"
                       " WHERE tunnel_id=?",("stale-owner",child2))
        with self.assertRaisesRegex(leases.LiveEvidenceHold,"SHARED_LEASE_CONFLICT"):
            leases._lease(blog,self.db)
        # The independent first child remains valid on that committed view.
        self.assert_matched()

    def test_direct_route_requires_no_proxy_lease_for_45121(self):
        direct={**self.binding,"child":self.owner,"lease":self.owner,
                "port":45121,"path":"/45121/www"}
        self.assertEqual(leases._lease(direct,self.db)["role"],"direct")
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO frp_proxy_leases VALUES (?,?,?,?,?)",
                       ("rogue",self.owner,"node-ir-0001","node-kh-0001",45121))
        with self.assertRaisesRegex(leases.LiveEvidenceHold,"DIRECT_LEASE_CONFLICT"):
            leases._lease(direct,self.db)

    def test_child_lease_is_in_panel_not_required_in_ir_registry(self):
        # Actual AdapterManager persists its local config. A KH-owned child
        # need not exist as a key in the IR Node's tunnels.json.
        self.assertEqual(set(self.registry),{self.owner})
        self.assert_matched()

    def test_friendly_name_is_not_an_internal_lease_owner(self):
        # A UI label must not be silently substituted for the UUID.
        self.binding["owner"] = "FRP-IR-KH-45121"
        with self.assertRaisesRegex(ir.ObserverHold,
                                    "IR_OWNER_REGISTRY_NOT_SINGLETON"):
            self.assert_matched()

    def test_wrong_owner_in_registry_holds(self):
        self.registry={"not-the-owner":self.registry[self.owner]}
        with self.assertRaisesRegex(ir.ObserverHold,"IR_OWNER_REGISTRY_NOT_SINGLETON"):
            self.assert_matched()

    def test_wrapper_assumption_is_explicitly_rejected(self):
        self.registry={"tunnels":self.registry}
        with self.assertRaisesRegex(ir.ObserverHold,"WRAPPER"):
            self.assert_matched()

    def test_mismatched_port_in_panel_lease_holds(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE frp_proxy_leases SET remote_port=38659")
        with self.assertRaisesRegex(leases.LiveEvidenceHold,"SHARED_LEASE_CONFLICT"):
            self.assert_matched()

    def test_wrong_child_to_owner_lease_holds(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE frp_proxy_leases SET owner_tunnel_id='unexpected'")
        with self.assertRaisesRegex(leases.LiveEvidenceHold,"SHARED_LEASE_CONFLICT"):
            self.assert_matched()

    def test_inactive_owner_holds(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE tunnels SET status='paused' WHERE id=?",(self.owner,))
        with self.assertRaisesRegex(leases.LiveEvidenceHold,
                                    "LEASE_IDENTITY_OR_STATUS_MISMATCH"):
            self.assert_matched()

    def test_mismatched_node_identity_holds(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE frp_proxy_leases SET foreign_node_id='other'")
        with self.assertRaisesRegex(leases.LiveEvidenceHold,"SHARED_LEASE_CONFLICT"):
            self.assert_matched()

    def test_missing_child_db_lease_holds(self):
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM frp_proxy_leases")
        with self.assertRaisesRegex(leases.LiveEvidenceHold,"SHARED_LEASE_CONFLICT"):
            self.assert_matched()

    def test_missing_node_owner_is_never_inferred_from_db_alone(self):
        self.registry.clear()
        with self.assertRaises(ir.ObserverHold):
            self.assert_matched()

    def test_no_install_or_grant_api_exposed(self):
        for source in ("smite-stage15-ir-host-observer.py",
                       "smite-stage15-live-evidence.py"):
            text=(ROOT/source).read_text()
            self.assertNotIn("docker restart",text)
        self.assertNotIn("install_grant", (ROOT/"smite-stage15-ir-host-observer.py").read_text())


if __name__=="__main__":
    unittest.main()
