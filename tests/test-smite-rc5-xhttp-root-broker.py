#!/usr/bin/env python3
"""Offline IR-only local broker regression; root-owned temp paths, fake apply."""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

MODULE = Path(__file__).resolve().parents[1] / "modules" / "smite-rc5-xhttp-root-broker.py"
spec = importlib.util.spec_from_file_location("uopti_minimal_xhttp_broker_test", MODULE)
broker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = broker
spec.loader.exec_module(broker)
ledger = broker._ledger_module()
contract = broker._contract_module()

KEY_VALUE = bytes(range(32))
NOW = 1_798_000_000
PEER_UID, PEER_GID = 1347, 1348
INSTANCE = "broker-ir-0001"


def claim(nonce="c"*32):
    return {
        "schema": 1, "audience": contract.AUDIENCE, "action": "create",
        "ir_node": "node-ir-0001", "kh_node": "node-kh-0001",
        "owner": "trial-frp-45121", "child": "trial-frp-49328",
        "lease": "lease-49328-00001", "port": 49328, "path": "/49328/sso",
        "owner_proof_sha256": "a"*64, "kh_inventory_sha256": "b"*64,
        "issued_at": NOW, "expires_at": NOW + 30, "nonce": nonce,
    }


def signed(body):
    mac = hmac.new(KEY_VALUE, contract.canonical(body), hashlib.sha256).hexdigest()
    return contract.canonical({**body, "mac": mac})


class BrokerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.geteuid(), 0)
        tmp = tempfile.TemporaryDirectory(prefix="uopti-broker-ipc-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        paths = {
            "CONFIG": self.root / "conf"/"route-broker.json",
            "KEY": self.root/"conf"/"route-broker.key",
            "GRANTS": self.root/"grants",
            "LEDGER": self.root/"ledger"/"nonce.db",
            "ENGINE_LOCK": self.root/"engine.lock",
            "HELPER": self.root/"bin"/"smite-xhttp-nginx-route",
            "PLANNER": self.root/"bin"/"smite_xhttp_nginx_plan.py",
            "SOCKET": self.root/"uds"/"xhttp-broker.sock",
        }
        for name, path in paths.items():
            patcher = patch.object(broker, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        for directory in ("conf", "grants", "ledger", "bin", "uds"):
            p = self.root/directory
            p.mkdir(mode=0o755 if directory == "bin" else 0o700)
        broker.KEY.write_bytes(KEY_VALUE)
        broker.KEY.chmod(0o600)
        for path, body in (
            (broker.HELPER, b"#!/bin/sh\nexit 99\n"),
            (broker.PLANNER, b"# Offline fake planner\n"),
        ):
            path.write_bytes(body)
            path.chmod(0o755)
        conf = {
            "schema": 1, "instance_id": INSTANCE,
            "peer_uid": PEER_UID, "peer_gid": PEER_GID,
            "helper_sha256": hashlib.sha256(broker.HELPER.read_bytes()).hexdigest(),
            "planner_sha256": hashlib.sha256(broker.PLANNER.read_bytes()).hexdigest(),
        }
        broker.CONFIG.write_text(json.dumps(conf, sort_keys=True))
        broker.CONFIG.chmod(0o600)
        self.grant = claim()
        self._put_grant(self.grant)
        ledger.DurableNonceLedger.bootstrap_new(
            broker.LEDGER, instance_id=INSTANCE
        )
        self._calls = []
        patches = [
            patch.object(broker.os, "uname",
                         return_value=SimpleNamespace(nodename="ir")),
            patch.object(broker.time, "time", return_value=NOW + 1),
            patch.object(broker, "_verify_bridge", return_value=None),
            patch.object(broker, "_apply_route",
                         side_effect=lambda p, path: self._calls.append((p,path))),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def _put_grant(self, approved):
        data = {k:v for k,v in approved.items() if k in (
            "ir_node", "kh_node", "owner", "child", "lease",
            "port", "path", "owner_proof_sha256", "kh_inventory_sha256",
        )}
        data["schema"] = 1
        path = broker.GRANTS/f'{approved["child"]}.json'
        path.write_text(json.dumps(data, sort_keys=True))
        path.chmod(0o600)

    def accept(self, body=None, **opts):
        return broker.process(
            signed(body or claim()),
            peer_uid=opts.get("uid", PEER_UID),
            peer_gid=opts.get("gid", PEER_GID),
        )

    def test_only_approved_peer_binding_and_once_nonce_calls_root_helper(self):
        self.assertEqual(self.accept(), "PASS_ROUTE_ADDED")
        self.assertEqual(self._calls, [(49328, "/49328/sso")])
        with self.assertRaises(ledger.LedgerHold):
            self.accept()
        self.assertEqual(len(self._calls), 1)

    def test_root_node_container_requires_exact_dedicated_group(self):
        conf = json.loads(broker.CONFIG.read_text())
        conf["peer_uid"] = 0
        conf["peer_gid"] = PEER_GID
        broker.CONFIG.write_text(json.dumps(conf, sort_keys=True))
        broker.CONFIG.chmod(0o600)
        self.assertEqual(self.accept(uid=0, gid=PEER_GID), "PASS_ROUTE_ADDED")
        self.assertEqual(self._calls, [(49328, "/49328/sso")])

        conf["peer_gid"] = 0
        broker.CONFIG.write_text(json.dumps(conf, sort_keys=True))
        broker.CONFIG.chmod(0o600)
        with self.assertRaises(broker.BrokerHold):
            self.accept(uid=0, gid=0)

    def test_invalid_peers_fail_before_ledger_or_host_actions(self):
        for opts in ({"uid":0},{"uid":PEER_UID+1},{"gid":PEER_GID+1}):
            with self.subTest(opts=opts), self.assertRaises(broker.BrokerHold):
                self.accept(**opts)
        self.assertEqual(self._calls, [])
        self.assertEqual(self.accept(), "PASS_ROUTE_ADDED")

    def test_unauthorized_child_port_path_or_evidence_rejected(self):
        for key,value in (
            ("port",52000),("path","/49328/www"),
            ("lease","lease-49328-00002"),
            ("owner_proof_sha256","d"*64),
            ("kh_inventory_sha256","e"*64),
            ("child","trial-frp-52000"),
        ):
            with self.subTest(key=key), self.assertRaises((broker.BrokerHold,contract.IntentHold)):
                self.accept({**claim(), key:value})
        self.assertEqual(self._calls, [])

    def test_bad_hmac_and_expiry_fail_closed(self):
        tamper = signed(claim()).replace(b'"port":49328', b'"port":52000')
        with self.assertRaises(contract.IntentHold):
            broker.process(tamper, peer_uid=PEER_UID, peer_gid=PEER_GID)
        with patch.object(broker.time, "time", return_value=NOW+31):
            with self.assertRaises(contract.IntentHold):
                self.accept()
        self.assertEqual(self._calls, [])

    def test_missing_key_grant_and_pinned_helper_abort_before_nonce(self):
        broker.KEY.unlink()
        with self.assertRaises(broker.BrokerHold):
            self.accept()
        broker.KEY.write_bytes(KEY_VALUE)
        broker.KEY.chmod(0o600)
        broker.HELPER.write_bytes(b"changed binary\n")
        with self.assertRaises(broker.BrokerHold):
            self.accept()
        broker.HELPER.write_bytes(b"#!/bin/sh\nexit 99\n")
        broker.HELPER.chmod(0o755)
        (broker.GRANTS/"trial-frp-49328.json").unlink()
        with self.assertRaises(broker.BrokerHold):
            self.accept()
        self._put_grant(claim())
        self.assertEqual(self.accept(), "PASS_ROUTE_ADDED")

    def test_untrusted_worker_directory_denies_before_nonce(self):
        broker.HELPER.parent.chmod(0o777)
        with self.assertRaises(broker.BrokerHold):
            self.accept()
        self.assertEqual(self._calls, [])
        broker.HELPER.parent.chmod(0o755)
        self.assertEqual(self.accept(), "PASS_ROUTE_ADDED")

    def test_missing_ledger_cannot_auto_repair_or_trigger_tool(self):
        broker.LEDGER.unlink()
        with self.assertRaises(ledger.LedgerHold):
            self.accept()
        self.assertFalse(broker.LEDGER.exists())
        self.assertEqual(self._calls, [])

    def test_unavailable_bridge_prevents_consume(self):
        with patch.object(broker, "_verify_bridge", side_effect=broker.BrokerHold("BRIDGE_MISSING")):
            with self.assertRaises(broker.BrokerHold):
                self.accept()
        self.assertEqual(self._calls, [])
        self.assertEqual(self.accept(), "PASS_ROUTE_ADDED")

    def test_failed_route_is_consumed_then_hold_no_automatic_retry(self):
        with patch.object(broker,"_apply_route", side_effect=RuntimeError("fake failure")):
            with self.assertRaisesRegex(broker.BrokerHold, "HOLD_RECONCILE_NO_RETRY"):
                self.accept()
        with self.assertRaises(ledger.LedgerHold):
            self.accept()
        self.assertEqual(self._calls, [])

    def test_unix_frame_is_exact_bounded_and_rejects_extra_data(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        data = signed(claim())
        left.sendall(data+b"\n")
        self.assertEqual(broker._receive(right), data)
        left.sendall(data+b"\nmore")
        with self.assertRaises(broker.BrokerHold):
            broker._receive(right)
        left.sendall(b"x"*(broker.MAX_INPUT+1)+b"\n")
        with self.assertRaises(broker.BrokerHold):
            broker._receive(right)

    def test_service_keeps_root_exec_and_public_ports_unavailable(self):
        source = MODULE.read_text()
        self.assertNotIn("shell=True", source)
        self.assertNotIn("AF_INET", source)
        self.assertNotIn("sudo ", source)
        self.assertFalse(broker.SOCKET.exists())


if __name__ == "__main__":
    unittest.main()
