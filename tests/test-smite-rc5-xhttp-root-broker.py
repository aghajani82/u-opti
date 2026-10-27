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
import stat
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


class PinnedSmiteRouteWorkerTests(unittest.TestCase):
    def test_installer_stages_exact_reviewed_worker_and_planner_bytes(self):
        root = Path(__file__).resolve().parents[1]
        expected = {
            "modules/smite-xhttp-nginx-route":
                "acb66752f6aa8600f1c45a7d68f46006b0d4d26c55330925bd35359d3ca868e6",
            "modules/smite_xhttp_nginx_plan.py":
                "0c007ca049b95227588d2e4847020a53d5d0c155d28dc537341367a783d81c19",
        }
        installer = (root / "install.sh").read_text()
        required_runtime = (
            "smite-rc5-xhttp-root-broker.py",
            "smite-rc5-xhttp-nonce-ledger.py",
            "smite-rc5-xhttp-signed-intent.py",
            "smite-rc5-xhttp-bridge-install.py",
            "smite-rc5-xhttp-bridge-admission.py",
            "smite-rc5-xhttp-broker-provision.py",
        )
        for module in required_runtime:
            with self.subTest(module=module):
                self.assertTrue((root / "modules" / module).is_file())
                self.assertIn(f'"{module}"', installer)
        self.assertIn("broker provision/activation helper (staged)", installer)
        for relative, digest in expected.items():
            with self.subTest(relative=relative):
                path = root / relative
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                self.assertIn(f'"{Path(relative).name}"', installer)

        worker_path = root / "modules/smite-xhttp-nginx-route"
        planner_path = root / "modules/smite_xhttp_nginx_plan.py"
        compile(worker_path.read_text(), str(worker_path), "exec")
        compile(planner_path.read_text(), str(planner_path), "exec")
        worker = worker_path.read_text()
        self.assertIn("from smite_xhttp_nginx_plan import", worker)
        self.assertIn('parser.add_argument("--port"', worker)
        self.assertIn('parser.add_argument("--path"', worker)
        self.assertIn('parser.add_argument("--apply"', worker)
        self.assertIn('parser.add_argument("--confirm-local-root"', worker)
        self.assertIn("RESULT=PASS_LOCAL_NGINX_ROUTE_CREATED", worker)


class InertBrokerProvisioningTests(unittest.TestCase):
    def test_provisions_root_owned_inert_files_without_enabling_service(self):
        import importlib.util

        repo = Path(__file__).resolve().parents[1]
        source_dir = repo / "modules"
        provisioner_path = source_dir / "smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_provisioner_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(provisioner)

        with tempfile.TemporaryDirectory(prefix="uopti-broker-provision-") as raw_root:
            root = Path(raw_root)
            root.chmod(0o700)
            nginx_config = root / "etc/nginx"
            nginx_config.mkdir(parents=True, mode=0o755)
            nginx_config.chmod(0o755)
            target_modules = root / "usr/local/lib/u-opti/modules"
            target_modules.mkdir(parents=True, mode=0o755)
            target_modules.chmod(0o755)
            broker_target = target_modules / "smite-rc5-xhttp-root-broker.py"
            broker_target.write_bytes((source_dir / broker_target.name).read_bytes())
            broker_target.chmod(0o644)

            result = provisioner.provision(
                peer_gid=PEER_GID, root=root, source_dir=source_dir,
                instance_id=INSTANCE,
            )
            etc = root / "etc/u-opti/smite"
            state = root / "var/lib/u-opti/smite-xhttp-broker"
            grants = etc / "route-grants"
            helper = root / "usr/local/libexec/smite-xhttp-nginx-route"
            planner = root / "usr/local/libexec/smite_xhttp_nginx_plan.py"
            service = root / "etc/systemd/system/u-opti-smite-xhttp-broker.service"

            self.assertEqual(result["BROKER_PROVISIONING"], "PASS_INERT")
            self.assertEqual(result["TRUSTED_GRANTS"], "NONE")
            self.assertEqual(result["SERVICE_UNIT"], "INSTALLED_NOT_ENABLED")
            self.assertEqual(result["SERVICE_START"], "NOT_PERFORMED")
            self.assertEqual(result["NODE_ENABLEMENT"], "NOT_PERFORMED")
            self.assertEqual(result["LIVE_ROUTE_CHANGE"], "NO")
            route_dir = root / "etc/nginx/smite-xhttp-routes"
            self.assertTrue(route_dir.is_dir())
            self.assertEqual(stat.S_IMODE(route_dir.stat().st_mode), 0o755)
            self.assertEqual(route_dir.stat().st_uid, 0)
            self.assertEqual(list(grants.iterdir()), [])
            self.assertEqual(len((etc / "route-broker.key").read_bytes()), 32)
            self.assertEqual(stat.S_IMODE((etc / "route-broker.key").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((etc / "route-broker.json").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((state / "nonce.db").stat().st_mode), 0o600)
            self.assertEqual(hashlib.sha256(helper.read_bytes()).hexdigest(),
                             provisioner.HELPER_SHA256)
            self.assertEqual(hashlib.sha256(planner.read_bytes()).hexdigest(),
                             provisioner.PLANNER_SHA256)
            unit = service.read_text()
            self.assertIn("Group=1348", unit)
            self.assertIn("Restart=on-failure", unit)
            self.assertLess(unit.index("StartLimitIntervalSec=60s"), unit.index("[Service]"))
            self.assertLess(unit.index("StartLimitBurst=3"), unit.index("[Service]"))
            self.assertIn("NoNewPrivileges=yes", unit)
            self.assertIn("ReadWritePaths=/etc/nginx/smite-xhttp-routes", unit)
            self.assertIn("ReadWritePaths=-/run/lock/u-opti-smite-engine.lock", unit)
            self.assertIn("ReadWritePaths=-/run/lock/smite-xhttp-nginx-route.lock", unit)
            self.assertIn("smite-rc5-xhttp-root-broker.py --serve", unit)

            key_before = (etc / "route-broker.key").read_bytes()
            with self.assertRaises(provisioner.ProvisionHold):
                provisioner.provision(
                    peer_gid=PEER_GID, root=root, source_dir=source_dir,
                    instance_id=INSTANCE,
                )
            self.assertEqual((etc / "route-broker.key").read_bytes(), key_before)

    def test_missing_nginx_config_dir_holds_before_any_filesystem_change(self):
        import importlib.util

        repo = Path(__file__).resolve().parents[1]
        provisioner_path = repo / "modules/smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_provisioner_missing_nginx_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(provisioner)
        with tempfile.TemporaryDirectory(prefix="uopti-broker-no-nginx-") as raw_root:
            root = Path(raw_root)
            root.chmod(0o700)
            with self.assertRaisesRegex(provisioner.ProvisionHold,
                                        "NGINX_CONFIG_DIRECTORY_MISSING"):
                provisioner.provision(
                    peer_gid=PEER_GID, root=root, source_dir=repo / "modules"
                )
            self.assertEqual(list(root.iterdir()), [])

    def test_bad_peer_gid_holds_before_any_filesystem_change(self):
        import importlib.util

        repo = Path(__file__).resolve().parents[1]
        provisioner_path = repo / "modules/smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_provisioner_gid_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(provisioner)
        with tempfile.TemporaryDirectory(prefix="uopti-broker-bad-gid-") as raw_root:
            root = Path(raw_root)
            root.chmod(0o700)
            with self.assertRaises(provisioner.ProvisionHold):
                provisioner.provision(peer_gid=0, root=root, source_dir=repo / "modules")
            self.assertEqual(list(root.iterdir()), [])

    def test_explicit_activation_enables_persistent_unit_and_verifies_socket(self):
        repo = Path(__file__).resolve().parents[1]
        source_dir = repo / "modules"
        provisioner_path = source_dir / "smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_activation_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = provisioner
        spec.loader.exec_module(provisioner)

        with tempfile.TemporaryDirectory(prefix="uopti-broker-activation-") as raw_root:
            root = Path(raw_root)
            root.chmod(0o700)
            nginx_config = root / "etc/nginx"
            nginx_config.mkdir(parents=True, mode=0o755)
            nginx_config.chmod(0o755)
            target_modules = root / "usr/local/lib/u-opti/modules"
            target_modules.mkdir(parents=True, mode=0o755)
            target_modules.chmod(0o755)
            broker_target = target_modules / "smite-rc5-xhttp-root-broker.py"
            broker_target.write_bytes((source_dir / broker_target.name).read_bytes())
            broker_target.chmod(0o644)
            provisioner.provision(peer_gid=PEER_GID, root=root, source_dir=source_dir,
                                  instance_id=INSTANCE)

            # Reproduce the exact old unit emitted before missing lock paths
            # were made optional for systemd namespace setup.
            service = root / "etc/systemd/system" / provisioner.SERVICE_NAME
            legacy_unit = service.read_text().replace(
                "ReadWritePaths=-/run/lock/u-opti-smite-engine.lock",
                "ReadWritePaths=/run/lock/u-opti-smite-engine.lock",
            ).replace(
                "ReadWritePaths=-/run/lock/smite-xhttp-nginx-route.lock",
                "ReadWritePaths=/run/lock/smite-xhttp-nginx-route.lock",
            )
            service.write_text(legacy_unit)
            service.chmod(0o644)

            calls = []
            def fake_systemctl(argv, **kwargs):
                calls.append(tuple(argv[1:]))
                if argv[0] == "getent":
                    return SimpleNamespace(returncode=0,
                                           stdout="u-opti-smite-peer:x:1348:\n",
                                           stderr="")
                action = argv[1]
                if action == "start":
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                if action == "is-enabled":
                    return SimpleNamespace(returncode=0, stdout="enabled\n", stderr="")
                if action == "is-active":
                    return SimpleNamespace(returncode=0, stdout="active\n", stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            # Simulate an interrupted legacy install where the unit already
            # references the route path but the directory was never provisioned.
            route_dir = root / "etc/nginx/smite-xhttp-routes"
            route_dir.rmdir()
            sock_dir = root / "run/u-opti/smite"
            sock = sock_dir / "xhttp-broker.sock"
            original_lstat = Path.lstat
            def lstat_with_mocked_service_socket(path):
                if path == sock_dir:
                    return SimpleNamespace(st_mode=stat.S_IFDIR | 0o750,
                                           st_uid=0, st_gid=PEER_GID)
                if path == sock:
                    return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660,
                                           st_uid=0, st_gid=PEER_GID)
                return original_lstat(path)
            with patch.object(Path, "lstat", lstat_with_mocked_service_socket):
                result = provisioner.activate(root=root, runner=fake_systemctl)
            self.assertEqual(result["SERVICE_ACTIVATION"], "PASS_ACTIVE_PERSISTENT")
            self.assertEqual(result["TRUSTED_GRANTS"], "UNCHANGED")
            self.assertEqual(result["LIVE_ROUTE_CHANGE"], "NO")
            self.assertEqual(calls, [
                ("group", "u-opti-smite-peer"), ("group", "1348"),
                ("daemon-reload",), ("enable", provisioner.SERVICE_NAME),
                ("reset-failed", provisioner.SERVICE_NAME),
                ("start", provisioner.SERVICE_NAME),
                ("is-enabled", provisioner.SERVICE_NAME),
                ("is-active", provisioner.SERVICE_NAME),
            ])
            self.assertEqual(list((root / "etc/u-opti/smite/route-grants").iterdir()), [])
            route_dir = root / "etc/nginx/smite-xhttp-routes"
            self.assertTrue(route_dir.is_dir())
            self.assertEqual(list(route_dir.iterdir()), [])
            self.assertEqual(list((root / "etc/nginx").glob("**/*.conf")), [])
            repaired_unit = service.read_text()
            self.assertIn("ReadWritePaths=-/run/lock/u-opti-smite-engine.lock", repaired_unit)
            self.assertIn("ReadWritePaths=-/run/lock/smite-xhttp-nginx-route.lock", repaired_unit)
            self.assertNotIn("ReadWritePaths=/run/lock/u-opti-smite-engine.lock", repaired_unit)
            self.assertNotIn("ReadWritePaths=/run/lock/smite-xhttp-nginx-route.lock", repaired_unit)

    def test_activation_holds_if_systemd_does_not_confirm_active(self):
        repo = Path(__file__).resolve().parents[1]
        source_dir = repo / "modules"
        provisioner_path = source_dir / "smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_activation_hold_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = provisioner
        spec.loader.exec_module(provisioner)

        with tempfile.TemporaryDirectory(prefix="uopti-broker-activation-hold-") as raw_root:
            root = Path(raw_root)
            root.chmod(0o700)
            nginx_config = root / "etc/nginx"
            nginx_config.mkdir(parents=True, mode=0o755)
            nginx_config.chmod(0o755)
            target_modules = root / "usr/local/lib/u-opti/modules"
            target_modules.mkdir(parents=True, mode=0o755)
            target_modules.chmod(0o755)
            broker_target = target_modules / "smite-rc5-xhttp-root-broker.py"
            broker_target.write_bytes((source_dir / broker_target.name).read_bytes())
            broker_target.chmod(0o644)
            provisioner.provision(peer_gid=PEER_GID, root=root, source_dir=source_dir,
                                  instance_id=INSTANCE)
            def failed_status(argv, **kwargs):
                if argv[0] == "getent":
                    return SimpleNamespace(returncode=0,
                                           stdout="u-opti-smite-peer:x:1348:\n",
                                           stderr="")
                output = "failed\n" if argv[1] == "is-active" else "enabled\n"
                return SimpleNamespace(returncode=0, stdout=output, stderr="")
            with self.assertRaisesRegex(provisioner.ProvisionHold,
                                        "BROKER_SYSTEMD_VERIFICATION_FAILED"):
                provisioner.activate(root=root, runner=failed_status)

    def test_activation_creates_missing_dedicated_peer_group_and_holds_on_collision(self):
        repo = Path(__file__).resolve().parents[1]
        provisioner_path = repo / "modules/smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_peer_group_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = provisioner
        spec.loader.exec_module(provisioner)

        calls = []
        def mock_runner(argv, **kwargs):
            calls.append(tuple(argv))
            if argv[0] != "getent":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            key = argv[2]
            if key == "u-opti-smite-peer":
                found = any(call[:2] == ("groupadd", "--system") for call in calls)
                output = "u-opti-smite-peer:x:1348:\n" if found else ""
                return SimpleNamespace(returncode=0 if found else 2,
                                       stdout=output, stderr="")
            found = (key == "1348" and any(
                call[:2] == ("groupadd", "--system") for call in calls
            ))
            output = "u-opti-smite-peer:x:1348:\n" if found else ""
            return SimpleNamespace(returncode=0 if found else 2,
                                   stdout=output, stderr="")

        provisioner._ensure_peer_group(1348, mock_runner)
        self.assertIn(("groupadd", "--system", "--gid", "1348", "u-opti-smite-peer"), calls)

        def collision_runner(argv, **kwargs):
            if argv[0] == "getent":
                return SimpleNamespace(returncode=0,
                                       stdout="docker:x:1348:\n", stderr="")
            raise AssertionError("group collision must hold without mutation")

        with self.assertRaisesRegex(provisioner.ProvisionHold,
                                    "BROKER_PEER_GROUP_COLLISION"):
            provisioner._ensure_peer_group(1348, collision_runner)

    def test_root_operator_grant_install_and_revoke_are_exact_and_durable(self):
        repo = Path(__file__).resolve().parents[1]
        provisioner_path = repo / "modules/smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_grant_approval_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = provisioner
        spec.loader.exec_module(provisioner)

        with tempfile.TemporaryDirectory(prefix="uopti-broker-grant-approval-") as raw_root:
            root = Path(raw_root)
            root.chmod(0o700)
            grants = root / "etc/u-opti/smite/route-grants"
            grants.mkdir(parents=True, mode=0o700)
            grants.chmod(0o700)
            (root / "etc/u-opti/smite").chmod(0o700)
            proposal = {
                "ir_node": "node-ir-0001", "kh_node": "node-kh-0001",
                "owner": "trial-frp-45121", "child": "trial-frp-49328",
                "lease": "lease-49328-00001", "port": 49328,
                "path": "/49328/sso", "owner_proof_sha256": "a" * 64,
                "kh_inventory_sha256": "b" * 64,
            }
            with self.assertRaisesRegex(provisioner.ProvisionHold,
                                        "BROKER_GRANT_CHILD_CONFIRMATION_MISMATCH"):
                provisioner.install_grant(
                    proposal, confirmed_child="trial-frp-45121", root=root,
                )
            self.assertEqual(list(grants.iterdir()), [])

            result = provisioner.install_grant(
                proposal, confirmed_child=proposal["child"], root=root,
            )
            target = grants / "trial-frp-49328.json"
            self.assertEqual(result["TRUSTED_GRANT"], "INSTALLED_ROOT_OPERATOR_APPROVED")
            self.assertEqual(result["EVIDENCE_VERIFICATION"], "OPERATOR_ASSERTED")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            stored = json.loads(target.read_text())
            self.assertEqual(stored, proposal)
            with self.assertRaisesRegex(provisioner.ProvisionHold,
                                        "BROKER_TARGET_EXISTS_REQUIRES_REVIEW"):
                provisioner.install_grant(
                    proposal, confirmed_child=proposal["child"], root=root,
                )
            self.assertEqual(json.loads(target.read_text()), proposal)

            revoked = provisioner.revoke_grant(proposal["child"], root=root)
            self.assertEqual(revoked["TRUSTED_GRANT"], "REVOKED")
            self.assertFalse(target.exists())

    def test_root_operator_grant_rejects_bad_route_hashes_and_untrusted_directory(self):
        repo = Path(__file__).resolve().parents[1]
        provisioner_path = repo / "modules/smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_grant_rejection_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = provisioner
        spec.loader.exec_module(provisioner)
        proposal = {
            "ir_node": "node-ir-0001", "kh_node": "node-kh-0001",
            "owner": "trial-frp-45121", "child": "trial-frp-49328",
            "lease": "lease-49328-00001", "port": 49328,
            "path": "/49328/sso", "owner_proof_sha256": "a" * 64,
            "kh_inventory_sha256": "b" * 64,
        }
        for changes, expected in (
            ({"port": 7000}, "BROKER_GRANT_INVALID_ROUTE"),
            ({"path": "/49328/../../etc"}, "BROKER_GRANT_INVALID_ROUTE"),
            ({"kh_inventory_sha256": "bad"}, "BROKER_GRANT_INVALID_EVIDENCE_HASH"),
        ):
            bad = {**proposal, **changes}
            with self.subTest(expected=expected, changes=changes):
                with self.assertRaisesRegex(provisioner.ProvisionHold, expected):
                    provisioner._checked_grant(bad, confirmed_child=proposal["child"])

        with tempfile.TemporaryDirectory(prefix="uopti-broker-grant-dir-") as raw_root:
            root = Path(raw_root)
            root.chmod(0o700)
            grants = root / "etc/u-opti/smite/route-grants"
            grants.mkdir(parents=True, mode=0o755)
            grants.chmod(0o755)
            with self.assertRaisesRegex(provisioner.ProvisionHold,
                                        "BROKER_GRANT_DIRECTORY_UNTRUSTED"):
                provisioner.install_grant(
                    proposal, confirmed_child=proposal["child"], root=root,
                )

    def test_interactive_root_approval_builds_panel_compatible_evidence_digests(self):
        repo = Path(__file__).resolve().parents[1]
        provisioner_path = repo / "modules/smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_grant_prompt_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = provisioner
        spec.loader.exec_module(provisioner)
        answers = iter((
            "node-ir-0001", "node-kh-0001", "trial-frp-45121",
            "trial-frp-49328", "lease-49328-00001", "49328", "/49328/sso",
            "APPROVE trial-frp-49328",
        ))
        with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
            grant, child = provisioner._interactive_grant()
        self.assertEqual(child, "trial-frp-49328")
        owner_facts = {"tunnel_id": "trial-frp-45121", "control_port": 7000,
                       "proxy_port": 49328}
        inbound_facts = {"port": 49328, "listen": "127.0.0.1",
                         "protocol": "vless", "network": "xhttp",
                         "path": "/49328/sso", "enabled": True}
        digest = lambda value: hashlib.sha256(json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")).hexdigest()
        self.assertEqual(grant["owner_proof_sha256"], digest(owner_facts))
        self.assertEqual(grant["kh_inventory_sha256"], digest(inbound_facts))

    def test_interactive_root_approval_requires_exact_child_phrase(self):
        repo = Path(__file__).resolve().parents[1]
        provisioner_path = repo / "modules/smite-rc5-xhttp-broker-provision.py"
        spec = importlib.util.spec_from_file_location("broker_grant_prompt_hold_test", provisioner_path)
        provisioner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = provisioner
        spec.loader.exec_module(provisioner)
        answers = iter((
            "node-ir-0001", "node-kh-0001", "trial-frp-45121",
            "trial-frp-49328", "lease-49328-00001", "49328", "/49328/sso",
            "APPROVE some-other-child",
        ))
        with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
            with self.assertRaisesRegex(provisioner.ProvisionHold,
                                        "BROKER_GRANT_APPROVAL_NOT_CONFIRMED"):
                provisioner._interactive_grant()


if __name__ == "__main__":
    unittest.main()
