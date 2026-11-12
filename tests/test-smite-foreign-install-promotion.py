"""Offline no-activation tests for foreign identity promotion."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "modules" / filename)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


client = load("foreign_client_for_promotion", "smite-foreign-install-client.py")
promoter = load("foreign_promotion", "smite-foreign-install-promotion.py")


class Promotion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.staged = self.root / "staged"
        self.staged.mkdir(mode=0o700)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.live = self.runtime / "node-identity.json"
        self.state = self.root / "state.env"
        self.gateway = self.root / "gateway.env"
        self.env = self.root / "node.env"
        self.now = 1850000000
        self.packet = {"protocol": "smi1", "panel_url": "https://panel.example.com",
                       "node_id": "foreign-node-1234", "node_name": "node-kh",
                       "origin": "https://kh.example.com:443",
                       "control_url": "https://kh.example.com:443/smite-node/" + "a"*32,
                       "installation_code": "smi1_" + "b"*43,
                       "expires_at": self.now+7200}
        self.write_config()

    def write(self, path, body):
        path.write_text(body)
        path.chmod(0o600)

    def write_config(self):
        self.write(self.state, "SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\nSMITE_NODE_NAME=node-kh\nSMITE_PANEL_DOMAIN=panel.example.com\n")
        self.write(self.gateway, "SMITE_FOREIGN_GATEWAY_DOMAIN=kh.example.com\nSMITE_FOREIGN_PANEL_DOMAIN=panel.example.com\nSMITE_FOREIGN_CONTROL_PATH=/smite-node/" + "a"*32 + "\nSMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443\nSMITE_FOREIGN_GATEWAY_MODE=https-control-path\n")
        self.write(self.env, "PANEL_ADDRESS=panel.example.com:443\nSMITE_CONTROL_ADDRESS=https://kh.example.com/smite-node/" + "a"*32 + "\nSMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_AGENT_AUTH_MODE=strict\nSMITE_ENGINE_INVENTORY_MODE=managed\n")

    def network(self, panel, target, body, headers):
        self.assertEqual(panel, "https://panel.example.com:443")
        record = json.loads((self.staged / "foreign-install-identity.json").read_text())
        if target == client.REDEEM:
            self.assertEqual(json.loads(body)["node_secret"], record["node_secret"])
            return {"status": "enrolled", "node_id": self.packet["node_id"]}
        self.assertEqual(target, client.STATUS)
        self.assertNotIn(record["node_secret"].encode(), body)
        self.assertEqual(headers["X-Smite-Node-ID"], self.packet["node_id"])
        return {"status": "enrolled", **{
            k: self.packet[k] for k in ("node_id", "node_name", "origin", "control_url")}}

    def stage(self):
        return client.enroll(json.dumps(self.packet), directory=self.staged,
                             live_identity=self.live, now=self.now, transport=self.network)

    def promote(self, **overrides):
        kwargs = dict(client=client, directory=self.staged, live_identity=self.live,
                      state_path=self.state, gateway_path=self.gateway,
                      node_env_path=self.env, transport=self.network, now=self.now)
        kwargs.update(overrides)
        return promoter.promote(json.dumps(self.packet), **kwargs)

    def test_success_exact_identity_no_activation_and_retry(self):
        self.stage()
        self.assertEqual(self.promote()["runtime_activation"], "not_performed")
        first = self.live.read_bytes()
        staged = json.loads((self.staged / "foreign-install-identity.json").read_text())
        self.assertEqual(json.loads(first), {"version":1, "node_id":self.packet["node_id"],
                                            "node_secret":staged["node_secret"]})
        self.assertEqual(self.live.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.promote()["status"], "identity_promoted")
        self.assertEqual(self.live.read_bytes(), first)
        self.assertEqual(len(list(self.runtime.glob("node-identity.json"))), 1)
        self.assertTrue((self.staged / "foreign-install-promotion-prepared.json").exists())
        self.assertTrue((self.staged / "foreign-install-promotion-completed.json").exists())

    def test_expired_code_does_not_block_signed_promotion(self):
        self.stage()
        self.packet["expires_at"] = self.now - 20
        self.assertEqual(self.promote()["status"], "identity_promoted")

    def test_no_stage_no_promotion(self):
        with self.assertRaises(promoter.Hold): self.promote()
        self.assertFalse(self.live.exists())

    def test_existing_runtime_even_with_same_secret_without_receipt_denied(self):
        self.stage()
        staged = json.loads((self.staged / "foreign-install-identity.json").read_text())
        self.write(self.live, json.dumps({"version":1,"node_id":self.packet["node_id"],
                                         "node_secret":staged["node_secret"]}))
        with self.assertRaises(promoter.Hold): self.promote()
        self.assertFalse((self.staged / "foreign-install-promotion-prepared.json").exists())

    def test_mismatched_gateway_config_is_fail_closed(self):
        self.stage()
        variants = [(self.state, "SMITE_NODE_NAME=node-kh", "SMITE_NODE_NAME=other"),
                    (self.gateway, "SMITE_FOREIGN_CONTROL_PATH=/smite-node/", "SMITE_FOREIGN_CONTROL_PATH=/wrong/"),
                    (self.env, "SMITE_NODE_PANEL_AUTH_MODE=paused", "SMITE_NODE_PANEL_AUTH_MODE=legacy"),
                    (self.env, "SMITE_CONTROL_ADDRESS=https://kh.example.com", "SMITE_CONTROL_ADDRESS=https://other.example.com")]
        for target, old, new in variants:
            original = target.read_text()
            target.write_text(original.replace(old, new))
            try:
                with self.assertRaises(promoter.Hold): self.promote()
                self.assertFalse(self.live.exists())
            finally:
                target.write_text(original)

    def test_bad_proof_does_not_write_identity(self):
        self.stage()
        def bad(*args):
            result = self.network(*args)
            if args[1] == client.STATUS: result["node_name"] = "wrong"
            return result
        with self.assertRaises(promoter.Hold): self.promote(transport=bad)
        self.assertFalse(self.live.exists())
        self.assertFalse((self.staged / "foreign-install-promotion-prepared.json").exists())

    def test_prepared_interrupted_before_link_resumes(self):
        self.stage()
        original = promoter.write_once
        def lost(fd, name, data):
            if name == "node-identity.json":
                raise OSError("simulated interruption")
            return original(fd, name, data)
        with patch.object(promoter, "write_once", side_effect=lost):
            with self.assertRaises(promoter.Hold): self.promote()
        self.assertTrue((self.staged / "foreign-install-promotion-prepared.json").exists())
        self.assertFalse(self.live.exists())
        self.assertEqual(self.promote()["status"], "identity_promoted")

    def test_live_link_completed_but_done_marker_missing_resumes(self):
        self.stage()
        original = promoter.write_once
        def lost(fd, name, data):
            if name == "foreign-install-promotion-completed.json":
                raise OSError("simulated interruption")
            return original(fd, name, data)
        with patch.object(promoter, "write_once", side_effect=lost):
            with self.assertRaises(promoter.Hold): self.promote()
        saved = self.live.read_bytes()
        self.promote()
        self.assertEqual(saved, self.live.read_bytes())

    def test_completed_receipt_missing_live_refuses_resurrection(self):
        self.stage()
        self.promote()
        self.live.unlink()
        with self.assertRaises(promoter.Hold): self.promote()
        self.assertFalse(self.live.exists())

    def test_corrupted_journal_does_not_replace(self):
        self.stage()
        self.promote()
        original = self.live.read_bytes()
        target = self.staged / "foreign-install-promotion-prepared.json"
        target.write_text("{}")
        with self.assertRaises(promoter.Hold): self.promote()
        self.assertEqual(self.live.read_bytes(), original)

    def test_untrusted_files_and_symlinks_refused(self):
        self.stage()
        self.env.chmod(0o644)
        with self.assertRaises(promoter.Hold): self.promote()
        self.env.chmod(0o600)
        link = self.root / "linked"
        link.symlink_to(self.runtime, target_is_directory=True)
        with self.assertRaises(promoter.Hold):
            self.promote(live_identity=link/"node-identity.json")
        self.assertFalse(self.live.exists())

    def test_promotion_scope_change_does_not_rotate(self):
        self.stage()
        self.promote()
        original = self.live.read_bytes()
        self.packet["control_url"] = "https://kh.example.com:443/smite-node/" + "c"*32
        with self.assertRaises(promoter.Hold): self.promote()
        self.assertEqual(self.live.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
