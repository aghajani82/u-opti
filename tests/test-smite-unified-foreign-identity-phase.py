"""Disposable composition test: real existing client + promoter, simulated Panel.

These tests make no network requests, never run Docker and never alter hosts.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "trial_unified_foreign_identity_phase",
    ROOT/"modules"/"smite-unified-foreign-identity-phase.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class IdentityPhase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)/"foreign-fixture"
        self.base.mkdir(mode=0o700)
        self.stage = self.base/"foreign-staging"
        self.stage.mkdir(mode=0o700)
        self.packet = self.stage/"foreign-install-packet.json"
        self.live = self.base/"node-identity.json"
        self.state = self.base/"state.env"
        self.gateway = self.base/"foreign-gateway.env"
        self.env = self.base/"node.env"
        self.now = 1850000000
        self.doc = {
            "protocol": "smi1",
            "panel_url": "https://panel.example.com:443",
            "node_id": "foreign-node-1234",
            "node_name": "node-kh",
            "origin": "https://kh.example.com:443",
            "control_url": "https://kh.example.com:443/smite-node/"+"a"*32,
            "installation_code": "smi1_"+"b"*43,
            "expires_at": self.now+7200,
        }
        self.write_packet()
        self.write(self.state, (
            "SMITE_ROLE=foreign\n"
            "SMITE_MANAGED_VERSION=2.0.0-rc.7\n"
            "SMITE_CONNECTION_MODE=standard\n"
            "SMITE_NODE_NAME=node-kh\n"
            "SMITE_PANEL_DOMAIN=panel.example.com\n"
            "SMITE_FOREIGN_DOMAIN=kh.example.com\n"))
        self.write(self.gateway, (
            "SMITE_FOREIGN_GATEWAY_DOMAIN=kh.example.com\n"
            "SMITE_FOREIGN_PANEL_DOMAIN=panel.example.com\n"
            "SMITE_FOREIGN_CONTROL_PATH=/smite-node/"+"a"*32+"\n"
            "SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443\n"
            "SMITE_FOREIGN_GATEWAY_MODE=https-control-path\n"))
        self.write(self.env, (
            "PANEL_ADDRESS=panel.example.com:443\n"
            "SMITE_CONTROL_ADDRESS=https://kh.example.com/smite-node/"+"a"*32+"\n"
            "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
            "SMITE_AGENT_AUTH_MODE=strict\n"
            "SMITE_ENGINE_INVENTORY_MODE=managed\n"))
        self.calls = []
        self.secret = None
        self.lost_reply = False
        self.wrong_proof = False
        self.revoke = False

    def write(self, target, body):
        target.write_text(body)
        target.chmod(0o600)

    def write_packet(self):
        self.write(self.packet, json.dumps(self.doc, separators=(",",":")))

    def mock_panel(self, panel, endpoint, body, headers):
        self.assertEqual(panel, self.doc["panel_url"])
        self.calls.append(endpoint)
        parsed = json.loads(body)
        if endpoint == "/api/foreign-install/redeem":
            self.assertFalse(self.revoke)
            self.assertEqual(parsed["installation_code"], self.doc["installation_code"])
            self.assertEqual(parsed["node_id"], self.doc["node_id"])
            self.assertEqual(parsed["node_name"], self.doc["node_name"])
            self.assertEqual(parsed["control_url"], self.doc["control_url"])
            if self.secret is not None:
                self.assertEqual(self.secret, parsed["node_secret"])
            self.secret = parsed["node_secret"]
            if self.lost_reply:
                raise TimeoutError("simulate reply lost only")
            return {"status":"enrolled","node_id":self.doc["node_id"]}
        if endpoint != "/api/node-control/installation-status":
            raise AssertionError("Unexpected Panel API")
        if self.revoke or self.secret is None:
            raise module.Hold()
        self.assertEqual(parsed, {"node_id":self.doc["node_id"]})
        self.assertEqual(headers["X-Smite-Node-ID"],self.doc["node_id"])
        self.assertEqual(len(headers["X-Smite-Nonce"]),32)
        canonical = "\n".join((
            "smite-node-hmac-v1",self.doc["node_id"],"POST",endpoint,
            headers["X-Smite-Timestamp"],headers["X-Smite-Nonce"],
            hashlib.sha256(body).hexdigest())).encode()
        self.assertEqual(
            headers["X-Smite-Signature"],
            hmac.new(self.secret.encode(),canonical,"sha256").hexdigest())
        return {"status":"enrolled","node_id":self.doc["node_id"],
                "node_name": "different" if self.wrong_proof else self.doc["node_name"],
                "origin":"https://kh.example.com:443",
                "control_url":self.doc["control_url"]}

    def call(self, **overrides):
        kwargs=dict(
            packet_path=self.packet,state_path=self.state,
            gateway_path=self.gateway,node_env_path=self.env,
            directory=self.stage,live_identity=self.live,
            transport=self.mock_panel,now=self.now,
            disposable_capability=True)
        kwargs.update(overrides)
        return module.rehearse(**kwargs)

    def test_real_client_promotion_and_no_duplicate_redemption(self):
        result=self.call()
        self.assertEqual(result, {
            "phase":"IDENTITY_PROMOTED_OFFLINE",
            "node_id":self.doc["node_id"],"signed_panel_proof":"PASS",
            "runtime_activation":"NOT_PERFORMED","connected":False})
        secret=json.loads(self.live.read_text())["node_secret"]
        self.assertEqual(self.secret,secret)
        self.assertEqual(self.live.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.calls,[
            "/api/foreign-install/redeem",
            "/api/node-control/installation-status",
            "/api/node-control/installation-status",
        ])
        before=self.live.read_bytes()
        self.calls.clear()
        self.assertEqual(self.call()["connected"],False)
        self.assertEqual(self.calls,["/api/node-control/installation-status"])
        self.assertEqual(self.live.read_bytes(),before)
        self.assertTrue((self.stage/"foreign-install-promotion-prepared.json").is_file())
        self.assertTrue((self.stage/"foreign-install-promotion-completed.json").is_file())

    def test_lost_acknowledgement_preserves_one_key_across_retry(self):
        self.lost_reply=True
        self.assertEqual(self.call()["phase"],"IDENTITY_PROMOTED_OFFLINE")
        original=self.live.read_bytes()
        self.lost_reply=False
        self.calls.clear()
        self.assertEqual(self.call()["phase"],"IDENTITY_PROMOTED_OFFLINE")
        self.assertEqual(self.calls,["/api/node-control/installation-status"])
        self.assertEqual(original,self.live.read_bytes())

    def test_expired_code_only_prevents_new_redemption_not_existing_identity(self):
        self.call()
        self.calls.clear()
        self.assertEqual(self.call(now=self.doc["expires_at"]+300)["connected"],False)
        self.assertEqual(self.calls,["/api/node-control/installation-status"])

    def test_expired_new_code_blocks_without_network_or_identity(self):
        with self.assertRaises(module.Hold):self.call(now=self.doc["expires_at"]+1)
        self.assertFalse(self.calls)
        self.assertFalse(self.live.exists())

    def test_invalid_gateway_or_node_state_before_code_consumption(self):
        variants=[
            (self.gateway, "SMITE_FOREIGN_CONTROL_PATH=/smite-node/",
                           "SMITE_FOREIGN_CONTROL_PATH=/mismatch/"),
            (self.state,"SMITE_NODE_NAME=node-kh","SMITE_NODE_NAME=other"),
            (self.state,"SMITE_CONNECTION_MODE=standard","SMITE_CONNECTION_MODE=private"),
            (self.env,"SMITE_NODE_PANEL_AUTH_MODE=paused","SMITE_NODE_PANEL_AUTH_MODE=legacy"),
            (self.env,"SMITE_CONTROL_ADDRESS=https://kh.example.com","SMITE_CONTROL_ADDRESS=https://other.example.com"),
        ]
        for target, old, new in variants:
            before=target.read_text()
            self.write(target,before.replace(old,new))
            try:
                with self.subTest(target=str(target),old=old),self.assertRaises(module.Hold):
                    self.call()
                self.assertFalse(self.calls)
                self.assertFalse((self.stage/"foreign-install-identity.json").exists())
            finally:
                self.write(target,before)

    def test_missing_grant_wrong_domain_or_node_halts_without_network(self):
        before=self.doc.copy()
        for field,value in (
                ("origin","https://other.example.com:443"),
                ("node_name","other-node"),
                ("control_url","https://kh.example.com:443/smite-node/"+"c"*32),
                ("installation_code","invalid"),
                ("protocol","smn1")):
            self.doc[field]=value
            self.write_packet()
            with self.subTest(field=field),self.assertRaises(module.Hold):
                self.call()
            self.doc=before.copy()
            self.assertEqual(self.calls,[])
        self.write_packet()

    def test_live_existing_identity_without_signed_journal_holds(self):
        self.write(self.live,'{"version":1,"node_id":"foreign-node-1234","node_secret":"'+("a"*64)+'"}')
        before=self.live.read_bytes()
        with self.assertRaises(module.Hold):self.call()
        self.assertEqual(self.live.read_bytes(),before)
        self.assertEqual(self.calls,[])

    def test_revoked_or_invalid_signed_proof_retains_staged_secret(self):
        self.wrong_proof=True
        with self.assertRaises(module.Hold):self.call()
        staged=(self.stage/"foreign-install-identity.json").read_bytes()
        self.assertFalse(self.live.exists())
        self.wrong_proof=False
        self.calls.clear()
        self.assertEqual(self.call()["phase"],"IDENTITY_PROMOTED_OFFLINE")
        self.assertEqual(staged,(self.stage/"foreign-install-identity.json").read_bytes())
        self.revoke=True
        before=self.live.read_bytes()
        with self.assertRaises(module.Hold):self.call()
        self.assertEqual(before,self.live.read_bytes())

    def test_corrupt_promotion_receipt_never_replaces_identity(self):
        self.call()
        before=self.live.read_bytes()
        self.write(self.stage/"foreign-install-promotion-completed.json",'{}')
        self.calls.clear()
        with self.assertRaises(module.Hold):self.call()
        self.assertEqual(before,self.live.read_bytes())
        self.assertEqual(self.calls,["/api/node-control/installation-status"])

    def test_no_capability_or_wrong_fixture_boundaries(self):
        with self.assertRaises(module.Hold):
            self.call(disposable_capability=False)
        with self.assertRaises(module.Hold):
            self.call(live_identity=Path("/etc/u-opti/smite/identities/node-identity.json"))
        with self.assertRaises(module.Hold):
            self.call(packet_path=self.state)
        with self.assertRaises(module.Hold):
            self.call(transport=None)
        self.assertFalse(self.calls)
        self.assertFalse(self.live.exists())

    def test_rehearsal_requires_private_temp_ancestors(self):
        try:
            self.base.chmod(0o755)
            with self.assertRaises(module.Hold):self.call()
        finally:
            self.base.chmod(0o700)
        try:
            self.base.parent.chmod(0o755)
            with self.assertRaises(module.Hold):self.call()
        finally:
            self.base.parent.chmod(0o700)
        self.assertFalse(self.calls)
        self.assertFalse(self.live.exists())

    def tx(self, **overrides):
        params = dict(packet_path=self.packet, state_path=self.state,
                      gateway_path=self.gateway, node_env_path=self.env,
                      directory=self.stage, live_identity=self.live,
                      transport=self.mock_panel, now=self.now,
                      disposable_capability=True)
        params.update(overrides)
        return module.rehearse_transaction(**params)

    def journal(self):
        return self.stage/"unified-foreign-transaction.json"

    def test_operation_journal_commits_same_identity_without_secrets(self):
        result=self.tx()
        self.assertEqual(result["phase"],"IDENTITY_PROMOTED_OFFLINE")
        self.assertEqual(result["journal"],"IDENTITY_PROMOTED_OFFLINE")
        self.assertIs(result["activation_allowed"],False)
        self.assertIs(result["connected"],False)
        receipt=json.loads(self.journal().read_text())
        self.assertEqual(receipt["phase"],"IDENTITY_PROMOTED_OFFLINE")
        self.assertEqual(receipt["node_id"],self.doc["node_id"])
        self.assertEqual(receipt["packet_sha256"],hashlib.sha256(
            self.packet.read_bytes()).hexdigest())
        self.assertNotIn("installation_code",self.journal().read_text())
        self.assertNotIn("node_secret",self.journal().read_text())
        self.assertNotIn(self.doc["installation_code"],self.journal().read_text())
        self.assertEqual(self.journal().stat().st_mode & 0o777,0o600)
        self.assertTrue((self.stage/"unified-foreign-transaction.lock").exists())
        self.assertEqual((self.stage/"unified-foreign-transaction.lock").stat().st_mode & 0o777,0o600)

    def test_completed_transaction_recheck_uses_signed_proof_only(self):
        self.tx()
        original=self.live.read_bytes()
        self.calls.clear()
        self.assertEqual(self.tx()["phase"],"IDENTITY_PROMOTED_OFFLINE")
        self.assertEqual(self.calls,["/api/node-control/installation-status"])
        self.assertEqual(original,self.live.read_bytes())
        self.revoke=True
        with self.assertRaises(module.Hold):self.tx()
        self.assertEqual(original,self.live.read_bytes())
        self.assertEqual(json.loads(self.journal().read_text())["phase"],
                         "IDENTITY_PROMOTED_OFFLINE")

    def test_process_interruption_leaves_intent_and_recovers_no_rekey(self):
        def interrupted(panel,endpoint,body,headers):
            result=self.mock_panel(panel,endpoint,body,headers)
            if endpoint=="/api/foreign-install/redeem":
                raise KeyboardInterrupt("simulated crash after server committed")
            return result
        with self.assertRaises(KeyboardInterrupt):
            self.tx(transport=interrupted)
        self.assertEqual(json.loads(self.journal().read_text())["phase"],"INTENT")
        saved=json.loads((self.stage/"foreign-install-identity.json").read_text())["node_secret"]
        self.calls.clear()
        outcome=self.tx()
        self.assertEqual(outcome["journal"],"IDENTITY_PROMOTED_OFFLINE")
        self.assertEqual(self.secret,saved)
        self.assertEqual(json.loads(self.live.read_text())["node_secret"],saved)
        self.assertEqual(self.calls[0],"/api/foreign-install/redeem")

    def test_failed_signed_proof_retains_intent_and_same_staged_key(self):
        self.wrong_proof=True
        with self.assertRaises(module.Hold):self.tx()
        self.assertEqual(json.loads(self.journal().read_text())["phase"],"INTENT")
        staged=(self.stage/"foreign-install-identity.json").read_bytes()
        self.assertFalse(self.live.exists())
        self.wrong_proof=False
        self.calls.clear()
        self.assertEqual(self.tx()["journal"],"IDENTITY_PROMOTED_OFFLINE")
        self.assertEqual((self.stage/"foreign-install-identity.json").read_bytes(),staged)

    def test_journal_corruption_refuses_any_new_proof_or_rekey(self):
        self.tx()
        original=self.live.read_bytes()
        self.journal().write_text("{}")
        self.journal().chmod(0o600)
        self.calls.clear()
        with self.assertRaises(module.Hold):self.tx()
        self.assertEqual(self.calls,[])
        self.assertEqual(original,self.live.read_bytes())

    def test_changed_code_after_interruption_cannot_be_adopted(self):
        self.wrong_proof=True
        with self.assertRaises(module.Hold):self.tx()
        self.wrong_proof=False
        self.doc["installation_code"]="smi1_"+"c"*43
        self.write_packet()
        self.calls.clear()
        with self.assertRaises(module.Hold):self.tx()
        self.assertEqual(self.calls,[])
        self.assertFalse(self.live.exists())

    def test_parallel_transaction_lock_does_not_consume_a_code(self):
        lock=self.stage/"unified-foreign-transaction.lock"
        with open(lock,"wb") as handle:
            handle.flush()
            fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(module.Hold):self.tx()
            self.assertFalse(self.journal().exists())
            self.assertFalse(self.calls)
        self.assertEqual(self.tx()["journal"],"IDENTITY_PROMOTED_OFFLINE")

    def test_unsafe_disposable_root_refuses_even_to_create_lock(self):
        self.base.chmod(0o755)
        try:
            with self.assertRaises(module.Hold):self.tx()
            self.assertFalse((self.stage/"unified-foreign-transaction.lock").exists())
        finally:
            self.base.chmod(0o700)
        with self.assertRaises(module.Hold):
            self.tx(directory=Path("/etc/u-opti/smite/foreign-staging"))
        self.assertFalse(self.calls)

    def test_cli_has_no_production_execution(self):
        executable=ROOT/"modules"/"smite-unified-foreign-identity-phase.py"
        result=subprocess.run([sys.executable,"-B",str(executable),"--status"],
                              capture_output=True,text=True,check=True)
        self.assertIn("PRODUCTION_REDEEM_AND_PROMOTION=NOT_AUTHORIZED",result.stdout)
        self.assertIn("FOREIGN_CONNECTED=NOT_PROVEN",result.stdout)
        result=subprocess.run([sys.executable,"-B",str(executable),"--activate"],
                              capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.calls)


if __name__=="__main__":
    unittest.main(verbosity=2)
